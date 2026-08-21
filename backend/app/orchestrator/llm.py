"""LLM interface for the tool-calling loop.

`GroqLLM` is the real thing (OpenAI-compatible tool calling, model id from
config). `FakeLLM` is a scripted policy that walks the exact same loop and
tool contracts — it powers tests, the zero-cost FAKE_APIS demo mode, and the
graceful-degradation fallback when the real model can't produce a valid plan.
"""

import json
import re
import time
from dataclasses import dataclass, field


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class LLMReply:
    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)


class GroqLLM:
    def __init__(
        self,
        api_key: str,
        model: str,
        max_retries: int = 3,
        backoff_base: float = 1.0,
        max_sleep: float = 22.0,
    ):
        from groq import Groq

        self._client = Groq(api_key=api_key)
        self.model = model
        self.total_tokens = 0  # cumulative prompt+completion, for cost visibility
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.max_sleep = max_sleep

    # reasoning_effort="low": gpt-oss is a reasoning model whose default
    # (medium) chain-of-thought filled the entire output-token budget on every
    # call — pushing tokens/minute past the free-tier cap and, in the tool
    # loop, truncating the tool call so it never finalized. "low" keeps the
    # output small; reasoning comes back in a separate field, so content and
    # tool_calls parsing is unaffected.
    def _create_with_retry(self, **kwargs):
        """Call the Groq completions API, retrying on 429 (waiting out the
        per-minute token window) and on transient 5xx/connection errors."""
        from groq import APIConnectionError, InternalServerError, RateLimitError

        response = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self._client.chat.completions.create(**kwargs)
                break
            except RateLimitError as exc:  # 429 TPM: wait out the window, retry
                if attempt == self.max_retries:
                    raise
                time.sleep(self._retry_after(exc, attempt))
            except (APIConnectionError, InternalServerError) as exc:  # transient
                if attempt == self.max_retries:
                    raise
                time.sleep(min(self.backoff_base * (2**attempt), self.max_sleep))

        if response.usage is not None:
            self.total_tokens += response.usage.total_tokens
        return response

    def chat(self, messages: list[dict], tools: list[dict]) -> LLMReply:
        response = self._create_with_retry(
            model=self.model,
            messages=messages,
            tools=tools,
            tool_choice="auto",
            temperature=0.2,
            max_tokens=600,  # replies are tool calls or short prose
            reasoning_effort="low",
        )
        msg = response.choices[0].message
        calls = []
        for tc in msg.tool_calls or []:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            calls.append(ToolCall(id=tc.id, name=tc.function.name, arguments=args))
        return LLMReply(content=msg.content, tool_calls=calls)

    def converse(self, messages: list[dict], *, max_tokens: int = 350, temperature: float = 0.2) -> str:
        """Plain (non-tool) multi-message completion with the same retry as
        chat(). The chat assistant answers from retrieved text, so it needs the
        message history but never the toolbox."""
        response = self._create_with_retry(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            reasoning_effort="low",
        )
        return response.choices[0].message.content or ""

    def complete(self, system: str, user: str, *, max_tokens: int = 900, temperature: float = 0.1) -> str:
        """Single system+user completion. Used by the research-brief and
        cost-estimate steps so they survive the per-minute token crunch
        instead of silently degrading to heuristics."""
        return self.converse(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=max_tokens,
            temperature=temperature,
        )

    def _retry_after(self, exc: Exception, attempt: int) -> float:
        """Seconds to wait before retrying a 429 — prefer the server's
        Retry-After header, then the 'try again in Xs' hint in the error body,
        then exponential backoff. Capped so one turn can't stall the plan."""
        resp = getattr(exc, "response", None)
        if resp is not None:
            header = resp.headers.get("retry-after")
            if header:
                try:
                    return min(float(header), self.max_sleep)
                except ValueError:
                    pass
        match = re.search(r"try again in ([\d.]+)s", str(exc))
        if match:
            return min(float(match.group(1)) + 0.5, self.max_sleep)
        return min(self.backoff_base * (2**attempt), self.max_sleep)


