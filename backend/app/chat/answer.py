"""Miles — the answering half of the chat loop.

One retrieve-then-generate step, no agent graph: the retriever picks the
fact cards, the model is allowed to phrase them and nothing else. That is the
same contract the planner works under (the LLM selects and phrases, the
grounding store owns the facts), applied to conversation.

Two safety nets keep an answer coming back no matter what:
- history is hard-capped server-side, so a long conversation can never push
  the request past the free tier's per-minute token budget;
- if the model call fails outright, the reply falls back to quoting the top
  chunks verbatim and says so via `degraded`.
"""

import re
from typing import Literal, Protocol

from pydantic import BaseModel, Field

from ..config import Settings
from ..orchestrator.llm import GroqLLM
from .corpus import Chunk
from .retriever import TOP_K, Retrieved, Retriever

MAX_HISTORY_EXCHANGES = 3  # user+assistant pairs kept from the client's history
MAX_HISTORY_CHARS = 600  # per message; long pastes never dominate the budget
MAX_ANSWER_TOKENS = 350

CONTEXT_HEADER = "Context from the traveller's plan:"
QUESTION_HEADER = "Question:"

SYSTEM_PROMPT = """You are Miles, the travel assistant for the "Where To" trip \
planner. You answer questions about ONE already-generated trip plan.

Rules:
- Answer ONLY from the numbered context below. Never add facts from your own \
knowledge — not prices, not opening hours, not travel advice.
- Cite constantly. EVERY sentence that states a fact from the plan MUST end \
with the bracketed number(s) of the card(s) it came from — for example: "Your \
return flight lands at 11:45 and costs INR 43,168 [2]." Never write a factual \
sentence without its [n]; use several markers when one sentence draws on \
several cards.
- If the context does not contain the answer, say so plainly ("That isn't in \
your plan") and suggest what you can answer instead. Never guess.
- You cannot change the plan. If asked to move, add, swap or remove anything, \
explain warmly that you can only answer questions about the trip as planned.
- Entry prices and meal costs in the context are researched estimates, not \
booked prices — say so when you quote them.
- Keep it short: two or three sentences, warm and practical. No markdown \
headings, no bullet lists unless you are listing a day's stops."""

# gpt-oss reasoning models sometimes emit full-width 【n】 instead of ASCII [n];
# accept both so real citations aren't silently dropped. Matches normalize to
# ASCII on substitution in _resolve_citations.
_CITE = re.compile(r"[\[【](\d+)[\]】]")


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatCitation(BaseModel):
    chunk_id: str
    label: str
    type: str
    day: int | None = None
    source_url: str | None = None


class ChatReply(BaseModel):
    answer: str
    citations: list[ChatCitation] = Field(default_factory=list)
    degraded: bool = False


class ChatLLM(Protocol):
    def converse(self, messages: list[dict], *, max_tokens: int, temperature: float) -> str: ...


def build_chat_llm(settings: Settings) -> ChatLLM:
    """Groq on `chat_model` — a different model from the orchestrator's, so
    Miles draws on its own per-model rate budget. Demo mode gets the scripted
    stand-in and stays keyless."""
    if settings.fake_apis or not settings.groq_api_key:
        return ScriptedChatLLM()
    return GroqLLM(settings.groq_api_key, settings.chat_model)


def answer_question(
    question: str,
    history: list[ChatMessage],
    retriever: Retriever,
    llm: ChatLLM,
    *,
    top_k: int = TOP_K,
) -> ChatReply:
    retrieved = retriever.search(question, k=top_k)
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages += [{"role": m.role, "content": m.content[:MAX_HISTORY_CHARS]} for m in _trim(history)]
    messages.append({"role": "user", "content": _prompt(question, retrieved)})

    try:
        raw = llm.converse(messages, max_tokens=MAX_ANSWER_TOKENS, temperature=0.2)
    except Exception:  # provider down, rate-limited past its retries, bad key
        return _extractive(retrieved)

    answer, citations = _resolve_citations(raw.strip(), retrieved)
    if not answer:
        return _extractive(retrieved)
    return ChatReply(answer=answer, citations=citations, degraded=retriever.degraded_vectors)


def _trim(history: list[ChatMessage]) -> list[ChatMessage]:
    """Keep only the last few turns. Summarizing older history would cost an
    extra model call per question — the thing RAG is here to avoid."""
    return history[-(MAX_HISTORY_EXCHANGES * 2) :]


