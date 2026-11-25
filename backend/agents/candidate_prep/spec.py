"""Candidate Prep: resume -> highlights, claims to verify, personalised section openers, role fit. Once per candidate."""

import logging
from typing import Annotated

from pydantic import BaseModel

from ...integrations.llm import LLMError
from ...models import Candidate, InterviewPlan, Role
from ..base import AgentSpec, Strs, Text, objects, run_agent
from .tools import apply_prep

log = logging.getLogger("prep")


class FitItemOut(BaseModel):
    requirement: Text = ""
    must_have: bool = True
    match: Text = "none"  # strong, partial or none
    evidence: Text = ""


class FitOut(BaseModel):
    # No name_key: the prompt asks for objects, so a bare string here is prose that leaked into the list.
    items: Annotated[list[FitItemOut], objects()] = []
    summary: Text = ""


class PrepOut(BaseModel):
    resume_highlights: Strs = []
    claims_to_verify: Strs = []
    openers: dict = {}  # section_id -> personalised opening question
    fit: FitOut = FitOut()
    vocabulary: Strs = []  # resume terms for speech-to-text


SPEC = AgentSpec(
    name="candidate_prep",
    tier="strong",
    output=PrepOut,
    prompt_version="2",
    max_tokens=3000,
    temperature=0.3,
    timeout_sec=60,
)


async def build_plan(role: Role, cand: Candidate) -> InterviewPlan:
    """Never raises: on LLM failure the plan uses the generic openers and is marked prep_status="failed"."""
    plan = InterviewPlan(
        role_id=role.role_id,
        role_version_id=role.version_id,
        candidate_id=cand.candidate_id,
        candidate_name=cand.name.split()[0] if cand.name else "",
        role_title=role.title,
        company=role.company,
        time_budget_sec=role.time_budget_sec,
        sections=[t.model_copy(deep=True) for t in role.sections],
        stt_hint=f"Interview for {role.title}{' at ' + role.company if role.company else ''}.",
    )
    if not cand.resume.strip():
        return plan
    sections = [
        {"section_id": t.section_id, "name": t.name, "intent": t.intent, "opening_question": t.opening_question}
        for t in plan.sections
    ]
    try:
        out, usage = await run_agent(
            SPEC, title=role.title, jd=role.jd[:6000], sections=sections, resume=cand.resume[:10000]
        )
    except LLMError as e:
        log.warning("prep failed, using generic openers: %s", e)
        plan.prep_status, plan.prep_error = "failed", str(e)
        return plan
    plan.usage.append(usage)
    return apply_prep(plan, out)
