"""Roles: build the brief with the Role Compiler, change it with Role Refine or by hand. Every brief is validated
the same way."""

from .. import config, store
from ..agents import role_compiler, role_refine
from ..models import Candidate, InterviewPlan, Role, Session
from . import Invalid, get
from .candidates import bundle


async def _compiled(coro) -> Role:
    try:
        return await coro
    except ValueError as e:  # the brief could not be made valid (no sections or no criteria)
        raise Invalid(str(e)) from e


async def create(title: str, jd: str, notes: str = "", company: str = "", time_budget_sec: int = 0) -> Role:
    if len(jd.strip()) < 40:
        raise Invalid("Paste the full job description")
    role = Role(
        title=title, jd=jd, notes=notes, company=company, time_budget_sec=time_budget_sec or config.TIME_BUDGET_SEC
    )
    role = await _compiled(role_compiler.compile_role(role))
    store.save(role)
    return role


async def from_document(text: str, title: str = "", time_budget_sec: int = 0) -> Role:
    """One hiring document (JD, guidelines, rubric, notes); the AI builds the whole brief."""
    if len(text.strip()) < 80:
        raise Invalid("The document is too short. Include at least the job description.")
    role = Role(
        title=title.strip() or "Untitled role",
        jd=text.strip()[:20000],
        time_budget_sec=time_budget_sec or config.TIME_BUDGET_SEC,
    )
    role = await _compiled(role_compiler.compile_role(role, from_document=True, fixed_length=bool(time_budget_sec)))
    store.save(role)
    return role


async def refine(role_id: str, instruction: str) -> Role:
    if not instruction.strip():
        raise Invalid("Describe the change you want")
    role = await _compiled(role_refine.refine_role(get(Role, role_id), instruction))
    store.save(role)
    return role


def update(role_id: str, changes: dict) -> Role:
    """Manual edit. Same checks as AI-written briefs: unique ids, weights in range, sections fit the length."""
    role = get(Role, role_id)
    for k, v in changes.items():
        setattr(role, k, v)
    try:
        brief = role_compiler.CompiledRole.model_validate(role.model_dump(include={"sections", "criteria"}))
        role = role_compiler.apply_compiled(role, brief)
    except ValueError:
        raise Invalid("A role needs at least one section and one criterion") from None
    store.save(role)
    return role


def list_all() -> list[tuple[Role, list[Candidate]]]:
    cands = store.load_all(Candidate)
    roles = sorted(store.load_all(Role), key=lambda r: r.created_at, reverse=True)
    return [(r, [c for c in cands if c.role_id == r.role_id]) for r in roles]


def with_candidates(role_id: str) -> tuple[Role, list[tuple[Candidate, Session | None, InterviewPlan | None]]]:
    role = get(Role, role_id)
    return role, [bundle(c) for c in store.load_all(Candidate) if c.role_id == role_id]
