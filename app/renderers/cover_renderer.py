"""封面渲染器。"""
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

from app.config import ASSET_COVER_BG
from app.models import ExamMetadata
from app.renderers.design_tokens import CANVAS, COLORS, COVER
from app.renderers.layout_utils import draw_centered, fit_font, load_background


class CoverRenderer:
    """渲染真实背景与中央暖白信息卡。"""

    def __init__(self):
        self.width = CANVAS.width
        self.height = CANVAS.height

    def render(
        self,
        output_path: str,
        metadata: ExamMetadata,
        background_path: Optional[str] = None,
    ) -> Optional[str]:
        try:
            image = load_background(background_path, ASSET_COVER_BG, (self.width, self.height), "#262421")
            image = image.filter(ImageFilter.GaussianBlur(COVER.background_blur))
            image = ImageEnhance.Brightness(image).enhance(0.94).convert("RGBA")
            image = Image.alpha_composite(image, Image.new("RGBA", image.size, (0, 0, 0, COVER.dark_overlay_alpha)))

            shadow = Image.new("RGBA", image.size, (0, 0, 0, 0))
            shadow_draw = ImageDraw.Draw(shadow)
            x1, y1, x2, y2 = COVER.card
            shadow_draw.rounded_rectangle((x1, y1 + 10, x2, y2 + 10), radius=COVER.radius, fill=(0, 0, 0, 26))
            image = Image.alpha_composite(image, shadow.filter(ImageFilter.GaussianBlur(14)))

            card = Image.new("RGBA", image.size, (0, 0, 0, 0))
            draw = ImageDraw.Draw(card)
            draw.rounded_rectangle(COVER.card, radius=COVER.radius, fill=COLORS.warm_white)

            kicker_font = fit_font(draw, metadata.cover_kicker, 850, range(38, 31, -1))
            title_font = fit_font(draw, metadata.cover_title, 880, range(62, 49, -1), "bold")
            subtitle_font = fit_font(draw, metadata.cover_subtitle, 860, range(46, 35, -1), "bold")
            draw_centered(draw, metadata.cover_kicker, COVER.kicker_y, kicker_font, COLORS.muted, self.width)
            draw_centered(draw, metadata.cover_title, COVER.title_y, title_font, COLORS.wine, self.width)
            draw_centered(draw, metadata.cover_subtitle, COVER.subtitle_y, subtitle_font, COLORS.ink, self.width)

            final = Image.alpha_composite(image, card).convert("RGB")
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            final.save(output_path, quality=96)
            return output_path
        except Exception as exc:
            print(f"渲染封面失败: {exc}")
            return None
