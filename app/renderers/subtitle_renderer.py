"""正文朗读字幕卡渲染器。"""
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw

from app.config import ASSET_COVER_BG
from app.renderers.design_tokens import CANVAS, COLORS, SUBTITLE
from app.renderers.layout_utils import draw_centered, load_background, load_font, wrap_text


class SubtitleRenderer:
    """生成固定字号、透明背景且按安全区自然换行的双语字幕。"""

    def render_card(self, english: str, chinese: str, chinese_top: bool = False) -> Image.Image:
        dummy = Image.new("RGBA", (SUBTITLE.width, 600), (0, 0, 0, 0))
        measure = ImageDraw.Draw(dummy)
        en_font = load_font(SUBTITLE.english_font_size, "bold")
        zh_font = load_font(SUBTITLE.chinese_font_size, "regular")
        max_width = SUBTITLE.width - SUBTITLE.padding_x * 2
        # 贪心换行会先尽量占满第一行；短句保持一行，长句可自然增加行数。
        en_lines = wrap_text(measure, english.strip(), en_font, max_width, prefer_words=True)
        zh_lines = wrap_text(measure, chinese.strip(), zh_font, max_width, prefer_words=False)

        first_lines, second_lines = (zh_lines, en_lines) if chinese_top else (en_lines, zh_lines)
        first_font, second_font = (zh_font, en_font) if chinese_top else (en_font, zh_font)
        first_step = first_font.size + 12
        second_step = second_font.size + 11
        content_height = len(first_lines) * first_step + SUBTITLE.gap + len(second_lines) * second_step
        height = SUBTITLE.padding_y * 2 + content_height

        image = Image.new("RGBA", (SUBTITLE.width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)

        y = SUBTITLE.padding_y
        for line in first_lines:
            self._draw_subtitle_line(draw, line, y, first_font)
            y += first_step
        y += SUBTITLE.gap
        for line in second_lines:
            self._draw_subtitle_line(draw, line, y, second_font)
            y += second_step
        return image

    @staticmethod
    def _draw_subtitle_line(draw, text: str, y: int, font) -> None:
        # 与“听力磨耳朵”一致：白字、深色描边和轻微阴影，不绘制字幕底板。
        draw_centered(
            draw,
            text,
            y + SUBTITLE.shadow,
            font,
            COLORS.subtitle_shadow,
            SUBTITLE.width,
            stroke_width=SUBTITLE.outline,
            stroke_fill=COLORS.subtitle_shadow,
        )
        draw_centered(
            draw,
            text,
            y,
            font,
            COLORS.subtitle_text,
            SUBTITLE.width,
            stroke_width=SUBTITLE.outline,
            stroke_fill=COLORS.subtitle_outline,
        )

    def render_preview(
        self,
        output_path: str,
        english: str,
        chinese: str,
        background_path: Optional[str] = None,
    ) -> str:
        background = load_background(
            background_path,
            ASSET_COVER_BG,
            (CANVAS.width, CANVAS.height),
            "#786D61",
        ).convert("RGBA")
        card = self.render_card(english, chinese)
        card_y = SUBTITLE.position_y(CANVAS.height, card.height, "portrait")
        background.alpha_composite(card, (SUBTITLE.x, card_y))
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        background.convert("RGB").save(output_path, quality=96)
        return output_path
