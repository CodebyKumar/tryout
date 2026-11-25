"""Use cases. The only layer that touches the database and joins agents with the engine; each route calls one
function. Pattern: read in one short transaction, call the LLM with no transaction open (a slow model never holds a
connection from the small free-tier pool), write in one transaction.

Errors, mapped to HTTP status in app.py: NotFound 404, Invalid 400 (bad input, or the action does not fit the
current state), Forbidden 403, Conflict 409 (someone else changed it first), Busy 503 (no capacity right now).
LLMError from an agent means the AI service is unavailable (503).
"""

import asyncio
from collections import Counter
from contextlib import asynccontextmanager

from .. import tables as t
from ..models import Usage


class NotFound(Exception):
    pass


class Invalid(Exception):
    pass


class Forbidden(Exception):
    pass


class Conflict(Exception):
    pass


class Busy(Exception):
    pass


# One lock per key (a candidate id), so a turn, a resume upload, a reset and a delete never interleave inside this
# process. Correctness across processes comes from the database (sessions.version, jobs claimed with SKIP LOCKED);
# the lock only saves wasted LLM calls. Entries are removed when nobody holds or waits, so the map stays small.
_locks: dict[str, asyncio.Lock] = {}
_users: Counter[str] = Counter()


@asynccontextmanager
async def locked(key: str):
    _users[key] += 1
    lock = _locks.setdefault(key, asyncio.Lock())
    try:
        async with lock:
            yield
    finally:
        _users[key] -= 1
        if not _users[key]:
            del _users[key], _locks[key]


def llm_calls(usage: list[Usage], **owner) -> list[t.LLMCall]:
    """Usage records as rows, tagged with what they were for (role_id, candidate_id or session_id)."""
    return [t.LLMCall(**u.model_dump(), **owner) for u in usage]
