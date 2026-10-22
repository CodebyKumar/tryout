"""Phase 4: versions, one row per turn, every evaluation kept, cascading deletes. Runs on SQLite by default; set
TEST_DATABASE_URL to run the same tests on Postgres."""

import asyncio
import time

from conftest import ROLE
from sqlalchemy import func, select

from backend import db
from backend import tables as t

JD = "We need a backend engineer for payments. " * 3


def count(model, **where):
    async def q():
        async with db.transaction() as s:
            stmt = select(func.count()).select_from(model)
            for k, v in where.items():
                stmt = stmt.where(getattr(model, k) == v)
            return await s.scalar(stmt)

    return asyncio.run(q())


def wait_for_report(c, cid):
    for _ in range(50):
        rep = c.get(f"/api/candidates/{cid}").json()
        if rep["state"] not in ("EVALUATING", "INTERVIEWING", "WRAPUP"):
            return rep
        time.sleep(0.05)
    return rep


def interview(c, llm, token):
    llm.handlers["turn_agent"] = lambda s, u: {"ack": "Okay.", "user_wants_stop": True}
    c.post(f"/api/i/{token}/start")
    c.post(f"/api/i/{token}/turn", json={"text": "I built the settlement service and I own its retries."})


def test_candidate_is_scored_on_the_brief_they_were_interviewed_on(client):  # A2, D1, D2
    c, llm = client
    role = c.post("/api/roles", json={"title": "Backend Engineer", "jd": JD}).json()
    cand = c.post(f"/api/roles/{role['role_id']}/candidates", json={"name": "Riya", "resume": "Acme Pay"}).json()
    llm.handlers["role_refine"] = lambda s, u: {
        "sections": ROLE["sections"],
        "criteria": [{"criterion_id": "system_design", "name": "System design", "description": "x", "weight": 2}],
    }
    refined = c.post(f"/api/roles/{role['role_id']}/refine", json={"instruction": "score system design only"}).json()
    assert (role["version"], refined["version"]) == (1, 2)

    interview(c, llm, cand["token"])
    rep = wait_for_report(c, cand["candidate_id"])
    assert [x["criterion_id"] for x in rep["report"]["criteria"]] == ["ownership", "impact"]  # v1, not v2
    assert "ownership" in llm.calls[-1][1] and "system_design" not in llm.calls[-1][1]


def test_turns_rows_and_every_evaluation_kept(client):  # D3, D4
    c, llm = client
    role = c.post("/api/roles", json={"title": "Backend Engineer", "jd": JD}).json()
    cand = c.post(f"/api/roles/{role['role_id']}/candidates", json={"name": "Riya"}).json()
    interview(c, llm, cand["token"])
    rep = wait_for_report(c, cand["candidate_id"])
    assert rep["state"] == "DONE"
    assert count(t.Turn) == 3  # greeting, answer, goodbye
    c.post(f"/api/candidates/{cand['candidate_id']}/reevaluate")
    assert count(t.Evaluation) == 2 and count(t.Evaluation, is_current=True) == 1
    assert count(t.LLMCall, agent="evaluator") == 2  # usage of both runs recorded


def test_delete_removes_everything(client):  # D5
    c, llm = client
    role = c.post("/api/roles", json={"title": "Backend Engineer", "jd": JD}).json()
    cand = c.post(f"/api/roles/{role['role_id']}/candidates", json={"name": "Riya", "resume": "Acme Pay"}).json()
    interview(c, llm, cand["token"])
    wait_for_report(c, cand["candidate_id"])
    c.delete(f"/api/candidates/{cand['candidate_id']}")
    assert [count(m) for m in (t.Candidate, t.Plan, t.Session, t.Turn, t.Evaluation, t.Document)] == [0] * 6
    assert c.get(f"/api/i/{cand['token']}").status_code == 404
