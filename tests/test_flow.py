import time

import pytest
from fastapi.testclient import TestClient

from backend import config
from backend.agents.evaluator import quote_found
from backend.app import app
from backend.engine import policy
from backend.llm.client import FakeLLM, parse_json, set_llm

ROLE = {
    "company": "Acme Pay",
    "sections": [
        {"target_id": "t_intro", "name": "Intro", "intent": "Background", "opening_question": "Tell me about yourself.",
         "slots": [{"slot_id": "background", "desc": "Current role and experience"}], "time_budget_sec": 120, "priority": 1},
        {"target_id": "t_project", "name": "Past work", "intent": "Ownership of a real system", "opening_question": "Tell me about a system you built.",
         "slots": [{"slot_id": "what", "desc": "What it was"}, {"slot_id": "own_role", "desc": "What they personally built"},
                   {"slot_id": "outcome", "desc": "Result or number"}], "time_budget_sec": 300, "priority": 1},
    ],
    "criteria": [
        {"criterion_id": "ownership", "name": "Ownership", "description": "Owns work end to end", "weight": 2,
         "above_bar": "Clear I-statements and decisions", "meets_bar": "Some ownership", "below_bar": "Only we"},
        {"criterion_id": "impact", "name": "Impact", "description": "Measurable results", "weight": 1},
    ],
}


def fake_llm():
    turns = iter([
        {"ack": "Backend at a fintech, got it.", "probe_question": "", "bridge_question": "Cool. So what's the settlement service on your resume?",
         "slot_updates": [{"target_id": "t_intro", "slot_id": "background", "value": "3 yrs backend at fintech", "status": "filled", "evidence": ["u2"]}]},
        {"ack": "A settlement service.", "probe_question": "Which part did you build yourself?",
         "slot_updates": [{"target_id": "t_project", "slot_id": "what", "value": "settlement service", "status": "filled"},
                          {"target_id": "t_project", "slot_id": "own_role", "value": "we built it", "status": "vague"}],
         "gap": {"slot_id": "own_role", "type": "no_ownership"}},
        {"ack": "So the retry logic was yours.", "probe_question": "",
         "slot_updates": [{"target_id": "t_project", "slot_id": "own_role", "value": "wrote idempotent retry logic", "status": "filled", "evidence": ["u6"]},
                          {"target_id": "t_project", "slot_id": "outcome", "value": "failed payouts dropped 40%", "status": "filled", "evidence": ["u6"]}]},
        {"ack": "Thanks for sharing that.", "probe_question": ""},
    ])
    return FakeLLM({
        "role_compiler": lambda s, u: ROLE,
        "candidate_prep": lambda s, u: {"resume_highlights": ["Settlement service at Acme"], "claims_to_verify": ["Cut failures 40%"],
                                        "openers": {"t_project": "Your resume mentions a settlement service. What was it?"}},
        "turn_agent": lambda s, u: next(turns),
        "evaluator": lambda s, u: {
            "criteria": [{"criterion_id": "ownership", "rating": "above_bar", "score": 4.5, "rationale": "Owned retries",
                          "evidence": [{"turn_id": "u6", "quote": "I wrote the idempotent retry logic myself"}]},
                         {"criterion_id": "impact", "rating": "meets_bar", "score": 3,
                          "evidence": [{"turn_id": "u6", "quote": "we doubled revenue"}]}],  # fabricated quote
            "summary": "Solid.", "strengths": ["Ownership"], "concerns": [], "recommendation": "advance",
            "recommendation_reason": "Strong ownership", "candidate_feedback": "You explained your retry design clearly."},
    })


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    llm = fake_llm()
    set_llm(llm)
    with TestClient(app) as c:
        yield c, llm
    set_llm(None)


