"""Small text helpers shared by the features."""

from __future__ import annotations

import json
import re
import unicodedata
from difflib import SequenceMatcher

# Scripts written without spaces between words: compared character by character.
_CHAR_SCRIPTS = re.compile(
    "[぀-ヿ㐀-䶿一-鿿฀-໿က-႟ក-៿]"
)


def normalize(text: str) -> str:
    """Make comparison forgiving: case, punctuation, width and spacing."""
    text = unicodedata.normalize("NFKC", text).casefold()
    text = re.sub(r"[^\w\s]", " ", text)
    return " ".join(text.split())


def parse_json(raw: str) -> dict:
    """Parse model output, tolerating code fences or stray text around it."""
    try:
        data = json.loads(raw)
    except ValueError:
        start, end = raw.find("{"), raw.rfind("}")
        if start == -1 or end <= start:
            raise ValueError("no JSON object found") from None
        data = json.loads(raw[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("JSON is not an object")
    return data


def _tokens(text: str, by_char: bool) -> list[tuple[str, str]]:
    """Split into (shown text, comparison key). Punctuation gets an empty key."""
    raw = [c for c in text if not c.isspace()] if by_char else text.split()
    return [(token, normalize(token).replace(" ", "")) for token in raw]


def compare(expected: str, typed: str) -> dict:
    """Mark which words (or characters) of a dictation match the original.

    Case and punctuation are ignored. Returns both texts as token lists with
    an ``ok`` flag each, plus counts for scoring.
    """
    by_char = bool(_CHAR_SCRIPTS.search(expected))
    exp, got = _tokens(expected, by_char), _tokens(typed, by_char)
    exp_idx = [i for i, (_, key) in enumerate(exp) if key]
    got_idx = [i for i, (_, key) in enumerate(got) if key]

    matcher = SequenceMatcher(
        a=[exp[i][1] for i in exp_idx], b=[got[i][1] for i in got_idx], autojunk=False
    )
    exp_ok, got_ok, correct = set(), set(), 0
    for block in matcher.get_matching_blocks():
        for offset in range(block.size):
            exp_ok.add(exp_idx[block.a + offset])
            got_ok.add(got_idx[block.b + offset])
        correct += block.size

    def marked(tokens, ok):
        return [{"text": t, "ok": (not key) or i in ok} for i, (t, key) in enumerate(tokens)]

    return {
        "expected": marked(exp, exp_ok),
        "typed": marked(got, got_ok),
        "correct": correct,
        "total": max(len(exp_idx), len(got_idx)),
        "joiner": "" if by_char else " ",
    }
