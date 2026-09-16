"""
Fish Audio语音合成服务
"""
import hashlib
import json
import os
import re
import requests
import numpy as np
from pathlib import Path
from typing import Any, List, Optional, Tuple
from dotenv import load_dotenv
from app.config import (
    AUDIO_CACHE_DIR, BODY_SENTENCE_GAP_SECONDS, FISH_CET_ZH_REFERENCE_ID,
    FISH_DAILY_EN_REFERENCE_ID, FISH_OPENING_REFERENCE_ID, FISH_REFERENCE_ID,
    OPENING_SENTENCE_GAP_SECONDS, TEMP_DIR
)
from app.services.audio_alignment import (
    cue_boundaries_from_word_timestamps,
    english_word_timestamps,
    voiced_bounds,
)
from app.services.subtitle_service import (
    english_word_count,
    sentence_units_from_translation_units,
    split_bilingual_subtitle_cues,
)

try:
    from moviepy.editor import AudioFileClip, concatenate_audioclips
    from moviepy.audio.AudioClip import AudioArrayClip
except ImportError:
    from moviepy import AudioArrayClip, AudioFileClip, concatenate_audioclips


class FishAudioService:
    """Fish Audio语音合成服务"""

    BASE_URL = "https://api.fish.audio/v1/tts"

    def __init__(self, api_key: Optional[str] = None):
        load_dotenv(override=True)
        env_reference_id = os.getenv("FISH_REFERENCE_ID", "")
        env_opening_reference_id = os.getenv("FISH_OPENING_REFERENCE_ID", "")
        env_cet_reference_id = os.getenv("FISH_CET_ZH_REFERENCE_ID", "")
        env_daily_reference_id = os.getenv("FISH_DAILY_EN_REFERENCE_ID", "")

        self.api_key = api_key or os.getenv("FISH_API_KEY", "") or os.getenv("FISH_AUDIO_API_KEY", "")
        self.reference_id = (
            env_reference_id
            or env_cet_reference_id
            or env_daily_reference_id
            or FISH_REFERENCE_ID
            or FISH_CET_ZH_REFERENCE_ID
            or FISH_DAILY_EN_REFERENCE_ID
        )
        self.opening_reference_id = env_opening_reference_id or FISH_OPENING_REFERENCE_ID
        self.model = os.getenv("FISH_TTS_MODEL", "")
        self._word_alignment_available = True

    def generate_audio(
        self,
        text: str,
        output_path: Optional[str] = None,
        reference_id: Optional[str] = None,
    ) -> Optional[str]:
        """
        生成英文朗读音频

        Args:
            text: 英文文本
            output_path: 输出路径，如果不指定则自动生成

        Returns:
            生成的音频文件路径，失败返回None
        """
        selected_reference_id = reference_id or self.reference_id
        if not selected_reference_id:
            print("错误: Fish Audio Reference ID未配置")
            return None

        # 如果未指定输出路径，自动生成
        if not output_path:
            output_path = str(TEMP_DIR / f"english_audio_{abs(hash(text)) % 100000}.mp3")

        try:
            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            if self.model:
                headers["model"] = self.model

            data = {
                "text": text,
                "reference_id": selected_reference_id,
                "format": "mp3",
                "chunk_length": 300,
                "normalize": True,
                "mp3_bitrate": 128,
                "latency": "normal",
            }

            response = requests.post(
                self.BASE_URL,
                headers=headers,
                json=data,
                timeout=90
            )
            response.raise_for_status()

            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, 'wb') as f:
                f.write(response.content)

            return output_path

        except Exception as e:
            print(f"生成音频失败: {e}")
            return None

    def generate_segmented_audio(
        self,
        segments: List[dict],
        output_path: Optional[str] = None,
        max_chars: int = 500
    ) -> Tuple[Optional[str], List[float], List[dict]]:
        """
        分段生成英文朗读并拼接，返回完整音频路径、每段时长和实际朗读分段。
        """
        if not segments:
            return None, [], []

        if not output_path:
            joined = " ".join(seg.get("english", "") for seg in segments)
            output_path = str(TEMP_DIR / f"english_audio_{abs(hash(joined)) % 100000}.mp3")

        # 完整句子才是 TTS 单位；句内短字幕只切换画面，不再切断朗读语流。
        sentence_units = []
        for segment in segments:
            provided_cues = segment.get("subtitle_cues") or []
            joined_cues = " ".join(
                " ".join(str(cue.get("english", "")).split())
                for cue in provided_cues
                if isinstance(cue, dict)
            ).strip()
            sentence_english = " ".join(str(segment.get("english", "")).split()).strip()
            if provided_cues and joined_cues == sentence_english:
                sentence_units.append(segment)
            else:
                sentence_units.extend(sentence_units_from_translation_units([segment]))
        if not sentence_units:
            return None, [], []

        if not self.reference_id:
            print("错误: 正文朗读未配置 FISH_REFERENCE_ID")
            return None, [], []

        part_paths = []
        for sentence in sentence_units:
            generated = self._cached_tts(
                sentence["english"],
                self.reference_id,
                "body_sentence_v2",
            )
            if not generated:
                return None, [], []
            part_paths.append(generated)

        try:
            gaps_after = sentence_gaps_after(
                [sentence["english"] for sentence in sentence_units],
                BODY_SENTENCE_GAP_SECONDS,
            )
            sentence_durations = self._combine_audio_parts(part_paths, output_path, gaps_after=gaps_after)
            actual_segments: List[dict] = []
            durations: List[float] = []
            for sentence, part_path, sentence_duration, gap in zip(
                sentence_units,
                part_paths,
                sentence_durations,
                gaps_after,
            ):
                cues = sentence.get("subtitle_cues") or split_bilingual_subtitle_cues(
                    sentence["english"], sentence["chinese"]
                )
                cue_durations = self._sentence_cue_durations(
                    part_path,
                    cues,
                    sentence_duration,
                    gap,
                )
                actual_segments.extend(cues)
                durations.extend(cue_durations)
            return output_path, durations, actual_segments
        except Exception as e:
            print(f"拼接音频失败: {e}")
            return None, [], []

    def generate_opening_audio(self, metadata: Any) -> Tuple[str, List[Tuple[str, str]], List[float]]:
        """按真实考试年月生成动态开场；相同文案和音色命中本地缓存。"""
        if not self.opening_reference_id:
            raise RuntimeError("请在 .env 中配置 FISH_OPENING_REFERENCE_ID")

        captions = opening_captions(metadata)
        spoken_parts = opening_spoken_texts(metadata)
        gaps_after = [OPENING_SENTENCE_GAP_SECONDS, 0.0]
        spoken_text = (
            "\n".join(spoken_parts)
            + "\n[gaps=" + ",".join(f"{gap:.3f}" for gap in gaps_after) + "]"
        )
        cache_key = self._cache_key(spoken_text, self.opening_reference_id)
        output_dir = AUDIO_CACHE_DIR / "opening"
        output_path = output_dir / f"{cache_key}.wav"
        metadata_path = output_dir / f"{cache_key}.json"

        cached_durations = self._read_cached_durations(metadata_path, len(captions))
        if self._valid_audio_file(output_path) and cached_durations:
            return str(output_path), captions, cached_durations

        part_paths = []
        for spoken_chinese in spoken_parts:
            generated = self._cached_tts(
                spoken_chinese,
                self.opening_reference_id,
                "opening_parts",
            )
            if not generated:
                raise RuntimeError("Fish Audio 动态开场生成失败")
            part_paths.append(generated)

        durations = self._combine_audio_parts(
            part_paths,
            str(output_path),
            gaps_after=gaps_after,
        )
        output_dir.mkdir(parents=True, exist_ok=True)
        temp_metadata = metadata_path.with_suffix(".tmp")
        temp_metadata.write_text(
            json.dumps({"durations": durations}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temp_metadata.replace(metadata_path)
        return str(output_path), captions, durations

    def _cached_tts(self, text: str, reference_id: str, namespace: str) -> Optional[str]:
        cache_dir = AUDIO_CACHE_DIR / namespace
        cache_path = cache_dir / f"{self._cache_key(text, reference_id)}.mp3"
        if self._valid_audio_file(cache_path):
            return str(cache_path)
        cache_dir.mkdir(parents=True, exist_ok=True)
        return self.generate_audio(text, str(cache_path), reference_id=reference_id)

    def _sentence_cue_durations(
        self,
        part_path: str,
        cues: List[dict],
        sentence_duration: float,
        gap_after: float,
    ) -> List[float]:
        """优先使用词级时间戳；不可用时按词数平滑分配句内字幕时间。"""
        total_duration = max(0.2, float(sentence_duration))
        gap = max(0.0, min(float(gap_after), total_duration - 0.1))
        spoken_duration = max(0.1, total_duration - gap)
        if len(cues) <= 1:
            return [total_duration]

        cache_payload = "\n".join(cue["english"] for cue in cues)
        cache_key = hashlib.sha256(
            f"sentence-cues-v2\n{Path(part_path).stem}\n{cache_payload}".encode("utf-8")
        ).hexdigest()[:24]
        cache_path = AUDIO_CACHE_DIR / "body_alignment_v2" / f"{cache_key}.json"
        cached = self._read_cached_durations(cache_path, len(cues))
        if cached and abs(sum(cached) - total_duration) <= 0.05:
            return cached

        boundaries: List[float] = []
        if self._word_alignment_available:
            try:
                source = AudioFileClip(part_path)
                try:
                    speech_start, _ = voiced_bounds(part_path, float(source.duration))
                finally:
                    source.close()
                raw_words = english_word_timestamps(part_path, cache_payload)
                adjusted_words = [
                    (
                        max(0.0, start - speech_start),
                        min(spoken_duration, max(0.0, end - speech_start)),
                        word,
                    )
                    for start, end, word in raw_words
                    if end > speech_start and start - speech_start < spoken_duration
                ]
                boundaries = cue_boundaries_from_word_timestamps(
                    [cue["english"] for cue in cues],
                    adjusted_words,
                    spoken_duration,
                )
            except Exception as exc:
                self._word_alignment_available = False
                print(f"词级字幕对齐不可用，改用朗读权重时间轴: {exc}")

        if not boundaries:
            weights = [max(1, english_word_count(cue["english"])) for cue in cues]
            total_weight = max(1, sum(weights))
            cursor = 0
            for weight in weights[:-1]:
                cursor += weight
                boundaries.append(spoken_duration * cursor / total_weight)

        points = [0.0, *boundaries, spoken_duration]
        durations = [
            max(0.05, points[index + 1] - points[index])
            for index in range(len(cues))
        ]
        durations[-1] += gap
        durations[-1] += total_duration - sum(durations)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = cache_path.with_suffix(".tmp")
        temp_path.write_text(
            json.dumps({"durations": durations}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temp_path.replace(cache_path)
        return durations

    def _cache_key(self, text: str, reference_id: str) -> str:
        payload = json.dumps(
            {
                "text": " ".join(str(text).split()),
                "reference_id": reference_id,
                "model": self.model,
                "format": "mp3",
                "normalize": True,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]

    @staticmethod
    def _valid_audio_file(path: str | Path) -> bool:
        candidate = Path(path)
        return candidate.is_file() and candidate.stat().st_size > 512

    @staticmethod
    def _read_cached_durations(path: Path, expected_count: int) -> List[float]:
        if not path.is_file():
            return []
        try:
            values = json.loads(path.read_text(encoding="utf-8")).get("durations", [])
            durations = [float(value) for value in values]
            return durations if len(durations) == expected_count and all(value > 0 for value in durations) else []
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return []

    def _combine_audio_parts(
        self,
        part_paths: List[str],
        output_path: str,
        gaps_after: Optional[List[float]] = None,
    ) -> List[float]:
        """裁掉 cue 边缘静音并插入句间停顿；返回含停顿的字幕时长。"""
        clips = []
        source_clips = []
        durations = []
        gaps_after = list(gaps_after or [0.0] * len(part_paths))
        if len(gaps_after) != len(part_paths):
            raise ValueError("音频片段数量与句间停顿数量不一致")
        try:
            for index, path in enumerate(part_paths):
                source = AudioFileClip(path)
                source_clips.append(source)
                speech_start, speech_end = voiced_bounds(path, float(source.duration))
                clip = (
                    source.subclipped(speech_start, speech_end)
                    if hasattr(source, "subclipped") and (speech_start > 0 or speech_end < source.duration)
                    else source.subclip(speech_start, speech_end)
                    if not hasattr(source, "subclipped") and (speech_start > 0 or speech_end < source.duration)
                    else source
                )
                clips.append(clip)
                gap = max(0.0, float(gaps_after[index]))
                durations.append(float(clip.duration) + gap)
                if gap:
                    channels = max(1, int(getattr(source, "nchannels", 1)))
                    silence = AudioArrayClip(
                        np.zeros((round(gap * 44100), channels), dtype=np.float64),
                        fps=44100,
                    )
                    clips.append(silence)

            final_audio = concatenate_audioclips(clips)
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            codec = "pcm_s16le" if Path(output_path).suffix.lower() == ".wav" else "libmp3lame"
            final_audio.write_audiofile(output_path, fps=44100, codec=codec, logger=None)
            final_audio.close()
            return durations
        finally:
            for clip in clips:
                clip.close()
            for source in source_clips:
                if source not in clips:
                    source.close()

    def estimate_duration(self, text: str) -> float:
        """
        估算音频时长（秒）
        简单估算：平均每个单词0.5秒
        """
        words = text.split()
        return len(words) * 0.5

    def _split_for_tts(self, text: str, max_chars: int = 500) -> List[str]:
        """按句子优先拆分，确保免费额度下每次请求不过长。"""
        import re

        text = " ".join(text.split())
        if len(text) <= max_chars:
            return [text] if text else []

        sentences = re.split(r'(?<=[.!?;:])\s+', text)
        chunks = []
        current = ""
        for sentence in sentences:
            if not sentence:
                continue
            if len(sentence) > max_chars:
                if current:
                    chunks.append(current.strip())
                    current = ""
                for i in range(0, len(sentence), max_chars):
                    chunks.append(sentence[i:i + max_chars].strip())
                continue
            if len(current) + len(sentence) + 1 <= max_chars:
                current = f"{current} {sentence}".strip()
            else:
                chunks.append(current.strip())
                current = sentence

        if current:
            chunks.append(current.strip())
        return chunks


def opening_captions(metadata: Any) -> List[Tuple[str, str]]:
    """构造动态中英文开场字幕；套数只在题板中显示。"""
    month_en = {6: "June", 12: "December"}.get(metadata.exam_month, str(metadata.exam_month))
    band = "4" if metadata.exam_level == "CET-4" else "6"
    captions = [
        (
            f"这是{metadata.exam_session}，全国大学生英语{metadata.exam_level_cn}考试翻译部分。",
            f"This is the translation section of the {month_en} {metadata.exam_year} College English Test Band {band}.",
        ),
        (
            "你有3秒钟的时间将下面的内容翻译成英文",
            "You have three seconds to translate the following content into English.",
        ),
    ]
    return captions


def opening_spoken_texts(metadata: Any) -> List[str]:
    """用中文数字明确读出“年/月”；套数只在题板中显示，不朗读。"""
    digits = "零一二三四五六七八九"
    year = "".join(digits[int(char)] for char in str(metadata.exam_year))
    month = {6: "六月", 12: "十二月"}.get(metadata.exam_month, f"{metadata.exam_month}月")
    return [
        f"这是{year}年{month}，全国大学生英语{metadata.exam_level_cn}考试翻译部分。",
        "你有3秒钟的时间将下面的内容翻译成英文",
    ]


def sentence_gaps_after(texts: List[str], gap_seconds: float) -> List[float]:
    """只在非末尾的完整英文句子后增加停顿，短语 cue 之间保持连贯。"""
    gaps = []
    for index, text in enumerate(texts):
        is_last = index == len(texts) - 1
        is_sentence_end = bool(re.search(r"[.!?][\"'”’\)\]]*$", str(text).strip()))
        gaps.append(0.0 if is_last or not is_sentence_end else float(gap_seconds))
    return gaps
