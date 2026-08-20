"""CET 竖屏视频的统一视觉令牌。"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Canvas:
    width: int = 1080
    height: int = 1920


@dataclass(frozen=True)
class Colors:
    ink: str = "#111111"
    ink_soft: str = "#444444"
    muted: str = "#555555"
    wine: str = "#7A1118"
    wine_dark: str = "#64161A"
    highlight_orange: str = "#D54A24"
    warm_white: tuple = (252, 252, 250, 250)
    glass_fill: tuple = (255, 250, 243, 150)
    glass_border: tuple = (255, 255, 255, 210)
    hairline: str = "#A7AAAC"
    center_bar: str = "#676E78"
    subtitle_text: tuple = (255, 255, 255, 255)
    subtitle_outline: tuple = (16, 16, 16, 255)
    subtitle_shadow: tuple = (0, 0, 0, 128)


@dataclass(frozen=True)
class CoverLayout:
    card: tuple = (46, 640, 1034, 1142)
    radius: int = 50
    kicker_y: int = 735
    title_y: int = 846
    subtitle_y: int = 1000
    background_blur: int = 3
    dark_overlay_alpha: int = 62


@dataclass(frozen=True)
class QuestionLayout:
    card: tuple = (71, 258, 1009, 1433)
    radius: int = 42
    content_left: int = 138
    content_right: int = 942
    divider_y: int = 625
    background_blur: int = 10


@dataclass(frozen=True)
class KeywordsLayout:
    outer: tuple = (86, 320, 994, 1590)
    outer_radius: int = 48
    glass_blur: int = 21
    row_x: int = 140
    row_width: int = 800
    row_height: int = 181
    row_gap: int = 24
    row_start_y: int = 482


@dataclass(frozen=True)
class SubtitleLayout:
    # 参考“听力磨耳朵”：保持固定字号，只在越过左右 30px 安全区时换行。
    x: int = 30
    width: int = 1020
    bottom: int = 110
    padding_x: int = 3
    padding_y: int = 30
    gap: int = 16
    outline: int = 3
    shadow: int = 2
    english_font_size: int = 43
    chinese_font_size: int = 37
    portrait_center_ratio: float = 0.5

    def position_y(self, canvas_height: int, content_height: int, orientation: str) -> int:
        """竖屏字幕居中于画面中部；横屏素材的字幕使用常规底部位置。"""
        if orientation == "portrait":
            return max(0, round(canvas_height * self.portrait_center_ratio - content_height / 2))
        return max(0, canvas_height - self.bottom - content_height)


CANVAS = Canvas()
COLORS = Colors()
COVER = CoverLayout()
QUESTION = QuestionLayout()
KEYWORDS = KeywordsLayout()
SUBTITLE = SubtitleLayout()
