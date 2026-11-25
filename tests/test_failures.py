import time

from conftest import wait_for

from backend.integrations.llm import LLMError


def down(system, user):
    raise LLMError("rate limited")


def test_prep_failure_is_visible_and_retryable(client):  # B3
    c, llm = client
    role = c.post("/api/roles", json={"title": "Backend Engineer", "jd": "We need a backend engineer. " * 3}).json()
    working = llm.handlers["candidate_prep"]
    llm.handlers["candidate_prep"] = down
    cand = c.post(
        f"/api/roles/{role['role_id']}/candidates", json={"name": "Riya", "resume": "Acme Pay, settlement"}
    ).json()
    row = lambda: c.get(f"/api/roles/{role['role_id']}").json()["candidates"][0]  # noqa: E731
    assert wait_for(row, lambda x: x["prep_status"] != "pending")["prep_status"] == "failed"
    assert c.post(f"/api/candidates/{cand['candidate_id']}/prepare").status_code == 503

    llm.handlers["candidate_prep"] = working
    assert c.post(f"/api/candidates/{cand['candidate_id']}/prepare").json()["prep_status"] == "ok"


def test_evaluation_failure_is_visible_and_retryable(client):  # B2
    c, llm = client
    role = c.post("/api/roles", json={"title": "Backend Engineer", "jd": "We need a backend engineer. " * 3}).json()
    cand = c.post(f"/api/roles/{role['role_id']}/candidates", json={"name": "Riya"}).json()
    cid, token = cand["candidate_id"], cand["token"]
    working = llm.handlers["evaluator"]
    llm.handlers["evaluator"] = down
    llm.handlers["turn_agent"] = lambda s, u: {"ack": "Okay.", "user_wants_stop": True}
    c.post(f"/api/i/{token}/start")
    assert c.post(f"/api/i/{token}/turn", json={"text": "I have to stop here."}).json()["done"]

    for _ in range(50):
        rep = c.get(f"/api/candidates/{cid}").json()
        if rep["state"] != "EVALUATING":
            break
        time.sleep(0.05)
    assert rep["state"] == "EVAL_FAILED" and "rate limited" in rep["eval_error"] and rep["report"] is None
    assert c.post(f"/api/candidates/{cid}/reevaluate").status_code == 503

    llm.handlers["evaluator"] = working
    rep = c.post(f"/api/candidates/{cid}/reevaluate").json()
    assert rep["state"] == "DONE" and rep["report"] and rep["eval_error"] == ""
