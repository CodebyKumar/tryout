"""Scores move from a 1-5 scale to 1-10: double every stored overall and criterion score.

Revision ID: 0003
Revises: 0002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_evals = sa.table("evaluations", sa.column("id"), sa.column("overall_score"), sa.column("report", sa.JSON))


def _rescale(factor: float) -> None:
    conn = op.get_bind()
    for row in conn.execute(sa.select(_evals.c.id, _evals.c.overall_score, _evals.c.report)).all():
        report = dict(row.report or {})
        scale = lambda v: None if v is None else round(v * factor, 1)  # noqa: E731
        report["overall_score"] = scale(report.get("overall_score"))
        report["criteria"] = [{**c, "score": scale(c.get("score"))} for c in report.get("criteria", [])]
        conn.execute(
            _evals.update().where(_evals.c.id == row.id).values(overall_score=scale(row.overall_score), report=report)
        )


def upgrade() -> None:
    _rescale(2)


def downgrade() -> None:
    _rescale(0.5)
