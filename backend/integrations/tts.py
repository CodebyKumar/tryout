"""Text-to-speech: local Piper voice. Generated on request, never stored."""

import asyncio
import io
import logging
import wave
from functools import cache

from .. import config
from .stt import VoiceError

log = logging.getLogger("tts")


@cache
def _voice():
    if not config.PIPER_MODEL:
        raise VoiceError("PIPER_MODEL is not set in .env")
    from piper import PiperVoice  # heavy and optional: loaded only when voice is configured

    return PiperVoice.load(config.PIPER_MODEL)


LEAD_IN_SEC = 0.25  # silence before speech: speakers and phone audio routes take a moment to wake up


def _synth(text: str) -> bytes:
    raw = io.BytesIO()
    with wave.open(raw, "wb") as w:
        _voice().synthesize_wav(text, w)
    raw.seek(0)
    with wave.open(raw, "rb") as r:
        params, frames = r.getparams(), r.readframes(r.getnframes())
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setparams(params)
        w.writeframes(b"\x00" * int(params.framerate * LEAD_IN_SEC) * params.sampwidth * params.nchannels + frames)
    return out.getvalue()


async def speak(text: str) -> bytes:
    return await asyncio.to_thread(_synth, text)


def warm_up() -> None:
    try:
        _voice()
    except Exception as e:  # voice is optional; the browser falls back to its own TTS
        log.warning("Piper not available: %s", e)
