from pathlib import Path

import numpy as np
from PIL import Image

from app.models import ExamMetadata, ExamPaper
from app.services.subtitle_service import (
    english_word_count,
    normalize_bilingual_segments,
    normalize_source_text,
    realign_bilingual_segments,
)
from app.config import (
    BODY_SENTENCE_GAP_SECONDS,
    COVER_DURATION_SECONDS,
    OPENING_SECTION_SET_GAP_SECONDS,
    OPENING_SENTENCE_GAP_SECONDS,
)


def test_metadata_comes_from_exam_paper_and_changes_all_source_fields():
    paper = ExamPaper(
        exam_type="CET-4", year=2024, month=12, set_number=2,
        chinese_text="测试正文", topic_cn="一个不同的测试主题",
    )
    metadata = ExamMetadata.from_paper(paper)
    assert metadata.exam_session == "2024年12月"
    assert metadata.exam_set_number == 2
    assert metadata.exam_full_title == "2024年12月全国大学生英语四级考试"
    assert metadata.cover_title == "2024年12月四级写译真题"
    assert metadata.cover_subtitle == "汉译英 ｜ 一个不同的测试主题"
    assert "2026" not in metadata.model_dump_json()
    assert "餐桌礼仪" not in metadata.model_dump_json()


def test_cet6_metadata_is_supported():
    paper = ExamPaper(exam_type="CET-6", year=2023, month=6, set_number=1, chinese_text="正文", topic_cn="城市交通")
    metadata = ExamMetadata.from_paper(paper)
    assert metadata.exam_level_cn == "六级"
    assert "六级" in metadata.exam_full_title


def test_publish_copy_uses_fixed_format_and_dedicated_publish_topic():
    paper = ExamPaper(
        exam_type="CET-4",
        year=2025,
        month=6,
        set_number=1,
        chinese_text="正文",
        topic_cn="杂交水稻",
        topic_keyword="杂交水稻",
        publish_topic="袁隆平--杂交水稻",
    )
    assert paper.publish_copy == "2025年四级第一套 | 袁隆平--杂交水稻"


def test_publish_copy_supports_cet6_and_legacy_topic_fallback():
    paper = ExamPaper(
        exam_type="CET-6",
        year=2024,
        month=12,
        set_number=2,
        chinese_text="正文",
        topic_cn="中国传统园林",
    )
    assert paper.publish_copy == "2024年六级第二套 | 中国传统园林"


def test_subtitle_normalizer_enforces_twenty_word_limit_without_losing_text():
    english = (
        "Yuan Longping and his research team overcame numerous challenges to develop a super hybrid rice, "
        "which has been widely adopted across many countries and contributes to global food security."
    )
    chinese = "袁隆平和他的科研团队克服重重困难，研发出超级杂交水稻，这项技术已经在许多国家得到广泛应用，并为全球粮食安全作出贡献。"
    segments = normalize_bilingual_segments([{"english": english, "chinese": chinese}])
    assert len(segments) >= 2
    assert all(english_word_count(segment["english"]) <= 20 for segment in segments)
    assert "".join(segment["chinese"] for segment in segments) == chinese
    assert " ".join(segment["english"] for segment in segments) == english


def test_renderers_contain_no_fixture_business_values():
    renderer_dir = Path(__file__).parents[1] / "app" / "renderers"
    source = "\n".join(path.read_text(encoding="utf-8") for path in renderer_dir.glob("*_renderer.py"))
    for forbidden in ("2026年6月", "餐桌礼仪", "2026年6月全国大学英语四级考试"):
        assert forbidden not in source


def test_extracted_source_line_breaks_do_not_create_word_gaps():
    source = "中国采取了一系列措施，包括推广共\n享单车，研发超\r\n级杂交水稻。"
    assert normalize_source_text(source) == "中国采取了一系列措施，包括推广共享单车，研发超级杂交水稻。"


def test_normalizer_removes_old_cjk_spacing_artifacts():
    segments = normalize_bilingual_segments([
        {"english": "super hybrid rice", "chinese": "超 级杂交水稻\n营养丰富"}
    ])
    assert segments[0]["chinese"] == "超级杂交水稻营养丰富"


def test_cover_duration_is_the_configured_point_two_seconds():
    assert COVER_DURATION_SECONDS == 0.2
    assert OPENING_SECTION_SET_GAP_SECONDS == 0.4
    assert OPENING_SENTENCE_GAP_SECONDS == 0.4
    assert BODY_SENTENCE_GAP_SECONDS == 0.3


def test_bilingual_realigner_keeps_each_language_inside_the_same_sentence():
    chinese = (
        "被誉为杂交水稻之父的袁隆平和他的科研团队克服重重困难，研发出超级杂交水稻。"
        "这项技术获得了举世公认的成功。"
    )
    raw = [
        {"english": "Yuan Longping, known as the Father of Hybrid Rice,", "chinese": "被誉为杂交水稻之父"},
        {"english": "and his team overcame many challenges to develop super hybrid rice.", "chinese": "的袁隆平和他的团队克服困难，"},
        {"english": "This technology has achieved universally recognized success.", "chinese": "研发出超级杂交水稻。这项技术获得了举世公认的成功。"},
    ]

    aligned = realign_bilingual_segments(chinese, raw)

    assert len(aligned) == 3
    assert "袁隆平" in aligned[0]["chinese"]
    assert "研发出超级杂交水稻" in aligned[1]["chinese"]
    assert aligned[1]["chinese"].endswith("。")
    assert aligned[2]["chinese"] == "这项技术获得了举世公认的成功。"
    assert "".join(item["chinese"] for item in aligned) == chinese


def test_question_clip_returns_clean_background_without_baked_subtitle(monkeypatch):
    from moviepy import AudioFileClip
    from app.config import ASSET_CLOSING_AUDIO, TEMP_DIR
    from app.pipeline.video_pipeline import VideoPipeline
    from app.services.audio_service import FishAudioService

    paper = ExamPaper(
        exam_type="CET-4",
        year=2025,
        month=6,
        set_number=3,
        chinese_text="这是一段用于验证干净题板的中文内容。",
        topic_cn="测试主题",
    )
    source_audio = AudioFileClip(str(ASSET_CLOSING_AUDIO))
    duration = source_audio.duration
    source_audio.close()
    monkeypatch.setattr(
        FishAudioService,
        "generate_opening_audio",
        lambda self, metadata: (
            str(ASSET_CLOSING_AUDIO),
            [("这是测试字幕。", "This is a test subtitle.")],
            [duration],
        ),
    )

    pipeline = VideoPipeline()
    clip, clean_frame = pipeline._create_question_clip(paper, ExamMetadata.from_paper(paper))
    try:
        rendered = np.array(Image.open(TEMP_DIR / f"question_{paper.paper_id}.png").convert("RGB"))
        composited = clip.get_frame(0).astype(np.uint8)
        assert np.array_equal(clean_frame, rendered)
        assert not np.array_equal(composited, clean_frame)
    finally:
        clip.close()
