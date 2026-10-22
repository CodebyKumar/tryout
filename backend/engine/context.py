"""Builds the per-turn STATE block for the Turn Agent. Small and flat: slots are the memory, not the transcript."""

from .. import config
from ..models import InterviewPlan, Section, Session
from . import policy

RECENT_TURNS = 4  # enough to follow the thread; older turns live on as slot values, which are shorter


def _fmt(sec: float) -> str:
    sec = max(0, int(sec))
    return f"{sec // 60:02d}:{sec % 60:02d}"


def _slot_lines(section: Section, session: Session, with_probes: bool) -> list[str]:
    st = session.sections[section.section_id]
    lines = []
    for s in section.slots:
        ss = st.slots[s.slot_id]
        req = "required" if s.required else "optional"
        if ss.value:
            state = f'{ss.status} "{ss.value}"'
        else:
            state = ss.status
        probe = f" probes_left {policy.probes_left(ss)}" if with_probes else ""
        lines.append(f"- {s.slot_id} ({s.desc}, {req}): {state}{probe}")
    return lines


def build(plan: InterviewPlan, session: Session) -> str:
    out = [
        f"TIME: {_fmt(session.elapsed_sec)} of {_fmt(plan.time_budget_sec)} used. "
        f"Remaining {_fmt(policy.remaining_sec(plan, session))}. "
        f"Behind schedule: {'yes' if policy.behind_schedule(plan, session) else 'no'}."
    ]

    cur = plan.section(session.current_section_id)
    st = session.sections[cur.section_id]
    out += [
        f"CURRENT SECTION: {cur.section_id} ({cur.name}) | {_fmt(st.time_used_sec)} of {_fmt(cur.time_budget_sec)} used | "
        f"coverage {int(policy.coverage(cur, st) * 100)}% | probes used {st.probe_count} of {config.MAX_PROBES_PER_SECTION}",
        f"INTENT: {cur.intent}",
        "SLOTS:",
        *_slot_lines(cur, session, with_probes=True),
    ]
    nxt = policy.next_section(plan, session, exclude=cur.section_id)
    out.append(f"NEXT: {nxt.name} | question to bridge into: {nxt.opening_question}" if nxt else "NEXT: none")

    if plan.resume_highlights:
        out.append("RESUME HIGHLIGHTS: " + " | ".join(plan.resume_highlights))
    if plan.claims_to_verify:
        out.append("CLAIMS TO VERIFY (probe for specifics when relevant): " + " | ".join(plan.claims_to_verify))

    others = [t for t in plan.sections if t.section_id != session.current_section_id]
    if others:
        out.append("OTHER SECTIONS (record evidence here if the candidate covers them early):")
        for t in others:
            slots = ", ".join(f"{s.slot_id}[{session.sections[t.section_id].slots[s.slot_id].status}]" for s in t.slots)
            out.append(f"- {t.section_id} ({t.intent}): {slots}")

    recent = session.turns[-(RECENT_TURNS + 1) : -1]
    if recent:
        out.append(
            "RECENT TURNS:\n<transcript>\n" + "\n".join(f"{t.turn_id}: {t.text}" for t in recent) + "\n</transcript>"
        )
    return "\n".join(out)
