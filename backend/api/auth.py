"""Accounts API: /api/auth/..."""

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field

from ..services import accounts
from ..services.accounts import Account
from .deps import COOKIE, Me, clear_login, set_login

router = APIRouter(prefix="/api/auth")


class SignUpIn(BaseModel):
    name: str = Field(max_length=120)
    email: str = Field(max_length=320)
    password: str = Field(max_length=200)


class LogInIn(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=200)


def _me(a: Account) -> dict:
    return {"id": a.id, "email": a.email, "name": a.name, "status": a.status, "is_admin": a.is_admin}


@router.post("/signup")
async def sign_up(body: SignUpIn, request: Request, response: Response):
    account, token = await accounts.sign_up(body.name, body.email, body.password)
    set_login(response, request, token)
    return _me(account)


@router.post("/login")
async def log_in(body: LogInIn, request: Request, response: Response):
    account, token = await accounts.log_in(body.email, body.password)
    set_login(response, request, token)
    return _me(account)


@router.post("/demo")
async def demo(request: Request, response: Response):
    account, token = await accounts.demo_login()
    set_login(response, request, token)
    return _me(account)


@router.post("/logout")
async def log_out(request: Request, response: Response):
    if token := request.cookies.get(COOKIE):
        await accounts.log_out(token)
    clear_login(response)
    return {"ok": True}


@router.get("/me")
async def me(account: Me):
    return _me(account)
