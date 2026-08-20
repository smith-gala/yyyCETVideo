from pydantic import BaseModel, ConfigDict

from app.ui.video_generator import _build_subtitle_timeline


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
