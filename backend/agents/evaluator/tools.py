"""Evaluator tools: code verifies every quote, clamps scores, computes the weighted score and the recommendation."""

import re
from typing import TYPE_CHECKING

from ...models import CriterionResult, Evidence, Report, Role, Session

if TYPE_CHECKING:
    from .spec import EvalOut

# Scores are out of 10. A score must sit inside its rating's band: "below_bar" with score 9 is not a valid answer.
_SCORES = {"above_bar": 9.0, "meets_bar": 6.0, "below_bar": 3.0}
_BANDS = {"above_bar": (8.0, 10.0), "meets_bar": (5.0, 7.9), "below_bar": (1.0, 4.9)}
REJECT_BELOW, ADVANCE_FROM = 5.0, 6.0
MIN_COVERAGE = (
    0.5  # quote-backed criteria must carry this share of the rubric's weight before there is an overall score
)


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
    """Suggestion from verified ratings only. Key criteria (weight 2+) must be verified to advance. No suggestion
    when nothing is backed by a quote; "hold" when some is, but too little for an overall score."""
    backed = [r for r in results if r.verified and r.score is not None]
    if not backed:
        return None
    key = [r for r, c in zip(results, role.criteria, strict=True) if c.weight >= 2]
    if any(r.verified and r.rating == "below_bar" for r in key) or (overall is not None and overall < REJECT_BELOW):
        return "reject"
    if overall is not None and overall >= ADVANCE_FROM and all(r.verified and r.rating != "not_assessed" for r in key):
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

    # Weighted average over quote-backed criteria only (an unbacked rating does not count), and only once those carry
    # enough of the rubric: one good answer on a minor criterion must not stand in for the whole interview.
    scored = [
        (r.score, c.weight) for r, c in zip(results, role.criteria, strict=True) if r.score is not None and r.verified
    ]
    coverage = sum(w for _, w in scored) / (sum(c.weight for c in role.criteria) or 1)
    overall = round(sum(s * w for s, w in scored) / sum(w for _, w in scored), 1) if coverage >= MIN_COVERAGE else None
    rec = recommend(results, role, overall)
    suggested, reason = out.recommendation, out.recommendation_reason
    basis = f"score {overall} of 10" if overall is not None else "evidence on less than half of the rubric"
    if rec is None:
        reason = "No answer could be backed by a quote, so nothing was scored. Consider resetting and re-inviting."
    elif rec != suggested:
        reason = (
            f"Set from verified evidence ({basis}); the evaluator suggested {suggested or 'nothing'}. {reason}".strip()
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
    )
