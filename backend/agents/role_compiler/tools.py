"""Role Compiler tools: turn a sloppy brief into one that cannot break interviews (ids, caps, time budget)."""

import re
from typing import TYPE_CHECKING

from ...models import Criterion, Role, Section, Slot

if TYPE_CHECKING:
    from .spec import CompiledRole


def snake(s: str, fallback: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", (s or "").lower()).strip("_")[:40] or fallback


def apply_compiled(role: Role, out: "CompiledRole") -> Role:
    """Unique ids, weights 0.5-3, priorities 1-3, sections within 85% of the interview length."""
    sections: list[Section] = []
    for i, raw in enumerate(out.sections):
        slots = []
        for j, s in enumerate(raw.slots):
            sid = snake(s.slot_id or s.desc, f"s{j + 1}")
            if sid not in {x.slot_id for x in slots}:
                slots.append(Slot(slot_id=sid, desc=s.desc or sid, required=s.required))
        tid = snake(raw.section_id, f"t_{i + 1}")
        if tid in {t.section_id for t in sections}:
            tid = f"{tid}_{i + 1}"
        sections.append(
            Section(
                section_id=tid,
                name=raw.name or tid,
                intent=raw.intent,
                opening_question=raw.opening_question or "Tell me about your background.",
                slots=slots or [Slot(slot_id="answer", desc="A specific, concrete answer")],
                time_budget_sec=max(30, int(raw.time_budget_sec or 120)),
                priority=min(3, max(1, int(raw.priority or 2))),
            )
        )
    if not sections:
        raise ValueError("Could not design interview sections from this JD")
    cap = int(role.time_budget_sec * 0.85)
    total = sum(t.time_budget_sec for t in sections)
    if total > cap:
        # Scale only the time above the 30 s floor, so the floor cannot push the total back over the cap.
        spare, extra = max(0, cap - 30 * len(sections)), max(1, total - 30 * len(sections))
        for t in sections:
            t.time_budget_sec = 30 + int((t.time_budget_sec - 30) * spare / extra)

    criteria = []
    for i, c in enumerate(out.criteria):
        cid = snake(c.criterion_id or c.name, f"c{i + 1}")
        if cid in {x.criterion_id for x in criteria}:
            cid = f"{cid}_{i + 1}"
        criteria.append(
            Criterion(
                criterion_id=cid,
                name=c.name or cid,
                description=c.description,
                weight=min(3.0, max(0.5, c.weight or 1.0)),
                above_bar=c.above_bar,
                meets_bar=c.meets_bar,
                below_bar=c.below_bar,
            )
        )
    if not criteria:
        raise ValueError(
            "Could not work out scoring criteria from this document. Try again or add the key requirements."
        )
    role.sections, role.criteria = sections, criteria
    role.company = role.company or out.company
    if not role.title.strip() or role.title == "Untitled role":
        role.title = (out.title or "Untitled role").strip()
    return role
