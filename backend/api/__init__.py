"""HTTP only: parse the request, call one service function, shape the response with views."""

from fastapi import HTTPException, UploadFile

from .. import config

MAX_DOC_BYTES = config.MAX_DOC_MB * 1024 * 1024
MAX_AUDIO_BYTES = config.MAX_AUDIO_MB * 1024 * 1024


async def read_upload(file: UploadFile, limit: int) -> bytes:
    # shortcut: the server has already received the whole body; set a body limit at the proxy when deploying.
    raw = await file.read(limit + 1)
    if len(raw) > limit:
        raise HTTPException(413, f"That file is too large (limit {limit // 1024 // 1024} MB).")
    return raw
