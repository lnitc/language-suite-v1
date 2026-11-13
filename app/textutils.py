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


def split_by_sentence(sentences: list[str], text: str) -> list[str]:
    """Cut one continuous dictation (e.g. read from handwriting) into the parts
    that belong to each original sentence, so each sentence can be marked.

    Words that match the original show where each sentence is. A word that
    matches nothing goes to the sentence of the original word it stands in for.
    """
    by_char = any(_CHAR_SCRIPTS.search(sentence) for sentence in sentences)
    expected = [  # (comparison key, sentence number) for every word of the original
        (key, number)
        for number, sentence in enumerate(sentences)
        for _, key in _tokens(sentence, by_char)
        if key
    ]
    written = _tokens(text, by_char)
    parts: list[list[str]] = [[] for _ in sentences]
    if not expected or not written:
        return ["" for _ in sentences]

    words = [i for i, (_, key) in enumerate(written) if key]
    matcher = SequenceMatcher(
        a=[key for key, _ in expected], b=[written[i][1] for i in words], autojunk=False
    )
    partner = {}  # position in `words` -> position in `expected`
    for block in matcher.get_matching_blocks():
        for offset in range(block.size):
            partner[block.b + offset] = block.a + offset

    owner: dict[int, int] = {}  # index in `written` -> sentence number
    position = 0
    while position < len(words):
        if position in partner:
            owner[words[position]] = expected[partner[position]][1]
            position += 1
            continue
        # A run of words that match nothing: spread it over the original
        # words that are missing between the neighbouring matches.
        end = position
        while end < len(words) and end not in partner:
            end += 1
        before = partner[position - 1] if position > 0 else -1
        after = partner[end] if end < len(words) else len(expected)
        missing, run = after - before - 1, end - position
        for k in range(run):
            if missing > 0:
                target = before + 1 + (k * missing) // run
            else:
                target = before if before >= 0 else min(after, len(expected) - 1)
            owner[words[position + k]] = expected[target][1]
        position = end

    current = owner[words[0]] if words else 0
    for i, (shown, _) in enumerate(written):  # punctuation stays with the word before it
        current = owner.get(i, current)
        parts[current].append(shown)
    return [("" if by_char else " ").join(part) for part in parts]
