"""Text to speech: Deepgram Aura over HTTP, streamed. Generated on request and never stored; the transcript is the
record. Without DEEPGRAM_API_KEY, opening a stream raises VoiceError and the room reads the line with the browser's
own voice."""

from collections.abc import AsyncIterator

import httpx

from .. import config
from .stt import VoiceError

URL = "https://api.deepgram.com/v1/speak"
_client: httpx.AsyncClient | None = None


def _shared() -> httpx.AsyncClient:
    """One connection pool for every line: reusing the TLS connection saves a round trip per line (the server runs one
    event loop, so one client is safe)."""
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=httpx.Timeout(15, read=20))
    return _client


async def stream(text: str) -> AsyncIterator[bytes]:
    """MP3 audio of one interviewer line, chunk by chunk as Deepgram makes it, so the browser starts playing within a
    few hundred milliseconds instead of after the whole file. The connection is opened before the first chunk is
    yielded, so a missing key or a failed request raises VoiceError while the caller can still answer 503."""
    if not config.DEEPGRAM_API_KEY:
        raise VoiceError("Interviewer voice is not configured")
    client = _shared()
    try:
        resp = await client.send(
            client.build_request(
                "POST",
                URL,
                params={"model": config.DEEPGRAM_VOICE, "encoding": "mp3"},
                headers={"Authorization": f"Token {config.DEEPGRAM_API_KEY}"},
                json={"text": text},
            ),
            stream=True,
        )
        if resp.status_code != 200:
            await resp.aclose()
            raise VoiceError(f"Interviewer voice unavailable (HTTP {resp.status_code})")
    except httpx.HTTPError as e:
        raise VoiceError(f"Interviewer voice unavailable ({type(e).__name__})") from e

    async def chunks() -> AsyncIterator[bytes]:
        try:
            async for chunk in resp.aiter_bytes(4096):
                yield chunk
        finally:
            await resp.aclose()

    return chunks()


async def speak(text: str) -> bytes:
    """The whole line at once (tests and scripts)."""
    return b"".join([c async for c in await stream(text)])
