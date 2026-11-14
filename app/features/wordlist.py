"""Feature 6: vocabulary list creator.

Builds a four-column word list (word, pronunciation, translation, example
and notes) either from a request ("100 business words") or from the
learner's own messy notes, which it tidies up and completes.

A small local model cannot reliably write 100 full entries in one answer,
so the work is cut into batches. The browser asks for one batch at a time,
which also gives a progress bar and lets a failed batch be repeated.
"""

from __future__ import annotations

import asyncio
import io
import math
import re
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field, StringConstraints

from ..providers.base import ChatProvider, ProviderError
from ..providers.factory import get_chat_provider
from ..textutils import normalize, parse_json
from .dictation import DIFFICULTIES

router = APIRouter(prefix="/api/wordlist", tags=["wordlist"])

MAX_ENTRIES = 100
BATCH_SIZE = 10
MAX_LINE_CHARS = 300
MAX_SESSIONS = 20
FIELDS = ("word", "pronunciation", "translation", "example", "example_translation", "remarks")


@dataclass
class Session:
    source_language: str
    target_language: str
    difficulty: str
    prompt: str
    lines: list[str]  # the words to include, or the learner's raw note lines
    from_file: bool
    include_examples: bool = True
    batches: dict[int, list[dict]] = field(default_factory=dict)


_sessions: OrderedDict[str, Session] = OrderedDict()


class StartRequest(BaseModel):
    source_language: str = Field(min_length=1, max_length=60)  # the language being learned
    target_language: str = Field(min_length=1, max_length=60)  # language of the explanations
    difficulty: Literal[
        "beginner", "elementary", "intermediate", "upper_intermediate", "advanced"
    ] = "intermediate"
    count: int = Field(default=20, ge=1, le=MAX_ENTRIES)
    prompt: str = Field(default="", max_length=2000)
    material: str = Field(default="", max_length=200_000)  # the learner's own list, if any
    # False: only word, pronunciation and translation are made. Quicker, and a
    # lighter list to reuse as practice material.
    include_examples: bool = True


def _get_session(session_id: str) -> Session:
    session = _sessions.get(session_id)
    if session is None:
        raise HTTPException(404, "This list is no longer available. Please start again.")
    return session


def note_lines(material: str) -> list[str]:
    """The learner's notes as clean lines: one entry per line, no blanks or repeats."""
    lines, seen = [], set()
    for raw in material.splitlines():
        line = " ".join(raw.split())[:MAX_LINE_CHARS]  # also folds full-width spaces
        if not any(ch.isalpha() for ch in line) or line in seen:
            continue
        seen.add(line)
        lines.append(line)
    return lines


async def _propose_words(req: StartRequest, chat: ChatProvider) -> list[str]:
    """Create mode, step 1: only the words. The details come batch by batch."""
    words: list[str] = []
    seen: set[str] = set()
    for _ in range(2):  # one top-up round if the model returns too few
        missing = req.count - len(words)
        if missing <= 0:
            break
        parts = [
            f"List {missing} words or collocations in {req.source_language} for a "
            f"learner's vocabulary list. Level: {DIFFICULTIES[req.difficulty].split(':')[0]}.",
        ]
        if req.prompt.strip():
            parts.append(f"Learner's request: {req.prompt.strip()}")
        if words:
            parts.append("Do not repeat any of these: " + ", ".join(words))
        parts.append(
            'Reply with JSON only: {"words": ["...", "..."]}. Each item is one word or '
            f"collocation in {req.source_language}, in dictionary form, with nothing else."
        )
        messages = [
            {"role": "system", "content": f"You are an expert teacher of {req.source_language}."},
            {"role": "user", "content": "\n\n".join(parts)},
        ]
        try:
            entries = parse_json(await chat.chat(messages, json_mode=True, temperature=0.8)).get("words", [])
        except ValueError:
            entries = []
        for entry in entries if isinstance(entries, list) else []:
            word = " ".join(str(entry).split())[:MAX_LINE_CHARS]
            key = normalize(word)
            if word and key and key not in seen and len(words) < req.count:
                seen.add(key)
                words.append(word)
    if not words:
        raise ProviderError(
            "The model did not return a usable word list. Please try again; "
            "if it keeps happening, try a different model."
        )
    return words


