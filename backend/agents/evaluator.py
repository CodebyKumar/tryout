"""Evaluator: transcript + rubric -> report. Code verifies every quote and computes the weighted score."""

import re

from .. import prompts
from ..llm.client import get_llm
from ..models import CriterionResult, Evidence, InterviewPlan, Report, Role, Session

_SCORES = {"above_bar": 4.5, "meets_bar": 3.0, "below_bar": 1.5}


def _words(s: str) -> list[str]:
    return re.sub(r"[^a-z0-9 ]+", " ", s.lower()).split()


def quote_found(quote: str, text: str) -> bool:
    """True if the quote appears in the turn, ignoring case and punctuation (allows small trims at the ends)."""
    q, t = " ".join(_words(quote)), " ".join(_words(text))
    if not q:
        return False
    if q in t:
        return True
    words = q.split()
    return len(words) >= 6 and " ".join(words[1:-1]) in t


async def evaluate(role: Role, plan: InterviewPlan, session: Session) -> Report:
    transcript = "\n".join(f"{t.turn_id} ({'candidate' if t.role == 'user' else 'interviewer'}, {session.offset(t)}): {t.text}"
                           for t in session.turns)
    slots = {t.target_id: {s: v.value for s, v in session.targets[t.target_id].slots.items() if v.value}
             for t in plan.targets}
    system, user = prompts.render(
        "evaluator", title=role.title,
        criteria=[c.model_dump() for c in role.criteria],
        resume={"highlights": plan.resume_highlights, "claims_to_verify": plan.claims_to_verify},
        slots=slots, transcript=transcript)
    data, usage = await get_llm().json(agent="evaluator", role="strong", system=system, user=user,
                                       max_tokens=6000, temperature=0.2)
    session.usage.append(usage)
    return build_report(role, session, data)


def build_report(role: Role, session: Session, data: dict) -> Report:
    by_id = {c.get("criterion_id"): c for c in data.get("criteria") or [] if isinstance(c, dict)}
    results = []
    for crit in role.criteria:
        raw = by_id.get(crit.criterion_id, {})
        rating = raw.get("rating") if raw.get("rating") in ("above_bar", "meets_bar", "below_bar", "not_assessed") else "not_assessed"
        evidence = []
        for e in raw.get("evidence") or []:
            if not isinstance(e, dict):
                continue
            turn = next((t for t in session.turns if t.turn_id == e.get("turn_id") and t.role == "user"), None)
            if turn and quote_found(e.get("quote") or "", turn.text):
                evidence.append(Evidence(turn_id=turn.turn_id, quote=e["quote"].strip(), at=session.offset(turn)))
        score = raw.get("score")
        score = float(score) if isinstance(score, (int, float)) and 1 <= score <= 5 else _SCORES.get(rating)
        results.append(CriterionResult(
            criterion_id=crit.criterion_id, name=crit.name, rating=rating,
            score=None if rating == "not_assessed" else score, rationale=raw.get("rationale") or "",
            evidence=evidence, verified=rating == "not_assessed" or bool(evidence)))

    # Weighted score over assessed, verified criteria only: an unbacked rating does not count.
    scored = [(r.score, c.weight) for r, c in zip(results, role.criteria) if r.score is not None and r.verified]
    overall = round(sum(s * w for s, w in scored) / sum(w for _, w in scored), 1) if scored else None
    rec = data.get("recommendation") if data.get("recommendation") in ("advance", "hold", "reject") else None
    reason = data.get("recommendation_reason") or ""
    if all(r.rating == "not_assessed" for r in results):
        rec, reason = None, "Not enough was said in the interview to assess any criterion. Consider resetting and re-inviting."
    lst = lambda k: [x for x in data.get(k) or [] if isinstance(x, str)][:4]
    return Report(overall_score=overall, recommendation=rec, recommendation_reason=reason,
                  summary=data.get("summary") or "", criteria=results, strengths=lst("strengths"),
                  concerns=lst("concerns"), resume_flags=lst("resume_flags"),
                  candidate_feedback=data.get("candidate_feedback") or "")
