"""One-off: import the prototype's data/*.json into the database (task 4.8). Safe to re-run: what exists is skipped.

uv run python scripts/import_json.py            imports into DATABASE_URL, then prints counts to check by hand
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import func, select  # noqa: E402

from backend import config, db  # noqa: E402
from backend import tables as t  # noqa: E402
from backend.models import Candidate, InterviewPlan, Role, Session, new_id  # noqa: E402
from backend.services import candidates, roles, sessions  # noqa: E402

RENAMES = {"target_id": "section_id", "current_target_id": "current_section_id", "targets": "sections"}


def renamed(value):
    """The prototype called sections "targets": rename the keys at every level."""
    if isinstance(value, dict):
        return {RENAMES.get(k, k): renamed(v) for k, v in value.items()}
    if isinstance(value, list):
        return [renamed(v) for v in value]
    return value


def read(kind: str) -> list[dict]:
    return [renamed(json.loads(p.read_text())) for p in sorted((config.DATA_DIR / kind).glob("*.json"))]


async def main() -> None:
    plans = {p["plan_id"]: p for p in read("plans")}
    by_session = {s["session_id"]: s for s in read("sessions")}
    versions: dict[str, str] = {}

    for raw in read("roles"):
        async with db.transaction() as s:
            if await s.get(t.Role, raw["role_id"]):
                versions[raw["role_id"]] = (await roles.load(s, raw["role_id"])).version_id
                continue
            role = await roles.save_version(s, Role.model_validate(raw), "import")
            versions[role.role_id] = role.version_id

    for raw in read("candidates"):
        if raw["role_id"] not in versions:
            print("skip candidate without role:", raw["candidate_id"])
            continue
        cand = Candidate.model_validate(raw)
        async with db.transaction() as s:
            if await s.get(t.Candidate, cand.candidate_id):
                continue
            await candidates.save(s, cand)
            if cand.resume.strip():
                s.add(t.Document(id=new_id("d"), kind="resume", candidate_id=cand.candidate_id, text=cand.resume))
            if cand.plan_id and cand.plan_id in plans:
                plan = InterviewPlan.model_validate({**plans[cand.plan_id], "role_version_id": versions[cand.role_id]})
                plan.prep_status = "ok" if plan.fit.score is not None else "skipped"
                s.add(
                    t.Plan(
                        id=plan.plan_id,
                        candidate_id=cand.candidate_id,
                        role_version_id=plan.role_version_id,
                        prep_status=plan.prep_status,
                        data=plan.model_dump(mode="json", exclude={"usage"}),
                    )
                )
                await s.flush()
            raw_session = by_session.get(cand.session_id or "")
            if raw_session and cand.plan_id in plans:
                session = Session.model_validate(raw_session)
                await sessions.save(s, session)
                if session.report:
                    s.add(
                        t.Evaluation(
                            id=new_id("e"),
                            session_id=session.session_id,
                            status="ok",
                            overall_score=session.report.overall_score,
                            recommendation=session.report.recommendation,
                            report=session.report.model_dump(mode="json"),
                            is_current=True,
                        )
                    )

    async with db.transaction() as s:
        for table in (
            t.Role,
            t.RoleVersion,
            t.Candidate,
            t.Plan,
            t.Session,
            t.Turn,
            t.Evaluation,
            t.Document,
            t.LLMCall,
        ):
            print(f"{table.__tablename__:16} {await s.scalar(select(func.count()).select_from(table))}")
    print(
        f"files:           roles {len(read('roles'))}, candidates {len(read('candidates'))}, "
        f"plans {len(plans)}, sessions {len(by_session)}"
    )


if __name__ == "__main__":
    asyncio.run(main())