def _prompt(question: str, retrieved: list[Retrieved]) -> str:
    if not retrieved:
        cards = "(no matching cards were found in this trip's plan)"
    else:
        cards = "\n\n".join(
            f"[{i}] {r.chunk.label}\n{r.chunk.text}" for i, r in enumerate(retrieved, start=1)
        )
    return f"{CONTEXT_HEADER}\n\n{cards}\n\n{QUESTION_HEADER} {question}"


def _resolve_citations(answer: str, retrieved: list[Retrieved]) -> tuple[str, list[ChatCitation]]:
    """Renumber the model's [n] markers to the order it actually used them, so
    the citation chips the client renders line up one-for-one with the text.
    Markers pointing at cards that were never supplied are dropped."""
    used: list[int] = []

    def renumber(match: re.Match) -> str:
        index = int(match.group(1)) - 1
        if not 0 <= index < len(retrieved):
            return ""
        if index not in used:
            used.append(index)
        return f"[{used.index(index) + 1}]"

    return _CITE.sub(renumber, answer).strip(), [_cite(retrieved[i].chunk) for i in used]


def _cite(chunk: Chunk) -> ChatCitation:
    return ChatCitation(
        chunk_id=chunk.id,
        label=chunk.label,
        type=chunk.type,
        day=chunk.day,
        source_url=chunk.source_url,
    )


EXTRACTIVE_MAX_CARDS = 3


def _extractive(retrieved: list[Retrieved]) -> ChatReply:
    """No model, no invention: hand back the retrieved cards themselves."""
    if not retrieved:
        return ChatReply(
            answer="I couldn't reach my language model, and I didn't find anything in "
            "your plan matching that question. Try asking about your flights, hotel, "
            "or a specific day.",
            degraded=True,
        )
    cards = retrieved[:EXTRACTIVE_MAX_CARDS]
    lines = [
        f"[{i}] {r.chunk.label} — {r.chunk.text}" for i, r in enumerate(cards, start=1)
    ]
    return ChatReply(
        answer="I couldn't reach my language model just now, so here's what your plan "
        "says, straight from the source:\n\n" + "\n\n".join(lines),
        citations=[_cite(r.chunk) for r in cards],
        degraded=True,
    )


# --------------------------------------------------------- scripted stand-in

_EDIT_INTENT = re.compile(
    r"\b(move|swap|replace|reschedule|rebook|cancel|add|remove|delete|change|"
    r"instead of|book me|make it)\b"
)
_STOPWORDS = frozenset(
    """about after also anything are but can could does doing done for from
    have here how into just like make many more most much need not our out
    should some tell that the their them then there these they this those
    trip trips very what when where which while will with would you your"""
    .split()
)


class ScriptedChatLLM:
    """Deterministic stand-in for the Groq chat model: powers FAKE_APIS demos
    and the test suite with zero keys and zero network. It reads the same
    prompt the real model gets and answers from the first card, so the whole
    endpoint — retrieval, citation renumbering, refusals — is exercised."""

    def converse(self, messages: list[dict], *, max_tokens: int = MAX_ANSWER_TOKENS, temperature: float = 0.2) -> str:
        prompt = messages[-1]["content"]
        context, _, question = prompt.rpartition(f"\n\n{QUESTION_HEADER} ")

        if _EDIT_INTENT.search(question.lower()):
            return (
                "I can only answer questions about this trip as it's planned — I can't "
                "move things around or rebook anything. Ask me what's scheduled, what "
                "it costs, or why something didn't make the cut."
            )

        content_words = {
            w for w in re.findall(r"[a-z0-9]+", question.lower())
            if len(w) > 3 and w not in _STOPWORDS
        }
        haystack = context.lower()
        no_cards = "[1] " not in context
        if no_cards or (content_words and not any(w in haystack for w in content_words)):
            return (
                "That isn't in your plan, so I'd only be guessing. I can tell you about "
                "your flights, your hotel, any day's schedule, the budget, or why a "
                "sight didn't make the cut."
            )

        # Cards are "\n\n"-separated; part 0 is the header, part 1 is card [1].
        body = context.split("\n\n")[1].split("\n", 1)[-1].strip()
        sentence = body.split(". ")[0].rstrip(".")
        return f"{sentence}. [1]"
