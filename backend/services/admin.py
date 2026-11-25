"""What the system is doing right now, for the admin page: live load, background jobs, LLM use per agent."""

from datetime import timedelta

from sqlalchemy import func, select

from .. import config, db
from .. import tables as t
from ..models import now
from . import interviews, jobs


async def overview() -> dict:
    async with db.transaction() as s:
        usage = (
            await s.execute(
                select(
                    t.LLMCall.agent,
                    func.sum(t.LLMCall.calls),
                    func.sum(t.LLMCall.prompt_tokens),
                    func.sum(t.LLMCall.cached_tokens),
                    func.sum(t.LLMCall.completion_tokens),
                    func.avg(t.LLMCall.latency_ms),
                )
                .where(t.LLMCall.created_at > now() - timedelta(days=1))
                .group_by(t.LLMCall.agent)
            )
        ).all()
    return {
        "live_interviews": await interviews.live_count(),
        "max_live_interviews": config.MAX_LIVE_INTERVIEWS,
        "jobs": await jobs.counts(),
        "usage_24h": [
            {
                "agent": agent,
                "calls": int(calls or 0),
                "prompt_tokens": int(p or 0),
                "cached_tokens": int(c or 0),
                "completion_tokens": int(o or 0),
                "avg_ms": int(ms or 0),
            }
            for agent, calls, p, c, o, ms in usage
        ],
        "voice": bool(config.DEEPGRAM_API_KEY),
    }
