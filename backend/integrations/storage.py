"""Original uploaded files in Supabase Storage (private bucket). Optional: the extracted text is the record."""

import logging
import re

import httpx

from .. import config

log = logging.getLogger("storage")


async def upload(path: str, data: bytes) -> str | None:
    """Stores the file and returns its path in the bucket, or None when storage is off or the upload fails (the
    request still succeeds: the text has already been read)."""
    if not (config.SUPABASE_URL and config.SUPABASE_SECRET_KEY):
        return None
    path = re.sub(r"[^\w./-]+", "_", path)  # storage keys: no spaces or odd characters from user file names
    url = f"{config.SUPABASE_URL}/storage/v1/object/{config.STORAGE_BUCKET}/{path}"
    headers = {"Authorization": f"Bearer {config.SUPABASE_SECRET_KEY}", "x-upsert": "true"}
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, content=data, headers=headers)
        resp.raise_for_status()
        return path
    except httpx.HTTPError as e:
        log.warning("could not store %s: %s", path, e)
        return None
