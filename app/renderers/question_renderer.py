"""中文翻译题板渲染器。"""
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

from app.config import ASSET_QUESTION_BG
from app.models import ExamMetadata
from app.renderers.design_tokens import CANVAS, COLORS, QUESTION
from app.renderers.layout_utils import draw_centered, fit_font, load_background, load_font, wrap_text


class QuestionRenderer:
    """渲染教室背景与正式试卷式正文卡。"""

    def __init__(self):
        self.width = CANVAS.width
        self.height = CANVAS.height

    def render(
        self,
        chinese_text: str,
        metadata: ExamMetadata,
        output_path: str,
        background_path: Optional[str] = None,
    ) -> Optional[str]:
        try:
            image = load_background(background_path, ASSET_QUESTION_BG, (self.width, self.height), "#D7D3CB")
            image = ImageEnhance.Brightness(image.filter(ImageFilter.GaussianBlur(QUESTION.background_blur))).enhance(0.93)
            image = image.convert("RGBA")

            layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
            draw = ImageDraw.Draw(layer)
            draw.rounded_rectangle(QUESTION.card, radius=QUESTION.radius, fill=(250, 250, 248, 252))

            title_font = fit_font(draw, metadata.exam_full_title, 820, range(48, 39, -1), "bold")
            draw_centered(draw, metadata.exam_full_title, 438, title_font, COLORS.ink, self.width)
            section_title = f"{metadata.section_cn}  第{metadata.exam_set_number}套"
            section_font = fit_font(draw, section_title, 820, range(50, 41, -1), "bold")
            draw_centered(draw, section_title, 520, section_font, COLORS.ink, self.width)

            center_x = self.width // 2
            center_half = 45
            line_y = QUESTION.divider_y
            draw.line((QUESTION.content_left, line_y, center_x - center_half - 12, line_y), fill=COLORS.hairline, width=3)
            draw.rounded_rectangle((center_x - center_half, line_y - 4, center_x + center_half, line_y + 4), radius=3, fill=COLORS.center_bar)
            draw.line((center_x + center_half + 12, line_y, QUESTION.content_right, line_y), fill=COLORS.hairline, width=3)

            draw.text((QUESTION.content_left, 682), "请将下面这段中文翻译成英语。", font=load_font(35), fill=COLORS.ink)
            self._draw_body(draw, chinese_text, start_y=790, bottom=1365)

            final = Image.alpha_composite(image, layer).convert("RGB")
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            final.save(output_path, quality=96)
            return output_path
        except Exception as exc:
            print(f"渲染题板失败: {exc}")
            return None

    def _draw_body(self, draw: ImageDraw.ImageDraw, text: str, start_y: int, bottom: int) -> None:
        cleaned = " ".join(text.replace("\n", " ").split())
        max_width = QUESTION.content_right - QUESTION.content_left
        chosen = None
        for size in range(37, 28, -1):
            font = load_font(size)
            lines = wrap_text(draw, "　　" + cleaned, font, max_width)
            line_height = max(54, size + 27)
            if start_y + len(lines) * line_height <= bottom:
                chosen = (font, lines, line_height)
                break
        if chosen is None:
            font = load_font(28)
            chosen = (font, wrap_text(draw, "　　" + cleaned, font, max_width), 52)

        font, lines, line_height = chosen
        y = start_y
        for line in lines:
            if y + line_height > bottom:
                raise ValueError("中文原文过长，缩小到最小字号后仍无法放入题板")
            draw.text((QUESTION.content_left, y), line, font=font, fill=COLORS.ink)
            y += line_height
