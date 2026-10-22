"""Use cases. The only layer that touches the database and joins agents with the engine; each route calls one
function. Pattern: read in one short transaction, call the LLM with no transaction open (a slow model never holds a
connection from the small free-tier pool), write in one transaction.

Errors: NotFound (404), Invalid (400: bad input, or the action does not fit the current state). LLMError from an
agent means the AI service is unavailable (503).
"""

import asyncio
from collections import defaultdict

from .. import tables as t
from ..models import Usage


class NotFound(Exception):
    pass


class Invalid(Exception):
    pass


# One lock per candidate, so a turn, a resume upload, a reset and a delete never interleave.
# shortcut: in-process, so one server instance only; use SELECT ... FOR UPDATE when running several.
locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)


def llm_calls(usage: list[Usage], **owner) -> list[t.LLMCall]:
    """Usage records as rows, tagged with what they were for (role_id, candidate_id or session_id)."""
    return [t.LLMCall(**u.model_dump(), **owner) for u in usage]
