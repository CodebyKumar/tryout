"""Use cases. The only layer that touches storage and joins agents with the engine; each route calls one function.

Errors: NotFound (404), Invalid (400: bad input, or the action does not fit the current state). LLMError from an
agent means the AI service is unavailable (503).
"""

import asyncio
from collections import defaultdict

from .. import store


class NotFound(Exception):
    pass


class Invalid(Exception):
    pass


# One lock per candidate, so a turn, a resume upload, a reset and a delete never interleave.
locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)


def get(cls, obj_id: str | None):
    obj = store.load(cls, obj_id) if obj_id else None
    if obj is None:
        raise NotFound(f"{cls.__name__} not found")
    return obj
