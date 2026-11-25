"""Interviews, by private link token. The engine decides state, the Turn Agent proposes; this is the only place
that joins them."""

import logging

from .. import db
from ..agents import turn_agent
from ..agents.base import run_agent
from ..engine import context, state_machine
from ..integrations import stt, tts
from ..integrations.llm import LLMError
from ..models import ExperienceRating, IntegrityEvent, InterviewPlan, Session
from ..safety import integrity
from . import Invalid, NotFound, candidates, evaluation, locks, roles, sessions

log = logging.getLogger("interviews")

# Whisper invents these on silence or noise; treat them as "didn't catch that".
_NOISE = {"", "you", "thank you", "thanks", "thanks for watching", "thank you for watching", "bye", "okay", "uh", "um"}


async def handle_user_turn(plan: InterviewPlan, session: Session, text: str) -> dict:
    """One candidate answer -> at most one Turn Agent call -> state update. Returns what the UI needs."""
    if session.state not in ("INTERVIEWING", "WRAPUP"):
        raise Invalid("This interview has already ended")
    if duplicate := state_machine.duplicate_reply(session, text):
        return duplicate
    wrapup = session.state == "WRAPUP"
    user_turn = state_machine.record_answer(session, text)
    if wrapup:
        # The answer to "anything else?" needs no LLM: nothing is left to ask, and the evaluator reads it in the
        # transcript. Saves one full Turn Agent call per interview.
        return state_machine.end(session, "Thank you.")
    try:
        out, usage = await run_agent(
            turn_agent.SPEC,
            candidate_name=plan.candidate_name or "the candidate",
            company=plan.company or "the company",
            role_title=plan.role_title,
            context=context.build(plan, session),
            turn_id=user_turn.turn_id,
            user_text=user_turn.text,
        )
    except LLMError as e:
        log.error("turn agent failed: %s", e)
        return state_machine.fallback(session)
    session.usage.append(usage)
    return state_machine.apply_turn(plan, session, user_turn, out)


async def _load(token: str):
    async with db.transaction() as s:
        cand = await candidates.load(s, token=token)
        if not cand.session_id:
            raise Invalid("The interview has not started")
        session = await sessions.load(s, cand.session_id)
        return cand, session, await candidates.load_plan(s, session.plan_id)


async def info(token: str):
    """Everything the candidate page needs: the candidate, the role, and the interview if it has started."""
    async with db.transaction() as s:
        cand = await candidates.load(s, token=token)
        role = await roles.load(s, cand.role_id)
        session = await sessions.load(s, cand.session_id) if cand.session_id else None
        plan = await candidates.load_plan(s, session.plan_id) if session else None
    return cand, role, session, plan


async def start(token: str) -> tuple[Session, InterviewPlan]:
    """Idempotent: a second start (reload, double click) returns the running interview."""
    async with db.transaction() as s:
        cand = await candidates.load(s, token=token)
    async with locks[cand.candidate_id]:
        async with db.transaction() as s:
            cand = await candidates.load(s, token=token)
            if cand.session_id:
                session = await sessions.load(s, cand.session_id)
                return session, await candidates.load_plan(s, session.plan_id)
            plan = await candidates.load_plan(s, cand.plan_id) if cand.plan_id else None
        plan = plan or await candidates.read_resume(cand)
        session = state_machine.new_session(plan)
        state_machine.start(plan, session)
        cand.status = "in_progress"
        async with db.transaction() as s:
            await sessions.save(s, session)
            await candidates.save(s, cand)
        return session, plan


async def answer(token: str, text: str) -> tuple[dict, Session, InterviewPlan]:
    if not text.strip():
        raise Invalid("Empty answer")
    cand, _, _ = await _load(token)
    async with locks[cand.candidate_id]:
        _, session, plan = await _load(token)  # fresh, under the lock
        result = await handle_user_turn(plan, session, text)
        async with db.transaction() as s:
            await sessions.save(s, session)
    if result["done"]:
        evaluation.run_later(cand.candidate_id, session.session_id)
    return result, session, plan


async def answer_audio(token: str, audio: bytes, filename: str) -> tuple[str, dict | None, Session, InterviewPlan]:
    """Voice answer: Whisper transcribes it (with role vocabulary as a hint), then the normal turn runs. Returns the
    transcript and the turn result, or no result when nothing usable was said."""
    cand, session, plan = await _load(token)
    last_q = next((x.text for x in reversed(session.turns) if x.role == "agent"), "")
    # The candidate's full name goes in the hint: Whisper can't spell names it has never seen.
    text = await stt.transcribe(audio, filename, f"Candidate: {cand.name}. {plan.stt_hint} {last_q}")
    if text.lower().strip(" .!?") in _NOISE or not any(ch.isalnum() for ch in text):
        return "", None, session, plan
    result, session, plan = await answer(token, text)
    return text, result, session, plan


async def speak(token: str, turn_id: str) -> bytes:
    """Interviewer audio for one agent turn. Generated on request and never stored: the transcript is the record."""
    _, session, _ = await _load(token)
    turn = next((x for x in session.turns if x.turn_id == turn_id and x.role == "agent"), None)
    if not turn:
        raise NotFound("No such turn")
    return await tts.speak(turn.text)


async def end(token: str) -> tuple[Session, InterviewPlan]:
    """The candidate ends early: whatever was said is evaluated."""
    cand, _, _ = await _load(token)
    async with locks[cand.candidate_id]:
        _, session, plan = await _load(token)
        if session.state in ("INTERVIEWING", "WRAPUP"):
            session.state, session.current_section_id = "EVALUATING", None
            async with db.transaction() as s:
                await sessions.save(s, session)
            evaluation.run_later(cand.candidate_id, session.session_id)
    return session, plan


async def rate(token: str, rating: ExperienceRating) -> None:
    """The candidate rates the interview once it is over. A second rating replaces the first."""
    cand, _, _ = await _load(token)
    async with locks[cand.candidate_id]:
        _, session, _ = await _load(token)
        if session is None or session.state in ("READY", "INTERVIEWING", "WRAPUP"):
            raise Invalid("You can rate the interview once it has ended")
        session.experience = rating
        async with db.transaction() as s:
            await sessions.save(s, session)


async def record_integrity(token: str, events: list[IntegrityEvent]) -> None:
    """Browser signals from the room, kept with the session. Dropped once the interview is over."""
    cand, _, _ = await _load(token)
    async with locks[cand.candidate_id]:
        _, session, _ = await _load(token)
        if session.state not in ("INTERVIEWING", "WRAPUP"):
            return
        session.integrity += events[: integrity.MAX_EVENTS - len(session.integrity)]
        async with db.transaction() as s:
            await sessions.save(s, session)
