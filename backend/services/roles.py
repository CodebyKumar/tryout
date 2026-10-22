"""Roles: build the brief with the Role Compiler, change it with Role Refine or by hand. Every change adds an
immutable version (audit A2): candidates keep the brief their plan was built on."""

from sqlalchemy import select

from .. import config, db
from .. import tables as t
from ..agents import role_compiler, role_refine
from ..models import Criterion, Role, Section, new_id
from . import Invalid, NotFound, llm_calls


def _role(row: t.Role, v: t.RoleVersion) -> Role:
    return Role(
        role_id=row.id,
        title=row.title,
        company=row.company,
        jd=v.jd,
        notes=v.notes,
        time_budget_sec=v.time_budget_sec,
        sections=[Section.model_validate(x) for x in v.brief["sections"]],
        criteria=[Criterion.model_validate(x) for x in v.brief["criteria"]],
        version=v.version,
        version_id=v.id,
        created_at=row.created_at,
    )


async def load(s, role_id: str) -> Role:
    """The role at its current version."""
    row = await s.get(t.Role, role_id)
    if row is None:
        raise NotFound("Role not found")
    v = await s.scalar(
        select(t.RoleVersion).where(t.RoleVersion.role_id == role_id, t.RoleVersion.version == row.current_version)
    )
    return _role(row, v)


async def load_version(s, version_id: str) -> Role:
    """The role exactly as one version had it: what a candidate's plan was built on."""
    v = await s.get(t.RoleVersion, version_id)
    return _role(await s.get(t.Role, v.role_id), v)


async def save_version(s, role: Role, source: str, instruction: str | None = None) -> Role:
    row = await s.get(t.Role, role.role_id)
    if row is None:
        row = t.Role(
            id=role.role_id, title=role.title, company=role.company, current_version=0, created_at=role.created_at
        )
        s.add(row)
        await s.flush()  # no ORM relationships: insert the parent before rows that point at it
        if role.document:
            s.add(t.Document(id=new_id("d"), kind="role_source", role_id=role.role_id, text=role.document))
    row.title, row.company, row.current_version = role.title, role.company, row.current_version + 1
    role.version, role.version_id = row.current_version, new_id("v")
    brief = {"sections": [x.model_dump() for x in role.sections], "criteria": [x.model_dump() for x in role.criteria]}
    s.add(
        t.RoleVersion(
            id=role.version_id,
            role_id=role.role_id,
            version=role.version,
            source=source,
            jd=role.jd,
            notes=role.notes,
            time_budget_sec=role.time_budget_sec,
            brief=brief,
            instruction=instruction,
        )
    )
    s.add_all(llm_calls(role.usage, role_id=role.role_id))
    role.usage = []
    return role


async def _compiled(coro) -> Role:
    try:
        return await coro
    except ValueError as e:  # the brief could not be made valid (no sections or no criteria)
        raise Invalid(str(e)) from e


async def _create(role: Role, **compile_kw) -> Role:
    role = await _compiled(role_compiler.compile_role(role, **compile_kw))
    async with db.transaction() as s:
        return await save_version(s, role, "compile")


async def create(title: str, jd: str, notes: str = "", company: str = "", time_budget_sec: int = 0) -> Role:
    if len(jd.strip()) < 40:
        raise Invalid("Paste the full job description")
    budget = time_budget_sec or config.TIME_BUDGET_SEC
    return await _create(Role(title=title, jd=jd, notes=notes, company=company, time_budget_sec=budget))


async def from_document(text: str, title: str = "", time_budget_sec: int = 0) -> Role:
    """One hiring document (JD, guidelines, rubric, notes); the AI builds the whole brief."""
    if len(text.strip()) < 80:
        raise Invalid("The document is too short. Include at least the job description.")
    role = Role(
        title=title.strip() or "Untitled role",
        jd=text.strip()[:20000],
        time_budget_sec=time_budget_sec or config.TIME_BUDGET_SEC,
    )
    return await _create(role, from_document=True, fixed_length=bool(time_budget_sec))


async def refine(role_id: str, instruction: str) -> Role:
    if not instruction.strip():
        raise Invalid("Describe the change you want")
    async with db.transaction() as s:
        role = await load(s, role_id)
    role = await _compiled(role_refine.refine_role(role, instruction))
    async with db.transaction() as s:
        return await save_version(s, role, "refine", instruction)


async def update(role_id: str, changes: dict) -> Role:
    """Manual edit. Same checks as AI-written briefs: unique ids, weights in range, sections fit the length."""
    async with db.transaction() as s:
        role = await load(s, role_id)
        for k, v in changes.items():
            setattr(role, k, v)
        try:
            brief = role_compiler.CompiledRole.model_validate(role.model_dump(include={"sections", "criteria"}))
            role = role_compiler.apply_compiled(role, brief)
        except ValueError:
            raise Invalid("A role needs at least one section and one criterion") from None
        return await save_version(s, role, "manual")


async def list_all() -> list[tuple[Role, list[str]]]:
    """Every role at its current version, newest first, with its candidates' statuses."""
    async with db.transaction() as s:
        rows = await s.execute(
            select(t.Role, t.RoleVersion)
            .join(
                t.RoleVersion, (t.RoleVersion.role_id == t.Role.id) & (t.RoleVersion.version == t.Role.current_version)
            )
            .order_by(t.Role.created_at.desc())
        )
        statuses = await s.execute(select(t.Candidate.role_id, t.Candidate.status))
    by_role: dict[str, list[str]] = {}
    for role_id, status in statuses:
        by_role.setdefault(role_id, []).append(status)
    return [(_role(r, v), by_role.get(r.id, [])) for r, v in rows]


async def get(role_id: str) -> Role:
    async with db.transaction() as s:
        return await load(s, role_id)