@router.post("/sessions")
async def start_session(
    req: StartRequest, chat: ChatProvider = Depends(get_chat_provider)
) -> dict:
    provided = 0
    if req.material.strip():
        lines = note_lines(req.material)
        provided = len(lines)
        if not lines:
            raise HTTPException(422, "No words were found in the uploaded file.")
        lines = lines[:MAX_ENTRIES]
    else:
        lines = await _propose_words(req, chat)

    session_id = uuid.uuid4().hex
    _sessions[session_id] = Session(
        source_language=req.source_language.strip(),
        target_language=req.target_language.strip(),
        difficulty=req.difficulty,
        prompt=req.prompt.strip(),
        lines=lines,
        from_file=provided > 0,
        include_examples=req.include_examples,
    )
    while len(_sessions) > MAX_SESSIONS:
        _sessions.popitem(last=False)
    return {
        "session_id": session_id,
        "total": len(lines),
        "batch_size": BATCH_SIZE,
        "batch_count": math.ceil(len(lines) / BATCH_SIZE),
        "from_file": provided > 0,
        "include_examples": req.include_examples,
        "provided": provided,  # entries found in the file, before the limit
        "limit": MAX_ENTRIES,
    }


def _batch_prompt(session: Session, chunk: list[str]) -> str:
    source, target = session.source_language, session.target_language
    parts = [
        f"Prepare vocabulary list entries for a learner of {source}. Explanations are "
        f"written in {target}. Learner level: {DIFFICULTIES[session.difficulty].split(':')[0]}."
    ]
    if session.prompt:
        parts.append(f"Learner's request: {session.prompt}")
    if session.from_file:
        parts.append(
            "The numbered lines below come from the learner's own notes, one entry per "
            "line. They are messy: the order of the parts varies, there are stray "
            f"brackets and symbols, readings are sometimes missing, and meanings are "
            f"sometimes written in {source} instead of {target}. Turn each line into "
            "one clean, complete entry. Keep what the learner wrote where it is correct "
            "(their meaning, their notes), correct what is wrong, and fill in what is missing."
        )
    else:
        parts.append("The numbered lines below are the words to include, one per line.")
    parts.append(
        "Each entry has these fields:\n"
        f'- "word": the word or collocation in {source}, in its standard spelling, '
        "with no brackets, readings or notes.\n"
        '- "pronunciation": how the whole word or phrase is read, in the notation '
        f"learners of {source} normally use: hiragana for Japanese, pinyin with tone "
        "marks for Chinese, romanization for other non-Latin scripts, IPA for "
        "languages written in the Latin alphabet. Never empty.\n"
        f'- "translation": the meaning in {target}, short; separate several senses with commas.'
        + (
            f'\n- "example": one natural sentence in {source} that uses the word, suited to the level.\n'
            f'- "example_translation": that sentence in {target}.\n'
            f'- "remarks": in {target}, and only when useful: register (formal, slang, '
            "jargon), nuance, a common mistake, a synonym, or a note the learner wrote. "
            'Otherwise "".'
            if session.include_examples
            else "\nGive only these three fields: no example sentences and no remarks."
        )
    )
    extra = (
        ', "example": "...", "example_translation": "...", "remarks": "..."'
        if session.include_examples
        else ""
    )
    parts.append(
        'Reply with JSON only: {"entries": [{"n": 1, "word": "...", "pronunciation": "...", '
        f'"translation": "..."{extra}}}]}}. '
        f"Give exactly one entry for each of the {len(chunk)} lines, with the same number."
    )
    parts.append("Lines:\n" + "\n".join(f"{n}. {line}" for n, line in enumerate(chunk, start=1)))
    return "\n\n".join(parts)


def _usable(entry: dict | None) -> bool:
    return bool(entry and str(entry.get("word") or "").strip() and str(entry.get("translation") or "").strip())


async def _ask(session: Session, chunk: list[str], chat: ChatProvider) -> dict[int, dict]:
    """One model call for a few lines. Returns the entries by line number
    (matched by number, so a skipped or reordered entry cannot shift the rest)."""
    messages = [
        {
            "role": "system",
            "content": (
                f"You are an expert {session.source_language} teacher and dictionary "
                "editor who prepares accurate vocabulary lists."
            ),
        },
        {"role": "user", "content": _batch_prompt(session, chunk)},
    ]
    raw = await chat.chat(messages, json_mode=True, temperature=0.2)
    try:
        entries = parse_json(raw).get("entries", [])
    except ValueError:
        return {}
    by_number: dict[int, dict] = {}
    for position, entry in enumerate(entries if isinstance(entries, list) else [], start=1):
        if not isinstance(entry, dict):
            continue
        try:
            number = int(entry.get("n", position))
        except (TypeError, ValueError):
            number = position
        by_number.setdefault(number, entry)
    return by_number


