"""Who is asking. Every recruiter route takes `Me` (signed in) or `Writer` (signed in and approved); admin routes
take `Admin`. Ownership of the data itself is checked in services, never here."""

from typing import Annotated

from fastapi import Depends, HTTPException, Request, Response

from .. import config
from ..services import accounts
from ..services.accounts import Account

COOKIE = "tryout_session"


async def current_account(request: Request) -> Account:
    token = request.cookies.get(COOKIE)
    account = await accounts.by_token(token) if token else None
    if account is None:
        raise HTTPException(401, "Sign in to continue")
    return account


_WAIT = {
    "pending": "Your account is waiting for approval. You can look around; creating roles opens once approved.",
    "demo": "This is the read-only demo. Create an account to run your own interviews.",
}


async def writer(account: Annotated[Account, Depends(current_account)]) -> Account:
    if not account.can_write:
        raise HTTPException(403, _WAIT.get(account.status, "This account cannot make changes"))
    return account


async def admin(account: Annotated[Account, Depends(current_account)]) -> Account:
    if not account.is_admin:
        raise HTTPException(404, "Not found")  # the admin area does not exist for anyone else
    return account


Me = Annotated[Account, Depends(current_account)]
Writer = Annotated[Account, Depends(writer)]
Admin = Annotated[Account, Depends(admin)]


def set_login(response: Response, request: Request, token: str) -> None:
    """HttpOnly: page scripts cannot read it. SameSite=Lax: other sites cannot send it with a POST, which is the
    CSRF guard. Secure whenever the request came over HTTPS (uvicorn trusts the host's proxy headers)."""
    response.set_cookie(
        COOKIE,
        token,
        max_age=config.SESSION_DAYS * 86400,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
        path="/",
    )


def clear_login(response: Response) -> None:
    response.delete_cookie(COOKIE, path="/")
