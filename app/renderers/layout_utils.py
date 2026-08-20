"""Pillow 渲染共享工具：字体、等比覆盖裁切、文本测量和磨砂卡片。"""
from pathlib import Path
import re
from typing import Iterable, Optional

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from app.config import ASSETS_DIR


PROJECT_FONT_DIR = ASSETS_DIR / "fonts"
FONT_CANDIDATES = {
    "regular": [
        PROJECT_FONT_DIR / "NotoSansSC-Regular.ttf",
        Path("C:/Windows/Fonts/NotoSansSC-VF.ttf"),
        Path("C:/Windows/Fonts/msyh.ttc"),
    ],
    "bold": [
        PROJECT_FONT_DIR / "NotoSansSC-Bold.ttf",
        Path("C:/Windows/Fonts/NotoSansSC-VF.ttf"),
        Path("C:/Windows/Fonts/msyhbd.ttc"),
    ],
}
ENGLISH_FONT_CANDIDATES = {
    "regular": [
        PROJECT_FONT_DIR / "DINNextLTPro-Regular.ttf",
        Path("C:/Windows/Fonts/DINNextLTPro-Regular.ttf"),
        Path("C:/Windows/Fonts/ARIALN.TTF"),
        Path("C:/Windows/Fonts/arial.ttf"),
    ],
    "bold": [
        PROJECT_FONT_DIR / "DINNextLTPro-Bold.ttf",
        Path("C:/Windows/Fonts/DINNextLTPro-Bold.ttf"),
        Path("C:/Windows/Fonts/ARIALNB.TTF"),
        Path("C:/Windows/Fonts/arialbd.ttf"),
    ],
}


def font_path(weight: str = "regular") -> Optional[str]:
    for candidate in FONT_CANDIDATES["bold" if weight == "bold" else "regular"]:
        if candidate.exists():
            return str(candidate)
    return None


def load_font(size: int, weight: str = "regular") -> ImageFont.FreeTypeFont:
    path = font_path(weight)
    if path:
        font = ImageFont.truetype(path, size)
        if Path(path).name.lower() == "notosanssc-vf.ttf":
            font.set_variation_by_axes([700 if weight == "bold" else 400])
        return font
    return ImageFont.load_default()


def load_english_font(size: int, weight: str = "regular") -> ImageFont.FreeTypeFont:
    """加载重点表达页使用的窄体 DIN 英文字体。"""
    for candidate in ENGLISH_FONT_CANDIDATES["bold" if weight == "bold" else "regular"]:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size)
    return load_font(size, weight)


def cover_crop(image: Image.Image, width: int, height: int) -> Image.Image:
    """保持宽高比缩放至完整覆盖目标画布，再做中心裁切。"""
    image = image.convert("RGB")
    scale = max(width / image.width, height / image.height)
    new_size = (max(width, round(image.width * scale)), max(height, round(image.height * scale)))
    resized = image.resize(new_size, Image.Resampling.LANCZOS)
    left = (resized.width - width) // 2
    top = (resized.height - height) // 2
    return resized.crop((left, top, left + width, top + height))


def load_background(path: Optional[Path | str], fallback: Path, size: tuple[int, int], color: str) -> Image.Image:
    source = Path(path) if path else fallback
    if source.exists():
        with Image.open(source) as opened:
            return cover_crop(opened, *size)
    return Image.new("RGB", size, color)


def text_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> int:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0]


def draw_centered(
    draw: ImageDraw.ImageDraw,
    text: str,
    y: int,
    font,
    fill,
    canvas_width: int = 1080,
    stroke_width: int = 0,
    stroke_fill=None,
) -> None:
    bbox = draw.textbbox((0, 0), text, font=font, stroke_width=stroke_width)
    x = (canvas_width - (bbox[2] - bbox[0])) // 2 - bbox[0]
    draw.text(
        (x, y - bbox[1]),
        text,
        font=font,
        fill=fill,
        stroke_width=stroke_width,
        stroke_fill=stroke_fill,
    )


def fit_font(draw: ImageDraw.ImageDraw, text: str, max_width: int, sizes: Iterable[int], weight: str = "regular"):
    sizes = list(sizes)
    for size in sizes:
        current = load_font(size, weight)
        if text_width(draw, text, current) <= max_width:
            return current
    return load_font(sizes[-1], weight)


