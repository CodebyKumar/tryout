"""Role Compiler: JD + recruiter notes -> interview sections + scoring criteria. Runs once per role."""

import re

from .. import prompts
from ..llm.client import get_llm
from ..models import Criterion, Role, Slot, Target


def snake(s: str, fallback: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", (s or "").lower()).strip("_")[:40] or fallback


async def compile_role(role: Role, from_document: bool = False, fixed_length: bool = True) -> Role:
    """from_document: role.jd holds a whole hiring document; title, notes and length are read from it."""
    if from_document and not fixed_length:
        m = re.search(r"(\d{1,2})\s*(?:-|to)?\s*(?:min|mins|minutes)\b", role.jd, re.I)
        if m and 3 <= int(m.group(1)) <= 60:
            role.time_budget_sec, fixed_length = int(m.group(1)) * 60, True
    system, user = prompts.render("role_compiler", title="" if role.title == "Untitled role" else role.title,
                                  jd=role.jd[:15000], notes=role.notes or "none", time_budget_sec=str(role.time_budget_sec))
    data, _ = await get_llm().json(agent="role_compiler", role="strong", system=system, user=user,
                                   max_tokens=7000, temperature=0.2)
    if from_document:
        length = data.get("time_budget_sec")
        if not fixed_length and isinstance(length, (int, float)) and 180 <= length <= 3600:
            role.time_budget_sec = int(length)
        role.jd = data.get("jd_summary") or role.jd
        role.notes = data.get("interviewer_notes") or role.notes
    return apply_compiled(role, data)


def _num(v, default: float) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _as_dict(item, key: str) -> dict | None:
    """Models sometimes return plain strings where objects were asked for; treat a string as just its name."""
    if isinstance(item, dict):
        return item
    if isinstance(item, str) and item.strip():
        return {key: item.strip()}
    return None


def apply_compiled(role: Role, data: dict) -> Role:
    """Validate the compiler output so a sloppy response can't break interviews."""
    sections: list[Target] = []
    for i, raw in enumerate(data.get("sections") or []):
        raw = _as_dict(raw, "name")
        if not raw:
            continue
        slots = []
        for j, s in enumerate(raw.get("slots") or []):
            s = _as_dict(s, "desc")
            if not s:
                continue
            sid = snake(s.get("slot_id") or s.get("desc"), f"s{j + 1}")
            if sid not in {x.slot_id for x in slots}:
                slots.append(Slot(slot_id=sid, desc=s.get("desc") or sid, required=bool(s.get("required", True))))
        tid = snake(raw.get("target_id"), f"t_{i + 1}")
        if tid in {t.target_id for t in sections}:
            tid = f"{tid}_{i + 1}"
        sections.append(Target(target_id=tid, name=raw.get("name") or tid, intent=raw.get("intent") or "",
                               opening_question=raw.get("opening_question") or "Tell me about your background.",
                               slots=slots or [Slot(slot_id="answer", desc="A specific, concrete answer")],
                               time_budget_sec=max(30, int(_num(raw.get("time_budget_sec"), 120))),
                               priority=min(3, max(1, int(_num(raw.get("priority"), 2))))))
    if not sections:
        raise ValueError("Could not design interview sections from this JD")
    cap = int(role.time_budget_sec * 0.85)
    total = sum(t.time_budget_sec for t in sections)
    if total > cap:
        for t in sections:
            t.time_budget_sec = max(30, int(t.time_budget_sec * cap / total))

    criteria = []
    for i, c in enumerate(data.get("criteria") or []):
        c = _as_dict(c, "name")
        if not c:
            continue
        cid = snake(c.get("criterion_id") or c.get("name"), f"c{i + 1}")
        if cid in {x.criterion_id for x in criteria}:
            cid = f"{cid}_{i + 1}"
        criteria.append(Criterion(criterion_id=cid, name=c.get("name") or cid, description=c.get("description") or "",
                                  weight=min(3.0, max(0.5, _num(c.get("weight"), 1.0))),
                                  above_bar=c.get("above_bar") or "", meets_bar=c.get("meets_bar") or "",
                                  below_bar=c.get("below_bar") or ""))
    if not criteria:
        raise ValueError("Could not work out scoring criteria from this document. Try again or add the key requirements.")
    role.sections, role.criteria = sections, criteria
    role.company = role.company or data.get("company") or ""
    if not role.title.strip() or role.title == "Untitled role":
        role.title = (data.get("title") or "Untitled role").strip()
    return role


async def refine_role(role: Role, instruction: str) -> Role:
    """Apply a recruiter's plain-language change ("add a section on agents", "drop logistics") to the brief."""
    current = {"sections": [t.model_dump() for t in role.sections], "criteria": [c.model_dump() for c in role.criteria]}
    system, user = prompts.render("role_refine", title=role.title, current=current, instruction=instruction[:2000],
                                  time_budget_sec=str(role.time_budget_sec))
    data, _ = await get_llm().json(agent="role_refine", role="strong", system=system, user=user,
                                   max_tokens=6000, temperature=0.2)
    return apply_compiled(role, data)
