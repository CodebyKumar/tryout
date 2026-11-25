"""Text to speech: Deepgram Aura over HTTP. Generated on request and never stored; the transcript is the record.
Without DEEPGRAM_API_KEY, speak() raises VoiceError and the room reads the line with the browser's own voice."""

import httpx

from .. import config
from .stt import VoiceError

URL = "https://api.deepgram.com/v1/speak"


async def speak(text: str) -> bytes:
    """MP3 audio of one interviewer line (small to send, plays in every browser)."""
    if not config.DEEPGRAM_API_KEY:
        raise VoiceError("Interviewer voice is not configured")
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                URL,
                params={"model": config.DEEPGRAM_VOICE, "encoding": "mp3"},
                headers={"Authorization": f"Token {config.DEEPGRAM_API_KEY}"},
                json={"text": text},
            )
        resp.raise_for_status()
    except httpx.HTTPError as e:
        raise VoiceError(f"Interviewer voice unavailable ({type(e).__name__})") from e
    return resp.content
