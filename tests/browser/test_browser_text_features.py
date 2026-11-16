"""Browser tests: the features that are typed (no microphone)."""

from helpers import answer_vocabulary, downloaded_text, open_feature


def test_vocabulary_practice(page):
    open_feature(page, "vocabulary")
    page.fill("#source-language", "English")
    page.fill("#target-language", "Spanish")
    page.fill("#count", "3")
    page.click("#start-button")
    page.wait_for_selector("#vocab-practice:not([hidden])")
    assert page.inner_text("#progress") == "Word 1 of 3" and page.inner_text("#word") == "dog"
    answer_vocabulary(page, ["Perro", "gato", None])  # right, wrong, skipped

    assert page.inner_text("#score") == "Score: 1 / 3 (33%)"
    assert page.locator("#result-rows tr td:last-child").all_inner_texts() == ["Correct", "Wrong", "Skipped"]
    name, text = downloaded_text(page, "#vocab-download")
    assert name.startswith("vocabulary-") and name.endswith(".txt")
    assert "===== WORDS TO REVIEW =====" in text and "car = coche, carro" in text


def test_grammar_drills(page):
    open_feature(page, "grammar")
    page.fill("#gr-language", "English")
    page.fill("#gr-topic", "past simple")
    page.fill("#gr-count", "4")
    page.click("#gr-start")
    page.wait_for_selector("#gr-work:not([hidden])")
    fields = page.locator("#gr-items [data-answer]")
    assert fields.count() == 4
    # A "correct the mistake" item starts with the wrong sentence, ready to edit.
    assert fields.nth(0).input_value() == "" and fields.nth(1).input_value().startswith("She don't")
    assert page.inner_text("#gr-unanswered").startswith("4 of 4 not answered")

    fields.nth(0).fill("Went")
    fields.nth(1).fill(fields.nth(1).input_value().replace("don't", "doesn't"))
    fields.nth(2).fill("goed")
    page.click("#gr-form button[type=submit]")
    page.wait_for_selector("#gr-results:not([hidden])")
    assert page.inner_text("#gr-score") == "Score: 2 / 4"
    assert page.locator("#gr-answers .badge").all_inner_texts() == ["Correct", "Correct", "Wrong", "Not answered"]
    assert "This form does not exist" in page.inner_text("#gr-answers .answer >> nth=2")
    name, text = downloaded_text(page, "#gr-download")
    assert name.startswith("grammar-") and "Grammar point: past simple" in text


def test_dictation_typed(page):
    open_feature(page, "writing", "dictation")
    page.fill("#dict-language", "English")
    page.select_option("#dict-length", "short")
    page.click("#dict-start-button")
    page.wait_for_selector("#dict-practice:not([hidden])")
    for typed in ("the cat sit on mat today", "It was a sunny day", ""):
        page.fill("#dict-answer", typed)
        page.click("#dict-next")
    page.wait_for_selector("#dict-results:not([hidden])")
    name, text = downloaded_text(page, "#dict-download")
    assert name.startswith("dictation-")
    assert "Accuracy:" in text and "Correct:   The cat sat on the mat." in text
    assert "Missed or wrong: sat, the" in text and "(nothing written)" in text


def test_reading_comprehension(page):
    open_feature(page, "reading")
    page.fill("#read-language", "English")
    page.fill("#read-count", "2")
    page.click("#read-start")
    page.wait_for_selector("#read-form:not([hidden])")
    assert page.inner_text("#read-title") == "The old bridge" and page.locator("#read-text p").count() == 3
    questions = page.locator("#read-questions fieldset")
    assert questions.count() == 2
    for number, pick_right in ((0, True), (1, False)):
        options = questions.nth(number).locator("label").all_inner_texts()
        index = next(i for i, option in enumerate(options) if ("hundred" in option) == pick_right)
        questions.nth(number).locator("input").nth(index).check()
    page.click("#read-form button[type=submit]")
    page.wait_for_selector("#read-results:not([hidden])")
    assert "1 / 2" in page.inner_text("#read-score")
    assert page.locator("#read-results .badge").all_inner_texts() == ["Correct", "Wrong"]
    assert "reread the first sentence" in page.inner_text("#read-results .answer >> nth=1")
    name, text = downloaded_text(page, "#read-download")
    assert name.startswith("reading-") and "===== QUESTIONS AND ANSWERS =====" in text


def test_essay(page):
    open_feature(page, "writing", "essay")
    page.fill("#essay-language", "English")
    page.click("#essay-start")
    page.wait_for_selector("#essay-write:not([hidden])")
    assert page.inner_text("#essay-assignment").startswith("Assignment")
    page.fill("#essay-text", "My favorit season is autum. I goed to the mountain with my family last year.")
    page.click("#essay-submit")
    page.wait_for_selector("#essay-results:not([hidden])")
    assert "12 / 20" in page.inner_text("#essay-rating")
    assert page.locator("#essay-corrections .correction").count() == 2
    assert page.inner_text("#essay-ideal").startswith("My favourite season is autumn.")
    name, text = downloaded_text(page, "#essay-download")
    assert name.startswith("essay-") and "===== IDEAL VERSION =====" in text


def test_written_translation(page):
    open_feature(page, "writing", "translation")
    page.fill("#tr-source-language", "English")
    page.fill("#tr-target-language", "Japanese")
    page.click("#tr-start")
    page.wait_for_selector("#tr-write:not([hidden])")
    assert "I went to the zoo" in page.inner_text("#tr-given-text")
    page.fill("#tr-translation", "先週末、動物園に行きました。楽しいでした。")
    page.click("#tr-submit")
    page.wait_for_selector("#tr-results:not([hidden])")
    assert "12 / 20" in page.inner_text("#tr-rating")
    assert "とても楽しかったです" in page.inner_text("#tr-corrections")
    assert page.inner_text("#tr-ideal").startswith("先週末")
    name, text = downloaded_text(page, "#tr-download")
    assert name.startswith("translation-") and "Languages: English -> Japanese" in text


def test_word_list_creator(page):
    open_feature(page, "vocabulary", "wordlist")
    page.fill("#wl-source", "English")
    page.fill("#wl-target", "Spanish")
    page.fill("#wl-count", "12")
    page.click("#wl-start")
    page.wait_for_selector("#wl-list:not([hidden])")
    page.wait_for_function("document.getElementById('wl-status').textContent.startsWith('Done')")
    assert page.locator("#wl-rows tr").count() == 12
    name, text = downloaded_text(page, "#wl-download")
    assert name.startswith("wordlist-") and name.endswith(".csv")
    assert len(text.strip().splitlines()) == 13 and "word12" in text  # a header and twelve words
