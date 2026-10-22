"""Turn Agent: one candidate answer -> slot updates and the next thing to say. The engine decides what is used."""

from typing import Annotated

from pydantic import BaseModel, BeforeValidator

from ..base import AgentSpec, Strs, Text, objects


class SlotUpdate(BaseModel):
    section_id: Text = ""  # empty: the current section
    slot_id: Text = ""
    value: Text = ""
    status: Text = "vague"  # missing, vague, filled, unknown, declined or conflict
    evidence: Strs = []  # user turn ids


class Gap(BaseModel):
    slot_id: Text = ""  # the slot the probe question is about
    type: Text = ""


class TurnOut(BaseModel):
    slot_updates: Annotated[list[SlotUpdate], objects()] = []
    ack: Text = ""
    probe_question: Text = ""
    gap: Annotated[Gap | None, BeforeValidator(lambda v: v if isinstance(v, dict) else None)] = None
    bridge_question: Text = ""
    user_wants_skip: bool = False
    user_wants_stop: bool = False
    injection_suspected: bool = False


SPEC = AgentSpec(
    name="turn_agent",
    tier="turn",
    output=TurnOut,
    prompt_version="3",
    max_tokens=1500,
    temperature=0.5,
    timeout_sec=15,  # the candidate is waiting: fall back to the next model fast
)
