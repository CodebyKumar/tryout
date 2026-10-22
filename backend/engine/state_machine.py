"""The interview state machine: owns Session state. Pure code, no LLM and no I/O: given the agent's proposal, it
decides what is recorded and what is said next."""

from typing import TYPE_CHECKING

from ..models import Flag, InterviewPlan, SectionState, Session, SlotState, Turn, now
from ..safety import pii
from . import policy
from .heuristics import fresh_ack, recent_agent, similar

if TYPE_CHECKING:
    from ..agents.turn_agent import TurnOut

FALLBACK_SAY = "Sorry, I lost my train of thought for a second. Could you say that once more?"
# Slot status only moves forward, so a later vague answer cannot reopen a filled slot. "conflict" is always allowed.
_RANK = {"missing": 0, "vague": 1, "conflict": 1, "filled": 2, "unknown": 2, "declined": 2}


def new_session(plan: InterviewPlan) -> Session:
    s = Session(plan_id=plan.plan_id, candidate_id=plan.candidate_id)
    for t in plan.sections:
        s.sections[t.section_id] = SectionState(slots={sl.slot_id: SlotState() for sl in t.slots})
    return s


def _tick(session: Session) -> None:
    t = now()
    if session.last_tick_at:
        delta = (t - session.last_tick_at).total_seconds()
        session.elapsed_sec += delta
        if session.current_section_id:
            session.sections[session.current_section_id].time_used_sec += delta
    session.last_tick_at = t


def _say(session: Session, text: str) -> Turn:
    turn = Turn(turn_id=session.next_turn_id("agent"), role="agent", text=text, section_id=session.current_section_id)
    session.turns.append(turn)
    return turn


def start(plan: InterviewPlan, session: Session) -> Turn:
    first = plan.sections[0]
    session.state = "INTERVIEWING"
    session.started_at = session.last_tick_at = now()
    session.current_section_id = first.section_id
    session.sections[first.section_id].status = "active"
    name = f" {plan.candidate_name}" if plan.candidate_name else ""
    at = f" at {plan.company}" if plan.company else ""
    minutes = max(1, round(plan.time_budget_sec / 60))
    intro = (
        f"Hi{name}, I'm your AI interviewer for the {plan.role_title} role{at}. This takes about {minutes} minutes. "
    )
    return _say(session, intro + first.opening_question)


def _apply_updates(plan: InterviewPlan, session: Session, updates: list, user_turn_id: str) -> None:
    user_ids = {t.turn_id for t in session.turns if t.role == "user"}
    for u in updates:
        section = plan.section(u.section_id or session.current_section_id or "")
        if not section or u.slot_id not in session.sections[section.section_id].slots:
            continue
        slot = session.sections[section.section_id].slots[u.slot_id]
        status = u.status if u.status in _RANK else "vague"
        if status != "conflict" and _RANK[status] < _RANK[slot.status]:
            continue
        slot.status = status
        if u.value:
            slot.value = u.value
        evidence = [e for e in u.evidence if e in user_ids] or [user_turn_id]
        slot.evidence = sorted(set(slot.evidence + evidence), key=lambda x: int(x[1:]))


def _advance(plan: InterviewPlan, session: Session) -> None:
    cur = plan.section(session.current_section_id)
    st = session.sections[cur.section_id]
    st.status = "satisfied" if policy.coverage(cur, st) >= 1 else "partial"
    nxt = policy.next_section(plan, session, exclude=cur.section_id)
    if nxt:
        session.current_section_id = nxt.section_id
        session.sections[nxt.section_id].status = "active"
    else:
        for t in plan.sections:
            if session.sections[t.section_id].status == "pending":
                session.sections[t.section_id].status = "skipped"
        session.current_section_id = None
        session.state = "WRAPUP"


def duplicate_reply(session: Session, text: str) -> dict | None:
    """Same answer sent twice (double submit, mic retry): replay the last line instead of recording it again."""
    last = session.turns[-1] if session.turns else None
    prev_user = next((t for t in reversed(session.turns) if t.role == "user"), None)
    if (
        prev_user
        and prev_user.text == text.strip()
        and (now() - prev_user.ts).total_seconds() < 20
        and last
        and last.role == "agent"
        and not last.fallback  # a repeat after "say that once more" is a real retry
    ):
        return {"say": last.text, "turn_id": last.turn_id, "done": False, "duplicate": True}
    return None


