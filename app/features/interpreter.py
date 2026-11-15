"""Feature 3: interpreter simulation (consecutive interpreting).

Two modes:
  - one speaker: the model writes a speech in the source language; it is
    spoken a few sentences at a time and the learner interprets each part
    into the target language;
  - two speakers: the model writes a dialogue between two people who do
    not share a language. Speaker A speaks one language, speaker B the
    other, and the learner interprets every turn into the other language,
    as an interpreter does in a real meeting.

The learner's spoken interpretations are turned into text by the ear. At
the end the model gives an ideal version and a comment for every part.
"""

from __future__ import annotations

import unicodedata
import uuid
from collections import Counter, OrderedDict
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, StringConstraints

from ..providers.base import ChatProvider, ProviderError
from ..providers.factory import get_chat_provider
from ..textutils import normalize, parse_json
from .dictation import DIFFICULTIES
from .speech import clean_language_code

router = APIRouter(prefix="/api/interpreter", tags=["interpreter"])

DEFAULT_SYSTEM_PROMPT = "You are an experienced interpreter trainer."
MAX_SESSIONS = 50
SPOKEN_RULES = (
    "Everything will be read aloud: no lists, no abbreviations, no symbols, "
    "and spell numbers out in words."
)


@dataclass
class Part:
    """One stretch of speech that the learner interprets."""

    text: str
    from_language: str
    to_language: str
    speak_code: str  # language code of the speech (for the voice)
    answer_code: str  # language code of the interpretation (for the microphone)
    speaker: str = ""  # "A" or "B" in a dialogue
    role: str = ""  # who that speaker is, e.g. "hotel guest"

    def public(self) -> dict:
        return {
            "text": self.text,  # the browser speaks it; it is not shown on screen
            "from_language": self.from_language,
            "to_language": self.to_language,
            "speak_code": self.speak_code,
            "answer_code": self.answer_code,
            "speaker": self.speaker,
            "role": self.role,
        }


@dataclass
class Session:
    mode: str  # "speech" or "dialogue"
    source_language: str  # speech: what is heard; dialogue: speaker A's language
    target_language: str  # speech: interpreted into; dialogue: speaker B's language
    system_prompt: str
    parts: list[Part]
    setting: str = ""
    roles: dict[str, str] = field(default_factory=dict)
    result: dict | None = None


_sessions: OrderedDict[str, Session] = OrderedDict()


class StartRequest(BaseModel):
    speakers: Literal[1, 2] = 1
    source_language: str = Field(min_length=1, max_length=60)
    target_language: str = Field(min_length=1, max_length=60)
    difficulty: Literal[
        "beginner", "elementary", "intermediate", "upper_intermediate", "advanced"
    ] = "intermediate"
    sentences_per_batch: int = Field(default=2, ge=1, le=5)  # dialogue: sentences per turn
    batch_count: int = Field(default=4, ge=1, le=10)  # dialogue: number of turns
    system_prompt: str = Field(default="", max_length=2000)
    session_prompt: str = Field(default="", max_length=2000)


class SubmitRequest(BaseModel):
    interpretations: list[Annotated[str, StringConstraints(max_length=4000)]] = Field(max_length=20)


def _get_session(session_id: str) -> Session:
    session = _sessions.get(session_id)
    if session is None:
        raise HTTPException(404, "Session not found. Please start a new one.")
    return session


def _one_line(text: object, limit: int = 600) -> str:
    return " ".join(str(text or "").split())[:limit]


async def _ask_json(req: StartRequest, parts: list[str], chat: ChatProvider) -> dict:
    messages = [
        {"role": "system", "content": req.system_prompt.strip() or DEFAULT_SYSTEM_PROMPT},
        {"role": "user", "content": "\n\n".join(parts)},
    ]
    try:
        return parse_json(await chat.chat(messages, json_mode=True, temperature=0.8))
    except ValueError:
        return {}


