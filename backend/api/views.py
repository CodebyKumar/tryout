"""Domain objects -> JSON. The candidate's views never contain scores or evaluation data."""

from ..engine import policy
from ..models import Candidate, InterviewPlan, Role, Session


def usage(s: Session) -> dict:
    turns = [u for u in s.usage if u.agent == "turn_agent"]
    return {
        "calls": sum(u.calls for u in s.usage),
        "prompt_tokens": sum(u.prompt_tokens for u in s.usage),
        "cached_tokens": sum(u.cached_tokens for u in s.usage),  # half price, and not counted by Groq rate limits
        "completion_tokens": sum(u.completion_tokens for u in s.usage),
        "avg_turn_ms": int(sum(u.latency_ms for u in turns) / max(1, len(turns))),
    }


def interview(s: Session, plan: InterviewPlan) -> dict:
    """What the candidate sees: the conversation and progress, never scores."""
    return {
        "state": s.state,
        "elapsed_sec": round(s.elapsed_sec),
        "time_budget_sec": plan.time_budget_sec,
        "current_section_id": s.current_section_id,
        "sections": [
            {
                "section_id": t.section_id,
                "name": t.name,
                "status": s.sections[t.section_id].status,
                "coverage": round(policy.coverage(t, s.sections[t.section_id]), 2),
            }
            for t in plan.sections
        ],
        "turns": [{"turn_id": t.turn_id, "role": t.role, "text": t.text} for t in s.turns],
    }


def summary(c: Candidate, s: Session | None, plan: InterviewPlan | None) -> dict:
    r = s.report if s else None
    return {
        **c.model_dump(exclude={"resume"}),
        "score": r.overall_score if r else None,
        "fit": plan.fit.score if plan else None,
        "recommendation": r.recommendation if r else None,
        "evaluating": bool(s and s.state == "EVALUATING"),
        "eval_failed": bool(s and s.state == "EVAL_FAILED"),
        "prep_status": plan.prep_status if plan else None,
    }


def role_list(rows: list[tuple[Role, list[Candidate]]]) -> list[dict]:
    return [
        {
            **r.model_dump(include={"role_id", "title", "company", "created_at", "time_budget_sec"}),
            "candidates": len(cands),
            "completed": sum(1 for c in cands if c.status not in ("invited", "in_progress")),
        }
        for r, cands in rows
    ]


def role(r: Role, candidates: list[tuple[Candidate, Session | None, InterviewPlan | None]]) -> dict:
    cands = [summary(*b) for b in candidates]
    cands.sort(key=lambda c: (c["score"] is None, -(c["score"] or 0)))
    return {**r.model_dump(), "candidates": cands}


def report(c: Candidate, r: Role, s: Session | None, plan: InterviewPlan | None) -> dict:
    out = {
        "candidate": c.model_dump(),
        "role": r.model_dump(include={"role_id", "title", "criteria"}),
        "report": None,
        "transcript": [],
        "flags": [],
        "usage": None,
        "state": None,
        "eval_error": "",
        "fit": plan.fit.model_dump() if plan else None,
    }
    if s:
        names = {t.section_id: t.name for t in plan.sections}
        out.update(
            report=s.report.model_dump() if s.report else None,
            state=s.state,
            eval_error=s.eval_error,
            usage=usage(s),
            flags=[f.model_dump() for f in s.flags],
            duration_sec=round(s.elapsed_sec),
            resume_highlights=plan.resume_highlights,
            transcript=[
                {
                    "turn_id": t.turn_id,
                    "role": t.role,
                    "text": t.text,
                    "at": s.offset(t),
                    "section": names.get(t.section_id, ""),
                }
                for t in s.turns
            ],
        )
    return out


def candidate_info(c: Candidate, r: Role, s: Session | None, plan: InterviewPlan | None) -> dict:
    return {
        "name": c.name,
        "role_title": r.title,
        "company": r.company,
        "minutes": round(r.time_budget_sec / 60),
        "status": c.status,
        "interview": interview(s, plan) if s else None,
        "feedback": s.report.candidate_feedback if s and s.report and c.feedback_released else None,
        "has_resume": bool(c.resume.strip()),
    }
