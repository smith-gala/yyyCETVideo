from app.renderers.keywords_renderer import _highlight_ranges


def _highlighted_parts(text: str, phrase: str) -> list[str]:
    return [text[start:end] for start, end in _highlight_ranges(text, phrase)]


def test_example_highlights_the_complete_key_expression_case_insensitively():
    text = "Yuan Longping is honored as the Father of Hybrid Rice."

    assert _highlighted_parts(text, "father of hybrid rice") == ["Father of Hybrid Rice"]


def test_example_highlights_key_words_when_modifiers_split_the_phrase():
    text = "Scientists must overcome numerous research challenges."

    assert _highlighted_parts(text, "overcome challenges") == ["overcome", "challenges"]


def test_highlight_does_not_match_inside_another_word():
    assert _highlighted_parts("The price is stable.", "rice") == []
