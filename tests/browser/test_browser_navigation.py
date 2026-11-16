"""Browser tests: sections, feature tabs and the Settings panel."""

from helpers import open_feature, visible_features


def test_first_page_and_sections(page):
    assert page.locator(".section-tab").all_inner_texts() == [
        "Speaking", "Listening", "Vocabulary", "Writing", "Reading", "Grammar", "Progress",
    ]
    # The app opens on Speaking > Conversation.
    assert page.inner_text(".section-tab.active") == "Speaking"
    assert page.inner_text(".tab.active") == "Conversation"
    assert page.is_visible("#talk-setup-form")

    expected = {
        "vocabulary": (["Vocabulary practice", "Word list creator"], "#setup-form"),
        "writing": (["Dictation", "Essay", "Translation"], "#dict-setup-form"),
        "progress": (["History", "My mistakes"], "#hist-list"),
    }
    for section, (features, first_form) in expected.items():
        open_feature(page, section)
        assert visible_features(page) == features
        assert page.is_visible(first_form)
        assert page.locator(".feature:not([hidden])").count() == 1  # one page at a time

    # A section with a single feature needs no second row of tabs.
    for section, form in (("listening", "#listen-setup-form"), ("reading", "#read-setup-form"), ("grammar", "#gr-setup-form")):
        open_feature(page, section)
        assert page.is_hidden("#feature-nav") and page.is_visible(form)


def test_a_section_remembers_its_last_feature(page):
    open_feature(page, "writing", "essay")
    open_feature(page, "speaking", "talk", kind="interview")
    assert page.inner_text("#talk-title") != "Conversation partner"
    open_feature(page, "writing")
    assert page.inner_text(".tab.active") == "Essay" and page.is_visible("#essay-setup-form")
    open_feature(page, "speaking")
    assert page.inner_text(".tab.active") == "Job interview"


def test_settings_fill_the_forms_and_survive_a_reload(page):
    page.click("#settings-open")
    page.fill("#set-learning", "Japanese")
    page.fill("#set-native", "English")
    page.select_option("#set-level", "advanced")
    page.click("#settings-form button[type=submit]")
    page.wait_for_selector("#settings-saved:not([hidden])")

    page.reload()
    open_feature(page, "grammar")
    assert page.input_value("#gr-language") == "Japanese"
    assert page.input_value("#gr-difficulty") == "advanced"
    # Vocabulary: words are shown in my language and answered in the new one.
    open_feature(page, "vocabulary")
    assert (page.input_value("#source-language"), page.input_value("#target-language")) == ("English", "Japanese")
    # A field the learner filled in is not overwritten.
    page.fill("#target-language", "Korean")
    open_feature(page, "grammar")
    open_feature(page, "vocabulary")
    assert page.input_value("#target-language") == "Korean"
