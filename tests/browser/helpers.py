"""Small helpers shared by the browser tests."""

from __future__ import annotations


def open_feature(page, section: str, feature: str | None = None, kind: str | None = None) -> None:
    """Clicks a section tab and, if given, one of its feature tabs."""
    page.click(f".section-tab[data-section={section}]")
    if feature:
        page.click(f".tab[data-feature={feature}]" + (f"[data-kind={kind}]" if kind else ""))


def visible_features(page) -> list[str]:
    return [tab.inner_text() for tab in page.locator("#feature-nav .tab").all() if tab.is_visible()]


def downloaded_text(page, button: str) -> tuple[str, str]:
    """Clicks a download button; returns the file name and its text."""
    with page.expect_download() as download:
        page.click(button)
    path = download.value.path()
    with open(path, encoding="utf-8-sig") as file:
        return download.value.suggested_filename, file.read()


def say_something(page, mic: str) -> None:
    """Records half a second with the pretend microphone: click, wait, click."""
    page.wait_for_function(
        "id => { const b = document.querySelector(id); return !b.disabled && b.textContent.includes('Speak'); }", arg=mic
    )
    page.click(mic)
    page.wait_for_function("id => document.querySelector(id).textContent.includes('Stop')", arg=mic)
    page.wait_for_timeout(500)
    page.click(mic)


def answer_vocabulary(page, answers: list[str | None]) -> None:
    """Types each answer (None presses Skip) until the result is shown."""
    for answer in answers:
        word = page.inner_text("#word")
        if answer is None:
            page.click("#skip-button")
        else:
            page.fill("#answer", answer)
            page.click("#answer-form button[type=submit]")
        page.wait_for_function(
            "w => document.getElementById('word').textContent !== w || !document.getElementById('vocab-results').hidden",
            arg=word,
        )
    page.wait_for_selector("#vocab-results:not([hidden])")


def saved_results(page) -> list[dict]:
    """What the history holds, newest first (asked from the app's own API)."""
    return page.request.get("/api/history/results").json()["results"]
