"""Things that belong to one browser request and are needed in many places.

- The learner's preferred language for feedback and explanations, sent by
  the browser with every request.
- Notes for the learner collected while the request is handled, such as
  "this request is large for the model". They travel back in a response
  header and are shown on the page.

Both live in context variables, so features and providers can reach them
without every function having to pass them along.
"""

from __future__ import annotations

import re
from contextvars import ContextVar
from urllib.parse import quote, unquote

DEFAULT_FEEDBACK_LANGUAGE = "English"
FEEDBACK_HEADER = b"x-feedback-language"
WARNING_HEADER = b"x-app-warning"

_feedback_language: ContextVar[str] = ContextVar("feedback_language", default=DEFAULT_FEEDBACK_LANGUAGE)
_warnings: ContextVar[list[str] | None] = ContextVar("warnings", default=None)
# A language name: letters of any script, spaces, hyphens, brackets. Nothing
# else, because the value is placed inside instructions to the model.
_LANGUAGE_NAME = re.compile(r"^[^\W\d_](?:[^\W\d_]|[ \-()（）])*$")


def clean_language_name(value: str) -> str:
    value = " ".join(value.split())
    return value if len(value) <= 40 and _LANGUAGE_NAME.match(value) else ""


def feedback_language() -> str:
    """The language the teacher's feedback and explanations should be in."""
    return _feedback_language.get()


def add_warning(message: str) -> None:
    notes = _warnings.get()
    if notes is not None and message not in notes:
        notes.append(message)


def current_warnings() -> list[str]:
    return list(_warnings.get() or [])


class RequestContext:
    """ASGI middleware: reads the preferences in, and writes the notes out."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or [])
        language = clean_language_name(unquote(headers.get(FEEDBACK_HEADER, b"").decode("latin-1")))
        notes: list[str] = []
        language_token = _feedback_language.set(language or DEFAULT_FEEDBACK_LANGUAGE)
        warnings_token = _warnings.set(notes)

        async def send_with_notes(message) -> None:
            if message["type"] == "http.response.start" and notes:
                message = {
                    **message,
                    "headers": [*message.get("headers", []), (WARNING_HEADER, quote(notes[0]).encode("ascii"))],
                }
            await send(message)

        try:
            await self.app(scope, receive, send_with_notes)
        finally:
            _feedback_language.reset(language_token)
            _warnings.reset(warnings_token)
