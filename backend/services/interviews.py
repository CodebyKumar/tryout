"""Interviews, by private link token. The engine decides state, the Turn Agent proposes; this is the only place
that joins them."""

import logging
import time
from datetime import timedelta

from sqlalchemy import func, select

from .. import config, db
from .. import tables as t
from ..agents import turn_agent
from ..agents.base import run_agent
from ..engine import context, state_machine
from ..integrations import stt, tts
from ..integrations.llm import LLMError
from ..models import Candidate, ExperienceRating, IntegrityEvent, InterviewPlan, Session, now
from ..safety import integrity
from . import Busy, Conflict, Invalid, NotFound, candidates, jobs, locked, roles, sessions

log = logging.getLogger("interviews")

# Whisper invents these on silence or noise; treat them as "didn't catch that".
_NOISE = {"", "you", "thank you", "thanks", "thanks for watching", "thank you for watching", "bye", "okay", "uh", "um"}
TAB_TAKEOVER_SEC = 60  # another tab may take over an interview whose tab has been silent this long
LIVE = ("INTERVIEWING", "WRAPUP")


async def handle_user_turn(plan: InterviewPlan, session: Session, text: str, stt_ms: int = 0) -> dict:
    """One candidate answer -> at most one Turn Agent call -> state update. Returns what the UI needs. The agent's
    line carries a trace: what the Turn Agent proposed and what code decided."""
    if session.state not in LIVE:
        raise Invalid("This interview has already ended")
    if duplicate := state_machine.duplicate_reply(session, text):
        return duplicate
    wrapup = session.state == "WRAPUP"
    section = session.current_section_id
    user_turn = state_machine.record_answer(session, text)
    if wrapup:
        # The answer to "anything else?" needs no LLM: nothing is left to ask, and the evaluator reads it in the
        # transcript. Saves one full Turn Agent call per interview.
        result = state_machine.end(session, "Thank you.")
        session.turns[-1].trace = {"decision": "wrap-up answered; no AI call", "stt_ms": stt_ms}
        return result
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
        result = state_machine.fallback(session)
        session.turns[-1].trace = {"decision": f"AI unavailable; asked to repeat ({e})"[:300], "stt_ms": stt_ms}
        return result
    session.usage.append(usage)
    result = state_machine.apply_turn(plan, session, user_turn, out)
    session.turns[-1].trace = {
        "proposal": out.model_dump(exclude_defaults=True),
        "decision": result.pop("decision"),
        "overrides": result.pop("overrides"),
        "section_before": section,
        "section_after": session.current_section_id,
        "model": usage.model,
        "agent_ms": usage.latency_ms,
        "stt_ms": stt_ms,
        "prompt_tokens": usage.prompt_tokens,
        "cached_tokens": usage.cached_tokens,
        "completion_tokens": usage.completion_tokens,
    }
    return result


async def _load(token: str) -> tuple[Candidate, Session, InterviewPlan]:
    async with db.transaction() as s:
        cand = await candidates.load(s, token=token)
        if not cand.session_id:
            raise Invalid("The interview has not started")
        session = await sessions.load(s, cand.session_id)
        return cand, session, await candidates.load_plan(s, session.plan_id)


def _check_tab(session: Session, client_id: str) -> None:
    """One browser tab per interview: two tabs answering at once would interleave the transcript."""
    if session.state in LIVE and session.client_id and client_id and session.client_id != client_id:
        raise Conflict("This interview is open in another tab or device. Continue there, or close it and reload.")


async def info(token: str):
    """Everything the candidate page needs: the candidate, the role, and the interview if it has started."""
    async with db.transaction() as s:
        cand = await candidates.load(s, token=token)
        role = await roles.load(s, cand.role_id)
        session = await sessions.load(s, cand.session_id) if cand.session_id else None
        plan = await candidates.load_plan(s, session.plan_id) if session else None
    return cand, role, session, plan


async def live_count() -> int:
    """Interviews in progress with an answer in the last two minutes: the load on the LLM right now."""
    async with db.transaction() as s:
        return await s.scalar(
            select(func.count()).where(
                t.Session.state.in_(LIVE), t.Session.last_activity_at > now() - timedelta(minutes=2)
            )
        )


async def start(
    token: str, client_id: str = "", extensions: list[str] | None = None, fullscreen: bool = True
) -> tuple[Session, InterviewPlan]:
    """Idempotent: a second start from the same tab (reload, double click) returns the running interview. Another
    tab may take over only after the first has been silent for TAB_TAKEOVER_SEC.

    `extensions` and `fullscreen` are the lobby's own checks. They come from the browser, so a determined candidate
    can fake them; they are a gate for honest setups and a record for the recruiter, not proof."""
    async with db.transaction() as s:
        cand = await candidates.load(s, token=token)
    extensions = [x[:60] for x in (extensions or [])][:10]
    async with locked(cand.candidate_id):
        async with db.transaction() as s:
            cand = await candidates.load(s, token=token)
            role = await roles.load(s, cand.role_id)
            if cand.session_id:
                session = await sessions.load(s, cand.session_id)
                plan = await candidates.load_plan(s, session.plan_id)
                if session.state in LIVE and client_id and session.client_id != client_id:
                    last = session.turns[-1].ts if session.turns else session.created_at
                    if (now() - last).total_seconds() < TAB_TAKEOVER_SEC:
                        _check_tab(session, client_id)
                    session.client_id = client_id  # the old tab went quiet: this one takes over
                    await sessions.save(s, session)
                return session, plan
            plan = await candidates.load_plan(s, cand.plan_id) if cand.plan_id else None
        if cand.opens_at and now() < cand.opens_at:
            raise Invalid("This interview has not opened yet")
        if cand.closes_at and now() > cand.closes_at:
            raise Invalid("This interview link has expired. Ask the recruiter for a new one.")
        if role.integrity == "strict":
            if extensions:
                raise Invalid("Turn off these browser extensions for this site, then reload: " + ", ".join(extensions))
            if not fullscreen:
                raise Invalid("This interview runs in full screen. Allow full screen and try again.")
        if await live_count() >= config.MAX_LIVE_INTERVIEWS:
            raise Busy("All interview slots are busy right now. Please try again in a few minutes.")
        plan = plan or await candidates.read_resume(cand)
        session = state_machine.new_session(plan)
        session.client_id = client_id
        session.integrity = [IntegrityEvent(kind="extension", at_sec=0, detail=x) for x in extensions]
        state_machine.start(plan, session)
        cand.status = "in_progress"
        async with db.transaction() as s:
            await sessions.save(s, session)
            await candidates.save(s, cand)
        return session, plan


