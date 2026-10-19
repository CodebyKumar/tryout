"""InterviewEngine: the state machine that owns SessionState. Agents propose, the engine decides and records."""

import logging

from .. import prompts
from ..llm.client import LLMError, get_llm
from ..models import Flag, InterviewPlan, Session, SlotState, TargetState, Turn, now
from . import context, policy

log = logging.getLogger("engine")

FALLBACK_SAY = "Sorry, I lost my train of thought for a second. Could you say that once more?"
_STATUSES = {"missing", "vague", "filled", "unknown", "declined", "conflict"}


_STOP = {"what", "did", "you", "your", "the", "and", "for", "how", "can", "could", "tell", "about", "that", "this",
         "with", "was", "were", "are", "have", "has", "there", "any", "one", "use", "used", "using", "would", "some"}


def _words(text: str) -> set[str]:
    return {w for w in "".join(c.lower() if c.isalnum() else " " for c in text).split() if len(w) > 2 and w not in _STOP}


def _similar(a: str, b: str) -> bool:
    wa, wb = _words(a), _words(b)
    return bool(wa and wb) and len(wa & wb) / len(wa | wb) >= 0.5


def _recent_agent(session: Session, n: int = 3) -> list[str]:
    return [t.text for t in session.turns if t.role == "agent"][-n:]


_FILLERS = {"got it", "okay", "ok", "right", "nice", "sure", "alright", "great", "cool", "i see", "makes sense"}


def _fresh_ack(ack: str, session: Session) -> str:
    """Keep the acknowledgment, but trim an opener word ("Got it,") that the last turns already used, so it doesn't
    sound repetitive. Only a bare repeated filler is dropped entirely."""
    recent = [t.lower() for t in _recent_agent(session, 2)]
    words = ack.split()
    for n in (2, 1):
        opener = " ".join(words[:n]).lower().strip(" .!,")
        if opener in _FILLERS and any(t.startswith(opener) for t in recent):
            rest = " ".join(words[n:]).lstrip(" ,.!-")
            return rest[:1].upper() + rest[1:] if len(rest.split()) >= 3 else ""
    return ack


def new_session(plan: InterviewPlan) -> Session:
    s = Session(plan_id=plan.plan_id, candidate_id=plan.candidate_id)
    for t in plan.targets:
        s.targets[t.target_id] = TargetState(slots={sl.slot_id: SlotState() for sl in t.slots})
    return s


def _tick(session: Session) -> None:
    t = now()
    if session.last_tick_at:
        delta = (t - session.last_tick_at).total_seconds()
        session.elapsed_sec += delta
        if session.current_target_id:
            session.targets[session.current_target_id].time_used_sec += delta
    session.last_tick_at = t


def _say(session: Session, text: str) -> Turn:
    turn = Turn(turn_id=session.next_turn_id("agent"), role="agent", text=text, target_id=session.current_target_id)
    session.turns.append(turn)
    return turn


def start(plan: InterviewPlan, session: Session) -> Turn:
    first = plan.targets[0]
    session.state = "INTERVIEWING"
    session.started_at = session.last_tick_at = now()
    session.current_target_id = first.target_id
    session.targets[first.target_id].status = "active"
    name = f" {plan.candidate_name}" if plan.candidate_name else ""
    at = f" at {plan.company}" if plan.company else ""
    minutes = max(1, round(plan.time_budget_sec / 60))
    intro = f"Hi{name}, I'm your AI interviewer for the {plan.role_title} role{at}. This takes about {minutes} minutes. "
    return _say(session, intro + first.opening_question)


def _apply_updates(plan: InterviewPlan, session: Session, updates: list, user_turn_id: str) -> None:
    user_ids = {t.turn_id for t in session.turns if t.role == "user"}
    for u in updates or []:
        if not isinstance(u, dict):
            continue
        target = plan.target(u.get("target_id") or session.current_target_id or "")
        if not target or u.get("slot_id") not in session.targets[target.target_id].slots:
            continue
        slot = session.targets[target.target_id].slots[u["slot_id"]]
        slot.status = u.get("status") if u.get("status") in _STATUSES else "vague"
        if u.get("value"):
            slot.value = str(u["value"])
        evidence = [e for e in (u.get("evidence") or []) if e in user_ids] or [user_turn_id]
        slot.evidence = sorted(set(slot.evidence + evidence), key=lambda x: int(x[1:]))


def _advance(plan: InterviewPlan, session: Session) -> None:
    cur = plan.target(session.current_target_id)
    st = session.targets[cur.target_id]
    st.status = "satisfied" if policy.coverage(cur, st) >= 1 else "partial"
    nxt = policy.next_target(plan, session, exclude=cur.target_id)
    if nxt:
        session.current_target_id = nxt.target_id
        session.targets[nxt.target_id].status = "active"
    else:
        for t in plan.targets:
            if session.targets[t.target_id].status == "pending":
                session.targets[t.target_id].status = "skipped"
        session.current_target_id = None
        session.state = "WRAPUP"


