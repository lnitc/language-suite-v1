"""Feature 4: vocabulary practice (text mode).

Flow: the model writes the word list *with accepted translations* up front,
plain code checks each answer, and at the end the model gives a second
opinion on answers the code marked wrong (to catch valid synonyms).
"""

from __future__ import annotations

import uuid
from collections import OrderedDict
from dataclasses import dataclass, field

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..providers.base import ChatProvider, ProviderError
from ..providers.factory import get_chat_provider
from ..textutils import normalize, parse_json
from .speech import clean_language_code

router = APIRouter(prefix="/api/vocabulary", tags=["vocabulary"])

DEFAULT_SYSTEM_PROMPT = "You are a careful, encouraging language teacher."
MAX_MATERIAL_CHARS = 8000
MAX_SESSIONS = 100


# ---------- data ----------

@dataclass
class Item:
    word: str
    translations: list[str]
    answer: str | None = None
    status: str = "pending"  # pending | correct | accepted | wrong | skipped


@dataclass
class Session:
    source_language: str
    target_language: str
    system_prompt: str
    items: list[Item]
    position: int = 0
    reviewed: bool = False


_sessions: OrderedDict[str, Session] = OrderedDict()


class StartRequest(BaseModel):
    source_language: str = Field(min_length=1, max_length=60)
    target_language: str = Field(min_length=1, max_length=60)
    count: int = Field(default=10, ge=1, le=50)
    system_prompt: str = Field(default="", max_length=2000)
    session_prompt: str = Field(default="", max_length=2000)
    material: str = Field(default="", max_length=200_000)


class AnswerRequest(BaseModel):
    answer: str = Field(default="", max_length=300)
    skip: bool = False


# ---------- helpers ----------

def _get_session(session_id: str) -> Session:
    session = _sessions.get(session_id)
    if session is None:
        raise HTTPException(404, "Session not found. Please start a new one.")
    return session


def _progress(session: Session) -> dict:
    done = session.position >= len(session.items)
    return {
        "done": done,
        "index": session.position,
        "total": len(session.items),
        "word": None if done else session.items[session.position].word,
    }


async def _generate_items(req: StartRequest, chat: ChatProvider) -> tuple[list[Item], dict]:
    material = req.material.strip()[:MAX_MATERIAL_CHARS]
    parts = [
        f"Create a vocabulary exercise with exactly {req.count} items.",
        f"The learner is shown a word or short phrase in {req.source_language} "
        f"and must translate it into {req.target_language}.",
    ]
    if req.session_prompt.strip():
        parts.append(f"Learner's instructions for this session: {req.session_prompt.strip()}")
    if material:
        parts.append(
            "Choose the words only from the learner's material below. "
            f"If an entry is not in {req.source_language}, use its "
            f"{req.source_language} equivalent as the word.\n"
            f"--- material ---\n{material}\n--- end material ---"
        )
    parts.append(
        'Reply with JSON only, in this shape: {"source_language_code": "...", '
        '"target_language_code": "...", "items": [{"word": "...", '
        '"translations": ["...", "..."]}]}. The codes are BCP-47 codes such as '
        '"en-US" or "ja-JP". '
        f'"word" is in {req.source_language}. "translations" lists every common '
        f"correct {req.target_language} translation (1 to 5), most usual first. "
        "No duplicates among the words."
    )
    messages = [
        {"role": "system", "content": req.system_prompt.strip() or DEFAULT_SYSTEM_PROMPT},
        {"role": "user", "content": "\n\n".join(parts)},
    ]
    raw = await chat.chat(messages, json_mode=True, temperature=0.8)

    try:
        data = parse_json(raw)
    except ValueError:
        data = {}
    entries = data.get("items", [])
    codes = {
        "source_language_code": clean_language_code(data.get("source_language_code")),
        "target_language_code": clean_language_code(data.get("target_language_code")),
    }

    items: list[Item] = []
    seen: set[str] = set()
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict):
            continue
        word = str(entry.get("word", "")).strip()
        translations = entry.get("translations", [])
        if isinstance(translations, str):
            translations = [translations]
        translations = [str(t).strip() for t in translations if str(t).strip()]
        key = normalize(word)
        if not word or not translations or key in seen:
            continue
        seen.add(key)
        items.append(Item(word=word, translations=translations))
        if len(items) == req.count:
            break

    if not items:
        raise ProviderError(
            "The model did not return a usable word list. Please try again; "
            "if it keeps happening, try a different model."
        )
    return items, codes


