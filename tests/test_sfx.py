import struct
import wave

from app.utils.sfx import ensure_default_sfx


def test_completion_chime_is_soft_edged_and_uses_new_duration(tmp_path):
    countdown = tmp_path / "countdown.wav"
    chime = tmp_path / "chime.wav"
    ensure_default_sfx(countdown, chime)

    with wave.open(str(chime), "rb") as handle:
        duration = handle.getnframes() / handle.getframerate()
        raw = handle.readframes(handle.getnframes())
    samples = struct.unpack(f"<{len(raw) // 2}h", raw)

    assert duration == 1.2
    assert abs(samples[0]) <= 1
    assert abs(samples[-1]) <= 1
    assert max(abs(value) for value in samples) < 32767