class FakeLLM:
    """Deterministic agent policy: cheapest flights, best-rated hotel, POIs
    ranked by rating. `invalid_first=True` sends one bogus finalize first, to
    exercise the validation-retry path."""

    def __init__(self, invalid_first: bool = False):
        self.invalid_first = invalid_first
        self._step = 0
        self._outbound_id: str | None = None
        self._return_id: str | None = None
        self._hotel_id: str | None = None
        self._poi_ids: list[str] = []
        self._attractions_searched = False

    def chat(self, messages: list[dict], tools: list[dict]) -> LLMReply:
        last_tool = _last_tool_result(messages)
        self._step += 1
        if self._step > 12:  # safety: end the conversation
            return LLMReply(content="done")

        if self._outbound_id is None:
            if last_tool and last_tool["name"] == "search_flights":
                options = _ok(last_tool)
                if options:
                    self._outbound_id = min(options, key=lambda o: o["price"])["id"]
                    return _call("get_return_flights", {"outbound_flight_id": self._outbound_id})
            return _call("search_flights", {})

        if self._return_id is None:
            options = _ok(last_tool) if last_tool and last_tool["name"] == "get_return_flights" else []
            if options:
                self._return_id = min(options, key=lambda o: o["price"])["id"]
            else:
                self._return_id = ""  # source failed; carry on
            return _call("search_hotels", {})

        if self._hotel_id is None:
            options = _ok(last_tool) if last_tool and last_tool["name"] == "search_hotels" else []
            rated = [o for o in options if o.get("rating") is not None]
            self._hotel_id = (max(rated, key=lambda o: o["rating"])["id"] if rated else options[0]["id"] if options else "")
            return _call("search_attractions", {})

        if not self._attractions_searched:
            if not (last_tool and last_tool["name"] == "search_attractions"):
                return _call("search_attractions", {})
            self._attractions_searched = True
            options = _ok(last_tool)
            self._poi_ids = [o["id"] for o in sorted(options, key=lambda o: -(o.get("rating") or 0))]
            if self.invalid_first:
                self.invalid_first = False
                return _call(
                    "finalize_plan",
                    {
                        "outbound_flight_id": "flight_out_999",
                        "return_flight_id": self._return_id or None,
                        "hotel_id": self._hotel_id or None,
                        "poi_ids": ["nope_0"],
                        "commentary": "bogus",
                    },
                )
            return self._finalize()

        if last_tool and last_tool["name"] == "finalize_plan" and "error" in (last_tool["payload"] or {}):
            return self._finalize()
        return LLMReply(content="Trip planned.")

    def _finalize(self) -> LLMReply:
        return _call(
            "finalize_plan",
            {
                "outbound_flight_id": self._outbound_id,
                "return_flight_id": self._return_id or None,
                "hotel_id": self._hotel_id or None,
                "poi_ids": self._poi_ids,
                "commentary": "Cheapest workable flights, the best-rated stay, and the city's must-see sights packed day by day.",
            },
        )


def _call(name: str, args: dict) -> LLMReply:
    return LLMReply(tool_calls=[ToolCall(id=f"call_{name}", name=name, arguments=args)])


def _last_tool_result(messages: list[dict]) -> dict | None:
    """Return {'name', 'payload'} for the most recent tool result message."""
    name_by_id: dict[str, str] = {}
    for m in messages:
        for tc in m.get("tool_calls") or []:
            name_by_id[tc["id"]] = tc["function"]["name"]
    for m in reversed(messages):
        if m.get("role") == "tool":
            try:
                payload = json.loads(m.get("content") or "null")
            except json.JSONDecodeError:
                payload = None
            return {"name": name_by_id.get(m.get("tool_call_id", ""), ""), "payload": payload}
    return None


def _ok(tool_result: dict | None) -> list[dict]:
    payload = (tool_result or {}).get("payload")
    if isinstance(payload, dict):
        return payload.get("options") or []
    return []
