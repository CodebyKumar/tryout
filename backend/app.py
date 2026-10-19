"""HTTP API + pages. Recruiter: / (dashboard). Candidate: /i/{token} (interview). Run: uv run uvicorn backend.app:app"""

import asyncio
import logging
from collections import defaultdict

import io

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pypdf import PdfReader
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, store, voice
from .agents import candidate_prep, evaluator, role_compiler
from .engine import engine, policy
from .llm.client import LLMError
from .models import Candidate, Criterion, InterviewPlan, Role, Session, Target

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("app")
app = FastAPI(title="Tryout")
_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
_tasks: set[asyncio.Task] = set()


@app.middleware("http")
async def _no_stale_ui(request, call_next):
    """Pages and scripts change often; make browsers revalidate so nobody runs an old copy of the UI."""
    response = await call_next(request)
    path = request.url.path
    if path.startswith("/static/") or path == "/" or path.startswith("/i/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


@app.exception_handler(Exception)
async def _unexpected(request, exc: Exception):
    from fastapi.responses import JSONResponse
    log.exception("unhandled error on %s", request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Something went wrong on the server. Please try again; if it keeps failing, check ./run.sh logs."})


@app.on_event("startup")
async def _warm_up():
    await asyncio.to_thread(voice.warm_up)


def _get(cls, obj_id: str):
    obj = store.load(cls, obj_id) if obj_id else None
    if obj is None:
        raise HTTPException(404, f"{cls.__name__} not found")
    return obj


async def _llm(coro):
    try:
        return await coro
    except LLMError as e:
        raise HTTPException(503, f"AI service is busy, please retry in a moment ({e})")
    except ValueError as e:
        raise HTTPException(400, str(e))


def _by_token(token: str) -> Candidate:
    cand = next((c for c in store.load_all(Candidate) if c.token == token), None)
    if not cand:
        raise HTTPException(404, "Interview link not found")
    return cand


def _usage(s: Session) -> dict:
    turns = [u for u in s.usage if u.agent == "turn_agent"]
    return {"calls": len(s.usage), "prompt_tokens": sum(u.prompt_tokens for u in s.usage),
            "completion_tokens": sum(u.completion_tokens for u in s.usage),
            "avg_turn_ms": int(sum(u.latency_ms for u in turns) / max(1, len(turns)))}


def _interview_view(s: Session, plan: InterviewPlan) -> dict:
    """What the candidate sees: the conversation and progress, never scores."""
    return {"state": s.state, "elapsed_sec": round(s.elapsed_sec), "time_budget_sec": plan.time_budget_sec,
            "current_target_id": s.current_target_id,
            "sections": [{"target_id": t.target_id, "name": t.name, "status": s.targets[t.target_id].status,
                          "coverage": round(policy.coverage(t, s.targets[t.target_id]), 2)} for t in plan.targets],
            "turns": [{"turn_id": t.turn_id, "role": t.role, "text": t.text} for t in s.turns]}


def _summary(c: Candidate) -> dict:
    s = store.load(Session, c.session_id) if c.session_id else None
    plan = store.load(InterviewPlan, c.plan_id) if c.plan_id else None
    r = s.report if s else None
    return {**c.model_dump(exclude={"resume"}), "score": r.overall_score if r else None,
            "fit": plan.fit.score if plan else None,
            "recommendation": r.recommendation if r else None, "evaluating": bool(s and s.state == "EVALUATING")}


# ---------- Recruiter ----------

class RoleIn(BaseModel):
    title: str
    jd: str
    notes: str = ""
    company: str = ""
    time_budget_sec: int = 900


@app.post("/api/roles")
async def create_role(body: RoleIn):
    if len(body.jd.strip()) < 40:
        raise HTTPException(400, "Paste the full job description")
    role = Role(**body.model_dump())
    role = await _llm(role_compiler.compile_role(role))
    store.save(role)
    return role.model_dump()


@app.get("/api/roles")
async def list_roles():
    cands = store.load_all(Candidate)
    return [{**r.model_dump(include={"role_id", "title", "company", "created_at", "time_budget_sec"}),
             "candidates": sum(1 for c in cands if c.role_id == r.role_id),
             "completed": sum(1 for c in cands if c.role_id == r.role_id and c.status not in ("invited", "in_progress"))}
            for r in sorted(store.load_all(Role), key=lambda r: r.created_at, reverse=True)]


@app.get("/api/roles/{role_id}")
async def get_role(role_id: str):
    role = _get(Role, role_id)
    cands = [_summary(c) for c in store.load_all(Candidate) if c.role_id == role_id]
    cands.sort(key=lambda c: (c["score"] is None, -(c["score"] or 0)))
    return {**role.model_dump(), "candidates": cands}


def _doc_text(name: str, raw: bytes) -> str:
    name = name.lower()
    if name.endswith(".pdf"):
        return "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(raw)).pages)
    if name.endswith(".docx"):
        import re, zipfile
        xml = zipfile.ZipFile(io.BytesIO(raw)).read("word/document.xml").decode(errors="ignore")
        return re.sub(r"<[^>]+>", "", re.sub(r"</w:p>", "\n", xml))
    return raw.decode(errors="ignore")


@app.post("/api/roles/from-document")
async def role_from_document(file: UploadFile | None = File(None), text: str = Form(""),
                             time_budget_sec: int = Form(0), title: str = Form("")):
    """Recruiter drops one document (JD, guidelines, rubric, notes); the AI builds the whole brief."""
    if file is not None:
        try:
            text = _doc_text(file.filename or "", await file.read())
        except Exception:
            raise HTTPException(400, "Could not read that file. Upload a PDF, DOCX or text file, or paste the text.")
    if len(text.strip()) < 80:
        raise HTTPException(400, "The document is too short. Include at least the job description.")
    role = Role(title=title.strip() or "Untitled role", jd=text.strip()[:20000], time_budget_sec=time_budget_sec or 900)
    role = await _llm(role_compiler.compile_role(role, from_document=True, fixed_length=bool(time_budget_sec)))
    store.save(role)
    return role.model_dump()


class RefineIn(BaseModel):
    instruction: str


@app.post("/api/roles/{role_id}/refine")
async def refine_role(role_id: str, body: RefineIn):
    if not body.instruction.strip():
        raise HTTPException(400, "Describe the change you want")
    role = await _llm(role_compiler.refine_role(_get(Role, role_id), body.instruction))
    store.save(role)
    return role.model_dump()


class RoleUpdate(BaseModel):
    title: str | None = None
    notes: str | None = None
    time_budget_sec: int | None = None
    sections: list[Target] | None = None
    criteria: list[Criterion] | None = None


@app.put("/api/roles/{role_id}")
async def update_role(role_id: str, body: RoleUpdate):
    role = _get(Role, role_id)
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(role, k, getattr(body, k))
    if not role.sections or not role.criteria:
        raise HTTPException(400, "A role needs at least one section and one criterion")
    store.save(role)
    return role.model_dump()


class CandidateIn(BaseModel):
    name: str
    email: str = ""
    resume: str = ""


@app.post("/api/roles/{role_id}/candidates")
async def add_candidate(role_id: str, body: CandidateIn):
    _get(Role, role_id)
    if not body.name.strip():
        raise HTTPException(400, "Candidate name is required")
    cand = Candidate(role_id=role_id, **body.model_dump())
    if cand.resume.strip():
        await _prepare(cand)
    store.save(cand)
    return _summary(cand)


async def _prepare(cand: Candidate) -> InterviewPlan:
    """Read the resume once: personalised questions, claims to verify, role fit. Saved on the candidate."""
    plan = await _llm(candidate_prep.build_plan(_get(Role, cand.role_id), cand))
    store.save(plan)
    cand.plan_id = plan.plan_id
    return plan


@app.get("/api/candidates/{candidate_id}")
async def candidate_report(candidate_id: str):
    cand = _get(Candidate, candidate_id)
    role = _get(Role, cand.role_id)
    out = {"candidate": cand.model_dump(), "role": role.model_dump(include={"role_id", "title", "criteria"}),
           "report": None, "transcript": [], "flags": [], "usage": None, "state": None,
           "fit": _get(InterviewPlan, cand.plan_id).fit.model_dump() if cand.plan_id else None}
    if cand.session_id:
        s = _get(Session, cand.session_id)
        plan = _get(InterviewPlan, s.plan_id)
        names = {t.target_id: t.name for t in plan.targets}
        out.update(report=s.report.model_dump() if s.report else None, state=s.state, usage=_usage(s),
                   fit=plan.fit.model_dump(),
                   flags=[f.model_dump() for f in s.flags],
                   duration_sec=round(s.elapsed_sec), resume_highlights=plan.resume_highlights,
                   transcript=[{"turn_id": t.turn_id, "role": t.role, "text": t.text, "at": s.offset(t),
                                "section": names.get(t.target_id, "")} for t in s.turns])
    return out


class DecisionIn(BaseModel):
    status: str


@app.post("/api/candidates/{candidate_id}/decision")
async def decide(candidate_id: str, body: DecisionIn):
    cand = _get(Candidate, candidate_id)
    if body.status not in ("advanced", "hold", "rejected"):
        raise HTTPException(400, "Decision must be advanced, hold or rejected")
    cand.status = body.status
    store.save(cand)
    return _summary(cand)


@app.post("/api/candidates/{candidate_id}/release_feedback")
async def release_feedback(candidate_id: str):
    cand = _get(Candidate, candidate_id)
    cand.feedback_released = True
    store.save(cand)
    return _summary(cand)


@app.delete("/api/candidates/{candidate_id}")
async def delete_candidate(candidate_id: str):
    """Remove the candidate and everything about them: resume, interview plan, transcript, report."""
    cand = _get(Candidate, candidate_id)
    async with _locks[cand.candidate_id]:
        if cand.session_id:
            store.delete(Session, cand.session_id)
        if cand.plan_id:
            store.delete(InterviewPlan, cand.plan_id)
        store.delete(Candidate, cand.candidate_id)
    return {"deleted": candidate_id}


@app.post("/api/candidates/{candidate_id}/reset")
async def reset_candidate(candidate_id: str):
    """Start over on the same link: transcript, report, resume and resume fit are all cleared."""
    cand = _get(Candidate, candidate_id)
    async with _locks[cand.candidate_id]:
        if cand.session_id:
            store.delete(Session, cand.session_id)
        if cand.plan_id:
            store.delete(InterviewPlan, cand.plan_id)
        cand.session_id, cand.plan_id, cand.resume = None, None, ""
        cand.status, cand.feedback_released = "invited", False
        store.save(cand)
    return _summary(cand)


@app.post("/api/candidates/{candidate_id}/reevaluate")
async def reevaluate(candidate_id: str):
    cand = _get(Candidate, candidate_id)
    s = _get(Session, cand.session_id)
    await _evaluate(cand, s)
    return await candidate_report(candidate_id)


# ---------- Candidate (by private link token) ----------

async def _evaluate(cand: Candidate, s: Session) -> None:
    async with _locks[f"eval_{s.session_id}"]:
        role, plan = _get(Role, cand.role_id), _get(InterviewPlan, s.plan_id)
        s.state = "EVALUATING"
        store.save(s)
        try:
            s.report = await evaluator.evaluate(role, plan, s)
            s.state = "DONE"
        except (LLMError, ValueError) as e:
            log.error("evaluation failed for %s: %s", cand.candidate_id, e)
            s.state = "DONE"  # transcript is safe; the recruiter can re-run evaluation
        store.save(s)
        cand = _get(Candidate, cand.candidate_id)
        if cand.status in ("invited", "in_progress"):
            cand.status = "completed"
            store.save(cand)


def _evaluate_later(cand: Candidate, s: Session) -> None:
    task = asyncio.create_task(_evaluate(cand, s))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


@app.get("/api/i/{token}")
async def interview_info(token: str):
    cand = _by_token(token)
    role = _get(Role, cand.role_id)
    out = {"name": cand.name, "role_title": role.title, "company": role.company,
           "minutes": round(role.time_budget_sec / 60), "status": cand.status, "interview": None, "feedback": None,
           "has_resume": bool(cand.resume.strip())}
    if cand.session_id:
        s = _get(Session, cand.session_id)
        out["interview"] = _interview_view(s, _get(InterviewPlan, s.plan_id))
        if cand.feedback_released and s.report:
            out["feedback"] = s.report.candidate_feedback
    return out


@app.post("/api/i/{token}/resume")
async def upload_resume(token: str, file: UploadFile | None = File(None), text: str = Form("")):
    cand = _by_token(token)
    if cand.session_id:
        raise HTTPException(400, "The interview has already started")
    if file is not None:
        raw = await file.read()
        if (file.filename or "").lower().endswith(".pdf"):
            try:
                text = "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(raw)).pages)
            except Exception:
                raise HTTPException(400, "Could not read that PDF. Try another file or paste the text.")
        else:
            text = raw.decode(errors="ignore")
    if len(text.strip()) < 100:
        raise HTTPException(400, "That resume looks empty. Upload a PDF or paste the text.")
    async with _locks[cand.candidate_id]:
        cand.resume = text.strip()[:20000]
        await _prepare(cand)
        store.save(cand)
    return {"ok": True}


@app.post("/api/i/{token}/start")
async def start_interview(token: str):
    cand = _by_token(token)
    async with _locks[cand.candidate_id]:
        cand = _by_token(token)
        if cand.session_id:
            s = _get(Session, cand.session_id)
            return _interview_view(s, _get(InterviewPlan, s.plan_id))
        plan = _get(InterviewPlan, cand.plan_id) if cand.plan_id else await _prepare(cand)
        s = engine.new_session(plan)
        engine.start(plan, s)
        cand.session_id, cand.status = s.session_id, "in_progress"
        store.save(s), store.save(cand)
        return _interview_view(s, plan)


class TurnIn(BaseModel):
    text: str


@app.post("/api/i/{token}/turn")
async def interview_turn(token: str, body: TurnIn):
    if not body.text.strip():
        raise HTTPException(400, "Empty answer")
    cand = _by_token(token)
    async with _locks[cand.candidate_id]:
        s = _get(Session, cand.session_id)
        plan = _get(InterviewPlan, s.plan_id)
        result = await _llm(engine.handle_user_turn(plan, s, body.text))
        store.save(s)
    if result["done"]:
        _evaluate_later(cand, s)
    return {**result, "interview": _interview_view(s, plan)}


_NOISE = {"", "you", "thank you", "thanks", "thanks for watching", "thank you for watching", "bye", "okay", "uh", "um"}


@app.post("/api/i/{token}/audio")
async def interview_audio(token: str, audio: UploadFile = File(...)):
    """Voice turn: Whisper transcribes the answer (with role vocabulary as a hint), then the normal turn runs."""
    cand = _by_token(token)
    s = _get(Session, cand.session_id)
    plan = _get(InterviewPlan, s.plan_id)
    last_q = next((t.text for t in reversed(s.turns) if t.role == "agent"), "")
    try:
        # The candidate's full name goes in the hint: Whisper can't spell names it has never seen.
        text = await voice.transcribe(await audio.read(), audio.filename or "answer.webm",
                                      f"Candidate: {cand.name}. {plan.stt_hint} {last_q}")
    except voice.VoiceError as e:
        raise HTTPException(503, str(e))
    # Whisper invents these on silence or noise; treat them as "didn't catch that".
    if text.lower().strip(" .!?") in _NOISE or not any(ch.isalnum() for ch in text):
        return {"user_text": "", "say": None, "done": False, "interview": _interview_view(s, plan)}
    result = await interview_turn(token, TurnIn(text=text))
    return {"user_text": text, **result}


@app.get("/api/i/{token}/tts/{turn_id}")
async def interview_tts(token: str, turn_id: str):
    """Interviewer audio for one agent turn (Piper). Generated on request and never stored: the transcript is the record."""
    cand = _by_token(token)
    s = _get(Session, cand.session_id)
    turn = next((t for t in s.turns if t.turn_id == turn_id and t.role == "agent"), None)
    if not turn:
        raise HTTPException(404, "No such turn")
    try:
        wav = await voice.speak(turn.text)
    except Exception as e:
        raise HTTPException(503, f"Voice unavailable: {e}")
    return Response(wav, media_type="audio/wav", headers={"Cache-Control": "private, max-age=600"})


@app.post("/api/i/{token}/end")
async def end_interview(token: str):
    cand = _by_token(token)
    async with _locks[cand.candidate_id]:
        s = _get(Session, cand.session_id)
        if s.state in ("INTERVIEWING", "WRAPUP"):
            s.state, s.current_target_id = "EVALUATING", None
            store.save(s)
            _evaluate_later(cand, s)
    return _interview_view(s, _get(InterviewPlan, s.plan_id))


@app.get("/api/health")
async def health():
    return {"ok": True, "llm_key": bool(config.GROQ_API_KEY), "models": config.MODELS}


@app.get("/")
async def recruiter_page():
    return FileResponse(config.FRONTEND_DIR / "recruiter.html")


@app.get("/i/{token}")
async def candidate_page(token: str):
    return FileResponse(config.FRONTEND_DIR / "interview.html")


app.mount("/static", StaticFiles(directory=config.FRONTEND_DIR), name="static")
