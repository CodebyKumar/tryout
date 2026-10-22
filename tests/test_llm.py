"""The Groq client against a fake Groq server: no request is wasted on a model known to be rate limited."""

import json

import httpx
import pytest

from backend.agents.turn_agent import TurnOut
from backend.integrations.llm import GroqLLM, LLMError, _retry_after

OK = '{"ack": "Ok."}'


def groq(script: dict[str, list], models=("m1", "m2")):
    """A client whose server answers each model from its script in order: a str is an answer, an int a status code,
    a (429, seconds) tuple a rate limit. Every request is recorded as (model, body)."""
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append((body["model"], body))
        step = script[body["model"]].pop(0)
        if isinstance(step, tuple):
            return httpx.Response(step[0], headers={"retry-after": str(step[1])}, text="rate limit")
        if isinstance(step, int):
            return httpx.Response(step, text="bad request")
        usage = {"prompt_tokens": 100, "completion_tokens": 10, "prompt_tokens_details": {"cached_tokens": 80}}
        return httpx.Response(200, json={"choices": [{"message": {"content": step}}], "usage": usage})

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://groq")
    return GroqLLM(models={"turn": list(models)}, http=http), requests


async def ask(llm, timeout=15):
    return await llm.json(agent="turn_agent", role="turn", system="s", user="u", output=TurnOut, timeout=timeout)


async def test_repair_counts_both_calls():
    llm, requests = groq(
        {"m1": ['{"ack": "Ok.", "user_wants_stop": "maybe"}', '{"ack": "Ok.", "user_wants_stop": true}']}
    )
    out, usage = await ask(llm)
    assert (
        out.user_wants_stop is True and len(requests) == 2 and "not valid" in requests[1][1]["messages"][-1]["content"]
    )
    assert (usage.calls, usage.prompt_tokens, usage.cached_tokens) == (2, 200, 160)


async def test_rate_limited_model_is_skipped_until_it_clears():
    llm, requests = groq({"m1": [(429, 60)], "m2": [OK, OK]})
    await ask(llm)
    await ask(llm)  # m1 is still cooling down: no request is sent to it
    assert [m for m, _ in requests] == ["m1", "m2", "m2"]


async def test_no_request_when_every_model_is_limited_past_the_budget():
    llm, requests = groq({"m1": [(429, 60)], "m2": [(429, 60)]})
    with pytest.raises(LLMError):
        await ask(llm)
    with pytest.raises(LLMError):
        await ask(llm)
    assert len(requests) == 2  # the second call sent nothing


async def test_short_limit_is_waited_out():
    llm, requests = groq({"m1": [(429, 0.05), OK], "m2": [(429, 0.05)]})
    out, _ = await ask(llm)
    assert out.ack == "Ok." and [m for m, _ in requests] == ["m1", "m2", "m1"]


async def test_rejected_optional_parameter_is_remembered():
    llm, requests = groq({"openai/gpt-oss-20b": [400, OK, OK]}, models=("openai/gpt-oss-20b",))
    await ask(llm)
    await ask(llm)
    sent = ["reasoning_effort" in body for _, body in requests]
    assert sent == [True, False, False]  # one rejected request in total, not one per call


def test_daily_limit_message_is_parsed():
    resp = httpx.Response(429, text="Rate limit reached. Please try again in 7m12.5s.")
    assert _retry_after(resp) == pytest.approx(432.5)