async def _write_speech(req: StartRequest, chat: ChatProvider) -> tuple[list[Part], dict]:
    source, target = req.source_language.strip(), req.target_language.strip()
    total = req.sentences_per_batch * req.batch_count
    parts = [
        f"Write one coherent text in {source}, as exactly {total} sentences, "
        f"for consecutive interpreting practice into {target}. It should "
        "sound like a real speaker: a talk, an announcement, a meeting or an interview answer.",
        f"Level: {DIFFICULTIES[req.difficulty]}.",
    ]
    if req.session_prompt.strip():
        parts.append(f"Learner's instructions for this session: {req.session_prompt.strip()}")
    parts.append(SPOKEN_RULES)
    parts.append(
        'Reply with JSON only: {"source_language_code": "...", "target_language_code": '
        '"...", "sentences": ["...", "..."]}. The codes are BCP-47 codes such as '
        '"en-US" or "ja-JP". Each entry of "sentences" is exactly one sentence.'
    )
    data = await _ask_json(req, parts, chat)
    entries = data.get("sentences", [])
    sentences = [
        _one_line(entry, 400)
        for entry in (entries if isinstance(entries, list) else [])
        if isinstance(entry, str) and entry.strip()
    ][:total]
    source_code = clean_language_code(data.get("source_language_code"))
    target_code = clean_language_code(data.get("target_language_code"))
    size = req.sentences_per_batch
    return [
        Part(
            text=" ".join(sentences[i : i + size]),
            from_language=source,
            to_language=target,
            speak_code=source_code,
            answer_code=target_code,
        )
        for i in range(0, len(sentences), size)
    ], {}


async def _write_dialogue(req: StartRequest, chat: ChatProvider) -> tuple[list[Part], dict]:
    lang_a, lang_b = req.source_language.strip(), req.target_language.strip()
    per_turn = (
        "one sentence" if req.sentences_per_batch == 1 else f"about {req.sentences_per_batch} sentences"
    )
    parts = [
        "Write a realistic dialogue for practising dialogue interpreting. Two people who "
        "do not share a language talk to each other through an interpreter. "
        f"Speaker A speaks only {lang_a}. Speaker B speaks only {lang_b}.",
        f"Write exactly {req.batch_count} turns, alternating, starting with Speaker A. "
        f"Each turn is {per_turn}. Each turn answers the one before it, as if it had "
        "been interpreted. The speakers talk to each other, not to the interpreter, "
        "and never mention the interpreter.",
        f"Level of the language in both languages: {DIFFICULTIES[req.difficulty]}.",
    ]
    if req.session_prompt.strip():
        parts.append(f"Learner's instructions for this session: {req.session_prompt.strip()}")
    parts.append(SPOKEN_RULES)
    parts.append(
        'Reply with JSON only: {"language_a_code": "...", "language_b_code": "...", '
        '"setting": "...", "speaker_a": "...", "speaker_b": "...", "turns": '
        '[{"speaker": "A", "text": "..."}, {"speaker": "B", "text": "..."}]}. '
        f'The codes are the BCP-47 codes of {lang_a} and {lang_b}, such as "en-US" or '
        '"ja-JP". "setting" is the situation in a few English words (for example '
        '"At a hotel reception"). "speaker_a" and "speaker_b" say who each person is, '
        f'in a few English words (for example "hotel guest"). The "text" of Speaker A '
        f"is in {lang_a}; the \"text\" of Speaker B is in {lang_b}."
    )
    data = await _ask_json(req, parts, chat)

    code = {"A": clean_language_code(data.get("language_a_code")), "B": clean_language_code(data.get("language_b_code"))}
    language = {"A": lang_a, "B": lang_b}
    roles = {"A": _one_line(data.get("speaker_a"), 60), "B": _one_line(data.get("speaker_b"), 60)}
    turns = data.get("turns", [])
    result = []
    for position, turn in enumerate(turns if isinstance(turns, list) else []):
        if not isinstance(turn, dict) or not _one_line(turn.get("text")):
            continue
        label = str(turn.get("speaker") or "").strip().upper().removeprefix("SPEAKER").strip()
        speaker = label if label in ("A", "B") else "AB"[position % 2]  # unlabelled: they alternate
        other = "B" if speaker == "A" else "A"
        result.append(
            Part(
                text=_one_line(turn.get("text")),
                from_language=language[speaker],
                to_language=language[other],
                speak_code=code[speaker],
                answer_code=code[other],
                speaker=speaker,
                role=roles[speaker],
            )
        )
    return result[: req.batch_count], {"setting": _one_line(data.get("setting"), 120), "roles": roles}


