"""Setup for the browser tests.

These tests open the real pages in a real browser and click through them,
the way a learner would. Three things are started for the test run:

  1. pretend model, voice and speech-recognition services (fake_services.py);
  2. the app itself, pointed at those services and at a temporary history
     file (your own ".env", Ollama and history are not used or touched);
  3. a browser without a window, with a pretend microphone.

Install once:   pip install -r requirements-browser.txt
Run:            python -m pytest tests/browser
Watch it work:  set BROWSER_TESTS_HEADED=1 first (a window opens)

Without the "playwright" package the tests are skipped, not failed.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
INSTALL_HINT = "Install it with:  pip install -r requirements-browser.txt"


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _wait_until_up(url: str, process: subprocess.Popen, log: Path) -> None:
    deadline = time.time() + 30
    while time.time() < deadline:
        if process.poll() is not None:
            break
        try:
            with urllib.request.urlopen(url, timeout=1):
                return
        except OSError:
            time.sleep(0.2)
    process.kill()
    raise RuntimeError(f"A test server did not start ({url}). Its output:\n{log.read_text(errors='replace')[-2000:]}")


@pytest.fixture(scope="session")
def app_url(tmp_path_factory):
    """Starts the pretend services and the app; gives the app's address."""
    folder = tmp_path_factory.mktemp("browser")
    fake_port, app_port = _free_port(), _free_port()
    fake = f"http://127.0.0.1:{fake_port}/v1"
    # Every setting is given here, so nothing is read from a developer's ".env"
    # (in particular no real key is ever sent to the pretend services).
    env = {
        **os.environ,
        "LLM_PROVIDER": "openai_compatible", "LLM_BASE_URL": fake, "LLM_MODEL": "pretend-model",
        "LLM_API_KEY": "", "LLM_TIMEOUT": "30", "LLM_CONTEXT_TOKENS": "4096",
        "TTS_PROVIDER": "openai_compatible", "TTS_BASE_URL": fake, "TTS_MODEL": "pretend-voice",
        "TTS_VOICE": "test", "TTS_API_KEY": "", "TTS_TIMEOUT": "30",
        "STT_PROVIDER": "openai_compatible", "STT_BASE_URL": fake, "STT_MODEL": "pretend-ear",
        "STT_API_KEY": "", "STT_TIMEOUT": "30",
        "HISTORY_DB": str(folder / "history.db"),
    }
    uvicorn = [sys.executable, "-m", "uvicorn", "--host", "127.0.0.1", "--log-level", "warning"]
    processes = []
    try:
        for name, target, port, cwd in (
            ("services", "fake_services:app", fake_port, HERE),
            ("app", "app.main:app", app_port, ROOT),
        ):
            log = folder / f"{name}.log"
            process = subprocess.Popen(
                [*uvicorn, target, "--port", str(port)],
                cwd=cwd, env=env, stdout=log.open("wb"), stderr=subprocess.STDOUT,
            )
            processes.append(process)
            check = "/openapi.json" if name == "services" else "/api/health"
            _wait_until_up(f"http://127.0.0.1:{port}{check}", process, log)
        yield f"http://127.0.0.1:{app_port}"
    finally:
        for process in processes:
            process.terminate()
        for process in processes:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()


@pytest.fixture(scope="session")
def browser():
    """A browser without a window. Uses, in this order: the program named in
    BROWSER_TESTS_CHROME, Playwright's own Chromium, installed Chrome, Edge."""
    try:
        from playwright.sync_api import Error, sync_playwright
    except ImportError:
        pytest.skip(f"The browser tests need the 'playwright' package. {INSTALL_HINT}")
    options = {
        "headless": not os.getenv("BROWSER_TESTS_HEADED"),
        # A pretend microphone, and sound may play without a click first.
        "args": ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
                 "--autoplay-policy=no-user-gesture-required", "--no-sandbox"],
    }
    custom = os.getenv("BROWSER_TESTS_CHROME")
    choices = [{"executable_path": custom}] if custom else [{}, {"channel": "chrome"}, {"channel": "msedge"}]
    with sync_playwright() as playwright:
        launched, problems = None, []
        for choice in choices:
            try:
                launched = playwright.chromium.launch(**options, **choice)
                break
            except Error as error:
                problems.append(str(error).splitlines()[0])
        if launched is None:
            pytest.skip(
                "No browser could be started for the tests. Run:  python -m playwright install chromium  "
                f"({'; '.join(problems)})"
            )
        yield launched
        launched.close()


@pytest.fixture
def page(browser, app_url):
    """A fresh browser profile on the app's first page, with an empty history.
    The test fails if the page reports a script error."""
    for what in ("results", "mistakes"):
        urllib.request.urlopen(urllib.request.Request(f"{app_url}/api/history/{what}", method="DELETE"), timeout=10)
    context = browser.new_context(
        base_url=app_url, permissions=["microphone"], accept_downloads=True,
        viewport={"width": 1000, "height": 1000},
    )
    tab = context.new_page()
    tab.set_default_timeout(20_000)
    script_errors = []
    tab.on("pageerror", lambda error: script_errors.append(str(error)))
    tab.on("dialog", lambda dialog: dialog.accept())  # "Really delete?" -> yes
    tab.goto("/")
    yield tab
    context.close()
    assert not script_errors, f"The page reported script errors: {script_errors}"
