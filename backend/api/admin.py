"""Admin API: /api/admin/... Accounts, approval, and what the system is doing right now."""

from fastapi import APIRouter
from pydantic import BaseModel

from ..services import accounts, admin
from .deps import Admin

router = APIRouter(prefix="/api/admin")


class StatusIn(BaseModel):
    status: str


@router.get("/accounts")
async def list_accounts(me: Admin):
    return await accounts.list_accounts()


@router.post("/accounts/{recruiter_id}/status")
async def set_status(recruiter_id: str, body: StatusIn, me: Admin):
    await accounts.set_status(me, recruiter_id, body.status)
    return {"ok": True}


@router.get("/overview")
async def overview(me: Admin):
    return await admin.overview()
