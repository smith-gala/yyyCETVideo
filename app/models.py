"""
数据模型定义
"""
from typing import Optional, List
from pydantic import BaseModel, ConfigDict, Field, field_validator
from datetime import datetime

from app.services.subtitle_service import normalize_source_text


class KeyExpression(BaseModel):
    """重点表达"""
    word: str = Field(..., description="英文词汇或短语")
    meaning: str = Field(..., description="中文释义")
    example: str = Field(..., description="英文例句或搭配")


class SubtitleSegment(BaseModel):
    """字幕片段"""
    start: float = Field(0, description="开始时间")
    end: float = Field(0, description="结束时间")
    english: str = Field("", description="英文字幕")
    chinese: str = Field("", description="中文字幕")


class TranslationUnit(BaseModel):
    """持久化的中英语义单元，不包含音频时间轴。"""
    english: str = Field("", description="完整英文语义单元")
    chinese: str = Field("", description="对应中文语义单元")


class ExamMetadata(BaseModel):
    """渲染层唯一使用的考试来源与展示元数据。"""

    exam_level: str
    exam_level_cn: str
    exam_year: int
    exam_month: int
    exam_set_number: int = 1
    exam_session: str
    exam_full_title: str
    section_cn: str = "翻译部分"
    section_en: str = "TRANSLATION"
    topic_cn: str
    topic_en: Optional[str] = None

    @classmethod
    def from_paper(cls, paper: "ExamPaper") -> "ExamMetadata":
        level = paper.exam_type.strip().upper()
        level_map = {"CET-4": "四级", "CET-6": "六级"}
        if level not in level_map:
            raise ValueError(f"不支持的考试等级: {paper.exam_type}")

        topic = (paper.topic_cn or paper.topic_keyword or "").strip()
        if not topic:
            raise ValueError("当前真题缺少已确认主题，请先在业务页面填写并保存主题。")

        level_cn = level_map[level]
        session = f"{paper.year}年{paper.month}月"
        return cls(
            exam_level=level,
            exam_level_cn=level_cn,
            exam_year=paper.year,
            exam_month=paper.month,
            exam_set_number=paper.set_number,
            exam_session=session,
            exam_full_title=f"{session}全国大学生英语{level_cn}考试",
            topic_cn=topic,
            topic_en=(paper.topic_en or "").strip() or None,
        )

    @property
    def cover_kicker(self) -> str:
        return f"{self.exam_level} ｜ {self.exam_level_cn}真题 ｜ 汉译英"

    @property
    def cover_title(self) -> str:
        return f"{self.exam_session}{self.exam_level_cn}写译真题"

    @property
    def cover_subtitle(self) -> str:
        return f"汉译英 ｜ {self.topic_cn}"


class PexelsAsset(BaseModel):
    """Pexels素材"""
    asset_id: str
    kind: str = Field(..., description="photo 或 video")
    title: str = ""
    author: str = ""
    preview_url: str = ""
    download_url: str = ""
    pexels_url: str = ""
    orientation: str = Field("portrait", description="portrait 或 landscape")
    width: int = 0
    height: int = 0
    duration: float = 0
    fps: float = 0
    local_path: Optional[str] = None


class ExamPaper(BaseModel):
    """试卷模型"""
    model_config = ConfigDict(validate_assignment=True)

    exam_type: str = Field(..., description="考试类型: CET-4 或 CET-6")
    year: int = Field(..., description="年份")
    month: int = Field(..., description="月份: 6 或 12")
    set_number: int = Field(..., description="套数: 1, 2, 3")
    chinese_text: str = Field(..., description="中文原文")
    english_text: Optional[str] = Field(None, description="英文翻译")
    topic_cn: Optional[str] = Field(None, description="已确认的真题中文主题（展示用）")
    topic_en: Optional[str] = Field(None, description="已确认的真题英文主题（可选）")
    topic_keyword: Optional[str] = Field(None, description="背景素材搜索关键词（兼容旧缓存）")
    publish_topic: Optional[str] = Field(None, description="短视频发布文案主题，如“袁隆平--杂交水稻”")
    key_expressions: Optional[List[KeyExpression]] = Field(default_factory=list, description="重点表达列表")
    translation_units: Optional[List[TranslationUnit]] = Field(default_factory=list, description="正文中英语义单元")
    subtitle_segments: Optional[List[SubtitleSegment]] = Field(default_factory=list, description="正文中英字幕时间轴")
    subtitle_pipeline_version: int = Field(1, description="正文语音与字幕管线版本")
    pdf_path: Optional[str] = Field(None, description="PDF文件路径")
    created_at: datetime = Field(default_factory=datetime.now)

    @field_validator("chinese_text", mode="before")
    @classmethod
    def clean_chinese_text(cls, value: str) -> str:
        return normalize_source_text(value)

    @property
    def paper_id(self) -> str:
        """生成试卷唯一ID"""
        return f"{self.exam_type}_{self.year}_{self.month}_{self.set_number}"

    @property
    def display_name(self) -> str:
        """显示名称"""
        return f"{self.year}年{self.month}月 {self.exam_type} 第{self.set_number}套"

    @property
    def publish_copy(self) -> str:
        """生成视频完成后可直接复制的固定发布文案。"""
        level_cn = {"CET-4": "四级", "CET-6": "六级"}.get(
            self.exam_type.strip().upper(),
            self.exam_type.strip(),
        )
        set_cn = {1: "一", 2: "二", 3: "三"}.get(self.set_number, str(self.set_number))
        topic = (self.publish_topic or self.topic_cn or self.topic_keyword or "").strip()
        prefix = f"{self.year}年{level_cn}第{set_cn}套"
        return f"{prefix} | {topic}" if topic else prefix

    @property
    def metadata(self) -> ExamMetadata:
        return ExamMetadata.from_paper(self)


class VideoConfig(BaseModel):
    """视频生成配置"""
    paper: ExamPaper
    background_type: str = Field("image", description="背景类型: image 或 video")
    background_orientation: str = Field("portrait", description="背景方向: portrait 或 landscape")
    background_path: str = Field(..., description="背景素材路径")
    background_paths: List[str] = Field(default_factory=list, description="背景素材路径列表")
    background_min_clip_duration: float = Field(4.0, description="背景素材最短展示时长")
    background_target_clip_duration: float = Field(7.0, description="背景素材目标展示时长")
    background_max_clip_duration: float = Field(10.0, description="背景素材最长展示时长")
    background_cut_sensitivity: str = Field("standard", description="背景素材语义切换敏感度")
    audio_path: Optional[str] = Field(None, description="英文朗读音频路径")
    cover_enabled: bool = Field(True, description="是否添加封面")
    cover_path: Optional[str] = Field(None, description="封面背景路径")
    cover_title: Optional[str] = Field(None, description="封面主标题")
    cover_subtitle: Optional[str] = Field(None, description="封面副标题")
    keywords_bg_path: Optional[str] = Field(None, description="重点表达背景路径")
    subtitle_segments: Optional[List[SubtitleSegment]] = Field(default_factory=list, description="正文字幕时间轴")
    output_path: Optional[str] = Field(None, description="输出视频路径")
