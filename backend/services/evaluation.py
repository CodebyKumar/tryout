"""Evaluation: run the Evaluator on a finished interview, as a background job or on the recruiter's request.
Every run is kept; the latest good one is current."""

import logging
from datetime import timedelta

from sqlalchemy import select, update

from .. import config, db
from .. import tables as t
from ..agents import evaluator
from ..integrations.llm import LLMError
from ..models import new_id, now
from . import Conflict, Invalid, candidates, jobs, locked, roles, sessions

log = logging.getLogger("evaluation")


async def run(session_id: str) -> bool:
    """Score one interview. Never raises on LLM failure: the session is marked EVAL_FAILED with the reason, and the
    transcript and any earlier report are kept. Returns False on failure so the job is retried. Scores against the
    brief version the candidate was interviewed on (audit A2).

    Holds the candidate's lock, so a reset or delete waits for it, and a run after a delete finds nothing (A4)."""
    async with db.transaction() as s:
        row = await s.get(t.Session, session_id)
    if row is None:
        return True  # deleted or reset meanwhile: nothing left to score
    candidate_id = row.data["candidate_id"]
    async with locked(candidate_id):
        async with db.transaction() as s:
            if await s.get(t.Session, session_id) is None:
                return True
            session = await sessions.load(s, session_id)
            plan = await candidates.load_plan(s, session.plan_id)
            role = await roles.load_version(s, plan.role_version_id)
            session.state = "EVALUATING"
            await sessions.save(s, session)
        try:
            report, error = await evaluator.evaluate(role, plan, session), ""
            session.state, session.eval_error = "DONE", ""
        except (LLMError, ValueError) as e:
            log.error("evaluation failed for %s: %s", candidate_id, e)
            report, error = None, str(e)
            session.state, session.eval_error = "EVAL_FAILED", error
        async with db.transaction() as s:
            await sessions.save(s, session)
            if report:
                await s.execute(
                    update(t.Evaluation).where(t.Evaluation.session_id == session_id).values(is_current=False)
                )
            s.add(
                t.Evaluation(
                    id=new_id("e"),
                    session_id=session_id,
                    status="ok" if report else "failed",
                    error=error or None,
                    overall_score=report.overall_score if report else None,
                    recommendation=report.recommendation if report else None,
                    report=report.model_dump(mode="json") if report else None,
                    model=report.model if report else None,
                    prompt_version=report.prompt_version if report else None,
                    is_current=bool(report),
                )
            )
            cand = await candidates.load(s, candidate_id)
            cand.status = "completed"
            await candidates.save(s, cand)
    return report is not None


jobs.HANDLERS["evaluate"] = run


async def rerun(owner: str, candidate_id: str) -> None:
    """The recruiter asks for a fresh score now (after a failure, or after a prompt change). Runs in the request."""
    async with db.transaction() as s:
        cand = await candidates.load(s, candidate_id, owner=owner)
    if not cand.session_id:
        raise Invalid("This candidate has not been interviewed yet")
    async with db.transaction() as s:
        session = await sessions.load(s, cand.session_id)
    if session.state in ("INTERVIEWING", "WRAPUP"):
        raise Invalid("The interview is still running")
    if not await run(cand.session_id):
        async with db.transaction() as s:
            session = await sessions.load(s, cand.session_id)
        raise LLMError(f"Evaluation failed: {session.eval_error}")


async def sweep_idle() -> None:
    """End interviews nobody has answered for IDLE_MINUTES (closed tab, lost network) and queue their evaluation."""
    cutoff = now() - timedelta(minutes=config.IDLE_MINUTES)
    async with db.transaction() as s:
        idle = (
            await s.scalars(
                select(t.Session.id).where(
                    t.Session.state.in_(("INTERVIEWING", "WRAPUP")), t.Session.last_activity_at < cutoff
                )
            )
        ).all()
    for session_id in idle:
        try:
            async with db.transaction() as s:
                session = await sessions.load(s, session_id)
                session.state, session.current_section_id = "EVALUATING", None
                await sessions.save(s, session)
                jobs.enqueue(s, "evaluate", session_id)
            log.info("ended idle interview %s", session_id)
        except Conflict:  # an answer arrived meanwhile: the interview is not idle after all
            log.info("idle sweep skipped %s", session_id)
    if idle:
        jobs.wake()


jobs.SWEEPS.append(sweep_idle)
