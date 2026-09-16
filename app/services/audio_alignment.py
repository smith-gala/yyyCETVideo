"""基于真实音频静音区间生成字幕边界，并裁掉 TTS 片段首尾空白。"""
from __future__ import annotations

import re
import subprocess
import os
from difflib import SequenceMatcher
from pathlib import Path
from typing import Iterable, Sequence

from dotenv import load_dotenv

from moviepy.config import FFMPEG_BINARY

from app.models import SubtitleSegment


SILENCE_RE = re.compile(r"silence_(start|end):\s*([0-9.]+)")
_ENGLISH_WHISPER_MODELS: dict[tuple[str, str, str], object] = {}


def detect_silences(
    audio_path: str | Path,
    min_duration: float = 0.14,
    noise_db: int = -38,
) -> list[tuple[float, float]]:
    """使用 MoviePy 自带的 ffmpeg 检出静音；失败时安全退回空列表。"""
    command = [
        str(FFMPEG_BINARY), "-hide_banner", "-nostats", "-i", str(audio_path),
        "-af", f"silencedetect=noise={noise_db}dB:d={min_duration}",
        "-f", "null", "-",
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    except (OSError, ValueError):
        return []

    intervals: list[tuple[float, float]] = []
    start = None
    for kind, raw_value in SILENCE_RE.findall(result.stderr):
        value = float(raw_value)
        if kind == "start":
            start = value
        elif start is not None and value > start:
            intervals.append((start, value))
            start = None
    return intervals


def voiced_bounds(audio_path: str | Path, duration: float, padding: float = 0.06) -> tuple[float, float]:
    """返回实际发声区间，只处理紧贴音频两端的静音。"""
    start, end = 0.0, float(duration)
    for silence_start, silence_end in detect_silences(audio_path, min_duration=0.12):
        if silence_start <= 0.08:
            start = max(start, silence_end - padding)
        if silence_end >= duration - 0.08:
            end = min(end, silence_start + padding)
    if end - start < 0.2:
        return 0.0, float(duration)
    return max(0.0, start), min(float(duration), end)


def english_word_timestamps(
    audio_path: str | Path,
    expected_text: str = "",
) -> list[tuple[float, float, str]]:
    """懒加载 Whisper，返回英文词级时间戳；调用方负责提供安全兜底。"""
    load_dotenv(override=True)
    model_name = os.getenv("WHISPER_MODEL", "small").strip() or "small"
    device = os.getenv("WHISPER_DEVICE", "auto").strip() or "auto"
    compute_type = os.getenv("WHISPER_COMPUTE_TYPE", "int8").strip() or "int8"
    cache_key = (model_name, device, compute_type)
    model = _ENGLISH_WHISPER_MODELS.get(cache_key)
    if model is None:
        from faster_whisper import WhisperModel

        model = WhisperModel(model_name, device=device, compute_type=compute_type)
        _ENGLISH_WHISPER_MODELS[cache_key] = model

    raw_segments, _ = model.transcribe(
        str(audio_path),
        language="en",
        beam_size=1,
        vad_filter=True,
        word_timestamps=True,
        condition_on_previous_text=False,
        initial_prompt=expected_text or None,
    )
    words: list[tuple[float, float, str]] = []
    for segment in raw_segments:
        for word in getattr(segment, "words", None) or []:
            text = str(getattr(word, "word", "")).strip()
            start = getattr(word, "start", None)
            end = getattr(word, "end", None)
            if text and start is not None and end is not None and float(end) > float(start):
                words.append((max(0.0, float(start)), float(end), text))
    return words


def cue_boundaries_from_word_timestamps(
    cue_texts: Sequence[str],
    words: Sequence[tuple[float, float, str]],
    duration: float,
) -> list[float]:
    """把已知字幕文本边界映射到 Whisper 词时间戳；识别差异过大时返回空列表。"""
    if len(cue_texts) <= 1 or len(words) < 2:
        return []
    expected_parts = [_alignment_text(text) for text in cue_texts]
    expected = "".join(expected_parts)
    recognized_parts = [_alignment_text(word[2]) for word in words]
    recognized = "".join(recognized_parts)
    if not expected or not recognized or SequenceMatcher(None, expected, recognized).ratio() < 0.55:
        return []

    expected_total = len(expected)
    recognized_total = max(1, len(recognized))
    recognized_cumulative = []
    cursor = 0
    for value in recognized_parts:
        cursor += len(value)
        recognized_cumulative.append(cursor)

    boundaries: list[float] = []
    expected_cursor = 0
    previous_word_index = -1
    for part in expected_parts[:-1]:
        expected_cursor += len(part)
        target_ratio = expected_cursor / expected_total
        valid_indices = range(previous_word_index + 1, len(words) - 1)
        try:
            word_index = min(
                valid_indices,
                key=lambda index: abs(recognized_cumulative[index] / recognized_total - target_ratio),
            )
        except ValueError:
            return []
        boundary = (float(words[word_index][1]) + float(words[word_index + 1][0])) / 2
        if boundaries and boundary <= boundaries[-1] + 0.05:
            return []
        boundaries.append(max(0.05, min(float(duration) - 0.05, boundary)))
        previous_word_index = word_index
    return boundaries


def _alignment_text(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z]", "", str(value)).lower()


def align_captions_to_audio(
    audio_path: str | Path,
    captions: Sequence[tuple[str, str]],
    duration: float,
) -> list[SubtitleSegment]:
    """把多句固定播报按真实停顿切成会随语音更新的字幕 cue。"""
    if not captions:
        return []
    if len(captions) == 1:
        chinese, english = captions[0]
        return [SubtitleSegment(start=0.0, end=duration, chinese=chinese, english=english)]

    weights = [max(1, len("".join(chinese.split()))) for chinese, _ in captions]
    expected = _weighted_boundaries(weights, duration)
    pauses = [
        ((start + end) / 2, end - start)
        for start, end in detect_silences(audio_path)
        if start > 0.1 and end < duration - 0.1
    ]
    boundaries = _select_boundaries(pauses, expected, duration)
    points = [0.0, *boundaries, float(duration)]
    return [
        SubtitleSegment(
            start=round(points[index], 3),
            end=round(points[index + 1], 3),
            chinese=chinese,
            english=english,
        )
        for index, (chinese, english) in enumerate(captions)
    ]


def _weighted_boundaries(weights: Iterable[int], duration: float) -> list[float]:
    values = list(weights)
    total = max(1, sum(values))
    cursor = 0
    boundaries = []
    for value in values[:-1]:
        cursor += value
        boundaries.append(duration * cursor / total)
    return boundaries


def _select_boundaries(
    pauses: Sequence[tuple[float, float]],
    expected: Sequence[float],
    duration: float,
) -> list[float]:
    """按句子预计位置匹配停顿；缺少停顿时使用文本比例作为兜底。"""
    selected: list[float] = []
    remaining = list(pauses)
    minimum_gap = min(0.35, duration / max(4, len(expected) * 3))
    for target in expected:
        valid = [item for item in remaining if (not selected or item[0] - selected[-1] >= minimum_gap)]
        if valid:
            candidate = min(
                valid,
                key=lambda item: abs(item[0] - target) / max(duration, 0.1) - min(item[1], 0.8) * 0.12,
            )
            boundary = candidate[0]
            remaining.remove(candidate)
        else:
            boundary = target
        selected.append(boundary)
    return sorted(max(0.05, min(duration - 0.05, value)) for value in selected)
