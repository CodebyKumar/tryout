"""Evaluator tools: code verifies every quote, clamps scores, computes the weighted score and the recommendation."""

import re
from typing import TYPE_CHECKING

from ...models import CriterionResult, Evidence, Report, Role, Session

if TYPE_CHECKING:
    from .spec import EvalOut

_SCORES = {"above_bar": 4.5, "meets_bar": 3.0, "below_bar": 1.5}
# A score must sit inside its rating's band: "below_bar" with score 5 is not a valid answer.
_BANDS = {"above_bar": (4.0, 5.0), "meets_bar": (2.5, 3.9), "below_bar": (1.0, 2.4)}


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


def _find_quote(session: Session, turn_id: str, quote: str):
    """The user turn that contains the quote: the cited one first, then any other (the model often cites the wrong id)."""
    user_turns = [t for t in session.turns if t.role == "user"]
    user_turns.sort(key=lambda t: t.turn_id != turn_id)
    return next((t for t in user_turns if quote_found(quote, t.text)), None)


def recommend(results: list[CriterionResult], role: Role, overall: float | None) -> str | None:
    """Suggestion from verified ratings only. Key criteria (weight 2+) must be verified to advance."""
    if overall is None:
        return None
    key = [r for r, c in zip(results, role.criteria, strict=True) if c.weight >= 2]
    if overall < 2.5 or any(r.verified and r.rating == "below_bar" for r in key):
        return "reject"
    if overall >= 3.0 and all(r.verified and r.rating != "not_assessed" for r in key):
        return "advance"
    return "hold"


def build_report(role: Role, session: Session, out: "EvalOut") -> Report:
    by_id = {c.criterion_id: c for c in out.criteria}
    results = []
    for crit in role.criteria:
        raw = by_id.get(crit.criterion_id)
        rating = raw.rating if raw and raw.rating in _BANDS else "not_assessed"
        evidence = []
        for e in raw.evidence if raw else []:
            turn = _find_quote(session, e.turn_id, e.quote.strip())
            if turn:
                evidence.append(Evidence(turn_id=turn.turn_id, quote=e.quote.strip(), at=session.offset(turn)))
        score = None
        if rating in _BANDS:
            lo, hi = _BANDS[rating]
            score = min(max(raw.score, lo), hi) if raw.score is not None else _SCORES[rating]
        results.append(
            CriterionResult(
                criterion_id=crit.criterion_id,
                name=crit.name,
                rating=rating,
                score=score,
                rationale=raw.rationale if raw else "",
                evidence=evidence,
                verified=rating == "not_assessed" or bool(evidence),
            )
        )

    # Weighted score over assessed, verified criteria only: an unbacked rating does not count.
    scored = [
        (r.score, c.weight) for r, c in zip(results, role.criteria, strict=True) if r.score is not None and r.verified
    ]
    overall = round(sum(s * w for s, w in scored) / sum(w for _, w in scored), 1) if scored else None
    rec = recommend(results, role, overall)
    suggested, reason = out.recommendation, out.recommendation_reason
    if rec is None:
        reason = "Not enough verified evidence to assess any criterion. Consider resetting and re-inviting."
    elif rec != suggested:
        reason = (
            f"Set from verified scores ({overall}); the evaluator suggested {suggested or 'nothing'}. {reason}".strip()
        )

    return Report(
        overall_score=overall,
        recommendation=rec,
        recommendation_reason=reason,
        summary=out.summary,
        criteria=results,
        strengths=out.strengths[:4],
        concerns=out.concerns[:4],
        resume_flags=out.resume_flags[:4],
        candidate_feedback=out.candidate_feedback,
    )
