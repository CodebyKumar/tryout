from datetime import timedelta

from backend.agents import evaluator
from backend.models import Session, Turn, now

ANSWER = "I wrote the idempotent retry logic myself and failed payouts dropped 40 percent."


def session():
    s = Session(plan_id="p", candidate_id="c", started_at=now() - timedelta(minutes=2))
    s.turns = [Turn(turn_id="a1", role="agent", text="Hi"), Turn(turn_id="u2", role="user", text=ANSWER)]
    return s


def build_report(role, s, data):
    return evaluator.build_report(role, s, evaluator.EvalOut.model_validate(data))


def crit(cid, rating, score=None, turn_id="u2", quote="I wrote the idempotent retry logic myself"):
    return {"criterion_id": cid, "rating": rating, "score": score, "evidence": [{"turn_id": turn_id, "quote": quote}]}


def test_score_clamped_into_rating_band(role):  # B5
    rep = build_report(
        role, session(), {"criteria": [crit("ownership", "below_bar", 9), crit("impact", "above_bar", 1)]}
    )
    assert [c.score for c in rep.criteria] == [4.9, 8.0]


def test_quote_with_wrong_turn_id_is_found(role):  # B6
    rep = build_report(role, session(), {"criteria": [crit("ownership", "meets_bar", 6, turn_id="u9")]})
    assert rep.criteria[0].verified and rep.criteria[0].evidence[0].turn_id == "u2"


def test_recommendation_comes_from_verified_scores(role):  # B4
    fake = "I designed the whole platform alone"
    data = {"recommendation": "advance", "recommendation_reason": "Great"}

    # Key criterion (ownership, weight 2) backed by a fabricated quote: cannot advance.
    rep = build_report(
        role,
        session(),
        data | {"criteria": [crit("ownership", "above_bar", 9, quote=fake), crit("impact", "above_bar", 9)]},
    )
    assert rep.recommendation == "hold" and "evaluator suggested advance" in rep.recommendation_reason
    assert rep.overall_score is None  # impact alone is a third of the rubric's weight: no overall score

    rep = build_report(
        role, session(), data | {"criteria": [crit("ownership", "above_bar", 9), crit("impact", "meets_bar", 6)]}
    )
    assert rep.recommendation == "advance" and rep.recommendation_reason == "Great" and rep.overall_score == 8.0

    rep = build_report(
        role, session(), data | {"criteria": [crit("ownership", "below_bar", 3), crit("impact", "above_bar", 9)]}
    )
    assert rep.recommendation == "reject"

    rep = build_report(role, session(), data | {"criteria": [crit("ownership", "above_bar", 9, quote=fake)]})
    assert rep.recommendation is None and rep.overall_score is None
