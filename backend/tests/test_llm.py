"""GroqLLM retry-branch unit tests. A fake client injected via `_client` drives
the retry loop with no real key or network; backoff_base=0 keeps it instant."""

from types import SimpleNamespace

import httpx
import pytest
from groq import BadRequestError

from app.orchestrator.llm import GroqLLM


def _bad_request(code: str) -> BadRequestError:
    """A Groq 400 shaped like the real thing — the error code lives in the body,
    which the SDK also echoes into the message string."""
    body = {"error": {"message": "Failed to parse tool call arguments as JSON", "code": code}}
    req = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    resp = httpx.Response(400, request=req, json=body)
    return BadRequestError(f"Error code: 400 - {body}", response=resp, body=body)


def _tool_call_response():
    """A minimal valid chat.completions response carrying one tool call."""
    func = SimpleNamespace(name="finalize_plan", arguments='{"poi_ids": []}')
    tc = SimpleNamespace(id="call_1", function=func)
    msg = SimpleNamespace(content=None, tool_calls=[tc])
    return SimpleNamespace(choices=[SimpleNamespace(message=msg)], usage=SimpleNamespace(total_tokens=10))


class _ScriptedClient:
    """Stands in for groq.Groq: each create() pops the next scripted item —
    exceptions are raised, anything else is returned."""

    def __init__(self, script):
        self._script = list(script)
        self.calls = 0
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls += 1
        item = self._script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _llm(script) -> GroqLLM:
    llm = GroqLLM(api_key="test", model="x", max_retries=3, backoff_base=0.0, max_sleep=0.0)
    llm._client = _ScriptedClient(script)
    return llm


def test_tool_use_failed_400_is_retried_then_succeeds():
    llm = _llm([_bad_request("tool_use_failed"), _tool_call_response()])
    reply = llm.chat(messages=[], tools=[])
    assert llm._client.calls == 2  # one malformed-JSON failure, one clean retry
    assert [c.name for c in reply.tool_calls] == ["finalize_plan"]
    assert llm.total_tokens == 10  # usage still accounted on the successful call


def test_non_tool_use_failed_400_is_not_retried():
    llm = _llm([_bad_request("json_validate_failed"), _tool_call_response()])
    with pytest.raises(BadRequestError):
        llm.chat(messages=[], tools=[])
    assert llm._client.calls == 1  # genuine bad request re-raised immediately


def test_tool_use_failed_400_gives_up_after_max_retries():
    # Persistent malformed JSON: retried up to the cap, then propagates.
    llm = _llm([_bad_request("tool_use_failed")] * 5)
    with pytest.raises(BadRequestError):
        llm.chat(messages=[], tools=[])
    assert llm._client.calls == llm.max_retries + 1  # initial attempt + retries
