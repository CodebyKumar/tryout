"""Candidates: invite, read the resume (Candidate Prep), decide, release feedback, reset, delete."""

import asyncio
import re
from dataclasses import dataclass

from sqlalchemy import and_, delete, select, update
from sqlalchemy.orm import aliased

from .. import db
from .. import tables as t
from ..agents import candidate_prep
from ..integrations import storage
from ..integrations.llm import LLMError
from ..models import Candidate, InterviewPlan, new_id
from . import Invalid, NotFound, llm_calls, locks, roles, sessions

_Plan = aliased(t.Plan)


@dataclass
class Summary:
    """One candidate row in the recruiter's list."""

    candidate: Candidate
    state: str | None  # interview session state, None before the interview
    score: float | None
    recommendation: str | None
    fit: int | None
    prep_status: str | None
    brief_version: int | None  # which version of the role's brief the candidate's plan was built on


def _with_plan_and_session(q):
    return q.outerjoin(_Plan, and_(_Plan.candidate_id == t.Candidate.id, _Plan.is_current)).outerjoin(
        t.Session, t.Session.plan_id == _Plan.id
    )


async def load(s, candidate_id: str | None = None, token: str | None = None) -> Candidate:
    """By id, or by interview link token (an indexed lookup)."""
    q = _with_plan_and_session(select(t.Candidate, _Plan.id, t.Session.id))
    q = q.where(t.Candidate.id == candidate_id) if candidate_id else q.where(t.Candidate.token == token)
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
    return Candidate(
        candidate_id=row.id,
        token=row.token,
        role_id=row.role_id,
        name=row.name,
        email=row.email,
        resume=resume or "",
        status=row.status,
        plan_id=plan_id,
        session_id=session_id,
        created_at=row.created_at,
    )


async def save(s, cand: Candidate) -> None:
    row = await s.get(t.Candidate, cand.candidate_id)
    if row is None:
        s.add(
            t.Candidate(
                id=cand.candidate_id,
                role_id=cand.role_id,
                name=cand.name,
                email=cand.email,
                token=cand.token,
                status=cand.status,
                created_at=cand.created_at,
            )
        )
        await s.flush()  # no ORM relationships: insert the parent before rows that point at it
        return
    row.name, row.email, row.status = cand.name, cand.email, cand.status


async def load_plan(s, plan_id: str) -> InterviewPlan:
    row = await s.get(t.Plan, plan_id)
    if row is None:
        raise NotFound("Interview plan not found")
    return InterviewPlan.model_validate(row.data)


async def summaries(role_id: str | None = None, candidate_id: str | None = None) -> list[Summary]:
    """The recruiter's list in one query: candidate, current plan, session and current evaluation."""
    q = _with_plan_and_session(
        select(
            t.Candidate,
            t.Session.state,
            t.Evaluation.overall_score,
            t.Evaluation.recommendation,
            _Plan.data,
            _Plan.prep_status,
            t.RoleVersion.version,
        )
    ).outerjoin(t.Evaluation, and_(t.Evaluation.session_id == t.Session.id, t.Evaluation.is_current))
    q = q.outerjoin(t.RoleVersion, t.RoleVersion.id == _Plan.role_version_id)
    q = q.where(t.Candidate.role_id == role_id) if role_id else q.where(t.Candidate.id == candidate_id)
    async with db.transaction() as s:
        rows = (await s.execute(q.order_by(t.Candidate.created_at))).all()
    out = []
    for c, state, score, rec, plan, prep, version in rows:
        cand = Candidate(
            candidate_id=c.id,
            token=c.token,
            role_id=c.role_id,
            name=c.name,
            email=c.email,
            status=c.status,
            created_at=c.created_at,
        )
        fit = (plan or {}).get("fit", {}).get("score")
        out.append(Summary(cand, state, score, rec, fit, prep, version))
    return out


async def summary(candidate_id: str) -> Summary:
    found = await summaries(candidate_id=candidate_id)
    if not found:
        raise NotFound("Candidate not found")
    return found[0]


