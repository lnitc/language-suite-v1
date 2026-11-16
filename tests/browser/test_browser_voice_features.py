"""Browser tests: the features with a voice and a microphone.

The browser is given a pretend microphone, and the pretend services "hear"
every recording as "I am fine thank you." and answer every request for
speech with a short tone.
"""

from helpers import downloaded_text, open_feature, say_something


def test_conversation(page):
    page.fill("#talk-language", "English")
    page.click("#talk-start")
    say_something(page, "#talk-mic")
    # The teacher's greeting, my sentence, the teacher's reply.
    page.wait_for_function("document.getElementById('talk-transcript').children.length === 3")
    assert "I am fine thank you." in page.inner_text("#talk-transcript")
    page.click("#talk-end")
    page.wait_for_selector("#talk-results:not([hidden])")
    assert page.inner_text("#talk-feedback").startswith("What went well")
    name, text = downloaded_text(page, "#talk-download")
    assert name.startswith("conversation-") and "===== SCRIPT =====" in text and "Hello! How are you today?" in text


def test_interpreter(page):
    open_feature(page, "speaking", "interpreter")
    page.fill("#interp-source", "English")
    page.fill("#interp-target", "Japanese")
    page.fill("#interp-per-batch", "2")
    page.fill("#interp-batch-count", "2")
    page.click("#interp-start")
    page.wait_for_selector("#interp-live:not([hidden])")
    for _ in range(2):
        page.click("#interp-play")
        say_something(page, "#interp-mic")
        page.wait_for_function("document.getElementById('interp-status').textContent.startsWith('Recorded')")
        page.click("#interp-next")
    page.wait_for_selector("#interp-results:not([hidden])")
    assert page.inner_text("#interp-overall") == "Good start. Watch omissions."
    assert page.locator("#interp-batches .sentence").count() == 2
    name, text = downloaded_text(page, "#interp-download")
    assert name.startswith("interpreter-") and "Ideal version: 工場へようこそ" in text


def test_shadowing(page):
    open_feature(page, "speaking", "shadowing")
    page.fill("#shadow-language", "English")
    page.fill("#shadow-count", "2")
    page.click("#shadow-start")
    page.wait_for_selector("#shadow-live:not([hidden])")
    page.click("#shadow-play")
    say_something(page, "#shadow-mic")
    page.wait_for_selector("#shadow-attempt:not([hidden])")
    assert "100%" in page.inner_text("#shadow-score")  # sentence 1 is exactly what the pretend ear hears
    page.click("#shadow-next")
    say_something(page, "#shadow-mic")
    page.wait_for_function("!document.getElementById('shadow-score').textContent.includes('100%')")
    assert page.locator("#shadow-marked .miss").count() > 0


def test_speech(page):
    open_feature(page, "speaking", "speech")
    page.fill("#sp-language", "English")
    page.select_option("#sp-minutes", "1")
    page.click("#sp-start")
    page.wait_for_selector("#sp-write:not([hidden])")
    assert page.inner_text("#sp-assignment").startswith("Assignment")
    page.click("#sp-record")
    page.wait_for_function("document.getElementById('sp-record').textContent.includes('Stop recording')")
    page.wait_for_timeout(1200)
    page.click("#sp-record")
    page.wait_for_selector("#sp-form:not([hidden])")
    assert page.input_value("#sp-transcript") == "I am fine thank you."
    page.click("#sp-submit")
    page.wait_for_selector("#sp-results:not([hidden])")
    assert "12 / 20" in page.inner_text("#sp-rating")
    assert page.inner_text("#sp-sample").startswith("Good morning, everyone.")
    name, text = downloaded_text(page, "#sp-download")
    assert name.startswith("speech-") and "===== YOUR SPEECH (as heard by the app) =====" in text


def test_listening_comprehension(page):
    open_feature(page, "listening")
    page.fill("#listen-language", "English")
    page.fill("#listen-count", "2")
    page.click("#listen-start")
    page.wait_for_selector("#listen-form:not([hidden])")
    # The text is heard, not shown, until the answers are in.
    assert "heavy rain" not in page.inner_text("#listen-work")
    page.click("#listen-play")
    page.wait_for_function("document.getElementById('listen-play').textContent.includes('Play again')")
    page.locator("#listen-questions fieldset >> nth=0").locator("input").first.check()
    page.click("#listen-form button[type=submit]")
    page.wait_for_selector("#listen-results:not([hidden])")
    assert "/ 2" in page.inner_text("#listen-score")
    name, text = downloaded_text(page, "#listen-download")
    assert name.startswith("listening-") and "heavy rain" in text
