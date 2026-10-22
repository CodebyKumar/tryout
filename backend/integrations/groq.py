"""Groq HTTP transport shared by the LLM and Whisper: one connection pool, so calls reuse warm TLS connections."""

import asyncio

import httpx

from .. import config

_clients: dict[int, httpx.AsyncClient] = {}


def client() -> httpx.AsyncClient:
    if not config.GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY is not set. Add it to .env")
    # httpx clients are bound to an event loop; keep one per loop (server, tests and scripts use different loops).
    loop_id = id(asyncio.get_running_loop())
    if loop_id not in _clients:
        _clients[loop_id] = httpx.AsyncClient(
            base_url=config.GROQ_BASE_URL, timeout=30, headers={"Authorization": f"Bearer {config.GROQ_API_KEY}"}
        )
    return _clients[loop_id]