@router.post("/sessions")
async def start_session(
    req: StartRequest, chat: ChatProvider = Depends(get_chat_provider)
) -> dict:
    dialogue = req.speakers == 2
    parts, extra = await (_write_dialogue if dialogue else _write_speech)(req, chat)
    if not parts:
        raise ProviderError(
            f"The model did not return a usable {'dialogue' if dialogue else 'text'}. "
            "Please try again; if it keeps happening, try a different model."
        )
    session_id = uuid.uuid4().hex
    session = Session(
        mode="dialogue" if dialogue else "speech",
        source_language=req.source_language.strip(),
        target_language=req.target_language.strip(),
        system_prompt=req.system_prompt.strip(),
        parts=parts,
        setting=extra.get("setting", ""),
        roles=extra.get("roles", {}),
    )
    _sessions[session_id] = session
    while len(_sessions) > MAX_SESSIONS:
        _sessions.popitem(last=False)
    return {
        "session_id": session_id,
        "mode": session.mode,
        "setting": session.setting,
        "roles": session.roles,
        "parts": [part.public() for part in parts],
    }


# ---------- checking the language of the "ideal version" ----------
# A small model sometimes writes the ideal version in the language of the
# original instead of the language it should be interpreted into. The code
# cannot read languages, but it can tell writing systems apart (Latin
# letters, kana and kanji, Cyrillic, ...) and it can notice an "ideal" that
# is almost a copy of the original.

_SCRIPTS = (
    ("HIRAGANA", "cjk"), ("KATAKANA", "cjk"), ("CJK", "cjk"), ("HANGUL", "hangul"),
    ("LATIN", "latin"), ("CYRILLIC", "cyrillic"), ("GREEK", "greek"), ("ARABIC", "arabic"),
    ("HEBREW", "hebrew"), ("THAI", "thai"), ("DEVANAGARI", "devanagari"),
)


def script_of(text: str) -> str | None:
    """The writing system most of the letters belong to, or None without letters."""
    counts: Counter[str] = Counter()
    for char in text:
        if not char.isalpha():
            continue
        name = unicodedata.name(char, "")
        counts[next((script for key, script in _SCRIPTS if key in name), "other")] += 1
    return counts.most_common(1)[0][0] if counts else None


def _language_scripts(parts: list[Part], said: list[str]) -> dict[str, str]:
    """Which writing system each language of this session uses, learned from
    the session itself: the originals, or failing that what the learner said."""
    originals: dict[str, str] = {}
    spoken: dict[str, str] = {}
    for part, interpretation in zip(parts, said):
        originals[part.from_language] = originals.get(part.from_language, "") + part.text
        spoken[part.to_language] = spoken.get(part.to_language, "") + interpretation
    scripts = {}
    for language in {*originals, *spoken}:
        script = script_of(originals.get(language, "")) or script_of(spoken.get(language, ""))
        if script:
            scripts[language] = script
    return scripts


def language_problem(ideal: str, part: Part, scripts: dict[str, str]) -> str:
    """"wrong": certainly not the target language (wrong writing system).
    "copy": suspiciously close to the original. "": looks fine."""
    if not ideal:
        return ""
    source, target = script_of(part.text), scripts.get(part.to_language)
    if source and target and source != target:
        return "" if script_of(ideal) == target else "wrong"
    similarity = SequenceMatcher(None, normalize(part.text), normalize(ideal), autojunk=False).ratio()
    return "copy" if similarity > 0.7 else ""


async def _redo_ideals(
    session: Session, numbers: list[int], to_language: str, chat: ChatProvider
) -> dict[int, str]:
    """Asks again for some ideal versions, all into one language, so that
    there is nothing for the model to mix up."""
    lines = "\n".join(
        f"{number}. ({session.parts[number - 1].from_language}) {session.parts[number - 1].text}"
        for number in numbers
    )
    messages = [
        {"role": "system", "content": session.system_prompt or DEFAULT_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Interpret each numbered sentence below into {to_language}, as a skilled "
                f"interpreter would say it: natural, accurate, complete. Write {to_language} "
                "only. Do not repeat or rephrase the sentence in its own language."
                + (f" The situation: {session.setting}." if session.setting else "")
                + f"\n\n{lines}\n\n"
                'Reply with JSON only: {"ideals": [{"number": 1, "ideal": "..."}]}, using the numbers above.'
            ),
        },
    ]
    try:
        entries = parse_json(await chat.chat(messages, json_mode=True, temperature=0.2)).get("ideals", [])
    except (ProviderError, ValueError):
        return {}
    found: dict[int, str] = {}
    for entry in entries if isinstance(entries, list) else []:
        if isinstance(entry, dict):
            try:
                found[int(entry.get("number"))] = str(entry.get("ideal") or "").strip()
            except (TypeError, ValueError):
                continue
    return found


