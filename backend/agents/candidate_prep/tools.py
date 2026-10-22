"""Candidate Prep tools: the fit score is plain arithmetic, and openers are only used if they are real questions."""

from typing import TYPE_CHECKING

from ...models import Fit, FitItem, InterviewPlan

if TYPE_CHECKING:
    from .spec import FitOut, PrepOut

_MATCH = {"strong": 1.0, "partial": 0.5, "none": 0.0}


def score_fit(raw: "FitOut") -> Fit:
    """The LLM judges each requirement; the score itself is plain arithmetic the recruiter can check."""
    items = [
        FitItem(
            requirement=it.requirement[:80],
            must_have=it.must_have,
            match=it.match if it.match in _MATCH else "none",
            evidence=it.evidence[:200],
        )
        for it in raw.items
        if it.requirement
    ]
    total = sum(2 if i.must_have else 1 for i in items)
    score = round(100 * sum((2 if i.must_have else 1) * _MATCH[i.match] for i in items) / total) if total else None
    return Fit(
        score=score,
        items=items[:14],
        summary=raw.summary,
        matched=[i.requirement for i in items if i.match != "none"],
        missing=[i.requirement for i in items if i.match == "none"],
    )


def apply_prep(plan: InterviewPlan, out: "PrepOut") -> InterviewPlan:
    plan.resume_highlights = out.resume_highlights[:6]
    plan.claims_to_verify = out.claims_to_verify[:4]
    plan.fit = score_fit(out.fit)
    if out.vocabulary:
        plan.stt_hint += " Terms: " + ", ".join(out.vocabulary[:30]) + "."
    for t in plan.sections:
        opener = out.openers.get(t.section_id)
        if isinstance(opener, str) and opener.strip().endswith("?"):
            t.opening_question = opener.strip()
    plan.prep_status = "ok"
    return plan