def record_answer(session: Session, text: str) -> Turn:
    """Adds the candidate's answer to the transcript, charges the elapsed time, and flags personal data in it."""
    _tick(session)
    user_turn = Turn(
        turn_id=session.next_turn_id("user"), role="user", text=text.strip(), section_id=session.current_section_id
    )
    session.turns.append(user_turn)
    for subtype, match in pii.find_pii(text):
        session.flags.append(
            Flag(
                type="pii" if subtype != "salary" else "sensitive_personal",
                subtype=subtype,
                turn_id=user_turn.turn_id,
                text=match,
            )
        )
    return user_turn


def fallback(session: Session) -> dict:
    """The Turn Agent failed: ask the candidate to repeat. The turn is marked so the repeat is not a duplicate."""
    agent_turn = _say(session, FALLBACK_SAY)
    agent_turn.fallback = True
    return {"say": agent_turn.text, "turn_id": agent_turn.turn_id, "done": False}


def apply_turn(plan: InterviewPlan, session: Session, user_turn: Turn, out: "TurnOut") -> dict:
    """The agent proposed; code decides what is recorded and what is said next."""
    _apply_updates(plan, session, out.slot_updates, user_turn.turn_id)
    if out.injection_suspected:
        session.flags.append(
            Flag(type="injection", subtype="prompt_injection", turn_id=user_turn.turn_id, text=user_turn.text[:200])
        )
    ack = fresh_ack(out.ack.strip(), session)
    if ack and ack[-1] not in ".!?":
        ack += "."
    if out.user_wants_stop:
        return end(session, ack)
    say = f"{ack} {_next_question(plan, session, out)}".strip()
    agent_turn = _say(session, say)
    return {"say": say, "turn_id": agent_turn.turn_id, "done": False}


def end(session: Session, ack: str) -> dict:
    session.state, session.current_section_id = "EVALUATING", None
    say = f"{ack} That's the end of our conversation. Thank you for your time; the hiring team will be in touch."
    agent_turn = _say(session, say.strip())
    return {"say": agent_turn.text, "turn_id": agent_turn.turn_id, "done": True}


def _next_question(plan: InterviewPlan, session: Session, out: "TurnOut") -> str:
    """Code decides whether to stay or move on, so the spoken question always matches the active topic."""
    cur = plan.section(session.current_section_id)
    st = session.sections[cur.section_id]
    probe, skip = out.probe_question.strip(), out.user_wants_skip
    if probe and any(similar(probe, q) for q in recent_agent(session)):
        probe, skip = "", True  # never ask the same thing twice; move on instead of looping
    open_optional = any(
        not s.required and not policy.is_resolved(st.slots[s.slot_id]) and policy.probes_left(st.slots[s.slot_id])
        for s in cur.slots
    )
    topic_done = policy.coverage(cur, st) >= 1
    advance = policy.must_move_on(plan, session, cur) or skip or (topic_done and (not probe or not open_optional))

    if not advance:
        if not probe:
            # The agent had nothing worth asking here: move on rather than asking a vague "tell me more".
            advance = True
        if not advance:
            gap_slot = st.slots.get(out.gap.slot_id) if out.gap else None
            if not gap_slot or policy.is_resolved(gap_slot):
                # The agent did not say which slot it probes: charge the first open required one.
                gap_slot = next(
                    (
                        st.slots[s.slot_id]
                        for s in cur.slots
                        if s.required and not policy.is_resolved(st.slots[s.slot_id])
                    ),
                    None,
                )
            if gap_slot:
                gap_slot.probes += 1
            st.probe_count += 1
            return probe

    planned_next = policy.next_section(plan, session, exclude=cur.section_id)
    _advance(plan, session)
    bridge = out.bridge_question.strip()
    # The agent's bridge was written for the next section we showed it; use it only if that's where we went.
    nxt = plan.section(session.current_section_id) if session.current_section_id else None
    if (
        bridge.endswith("?")
        and (nxt is planned_next or (nxt is None and planned_next is None))
        and not any(similar(bridge, q) for q in recent_agent(session))
    ):
        return bridge
    if nxt:
        return f"Okay, let's switch gears. {nxt.opening_question}"
    return "We're almost out of time. Is there anything else you'd like the team to know about you?"
