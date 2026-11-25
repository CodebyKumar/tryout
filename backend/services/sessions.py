"""Loading and saving an interview session. Turns and usage are append-only rows; the engine state is one JSON."""

from sqlalchemy import func, select, update

from .. import tables as t
from ..models import Session, Usage, now
from . import Conflict, NotFound, llm_calls


async def load(s, session_id: str) -> Session:
    row = await s.get(t.Session, session_id)
    if row is None:
        raise NotFound("Interview not found")
    turns = (await s.scalars(select(t.Turn).where(t.Turn.session_id == session_id).order_by(t.Turn.seq))).all()
    usage = (await s.scalars(select(t.LLMCall).where(t.LLMCall.session_id == session_id).order_by(t.LLMCall.id))).all()
    report = await s.scalar(
        select(t.Evaluation.report).where(t.Evaluation.session_id == session_id, t.Evaluation.is_current)
    )
    return Session.model_validate(
        {
            **row.data,
            "state": row.state,
            "version": row.version,
            "turns": [
                {
                    "turn_id": x.turn_id,
                    "role": x.speaker,
                    "text": x.text,
                    "ts": x.created_at,
                    "section_id": x.section_id,
                    "fallback": x.fallback,
                    "trace": x.trace,
                }
                for x in turns
            ],
            "usage": [Usage.model_validate(u, from_attributes=True) for u in usage],
            "report": report,
        }
    )


async def save(s, session: Session) -> None:
    """One transaction per turn (audit D3): the engine state is updated, and only new turns and usage are inserted.
    The update only applies if the row is still at the version this copy was read at; otherwise another request
    (a second tab, a double submit on another server) wrote first, and this one raises Conflict instead of
    overwriting it."""
    data = session.model_dump(mode="json", exclude={"turns", "usage", "report", "state", "version"})
    if not session.version:
        s.add(t.Session(id=session.session_id, plan_id=session.plan_id, state=session.state, data=data, version=1))
        await s.flush()  # no ORM relationships: insert the parent before rows that point at it
        session.version, last_seq, saved_usage = 1, 0, 0
    else:
        done = await s.execute(
            update(t.Session)
            .where(t.Session.id == session.session_id, t.Session.version == session.version)
            .values(state=session.state, data=data, last_activity_at=now(), version=session.version + 1)
        )
        if done.rowcount != 1:
            raise Conflict("This interview changed in another window. Reload the page to continue.")
        session.version += 1
        last_seq = await s.scalar(select(func.max(t.Turn.seq)).where(t.Turn.session_id == session.session_id)) or 0
        saved_usage = await s.scalar(select(func.count()).where(t.LLMCall.session_id == session.session_id))
    for turn in session.turns:
        seq = int(turn.turn_id[1:])  # turn ids number the transcript: u3, a4, ...
        if seq > last_seq:
            s.add(
                t.Turn(
                    session_id=session.session_id,
                    seq=seq,
                    turn_id=turn.turn_id,
                    speaker=turn.role,
                    fallback=turn.fallback,
                    text=turn.text,
                    section_id=turn.section_id,
                    trace=turn.trace,
                    created_at=turn.ts,
                )
            )
    s.add_all(llm_calls(session.usage[saved_usage:], session_id=session.session_id))
