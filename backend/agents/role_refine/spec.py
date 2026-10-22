"""Role Refine: a recruiter's plain-language change ("add a section on agents", "drop logistics") -> new brief."""

from ...models import Role
from ..base import AgentSpec, run_agent
from ..role_compiler import CompiledRole, apply_compiled

SPEC = AgentSpec(
    name="role_refine",
    tier="strong",
    output=CompiledRole,  # same brief shape as the compiler, validated by the same tool
    prompt_version="2",
    max_tokens=6000,
    temperature=0.2,
    timeout_sec=90,
)


async def refine_role(role: Role, instruction: str) -> Role:
    current = {"sections": [t.model_dump() for t in role.sections], "criteria": [c.model_dump() for c in role.criteria]}
    out, usage = await run_agent(
        SPEC,
        title=role.title,
        current=current,
        instruction=instruction[:2000],
        time_budget_sec=str(role.time_budget_sec),
    )
    role.usage.append(usage)
    return apply_compiled(role, out)
