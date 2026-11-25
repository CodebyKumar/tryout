import os

import pytest
from pydantic import ValidationError

from backend.agents import evaluator, role_compiler, turn_agent
from backend.agents.base import render, run_agent
from backend.agents.candidate_prep import spec as prep_spec

VALUES = [
    "company",
    "candidate_name",
    "role_title",
    "context",
    "turn_id",
    "user_text",
    "title",
    "jd",
    "sections",
    "resume",
    "criteria",
    "slots",
    "transcript",
    "notes",
    "time_budget_sec",
    "current",
    "instruction",
]


def test_sloppy_but_harmless_answers_validate():
    out = evaluator.EvalOut.model_validate(
        {
            "criteria": [{"criterion_id": "x", "rating": None, "evidence": [{"turn_id": "u2", "quote": None}]}, "junk"],
            "strengths": ["clear", 3, None],
            "summary": None,
        }
    )
    assert len(out.criteria) == 1 and out.criteria[0].evidence[0].quote == "" and out.strengths == ["clear"]
    brief = role_compiler.CompiledRole.model_validate(
        {"sections": ["Intro", {"name": "Past work", "slots": ["What they built"]}]}
    )
    assert [s.name for s in brief.sections] == ["Intro", "Past work"] and brief.sections[1].slots[
        0
    ].desc == "What they built"


async def test_fake_llm_rejects_answers_that_break_the_contract(fake_llm):  # 2.6
    fake_llm.handlers["turn_agent"] = lambda s, u: {"ack": "Ok.", "user_wants_stop": "maybe"}
    with pytest.raises(ValidationError):
        await run_agent(turn_agent.SPEC, context="", user_text="hi")


async def test_usage_records_prompt_version(fake_llm):  # 2.5
    fake_llm.handlers["turn_agent"] = lambda s, u: {"ack": "Ok."}
    out, usage = await run_agent(turn_agent.SPEC, context="", user_text="hi")
    assert out.ack == "Ok." and (usage.agent, usage.prompt_version) == ("turn_agent", turn_agent.SPEC.prompt_version)


@pytest.mark.parametrize("agent", ["turn_agent", "candidate_prep", "evaluator", "role_compiler", "role_refine"])
def test_prompt_starts_with_static_text(agent):
    """Groq caches only an exact prefix (and cached tokens skip the rate limit): the fixed instructions must come
    before anything that changes per call, so every call shares them."""
    a = render(agent, **dict.fromkeys(VALUES, "first"))
    b = render(agent, **dict.fromkeys(VALUES, "second"))
    shared = len(os.path.commonprefix([a[0] + a[1], b[0] + b[1]]))
    assert shared / len(a[0] + a[1]) > 0.75


def test_objects_sent_as_json_strings_are_read_not_renamed():
    """A real Groq answer sent each fit item as a JSON string plus stray fragments; the score came out 11% instead
    of about 80% because every string became a requirement named after its own JSON."""
    out = prep_spec.FitOut.model_validate(
        {
            "items": [
                {"requirement": "Python or Go", "must_have": True, "match": "strong"},
                '{"requirement": "Designing reliable APIs", "must_have": true, "match": "strong"}',
                '{ "requirement": "Payments domain", "must_ha',
                ":",
                "Kafka",
            ]
        }
    )
    assert [i.requirement for i in out.items] == ["Python or Go", "Designing reliable APIs"]  # prose is dropped
    assert out.items[1].match == "strong"