async def _fix_ideal_languages(session: Session, rows: list[dict], said: list[str], chat: ChatProvider) -> None:
    scripts = _language_scripts(session.parts, said)
    problems = {
        row["number"]: problem
        for row, part in zip(rows, session.parts)
        if (problem := language_problem(row["ideal"], part, scripts))
    }
    for to_language in {session.parts[number - 1].to_language for number in problems}:
        numbers = [n for n in problems if session.parts[n - 1].to_language == to_language]
        redone = await _redo_ideals(session, numbers, to_language, chat)
        for number in numbers:
            part, row = session.parts[number - 1], rows[number - 1]
            second = redone.get(number, "")
            if second and language_problem(second, part, scripts) != "wrong":
                row["ideal"] = second
            elif problems[number] == "wrong":
                row["ideal"] = ""  # better none than one in the wrong language


def _who(part: Part) -> str:
    if not part.speaker:
        return ""
    return f"Speaker {part.speaker}" + (f" ({part.role})" if part.role else "")


@router.post("/sessions/{session_id}/submit")
async def submit(
    session_id: str, req: SubmitRequest, chat: ChatProvider = Depends(get_chat_provider)
) -> dict:
    session = _get_session(session_id)
    if session.result is not None:
        return session.result

    count = len(session.parts)
    said = [" ".join(text.split()) for text in (req.interpretations + [""] * count)[:count]]
    blocks = [
        f"Part {i}\n"
        + (f"{_who(part)} said, in {part.from_language}: " if part.speaker else f"Original ({part.from_language}): ")
        + f"{part.text}\n"
        f"Learner's interpretation into {part.to_language}: {spoken or '(nothing said)'}\n"
        f"The ideal version of this part must be written in {part.to_language}."
        for i, (part, spoken) in enumerate(zip(session.parts, said), start=1)
    ]
    if session.mode == "dialogue":
        intro = (
            "A learner practised dialogue interpreting between two people who do not "
            f"share a language. Speaker A speaks {session.source_language} and Speaker B "
            f"speaks {session.target_language}; the learner interpreted each turn into "
            "the other person's language."
            + (f" The situation: {session.setting}." if session.setting else "")
        )
        ideal = (
            '"ideal" is how a skilled interpreter would say that turn in the language it '
            "had to be interpreted into, in the tone that suits the situation and the "
            "listener. The direction changes from part to part: for each part, write the "
            "ideal version in the language stated on its last line, never in the language "
            "of the original."
        )
    else:
        intro = (
            f"A learner practised consecutive interpreting from {session.source_language} "
            f"into {session.target_language}."
        )
        ideal = (
            f'"ideal" is a natural, accurate {session.target_language} interpretation of the '
            f"original, written in {session.target_language}, never in {session.source_language}."
        )
    messages = [
        {"role": "system", "content": session.system_prompt or DEFAULT_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"{intro} Their interpretations come from speech recognition, so ignore "
                "punctuation and allow for small recognition slips.\n\n"
                + "\n\n".join(blocks)
                + '\n\nReply with JSON only: {"batches": [{"ideal": "...", "comment": "..."}], '
                f'"overall": "..."}}. Give exactly {count} entries in "batches", in order. '
                f"{ideal} "
                '"comment" is one to three sentences on meaning errors, '
                'omissions, additions and language mistakes, or praise if it was good. '
                '"overall" is a short summary with two or three tips. Write comments and '
                "the summary in English unless the system prompt asks for another language."
            ),
        },
    ]
    raw = await chat.chat(messages, json_mode=True, temperature=0.3)
    try:
        data = parse_json(raw)
    except ValueError:
        raise ProviderError(
            "The model did not return usable feedback. Please press the button again."
        ) from None
    reviews = data.get("batches", [])
    reviews = reviews if isinstance(reviews, list) else []

    rows = []
    for i, (part, spoken) in enumerate(zip(session.parts, said)):
        review = reviews[i] if i < len(reviews) and isinstance(reviews[i], dict) else {}
        rows.append(
            {
                "number": i + 1,
                "speaker": part.speaker,
                "role": part.role,
                "from_language": part.from_language,
                "to_language": part.to_language,
                "original": part.text,
                "interpretation": spoken,
                "ideal": str(review.get("ideal", "")).strip(),
                "comment": str(review.get("comment", "")).strip(),
            }
        )
    await _fix_ideal_languages(session, rows, said, chat)
    session.result = {
        "mode": session.mode,
        "source_language": session.source_language,
        "target_language": session.target_language,
        "setting": session.setting,
        "roles": session.roles,
        "batches": rows,
        "overall": str(data.get("overall", "")).strip(),
    }
    return session.result
