"""Prompt templates live in backend/prompts/*.md. Placeholders are {{name}}.

The shared rules go in the system message; the rendered agent prompt goes in the user message with
static instructions first and per-turn data last, so provider prefix caching can reuse the start.
"""

import json
from functools import cache

from . import config


@cache
def _read(name: str) -> str:
    return (config.PROMPTS_DIR / f"{name}.md").read_text()


def render(name: str, **values) -> tuple[str, str]:
    text = _read(name)
    for key, val in values.items():
        if not isinstance(val, str):
            val = json.dumps(val, ensure_ascii=False)
        text = text.replace("{{" + key + "}}", val)
    return _read("_shared"), text
