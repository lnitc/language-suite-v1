"""Browser tests: results are saved, shown again, and mistakes can be practised."""

from helpers import answer_vocabulary, downloaded_text, open_feature, saved_results


def do_vocabulary(page, answers):
    open_feature(page, "vocabulary", "vocabulary")
    if page.is_visible("#restart-button"):
        page.click("#restart-button")
    page.fill("#source-language", "English")
    page.fill("#target-language", "Spanish")
    page.fill("#count", "3")
    page.click("#start-button")
    page.wait_for_selector("#vocab-practice:not([hidden])")
    answer_vocabulary(page, answers)


def test_results_appear_in_the_history(page):
    open_feature(page, "progress")
    page.wait_for_selector("#hist-empty:not([hidden])")
    assert page.is_checked("#hist-on")

    do_vocabulary(page, ["perro", "gato", None])
    open_feature(page, "progress", "history")
    page.wait_for_selector("#hist-table:not([hidden])")
    row = page.inner_text("#hist-table tbody tr")
    assert "Vocabulary practice" in row and "Spanish" in row and "1 / 3 (33%)" in row
    assert "33%" in page.inner_text("#hist-summary tbody tr")

    # Open shows the same text as the download of that day.
    page.click("#hist-table tbody button")
    page.wait_for_selector("#hist-detail:not([hidden])")
    assert "Score: 1 / 3 (33%)" in page.inner_text("#hist-report")
    name, text = downloaded_text(page, "#hist-download")
    assert name.startswith("vocabulary-") and "===== WORDS =====" in text
    page.click("#hist-delete")
    page.wait_for_selector("#hist-empty:not([hidden])")


def test_wrong_words_can_be_practised_until_learned(page):
    do_vocabulary(page, ["perro", "gato", None])  # car wrong, house skipped
    open_feature(page, "progress", "mistakes")
    page.wait_for_selector(".mistake")
    assert sorted(page.locator(".mistake .prompt").all_inner_texts()) == ["car", "house"]
    assert page.inner_text("#mist-practise-note").startswith("2 words (English → Spanish)")

    page.click("#mist-practise")
    page.wait_for_selector("#vocab-practice:not([hidden])")
    assert page.inner_text(".section-tab.active") == "Vocabulary"
    assert page.inner_text("#vocab-note") == "Practising 2 words from your mistakes."
    first = page.inner_text("#word")
    second = "house" if first == "car" else "car"
    answer_vocabulary(page, [{"car": "coche", "house": "casa"}[first], "nonsense"])
    assert page.inner_text("#score") == "Score: 1 / 2 (50%)"

    open_feature(page, "progress", "mistakes")
    page.wait_for_function("document.querySelectorAll('.mistake').length === 1")
    assert page.inner_text(".mistake .prompt") == second and "wrong 2 times" in page.inner_text(".mistake")
    page.select_option("#mist-show", "true")  # the other word became "learned" by itself
    page.wait_for_function("word => document.querySelector('.mistake .prompt')?.textContent === word", arg=first)
    name, text = downloaded_text(page, "#mist-download")
    assert name.startswith("mistakes-") and first in text
    page.click(".mistake button:has-text('Remove')")
    page.wait_for_function("document.querySelectorAll('.mistake').length === 0")


def test_saving_can_be_switched_off(page):
    open_feature(page, "progress")
    page.uncheck("#hist-on")
    do_vocabulary(page, ["perro", "coche", "casa"])
    assert saved_results(page) == []
    page.reload()  # the choice is remembered in this browser
    open_feature(page, "progress")
    assert not page.is_checked("#hist-on")
    page.check("#hist-on")
    do_vocabulary(page, ["perro", "coche", "casa"])
    page.wait_for_timeout(300)
    assert [(row["feature"], row["percent"]) for row in saved_results(page)] == [("vocabulary", 100)]
