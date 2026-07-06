"""LLM interface for the tool-calling loop.

`GroqLLM` is the real thing (OpenAI-compatible tool calling, model id from
config). `FakeLLM` is a scripted policy that walks the exact same loop and
tool contracts — it powers tests, the zero-cost FAKE_APIS demo mode, and the
graceful-degradation fallback when the real model can't produce a valid plan.
"""

import json
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
    def __init__(self, api_key: str, model: str):
        from groq import Groq

        self._client = Groq(api_key=api_key)
        self.model = model

    def chat(self, messages: list[dict], tools: list[dict]) -> LLMReply:
        response = self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            tools=tools,
            tool_choice="auto",
            temperature=0.2,
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
                "commentary": "Cheapest workable flights, the best-rated stay, and your interests packed day by day.",
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
