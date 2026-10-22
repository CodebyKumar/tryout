"""Database tables (lean schema, docs/backend-audit.md section 8.4 trimmed). Services query these directly.

Normalised where rows are queried, appended or audited: roles and their immutable versions, candidates, plans,
sessions, turns (one row per message), evaluations (every run kept), decisions, LLM calls, jobs. Nested structures
that are always read whole are JSON: a brief's sections and criteria, a plan, a session's engine state, a report.
"""

from datetime import datetime

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
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from .models import now

Json = JSON().with_variant(JSONB(), "postgresql")
Id = String(40)


def _created() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), default=now, nullable=False)


class Base(DeclarativeBase):
    pass


class Recruiter(Base):  # accounts arrive in Phase 6
    __tablename__ = "recruiters"
    id: Mapped[str] = mapped_column(Id, primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()


class Role(Base):
    __tablename__ = "roles"
    id: Mapped[str] = mapped_column(Id, primary_key=True)
    recruiter_id: Mapped[str | None] = mapped_column(ForeignKey("recruiters.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(Text)
    company: Mapped[str] = mapped_column(Text, default="")
    current_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = _created()


class RoleVersion(Base):
    """Immutable once written: compile, refine and manual edits each add a version, so every candidate is
    interviewed and scored against the exact brief their plan was built on (audit A2, D1, D2)."""

    __tablename__ = "role_versions"
    __table_args__ = (
        UniqueConstraint("role_id", "version"),
        CheckConstraint("source in ('compile', 'refine', 'manual', 'import')", name="source"),
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
    __tablename__ = "candidates"
    id: Mapped[str] = mapped_column(Id, primary_key=True)
    role_id: Mapped[str] = mapped_column(ForeignKey("roles.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(Text)
    email: Mapped[str] = mapped_column(Text, default="")
    token: Mapped[str] = mapped_column(String(64), unique=True)  # indexed lookup for every candidate request
    status: Mapped[str] = mapped_column(String(12), default="invited")
    feedback_released: Mapped[bool] = mapped_column(Boolean, default=False)
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
    last_activity_at: Mapped[datetime] = _created()  # the idle sweeper's clock (Phase 5)
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


class Decision(Base):  # audit log (D10), written from Phase 5
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


class Job(Base):  # persisted background work (audit A3), Phase 5
    __tablename__ = "jobs"
    __table_args__ = (Index("jobs_due", "status", "run_after"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(20))
    target_id: Mapped[str] = mapped_column(Id)
    status: Mapped[str] = mapped_column(String(8), default="queued")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    run_after: Mapped[datetime] = _created()
    created_at: Mapped[datetime] = _created()
