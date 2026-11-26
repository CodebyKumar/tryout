"""Candidate API, by private link token: /api/i/{token}/... No account: the link is the credential. Each browser
tab sends its own random X-Client-Id, so one interview runs in one tab at a time."""

from typing import Annotated

from fastapi import APIRouter, File, Form, Header, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..models import ExperienceRating, IntegrityEvent
from ..services import candidates, interviews
from . import MAX_AUDIO_BYTES, read_upload, views
from .recruiter import read_document

router = APIRouter(prefix="/api/i/{token}")

ClientId = Annotated[str, Header(alias="X-Client-Id", max_length=64)]


class TurnIn(BaseModel):
    text: str = Field(max_length=4000)


class StartIn(BaseModel):
    """The lobby's own checks (see interviews.start for what they can and cannot prove)."""

    extensions: list[str] = Field(default=[], max_length=10)
    fullscreen: bool = True


class EventsIn(BaseModel):
    events: list[IntegrityEvent] = Field(max_length=50)


@router.get("")
async def interview_info(token: str):
    return views.candidate_info(*await interviews.info(token))


@router.post("/resume")
async def upload_resume(token: str, file: UploadFile | None = File(None), text: str = Form("")):
    raw = None
    if file is not None:
        text, raw = await read_document(file)
    await candidates.upload_resume(token, text, file.filename if file else None, raw)
    return {"ok": True}


@router.post("/start")
async def start_interview(token: str, body: StartIn | None = None, client_id: ClientId = ""):
    body = body or StartIn()
    return views.interview(*await interviews.start(token, client_id, body.extensions, body.fullscreen))


@router.post("/turn")
async def interview_turn(token: str, body: TurnIn, client_id: ClientId = ""):
    result, s, plan = await interviews.answer(token, body.text, client_id)
    return {**result, "interview": views.interview(s, plan)}


@router.post("/audio")
async def interview_audio(token: str, audio: UploadFile = File(...), client_id: ClientId = ""):
    raw = await read_upload(audio, MAX_AUDIO_BYTES)
    text, result, s, plan = await interviews.answer_audio(token, raw, audio.filename or "answer.webm", client_id)
    if result is None:  # nothing usable was said: the UI asks again
        return {"user_text": "", "say": None, "done": False, "interview": views.interview(s, plan)}
    return {"user_text": text, **result, "interview": views.interview(s, plan)}


@router.get("/tts/{turn_id}")
async def interview_tts(token: str, turn_id: str):
    """Streamed MP3, so playback starts on the first chunk. 503 (VoiceError) before any audio when the voice service is
    off or failing: the room then uses the browser's own voice."""
    audio = await interviews.speak(token, turn_id)
    return StreamingResponse(audio, media_type="audio/mpeg", headers={"Cache-Control": "private, max-age=600"})


@router.post("/end")
async def end_interview(token: str, client_id: ClientId = ""):
    return views.interview(*await interviews.end(token, client_id))


@router.post("/rating")
async def rate_interview(token: str, body: ExperienceRating):
    await interviews.rate(token, ExperienceRating(stars=body.stars, comment=body.comment.strip()))
    return {"ok": True}


@router.post("/events")
async def integrity_events(token: str, body: EventsIn):
    await interviews.record_integrity(token, body.events)
    return {"ok": True}
