import time

from conftest import ROLE

from backend import config
from backend.agents import evaluator
from backend.agents.evaluator import quote_found
from backend.agents.role_compiler import CompiledRole, apply_compiled
from backend.engine import policy
from backend.engine.state_machine import new_session
from backend.integrations.llm import parse_json
from backend.models import InterviewPlan, Role
from backend.safety import pii


def test_recruiter_to_report_flow(client):
    c, llm = client
    role = c.post(
        "/api/roles",
        json={
            "title": "Backend Engineer",
            "jd": "We need a backend engineer for payments. " * 3,
            "time_budget_sec": 600,
        },
    ).json()
    assert [s["section_id"] for s in role["sections"]] == ["t_intro", "t_project"] and role["company"] == "Acme Pay"

    cand = c.post(
        f"/api/roles/{role['role_id']}/candidates",
        json={"name": "Riya Pillai", "resume": "Acme Pay, settlement service"},
    ).json()
    token = cand["token"]
    assert c.get(f"/api/i/{token}").json()["status"] == "invited"

    view = c.post(f"/api/i/{token}/start").json()
    assert view["turns"][0]["text"].startswith("Hi Riya") and "Backend Engineer" in view["turns"][0]["text"]
    assert "score" not in str(view)  # candidate never sees evaluation data

    r = c.post(f"/api/i/{token}/turn", json={"text": "I have 3 years of backend experience at a fintech."}).json()
    assert r["say"] == "Backend at a fintech, got it. Cool. So what's the settlement service on your resume?"

    r = c.post(f"/api/i/{token}/turn", json={"text": "We built a settlement service for merchant payouts."}).json()
    assert (
        r["say"].endswith("Which part did you build yourself?") and r["interview"]["current_section_id"] == "t_project"
    )

    r = c.post(
        f"/api/i/{token}/turn",
        json={"text": "I wrote the idempotent retry logic myself, and failed payouts dropped about 40 percent."},
    ).json()
    assert "probes_left 1" in llm.calls[-1][1] and "CLAIMS TO VERIFY" in llm.calls[-1][1]
    assert r["interview"]["state"] == "WRAPUP" and "anything else" in r["say"]

    r = c.post(f"/api/i/{token}/turn", json={"text": "No, that's all."}).json()
    assert r["done"]
    assert [a for a, _ in llm.calls].count("turn_agent") == 3  # the wrap-up answer needs no LLM call

    for _ in range(50):
        rep = c.get(f"/api/candidates/{cand['candidate_id']}").json()
        if rep["report"]:
            break
        time.sleep(0.05)
    report = rep["report"]
    own, impact = report["criteria"]
    assert own["verified"] and own["evidence"][0]["at"]
    assert not impact["verified"] and impact["evidence"] == []  # fabricated quote rejected
    assert report["overall_score"] == 9  # only verified criteria count
    assert (report["model"], report["prompt_version"]) == ("fake", evaluator.SPEC.prompt_version)
    assert rep["candidate"]["status"] == "completed"

    assert c.get(f"/api/i/{token}").json()["rated"] is False
    assert c.post(f"/api/i/{token}/rating", json={"stars": 6}).status_code == 422
    assert c.post(f"/api/i/{token}/rating", json={"stars": 4, "comment": " Clear questions "}).status_code == 200
    assert c.get(f"/api/i/{token}").json()["rated"] is True
    assert c.get(f"/api/candidates/{cand['candidate_id']}").json()["experience"]["comment"] == "Clear questions"
    c.post(f"/api/candidates/{cand['candidate_id']}/decision", json={"status": "advanced"})
    ranked = c.get(f"/api/roles/{role['role_id']}").json()["candidates"]
    assert ranked[0]["status"] == "advanced" and ranked[0]["score"] == 9


def test_policy_and_parsing():

    role = apply_compiled(Role(title="X", jd="y", time_budget_sec=300), CompiledRole.model_validate(ROLE))
    assert sum(t.time_budget_sec for t in role.sections) <= 255  # capped to 85% of budget
    plan = InterviewPlan(
        role_id=role.role_id,
        candidate_id="c",
        candidate_name="A",
        role_title="X",
        time_budget_sec=300,
        sections=role.sections,
    )
    s = new_session(plan)
    t = plan.sections[0]
    assert not policy.must_move_on(plan, s, t)
    s.sections[t.section_id].probe_count = config.MAX_PROBES_PER_SECTION
    assert policy.must_move_on(plan, s, t)
    s.elapsed_sec = 290
    assert policy.next_section(plan, s) is None

    assert quote_found("I wrote the retry logic", "Honestly, I wrote the retry logic myself.")
    assert not quote_found("we doubled revenue", "I wrote the retry logic myself.")
    assert {"phone", "pan", "salary"} <= {
        k for k, _ in pii.find_pii("call +91 98765 43210, PAN ABCDE1234F, CTC 12 LPA")
    }
    assert not pii.find_pii("about 300 users use it")
    assert parse_json('```json\n{"a": [1, 2,],}\n```') == {"a": [1, 2]}


def test_role_templates(client):
    c, _ = client
    found = c.get("/api/templates").json()
    assert len(found) >= 4 and all(t["title"] and t["summary"] and len(t["jd"]) > 200 for t in found)
    assert "digital_design_intern" in [t["id"] for t in found]


def test_integrity_events_are_kept_summarised_and_never_scored(client):
    c, _ = client
    role = c.post("/api/roles", json={"title": "Backend Engineer", "jd": "We need a backend engineer. " * 5}).json()
    token = c.post(
        f"/api/roles/{role['role_id']}/candidates", json={"name": "Riya Pillai", "resume": "Acme Pay"}
    ).json()["token"]
    c.post(f"/api/i/{token}/start")
    away = [{"kind": "tab_hidden", "at_sec": 20, "seconds": 8}] * 3
    r = c.post(
        f"/api/i/{token}/events", json={"events": [*away, {"kind": "paste", "at_sec": 40, "detail": "42 characters"}]}
    )
    assert r.status_code == 200
    assert c.post(f"/api/i/{token}/events", json={"events": [{"kind": "hack", "at_sec": 1}]}).status_code == 422
    cid = c.get(f"/api/roles/{role['role_id']}").json()["candidates"][0]["candidate_id"]
    summary = c.get(f"/api/candidates/{cid}").json()["integrity"]
    assert summary["level"] == "review" and summary["times_away"] == 3 and summary["away_sec"] == 24
    assert summary["counts"] == {"tab_hidden": 3, "paste": 1}
    assert "integrity" not in c.get(f"/api/i/{token}").text  # the candidate view never shows it
