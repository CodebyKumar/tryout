"""Background work that survives a restart (audit A3): reading a resume ("prepare") and scoring an interview
("evaluate"). Each job is a row in `jobs`; worker tasks in this process claim one at a time, run it, then delete it
(done) or schedule a retry. The same loop ends abandoned interviews.

Claiming is safe with several workers or servers: a job moves from queued to running in one conditional UPDATE,
so only one claimer wins (Postgres also skips rows another transaction holds, SKIP LOCKED).
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import timedelta

from sqlalchemy import select, update

from .. import config, db
from .. import tables as t
from ..models import now

log = logging.getLogger("jobs")

WORKERS = 2  # LLM jobs wait on the network; two overlap without hitting the free tier's per-minute limit
MAX_ATTEMPTS = 3
POLL_SEC = 2.0
SWEEP_SEC = 60.0

# kind -> handler(target_id) -> True when done, False to retry. Filled in by the services that own the work, so
# this module does not import them (they import it to enqueue).
HANDLERS: dict[str, Callable[[str], Awaitable[bool]]] = {}
_wake: asyncio.Event | None = None


def enqueue(s, kind: str, target_id: str) -> None:
    """Add a job inside the caller's transaction (so it exists only if their write commits). Call wake() after."""
    s.add(t.Job(kind=kind, target_id=target_id))


def wake() -> None:
    if _wake:
        _wake.set()


async def _claim() -> t.Job | None:
    async with db.transaction() as s:
        job = await s.scalar(
            select(t.Job)
            .where(t.Job.status == "queued", t.Job.run_after <= now())
            .order_by(t.Job.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if job is None:
            return None
        won = await s.execute(
            update(t.Job)
            .where(t.Job.id == job.id, t.Job.status == "queued")
            .values(status="running", attempts=t.Job.attempts + 1)
        )
        if won.rowcount != 1:
            return None
        await s.refresh(job)
        return job


async def run_one() -> bool:
    """Claim and run one due job. Returns False when there was none."""
    job = await _claim()
    if job is None:
        return False
    try:
        ok, error = await HANDLERS[job.kind](job.target_id), ""
    except Exception as e:  # a bug or an outage: keep the error on the job and retry like any failure
        log.exception("job %s %s failed", job.kind, job.target_id)
        ok, error = False, f"{type(e).__name__}: {e}"
    async with db.transaction() as s:
        row = await s.get(t.Job, job.id)
        if ok:
            await s.delete(row)
        elif row.attempts < MAX_ATTEMPTS:
            row.status, row.error = "queued", error or "failed, will retry"
            row.run_after = now() + timedelta(seconds=30 * row.attempts)
        else:
            row.status, row.error = "failed", error or "failed"
    return True


async def requeue_running() -> None:
    """After a crash or restart, jobs left running are queued again.
    shortcut: assumes one server; with several, requeue only jobs whose claim is older than the longest job."""
    async with db.transaction() as s:
        await s.execute(update(t.Job).where(t.Job.status == "running").values(status="queued"))


SWEEPS: list[Callable[[], Awaitable[None]]] = []  # periodic checks (the idle interview sweep)


async def _worker(n: int) -> None:
    last_sweep = 0.0
    while True:
        try:
            while await run_one():
                pass
            if n == 0 and time.monotonic() - last_sweep > SWEEP_SEC:
                last_sweep = time.monotonic()
                for sweep in SWEEPS:
                    await sweep()
        except Exception:  # the database is unreachable for a moment: try again on the next tick
            log.exception("jobs loop error")
        try:
            await asyncio.wait_for(_wake.wait(), POLL_SEC)
        except TimeoutError:
            pass
        _wake.clear()


async def start() -> list[asyncio.Task]:
    global _wake
    _wake = asyncio.Event()  # created on the running loop (tests start a new loop per app)
    await requeue_running()
    return [asyncio.create_task(_worker(n)) for n in range(WORKERS)]


async def counts() -> dict:
    """Queued, running and failed jobs, for the admin page."""
    async with db.transaction() as s:
        rows = (await s.execute(select(t.Job.status, t.Job.kind, t.Job.error))).all()
    return {
        "queued": sum(1 for r in rows if r.status == "queued"),
        "running": sum(1 for r in rows if r.status == "running"),
        "failed": [{"kind": r.kind, "error": r.error} for r in rows if r.status == "failed"][:20],
        "idle_minutes": config.IDLE_MINUTES,
    }
