"""固定语音的字幕清单、文件变更检测与 Whisper 重新识别。"""
from __future__ import annotations

import hashlib
import json
import os
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Callable, Optional, Sequence

from dotenv import load_dotenv

from app.config import ASSET_FIXED_AUDIO_SUBTITLES, AUDIO_CACHE_DIR
from app.models import SubtitleSegment
from app.services.audio_alignment import align_captions_to_audio


_WHISPER_MODELS: dict[tuple[str, str, str], object] = {}
COMMON_TRADITIONAL_TO_SIMPLIFIED = str.maketrans({
    "學": "学", "們": "们", "譯": "译", "結": "结", "過": "过",
    "級": "级", "點": "点", "贊": "赞", "關": "关", "這": "这",
    "國": "国", "時": "时", "間": "间", "請": "请", "師": "师",
    "試": "试", "書": "书", "語": "语", "聲": "声", "練": "练",
    "繼": "继", "續": "续", "閱": "阅", "讀": "读", "內": "内",
    "題": "题", "開": "开", "動": "动", "聽": "听", "說": "说",
})


class FixedAudioSubtitleService:
    """固定 MP3 未变化时使用审校字幕，变化后按内容哈希自动重新识别。"""

    def __init__(
        self,
        manifest_path: str | Path = ASSET_FIXED_AUDIO_SUBTITLES,
        cache_dir: str | Path = AUDIO_CACHE_DIR / "transcripts",
        transcriber: Optional[Callable[[Path, float], list[SubtitleSegment]]] = None,
    ):
        self.manifest_path = Path(manifest_path)
        self.cache_dir = Path(cache_dir)
        self._transcriber = transcriber

    def segments_for(
        self,
        audio_path: str | Path,
        duration: float,
        fallback_captions: Sequence[tuple[str, str]] = (),
        force: bool = False,
    ) -> list[SubtitleSegment]:
        """返回与当前文件内容匹配的字幕；force=True 时忽略已有结果重新识别。"""
        path = Path(audio_path)
        if not path.is_file():
            return []

        digest = self._file_sha256(path)
        manifest_entry = self._manifest_entry(path.name)
        captions = self._entry_captions(manifest_entry) or list(fallback_captions)
        cache_path = self.cache_dir / f"{path.stem}_{digest[:24]}.json"

        if not force:
            if manifest_entry.get("sha256", "").lower() == digest and captions:
                return align_captions_to_audio(path, captions, duration)
            cached = self._read_cached_segments(cache_path, digest, duration)
            if cached:
                return cached

        recognized = self._run_transcriber(path, duration)
        if not recognized:
            raise RuntimeError(f"没有从固定语音中识别到字幕：{path.name}")

        # 同一文案仅重新编码或换音色时，继续使用人工审校过的中英字幕；真正换词时使用识别结果。
        if captions and (
            manifest_entry.get("sha256", "").lower() == digest
            or self._texts_are_close(recognized, captions)
        ):
            recognized = align_captions_to_audio(path, captions, duration)

        self._write_cached_segments(cache_path, digest, recognized)
        return recognized

    def _run_transcriber(self, path: Path, duration: float) -> list[SubtitleSegment]:
        if self._transcriber:
            return self._transcriber(path, duration)

        load_dotenv(override=True)
        model_name = os.getenv("WHISPER_MODEL", "small").strip() or "small"
        device = os.getenv("WHISPER_DEVICE", "auto").strip() or "auto"
        compute_type = os.getenv("WHISPER_COMPUTE_TYPE", "int8").strip() or "int8"
        cache_key = (model_name, device, compute_type)
        model = _WHISPER_MODELS.get(cache_key)
        if model is None:
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:
                raise RuntimeError(
                    "固定语音已更换，需要先安装 faster-whisper（运行 pip install -r requirements.txt）"
                ) from exc
            kwargs = {"device": device, "compute_type": compute_type}
            model = WhisperModel(model_name, **kwargs)
            _WHISPER_MODELS[cache_key] = model

        raw_segments, _ = model.transcribe(
            str(path),
            language="zh",
            beam_size=5,
            vad_filter=True,
            word_timestamps=True,
            condition_on_previous_text=False,
            initial_prompt="以下是普通话语音，请使用简体中文和规范标点转写。",
        )
        result = []
        for segment in raw_segments:
            word_groups = self._word_groups(getattr(segment, "words", None) or [])
            if word_groups:
                for start, end, text in word_groups:
                    end = min(float(duration), end)
                    if text and end > start:
                        result.append(SubtitleSegment(
                            start=round(start, 3),
                            end=round(end, 3),
                            chinese=self._to_simplified(text),
                            english="",
                        ))
                continue

            text = self._to_simplified(str(segment.text).strip())
            start = max(0.0, float(segment.start))
            end = min(float(duration), float(segment.end))
            if text and end > start:
                result.append(SubtitleSegment(start=round(start, 3), end=round(end, 3), chinese=text, english=""))
        return result

    @classmethod
    def _word_groups(cls, words: Sequence[object]) -> list[tuple[float, float, str]]:
        """按词级停顿拆分 Whisper 的长段，字幕边界直接落在发声时间戳上。"""
        groups: list[tuple[float, float, str]] = []
        current: list[object] = []
        for word in words:
            text = str(getattr(word, "word", "")).strip()
            start = getattr(word, "start", None)
            end = getattr(word, "end", None)
            if not text or start is None or end is None:
                continue
            if current:
                previous_end = float(getattr(current[-1], "end"))
                current_text = "".join(str(getattr(item, "word", "")).strip() for item in current)
                if float(start) - previous_end >= 0.22 or len(cls._normalize_text(current_text)) >= 18:
                    groups.append(cls._word_group_value(current))
                    current = []
            current.append(word)
        if current:
            groups.append(cls._word_group_value(current))
        return groups

    @staticmethod
    def _word_group_value(words: Sequence[object]) -> tuple[float, float, str]:
        return (
            max(0.0, float(getattr(words[0], "start"))),
            float(getattr(words[-1], "end")),
            "".join(str(getattr(word, "word", "")).strip() for word in words).strip(),
        )

    def _manifest_entry(self, filename: str) -> dict:
        if not self.manifest_path.is_file():
            return {}
        try:
            payload = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            entry = payload.get("assets", {}).get(filename, {})
            return entry if isinstance(entry, dict) else {}
        except (OSError, TypeError, json.JSONDecodeError):
            return {}

    @staticmethod
    def _entry_captions(entry: dict) -> list[tuple[str, str]]:
        result = []
        for item in entry.get("captions", []):
            if isinstance(item, dict) and str(item.get("chinese", "")).strip():
                result.append((
                    str(item.get("chinese", "")).strip(),
                    str(item.get("english", "")).strip(),
                ))
        return result

    @staticmethod
    def _file_sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _read_cached_segments(path: Path, digest: str, duration: float) -> list[SubtitleSegment]:
        if not path.is_file():
            return []
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("audio_sha256") != digest:
                return []
            segments = [SubtitleSegment.model_validate(item) for item in payload.get("segments", [])]
            if not segments or any(segment.end <= segment.start or segment.end > duration + 0.1 for segment in segments):
                return []
            return segments
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return []

    def _write_cached_segments(self, path: Path, digest: str, segments: list[SubtitleSegment]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix(".tmp")
        temp_path.write_text(
            json.dumps(
                {
                    "audio_sha256": digest,
                    "segments": [segment.model_dump(mode="json") for segment in segments],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        temp_path.replace(path)

    @classmethod
    def _texts_are_close(
        cls,
        recognized: Sequence[SubtitleSegment],
        captions: Sequence[tuple[str, str]],
    ) -> bool:
        recognized_text = cls._normalize_text("".join(segment.chinese for segment in recognized))
        expected_text = cls._normalize_text("".join(chinese for chinese, _ in captions))
        if not recognized_text or not expected_text:
            return False
        return SequenceMatcher(None, recognized_text, expected_text).ratio() >= 0.72

    @staticmethod
    def _normalize_text(value: str) -> str:
        return re.sub(
            r"[^0-9A-Za-z\u3400-\u9fff]",
            "",
            FixedAudioSubtitleService._to_simplified(value),
        ).lower()

    @staticmethod
    def _to_simplified(value: str) -> str:
        return str(value).translate(COMMON_TRADITIONAL_TO_SIMPLIFIED)
