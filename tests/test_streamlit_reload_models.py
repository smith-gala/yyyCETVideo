from pydantic import BaseModel, ConfigDict

from app.models import ExamPaper, SubtitleSegment
from app.services.subtitle_service import SUBTITLE_PIPELINE_VERSION
from app.ui.video_generator import _build_subtitle_timeline, _resolve_existing_body_audio


def test_subtitle_timeline_crosses_hot_reload_boundary_as_plain_data():
    class CachedSubtitleSegment(BaseModel):
        start: float
        end: float
        english: str
        chinese: str

    class CachedExamPaper(BaseModel):
        model_config = ConfigDict(validate_assignment=True)
        subtitle_segments: list[CachedSubtitleSegment]

    cached_paper = CachedExamPaper(subtitle_segments=[])
    timeline = _build_subtitle_timeline(
        [{"english": "Hybrid rice", "chinese": "杂交水稻"}],
        [1.25],
    )

    assert isinstance(timeline[0], dict)
    cached_paper.subtitle_segments = timeline
    assert isinstance(cached_paper.subtitle_segments[0], CachedSubtitleSegment)
    assert cached_paper.subtitle_segments[0].end == 1.25


def test_existing_body_audio_is_recovered_after_session_state_is_lost(tmp_path):
    audio_path = tmp_path / "english_audio_CET-4_2026_6_1.wav"
    audio_path.write_bytes(b"existing audio")
    paper = ExamPaper(
        exam_type="CET-4",
        year=2026,
        month=6,
        set_number=1,
        chinese_text="餐桌礼仪(dining etiquette)是传统文化的一部分。",
        english_text="Dining etiquette is part of traditional culture.",
        subtitle_pipeline_version=SUBTITLE_PIPELINE_VERSION,
        subtitle_segments=[
            SubtitleSegment(
                start=0,
                end=2,
                english="Dining etiquette is part",
                chinese="餐桌礼仪是传统文化",
            ),
            SubtitleSegment(
                start=2,
                end=3,
                english="of traditional culture.",
                chinese="的一部分。",
            ),
        ],
    )

    recovered = _resolve_existing_body_audio(
        paper,
        paper.chinese_text,
        paper.english_text,
        None,
        audio_path,
    )

    assert recovered == str(audio_path)


def test_existing_body_audio_is_not_reused_after_translation_changes(tmp_path):
    audio_path = tmp_path / "existing.wav"
    audio_path.write_bytes(b"existing audio")
    paper = ExamPaper(
        exam_type="CET-4",
        year=2026,
        month=6,
        set_number=1,
        chinese_text="餐桌礼仪是传统文化的一部分。",
        english_text="Dining etiquette is part of traditional culture.",
        subtitle_pipeline_version=SUBTITLE_PIPELINE_VERSION,
        subtitle_segments=[
            SubtitleSegment(
                start=0,
                end=3,
                english="Dining etiquette is part of traditional culture.",
                chinese="餐桌礼仪是传统文化的一部分。",
            )
        ],
    )

    assert _resolve_existing_body_audio(
        paper,
        paper.chinese_text,
        "This translation has been edited.",
        audio_path,
    ) is None