def test_recruiter_to_report_flow(client):
    c, llm = client
    role = c.post("/api/roles", json={"title": "Backend Engineer", "jd": "We need a backend engineer for payments. " * 3,
                                      "time_budget_sec": 600}).json()
    assert [s["target_id"] for s in role["sections"]] == ["t_intro", "t_project"] and role["company"] == "Acme Pay"

    cand = c.post(f"/api/roles/{role['role_id']}/candidates", json={"name": "Riya Pillai", "resume": "Acme Pay, settlement service"}).json()
    token = cand["token"]
    assert c.get(f"/api/i/{token}").json()["status"] == "invited"

    view = c.post(f"/api/i/{token}/start").json()
    assert view["turns"][0]["text"].startswith("Hi Riya") and "Backend Engineer" in view["turns"][0]["text"]
    assert "score" not in str(view)  # candidate never sees evaluation data

    r = c.post(f"/api/i/{token}/turn", json={"text": "I have 3 years of backend experience at a fintech."}).json()
    assert r["say"] == "Backend at a fintech, got it. Cool. So what's the settlement service on your resume?"

    r = c.post(f"/api/i/{token}/turn", json={"text": "We built a settlement service for merchant payouts."}).json()
    assert r["say"].endswith("Which part did you build yourself?") and r["interview"]["current_target_id"] == "t_project"

    r = c.post(f"/api/i/{token}/turn", json={"text": "I wrote the idempotent retry logic myself, and failed payouts dropped about 40 percent."}).json()
    assert "probes_left 1" in llm.calls[-1][1] and "CLAIMS TO VERIFY" in llm.calls[-1][1]
    assert r["interview"]["state"] == "WRAPUP" and "anything else" in r["say"]

    r = c.post(f"/api/i/{token}/turn", json={"text": "No, that's all."}).json()
    assert r["done"]

    for _ in range(50):
        rep = c.get(f"/api/candidates/{cand['candidate_id']}").json()
        if rep["report"]:
            break
        time.sleep(0.05)
    report = rep["report"]
    own, impact = report["criteria"]
    assert own["verified"] and own["evidence"][0]["at"]
    assert not impact["verified"] and impact["evidence"] == []  # fabricated quote rejected
    assert report["overall_score"] == 4.5  # only verified criteria count
    assert rep["candidate"]["status"] == "completed"

    assert c.get(f"/api/i/{token}").json()["feedback"] is None
    c.post(f"/api/candidates/{cand['candidate_id']}/release_feedback")
    assert "retry design" in c.get(f"/api/i/{token}").json()["feedback"]
    c.post(f"/api/candidates/{cand['candidate_id']}/decision", json={"status": "advanced"})
    ranked = c.get(f"/api/roles/{role['role_id']}").json()["candidates"]
    assert ranked[0]["status"] == "advanced" and ranked[0]["score"] == 4.5


def test_policy_and_parsing():
    from backend.agents.role_compiler import apply_compiled
    from backend.engine.engine import new_session
    from backend.models import InterviewPlan, Role
    role = apply_compiled(Role(title="X", jd="y", time_budget_sec=300), ROLE)
    assert sum(t.time_budget_sec for t in role.sections) <= 255  # capped to 85% of budget
    plan = InterviewPlan(role_id=role.role_id, candidate_id="c", candidate_name="A", role_title="X",
                         time_budget_sec=300, targets=role.sections)
    s = new_session(plan)
    t = plan.targets[0]
    assert not policy.must_move_on(plan, s, t)
    s.targets[t.target_id].probe_count = policy.MAX_PROBES_PER_TARGET
    assert policy.must_move_on(plan, s, t)
    s.elapsed_sec = 290
    assert policy.next_target(plan, s) is None

    assert quote_found("I wrote the retry logic", "Honestly, I wrote the retry logic myself.")
    assert not quote_found("we doubled revenue", "I wrote the retry logic myself.")
    assert {"phone", "pan", "salary"} <= {k for k, _ in policy.find_pii("call +91 98765 43210, PAN ABCDE1234F, CTC 12 LPA")}
    assert not policy.find_pii("about 300 users use it")
    assert parse_json('```json\n{"a": [1, 2,],}\n```') == {"a": [1, 2]}
