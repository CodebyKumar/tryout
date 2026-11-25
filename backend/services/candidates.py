"""Candidates: invite and schedule, read the resume (Candidate Prep, as a job), decide, reset, delete."""

import asyncio
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import and_, delete, exists, select, update
from sqlalchemy.orm import aliased

from .. import config, db
from .. import tables as t
from ..agents import candidate_prep
from ..integrations import storage
from ..integrations.llm import LLMError
from ..models import Candidate, InterviewPlan, new_id, now
from . import Invalid, NotFound, jobs, llm_calls, locked, roles, sessions

_Plan = aliased(t.Plan)


@dataclass
class Summary:
    """One candidate row in the recruiter's list."""

    candidate: Candidate
    state: str | None  # interview session state, None before the interview
    score: float | None
    recommendation: str | None
    fit: int | None
    prep_status: str | None  # ok / failed (retried in the background) / skipped / pending (first read queued) / None
    brief_version: int | None  # which version of the role's brief the candidate's plan was built on


def _with_plan_and_session(q):
    return q.outerjoin(_Plan, and_(_Plan.candidate_id == t.Candidate.id, _Plan.is_current)).outerjoin(
        t.Session, t.Session.plan_id == _Plan.id
    )


def _candidate(row: t.Candidate, **extra) -> Candidate:
    return Candidate(
        candidate_id=row.id,
        token=row.token,
        role_id=row.role_id,
        name=row.name,
        email=row.email,
        status=row.status,
        decision=row.decision,
        opens_at=row.opens_at,
        closes_at=row.closes_at,
        created_at=row.created_at,
        **extra,
    )


async def load(s, candidate_id: str | None = None, token: str | None = None, owner: str | None = None) -> Candidate:
    """By id, or by interview link token (an indexed lookup). With owner, only that recruiter's candidates exist."""
    q = _with_plan_and_session(select(t.Candidate, _Plan.id, t.Session.id))
    q = q.where(t.Candidate.id == candidate_id) if candidate_id else q.where(t.Candidate.token == token)
    if owner is not None:
        q = q.join(t.Role, t.Role.id == t.Candidate.role_id).where(t.Role.recruiter_id == owner)
    found = (await s.execute(q)).first()
    if not found:
        raise NotFound("Candidate not found" if candidate_id else "Interview link not found")
    row, plan_id, session_id = found
    resume = await s.scalar(
        select(t.Document.text)
        .where(t.Document.candidate_id == row.id, t.Document.kind == "resume")
        .order_by(t.Document.created_at.desc())
        .limit(1)
    )
    return _candidate(row, resume=resume or "", plan_id=plan_id, session_id=session_id)


async def save(s, cand: Candidate) -> None:
    row = await s.get(t.Candidate, cand.candidate_id)
    if row is None:
        row = t.Candidate(id=cand.candidate_id, role_id=cand.role_id, created_at=cand.created_at)
        s.add(row)
    row.name, row.email, row.token, row.status, row.decision = (
        cand.name,
        cand.email,
        cand.token,
        cand.status,
        cand.decision,
    )
    row.opens_at, row.closes_at = cand.opens_at, cand.closes_at
    await s.flush()  # no ORM relationships: insert the parent before rows that point at it


async def load_plan(s, plan_id: str) -> InterviewPlan:
    row = await s.get(t.Plan, plan_id)
    if row is None:
        raise NotFound("Interview plan not found")
    return InterviewPlan.model_validate(row.data)


async def summaries(owner: str, role_id: str | None = None, candidate_id: str | None = None) -> list[Summary]:
    """The recruiter's list in one query: candidate, current plan, session, current evaluation, queued prep."""
    prep_queued = exists().where(
        t.Job.kind == "prepare", t.Job.target_id == t.Candidate.id, t.Job.status.in_(("queued", "running"))
    )
    q = _with_plan_and_session(
        select(
            t.Candidate,
            t.Session.state,
            t.Evaluation.overall_score,
            t.Evaluation.recommendation,
            _Plan.data,
            _Plan.prep_status,
            t.RoleVersion.version,
            prep_queued,
        )
    ).outerjoin(t.Evaluation, and_(t.Evaluation.session_id == t.Session.id, t.Evaluation.is_current))
    q = q.outerjoin(t.RoleVersion, t.RoleVersion.id == _Plan.role_version_id)
    q = q.join(t.Role, t.Role.id == t.Candidate.role_id).where(t.Role.recruiter_id == owner)
    q = q.where(t.Candidate.role_id == role_id) if role_id else q.where(t.Candidate.id == candidate_id)
    async with db.transaction() as s:
        rows = (await s.execute(q.order_by(t.Candidate.created_at))).all()
    out = []
    for c, state, score, rec, plan, prep, version, queued in rows:
        fit = (plan or {}).get("fit", {}).get("score")
        out.append(Summary(_candidate(c), state, score, rec, fit, prep or ("pending" if queued else None), version))
    return out


