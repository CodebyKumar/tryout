"""Data contracts: Role (recruiter side), Candidate, InterviewPlan, Session, Report."""

import secrets
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from . import config


def now() -> datetime:
    return datetime.now(UTC)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:10]}"


class Usage(BaseModel):
    agent: str
    model: str
    prompt_version: str = ""
    calls: int = 1  # HTTP calls that produced the answer (2 when a repair was needed)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0
    latency_ms: int = 0


# ---------- Recruiter side ----------


class Slot(BaseModel):
    """One piece of evidence a section must collect, e.g. 'own_role: what they personally built'."""

    slot_id: str
    desc: str
    required: bool = True


class Section(BaseModel):
    """An interview section."""

    section_id: str
    name: str
    intent: str
    opening_question: str
    slots: list[Slot]
    time_budget_sec: int = 120
    priority: int = 2


class Criterion(BaseModel):
    criterion_id: str
    name: str
    description: str
    weight: float = 1.0
    above_bar: str = ""
    meets_bar: str = ""
    below_bar: str = ""


class Role(BaseModel):
    role_id: str = Field(default_factory=lambda: new_id("r"))
    title: str
    company: str = ""
    jd: str  # the job description, or the AI's summary of an uploaded document
    document: str = ""  # the recruiter's uploaded document as they wrote it
    notes: str = ""
    time_budget_sec: int = config.TIME_BUDGET_SEC
    sections: list[Section] = []
    criteria: list[Criterion] = []
    usage: list[Usage] = []  # LLM calls not yet saved
    version: int = 0  # which version of the brief this is (0: not saved yet)
    version_id: str = ""
    created_at: datetime = Field(default_factory=now)


CandidateStatus = Literal["invited", "in_progress", "completed", "advanced", "hold", "rejected"]


class Candidate(BaseModel):
    candidate_id: str = Field(default_factory=lambda: new_id("c"))
    token: str = Field(default_factory=lambda: secrets.token_urlsafe(16))
    role_id: str
    name: str
    email: str = ""
    resume: str = ""
    status: CandidateStatus = "invited"
    session_id: str | None = None
    plan_id: str | None = None
    feedback_released: bool = False
    created_at: datetime = Field(default_factory=now)


# ---------- Interview ----------


class FitItem(BaseModel):
    requirement: str
    must_have: bool = True
    match: Literal["strong", "partial", "none"] = "none"
    evidence: str = ""  # what in the resume shows it


class Fit(BaseModel):
    """How well the resume matches the role. Shown to the recruiter only.
    score = weighted share of requirements met: must-haves count 2, nice-to-haves 1; strong 1, partial 0.5, none 0."""

    score: int | None = None  # 0-100
    items: list[FitItem] = []
    matched: list[str] = []
    missing: list[str] = []
    summary: str = ""


class InterviewPlan(BaseModel):
    plan_id: str = Field(default_factory=lambda: new_id("p"))
    role_id: str
    role_version_id: str = ""  # the brief this plan was built on; the evaluator scores against the same one
    candidate_id: str
    candidate_name: str
    role_title: str
    company: str = ""
    time_budget_sec: int
    sections: list[Section]
    resume_highlights: list[str] = []
    claims_to_verify: list[str] = []
    fit: Fit = Fit()
    stt_hint: str = ""  # vocabulary for speech-to-text: role, tools, resume terms
    prep_status: Literal["ok", "failed", "skipped"] = "skipped"  # skipped: no resume to read
    prep_error: str = ""
    usage: list[Usage] = []  # LLM calls made while preparing this plan

    def section(self, section_id: str) -> Section | None:
        return next((t for t in self.sections if t.section_id == section_id), None)


SlotStatus = Literal["missing", "vague", "filled", "unknown", "declined", "conflict"]


class SlotState(BaseModel):
    value: str | None = None
    status: SlotStatus = "missing"
    evidence: list[str] = []
    probes: int = 0


class SectionState(BaseModel):
    status: Literal["pending", "active", "satisfied", "partial", "skipped"] = "pending"
    time_used_sec: float = 0
    probe_count: int = 0
    slots: dict[str, SlotState] = {}


class Turn(BaseModel):
    turn_id: str
    role: Literal["agent", "user"]
    text: str
    ts: datetime = Field(default_factory=now)
    section_id: str | None = None
    fallback: bool = False  # the LLM failed and the agent asked the candidate to repeat


class Flag(BaseModel):
    type: Literal["pii", "sensitive_personal", "injection"]
    subtype: str
    turn_id: str
    text: str


# ---------- Report ----------


class Evidence(BaseModel):
    turn_id: str
    quote: str
    at: str = ""  # mm:ss from interview start


class CriterionResult(BaseModel):
    criterion_id: str
    name: str
    rating: Literal["above_bar", "meets_bar", "below_bar", "not_assessed"]
    score: float | None = None  # 1-5
    rationale: str = ""
    evidence: list[Evidence] = []
    verified: bool = True  # False when the evaluator's quotes could not be found in the transcript


class Report(BaseModel):
    overall_score: float | None = None
    recommendation: Literal["advance", "hold", "reject"] | None = None  # None: the evaluator gave no suggestion
    recommendation_reason: str = ""
    summary: str = ""
    criteria: list[CriterionResult] = []
    strengths: list[str] = []
    concerns: list[str] = []
    resume_flags: list[str] = []
    candidate_feedback: str = ""
    model: str = ""  # which model and prompt produced this report, for audits
    prompt_version: str = ""
    created_at: datetime = Field(default_factory=now)


SessionState = Literal["READY", "INTERVIEWING", "WRAPUP", "EVALUATING", "EVAL_FAILED", "DONE"]


class Session(BaseModel):
    session_id: str = Field(default_factory=lambda: new_id("s"))
    plan_id: str
    candidate_id: str
    state: SessionState = "READY"
    created_at: datetime = Field(default_factory=now)
    started_at: datetime | None = None
    last_tick_at: datetime | None = None
    elapsed_sec: float = 0
    current_section_id: str | None = None
    sections: dict[str, SectionState] = {}
    turns: list[Turn] = []
    flags: list[Flag] = []
    usage: list[Usage] = []
    report: Report | None = None
    eval_error: str = ""  # why the last evaluation failed (state EVAL_FAILED)

    def next_turn_id(self, role: str) -> str:
        return f"{'u' if role == 'user' else 'a'}{len(self.turns) + 1}"

    def offset(self, turn: Turn) -> str:
        if not self.started_at:
            return ""
        sec = max(0, int((turn.ts - self.started_at).total_seconds()))
        return f"{sec // 60:02d}:{sec % 60:02d}"
