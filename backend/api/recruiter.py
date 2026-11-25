"""Recruiter API: /api/roles and /api/candidates."""

import asyncio

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from .. import config
from ..integrations import documents
from ..models import Criterion, Section
from ..services import candidates, evaluation, roles
from . import MAX_DOC_BYTES, read_upload, views

router = APIRouter(prefix="/api")


class RoleIn(BaseModel):
    title: str
    jd: str
    notes: str = ""
    company: str = ""
    time_budget_sec: int = config.TIME_BUDGET_SEC


class RefineIn(BaseModel):
    instruction: str


class RoleUpdate(BaseModel):
    title: str | None = None
    company: str | None = None
    notes: str | None = None
    time_budget_sec: int | None = None
    sections: list[Section] | None = None
    criteria: list[Criterion] | None = None


class CandidateIn(BaseModel):
    name: str
    email: str = ""
    resume: str = ""


class DecisionIn(BaseModel):
    status: str


async def read_document(file: UploadFile) -> tuple[str, bytes]:
    """The upload's text, and its bytes for storage."""
    raw = await read_upload(file, MAX_DOC_BYTES)
    try:
        return await asyncio.to_thread(documents.extract_text, file.filename or "", raw), raw
    except ValueError:
        raise HTTPException(400, "Could not read that file. Upload a PDF, DOCX or text file, or paste the text.")


@router.get("/templates")
async def list_templates():
    return roles.templates()


@router.post("/roles")
async def create_role(body: RoleIn):
    return (await roles.create(**body.model_dump())).model_dump()


@router.get("/roles")
async def list_roles():
    return views.role_list(await roles.list_all())


@router.get("/roles/{role_id}")
async def get_role(role_id: str):
    role, cands = await asyncio.gather(roles.get(role_id), candidates.summaries(role_id=role_id))  # two connections
    return views.role(role, cands)


@router.post("/roles/from-document")
async def role_from_document(
    file: UploadFile | None = File(None), text: str = Form(""), time_budget_sec: int = Form(0), title: str = Form("")
):
    """Recruiter drops one document (JD, guidelines, rubric, notes); the AI builds the whole brief."""
    if file is not None:
        text, _ = await read_document(file)
    return (await roles.from_document(text, title, time_budget_sec)).model_dump()


@router.post("/roles/{role_id}/refine")
async def refine_role(role_id: str, body: RefineIn):
    return (await roles.refine(role_id, body.instruction)).model_dump()


@router.put("/roles/{role_id}")
async def update_role(role_id: str, body: RoleUpdate):
    changes = {k: getattr(body, k) for k in body.model_dump(exclude_none=True)}
    return (await roles.update(role_id, changes)).model_dump()


@router.post("/roles/{role_id}/candidates")
async def add_candidate(role_id: str, body: CandidateIn):
    cand = await candidates.add(role_id, **body.model_dump())
    return views.summary(await candidates.summary(cand.candidate_id))


@router.get("/candidates/{candidate_id}")
async def candidate_report(candidate_id: str):
    return views.report(*await candidates.report(candidate_id))


@router.post("/candidates/{candidate_id}/decision")
async def decide(candidate_id: str, body: DecisionIn):
    await candidates.decide(candidate_id, body.status)
    return views.summary(await candidates.summary(candidate_id))


@router.delete("/candidates/{candidate_id}")
async def delete_candidate(candidate_id: str):
    await candidates.delete_candidate(candidate_id)
    return {"deleted": candidate_id}


@router.post("/candidates/{candidate_id}/reset")
async def reset_candidate(candidate_id: str):
    await candidates.reset(candidate_id)
    return views.summary(await candidates.summary(candidate_id))


@router.post("/candidates/{candidate_id}/reevaluate")
async def reevaluate(candidate_id: str):
    await evaluation.rerun(candidate_id)
    return views.report(*await candidates.report(candidate_id))


@router.post("/candidates/{candidate_id}/prepare")
async def prepare(candidate_id: str):
    """Re-read the resume after a failed (or outdated) prep. Only before the interview starts."""
    await candidates.prepare(candidate_id)
    return views.summary(await candidates.summary(candidate_id))
