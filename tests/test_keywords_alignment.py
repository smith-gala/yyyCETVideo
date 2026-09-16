from PIL import Image, ImageDraw

from app.renderers.keywords_renderer import _visual_centered_text_y
from app.renderers.layout_utils import load_english_font, load_font


def test_english_and_chinese_main_text_share_visual_center():
    draw = ImageDraw.Draw(Image.new("RGB", (1000, 200)))
    english = "convenient living circles"
    chinese = "便民生活圈"
    english_font = load_english_font(42, "bold")
    chinese_font = load_font(42, "bold")
    target_center = 56

    english_y = _visual_centered_text_y(draw, english, english_font, target_center)
    chinese_y = _visual_centered_text_y(draw, chinese, chinese_font, target_center)
    english_box = draw.textbbox((0, english_y), english, font=english_font)
    chinese_box = draw.textbbox((0, chinese_y), chinese, font=chinese_font)

    english_center = (english_box[1] + english_box[3]) / 2
    chinese_center = (chinese_box[1] + chinese_box[3]) / 2
    assert abs(english_center - chinese_center) <= 1
