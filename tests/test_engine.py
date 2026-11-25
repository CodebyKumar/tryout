import subprocess
import sys

from backend import config
from backend.agents.turn_agent.spec import SlotUpdate
from backend.engine.state_machine import FALLBACK_SAY, _apply_updates, new_session, start
from backend.integrations.llm import LLMError
from backend.services.interviews import handle_user_turn


def started(plan):
    s = new_session(plan)
    start(plan, s)
    return s


async def test_retry_after_llm_failure_calls_llm_again(plan, fake_llm):  # B1
    replies = iter([LLMError("down"), {"ack": "Got it.", "probe_question": "Which stack do you use?"}])

    def turn_agent(system, user):
        r = next(replies)
        if isinstance(r, Exception):
            raise r
        return r

    fake_llm.handlers["turn_agent"] = turn_agent
    s = started(plan)
    assert (await handle_user_turn(plan, s, "I build payment systems."))["say"] == FALLBACK_SAY
    r = await handle_user_turn(plan, s, "I build payment systems.")
    assert not r.get("duplicate") and r["say"].endswith("Which stack do you use?")


async def test_double_submit_is_still_ignored(plan, fake_llm):
    fake_llm.handlers["turn_agent"] = lambda s, u: {"ack": "Okay.", "probe_question": "Which stack do you use?"}
    s = started(plan)
    await handle_user_turn(plan, s, "I build payment systems.")
    assert (await handle_user_turn(plan, s, "I build payment systems."))["duplicate"]


def test_slot_status_only_moves_forward(plan):  # B11
    s = new_session(plan)
    slot = s.sections["t_intro"].slots["background"]

    def update(status, value):
        update = SlotUpdate(section_id="t_intro", slot_id="background", status=status, value=value)
        _apply_updates(plan, s, [update], "u2")

    update("filled", "3 yrs backend")
    update("vague", "not sure")
    assert (slot.status, slot.value) == ("filled", "3 yrs backend")
    update("conflict", "said 5 yrs now")
    assert slot.status == "conflict"


async def test_probe_counts_without_gap(plan, fake_llm):  # B12
    fake_llm.handlers["turn_agent"] = lambda s, u: {"ack": "Okay.", "probe_question": "Which company was that?"}
    s = started(plan)
    await handle_user_turn(plan, s, "I do backend work.")
    assert s.sections["t_intro"].slots["background"].probes == 1


def test_engine_has_no_llm_imports():  # 2.7: the engine is pure code, testable without any agent or LLM
    code = (
        "import sys, backend.engine.state_machine, backend.engine.context;"
        "print([m for m in sys.modules if m.startswith(('backend.integrations.llm', 'backend.agents'))])"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout
    assert out.strip() == "[]"


async def test_turn_agent_context_stays_bounded_on_long_interviews(plan, fake_llm, monkeypatch):  # R6
    """Slots are the memory, not the transcript: the Turn Agent's input at turn 40 is about the size of turn 5."""
    monkeypatch.setattr(config, "MAX_PROBES_PER_SECTION", 100)  # keep it in one section for 40 answers
    n = iter(range(1000))
    fake_llm.handlers["turn_agent"] = lambda s, u: {
        "ack": "Okay.",
        "probe_question": f"What about topic{(k := next(n))} and area{k}?",
    }
    session = new_session(plan)
    start(plan, session)
    sizes = []
    for i in range(40):
        await handle_user_turn(plan, session, f"Answer {i}: " + "I worked on the payments service. " * 8)
        sizes.append(len(fake_llm.calls[-1][1]))
    assert session.state == "INTERVIEWING" and len(session.turns) > 80
    assert sizes[-1] <= sizes[4] * 1.15
    assert sizes[-1] / 4 < 2500  # about 4 characters per token: well under the turn model's context
