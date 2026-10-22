"""Candidates: invite, read the resume (Candidate Prep), decide, release feedback, reset, delete."""

from .. import store
from ..agents import candidate_prep
from ..integrations.llm import LLMError
from ..models import Candidate, InterviewPlan, Role, Session
from . import Invalid, NotFound, get, locks


def bundle(cand: Candidate) -> tuple[Candidate, Session | None, InterviewPlan | None]:
    """A candidate with their interview session and plan, when they exist."""
    s = store.load(Session, cand.session_id) if cand.session_id else None
    plan = store.load(InterviewPlan, cand.plan_id) if cand.plan_id else None
    return cand, s, plan


def by_token(token: str) -> Candidate:
    # shortcut: scans every candidate file, fine for hundreds; Phase 4 replaces this with an indexed query.
    cand = next((c for c in store.load_all(Candidate) if c.token == token), None)
    if not cand:
        raise NotFound("Interview link not found")
    return cand


async def read_resume(cand: Candidate) -> InterviewPlan:
    """Read the resume once: personalised questions, claims to verify, role fit. Never raises on LLM failure: the
    plan is marked prep_status="failed" and the recruiter can retry."""
    plan = await candidate_prep.build_plan(get(Role, cand.role_id), cand)
    store.save(plan)
    if cand.plan_id:
        store.delete(InterviewPlan, cand.plan_id)  # the superseded plan
    cand.plan_id = plan.plan_id
    return plan


async def add(role_id: str, name: str, email: str = "", resume: str = "") -> Candidate:
    get(Role, role_id)
    if not name.strip():
        raise Invalid("Candidate name is required")
    cand = Candidate(role_id=role_id, name=name, email=email, resume=resume)
    if cand.resume.strip():
        await read_resume(cand)
    store.save(cand)
    return cand


async def prepare(candidate_id: str) -> Candidate:
    """Re-read the resume after a failed (or outdated) prep. Only before the interview starts."""
    async with locks[candidate_id]:
        cand = get(Candidate, candidate_id)
        if cand.session_id:
            raise Invalid("The interview has already started")
        if not cand.resume.strip():
            raise Invalid("This candidate has no resume yet")
        plan = await read_resume(cand)
        store.save(cand)
    if plan.prep_status == "failed":
        raise LLMError(f"Could not read the resume: {plan.prep_error}")
    return cand


async def upload_resume(token: str, text: str) -> None:
    cand = by_token(token)
    if cand.session_id:
        raise Invalid("The interview has already started")
    if len(text.strip()) < 100:
        raise Invalid("That resume looks empty. Upload a PDF or paste the text.")
    async with locks[cand.candidate_id]:
        cand.resume = text.strip()[:20000]
        await read_resume(cand)
        store.save(cand)


def decide(candidate_id: str, status: str) -> Candidate:
    cand = get(Candidate, candidate_id)
    if status not in ("advanced", "hold", "rejected"):
        raise Invalid("Decision must be advanced, hold or rejected")
    cand.status = status
    store.save(cand)
    return cand


def release_feedback(candidate_id: str) -> Candidate:
    cand = get(Candidate, candidate_id)
    cand.feedback_released = True
    store.save(cand)
    return cand


async def delete(candidate_id: str) -> None:
    """Remove the candidate and everything about them: resume, interview plan, transcript, report."""
    cand = get(Candidate, candidate_id)
    async with locks[cand.candidate_id]:
        if cand.session_id:
            store.delete(Session, cand.session_id)
        if cand.plan_id:
            store.delete(InterviewPlan, cand.plan_id)
        store.delete(Candidate, cand.candidate_id)


async def reset(candidate_id: str) -> Candidate:
    """Start over on the same link: transcript, report, resume and resume fit are all cleared."""
    cand = get(Candidate, candidate_id)
    async with locks[cand.candidate_id]:
        if cand.session_id:
            store.delete(Session, cand.session_id)
        if cand.plan_id:
            store.delete(InterviewPlan, cand.plan_id)
        cand.session_id, cand.plan_id, cand.resume = None, None, ""
        cand.status, cand.feedback_released = "invited", False
        store.save(cand)
    return cand


def report(candidate_id: str) -> tuple[Candidate, Role, Session | None, InterviewPlan | None]:
    cand = get(Candidate, candidate_id)
    s = get(Session, cand.session_id) if cand.session_id else None
    plan_id = s.plan_id if s else cand.plan_id
    return cand, get(Role, cand.role_id), s, get(InterviewPlan, plan_id) if plan_id else None