async def summary(owner: str, candidate_id: str) -> Summary:
    found = await summaries(owner, candidate_id=candidate_id)
    if not found:
        raise NotFound("Candidate not found")
    return found[0]


# ---------- Resume ----------


async def read_resume(cand: Candidate) -> InterviewPlan:
    """Read the resume once: personalised questions, claims to verify, role fit. Never raises on LLM failure: the
    plan is marked prep_status="failed" and can be retried. The plan is built on the role's current version and
    replaces the candidate's current plan."""
    async with db.transaction() as s:
        role = await roles.load(s, cand.role_id)
    plan = await candidate_prep.build_plan(role, cand)
    async with db.transaction() as s:
        await s.execute(update(t.Plan).where(t.Plan.candidate_id == cand.candidate_id).values(is_current=False))
        s.add(
            t.Plan(
                id=plan.plan_id,
                candidate_id=cand.candidate_id,
                role_version_id=plan.role_version_id,
                prep_status=plan.prep_status,
                data=plan.model_dump(mode="json", exclude={"usage"}),
            )
        )
        s.add_all(llm_calls(plan.usage, candidate_id=cand.candidate_id))
    cand.plan_id = plan.plan_id
    return plan


async def prepare_job(candidate_id: str) -> bool:
    """Job handler: read the resume of a newly added candidate. Nothing to do once the interview has started."""
    async with locked(candidate_id):
        async with db.transaction() as s:
            try:
                cand = await load(s, candidate_id)
            except NotFound:
                return True  # deleted meanwhile
        if cand.session_id or not cand.resume.strip():
            return True
        return (await read_resume(cand)).prep_status != "failed"


jobs.HANDLERS["prepare"] = prepare_job


async def prep_pending(candidate_id: str) -> bool:
    """A resume read for this candidate is queued or running."""
    async with db.transaction() as s:
        return bool(
            await s.scalar(
                select(t.Job.id).where(
                    t.Job.kind == "prepare", t.Job.target_id == candidate_id, t.Job.status.in_(("queued", "running"))
                )
            )
        )


async def _store_resume(s, cand: Candidate, text: str, filename: str | None = None, raw: bytes | None = None) -> None:
    path = await storage.upload(f"resumes/{cand.candidate_id}/{filename}", raw) if raw and filename else None
    s.add(
        t.Document(
            id=new_id("d"),
            kind="resume",
            candidate_id=cand.candidate_id,
            filename=filename,
            storage_path=path,
            text=text,
        )
    )


# ---------- Invite and schedule ----------

# Shape check only (something@domain.tld); delivery is never verified because invites are sent by the recruiter.
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


def _window(opens_at: datetime | None, closes_at: datetime | None) -> tuple[datetime | None, datetime]:
    """When the link works. No end given: LINK_DAYS after it opens (or from now)."""
    closes_at = closes_at or (opens_at or now()) + timedelta(days=config.LINK_DAYS)
    if opens_at and closes_at <= opens_at:
        raise Invalid("The interview window must end after it starts")
    if closes_at <= now():
        raise Invalid("The interview window must end in the future")
    return opens_at, closes_at


def _details(name: str, email: str) -> tuple[str, str]:
    name, email = name.strip(), email.strip().lower()
    if not name:
        raise Invalid("Candidate name is required")
    if email and not _EMAIL.fullmatch(email):
        raise Invalid(f"{email} is not a valid email address")
    return name[:120], email


async def add(
    owner: str,
    role_id: str,
    name: str,
    email: str = "",
    resume: str = "",
    opens_at: datetime | None = None,
    closes_at: datetime | None = None,
) -> Candidate:
    name, email = _details(name, email)
    opens_at, closes_at = _window(opens_at, closes_at)
    cand = Candidate(role_id=role_id, name=name, email=email, opens_at=opens_at, closes_at=closes_at)
    async with db.transaction() as s:
        await roles.load(s, role_id, owner)
        taken = email and await s.scalar(
            select(t.Candidate.id).where(t.Candidate.role_id == role_id, t.Candidate.email == email)
        )
        if taken:
            raise Invalid(f"{email} is already a candidate for this role")
        await save(s, cand)
        if resume.strip():
            await _store_resume(s, cand, resume.strip()[:20000])
            jobs.enqueue(s, "prepare", cand.candidate_id)
    jobs.wake()
    return cand


