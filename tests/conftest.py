"""Shared test fixtures: a fixed role brief, a scripted fake LLM, an app client and an interview plan."""

import asyncio
import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from backend import db, tables
from backend.agents.role_compiler import CompiledRole, apply_compiled
from backend.app import app
from backend.integrations.llm import FakeLLM, set_llm
from backend.models import InterviewPlan, Role

ROLE = {
    "company": "Acme Pay",
    "sections": [
        {
            "section_id": "t_intro",
            "name": "Intro",
            "intent": "Background",
            "opening_question": "Tell me about yourself.",
            "slots": [{"slot_id": "background", "desc": "Current role and experience"}],
            "time_budget_sec": 120,
            "priority": 1,
        },
        {
            "section_id": "t_project",
            "name": "Past work",
            "intent": "Ownership of a real system",
            "opening_question": "Tell me about a system you built.",
            "slots": [
                {"slot_id": "what", "desc": "What it was"},
                {"slot_id": "own_role", "desc": "What they personally built"},
                {"slot_id": "outcome", "desc": "Result or number"},
            ],
            "time_budget_sec": 300,
            "priority": 1,
        },
    ],
    "criteria": [
        {
            "criterion_id": "ownership",
            "name": "Ownership",
            "description": "Owns work end to end",
            "weight": 2,
            "above_bar": "Clear I-statements and decisions",
            "meets_bar": "Some ownership",
            "below_bar": "Only we",
        },
        {"criterion_id": "impact", "name": "Impact", "description": "Measurable results", "weight": 1},
    ],
}


def make_fake_llm():
    turns = iter(
        [
            {
                "ack": "Backend at a fintech, got it.",
                "probe_question": "",
                "bridge_question": "Cool. So what's the settlement service on your resume?",
                "slot_updates": [
                    {
                        "section_id": "t_intro",
                        "slot_id": "background",
                        "value": "3 yrs backend at fintech",
                        "status": "filled",
                        "evidence": ["u2"],
                    }
                ],
            },
            {
                "ack": "A settlement service.",
                "probe_question": "Which part did you build yourself?",
                "slot_updates": [
                    {"section_id": "t_project", "slot_id": "what", "value": "settlement service", "status": "filled"},
                    {"section_id": "t_project", "slot_id": "own_role", "value": "we built it", "status": "vague"},
                ],
                "gap": {"slot_id": "own_role", "type": "no_ownership"},
            },
            {
                "ack": "So the retry logic was yours.",
                "probe_question": "",
                "slot_updates": [
                    {
                        "section_id": "t_project",
                        "slot_id": "own_role",
                        "value": "wrote idempotent retry logic",
                        "status": "filled",
                        "evidence": ["u6"],
                    },
                    {
                        "section_id": "t_project",
                        "slot_id": "outcome",
                        "value": "failed payouts dropped 40%",
                        "status": "filled",
                        "evidence": ["u6"],
                    },
                ],
            },
            {"ack": "Thanks for sharing that.", "probe_question": ""},
        ]
    )
    return FakeLLM(
        {
            "role_compiler": lambda s, u: ROLE,
            "candidate_prep": lambda s, u: {
                "resume_highlights": ["Settlement service at Acme"],
                "claims_to_verify": ["Cut failures 40%"],
                "openers": {"t_project": "Your resume mentions a settlement service. What was it?"},
            },
            "turn_agent": lambda s, u: next(turns),
            "evaluator": lambda s, u: {
                "criteria": [
                    {
                        "criterion_id": "ownership",
                        "rating": "above_bar",
                        "score": 4.5,
                        "rationale": "Owned retries",
                        "evidence": [{"turn_id": "u6", "quote": "I wrote the idempotent retry logic myself"}],
                    },
                    {
                        "criterion_id": "impact",
                        "rating": "meets_bar",
                        "score": 3,
                        "evidence": [{"turn_id": "u6", "quote": "we doubled revenue"}],
                    },
                ],  # fabricated quote
                "summary": "Solid.",
                "strengths": ["Ownership"],
                "concerns": [],
                "recommendation": "advance",
                "recommendation_reason": "Strong ownership",
                "candidate_feedback": "You explained your retry design clearly.",
            },
        }
    )


@pytest.fixture
def fake_llm():
    """The scripted LLM, installed as the app's LLM. Tests can swap `fake_llm.handlers[agent]`."""
    llm = make_fake_llm()
    set_llm(llm)
    yield llm
    set_llm(None)


async def _empty_tables():
    async with db.transaction() as s:
        for table in reversed(tables.Base.metadata.sorted_tables):
            await s.execute(table.delete())


@pytest.fixture
def database(tmp_path):
    """A fresh SQLite database with the real tables, so tests run the same SQL code offline. TEST_DATABASE_URL runs
    them on Postgres instead; it must be an EMPTY, migrated test database: every table is emptied after each test."""
    if url := os.getenv("TEST_DATABASE_URL"):
        db.configure(url, pooled=False)
        yield
        asyncio.run(_empty_tables())
        return
    url = f"sqlite:///{tmp_path / 'test.db'}"
    tables.Base.metadata.create_all(create_engine(url))
    db.configure(url.replace("sqlite://", "sqlite+aiosqlite://"))
    yield


@pytest.fixture
def client(database, fake_llm):
    with TestClient(app) as c:
        yield c, fake_llm


@pytest.fixture
def role():
    return apply_compiled(
        Role(title="Backend Engineer", jd="y", time_budget_sec=600), CompiledRole.model_validate(ROLE)
    )


@pytest.fixture
def plan(role):
    return InterviewPlan(
        role_id=role.role_id,
        candidate_id="c",
        candidate_name="Riya",
        role_title=role.title,
        time_budget_sec=role.time_budget_sec,
        sections=role.sections,
    )
