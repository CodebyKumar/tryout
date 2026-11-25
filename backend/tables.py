"""Database tables. Services query these directly; there is no repository layer.

Normalised where rows are queried, appended or audited: recruiters and their login sessions, roles and their
immutable versions, candidates, plans, sessions, turns (one row per message), evaluations (every run kept),
decisions, LLM calls, jobs. Nested structures that are always read whole are JSON: a brief's sections and criteria,
a plan, a session's engine state, a report.

Ownership: recruiter -> roles -> candidates -> plans -> sessions. Every recruiter query starts from roles.recruiter_id.
"""

from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from .models import now

Json = JSON().with_variant(JSONB(), "postgresql")
Id = String(40)


class Timestamp(TypeDecorator):
    """A UTC timestamp that always reads back time-zone aware. Postgres keeps the zone; SQLite (tests) drops it."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_result_value(self, value, dialect):
        return value.replace(tzinfo=UTC) if value is not None and value.tzinfo is None else value


def _created() -> Mapped[datetime]:
    return mapped_column(Timestamp, default=now, nullable=False)


class Base(DeclarativeBase):
    pass


class Recruiter(Base):
    """An account. New sign-ups are pending until an admin approves them; demo is the shared read-only account."""

    __tablename__ = "recruiters"
    __table_args__ = (CheckConstraint("status in ('pending', 'active', 'disabled', 'demo')", name="status"),)
    id: Mapped[str] = mapped_column(Id, primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    name: Mapped[str] = mapped_column(Text)
    password_hash: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(10), default="pending")
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = _created()


class AuthSession(Base):
    """A login. Only the token's SHA-256 is stored, so a copy of the database cannot be used to sign in."""

    __tablename__ = "auth_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    recruiter_id: Mapped[str] = mapped_column(ForeignKey("recruiters.id", ondelete="CASCADE"), index=True)
    expires_at: Mapped[datetime] = mapped_column(Timestamp)
    created_at: Mapped[datetime] = _created()


class Role(Base):
    __tablename__ = "roles"
    __table_args__ = (CheckConstraint("integrity in ('standard', 'strict')", name="integrity"),)
    id: Mapped[str] = mapped_column(Id, primary_key=True)
    recruiter_id: Mapped[str] = mapped_column(ForeignKey("recruiters.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(Text)
    company: Mapped[str] = mapped_column(Text, default="")
    integrity: Mapped[str] = mapped_column(
        String(8), default="standard"
    )  # strict: full screen, blocks, extension check
    current_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = _created()


class RoleVersion(Base):
    """Immutable once written: compile, refine and manual edits each add a version, so every candidate is
    interviewed and scored against the exact brief their plan was built on (audit A2, D1, D2)."""

    __tablename__ = "role_versions"
    __table_args__ = (
        UniqueConstraint("role_id", "version"),
        CheckConstraint("source in ('compile', 'refine', 'manual')", name="source"),
    )
    id: Mapped[str] = mapped_column(Id, primary_key=True)
    role_id: Mapped[str] = mapped_column(ForeignKey("roles.id", ondelete="CASCADE"))
    version: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(10))
    jd: Mapped[str] = mapped_column(Text)  # the JD, or the AI's summary of an uploaded document
    notes: Mapped[str] = mapped_column(Text, default="")
    time_budget_sec: Mapped[int] = mapped_column(Integer)
    brief: Mapped[dict] = mapped_column(Json)  # {"sections": [...], "criteria": [...]}
    instruction: Mapped[str | None] = mapped_column(Text)  # the refine request that produced it
    created_at: Mapped[datetime] = _created()


class Document(Base):
    """What a recruiter or candidate uploaded, as text (audit B13, D8). The file itself goes to object storage."""

    __tablename__ = "documents"
    __table_args__ = (CheckConstraint("kind in ('role_source', 'resume')", name="kind"),)
    id: Mapped[str] = mapped_column(Id, primary_key=True)
    kind: Mapped[str] = mapped_column(String(12))
    role_id: Mapped[str | None] = mapped_column(ForeignKey("roles.id", ondelete="CASCADE"), index=True)
    candidate_id: Mapped[str | None] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str | None] = mapped_column(Text)
    storage_path: Mapped[str | None] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()


