"""
Small generated sound effects used by the video pipeline.
"""
import math
import struct
import wave
from pathlib import Path
from typing import Iterable, List, Sequence, Tuple


Tone = Tuple[Sequence[Tuple[float, float]], float]


def _write_tones(path: Path, tones: Iterable[Tone], sample_rate: int = 44100) -> None:
    samples: List[float] = []
    for frequencies, duration in tones:
        frame_count = int(duration * sample_rate)
        for i in range(frame_count):
            t = i / sample_rate
            value = sum(math.sin(2 * math.pi * freq * t) * gain for freq, gain in frequencies)
            samples.append(value)

    peak = max([1.0] + [abs(sample) for sample in samples])
    frames = b"".join(
        struct.pack("<h", int(32767 * 0.72 * sample / peak))
        for sample in samples
    )

    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(frames)


def _write_completion_chime(path: Path, sample_rate: int = 44100) -> None:
    """生成柔和的双音完成提示：短起音、指数衰减和少量泛音，避免生硬蜂鸣。"""
    total_duration = 1.20
    notes = [
        # 起点、基频、持续时间、音量：先 C6，后 G6，形成轻柔上行完成感。
        (0.00, 1046.50, 0.72, 0.72),
        (0.18, 1567.98, 0.94, 0.58),
    ]
    samples: List[float] = []
    for index in range(round(total_duration * sample_rate)):
        t = index / sample_rate
        value = 0.0
        for start, frequency, duration, gain in notes:
            local_t = t - start
            if local_t < 0 or local_t >= duration:
                continue
            attack = min(1.0, local_t / 0.008)
            release = min(1.0, (duration - local_t) / 0.09)
            envelope = attack * release * math.exp(-3.3 * local_t / duration)
            bell = (
                math.sin(2 * math.pi * frequency * local_t)
                + 0.24 * math.sin(2 * math.pi * frequency * 2.01 * local_t)
                + 0.08 * math.sin(2 * math.pi * frequency * 3.98 * local_t)
            )
            value += gain * envelope * bell
        samples.append(value)

    peak = max([1.0] + [abs(sample) for sample in samples])
    frames = b"".join(
        struct.pack("<h", int(32767 * 0.56 * sample / peak))
        for sample in samples
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(frames)


def _wav_duration(path: Path) -> float:
    if not path.is_file():
        return 0.0
    try:
        with wave.open(str(path), "rb") as handle:
            return handle.getnframes() / handle.getframerate()
    except (OSError, wave.Error, ZeroDivisionError):
        return 0.0


def ensure_default_sfx(countdown_path: Path, dingdong_path: Path) -> None:
    """Create default wav effects when they are missing."""
    if not countdown_path.exists():
        _write_tones(
            countdown_path,
            [
                ([(220, 1.0)], 0.16),
                ([], 0.84),
                ([(220, 1.0)], 0.16),
                ([], 0.84),
                ([(220, 1.0), (330, 0.35)], 0.22),
                ([], 0.78),
            ],
        )

    # 旧版是 0.81 秒的无包络蜂鸣；检测到旧时长时自动替换为新版柔和提示音。
    if abs(_wav_duration(dingdong_path) - 1.20) > 0.01:
        _write_completion_chime(dingdong_path)
