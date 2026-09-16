import pytest
from PIL import Image, ImageDraw

from app.models import ExamPaper, SubtitleSegment, TranslationUnit
from app.renderers.design_tokens import SUBTITLE
from app.renderers.layout_utils import load_font, wrap_text
from app.renderers.subtitle_renderer import SubtitleRenderer
from app.services.audio_alignment import cue_boundaries_from_word_timestamps
from app.services.audio_service import FishAudioService
from app.services.subtitle_service import (
    SUBTITLE_PIPELINE_VERSION,
    prepare_translation_units,
    sentence_units_from_translation_units,
    split_bilingual_subtitle_cues,
    split_english_sentences,
)


def test_quoted_sentence_end_is_recognized_without_splitting_key_phrase():
    text = (
        'In recent years, an increasing number of Chinese cities have focused on building '
        '"15-minute convenient living circles." Residents can use nearby services.'
    )
    sentences = split_english_sentences(text)

    assert sentences == [
        'In recent years, an increasing number of Chinese cities have focused on building '
        '"15-minute convenient living circles."',
        "Residents can use nearby services.",
    ]
    cues = split_bilingual_subtitle_cues(sentences[0], "近年来，越来越多的中国城市着力打造15分钟便民生活圈。")
    assert any('"15-minute convenient living circles."' in cue["english"] for cue in cues)
    assert all(not cue["english"].endswith('"15-minute') for cue in cues)


def test_current_corrupted_cues_are_rebuilt_as_sentence_units_with_short_lines():
    chinese_text = (
        "近年来，中国越来越多的城市着力打造“15 分钟便民生活圈 (convenient living circles)”。"
        "社区居民步行15 分钟就能享受到日常所需的公共服务。"
        "生活圈内建有便利店、公园、健身场地、图书馆、学校、社区食堂、诊所等。"
        "生活圈的建立能够为居民提供更加便利、舒适、友好、愉悦的生活环境，"
        "更好地满足城市居民多元化的日常生活服务需求，提升居民的生活品质和幸福感。"
    )
    english_text = (
        'In recent years, an increasing number of Chinese cities have focused on building "15-minute convenient living circles." '
        "Residents can enjoy daily public services within a 15-minute walk from their homes. "
        "These circles feature convenience stores, parks, fitness venues, libraries, schools, community canteens, and clinics. "
        "The establishment of such circles offers a more convenient, comfortable, friendly, and pleasant living environment. "
        "It effectively caters to the diverse daily needs of urban residents, significantly improving their quality of life and well-being."
    )
    raw = [
        {
            "english": 'In recent years, an increasing number of Chinese cities have focused on building "15-minute',
            "chinese": "近年来，中国越来越多的城市着力打造“15 分钟便民生活",
        },
        {
            "english": 'convenient living circles." Residents can enjoy daily public services within a 15-minute walk from their homes.',
            "chinese": "圈 (convenient living circles)”。",
        },
        {
            "english": "These circles feature convenience stores, parks, fitness venues, libraries, schools, community canteens, and clinics.",
            "chinese": "社区居民步行15 分钟就能享受到日常所需的公共服务。",
        },
        {
            "english": "The establishment of such circles offers a more convenient, comfortable, friendly, and pleasant living environment.",
            "chinese": "生活圈内建有便利店、公园、健身场地、图书馆、学校、社区食堂、诊所等。",
        },
        {
            "english": "It effectively caters to the diverse daily needs of urban residents, significantly improving their quality of life and well-being.",
            "chinese": "生活圈的建立能够为居民提供更加便利、舒适、友好、愉悦的生活环境，更好地满足城市居民多元化的日常生活服务需求，提升居民的生活品质和幸福感。",
        },
    ]
    units = prepare_translation_units(chinese_text, english_text, raw)
    sentences = sentence_units_from_translation_units(units)
    cues = [
        cue
        for sentence in sentences
        for cue in split_bilingual_subtitle_cues(sentence["english"], sentence["chinese"])
    ]

    assert sentences[0]["english"].endswith('"15-minute convenient living circles."')
    assert cues[0]["chinese"] == "近年来，中国越来越多的城市"
    assert cues[1]["chinese"].startswith("着力打造")
    assert " ".join(cue["english"] for cue in cues) == english_text

    draw = ImageDraw.Draw(Image.new("RGB", (SUBTITLE.width, 300)))
    english_font = load_font(SUBTITLE.english_font_size, "bold")
    chinese_font = load_font(SUBTITLE.chinese_font_size, "regular")
    max_width = SUBTITLE.width - SUBTITLE.padding_x * 2
    assert all(len(wrap_text(draw, cue["english"], english_font, max_width, True)) <= 2 for cue in cues)
    assert all(len(wrap_text(draw, cue["chinese"], chinese_font, max_width, False)) <= 2 for cue in cues)


