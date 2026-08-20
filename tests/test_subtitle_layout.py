from app.renderers.design_tokens import CANVAS, COLORS, SUBTITLE
from app.renderers.subtitle_renderer import SubtitleRenderer
from app.renderers.layout_utils import load_font, text_width, wrap_text_balanced
from PIL import Image, ImageDraw


def test_subtitle_has_transparent_background_and_centered_bilingual_lines():
    image = SubtitleRenderer().render_card(
        "English subtitle position",
        "中文字幕位置",
    )
    alpha = image.getchannel("A")

    assert alpha.getpixel((0, 0)) == 0
    assert alpha.getpixel((image.width - 1, image.height - 1)) == 0
    assert sum(1 for value in alpha.getdata() if value) < image.width * image.height * 0.2
    assert COLORS.subtitle_text in image.getdata()
    assert COLORS.subtitle_outline in image.getdata()

    upper = alpha.crop((0, 0, image.width, image.height // 2)).getbbox()
    lower = alpha.crop((0, image.height // 2, image.width, image.height)).getbbox()
    assert upper is not None
    assert lower is not None
    assert abs((upper[0] + upper[2]) / 2 - image.width / 2) <= 2
    assert abs((lower[0] + lower[2]) / 2 - image.width / 2) <= 2


def test_portrait_subtitle_is_centered_and_landscape_subtitle_is_at_bottom():
    content_height = 220

    portrait_y = SUBTITLE.position_y(1920, content_height, "portrait")
    landscape_y = SUBTITLE.position_y(1920, content_height, "landscape")

    assert portrait_y + content_height / 2 == 1920 / 2
    assert landscape_y + content_height == 1920 - SUBTITLE.bottom


def test_two_line_subtitle_does_not_leave_a_shorter_first_line():
    image = Image.new("RGB", (940, 200), "white")
    draw = ImageDraw.Draw(image)
    font = load_font(31, "bold")
    lines = wrap_text_balanced(
        draw,
        "and his research team overcame numerous challenges to develop a super hybrid rice variety.",
        font,
        SUBTITLE.width - SUBTITLE.padding_x * 2,
        prefer_words=True,
    )

    assert len(lines) == 2
    assert text_width(draw, lines[0], font) >= text_width(draw, lines[1], font)
    assert " ".join(lines) == "and his research team overcame numerous challenges to develop a super hybrid rice variety."


def test_portrait_subtitle_uses_fixed_sizes_and_thirty_pixel_safe_area(monkeypatch):
    import app.renderers.subtitle_renderer as renderer_module

    used_sizes = []
    original_load_font = renderer_module.load_font

    def recording_load_font(size, weight="regular"):
        used_sizes.append(size)
        return original_load_font(size, weight)

    monkeypatch.setattr(renderer_module, "load_font", recording_load_font)
    renderer = renderer_module.SubtitleRenderer()
    renderer.render_card("Short line", "短字幕")
    renderer.render_card(
        "This deliberately longer sentence wraps naturally without changing its font size across subtitle cues.",
        "这是一条更长的中文字幕，用来确认换行时不会缩小字号。",
    )

    assert used_sizes == [
        SUBTITLE.english_font_size,
        SUBTITLE.chinese_font_size,
        SUBTITLE.english_font_size,
        SUBTITLE.chinese_font_size,
    ]
    assert SUBTITLE.x >= 30
    assert SUBTITLE.x + SUBTITLE.width <= CANVAS.width - 30


def test_fixed_size_wrapping_fills_first_line_before_wrapping():
    image = Image.new("RGB", (SUBTITLE.width, 300), "white")
    draw = ImageDraw.Draw(image)
    font = load_font(SUBTITLE.english_font_size, "bold")
    max_width = SUBTITLE.width - SUBTITLE.padding_x * 2
    text = "This sentence should remain on its first line until the next complete word would cross the safe area boundary"
    from app.renderers.layout_utils import wrap_text

    lines = wrap_text(draw, text, font, max_width, prefer_words=True)
    assert len(lines) >= 2
    next_word = lines[1].split()[0]
    assert text_width(draw, f"{lines[0]} {next_word}", font) > max_width


def test_announcement_moves_up_fifty_pixels_and_keywords_keep_thirty_pixel_gap():
    from app.pipeline.video_pipeline import VideoPipeline
    from app.renderers.design_tokens import KEYWORDS

    content_height = 179
    normal_y = SUBTITLE.position_y(CANVAS.height, content_height, "landscape")
    announcement_y = VideoPipeline._subtitle_position(content_height, "landscape", y_offset=-50)
    keywords_y = VideoPipeline._subtitle_position(
        content_height,
        "landscape",
        y_offset=-50,
        minimum_y=KEYWORDS.outer[3] + 30,
    )

    assert announcement_y == normal_y - 50
    assert keywords_y == KEYWORDS.outer[3] + 30
