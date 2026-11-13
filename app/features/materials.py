"""Reads the text out of uploaded learning material (PDF and Word files).

Plain text files and images are handled in the browser; this endpoint is
for the formats that need unpacking. Files are read in memory and never
saved to disk.
"""

from __future__ import annotations

import asyncio
import io
import re
import zipfile
from xml.etree import ElementTree

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/api/materials", tags=["materials"])

MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_XML_BYTES = 30 * 1024 * 1024
MAX_PDF_PAGES = 200
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


class UnreadableFile(Exception):
    """The message is safe to show to the user."""


def extract_pdf(data: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise UnreadableFile(
            "PDF support is not installed. In your project folder run: "
            "pip install -r requirements.txt"
        ) from exc
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted and not reader.decrypt(""):
            raise UnreadableFile("This PDF is password-protected. Remove the password and try again.")
        pages = [page.extract_text() or "" for page in reader.pages[:MAX_PDF_PAGES]]
    except UnreadableFile:
        raise
    except Exception as exc:
        raise UnreadableFile("This PDF could not be read. It may be damaged.") from exc
    text = "\n\n".join(page.strip() for page in pages if page.strip())
    if not text:
        raise UnreadableFile(
            "This PDF contains no selectable text (it is probably a scan). "
            "Upload it as an image instead, or use a text-based PDF."
        )
    return text


def extract_docx(data: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            info = archive.getinfo("word/document.xml")
            if info.file_size > MAX_XML_BYTES:
                raise UnreadableFile("This Word file is too large to read.")
            xml = archive.read(info)
    except UnreadableFile:
        raise
    except (zipfile.BadZipFile, KeyError) as exc:
        raise UnreadableFile("This does not look like a valid .docx file.") from exc
    if b"<!DOCTYPE" in xml[:4096] or b"<!ENTITY" in xml[:4096]:
        raise UnreadableFile("This Word file has an unexpected structure and was not read.")
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError as exc:
        raise UnreadableFile("This Word file could not be read. It may be damaged.") from exc

    # Every paragraph, in order, including those inside tables.
    paragraphs = []
    for paragraph in root.iter(f"{_W}p"):
        pieces = []
        for node in paragraph.iter():
            if node.tag == f"{_W}t":
                pieces.append(node.text or "")
            elif node.tag == f"{_W}tab":
                pieces.append("\t")
            elif node.tag in (f"{_W}br", f"{_W}cr"):
                pieces.append("\n")
        line = "".join(pieces).strip()
        if line:
            paragraphs.append(line)
    if not paragraphs:
        raise UnreadableFile("No text was found in this Word file.")
    return "\n".join(paragraphs)


def extract_text(data: bytes, filename: str) -> str:
    name = filename.lower()
    if data[:5] == b"%PDF-" or name.endswith(".pdf"):
        text = extract_pdf(data)
    elif name.endswith(".docx") or (data[:2] == b"PK" and not name.endswith(".doc")):
        text = extract_docx(data)
    elif name.endswith(".doc") or data[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        raise UnreadableFile(
            "Old-style .doc files cannot be read. Open the file in Word, choose "
            "Save As, and save it as .docx or PDF."
        )
    else:
        raise UnreadableFile("This file type is not supported. Use PDF, .docx, a text file or an image.")
    text = text.replace("\x00", "")
    return re.sub(r"\n{3,}", "\n\n", text).strip()


@router.post("/extract")
async def extract(request: Request, filename: str = "") -> dict:
    """Body: the raw file. Returns its text."""
    data = await request.body()
    if not data:
        raise HTTPException(400, "The uploaded file is empty.")
    if len(data) > MAX_FILE_BYTES:
        raise HTTPException(413, "The file is larger than 20 MB. Please use a smaller one.")
    try:
        text = await asyncio.to_thread(extract_text, data, filename[:200])
    except UnreadableFile as error:
        raise HTTPException(422, str(error)) from error
    return {"text": text, "characters": len(text)}
