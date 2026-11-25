"""Recruiter API: /api/roles and /api/candidates. Reads need a signed-in account (Me); changes need an approved
one (Writer). Services return 404 for anything the account does not own."""

import asyncio
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from .. import config
from ..integrations import documents
from ..models import Criterion, Section
from ..services import candidates, evaluation, interviews, roles
from . import MAX_DOC_BYTES, read_upload, views
from .deps import Me, Writer

router = APIRouter(prefix="/api")


class RoleIn(BaseModel):
    title: str = Field(max_length=200)
    jd: str = Field(max_length=40000)
    notes: str = Field("", max_length=5000)
    company: str = Field("", max_length=200)
    time_budget_sec: int = Field(config.TIME_BUDGET_SEC, ge=180, le=3600)
    integrity: Literal["standard", "strict"] = "standard"


class RefineIn(BaseModel):
    instruction: str = Field(max_length=2000)


class RoleUpdate(BaseModel):
    title: str | None = Field(None, max_length=200)
    company: str | None = Field(None, max_length=200)
    notes: str | None = Field(None, max_length=5000)
    time_budget_sec: int | None = Field(None, ge=180, le=3600)
    integrity: Literal["standard", "strict"] | None = None
    sections: list[Section] | None = None
    criteria: list[Criterion] | None = None


class CandidateIn(BaseModel):
    name: str = Field(max_length=120)
    email: str = Field("", max_length=320)
    resume: str = Field("", max_length=40000)
    opens_at: datetime | None = None
    closes_at: datetime | None = None


class CandidateEdit(BaseModel):
    name: str = Field(max_length=120)
    email: str = Field("", max_length=320)
    opens_at: datetime | None = None
    closes_at: datetime | None = None


class DecisionIn(BaseModel):
    decision: Literal["advanced", "hold", "rejected"] | None


async def read_document(file: UploadFile) -> tuple[str, bytes]:
    """The upload's text, and its bytes for storage."""
    raw = await read_upload(file, MAX_DOC_BYTES)
    try:
        return await asyncio.to_thread(documents.extract_text, file.filename or "", raw), raw
    except ValueError:
        raise HTTPException(400, "Could not read that file. Upload a PDF, DOCX or text file, or paste the text.")


# ---------- Roles ----------


@router.get("/templates")
async def list_templates(me: Me):
    return roles.templates()


@router.post("/roles")
async def create_role(body: RoleIn, me: Writer):
    return views.role(await roles.create(me.id, **body.model_dump()), [])


@router.get("/roles")
async def list_roles(me: Me):
    return views.role_list(await roles.list_all(me.id))


@router.get("/roles/{role_id}")
async def get_role(role_id: str, me: Me):
    role = await roles.get(me.id, role_id)
    return views.role(role, await candidates.summaries(me.id, role_id=role_id))


@router.post("/roles/from-document")
async def role_from_document(
    me: Writer,
    file: UploadFile | None = File(None),
    text: str = Form(""),
    time_budget_sec: int = Form(0),
    title: str = Form(""),
):
    """Recruiter drops one document (JD, guidelines, rubric, notes); the AI builds the whole brief."""
    if file is not None:
        text, _ = await read_document(file)
    return views.role(await roles.from_document(me.id, text, title, time_budget_sec), [])


@router.post("/roles/{role_id}/refine")
async def refine_role(role_id: str, body: RefineIn, me: Writer):
    return views.role(await roles.refine(me.id, role_id, body.instruction), [])


@router.put("/roles/{role_id}")
async def update_role(role_id: str, body: RoleUpdate, me: Writer):
    changes = {k: getattr(body, k) for k in body.model_dump(exclude_none=True)}
    return views.role(await roles.update(me.id, role_id, changes), [])


@router.delete("/roles/{role_id}")
async def delete_role(role_id: str, me: Writer):
    await roles.delete_role(me.id, role_id)
    return {"deleted": role_id}


# ---------- Candidates ----------


@router.post("/roles/{role_id}/candidates")
async def add_candidate(role_id: str, body: CandidateIn, me: Writer):
    cand = await candidates.add(me.id, role_id, **body.model_dump())
    return views.summary(await candidates.summary(me.id, cand.candidate_id))


@router.get("/candidates/{candidate_id}")
async def candidate_report(candidate_id: str, me: Me):
    return views.report(*await candidates.report(me.id, candidate_id))


@router.get("/candidates/{candidate_id}/trace")
async def candidate_trace(candidate_id: str, me: Me):
    return await interviews.trace(me.id, candidate_id)


@router.put("/candidates/{candidate_id}")
async def edit_candidate(candidate_id: str, body: CandidateEdit, me: Writer):
    await candidates.edit(me.id, candidate_id, **body.model_dump())
    return views.summary(await candidates.summary(me.id, candidate_id))


@router.post("/candidates/{candidate_id}/decision")
async def decide(candidate_id: str, body: DecisionIn, me: Writer):
    await candidates.decide(me.id, candidate_id, body.decision)
    return views.summary(await candidates.summary(me.id, candidate_id))


@router.delete("/candidates/{candidate_id}")
async def delete_candidate(candidate_id: str, me: Writer):
    await candidates.delete_candidate(me.id, candidate_id)
    return {"deleted": candidate_id}


@router.post("/candidates/{candidate_id}/reset")
async def reset_candidate(candidate_id: str, me: Writer):
    await candidates.reset(me.id, candidate_id)
    return views.summary(await candidates.summary(me.id, candidate_id))


@router.post("/candidates/{candidate_id}/reevaluate")
async def reevaluate(candidate_id: str, me: Writer):
    await evaluation.rerun(me.id, candidate_id)
    return views.report(*await candidates.report(me.id, candidate_id))


@router.post("/candidates/{candidate_id}/prepare")
async def prepare(candidate_id: str, me: Writer):
    """Re-read the resume after a failed (or outdated) prep. Only before the interview starts."""
    await candidates.prepare(me.id, candidate_id)
    return views.summary(await candidates.summary(me.id, candidate_id))
