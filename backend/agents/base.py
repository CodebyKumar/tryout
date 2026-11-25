"""The agent contract. Every agent folder has prompt.md, spec.py (output model + AgentSpec + entry function) and,
where code checks the answer, tools.py. The LLM proposes; the tools decide.

Prompt placeholders are {{name}}. The shared rules go in the system message; the rendered agent prompt goes in the
user message with static instructions first and per-call data last, so provider prefix caching can reuse the start.
"""

import json
import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, BeforeValidator

from ..integrations.llm import get_llm
from ..models import Usage

AGENTS_DIR = Path(__file__).parent


@dataclass(frozen=True)
class AgentSpec:
    name: str  # folder name; the prompt is agents/<name>/prompt.md
    tier: str  # "turn", "strong" or "aux": picks the model fallback chain in config.MODELS
    output: type[BaseModel]  # what the LLM must return; answers are validated against it
    prompt_version: str  # bump when prompt.md changes; recorded with every call
    max_tokens: int
    temperature: float
    timeout_sec: float  # per HTTP call, so a slow model falls back instead of stalling


async def run_agent[M: BaseModel](spec: AgentSpec, **values) -> tuple[M, Usage]:
    system, user = render(spec.name, **values)
    out, usage = await get_llm().json(
        agent=spec.name,
        role=spec.tier,
        system=system,
        user=user,
        output=spec.output,
        max_tokens=spec.max_tokens,
        temperature=spec.temperature,
        timeout=spec.timeout_sec,
    )
    usage.prompt_version = spec.prompt_version
    return out, usage


# ---------- Prompt rendering ----------


@cache
def _read(path: Path) -> str:
    return path.read_text()


# Closing tags of the data blocks in the prompts: user text containing one could end the block early.
_DATA_TAG = re.compile(r"</(candidate_turn|jd|notes|resume|transcript)>", re.I)


def _value(val) -> str:
    text = val if isinstance(val, str) else json.dumps(val, ensure_ascii=False)
    return _DATA_TAG.sub(r"<\/\1>", text)


def render(name: str, **values) -> tuple[str, str]:
    """Single pass, so a placeholder inside a value (a JD containing "{{resume}}") is never filled in."""
    prompt = _read(AGENTS_DIR / name / "prompt.md")
    text = re.sub(r"\{\{(\w+)\}\}", lambda m: _value(values[m[1]]) if m[1] in values else m[0], prompt)
    return _read(AGENTS_DIR / "_shared.md"), text


# ---------- Lenient output fields ----------
# Models are sloppy in harmless ways (null for "", a stray item in a list). Absorb those here instead of paying
# for a repair call; anything that cannot be read still fails validation and gets one repair attempt.

Text = Annotated[str, BeforeValidator(lambda v: "" if v is None else v if isinstance(v, str) else str(v))]
Strs = Annotated[
    list[str], BeforeValidator(lambda v: [x for x in v if isinstance(x, str)] if isinstance(v, list) else [])
]


def _as_object(x, name_key: str | None):
    """One list item as a dict, or None for junk. Models sometimes send each object as a JSON string, or leave
    stray fragments (":") in the list; a plain word or phrase becomes {name_key: phrase}."""
    if isinstance(x, dict):
        return x
    if not isinstance(x, str) or not any(c.isalpha() for c in x):
        return None
    text = x.strip()
    if text.startswith("{"):
        try:
            parsed = json.loads(text)
        except ValueError:
            return None  # a broken fragment of an object, not a name
        return parsed if isinstance(parsed, dict) else None
    return {name_key: text} if name_key else None


def objects(name_key: str | None = None) -> BeforeValidator:
    """For a list of objects: keep dicts, read objects sent as JSON strings, turn a bare phrase into {name_key: phrase}
    ("Python" for {"name": ...}), drop the rest."""

    def clean(v):
        if not isinstance(v, list):
            return []
        return [o for o in (_as_object(x, name_key) for x in v) if o is not None]

    return BeforeValidator(clean)
