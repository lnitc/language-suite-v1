"""Reading a learner's handwriting from photos, shared by dictation and essay.

The model is asked for a literal transcription and is never shown what the
learner was supposed to write, so it cannot quietly repair their mistakes.
The features show the result to the learner for checking before it is marked.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import HTTPException
from pydantic import BaseModel, Field, StringConstraints

from ..providers.base import ChatProvider, ProviderError


class HandwritingRequest(BaseModel):
    # Photos of the handwritten page(s), as data URLs.
    images: list[Annotated[str, StringConstraints(max_length=8_000_000)]] = Field(
        min_length=1, max_length=4
    )


async def transcribe_handwriting(
    chat: ChatProvider, language: str, images: list[str], what: str
) -> str:
    """`what` names the piece of work, e.g. "dictation" or "essay"."""
    if any(not image.startswith("data:image/") for image in images):
        raise HTTPException(422, "An uploaded file is not an image.")
    instruction = (
        f"The image{'s show' if len(images) > 1 else ' shows'} a learner's handwritten "
        f"{what} in {language}. Transcribe the handwriting exactly as written. "
        "Keep every spelling and grammar mistake: do not correct, complete or improve "
        "anything, because the mistakes are what will be marked. Leave out words the "
        "writer crossed out. If a word cannot be read, write [?] in its place. Keep "
        "the paragraph breaks. Several images are consecutive pages, in order. Reply "
        "with the transcription only: no comments, no quotation marks, no translation."
    )
    messages = [
        {"role": "system", "content": "You transcribe handwriting precisely and literally."},
        {
            "role": "user",
            "content": [{"type": "text", "text": instruction}]
            + [{"type": "image_url", "image_url": {"url": image}} for image in images],
        },
    ]
    try:
        raw = await chat.chat(messages, temperature=0.0)
    except ProviderError as error:
        raise ProviderError(
            f"{error} Reading handwriting needs a chat model that can read images."
        ) from error
    text = raw.replace("```", "").strip().strip('"').strip()
    if not text:
        raise ProviderError(
            "The model returned no text for this photo. Try a sharper, well-lit photo, "
            "and check that your chat model can read images."
        )
    return text[:20000]
