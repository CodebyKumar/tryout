"""Accounts and access: who can reach what (requirements R2, R3)."""

import asyncio
import re

import pytest
from conftest import ADMIN, sign_up
from sqlalchemy import update

from backend import db
from backend import tables as t
from backend.app import app
from backend.services import accounts

JD = "We need a backend engineer for payments. " * 3

# Every recruiter and admin route, read from the app itself, so a new route is covered without editing this list.
PRIVATE = sorted(
    (method.upper(), path)
    for path, ops in app.openapi()["paths"].items()
    if path.startswith("/api/") and not path.startswith(("/api/i/", "/api/auth/", "/api/health"))
    for method in ops
)


async def _activate(recruiter_id: str) -> None:
    async with db.transaction() as s:
        await s.execute(update(t.Recruiter).where(t.Recruiter.id == recruiter_id).values(status="active"))


def _fill(path: str) -> str:
    return re.sub(r"\{\w+\}", "x_missing", path)


@pytest.mark.parametrize("method,path", PRIVATE)
def test_every_private_route_needs_a_login(anon, method, path):
    c, _ = anon
    assert c.request(method, _fill(path), json={}).status_code == 401


def test_routes_list_is_not_empty():
    assert len(PRIVATE) >= 20 and ("GET", "/api/admin/overview") in PRIVATE


def test_recruiters_never_see_each_others_data(client):
    c, _ = client  # signed in as the admin
    role = c.post("/api/roles", json={"title": "Backend Engineer", "jd": JD}).json()
    cand = c.post(f"/api/roles/{role['role_id']}/candidates", json={"name": "Riya"}).json()
    c.post("/api/auth/logout")
    other = sign_up(c, email="other@example.com")
    asyncio.run(_activate(other["id"]))  # approved, so writes reach the ownership check instead of stopping at 403
    ids = {"role_id": role["role_id"], "candidate_id": cand["candidate_id"], "recruiter_id": "x"}
    for method, path in PRIVATE:
        if path.startswith("/api/admin") or not re.search(r"\{(role_id|candidate_id)\}", path):
            continue
        url = re.sub(r"\{(\w+)\}", lambda m: ids[m[1]], path)
        status = c.request(method, url, json={"instruction": "x", "name": "x", "decision": None}).status_code
        assert status == 404, (method, path, status)
    assert c.get("/api/roles").json() == []


def test_pending_account_can_look_but_not_change(anon):
    c, _ = anon
    me = sign_up(c)
    assert me["status"] == "pending" and not me["is_admin"]
    assert c.get("/api/roles").status_code == 200
    r = c.post("/api/roles", json={"title": "Backend Engineer", "jd": JD})
    assert r.status_code == 403 and "approval" in r.json()["detail"]
    assert c.get("/api/admin/accounts").status_code == 404  # the admin area does not exist for them


def test_admin_approves_and_disables(anon):
    c, _ = anon
    ravi = sign_up(c)
    c.post("/api/auth/logout")
    assert c.post("/api/auth/login", json={"email": ADMIN["email"], "password": "wrong password"}).status_code == 400
    c.post("/api/auth/signup", json=ADMIN)
    listed = {a["email"]: a for a in c.get("/api/admin/accounts").json()}
    assert listed["ravi@example.com"]["status"] == "pending"
    assert c.post(f"/api/admin/accounts/{ravi['id']}/status", json={"status": "active"}).status_code == 200
    admin_id = c.get("/api/auth/me").json()["id"]
    assert c.post(f"/api/admin/accounts/{admin_id}/status", json={"status": "disabled"}).status_code == 400

    other = c.__class__(app)  # a second browser
    other.post("/api/auth/login", json={"email": "ravi@example.com", "password": "correct horse"})
    assert other.post("/api/roles", json={"title": "Backend Engineer", "jd": JD}).status_code == 200
    c.post(f"/api/admin/accounts/{ravi['id']}/status", json={"status": "disabled"})
    assert other.get("/api/roles").status_code == 401  # disabling ends their logins at once
    r = other.post("/api/auth/login", json={"email": "ravi@example.com", "password": "correct horse"})
    assert r.status_code == 403


def test_sign_up_and_log_in_rules(anon):
    c, _ = anon
    bad = [
        {"name": "", "email": "a@b.co", "password": "longenough"},
        {"name": "A", "email": "not-an-email", "password": "longenough"},
        {"name": "A", "email": "a@b.co", "password": "short"},
    ]
    assert all(c.post("/api/auth/signup", json=x).status_code == 400 for x in bad)
    sign_up(c, email="Ravi@Example.com")
    assert (
        c.post("/api/auth/signup", json={"name": "B", "email": "ravi@example.com", "password": "x" * 9}).status_code
        == 400
    )
    c.post("/api/auth/logout")
    assert c.get("/api/auth/me").status_code == 401
    for _ in range(accounts.MAX_FAILURES):
        c.post("/api/auth/login", json={"email": "ravi@example.com", "password": "nope nope"})
    r = c.post("/api/auth/login", json={"email": "ravi@example.com", "password": "correct horse"})
    assert r.status_code == 403  # locked out for a while after repeated failures, even with the right password
    accounts._failures.clear()


def test_passwords_and_tokens_are_never_stored_plain():
    stored = accounts.hash_password("correct horse")
    assert "correct horse" not in stored and accounts.check_password("correct horse", stored)
    assert not accounts.check_password("correct horsE", stored) and not accounts.check_password("x", "garbage")
    assert accounts._digest("abc") != "abc" and len(accounts._digest("abc")) == 64
