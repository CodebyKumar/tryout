"""Domain objects -> JSON. The candidate's views never contain scores or evaluation data."""

from ..engine import policy
from ..models import Candidate, InterviewPlan, Role, Session
from ..safety import integrity
from ..services.candidates import Summary


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


def summary(sm: Summary) -> dict:
    return {
        **sm.candidate.model_dump(exclude={"resume", "plan_id", "session_id"}),
        "score": sm.score,
        "fit": sm.fit,
        "recommendation": sm.recommendation,
        "evaluating": sm.state == "EVALUATING",
        "eval_failed": sm.state == "EVAL_FAILED",
        "prep_status": sm.prep_status,
        "brief_version": sm.brief_version,
    }


def role_list(rows: list[tuple[Role, list[str]]]) -> list[dict]:
    return [
        {
            **r.model_dump(include={"role_id", "title", "company", "created_at", "time_budget_sec", "version"}),
            "candidates": len(statuses),
            "completed": sum(1 for x in statuses if x not in ("invited", "in_progress")),
            "to_review": statuses.count("completed"),  # scored, no decision yet
        }
        for r, statuses in rows
    ]


def role(r: Role, candidates: list[Summary]) -> dict:
    cands = [summary(x) for x in candidates]
    cands.sort(key=lambda c: (c["score"] is None, -(c["score"] or 0)))
    return {**r.model_dump(exclude={"usage", "document"}), "candidates": cands}


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
        "role_version": plan.role_version_id if plan else None,
    }
    if s:
        names = {t.section_id: t.name for t in plan.sections}
        out.update(
            report=s.report.model_dump() if s.report else None,
            state=s.state,
            eval_error=s.eval_error,
            usage=usage(s),
            flags=[f.model_dump() for f in s.flags],
            integrity=integrity.summarize(s.integrity),
            experience=s.experience.model_dump(mode="json") if s.experience else None,
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
        "rated": bool(s and s.experience),
        "has_resume": bool(c.resume.strip()),
    }
