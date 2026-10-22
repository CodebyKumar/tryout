"""Uploaded documents (JDs, resumes) -> plain text. One reader for every upload."""

import html
import io
import re
import zipfile

from pypdf import PdfReader


def extract_text(filename: str, raw: bytes) -> str:
    """PDF, DOCX or UTF-8 text. Raises ValueError for anything else, so binary files never reach the LLM.
    CPU-bound: call it through asyncio.to_thread from request handlers."""
    name = filename.lower()
    try:
        if name.endswith(".pdf"):
            return "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(raw)).pages)
        if name.endswith(".docx"):
            xml = zipfile.ZipFile(io.BytesIO(raw)).read("word/document.xml").decode()
            return html.unescape(re.sub(r"<[^>]+>", "", xml.replace("</w:p>", "\n")))
        return raw.decode("utf-8")
    except Exception as e:  # pypdf and zipfile raise many types on corrupt files
        raise ValueError(f"Could not read {filename or 'the file'}") from e
