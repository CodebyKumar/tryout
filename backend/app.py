"""Builds the app. Recruiter UI: / . Candidate UI: /i/{token} . Run: ./run.sh dev

Layers (each only calls the one below): api/ (HTTP) -> services/ (use cases, storage) -> agents/ + engine/ ->
integrations/ (Groq, Whisper, Piper, documents).
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import config
from .api import candidate, recruiter
from .integrations import tts
from .integrations.llm import LLMError
from .integrations.stt import VoiceError
from .services import Invalid, NotFound

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await asyncio.to_thread(tts.warm_up)
    yield


app = FastAPI(title="TryOut", lifespan=lifespan)
app.include_router(recruiter.router)
app.include_router(candidate.router)


@app.middleware("http")
async def _no_stale_ui(request, call_next):
    """Pages and scripts change often; make browsers revalidate so nobody runs an old copy of the UI."""
    response = await call_next(request)
    path = request.url.path
    if path.startswith("/static/") or path == "/" or path.startswith("/i/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


@app.exception_handler(NotFound)
async def _not_found(request, exc: NotFound):
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(Invalid)
async def _invalid(request, exc: Invalid):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(LLMError)
async def _llm_down(request, exc: LLMError):
    return JSONResponse(status_code=503, content={"detail": f"AI service is busy, please retry in a moment ({exc})"})


@app.exception_handler(VoiceError)
async def _voice_down(request, exc: VoiceError):
    return JSONResponse(status_code=503, content={"detail": str(exc)})


@app.exception_handler(Exception)
async def _unexpected(request, exc: Exception):
    log.exception("unhandled error on %s", request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Something went wrong on the server. Please try again; if it keeps failing, check ./run.sh logs."
        },
    )


@app.get("/api/health")
async def health():
    return {"ok": True, "llm_key": bool(config.GROQ_API_KEY), "models": config.MODELS}


@app.get("/")
async def recruiter_page():
    return FileResponse(config.FRONTEND_DIR / "recruiter.html")


@app.get("/i/{token}")
async def candidate_page(token: str):
    return FileResponse(config.FRONTEND_DIR / "interview.html")


app.mount("/static", StaticFiles(directory=config.FRONTEND_DIR), name="static")