async def answer(token: str, text: str, client_id: str = "", stt_ms: int = 0) -> tuple[dict, Session, InterviewPlan]:
    if not text.strip():
        raise Invalid("Empty answer")
    cand, _, _ = await _load(token)
    async with locked(cand.candidate_id):
        _, session, plan = await _load(token)  # fresh, under the lock
        _check_tab(session, client_id)
        result = await handle_user_turn(plan, session, text, stt_ms)
        async with db.transaction() as s:
            await sessions.save(s, session)
            if result["done"]:
                jobs.enqueue(s, "evaluate", session.session_id)
    jobs.wake()
    return result, session, plan


async def answer_audio(
    token: str, audio: bytes, filename: str, client_id: str = ""
) -> tuple[str, dict | None, Session, InterviewPlan]:
    """Voice answer: Whisper transcribes it (with role vocabulary as a hint), then the normal turn runs. Returns the
    transcript and the turn result, or no result when nothing usable was said."""
    cand, session, plan = await _load(token)
    _check_tab(session, client_id)
    last_q = next((x.text for x in reversed(session.turns) if x.role == "agent"), "")
    started = time.monotonic()
    # The candidate's full name goes in the hint: Whisper can't spell names it has never seen.
    text = await stt.transcribe(audio, filename, f"Candidate: {cand.name}. {plan.stt_hint} {last_q}")
    stt_ms = int((time.monotonic() - started) * 1000)
    if text.lower().strip(" .!?") in _NOISE or not any(ch.isalnum() for ch in text):
        return "", None, session, plan
    result, session, plan = await answer(token, text, client_id, stt_ms)
    return text, result, session, plan


async def speak(token: str, turn_id: str) -> bytes:
    """Interviewer audio for one agent turn. Generated on request and never stored: the transcript is the record."""
    async with db.transaction() as s:
        cand = await candidates.load(s, token=token)
        found = cand.session_id and await s.scalar(
            select(t.Turn.text).where(
                t.Turn.session_id == cand.session_id, t.Turn.turn_id == turn_id, t.Turn.speaker == "agent"
            )
        )
    if not found:
        raise NotFound("No such turn")
    return await tts.speak(found)


async def end(token: str, client_id: str = "") -> tuple[Session, InterviewPlan]:
    """The candidate ends early: whatever was said is evaluated."""
    cand, _, _ = await _load(token)
    async with locked(cand.candidate_id):
        _, session, plan = await _load(token)
        _check_tab(session, client_id)
        if session.state in LIVE:
            session.state, session.current_section_id = "EVALUATING", None
            async with db.transaction() as s:
                await sessions.save(s, session)
                jobs.enqueue(s, "evaluate", session.session_id)
    jobs.wake()
    return session, plan


async def rate(token: str, rating: ExperienceRating) -> None:
    """The candidate rates the interview once it is over. A second rating replaces the first."""
    cand, _, _ = await _load(token)
    async with locked(cand.candidate_id):
        _, session, _ = await _load(token)
        if session.state in ("READY", *LIVE):
            raise Invalid("You can rate the interview once it has ended")
        session.experience = rating
        async with db.transaction() as s:
            await sessions.save(s, session)


async def record_integrity(token: str, events: list[IntegrityEvent]) -> None:
    """Browser signals from the room, kept with the session. Dropped once the interview is over."""
    cand, _, _ = await _load(token)
    async with locked(cand.candidate_id):
        _, session, _ = await _load(token)
        if session.state not in LIVE:
            return
        session.integrity += events[: integrity.MAX_EVENTS - len(session.integrity)]
        async with db.transaction() as s:
            await sessions.save(s, session)


async def trace(owner: str, candidate_id: str) -> list[dict]:
    """The recruiter's view of how the interview was run: each exchange with the Turn Agent's proposal and what
    code decided."""
    async with db.transaction() as s:
        cand = await candidates.load(s, candidate_id, owner=owner)
        if not cand.session_id:
            return []
        session = await sessions.load(s, cand.session_id)
    out, answer_text = [], None
    for turn in session.turns:
        if turn.role == "user":
            answer_text = turn.text
            continue
        out.append(
            {
                "turn_id": turn.turn_id,
                "at": session.offset(turn),
                "answer": answer_text,
                "said": turn.text,
                "fallback": turn.fallback,
                **(turn.trace or {}),
            }
        )
        answer_text = None
    return out