def fit_english_font(
    draw: ImageDraw.ImageDraw,
    text: str,
    max_width: int,
    sizes: Iterable[int],
    weight: str = "regular",
):
    sizes = list(sizes)
    for size in sizes:
        current = load_english_font(size, weight)
        if text_width(draw, text, current) <= max_width:
            return current
    return load_english_font(sizes[-1], weight)


def wrap_text(draw: ImageDraw.ImageDraw, text: str, font, max_width: int, prefer_words: bool = False) -> list[str]:
    if prefer_words:
        text = " ".join(text.split())
    else:
        text = re.sub(r"\s*[\r\n]+\s*", "", text)
        text = re.sub(r"[\t ]+", " ", text).strip()
    if not text:
        return [""]
    units = text.split(" ") if prefer_words else list(text)
    separator = " " if prefer_words else ""
    lines: list[str] = []
    current = ""
    for unit in units:
        candidate = f"{current}{separator if current else ''}{unit}"
        if text_width(draw, candidate, font) <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = unit
    if current:
        lines.append(current)
    return lines or [""]


def wrap_text_balanced(
    draw: ImageDraw.ImageDraw,
    text: str,
    font,
    max_width: int,
    prefer_words: bool = False,
) -> list[str]:
    """在最多两行能容纳时平衡行宽，避免第一行明显短于第二行。"""
    if prefer_words:
        clean = " ".join(text.split())
    else:
        clean = re.sub(r"\s*[\r\n]+\s*", "", text)
        clean = re.sub(r"[\t ]+", " ", clean).strip()
    if not clean or text_width(draw, clean, font) <= max_width:
        return [clean]

    units = clean.split() if prefer_words else list(clean)
    separator = " " if prefer_words else ""
    candidates = []
    for index in range(1, len(units)):
        first = separator.join(units[:index]).strip()
        second = separator.join(units[index:]).strip()
        first_width = text_width(draw, first, font)
        second_width = text_width(draw, second, font)
        if first_width > max_width or second_width > max_width:
            continue

        natural = 0.0
        if first.rstrip().endswith((".", "!", "?", ";", ":", ",", "。", "！", "？", "；", "：", "，", "、")):
            natural = 0.10
        elif prefer_words and units[index].lower().strip("\"'(") in {
            "and", "but", "or", "because", "which", "that", "who", "when", "while", "if",
        }:
            natural = 0.06

        imbalance = abs(first_width - second_width) / max_width
        # 上短下长比上长下短更显眼，给予更高惩罚。
        lower_heavy = max(0, second_width - first_width) / max_width
        candidates.append((imbalance + lower_heavy * 2.5 - natural, index, first, second))

    if candidates:
        _, _, first, second = min(candidates, key=lambda item: (item[0], item[1]))
        return [first, second]
    return wrap_text(draw, clean, font, max_width, prefer_words=prefer_words)


def apply_glass_panel(
    base: Image.Image,
    box: tuple[int, int, int, int],
    radius: int,
    blur: int,
    fill: tuple[int, int, int, int],
    border: Optional[tuple[int, int, int, int]] = None,
    border_width: int = 1,
    shadow_alpha: int = 22,
) -> Image.Image:
    """对卡片背后的真实图像做局部模糊，再叠加暖白半透明层。"""
    result = base.convert("RGBA")
    x1, y1, x2, y2 = box
    panel_size = (x2 - x1, y2 - y1)

    if shadow_alpha:
        shadow = Image.new("RGBA", result.size, (0, 0, 0, 0))
        ImageDraw.Draw(shadow).rounded_rectangle(
            (x1 + 1, y1 + 9, x2 + 1, y2 + 9), radius=radius, fill=(0, 0, 0, shadow_alpha)
        )
        result = Image.alpha_composite(result, shadow.filter(ImageFilter.GaussianBlur(12)))

    crop = result.crop(box).filter(ImageFilter.GaussianBlur(blur))
    mask = Image.new("L", panel_size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, *panel_size), radius=radius, fill=255)
    result.paste(crop, (x1, y1), mask)

    overlay = Image.new("RGBA", result.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=border, width=border_width)
    return Image.alpha_composite(result, overlay)
