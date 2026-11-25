"""Accounts: sign up, log in, log out, approval. Passwords use scrypt from the standard library; a login is a random
token in a cookie whose SHA-256 is the only thing stored."""

import asyncio
import hashlib
import hmac
import re
import secrets
import time
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import delete, func, select

from .. import config, db
from .. import tables as t
from ..models import new_id, now
from . import Forbidden, Invalid, NotFound

DEMO_EMAIL = "demo@tryout.app"
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


@dataclass
class Account:
    id: str
    email: str
    name: str
    status: str  # pending / active / disabled / demo
    is_admin: bool

    @property
    def can_write(self) -> bool:
        return self.status == "active"


def _account(row: t.Recruiter) -> Account:
    return Account(row.id, row.email, row.name, row.status, row.is_admin)


# ---------- Passwords and tokens ----------


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    key = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return f"scrypt${salt.hex()}${key.hex()}"


def check_password(password: str, stored: str) -> bool:
    try:
        _, salt, key = stored.split("$")
    except ValueError:
        return False
    got = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=2**14, r=8, p=1)
    return hmac.compare_digest(got.hex(), key)


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# shortcut: failed logins counted in memory per email (resets on restart, one process); move to a table if abused.
_failures: dict[str, list[float]] = {}
MAX_FAILURES, FAILURE_WINDOW_SEC = 5, 15 * 60


def _too_many(email: str) -> bool:
    recent = [x for x in _failures.get(email, []) if time.time() - x < FAILURE_WINDOW_SEC]
    _failures[email] = recent
    if not recent:
        del _failures[email]
    return len(recent) >= MAX_FAILURES


# ---------- Use cases ----------


async def new_login(s, recruiter_id: str) -> str:
    token = secrets.token_urlsafe(32)
    expires = now() + timedelta(days=config.SESSION_DAYS)
    s.add(t.AuthSession(token_hash=_digest(token), recruiter_id=recruiter_id, expires_at=expires))
    await s.execute(delete(t.AuthSession).where(t.AuthSession.expires_at < now()))  # keep the table small
    return token


async def sign_up(name: str, email: str, password: str) -> tuple[Account, str]:
    """New accounts wait for approval, except the configured admin. Returns the account and a login token."""
    name, email = name.strip(), email.strip().lower()
    if not name:
        raise Invalid("Enter your name")
    if not _EMAIL.fullmatch(email):
        raise Invalid("Enter a valid email address")
    if len(password) < 8:
        raise Invalid("Use a password of at least 8 characters")
    is_admin = bool(config.ADMIN_EMAIL) and email == config.ADMIN_EMAIL
    hashed = await asyncio.to_thread(hash_password, password)  # scrypt is deliberately slow: keep it off the loop
    async with db.transaction() as s:
        if await s.scalar(select(t.Recruiter.id).where(t.Recruiter.email == email)):
            raise Invalid("An account with this email already exists. Sign in instead.")
        row = t.Recruiter(
            id=new_id("u"),
            email=email,
            name=name[:120],
            password_hash=hashed,
            status="active" if is_admin else "pending",
            is_admin=is_admin,
        )
        s.add(row)
        await s.flush()
        return _account(row), await new_login(s, row.id)


async def log_in(email: str, password: str) -> tuple[Account, str]:
    email = email.strip().lower()
    if _too_many(email):
        raise Forbidden("Too many failed attempts. Wait 15 minutes and try again.")
    async with db.transaction() as s:
        row = await s.scalar(select(t.Recruiter).where(t.Recruiter.email == email))
    ok = row is not None and await asyncio.to_thread(check_password, password, row.password_hash)
    if not ok:
        _failures.setdefault(email, []).append(time.time())
        raise Invalid("Email or password is wrong")
    if row.status == "disabled":
        raise Forbidden("This account has been disabled")
    async with db.transaction() as s:
        return _account(row), await new_login(s, row.id)


async def demo_login() -> tuple[Account, str]:
    """A login to the shared demo account, which can look at everything in it and change nothing."""
    async with db.transaction() as s:
        row = await s.scalar(select(t.Recruiter).where(t.Recruiter.email == DEMO_EMAIL))
        if row is None:
            raise NotFound("The demo is not set up on this server")
        return _account(row), await new_login(s, row.id)


async def log_out(token: str) -> None:
    async with db.transaction() as s:
        await s.execute(delete(t.AuthSession).where(t.AuthSession.token_hash == _digest(token)))


async def by_token(token: str) -> Account | None:
    """The account a login cookie belongs to, or None when it is unknown, expired or disabled."""
    async with db.transaction() as s:
        row = await s.scalar(
            select(t.Recruiter)
            .join(t.AuthSession, t.AuthSession.recruiter_id == t.Recruiter.id)
            .where(t.AuthSession.token_hash == _digest(token), t.AuthSession.expires_at > now())
        )
    return _account(row) if row and row.status != "disabled" else None


# ---------- Admin ----------


async def list_accounts() -> list[dict]:
    """Every account with how much it has used: roles, candidates, interviews and LLM tokens."""
    async with db.transaction() as s:
        rows = (await s.scalars(select(t.Recruiter).order_by(t.Recruiter.created_at.desc()))).all()
        roles = dict((await s.execute(select(t.Role.recruiter_id, func.count()).group_by(t.Role.recruiter_id))).all())
        cands = dict(
            (
                await s.execute(
                    select(t.Role.recruiter_id, func.count())
                    .join(t.Candidate, t.Candidate.role_id == t.Role.id)
                    .group_by(t.Role.recruiter_id)
                )
            ).all()
        )
        interviews = dict(
            (
                await s.execute(
                    select(t.Role.recruiter_id, func.count())
                    .join(t.Candidate, t.Candidate.role_id == t.Role.id)
                    .where(t.Candidate.status != "invited")
                    .group_by(t.Role.recruiter_id)
                )
            ).all()
        )
    return [
        {
            "id": r.id,
            "email": r.email,
            "name": r.name,
            "status": r.status,
            "is_admin": r.is_admin,
            "created_at": r.created_at,
            "roles": roles.get(r.id, 0),
            "candidates": cands.get(r.id, 0),
            "interviews": interviews.get(r.id, 0),
        }
        for r in rows
    ]


async def set_status(admin: Account, recruiter_id: str, status: str) -> None:
    if status not in ("active", "disabled", "pending"):
        raise Invalid("Status must be active, disabled or pending")
    if recruiter_id == admin.id:
        raise Invalid("You cannot change your own account")
    async with db.transaction() as s:
        row = await s.get(t.Recruiter, recruiter_id)
        if row is None:
            raise NotFound("Account not found")
        if row.status == "demo":
            raise Invalid("The demo account cannot be changed")
        row.status = status
        if status == "disabled":
            await s.execute(delete(t.AuthSession).where(t.AuthSession.recruiter_id == recruiter_id))
