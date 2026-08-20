import hashlib
import json

from app.services.audio_alignment import _select_boundaries, align_captions_to_audio
from app.config import OPENING_SECTION_SET_GAP_SECONDS, OPENING_SENTENCE_GAP_SECONDS
from app.models import ExamMetadata, ExamPaper, SubtitleSegment
from app.services.audio_service import (
    FishAudioService,
    opening_captions,
    opening_spoken_texts,
    sentence_gaps_after,
)


def test_pause_boundary_is_selected_near_expected_sentence_change():
    pauses = [(1.0, 0.18), (6.6, 0.56), (9.5, 0.2)]
    assert _select_boundaries(pauses, [6.2], 12.0) == [6.6]


def test_opening_announcement_changes_subtitle_during_audio(monkeypatch):
    import app.services.audio_alignment as alignment_module

    monkeypatch.setattr(alignment_module, "detect_silences", lambda path: [(6.3, 6.7)])
    segments = align_captions_to_audio(
        "opening.mp3",
        [
            ("这是全国大学英语考试翻译部分。", "This is the translation section."),
            (
                "你有3秒钟的时间将下面的内容翻译成英文",
                "You have three seconds to translate the following content into English.",
            ),
        ],
        12.277,
    )
    assert len(segments) == 2
    assert segments[0].end == 6.5
    assert segments[1].start == segments[0].end


def test_opening_announcement_uses_real_exam_year_month_and_level():
    metadata = ExamMetadata.from_paper(ExamPaper(
        exam_type="CET-6",
        year=2023,
        month=12,
        set_number=1,
        chinese_text="测试",
        topic_cn="测试主题",
    ))
    captions = opening_captions(metadata)
    assert captions[0][0] == "这是2023年12月，全国大学生英语六级考试翻译部分。"
    assert len(captions) == 2
    assert all("第1套" not in chinese for chinese, _ in captions)
    assert "December 2023" in captions[0][1]
    assert "Band 6" in captions[0][1]
    assert opening_spoken_texts(metadata)[0] == "这是二零二三年十二月，全国大学生英语六级考试翻译部分。"
    assert opening_spoken_texts(metadata)[1] == "你有3秒钟的时间将下面的内容翻译成英文"
    assert captions[1] == (
        "你有3秒钟的时间将下面的内容翻译成英文",
        "You have three seconds to translate the following content into English.",
    )


def test_first_set_opening_does_not_generate_set_audio(tmp_path, monkeypatch):
    import app.services.audio_service as audio_module

    monkeypatch.setattr(audio_module, "AUDIO_CACHE_DIR", tmp_path)
    metadata = ExamMetadata.from_paper(ExamPaper(
        exam_type="CET-4",
        year=2025,
        month=6,
        set_number=1,
        chinese_text="测试",
        topic_cn="测试主题",
    ))
    service = FishAudioService(api_key="test")
    service.opening_reference_id = "opening-voice"
    monkeypatch.setattr(service, "_cached_tts", lambda text, reference_id, namespace: f"{text}.mp3")
    captured = {}

    def fake_combine(part_paths, output_path, gaps_after):
        captured["part_paths"] = part_paths
        captured["gaps_after"] = gaps_after
        return [1.0 + gap for gap in gaps_after]

    monkeypatch.setattr(service, "_combine_audio_parts", fake_combine)
    _, captions, durations = service.generate_opening_audio(metadata)

    assert len(captions) == 2
    assert len(captured["part_paths"]) == 2
    assert all("第一套" not in path for path in captured["part_paths"])
    assert captured["gaps_after"] == [OPENING_SENTENCE_GAP_SECONDS, 0.0]
    assert durations == [1.4, 1.0]


def test_opening_audio_keeps_both_requested_gaps(tmp_path, monkeypatch):
    import app.services.audio_service as audio_module

    monkeypatch.setattr(audio_module, "AUDIO_CACHE_DIR", tmp_path)
    metadata = ExamMetadata.from_paper(ExamPaper(
        exam_type="CET-4",
        year=2025,
        month=6,
        set_number=2,
        chinese_text="测试",
        topic_cn="测试主题",
    ))
    service = FishAudioService(api_key="test")
    service.opening_reference_id = "opening-voice"
    monkeypatch.setattr(service, "_cached_tts", lambda text, reference_id, namespace: f"{text}.mp3")
    captured = {}

    def fake_combine(part_paths, output_path, gaps_after):
        captured["part_paths"] = part_paths
        captured["gaps_after"] = gaps_after
        return [1.0 + gap for gap in gaps_after]

    monkeypatch.setattr(service, "_combine_audio_parts", fake_combine)

    _, captions, durations = service.generate_opening_audio(metadata)

    assert captions[1] == ("第2套", "Set 2.")
    assert len(captured["part_paths"]) == 3
    assert captured["gaps_after"] == [
        OPENING_SECTION_SET_GAP_SECONDS,
        OPENING_SENTENCE_GAP_SECONDS,
        0.0,
    ]
    assert durations == [1.4, 1.4, 1.0]


def test_identical_tts_text_reuses_stable_disk_cache(tmp_path, monkeypatch):
    import app.services.audio_service as audio_module

    monkeypatch.setattr(audio_module, "AUDIO_CACHE_DIR", tmp_path)
    service = FishAudioService(api_key="test")
    calls = []

    def fake_generate(text, output_path=None, reference_id=None):
        calls.append((text, reference_id))
        with open(output_path, "wb") as handle:
            handle.write(b"x" * 1024)
        return output_path

    monkeypatch.setattr(service, "generate_audio", fake_generate)
    first = service._cached_tts("same words", "opening-voice", "opening_parts")
    second = service._cached_tts("same words", "opening-voice", "opening_parts")

    assert first == second
    assert calls == [("same words", "opening-voice")]


def test_sentence_pause_is_only_added_after_complete_nonfinal_sentences():
    texts = [
        "This is the end of sentence one.",
        "A clause that continues,",
        "and finishes sentence two!",
        "The final sentence.",
    ]
    assert sentence_gaps_after(texts, 0.3) == [0.3, 0.0, 0.3, 0.0]


def test_fixed_audio_change_is_transcribed_once_then_cached(tmp_path):
    from app.services.fixed_audio_subtitle_service import FixedAudioSubtitleService

    audio_path = tmp_path / "closing.mp3"
    audio_path.write_bytes(b"original audio")
    original_digest = hashlib.sha256(audio_path.read_bytes()).hexdigest()
    manifest_path = tmp_path / "subtitles.json"
    manifest_path.write_text(json.dumps({
        "assets": {
            "closing.mp3": {
                "sha256": original_digest,
                "captions": [{"chinese": "旧字幕。", "english": "Old caption."}],
            }
        }
    }, ensure_ascii=False), encoding="utf-8")
    calls = []

    def fake_transcriber(path, duration):
        calls.append(path.read_bytes())
        return [SubtitleSegment(start=0.1, end=1.8, chinese="全新的语音。", english="")]

    service = FixedAudioSubtitleService(
        manifest_path=manifest_path,
        cache_dir=tmp_path / "transcripts",
        transcriber=fake_transcriber,
    )
    original = service.segments_for(audio_path, 2.0)
    assert original[0].chinese == "旧字幕。"
    assert calls == []

    audio_path.write_bytes(b"replacement audio")
    replaced = service.segments_for(audio_path, 2.0)
    cached = service.segments_for(audio_path, 2.0)
    assert replaced[0].chinese == "全新的语音。"
    assert cached[0].chinese == "全新的语音。"
    assert calls == [b"replacement audio"]
