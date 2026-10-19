"""Builds the per-turn STATE block for the Turn Agent. Small and flat: slots are the memory, not the transcript."""

from ..models import InterviewPlan, Session, Target
from . import policy

RECENT_TURNS = 4


def _fmt(sec: float) -> str:
    sec = max(0, int(sec))
    return f"{sec // 60:02d}:{sec % 60:02d}"


def _slot_lines(target: Target, session: Session, with_probes: bool) -> list[str]:
    st = session.targets[target.target_id]
    lines = []
    for s in target.slots:
        ss = st.slots[s.slot_id]
        req = "required" if s.required else "optional"
        if ss.value:
            state = f'{ss.status} "{ss.value}"'
        else:
            state = ss.status
        probe = f" probes_left {policy.probes_left(ss)}" if with_probes else ""
        lines.append(f"- {s.slot_id} ({s.desc}, {req}): {state}{probe}")
    return lines


def build(plan: InterviewPlan, session: Session, wrapup: bool = False) -> str:
    out = [f"TIME: {_fmt(session.elapsed_sec)} of {_fmt(plan.time_budget_sec)} used. "
           f"Remaining {_fmt(policy.remaining_sec(plan, session))}. "
           f"Behind schedule: {'yes' if policy.behind_schedule(plan, session) else 'no'}."]

    if wrapup:
        out.append("PHASE: WRAP-UP. All topics are closed. Record any additions or corrections the user makes in the "
                   "right topic. ack: thank them in one sentence. probe_question: empty.")
    else:
        cur = plan.target(session.current_target_id)
        st = session.targets[cur.target_id]
        out += [
            f"CURRENT SECTION: {cur.target_id} ({cur.name}) | {_fmt(st.time_used_sec)} of {_fmt(cur.time_budget_sec)} used | "
            f"coverage {int(policy.coverage(cur, st) * 100)}% | probes used {st.probe_count} of {policy.MAX_PROBES_PER_TARGET}",
            f"INTENT: {cur.intent}",
            "SLOTS:", *_slot_lines(cur, session, with_probes=True),
        ]
        nxt = policy.next_target(plan, session, exclude=cur.target_id)
        out.append(f"NEXT: {nxt.name} | question to bridge into: {nxt.opening_question}" if nxt else "NEXT: none")

    if plan.resume_highlights:
        out.append("RESUME HIGHLIGHTS: " + " | ".join(plan.resume_highlights))
    if plan.claims_to_verify:
        out.append("CLAIMS TO VERIFY (probe for specifics when relevant): " + " | ".join(plan.claims_to_verify))

    others = [t for t in plan.targets if t.target_id != session.current_target_id]
    if others:
        out.append("OTHER SECTIONS (record evidence here if the candidate covers them early):")
        for t in others:
            slots = ", ".join(f"{s.slot_id}[{session.targets[t.target_id].slots[s.slot_id].status}]" for s in t.slots)
            out.append(f"- {t.target_id} ({t.intent}): {slots}")

    recent = session.turns[-(RECENT_TURNS + 1):-1]
    if recent:
        out.append("RECENT TURNS:\n<transcript>\n" + "\n".join(f"{t.turn_id}: {t.text}" for t in recent) + "\n</transcript>")
    return "\n".join(out)
