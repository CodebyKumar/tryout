"""Role Compiler: JD + recruiter notes (or one whole hiring document) -> interview sections + scoring criteria."""

import re
from typing import Annotated

from pydantic import BaseModel

from ...models import Role
from ..base import AgentSpec, Text, objects, run_agent
from .tools import apply_compiled


class SlotOut(BaseModel):
    slot_id: Text = ""
    desc: Text = ""
    required: bool = True


class SectionOut(BaseModel):
    section_id: Text = ""
    name: Text = ""
    intent: Text = ""
    opening_question: Text = ""
    slots: Annotated[list[SlotOut], objects("desc")] = []
    time_budget_sec: float | None = None
    priority: float | None = None  # 1 (must cover) to 3 (skip when behind schedule)


class CriterionOut(BaseModel):
    criterion_id: Text = ""
    name: Text = ""
    description: Text = ""
    weight: float | None = None
    above_bar: Text = ""
    meets_bar: Text = ""
    below_bar: Text = ""


class CompiledRole(BaseModel):
    """The brief. Also the output of Role Refine, and what manual edits are validated as."""

    title: Text = ""
    company: Text = ""
    time_budget_sec: float | None = None
    jd_summary: Text = ""
    interviewer_notes: Text = ""
    sections: Annotated[list[SectionOut], objects("name")] = []
    criteria: Annotated[list[CriterionOut], objects("name")] = []


SPEC = AgentSpec(
    name="role_compiler",
    tier="strong",
    output=CompiledRole,
    prompt_version="3",
    max_tokens=7000,
    temperature=0.2,
    timeout_sec=90,
)


async def compile_role(role: Role, from_document: bool = False, fixed_length: bool = True) -> Role:
    """from_document: role.jd holds a whole hiring document; title, notes and length are read from it."""
    if from_document and not fixed_length:
        m = re.search(r"(\d{1,2})\s*(?:-|to)?\s*(?:min|mins|minutes)\b", role.jd, re.I)
        if m and 3 <= int(m.group(1)) <= 60:
            role.time_budget_sec, fixed_length = int(m.group(1)) * 60, True
    out, usage = await run_agent(
        SPEC,
        title="" if role.title == "Untitled role" else role.title,
        jd=role.jd[:15000],
        notes=role.notes or "none",
        time_budget_sec=str(role.time_budget_sec),
    )
    role.usage.append(usage)
    if from_document:
        if not fixed_length and out.time_budget_sec and 180 <= out.time_budget_sec <= 3600:
            role.time_budget_sec = int(out.time_budget_sec)
        role.document = role.document or role.jd
        role.jd = out.jd_summary or role.jd
        role.notes = out.interviewer_notes or role.notes
    return apply_compiled(role, out)
