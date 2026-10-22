"""Lock alembic_version against Supabase's public REST API (flagged by the Supabase security advisor).

Revision ID: 0002
Revises: 0001
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("alter table alembic_version enable row level security")


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("alter table alembic_version disable row level security")
