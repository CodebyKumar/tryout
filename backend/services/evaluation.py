"""Evaluation: run the Evaluator on a finished interview, in the background or on request. Every run is kept."""

import asyncio
import logging

from sqlalchemy import update

from .. import db
from .. import tables as t
from ..agents import evaluator
from ..integrations.llm import LLMError
from ..models import new_id
from . import Invalid, candidates, locks, roles, sessions

log = logging.getLogger("evaluation")
_tasks: set[asyncio.Task] = set()  # shortcut: lost on restart (audit A3); Phase 5 moves this to the jobs table


async def run(candidate_id: str, session_id: str) -> None:
    """Never raises on LLM failure: the session is marked EVAL_FAILED with the reason; the transcript and any
    earlier report are kept. Scores against the brief version the candidate was interviewed on (audit A2)."""
    async with locks[f"eval_{session_id}"]:
        async with db.transaction() as s:
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
            if cand.status in ("invited", "in_progress"):
                cand.status = "completed"
                await candidates.save(s, cand)


def run_later(candidate_id: str, session_id: str) -> None:
    task = asyncio.create_task(run(candidate_id, session_id))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def rerun(candidate_id: str) -> None:
    async with db.transaction() as s:
        cand = await candidates.load(s, candidate_id)
    if not cand.session_id:
        raise Invalid("This candidate has not been interviewed yet")
    await run(candidate_id, cand.session_id)
    async with db.transaction() as s:
        session = await sessions.load(s, cand.session_id)
    if session.state == "EVAL_FAILED":
        raise LLMError(f"Evaluation failed: {session.eval_error}")
