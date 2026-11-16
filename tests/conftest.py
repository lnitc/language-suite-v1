"""Shared test setup."""

import pytest


@pytest.fixture(autouse=True)
def history_in_a_temporary_file(tmp_path, monkeypatch):
    # No test may write to the learner's real history.
    monkeypatch.setenv("HISTORY_DB", str(tmp_path / "history.db"))
