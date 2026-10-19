"""Voice: Groq Whisper for speech-to-text, local Piper for text-to-speech."""

import asyncio
import io
import logging
import wave
from functools import cache

import httpx

from . import config

log = logging.getLogger("voice")


class VoiceError(RuntimeError):
    pass


# Whisper uses the prompt as "previous text": common terms from Indian tech interviews, spelled correctly.
BASE_VOCAB = ("B.Tech, B.E., Computer Science and Engineering, Artificial Intelligence and Machine Learning, "
              "agentic AI, generative AI, LLM, RAG, API, REST, FastAPI, Django, Flask, Python, Java, JavaScript, "
              "TypeScript, React, Node.js, SQL, MongoDB, PostgreSQL, Git, GitHub, Docker, AWS, data structures, algorithms.")


PROMPT_LIMIT = 800  # Groq rejects Whisper prompts over 896 characters


def _prompt(hint: str) -> str:
    """Whisper reads the prompt as the text just before the audio, so the end matters most: keep the role terms and
    the question just asked, and trim the generic vocabulary from the front if it's too long."""
    text = " ".join(f"{BASE_VOCAB} {hint}".split())
    return text[-PROMPT_LIMIT:]


async def _normalise(audio: bytes) -> bytes:
    """Any browser recording (Chrome webm/opus, Safari mp4/aac) -> 16 kHz mono FLAC, the format Whisper handles best."""
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-i", "pipe:0", "-ac", "1", "-ar", "16000", "-f", "flac", "pipe:1",
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    out, err = await proc.communicate(audio)
    if proc.returncode != 0 or len(out) < 1000:
        log.warning("ffmpeg could not read the recording (%d bytes): %s", len(audio), err.decode(errors="ignore")[:300])
        raise VoiceError("Couldn't read that recording. Please try again, or type your answer.")
    return out


async def transcribe(audio: bytes, filename: str, hint: str = "") -> str:
    """hint: domain words (role, tools, resume terms) so Whisper spells technical terms correctly."""
    if not config.GROQ_API_KEY:
        raise VoiceError("GROQ_API_KEY is not set")
    if len(audio) < 2000:
        return ""  # nothing usable was recorded
    flac = await _normalise(audio)
    async with httpx.AsyncClient(base_url=config.GROQ_BASE_URL, timeout=30,
                                 headers={"Authorization": f"Bearer {config.GROQ_API_KEY}"}) as client:
        for attempt in range(3):
            resp = await client.post("/audio/transcriptions",
                                     files={"file": ("answer.flac", flac, "audio/flac")},
                                     data={"model": config.STT_MODEL, "language": "en", "temperature": "0",
                                           "response_format": "verbose_json", "prompt": _prompt(hint)})
            if resp.status_code == 429 and attempt < 2:
                await asyncio.sleep(2 * (attempt + 1))
                continue
            if resp.status_code >= 400:
                log.error("Whisper %s: %s", resp.status_code, resp.text[:500])
                raise VoiceError("Couldn't transcribe that answer. Please try again, or type it.")
            data = resp.json()
            segments = data.get("segments")
            if not segments:
                return (data.get("text") or "").strip()
            # Whisper invents text on silence. Drop a segment only when it's BOTH probably silence and low confidence
            # (the standard Whisper rule). Low confidence alone is common for accented speech and must be kept.
            kept = [sg.get("text", "") for sg in segments
                    if not (sg.get("no_speech_prob", 0) > 0.6 and sg.get("avg_logprob", 0) < -1.0)]
            text = " ".join(t.strip() for t in kept).strip()
            log.info("stt %.1fs: %r (segments %d, kept %d)", data.get("duration") or 0, text[:120], len(segments), len(kept))
            return text
    raise VoiceError("Transcription is busy right now, please try again in a moment")


@cache
def _voice():
    if not config.PIPER_MODEL:
        raise VoiceError("PIPER_MODEL is not set in .env")
    from piper import PiperVoice
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
