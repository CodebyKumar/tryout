"""Evaluator: transcript + rubric -> report. Runs once per finished interview (in the background)."""

from typing import Annotated

from pydantic import BaseModel

from ...models import InterviewPlan, Report, Role, Session
from ..base import AgentSpec, Strs, Text, objects, run_agent
from .tools import build_report


class EvidenceOut(BaseModel):
    turn_id: Text = ""
    quote: Text = ""


class CriterionOut(BaseModel):
    criterion_id: Text = ""
    rating: Text = "not_assessed"  # above_bar, meets_bar, below_bar or not_assessed
    score: float | None = None  # 1-5, clamped into the rating's band by the tools
    rationale: Text = ""
    evidence: list[EvidenceOut] = []


class EvalOut(BaseModel):
    criteria: Annotated[list[CriterionOut], objects()] = []
    summary: Text = ""
    strengths: Strs = []
    concerns: Strs = []
    resume_flags: Strs = []
    recommendation: Text = ""  # the model's suggestion; the tools derive the real one from verified scores
    recommendation_reason: Text = ""
    candidate_feedback: Text = ""


SPEC = AgentSpec(
    name="evaluator",
    tier="strong",
    output=EvalOut,
    prompt_version="2",
    max_tokens=6000,
    temperature=0.2,
    timeout_sec=90,
)


async def evaluate(role: Role, plan: InterviewPlan, session: Session) -> Report:
    transcript = "\n".join(
        f"{t.turn_id} ({'candidate' if t.role == 'user' else 'interviewer'}, {session.offset(t)}): {t.text}"
        for t in session.turns
    )
    slots = {
        t.section_id: {s: v.value for s, v in session.sections[t.section_id].slots.items() if v.value}
        for t in plan.sections
    }
    out, usage = await run_agent(
        SPEC,
        title=role.title,
        criteria=[c.model_dump() for c in role.criteria],
        resume={"highlights": plan.resume_highlights, "claims_to_verify": plan.claims_to_verify},
        slots=slots,
        transcript=transcript,
    )
    session.usage.append(usage)
    report = build_report(role, session, out)
    report.model, report.prompt_version = usage.model, usage.prompt_version
    return report
