"""Evaluation: run the Evaluator on a finished interview, in the background or on request."""

import asyncio
import logging

from .. import store
from ..agents import evaluator
from ..integrations.llm import LLMError
from ..models import Candidate, InterviewPlan, Role, Session
from . import get, locks

log = logging.getLogger("evaluation")
_tasks: set[asyncio.Task] = set()  # shortcut: lost on restart (audit A3); Phase 5 moves this to a jobs table


async def run(cand: Candidate, s: Session) -> None:
    """Never raises on LLM failure: the session is marked EVAL_FAILED with the reason, and the transcript is kept."""
    async with locks[f"eval_{s.session_id}"]:
        role, plan = get(Role, cand.role_id), get(InterviewPlan, s.plan_id)
        s.state = "EVALUATING"
        store.save(s)
        try:
            s.report = await evaluator.evaluate(role, plan, s)
            s.state, s.eval_error = "DONE", ""
        except (LLMError, ValueError) as e:
            log.error("evaluation failed for %s: %s", cand.candidate_id, e)
            s.state, s.eval_error = "EVAL_FAILED", str(e)
        store.save(s)
        cand = get(Candidate, cand.candidate_id)
        if cand.status in ("invited", "in_progress"):
            cand.status = "completed"
            store.save(cand)


def run_later(cand: Candidate, s: Session) -> None:
    task = asyncio.create_task(run(cand, s))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def rerun(candidate_id: str) -> None:
    cand = get(Candidate, candidate_id)
    s = get(Session, cand.session_id)
    await run(cand, s)
    if s.state == "EVAL_FAILED":
        raise LLMError(f"Evaluation failed: {s.eval_error}")
