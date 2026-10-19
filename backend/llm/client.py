"""One LLM entry point for every agent.

Agents call `llm.json(agent=..., role=..., system=..., user=...)` and get a dict back. The role picks a
fallback chain of models (config.MODELS); rate limits and provider errors move to the next model.
"""

import asyncio
import json
import logging
import re
import time
from typing import Callable, Protocol

import httpx

from .. import config
from ..models import Usage

log = logging.getLogger("llm")


class LLMError(RuntimeError):
    pass


class LLM(Protocol):
    async def json(self, *, agent: str, role: str, system: str, user: str,
                   max_tokens: int = 800, temperature: float = 0.3) -> tuple[dict, Usage]: ...


def parse_json(text: str) -> dict:
    """Defensive JSON parsing: strips code fences and surrounding prose, tolerates trailing commas."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object in response")
    body = re.sub(r",\s*([}\]])", r"\1", text[start:end + 1])
    data = json.loads(body)
    if not isinstance(data, dict):
        raise ValueError("JSON is not an object")
    return data


def _extra_params(model: str) -> dict:
    # Keep reasoning short on reasoning models: latency matters more than depth for these tasks.
    if "gpt-oss" in model:
        return {"reasoning_effort": "low"}
    if "qwen3" in model:
        return {"reasoning_effort": "none"}
    return {}


MAX_RATE_LIMIT_WAIT = 10.0


def _retry_after(resp: httpx.Response) -> float | None:
    if resp.status_code != 429:
        return None
    if resp.headers.get("retry-after"):
        try:
            return float(resp.headers["retry-after"])
        except ValueError:
            pass
    m = re.search(r"try again in ([\d.]+)(ms|s)", resp.text)
    if not m:
        return None
    return float(m.group(1)) / (1000 if m.group(2) == "ms" else 1)


class GroqLLM:
    def __init__(self, api_key: str = config.GROQ_API_KEY, base_url: str = config.GROQ_BASE_URL,
                 models: dict[str, list[str]] = config.MODELS, timeout: float = 30):
        if not api_key:
            raise LLMError("GROQ_API_KEY is not set. Add it to .env")
        self.models = models
        self._opts = {"base_url": base_url, "timeout": timeout, "headers": {"Authorization": f"Bearer {api_key}"}}
        self._clients: dict[int, httpx.AsyncClient] = {}

    @property
    def client(self) -> httpx.AsyncClient:
        # httpx clients are bound to an event loop; keep one per loop (server, tests and scripts use different loops).
        loop_id = id(asyncio.get_running_loop())
        if loop_id not in self._clients:
            self._clients[loop_id] = httpx.AsyncClient(**self._opts)
        return self._clients[loop_id]

    async def _call(self, model: str, messages: list[dict], max_tokens: int, temperature: float) -> dict:
        body = {"model": model, "messages": messages, "temperature": temperature,
                "max_completion_tokens": max_tokens, "response_format": {"type": "json_object"},
                **_extra_params(model)}
        resp = await self.client.post("/chat/completions", json=body)
        for _ in range(2):
            # Per-minute token limits on free tiers clear in seconds: wait and retry before falling back.
            wait = _retry_after(resp)
            if wait is None or wait > MAX_RATE_LIMIT_WAIT:
                break
            log.info("rate limited on %s, waiting %.1fs", model, wait)
            await asyncio.sleep(wait + 0.2)
            resp = await self.client.post("/chat/completions", json=body)
        if resp.status_code == 400 and _extra_params(model):
            # Provider rejected an optional parameter: retry once with the plain request.
            for k in _extra_params(model):
                body.pop(k, None)
            resp = await self.client.post("/chat/completions", json=body)
        if resp.status_code >= 400:
            raise LLMError(f"{model}: HTTP {resp.status_code} {resp.text[:300]}")
        return resp.json()

    async def json(self, *, agent: str, role: str, system: str, user: str,
                   max_tokens: int = 800, temperature: float = 0.3) -> tuple[dict, Usage]:
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        errors = []
        for model in self.models[role]:
            t0 = time.perf_counter()
            try:
                data = await self._call(model, messages, max_tokens, temperature)
                content = data["choices"][0]["message"].get("content") or ""
                try:
                    result = parse_json(content)
                except ValueError as e:
                    # One repair attempt on the same model with the parse error.
                    repair = messages + [{"role": "assistant", "content": content},
                                         {"role": "user", "content": f"That was not valid JSON ({e}). Return only the JSON object."}]
                    data = await self._call(model, repair, max_tokens, temperature)
                    result = parse_json(data["choices"][0]["message"].get("content") or "")
            except (LLMError, httpx.HTTPError, ValueError, KeyError) as e:
                log.warning("agent=%s model=%s failed: %s", agent, model, e)
                errors.append(str(e))
                continue
            u = data.get("usage") or {}
            usage = Usage(agent=agent, model=model,
                          prompt_tokens=u.get("prompt_tokens", 0),
                          completion_tokens=u.get("completion_tokens", 0),
                          cached_tokens=(u.get("prompt_tokens_details") or {}).get("cached_tokens", 0),
                          latency_ms=int((time.perf_counter() - t0) * 1000))
            log.info("agent=%s model=%s in=%s out=%s %sms", agent, model,
                     usage.prompt_tokens, usage.completion_tokens, usage.latency_ms)
            return result, usage
        raise LLMError(f"All models failed for {agent}: {' | '.join(errors)}")


class FakeLLM:
    """Test double: handlers[agent](system, user) -> dict."""

    def __init__(self, handlers: dict[str, Callable[[str, str], dict]]):
        self.handlers = handlers
        self.calls: list[tuple[str, str]] = []

    async def json(self, *, agent: str, role: str, system: str, user: str,
                   max_tokens: int = 800, temperature: float = 0.3) -> tuple[dict, Usage]:
        self.calls.append((agent, user))
        return self.handlers[agent](system, user), Usage(agent=agent, model="fake")


_default: LLM | None = None


def get_llm() -> LLM:
    global _default
    if _default is None:
        _default = GroqLLM()
    return _default


def set_llm(llm: LLM | None) -> None:
    global _default
    _default = llm
