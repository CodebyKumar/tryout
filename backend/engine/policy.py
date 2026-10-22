"""Deterministic interview rules: coverage, probe limits, time, scheduling. No LLM here."""

from .. import config
from ..models import InterviewPlan, Section, SectionState, Session, SlotState

RESOLVED = {"filled", "unknown", "declined"}


def is_resolved(s: SlotState) -> bool:
    return s.status in RESOLVED


def coverage(section: Section, state: SectionState) -> float:
    slots = [s for s in section.slots if s.required] or section.slots
    if not slots:
        return 1.0
    done = sum(1 for s in slots if is_resolved(state.slots[s.slot_id]))
    return done / len(slots)


def remaining_sec(plan: InterviewPlan, session: Session) -> float:
    return plan.time_budget_sec - session.elapsed_sec


def must_move_on(plan: InterviewPlan, session: Session, section: Section) -> bool:
    st = session.sections[section.section_id]
    if remaining_sec(plan, session) < config.WRAPUP_RESERVE_SEC:
        return True
    if st.probe_count >= config.MAX_PROBES_PER_SECTION:
        return True
    if st.time_used_sec > section.time_budget_sec * 1.5:
        return True
    return st.time_used_sec > section.time_budget_sec and coverage(section, st) >= 0.6


def behind_schedule(plan: InterviewPlan, session: Session) -> bool:
    pending = [t for t in plan.sections if session.sections[t.section_id].status in ("pending", "active")]
    needed = sum(max(0, t.time_budget_sec - session.sections[t.section_id].time_used_sec) for t in pending)
    return needed > remaining_sec(plan, session) - config.WRAPUP_RESERVE_SEC


def next_section(plan: InterviewPlan, session: Session, exclude: str | None = None) -> Section | None:
    """Next pending section in plan order. When behind schedule, low-priority sections are skipped."""
    if remaining_sec(plan, session) < config.WRAPUP_RESERVE_SEC:
        return None
    behind = behind_schedule(plan, session)
    for t in plan.sections:
        if t.section_id == exclude or session.sections[t.section_id].status != "pending":
            continue
        if behind and t.priority >= 3:
            continue
        return t
    return None


def probes_left(slot: SlotState) -> int:
    return max(0, config.MAX_PROBES_PER_SLOT - slot.probes)