async def edit(
    owner: str, candidate_id: str, name: str, email: str, opens_at: datetime | None, closes_at: datetime | None
) -> None:
    """Change the name, email or interview window (to reschedule, or to extend an expired link)."""
    name, email = _details(name, email)
    async with locked(candidate_id), db.transaction() as s:
        cand = await load(s, candidate_id, owner=owner)
        cand.name, cand.email = name, email
        if not cand.session_id:  # the window only matters before the interview starts
            cand.opens_at, cand.closes_at = _window(opens_at, closes_at)
        await save(s, cand)


async def prepare(owner: str, candidate_id: str) -> None:
    """The recruiter retries a failed resume read. Runs in the request, so the result is known at once."""
    async with locked(candidate_id):
        async with db.transaction() as s:
            cand = await load(s, candidate_id, owner=owner)
        if cand.session_id:
            raise Invalid("The interview has already started")
        if not cand.resume.strip():
            raise Invalid("This candidate has no resume yet")
        plan = await read_resume(cand)
    if plan.prep_status == "failed":
        raise LLMError(f"Could not read the resume: {plan.prep_error}")


async def upload_resume(token: str, text: str, filename: str | None = None, raw: bytes | None = None) -> None:
    """The candidate adds their resume in the lobby. Read at once: the interview starts right after."""
    async with db.transaction() as s:
        cand = await load(s, token=token)
    if cand.session_id:
        raise Invalid("The interview has already started")
    if len(text.strip()) < 100:
        raise Invalid("That resume looks empty. Upload a PDF or paste the text.")
    async with locked(cand.candidate_id):
        cand.resume = text.strip()[:20000]
        async with db.transaction() as s:
            await _store_resume(s, cand, cand.resume, filename, raw)
        await read_resume(cand)


# ---------- Decide, reset, delete ----------


async def decide(owner: str, candidate_id: str, decision: str | None) -> None:
    """The human decides, and only after there is a report to decide on. Every change is logged (audit D10)."""
    if decision not in ("advanced", "hold", "rejected", None):
        raise Invalid("Decision must be advanced, hold or rejected")
    async with locked(candidate_id), db.transaction() as s:
        cand = await load(s, candidate_id, owner=owner)
        state = await s.scalar(select(t.Session.state).where(t.Session.id == cand.session_id))
        if state != "DONE":
            raise Invalid("Decide once the report is ready")
        if cand.decision != decision:
            s.add(
                t.Decision(
                    candidate_id=candidate_id, recruiter_id=owner, from_decision=cand.decision, to_decision=decision
                )
            )
            cand.decision = decision
            await save(s, cand)


async def delete_candidate(owner: str, candidate_id: str) -> None:
    """Remove the candidate and everything about them: resumes, plans, transcripts, reports (foreign keys cascade)."""
    async with locked(candidate_id), db.transaction() as s:
        await load(s, candidate_id, owner=owner)
        await s.execute(delete(t.Candidate).where(t.Candidate.id == candidate_id))


async def reset(owner: str, candidate_id: str) -> None:
    """Start over with a new link: the old link stops working; transcript, report, resume and decision are cleared."""
    async with locked(candidate_id), db.transaction() as s:
        cand = await load(s, candidate_id, owner=owner)
        await s.execute(delete(t.Plan).where(t.Plan.candidate_id == candidate_id))  # cascades to sessions and turns
        await s.execute(delete(t.Document).where(t.Document.candidate_id == candidate_id))
        cand.token, cand.status, cand.decision = secrets.token_urlsafe(16), "invited", None
        if cand.closes_at and cand.closes_at <= now():
            cand.opens_at, cand.closes_at = _window(None, None)
        await save(s, cand)


async def report(owner: str, candidate_id: str):
    """Everything the report page shows: candidate, role, interview session, plan and decision history."""
    async with db.transaction() as s:
        cand = await load(s, candidate_id, owner=owner)
        history = (
            await s.scalars(
                select(t.Decision).where(t.Decision.candidate_id == candidate_id).order_by(t.Decision.id.desc())
            )
        ).all()

    async def read(fn, key):  # each part on its own connection, so the database round trips overlap
        if not key:
            return None
        async with db.transaction() as s:
            return await fn(s, key)

    role, session, plan = await asyncio.gather(
        read(roles.load, cand.role_id), read(sessions.load, cand.session_id), read(load_plan, cand.plan_id)
    )
    decisions = [{"from": d.from_decision, "to": d.to_decision, "at": d.created_at} for d in history]
    return cand, role, session, plan, decisions
