"""One LLM entry point for every agent.

Agents call `llm.json(agent=..., role=..., system=..., user=..., output=Model)` and get a validated Model back. The role picks a
fallback chain of models (config.MODELS); rate limits and provider errors move to the next model.
"""

import asyncio
import json
import logging
import re
import time
from collections.abc import Callable
from typing import Protocol, TypeVar

import httpx
from pydantic import BaseModel

from .. import config
from ..models import Usage
from . import groq

log = logging.getLogger("llm")
M = TypeVar("M", bound=BaseModel)


class LLMError(RuntimeError):
    pass


class LLM(Protocol):
    async def json(
        self,
        *,
        agent: str,
        role: str,
        system: str,
        user: str,
        output: type[M],
        max_tokens: int = 800,
        temperature: float = 0.3,
        timeout: float = 30,
    ) -> tuple[M, Usage]: ...


def parse_json(text: str) -> dict:
    """Defensive JSON parsing: strips code fences and surrounding prose, tolerates trailing commas."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object in response")
    body = re.sub(r",\s*([}\]])", r"\1", text[start : end + 1])
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


DEFAULT_RATE_LIMIT_WAIT = 5.0  # when a 429 does not say how long to wait


class RateLimited(LLMError):
    def __init__(self, model: str, wait: float):
        super().__init__(f"{model}: rate limited for {wait:.1f}s")
        self.wait = wait


def _retry_after(resp: httpx.Response) -> float:
    if resp.headers.get("retry-after"):
        try:
            return float(resp.headers["retry-after"])
        except ValueError:
            pass
    m = re.search(r"try again in (?:(\d+)m)?([\d.]+)(ms|s)", resp.text)
    if not m:
        return DEFAULT_RATE_LIMIT_WAIT
    return int(m.group(1) or 0) * 60 + float(m.group(2)) / (1000 if m.group(3) == "ms" else 1)


class GroqLLM:
    """Spends as few calls and tokens as possible: a rate-limited model is skipped until its limit clears (shared
    by every request in the process), no request is sent that is known to fail, and rejected optional parameters
    are remembered per model."""

    def __init__(self, models: dict[str, list[str]] = config.MODELS, http: httpx.AsyncClient | None = None):
        if http is None and not config.GROQ_API_KEY:
            raise LLMError("GROQ_API_KEY is not set. Add it to .env")
        self.models = models
        self._http = http  # tests pass a fake server; otherwise the shared Groq transport
        self._cooldown: dict[str, float] = {}  # model -> monotonic time its rate limit clears
        self._plain: set[str] = set()  # models that rejected _extra_params

    @property
    def client(self) -> httpx.AsyncClient:
        return self._http or groq.client()

    async def _call(
        self, model: str, messages: list[dict], max_tokens: int, temperature: float, timeout: float
    ) -> dict:
        extra = {} if model in self._plain else _extra_params(model)
        body = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_completion_tokens": max_tokens,
            "response_format": {"type": "json_object"},
            **extra,
        }
        resp = await self.client.post("/chat/completions", json=body, timeout=timeout)
        if resp.status_code == 400 and extra:
            # Provider rejected an optional parameter: remember it, and retry once with the plain request.
            self._plain.add(model)
            body = {k: v for k, v in body.items() if k not in extra}
            resp = await self.client.post("/chat/completions", json=body, timeout=timeout)
        if resp.status_code == 429:
            raise RateLimited(model, _retry_after(resp))
        if resp.status_code >= 400:
            raise LLMError(f"{model}: HTTP {resp.status_code} {resp.text[:300]}")
        return resp.json()

    async def _ask(self, model: str, messages: list[dict], output: type[M], **kw) -> tuple[M, list[dict]]:
        """One answer from one model, with one repair attempt. Returns the result and the usage of each call."""
        data = await self._call(model, messages, **kw)
        content = data["choices"][0]["message"].get("content") or ""
        try:
            return output.model_validate(parse_json(content)), [data.get("usage") or {}]
        except ValueError as e:  # bad JSON, or JSON that does not match the output model
            repair = messages + [
                {"role": "assistant", "content": content},
                {
                    "role": "user",
                    "content": f"That answer was not valid ({str(e)[:500]}). Return only the corrected JSON object.",
                },
            ]
            fixed = await self._call(model, repair, **kw)
            result = output.model_validate(parse_json(fixed["choices"][0]["message"].get("content") or ""))
            return result, [data.get("usage") or {}, fixed.get("usage") or {}]

    async def json(
        self,
        *,
        agent: str,
        role: str,
        system: str,
        user: str,
        output: type[M],
        max_tokens: int = 800,
        temperature: float = 0.3,
        timeout: float = 30,
    ) -> tuple[M, Usage]:
        """Tries the role's models in order. `timeout` is also the longest this call waits for a rate limit to clear:
        the Turn Agent (candidate waiting) gives up fast, background agents wait longer."""
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        give_up = time.monotonic() + timeout
        failed: set[str] = set()  # models with a real error (not a rate limit): not retried in this call
        errors = []
        while True:
            chain = [m for m in self.models[role] if m not in failed]
            ready = [m for m in chain if self._cooldown.get(m, 0) <= time.monotonic()]
            if not ready:
                wake = min((self._cooldown[m] for m in chain), default=None)
                if wake is None or wake > give_up:
                    break
                log.info("agent=%s: all models rate limited, waiting %.1fs", agent, wake - time.monotonic())
                await asyncio.sleep(max(0.0, wake - time.monotonic()))
                continue
            model = ready[0]
            t0 = time.perf_counter()
            try:
                result, raw = await self._ask(
                    model, messages, output, max_tokens=max_tokens, temperature=temperature, timeout=timeout
                )
            except RateLimited as e:
                self._cooldown[model] = time.monotonic() + e.wait
                log.info("agent=%s %s", agent, e)
                errors.append(str(e))
                continue
            except (LLMError, httpx.HTTPError, ValueError, KeyError) as e:
                log.warning("agent=%s model=%s failed: %s", agent, model, e)
                failed.add(model)
                errors.append(str(e))
                continue
            usage = Usage(
                agent=agent,
                model=model,
                calls=len(raw),
                prompt_tokens=sum(u.get("prompt_tokens", 0) for u in raw),
                completion_tokens=sum(u.get("completion_tokens", 0) for u in raw),
                cached_tokens=sum((u.get("prompt_tokens_details") or {}).get("cached_tokens", 0) for u in raw),
                latency_ms=int((time.perf_counter() - t0) * 1000),
            )
            log.info(
                "agent=%s model=%s in=%s cached=%s out=%s %sms",
                agent,
                model,
                usage.prompt_tokens,
                usage.cached_tokens,
                usage.completion_tokens,
                usage.latency_ms,
            )
            return result, usage
        raise LLMError(f"All models failed for {agent}: {' | '.join(errors[-4:])}")


class FakeLLM:
    """Test double: handlers[agent](system, user) -> dict, validated against the output model like real answers."""

    def __init__(self, handlers: dict[str, Callable[[str, str], dict]]):
        self.handlers = handlers
        self.calls: list[tuple[str, str]] = []

    async def json(
        self,
        *,
        agent: str,
        role: str,
        system: str,
        user: str,
        output: type[M],
        max_tokens: int = 800,
        temperature: float = 0.3,
        timeout: float = 30,
    ) -> tuple[M, Usage]:
        self.calls.append((agent, user))
        return output.model_validate(self.handlers[agent](system, user)), Usage(agent=agent, model="fake")


_default: LLM | None = None


def get_llm() -> LLM:
    global _default
    if _default is None:
        _default = GroqLLM()
    return _default


def set_llm(llm: LLM | None) -> None:
    global _default
    _default = llm
