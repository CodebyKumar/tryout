"""Candidate API, by private link token: /api/i/{token}/..."""

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from ..services import NotFound, candidates, interviews
from . import MAX_AUDIO_BYTES, read_upload, views
from .recruiter import read_document

router = APIRouter(prefix="/api/i/{token}")


class TurnIn(BaseModel):
    text: str


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
async def start_interview(token: str):
    return views.interview(*await interviews.start(token))


@router.post("/turn")
async def interview_turn(token: str, body: TurnIn):
    result, s, plan = await interviews.answer(token, body.text)
    return {**result, "interview": views.interview(s, plan)}


@router.post("/audio")
async def interview_audio(token: str, audio: UploadFile = File(...)):
    raw = await read_upload(audio, MAX_AUDIO_BYTES)
    text, result, s, plan = await interviews.answer_audio(token, raw, audio.filename or "answer.webm")
    if result is None:  # nothing usable was said: the UI asks again
        return {"user_text": "", "say": None, "done": False, "interview": views.interview(s, plan)}
    return {"user_text": text, **result, "interview": views.interview(s, plan)}


@router.get("/tts/{turn_id}")
async def interview_tts(token: str, turn_id: str):
    try:
        wav = await interviews.speak(token, turn_id)
    except NotFound:
        raise
    except Exception as e:  # Piper not installed or the voice model missing: the UI falls back to text
        raise HTTPException(503, f"Voice unavailable: {e}")
    return Response(wav, media_type="audio/wav", headers={"Cache-Control": "private, max-age=600"})


@router.post("/end")
async def end_interview(token: str):
    return views.interview(*await interviews.end(token))
