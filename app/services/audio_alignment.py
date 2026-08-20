"""基于真实音频静音区间生成字幕边界，并裁掉 TTS 片段首尾空白。"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Iterable, Sequence

from moviepy.config import FFMPEG_BINARY

from app.models import SubtitleSegment


SILENCE_RE = re.compile(r"silence_(start|end):\s*([0-9.]+)")


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