async def read_resume(cand: Candidate) -> InterviewPlan:
    """Read the resume once: personalised questions, claims to verify, role fit. Never raises on LLM failure: the
    plan is marked prep_status="failed" and the recruiter can retry. The plan is built on the role's current
    version and replaces the candidate's current plan."""
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


# Shape check only (something@domain.tld); delivery is never verified because links are shared by hand.
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


async def add(role_id: str, name: str, email: str = "", resume: str = "") -> Candidate:
    name, email = name.strip(), email.strip().lower()
    if not name:
        raise Invalid("Candidate name is required")
    if email and not _EMAIL.fullmatch(email):
        raise Invalid(f"{email} is not a valid email address")
    cand = Candidate(role_id=role_id, name=name, email=email, resume=resume)
    async with db.transaction() as s:
        await roles.load(s, role_id)
        taken = email and await s.scalar(
            select(t.Candidate.id).where(t.Candidate.role_id == role_id, t.Candidate.email == email)
        )
        if taken:
            raise Invalid(f"{email} is already a candidate for this role")
        await save(s, cand)
        if resume.strip():
            await _store_resume(s, cand, resume.strip())
    if cand.resume.strip():
        await read_resume(cand)
    return cand


async def prepare(candidate_id: str) -> Candidate:
    """Re-read the resume after a failed (or outdated) prep. Only before the interview starts."""
    async with locks[candidate_id]:
        async with db.transaction() as s:
            cand = await load(s, candidate_id)
        if cand.session_id:
            raise Invalid("The interview has already started")
        if not cand.resume.strip():
            raise Invalid("This candidate has no resume yet")
        plan = await read_resume(cand)
    if plan.prep_status == "failed":
        raise LLMError(f"Could not read the resume: {plan.prep_error}")
    return cand


async def upload_resume(token: str, text: str, filename: str | None = None, raw: bytes | None = None) -> None:
    async with db.transaction() as s:
        cand = await load(s, token=token)
    if cand.session_id:
        raise Invalid("The interview has already started")
    if len(text.strip()) < 100:
        raise Invalid("That resume looks empty. Upload a PDF or paste the text.")
    async with locks[cand.candidate_id]:
        cand.resume = text.strip()[:20000]
        async with db.transaction() as s:
            await _store_resume(s, cand, cand.resume, filename, raw)
        await read_resume(cand)


async def decide(candidate_id: str, status: str) -> None:
    if status not in ("advanced", "hold", "rejected"):
        raise Invalid("Decision must be advanced, hold or rejected")
    async with db.transaction() as s:
        cand = await load(s, candidate_id)
        cand.status = status
        await save(s, cand)


async def delete_candidate(candidate_id: str) -> None:
    """Remove the candidate and everything about them: resumes, plans, transcripts, reports (foreign keys cascade)."""
    async with locks[candidate_id], db.transaction() as s:
        await load(s, candidate_id)
        await s.execute(delete(t.Candidate).where(t.Candidate.id == candidate_id))


async def reset(candidate_id: str) -> None:
    """Start over on the same link: transcript, report, resume and resume fit are all cleared."""
    async with locks[candidate_id], db.transaction() as s:
        cand = await load(s, candidate_id)
        await s.execute(delete(t.Plan).where(t.Plan.candidate_id == candidate_id))  # cascades to sessions and turns
        await s.execute(delete(t.Document).where(t.Document.candidate_id == candidate_id))
        cand.status = "invited"
        await save(s, cand)


async def report(candidate_id: str):
    """Everything the recruiter's report page shows: candidate, role, interview session and plan."""
    async with db.transaction() as s:
        cand = await load(s, candidate_id)

    async def read(fn, key):  # each part on its own connection, so the database round trips overlap
        if not key:
            return None
        async with db.transaction() as s:
            return await fn(s, key)

    role, session, plan = await asyncio.gather(
        read(roles.load, cand.role_id), read(sessions.load, cand.session_id), read(load_plan, cand.plan_id)
    )
    return cand, role, session, plan
