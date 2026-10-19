"""Deterministic interview rules: coverage, probe limits, time, scheduling, PII regex. No LLM here."""

import re

from ..models import InterviewPlan, Session, SlotState, Target, TargetState

MAX_PROBES_PER_SLOT = 2
MAX_PROBES_PER_TARGET = 3
WRAPUP_RESERVE_SEC = 45
RESOLVED = {"filled", "unknown", "declined"}


def is_resolved(s: SlotState) -> bool:
    return s.status in RESOLVED


def coverage(target: Target, state: TargetState) -> float:
    slots = [s for s in target.slots if s.required] or target.slots
    if not slots:
        return 1.0
    done = sum(1 for s in slots if is_resolved(state.slots[s.slot_id]))
    return done / len(slots)


def remaining_sec(plan: InterviewPlan, session: Session) -> float:
    return plan.time_budget_sec - session.elapsed_sec


def must_move_on(plan: InterviewPlan, session: Session, target: Target) -> bool:
    st = session.targets[target.target_id]
    if remaining_sec(plan, session) < WRAPUP_RESERVE_SEC:
        return True
    if st.probe_count >= MAX_PROBES_PER_TARGET:
        return True
    if st.time_used_sec > target.time_budget_sec * 1.5:
        return True
    return st.time_used_sec > target.time_budget_sec and coverage(target, st) >= 0.6


def behind_schedule(plan: InterviewPlan, session: Session) -> bool:
    pending = [t for t in plan.targets if session.targets[t.target_id].status in ("pending", "active")]
    needed = sum(max(0, t.time_budget_sec - session.targets[t.target_id].time_used_sec) for t in pending)
    return needed > remaining_sec(plan, session) - WRAPUP_RESERVE_SEC


def next_target(plan: InterviewPlan, session: Session, exclude: str | None = None) -> Target | None:
    """Next pending target in plan order. When behind schedule, low-priority targets are skipped."""
    if remaining_sec(plan, session) < WRAPUP_RESERVE_SEC:
        return None
    behind = behind_schedule(plan, session)
    for t in plan.targets:
        if t.target_id == exclude or session.targets[t.target_id].status != "pending":
            continue
        if behind and t.priority >= 3:
            continue
        return t
    return None


def probes_left(slot: SlotState) -> int:
    return max(0, MAX_PROBES_PER_SLOT - slot.probes)


# Sensitive data the candidate volunteers (flagged for the recruiter, never used for scoring).
PII_PATTERNS = {
    "email": re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"),
    "phone": re.compile(r"(?<!\d)(?:\+?91[\s-]?)?[6-9]\d{4}[\s-]?\d{5}(?!\d)"),
    "aadhaar": re.compile(r"(?<!\d)\d{4}[\s-]?\d{4}[\s-]?\d{4}(?!\d)"),
    "pan": re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b"),
    "ifsc": re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b"),
    "card_or_account": re.compile(r"(?<!\d)\d{13,18}(?!\d)"),
    "salary": re.compile(r"(?:₹\s?\d|\brs\.?\s?\d|\binr\b|\blpa\b|\bctc\b|\bsalary\b|\blakhs?\b|\bper annum\b)", re.I),
}


def find_pii(text: str) -> list[tuple[str, str]]:
    hits = []
    for subtype, pattern in PII_PATTERNS.items():
        for m in pattern.finditer(text):
            hits.append((subtype, m.group(0)))
    return hits
