"""Candidate Prep: resume -> highlights, claims to verify, personalised section openers. Once per candidate."""

import logging

from .. import prompts
from ..llm.client import LLMError, get_llm
from ..models import Candidate, Fit, FitItem, InterviewPlan, Role

log = logging.getLogger("prep")


_MATCH = {"strong": 1.0, "partial": 0.5, "none": 0.0}


def score_fit(raw: dict) -> Fit:
    """The LLM judges each requirement; the score itself is plain arithmetic the recruiter can check."""
    items = []
    for it in raw.get("items") or []:
        if isinstance(it, dict) and it.get("requirement"):
            items.append(FitItem(requirement=str(it["requirement"])[:80], must_have=bool(it.get("must_have", True)),
                                 match=it.get("match") if it.get("match") in _MATCH else "none",
                                 evidence=str(it.get("evidence") or "")[:200]))
    total = sum(2 if i.must_have else 1 for i in items)
    score = round(100 * sum((2 if i.must_have else 1) * _MATCH[i.match] for i in items) / total) if total else None
    return Fit(score=score, items=items[:14], summary=raw.get("summary") or "",
               matched=[i.requirement for i in items if i.match != "none"],
               missing=[i.requirement for i in items if i.match == "none"])


async def build_plan(role: Role, cand: Candidate) -> InterviewPlan:
    plan = InterviewPlan(role_id=role.role_id, candidate_id=cand.candidate_id, candidate_name=cand.name.split()[0] if cand.name else "",
                         role_title=role.title, company=role.company, time_budget_sec=role.time_budget_sec,
                         targets=[t.model_copy(deep=True) for t in role.sections],
                         stt_hint=f"Interview for {role.title}{' at ' + role.company if role.company else ''}.")
    if not cand.resume.strip():
        return plan
    sections = [{"target_id": t.target_id, "name": t.name, "intent": t.intent, "opening_question": t.opening_question}
                for t in plan.targets]
    system, user = prompts.render("candidate_prep", title=role.title, jd=role.jd[:6000], sections=sections,
                                  resume=cand.resume[:10000])
    try:
        data, _ = await get_llm().json(agent="candidate_prep", role="strong", system=system, user=user,
                                       max_tokens=3000, temperature=0.3)
    except LLMError as e:
        log.warning("prep failed, using generic openers: %s", e)
        return plan
    plan.resume_highlights = [h for h in data.get("resume_highlights") or [] if isinstance(h, str)][:6]
    plan.claims_to_verify = [h for h in data.get("claims_to_verify") or [] if isinstance(h, str)][:4]
    plan.fit = score_fit(data.get("fit") if isinstance(data.get("fit"), dict) else {})
    vocab = [v for v in data.get("vocabulary") or [] if isinstance(v, str)][:30]
    if vocab:
        plan.stt_hint += " Terms: " + ", ".join(vocab) + "."
    for t in plan.targets:
        openers = data.get("openers") if isinstance(data.get("openers"), dict) else {}
        opener = openers.get(t.target_id)
        if isinstance(opener, str) and opener.strip().endswith("?"):
            t.opening_question = opener.strip()
    return plan
