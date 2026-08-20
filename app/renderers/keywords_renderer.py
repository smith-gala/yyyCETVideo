"""重点表达页渲染器。"""
from pathlib import Path
import re
from typing import List, Optional

from PIL import Image, ImageDraw, ImageEnhance

from app.config import ASSET_KEYWORDS_BG
from app.models import ExamMetadata, KeyExpression
from app.renderers.design_tokens import CANVAS, COLORS, KEYWORDS
from app.renderers.layout_utils import (
    apply_glass_panel,
    draw_centered,
    fit_english_font,
    load_background,
    load_english_font,
    load_font,
    text_width,
    wrap_text,
)


class KeywordsRenderer:
    """渲染明亮真实背景、磨砂玻璃大卡与最多五个表达子卡。"""

    def __init__(self):
        self.width = CANVAS.width
        self.height = CANVAS.height

    def render(
        self,
        key_expressions: List[KeyExpression],
        metadata: ExamMetadata,
        output_path: str,
        background_path: Optional[str] = None,
    ) -> Optional[str]:
        try:
            image = load_background(background_path, ASSET_KEYWORDS_BG, (self.width, self.height), "#D8C7B2")
            image = ImageEnhance.Brightness(image).enhance(1.08).convert("RGBA")
            warm_light = Image.new("RGBA", image.size, (0, 0, 0, 0))
            light_draw = ImageDraw.Draw(warm_light)
            for y in range(self.height):
                alpha = 25 if y >= 520 else round(25 + 185 * (1 - y / 520))
                light_draw.line((0, y, self.width, y), fill=(255, 250, 242, alpha), width=1)
            image = Image.alpha_composite(image, warm_light)
            image = apply_glass_panel(
                image, KEYWORDS.outer, KEYWORDS.outer_radius, KEYWORDS.glass_blur,
                COLORS.glass_fill, COLORS.glass_border, 2,
            )
            draw = ImageDraw.Draw(image)

            draw_centered(draw, "WORDS TO REMEMBER", 130, load_english_font(32), COLORS.ink, self.width)
            draw_centered(draw, "本题重点表达", 184, load_font(56, "bold"), "#050505", self.width)
            draw.rounded_rectangle((505, 274, 575, 281), radius=4, fill=COLORS.wine)
            draw_centered(
                draw,
                f"{metadata.exam_level} · {metadata.section_en}",
                382,
                load_english_font(32),
                COLORS.ink,
                self.width,
            )

            for index, expression in enumerate(key_expressions[:5], start=1):
                y = KEYWORDS.row_start_y + (index - 1) * (KEYWORDS.row_height + KEYWORDS.row_gap)
                self._draw_row(draw, expression, index, y)

            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            image.convert("RGB").save(output_path, quality=96)
            return output_path
        except Exception as exc:
            print(f"渲染重点表达页失败: {exc}")
            return None

    def _draw_row(self, draw: ImageDraw.ImageDraw, expr: KeyExpression, index: int, y: int) -> None:
        x = KEYWORDS.row_x
        x2 = x + KEYWORDS.row_width
        y2 = y + KEYWORDS.row_height
        draw.rounded_rectangle((x, y, x2, y2), radius=18, fill=(255, 252, 247, 188), outline=(214, 210, 204, 180), width=1)
        draw.text((x + 27, y + 55), f"{index:02d}", font=load_english_font(49, "bold"), fill=COLORS.wine_dark)
        divider_x = x + 132
        draw.rectangle((divider_x, y + 43, divider_x + 2, y + 139), fill="#8A2628")

        content_x = divider_x + 34
        content_width = x2 - content_x - 26
        word = expr.word.strip()
        meaning = expr.meaning.strip()
        main_size = self._single_line_main_size(draw, word, meaning, content_width)
        if main_size is not None:
            english_font = load_english_font(main_size, "bold")
            chinese_font = load_font(main_size, "bold")
            draw.text((content_x, y + 31), word, font=english_font, fill="#050505")
            word_width = draw.textlength(word + "  ", font=english_font)
            draw.text((round(content_x + word_width), y + 31), meaning, font=chinese_font, fill="#050505")
            example_y = y + 101
        else:
            english_font = fit_english_font(draw, word, content_width, [34, 32, 30, 28], "bold")
            chinese_font = load_font(getattr(english_font, "size", 28), "bold")
            english_lines = wrap_text(draw, word, english_font, content_width, prefer_words=True)
            if len(english_lines) > 1 or text_width(draw, meaning, chinese_font) > content_width:
                raise ValueError(f"重点表达过长，最小字号仍超过两行: {word}  {meaning}")
            draw.text((content_x, y + 18), english_lines[0], font=english_font, fill="#050505")
            draw.text((content_x, y + 57), meaning, font=chinese_font, fill="#050505")
            example_y = y + 105

        example_font = fit_english_font(draw, expr.example.strip(), content_width, [31, 29, 27, 25])
        example_lines = wrap_text(draw, expr.example.strip(), example_font, content_width, prefer_words=True)
        if len(example_lines) > 2:
            raise ValueError(f"重点表达例句过长，最小字号仍超过两行: {expr.example}")
        line_step = max(31, getattr(example_font, "size", 26) + 5)
        for offset, line in enumerate(example_lines):
            self._draw_highlighted_example(
                draw,
                line,
                expr.word,
                content_x,
                example_y + offset * line_step,
                example_font,
            )

    @staticmethod
    def _draw_highlighted_example(draw, text: str, key_expression: str, x: int, y: int, font) -> None:
        """例句保持原有排版，仅将其中的目标表达改为橙红色。"""
        ranges = _highlight_ranges(text, key_expression)
        if not ranges:
            draw.text((x, y), text, font=font, fill="#222222")
            return

        cursor = 0
        current_x = float(x)
        for start, end in ranges:
            before = text[cursor:start]
            if before:
                draw.text((round(current_x), y), before, font=font, fill="#222222")
                current_x += draw.textlength(before, font=font)
            highlighted = text[start:end]
            draw.text((round(current_x), y), highlighted, font=font, fill=COLORS.highlight_orange)
            current_x += draw.textlength(highlighted, font=font)
            cursor = end

        remainder = text[cursor:]
        if remainder:
            draw.text((round(current_x), y), remainder, font=font, fill="#222222")

    @staticmethod
    def _single_line_main_size(draw, word: str, meaning: str, max_width: int) -> Optional[int]:
        for size in [42, 40, 38, 36, 34]:
            english_font = load_english_font(size, "bold")
            chinese_font = load_font(size, "bold")
            width = draw.textlength(word + "  ", font=english_font) + draw.textlength(meaning, font=chinese_font)
            if width <= max_width:
                return size
        return None


def _highlight_ranges(text: str, key_expression: str) -> list[tuple[int, int]]:
    """优先高亮完整短语；短语被换行或例句插入修饰词时，回退到关键单词。"""
    phrase = " ".join(str(key_expression).split()).strip()
    if not text or not phrase:
        return []

    exact_pattern = rf"(?<![A-Za-z0-9]){re.escape(phrase)}(?![A-Za-z0-9])"
    exact_matches = list(re.finditer(exact_pattern, text, flags=re.IGNORECASE))
    if exact_matches:
        return [(match.start(), match.end()) for match in exact_matches]

    key_words = {
        match.group(0).casefold()
        for match in re.finditer(r"[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)*", phrase)
    }
    if not key_words:
        return []
    return [
        (match.start(), match.end())
        for match in re.finditer(r"[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)*", text)
        if match.group(0).casefold() in key_words
    ]