async def _second_opinion(session: Session, chat: ChatProvider) -> None:
    """Ask the model whether 'wrong' answers are in fact valid translations."""
    doubtful = [
        (i, item) for i, item in enumerate(session.items) if item.status == "wrong"
    ]
    if not doubtful:
        return
    lines = [
        f'{i}: word "{item.word}" | expected {item.translations} | learner wrote "{item.answer}"'
        for i, item in doubtful
    ]
    messages = [
        {"role": "system", "content": session.system_prompt or DEFAULT_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"A learner translated words from {session.source_language} into "
                f"{session.target_language}. For each line, decide whether the "
                "learner's answer is a correct translation of the word (a valid "
                "synonym or a trivial typo counts as correct; a different meaning "
                "does not). Be strict when unsure.\n\n"
                + "\n".join(lines)
                + '\n\nReply with JSON only: {"verdicts": [{"index": 0, "correct": true}]}'
            ),
        },
    ]
    try:
        verdicts = parse_json(await chat.chat(messages, json_mode=True, temperature=0.0))
        allowed = {i for i, _ in doubtful}
        for verdict in verdicts.get("verdicts", []):
            index = verdict.get("index")
            if index in allowed and verdict.get("correct") is True:
                session.items[index].status = "accepted"
    except (ProviderError, ValueError, AttributeError, TypeError):
        # The second opinion is a bonus; without it the exact-match result stands.
        pass


# ---------- routes ----------

@router.post("/sessions")
async def start_session(
    req: StartRequest, chat: ChatProvider = Depends(get_chat_provider)
) -> dict:
    items, codes = await _generate_items(req, chat)
    session_id = uuid.uuid4().hex
    _sessions[session_id] = Session(
        source_language=req.source_language,
        target_language=req.target_language,
        system_prompt=req.system_prompt.strip(),
        items=items,
    )
    while len(_sessions) > MAX_SESSIONS:
        _sessions.popitem(last=False)
    return {"session_id": session_id, **codes, **_progress(_sessions[session_id])}


@router.post("/sessions/{session_id}/answers")
async def submit_answer(session_id: str, req: AnswerRequest) -> dict:
    session = _get_session(session_id)
    if session.position >= len(session.items):
        raise HTTPException(409, "This session is already finished.")
    item = session.items[session.position]
    answer = req.answer.strip()
    if req.skip or not answer:
        item.status = "skipped"
    else:
        item.answer = answer
        accepted = {normalize(t) for t in item.translations}
        item.status = "correct" if normalize(answer) in accepted else "wrong"
    session.position += 1
    return _progress(session)


@router.get("/sessions/{session_id}/result")
async def get_result(
    session_id: str, chat: ChatProvider = Depends(get_chat_provider)
) -> dict:
    session = _get_session(session_id)
    if session.position < len(session.items):
        raise HTTPException(409, "This session is not finished yet.")
    if not session.reviewed:
        await _second_opinion(session, chat)
        session.reviewed = True
    score = sum(item.status in ("correct", "accepted") for item in session.items)
    return {
        "score": score,
        "total": len(session.items),
        "source_language": session.source_language,
        "target_language": session.target_language,
        "items": [
            {
                "word": item.word,
                "your_answer": item.answer,
                "correct_translations": item.translations,
                "status": item.status,
            }
            for item in session.items
        ],
    }