@router.post("/sessions/{session_id}/batches/{index}")
async def make_batch(
    session_id: str, index: int, chat: ChatProvider = Depends(get_chat_provider)
) -> dict:
    session = _get_session(session_id)
    chunk = session.lines[index * BATCH_SIZE : (index + 1) * BATCH_SIZE] if index >= 0 else []
    if not chunk:
        raise HTTPException(404, "No such part of the list.")
    if index in session.batches:
        return {"index": index, "rows": session.batches[index]}

    by_number = await _ask(session, chunk, chat)
    if not by_number:
        raise ProviderError(
            "The model did not return usable entries for this part of the list. "
            "Press Continue to try that part again."
        )
    # Small models sometimes skip a line. Ask once more, for the skipped lines only.
    skipped = [n for n in range(1, len(chunk) + 1) if not _usable(by_number.get(n))]
    if skipped:
        try:
            again = await _ask(session, [chunk[n - 1] for n in skipped], chat)
        except ProviderError:
            again = {}
        for position, number in enumerate(skipped, start=1):
            if _usable(again.get(position)):
                by_number[number] = again[position]

    rows = []
    for number, line in enumerate(chunk, start=1):
        entry = by_number.get(number, {})
        row = {name: " ".join(str(entry.get(name) or "").split()) for name in FIELDS}
        if not session.include_examples:  # not asked for: drop anything the model added anyway
            row.update(example="", example_translation="", remarks="")
        # An entry the model skipped keeps the original line, so nothing is lost.
        row["complete"] = bool(row["word"] and row["translation"])
        if not row["word"]:
            row["word"] = line
        row["source_line"] = line
        rows.append(row)
    session.batches[index] = rows
    return {"index": index, "rows": rows}


# ---------- Word (.docx) export ----------
# The other formats (CSV, text, JSON, PDF) are made in the browser. A Word
# file is a zipped package, so it is built here from the rows the browser sends.

DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")  # not allowed inside a Word file
Cell = Annotated[str, StringConstraints(max_length=3000)]


class ExportRequest(BaseModel):
    title: str = Field(default="Vocabulary list", max_length=200)
    subtitle: str = Field(default="", max_length=300)
    header: list[Cell] = Field(min_length=1, max_length=8)
    rows: list[list[Cell]] = Field(min_length=1, max_length=MAX_ENTRIES * 2)


def build_docx(req: ExportRequest) -> bytes:
    try:
        from docx import Document
        from docx.enum.section import WD_ORIENT
        from docx.shared import Mm, Pt
    except ImportError as exc:
        raise ProviderError(
            "Word export is not installed. In your project folder run: "
            "pip install -r requirements.txt"
        ) from exc

    def clean(text: str) -> str:
        return _CONTROL_CHARS.sub("", text)

    document = Document()
    section = document.sections[0]  # A4, landscape: four columns need the width
    section.orientation = WD_ORIENT.LANDSCAPE
    section.page_width, section.page_height = Mm(297), Mm(210)
    for side in ("left_margin", "right_margin", "top_margin", "bottom_margin"):
        setattr(section, side, Mm(15))

    document.add_heading(clean(req.title), level=1)
    if req.subtitle:
        document.add_paragraph(clean(req.subtitle))

    columns = len(req.header)
    table = document.add_table(rows=1, cols=columns)
    table.style = "Table Grid"
    for cell, text in zip(table.rows[0].cells, req.header):
        cell.text = ""
        run = cell.paragraphs[0].add_run(clean(text))
        run.bold = True
    for row in req.rows:
        cells = table.add_row().cells
        for cell, text in zip(cells, (row + [""] * columns)[:columns]):
            cell.text = clean(text)
    # Narrow number column, wide example column (the usable width is 267 mm).
    widths = {5: [Mm(12), Mm(50), Mm(45), Mm(60), Mm(100)], 4: [Mm(12), Mm(80), Mm(75), Mm(100)]}.get(columns)
    if widths:
        table.autofit = False
        for column, width in zip(table.columns, widths):
            column.width = width  # Word reads the cell widths, other apps the column widths
    for row in table.rows:
        for position, cell in enumerate(row.cells):
            if widths:
                cell.width = widths[position]
            for paragraph in cell.paragraphs:
                for run in paragraph.runs:
                    run.font.size = Pt(10)

    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


@router.post("/export/docx")
async def export_docx(req: ExportRequest) -> Response:
    data = await asyncio.to_thread(build_docx, req)
    return Response(content=data, media_type=DOCX_TYPE, headers={"Cache-Control": "no-store"})