class Candidate(Base):
    """status is where the interview is; decision is what the recruiter chose. They change independently (audit C1)."""

    __tablename__ = "candidates"
    __table_args__ = (
        CheckConstraint("status in ('invited', 'in_progress', 'completed')", name="status"),
        CheckConstraint("decision in ('advanced', 'hold', 'rejected')", name="decision"),
    )
    id: Mapped[str] = mapped_column(Id, primary_key=True)
    role_id: Mapped[str] = mapped_column(ForeignKey("roles.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(Text)
    email: Mapped[str] = mapped_column(Text, default="")
    # The private link. Kept readable so the recruiter can copy it again; it expires at closes_at and a reset
    # replaces it. 128 random bits, so it cannot be guessed.
    token: Mapped[str] = mapped_column(String(64), unique=True)
    status: Mapped[str] = mapped_column(String(12), default="invited")
    decision: Mapped[str | None] = mapped_column(String(10))
    opens_at: Mapped[datetime | None] = mapped_column(Timestamp)  # scheduled start; None: any time
    closes_at: Mapped[datetime] = mapped_column(Timestamp)  # the link stops working after this
    created_at: Mapped[datetime] = _created()


class Plan(Base):
    """A candidate's interview plan, built on one role version. Only one is current per candidate."""

    __tablename__ = "interview_plans"
    __table_args__ = (
        Index(
            "one_current_plan",
            "candidate_id",
            unique=True,
            sqlite_where=text("is_current"),
            postgresql_where=text("is_current"),
        ),
    )
    id: Mapped[str] = mapped_column(Id, primary_key=True)
    candidate_id: Mapped[str] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"))
    role_version_id: Mapped[str] = mapped_column(ForeignKey("role_versions.id"))
    prep_status: Mapped[str] = mapped_column(String(10))
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    data: Mapped[dict] = mapped_column(Json)  # the InterviewPlan
    created_at: Mapped[datetime] = _created()


class Session(Base):
    __tablename__ = "sessions"
    id: Mapped[str] = mapped_column(Id, primary_key=True)
    plan_id: Mapped[str] = mapped_column(ForeignKey("interview_plans.id", ondelete="CASCADE"), unique=True)
    state: Mapped[str] = mapped_column(String(12), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)  # a write must name the version it read (stale = 409)
    last_activity_at: Mapped[datetime] = _created()  # the idle sweeper's clock; also counts live interviews
    data: Mapped[dict] = mapped_column(Json)  # engine state: sections, current section, flags, timing
    created_at: Mapped[datetime] = _created()


class Turn(Base):
    """Append-only, one row per message (audit D3)."""

    __tablename__ = "turns"
    __table_args__ = (UniqueConstraint("session_id", "seq"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"))
    seq: Mapped[int] = mapped_column(Integer)
    turn_id: Mapped[str] = mapped_column(String(12))  # "u3" / "a4": what quotes and slot evidence cite
    speaker: Mapped[str] = mapped_column(String(5))  # agent / user
    fallback: Mapped[bool] = mapped_column(Boolean, default=False)
    text: Mapped[str] = mapped_column(Text)
    section_id: Mapped[str | None] = mapped_column(String(60))
    # Agent turns only: what the Turn Agent proposed and what code decided. Shown on the recruiter's trace page.
    trace: Mapped[dict | None] = mapped_column(Json)
    created_at: Mapped[datetime] = _created()


class Evaluation(Base):
    """Every run is kept (audit D4); is_current marks the one shown."""

    __tablename__ = "evaluations"
    __table_args__ = (
        Index(
            "one_current_eval",
            "session_id",
            unique=True,
            sqlite_where=text("is_current"),
            postgresql_where=text("is_current"),
        ),
    )
    id: Mapped[str] = mapped_column(Id, primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(8))  # ok / failed
    error: Mapped[str | None] = mapped_column(Text)
    overall_score: Mapped[float | None] = mapped_column(Float)
    recommendation: Mapped[str | None] = mapped_column(String(8))
    report: Mapped[dict | None] = mapped_column(Json)
    model: Mapped[str | None] = mapped_column(Text)
    prompt_version: Mapped[str | None] = mapped_column(String(10))
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = _created()


class Decision(Base):
    """Every change of the recruiter's decision on a candidate (audit D10)."""

    __tablename__ = "decisions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    candidate_id: Mapped[str] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"), index=True)
    recruiter_id: Mapped[str | None] = mapped_column(ForeignKey("recruiters.id", ondelete="SET NULL"))
    from_decision: Mapped[str | None] = mapped_column(String(10))
    to_decision: Mapped[str | None] = mapped_column(String(10))
    created_at: Mapped[datetime] = _created()


class LLMCall(Base):
    """Usage of every agent call (audit C3): cost per role, per candidate, per interview."""

    __tablename__ = "llm_calls"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent: Mapped[str] = mapped_column(String(20))
    model: Mapped[str] = mapped_column(Text)
    prompt_version: Mapped[str] = mapped_column(String(10), default="")
    role_id: Mapped[str | None] = mapped_column(ForeignKey("roles.id", ondelete="SET NULL"), index=True)
    candidate_id: Mapped[str | None] = mapped_column(ForeignKey("candidates.id", ondelete="SET NULL"), index=True)
    session_id: Mapped[str | None] = mapped_column(ForeignKey("sessions.id", ondelete="SET NULL"), index=True)
    calls: Mapped[int] = mapped_column(Integer, default=1)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cached_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = _created()


class Job(Base):
    """Background work that must survive a restart (audit A3): resume prep and evaluation. Done jobs are deleted."""

    __tablename__ = "jobs"
    __table_args__ = (
        Index("jobs_due", "status", "run_after"),
        CheckConstraint("status in ('queued', 'running', 'failed')", name="status"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(20))
    target_id: Mapped[str] = mapped_column(Id)
    status: Mapped[str] = mapped_column(String(8), default="queued")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    run_after: Mapped[datetime] = _created()
    created_at: Mapped[datetime] = _created()