def test_word_timestamps_map_to_the_short_cue_boundary():
    cues = ["The city has focused on building", "convenient living circles."]
    words = [
        (0.0, 0.3, "The"), (0.3, 0.6, "city"), (0.6, 0.9, "has"),
        (0.9, 1.3, "focused"), (1.3, 1.5, "on"), (1.5, 1.9, "building"),
        (2.0, 2.6, "convenient"), (2.6, 3.0, "living"), (3.0, 3.5, "circles"),
    ]
    boundaries = cue_boundaries_from_word_timestamps(cues, words, 3.6)
    assert boundaries == [pytest.approx(1.95)]


def test_segmented_audio_requests_tts_once_per_complete_sentence(monkeypatch, tmp_path):
    service = FishAudioService(api_key="test")
    service.reference_id = "body-voice"
    requested = []
    combined = {}

    def fake_cached(text, reference_id, namespace):
        requested.append((text, namespace))
        return str(tmp_path / f"part_{len(requested)}.mp3")

    def fake_combine(paths, output_path, gaps_after):
        combined["gaps"] = gaps_after
        return [6.3, 4.0]

    def fake_cue_durations(path, cues, sentence_duration, gap):
        values = [sentence_duration / len(cues)] * len(cues)
        values[-1] += sentence_duration - sum(values)
        return values

    monkeypatch.setattr(service, "_cached_tts", fake_cached)
    monkeypatch.setattr(service, "_combine_audio_parts", fake_combine)
    monkeypatch.setattr(service, "_sentence_cue_durations", fake_cue_durations)
    units = [{
        "english": (
            'Cities have focused on building "15-minute convenient living circles." '
            "Residents can use nearby public services."
        ),
        "chinese": "城市着力打造十五分钟便民生活圈。居民可以使用附近的公共服务。",
    }]

    _, durations, cues = service.generate_segmented_audio(units, str(tmp_path / "body.wav"))

    assert [text for text, _ in requested] == [
        'Cities have focused on building "15-minute convenient living circles."',
        "Residents can use nearby public services.",
    ]
    assert all(namespace == "body_sentence_v2" for _, namespace in requested)
    assert combined["gaps"] == [0.3, 0.0]
    assert len(durations) == len(cues)


def test_segmented_audio_preserves_ai_aligned_cues(monkeypatch, tmp_path):
    service = FishAudioService(api_key="test")
    service.reference_id = "body-voice"
    units = [{
        "english": "In recent years, Northeast China has developed its ice and snow resources.",
        "chinese": "近年来，中国东北地区开发了冰雪资源。",
        "subtitle_cues": [
            {
                "english": "In recent years, Northeast China",
                "chinese": "近年来，中国东北地区",
            },
            {
                "english": "has developed its ice and snow resources.",
                "chinese": "开发了冰雪资源。",
            },
        ],
    }]
    monkeypatch.setattr(service, "_cached_tts", lambda *args: str(tmp_path / "sentence.mp3"))
    monkeypatch.setattr(service, "_combine_audio_parts", lambda *args, **kwargs: [5.0])
    monkeypatch.setattr(service, "_sentence_cue_durations", lambda *args: [2.0, 3.0])

    _, durations, cues = service.generate_segmented_audio(units, str(tmp_path / "body.wav"))

    assert cues == units[0]["subtitle_cues"]
    assert durations == [2.0, 3.0]


def test_strict_renderer_rejects_paragraph_sized_body_subtitle():
    with pytest.raises(ValueError, match="英文字幕超过2行"):
        SubtitleRenderer().render_card(
            "This deliberately oversized subtitle contains far too many words to remain readable as normal body captions on a vertical video screen.",
            "这是一条过长的正文字幕。",
            max_english_lines=2,
            max_chinese_lines=2,
        )


def test_exam_paper_persists_translation_units_and_pipeline_version():
    paper = ExamPaper(
        exam_type="CET-4",
        year=2025,
        month=6,
        set_number=2,
        chinese_text="便民生活圈。",
        translation_units=[TranslationUnit(chinese="便民生活圈。", english="Convenient living circles.")],
        subtitle_pipeline_version=SUBTITLE_PIPELINE_VERSION,
    )
    restored = ExamPaper.model_validate_json(paper.model_dump_json())
    assert restored.translation_units[0].english == "Convenient living circles."
    assert restored.subtitle_pipeline_version == SUBTITLE_PIPELINE_VERSION


def test_background_sentence_boundary_accepts_period_before_closing_quote():
    from app.pipeline.video_pipeline import VideoPipeline

    segments = [SubtitleSegment(start=0, end=2.5, english='convenient living circles."', chinese="便民生活圈。")]
    assert VideoPipeline.__new__(VideoPipeline)._is_sentence_boundary(2.5, segments)
