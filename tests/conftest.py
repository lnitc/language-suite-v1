"""Shared test setup."""

from pathlib import Path

import pytest

BROWSER_TESTS = Path(__file__).resolve().parent / "browser"


@pytest.fixture(autouse=True)
def history_in_a_temporary_file(tmp_path, monkeypatch):
    # No test may write to the learner's real history.
    monkeypatch.setenv("HISTORY_DB", str(tmp_path / "history.db"))


def pytest_collection_modifyitems(items):
    """Marks the browser tests, and runs them after all the others.

    The order matters: while the test browser is open, Playwright keeps its
    own event loop running, and the provider tests (which start a loop of
    their own with asyncio.run) cannot run next to it.
    """
    def in_browser(item) -> bool:
        return BROWSER_TESTS in Path(str(item.fspath)).parents

    for item in items:
        if in_browser(item):
            item.add_marker(pytest.mark.browser)
    items.sort(key=in_browser)  # a stable sort: everything else keeps its order
