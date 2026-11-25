"""Builds the app. Run: ./run.sh dev

Pages: / (home), /login, /signup, /app (recruiter), /admin, /i/{token} (candidate's interview room).
Layers (each only calls the one below): api/ (HTTP) -> services/ (use cases, the only database access) ->
agents/ + engine/ (no I/O) -> integrations/ (Groq, Whisper, Deepgram, documents, storage).
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import config
from .api import admin, auth, candidate, recruiter
from .integrations.llm import LLMError
from .integrations.stt import VoiceError
from .services import Busy, Conflict, Forbidden, Invalid, NotFound, jobs

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    workers = await jobs.start()  # prep and evaluation jobs, and the idle interview sweep
    yield
    for w in workers:
        w.cancel()
    await asyncio.gather(*workers, return_exceptions=True)


app = FastAPI(title="TryOut", lifespan=lifespan, docs_url=None, redoc_url=None)
for router in (auth.router, recruiter.router, candidate.router, admin.router):
    app.include_router(router)


@app.middleware("http")
async def _headers(request, call_next):
    """Pages and scripts change with each release: browsers revalidate (cheap 304s) instead of running an old copy.
    The interview room may use the microphone and camera; nothing else on the site may."""
    response = await call_next(request)
    if not request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-cache"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"  # the candidate's private link never leaks to other sites
    response.headers["X-Frame-Options"] = "DENY"
    return response


def _error(status: int):
    async def handler(request, exc):
        return JSONResponse(status_code=status, content={"detail": str(exc)})

    return handler


for exc, status in ((NotFound, 404), (Invalid, 400), (Forbidden, 403), (Conflict, 409), (Busy, 503)):
    app.add_exception_handler(exc, _error(status))
app.add_exception_handler(VoiceError, _error(503))


@app.exception_handler(LLMError)
async def _llm_down(request, exc: LLMError):
    return JSONResponse(
        status_code=503, content={"detail": f"The AI service is busy, please retry in a moment ({exc})"}
    )


@app.exception_handler(Exception)
async def _unexpected(request, exc: Exception):
    log.exception("unhandled error on %s", request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Something went wrong on the server. Please try again."})


@app.get("/api/health")
async def health():
    return {"ok": True, "llm": bool(config.GROQ_API_KEY), "voice": bool(config.DEEPGRAM_API_KEY)}


def _page(name: str):
    async def page():
        return FileResponse(config.FRONTEND_DIR / name)

    return page


for path, name in (
    ("/", "index.html"),
    ("/login", "login.html"),
    ("/signup", "login.html"),  # one page, two forms
    ("/app", "app.html"),
    ("/admin", "admin.html"),
    ("/i/{token}", "interview.html"),
):
    app.add_api_route(path, _page(name), methods=["GET"], include_in_schema=False)

app.mount("/static", StaticFiles(directory=config.FRONTEND_DIR), name="static")
