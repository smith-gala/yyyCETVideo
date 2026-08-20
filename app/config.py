"""
配置管理模块
"""
import os
from pathlib import Path
from dotenv import load_dotenv


# 加载环境变量
load_dotenv()

# 项目根目录
ROOT_DIR = Path(__file__).parent.parent.absolute()

# 数据目录
DATA_DIR = ROOT_DIR / "data"
ASSETS_DIR = DATA_DIR / "assets"
COVER_ASSETS_DIR = ASSETS_DIR / "cover"
QUESTION_ASSETS_DIR = ASSETS_DIR / "question"
KEYWORDS_ASSETS_DIR = ASSETS_DIR / "keywords"
AUDIO_ASSETS_DIR = ASSETS_DIR / "audio"
SFX_ASSETS_DIR = ASSETS_DIR / "sfx"
BACKGROUNDS_DIR = DATA_DIR / "backgrounds"
PEXELS_PHOTOS_DIR = BACKGROUNDS_DIR / "pexels" / "photos"
PEXELS_VIDEOS_DIR = BACKGROUNDS_DIR / "pexels" / "videos"
CACHE_DIR = DATA_DIR / "cache"
AUDIO_CACHE_DIR = CACHE_DIR / "audio"
PDFS_DIR = DATA_DIR / "pdfs"
OUTPUT_DIR = DATA_DIR / "output"
TEMP_DIR = DATA_DIR / "temp"

# 日志目录
LOGS_DIR = ROOT_DIR / "logs"

# 确保所有目录存在
for dir_path in [
    CACHE_DIR, AUDIO_CACHE_DIR, PDFS_DIR, OUTPUT_DIR, TEMP_DIR, LOGS_DIR,
    COVER_ASSETS_DIR, QUESTION_ASSETS_DIR, KEYWORDS_ASSETS_DIR,
    AUDIO_ASSETS_DIR, SFX_ASSETS_DIR, PEXELS_PHOTOS_DIR, PEXELS_VIDEOS_DIR,
]:
    dir_path.mkdir(parents=True, exist_ok=True)

# 素材文件路径
ASSET_OPENING_AUDIO = AUDIO_ASSETS_DIR / "opening.mp3"
ASSET_ENDING_EXAM_AUDIO = AUDIO_ASSETS_DIR / "exam_end.mp3"
ASSET_CLOSING_AUDIO = AUDIO_ASSETS_DIR / "closing.mp3"
ASSET_FIXED_AUDIO_SUBTITLES = AUDIO_ASSETS_DIR / "subtitles.json"
ASSET_QUESTION_BG = QUESTION_ASSETS_DIR / "question_bg.png"
# 重点表达默认沿用明亮餐桌实拍图；用户仍可在 UI 中单独替换。
ASSET_KEYWORDS_BG = COVER_ASSETS_DIR / "default_cover.jpg"
ASSET_COVER_BG = COVER_ASSETS_DIR / "default_cover.jpg"
ASSET_COUNTDOWN_SFX = SFX_ASSETS_DIR / "countdown_beep.wav"
ASSET_DINGDONG_SFX = SFX_ASSETS_DIR / "dingdong.wav"

# Fish Audio配置
FISH_API_KEY = os.getenv("FISH_API_KEY", "")
FISH_TTS_MODEL = os.getenv("FISH_TTS_MODEL", "")
FISH_REFERENCE_ID = os.getenv("FISH_REFERENCE_ID", "")
# 开场播报使用独立音色，不能与正文英文朗读的 Reference ID 混用。
FISH_OPENING_REFERENCE_ID = os.getenv("FISH_OPENING_REFERENCE_ID", "")
FISH_CET_ZH_REFERENCE_ID = os.getenv("FISH_CET_ZH_REFERENCE_ID", "")
FISH_DAILY_EN_REFERENCE_ID = os.getenv("FISH_DAILY_EN_REFERENCE_ID", "")
FISH_DAILY_ZH_REFERENCE_ID = os.getenv("FISH_DAILY_ZH_REFERENCE_ID", "")

# Anthropic API配置
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "")
LLM_MODEL = os.getenv("LLM_MODEL", "claude-3-5-sonnet-20241022")
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "")

# 视频配置
VIDEO_WIDTH = 1080
VIDEO_HEIGHT = 1920
VIDEO_FPS = 30

# 封面在成片开头的停留时间（秒）。如需调整，直接修改此值即可。
COVER_DURATION_SECONDS = 0.2

# 开场“翻译部分”与“第 N 套”之间的停顿（秒）。
OPENING_SECTION_SET_GAP_SECONDS = 0.4

# 开场“第 N 套”与“你有3秒钟……”之间原有的停顿（秒）。
OPENING_SENTENCE_GAP_SECONDS = 0.4

# 正文英文朗读在完整句号、问号或感叹号后的停顿（秒）。
BODY_SENTENCE_GAP_SECONDS = 0.3

# 字体配置（优先使用系统中文字体）
FONT_PATHS = [
    "C:/Windows/Fonts/NotoSansSC-VF.ttf",  # 固定现代中文 Sans
    "C:/Windows/Fonts/msyh.ttc",  # 微软雅黑
    "C:/Windows/Fonts/simhei.ttf",  # 黑体
    "C:/Windows/Fonts/simsun.ttc",  # 宋体
]

def get_available_font():
    """获取可用的中文字体"""
    for font_path in FONT_PATHS:
        if os.path.exists(font_path):
            return font_path
    return None