async def handle_user_turn(plan: InterviewPlan, session: Session, text: str) -> dict:
    """One user turn -> one LLM call -> state update. Returns what the UI needs."""
    if session.state not in ("INTERVIEWING", "WRAPUP"):
        raise ValueError("This interview has already ended")
    last = session.turns[-1] if session.turns else None
    prev_user = next((t for t in reversed(session.turns) if t.role == "user"), None)
    if prev_user and prev_user.text == text.strip() and (now() - prev_user.ts).total_seconds() < 20 and last and last.role == "agent":
        # Same answer sent twice (double submit, mic retry): don't record or answer it again.
        return {"say": last.text, "turn_id": last.turn_id, "done": False, "duplicate": True}
    _tick(session)
    wrapup = session.state == "WRAPUP"
    user_turn = Turn(turn_id=session.next_turn_id("user"), role="user", text=text.strip(),
                     target_id=session.current_target_id)
    session.turns.append(user_turn)

    for subtype, match in policy.find_pii(text):
        session.flags.append(Flag(type="pii" if subtype != "salary" else "sensitive_personal",
                                  subtype=subtype, turn_id=user_turn.turn_id, text=match))

    system, user = prompts.render("turn_agent", candidate_name=plan.candidate_name or "the candidate",
                                  company=plan.company or "the company",
                                  role_title=plan.role_title, context=context.build(plan, session, wrapup=wrapup),
                                  turn_id=user_turn.turn_id, user_text=text.strip())
    try:
        out, usage = await get_llm().json(agent="turn_agent", role="turn", system=system, user=user,
                                          max_tokens=1500, temperature=0.5)
        session.usage.append(usage)
    except LLMError as e:
        log.error("turn agent failed: %s", e)
        agent_turn = _say(session, FALLBACK_SAY)
        return {"say": agent_turn.text, "turn_id": agent_turn.turn_id, "done": False}

    _apply_updates(plan, session, out.get("slot_updates"), user_turn.turn_id)
    if out.get("injection_suspected"):
        session.flags.append(Flag(type="injection", subtype="prompt_injection", turn_id=user_turn.turn_id, text=text[:200]))

    ack = _fresh_ack((out.get("ack") or "").strip(), session)
    if ack and ack[-1] not in ".!?":
        ack += "."
    done = False
    if wrapup or out.get("user_wants_stop"):
        session.state, session.current_target_id, done = "EVALUATING", None, True
        question = "That's the end of our conversation. Thank you for your time; the hiring team will be in touch."
    else:
        question = _next_question(plan, session, out)
    say = f"{ack} {question}".strip()
    agent_turn = _say(session, say)
    return {"say": say, "turn_id": agent_turn.turn_id, "done": done}


def _next_question(plan: InterviewPlan, session: Session, out: dict) -> str:
    """Code decides whether to stay or move on, so the spoken question always matches the active topic."""
    cur = plan.target(session.current_target_id)
    st = session.targets[cur.target_id]
    probe = (out.get("probe_question") or "").strip()
    if probe and any(_similar(probe, q) for q in _recent_agent(session)):
        probe = ""  # never ask the same thing twice; move on instead of looping
        out["user_wants_skip"] = True
    open_optional = any(not s.required and not policy.is_resolved(st.slots[s.slot_id]) and policy.probes_left(st.slots[s.slot_id])
                        for s in cur.slots)
    topic_done = policy.coverage(cur, st) >= 1
    advance = (policy.must_move_on(plan, session, cur) or bool(out.get("user_wants_skip"))
               or (topic_done and (not probe or not open_optional)))

    if not advance:
        if not probe:
            # The agent had nothing worth asking here: move on rather than asking a vague "tell me more".
            advance = True
        if not advance:
            gap = out.get("gap") if isinstance(out.get("gap"), dict) else {}
            gap_slot = st.slots.get(gap.get("slot_id") or "")
            if gap_slot and not policy.is_resolved(gap_slot):
                gap_slot.probes += 1
            st.probe_count += 1
            return probe

    planned_next = policy.next_target(plan, session, exclude=cur.target_id)
    _advance(plan, session)
    bridge = (out.get("bridge_question") or "").strip()
    # The agent's bridge was written for the next section we showed it; use it only if that's where we went.
    nxt = plan.target(session.current_target_id) if session.current_target_id else None
    if bridge.endswith("?") and (nxt is planned_next or (nxt is None and planned_next is None)) \
            and not any(_similar(bridge, q) for q in _recent_agent(session)):
        return bridge
    if nxt:
        return f"Okay, let's switch gears. {nxt.opening_question}"
    return "We're almost out of time. Is there anything else you'd like the team to know about you?"
