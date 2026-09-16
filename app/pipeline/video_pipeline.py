"""
视频生成管道。
"""
import os
import re
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
from PIL import Image, ImageDraw

try:
    from moviepy.editor import (
        AudioFileClip, CompositeAudioClip, CompositeVideoClip, ImageClip, VideoFileClip,
        concatenate_videoclips
    )
    from moviepy.editor import vfx
except ImportError:
    from moviepy import AudioFileClip, CompositeAudioClip, CompositeVideoClip, ImageClip, VideoFileClip, concatenate_videoclips, vfx

from app.config import (
    ASSET_CLOSING_AUDIO, ASSET_COUNTDOWN_SFX, ASSET_DINGDONG_SFX,
    ASSET_ENDING_EXAM_AUDIO, COVER_DURATION_SECONDS, OUTPUT_DIR, TEMP_DIR,
    VIDEO_FPS, VIDEO_HEIGHT, VIDEO_WIDTH
)
from app.models import ExamMetadata, ExamPaper, SubtitleSegment, VideoConfig
from app.renderers.cover_renderer import CoverRenderer
from app.renderers.keywords_renderer import KeywordsRenderer
from app.renderers.question_renderer import QuestionRenderer
from app.renderers.subtitle_renderer import SubtitleRenderer
from app.renderers.design_tokens import KEYWORDS, SUBTITLE
from app.renderers.layout_utils import load_font
from app.services.background_selector import AdaptiveBackgroundSelector, BackgroundAsset
from app.services.audio_alignment import align_captions_to_audio
from app.services.audio_service import FishAudioService
from app.services.fixed_audio_subtitle_service import FixedAudioSubtitleService
from app.services.subtitle_service import english_word_count
from app.utils.sfx import ensure_default_sfx


SENTENCE_ENDINGS = (".", "!", "?", "。", "！", "？")
CUT_THRESHOLDS = {"relaxed": 0.75, "standard": 0.45, "fast": 0.18}
WORD_PATTERN = re.compile(r"[a-zA-Z0-9]+|[\u3400-\u9fff]{2,}")
STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "to", "of", "in", "on", "is",
    "are", "was", "were", "you", "your", "i", "we", "they", "it", "this",
    "that", "的", "了", "是", "在", "我", "你", "我们", "他们",
}
THEME_HINTS = {
    "city": ("city", "street", "urban", "traffic", "城市", "街道", "都市"),
    "nature": ("nature", "forest", "mountain", "ocean", "sea", "river", "自然", "森林", "山", "海"),
    "work": ("work", "office", "business", "career", "meeting", "工作", "办公室"),
    "technology": ("technology", "computer", "software", "phone", "ai", "科技", "电脑"),
    "people": ("people", "family", "friend", "community", "人们", "家庭", "朋友"),
    "travel": ("travel", "journey", "airport", "train", "road", "旅行", "旅程"),
    "food": ("food", "cook", "restaurant", "coffee", "食物", "烹饪", "餐桌", "饮食"),
    "education": ("school", "student", "teacher", "education", "大学", "学生", "教育", "学习"),
    "culture": ("culture", "tradition", "history", "festival", "文化", "传统", "历史", "节日"),
}


class VideoPipeline:
    """生成完整CET翻译短视频。"""

    def __init__(self):
        self.question_renderer = QuestionRenderer()
        self.keywords_renderer = KeywordsRenderer()
        self.cover_renderer = CoverRenderer()
        self.subtitle_renderer = SubtitleRenderer()
        self.fixed_audio_subtitles = FixedAudioSubtitleService()
        self.fps = VIDEO_FPS
        self.size = (VIDEO_WIDTH, VIDEO_HEIGHT)
        ensure_default_sfx(ASSET_COUNTDOWN_SFX, ASSET_DINGDONG_SFX)

    def generate(self, config: VideoConfig) -> Optional[str]:
        try:
            metadata = ExamMetadata.from_paper(config.paper)
            self._print_metadata(metadata)
            clips = []

            if config.cover_enabled:
                clip = self._create_cover_clip(config, metadata)
                if clip:
                    clips.append(clip)

            question_result = self._create_question_clip(config.paper, metadata)
            question_clip, question_frame = question_result if question_result else (None, None)
            if question_clip:
                clips.append(question_clip)

            countdown_clip = self._create_countdown_clip(question_frame)
            if countdown_clip:
                clips.append(countdown_clip)

            exam_end_clip = self._create_exam_end_clip(question_frame)
            if exam_end_clip:
                clips.append(exam_end_clip)

            content_clip = self._create_content_clip(config)
            if content_clip:
                clips.append(content_clip)

            keywords_clip = self._create_keywords_clip(config, metadata)
            if keywords_clip:
                clips.append(keywords_clip)

            if not clips:
                return None

            final_video = concatenate_videoclips(clips, method="chain")

            if not config.output_path:
                output_filename = f"{config.paper.paper_id}.mp4"
                config.output_path = str(OUTPUT_DIR / output_filename)

            final_video.write_videofile(
                config.output_path,
                fps=self.fps,
                codec="libx264",
                audio_codec="aac",
                preset="veryfast",
                threads=max(1, min(os.cpu_count() or 4, 8)),
                pixel_format="yuv420p",
                temp_audiofile=str(TEMP_DIR / "temp-audio.m4a"),
                remove_temp=True,
            )

            final_video.close()
            for clip in clips:
                clip.close()
            return config.output_path
        except Exception as e:
            print(f"生成视频失败: {e}")
            import traceback
            traceback.print_exc()
            return None

    def _create_cover_clip(self, config: VideoConfig, metadata: ExamMetadata):
        img_path = str(TEMP_DIR / f"cover_{config.paper.paper_id}.jpg")
        rendered = self.cover_renderer.render(
            output_path=img_path,
            metadata=metadata,
            background_path=config.cover_path,
        )
        if not rendered:
            return None
        return self._with_duration(ImageClip(img_path), COVER_DURATION_SECONDS)

    def _create_question_clip(self, paper: ExamPaper, metadata: ExamMetadata):
        img_path = str(TEMP_DIR / f"question_{paper.paper_id}.png")
        rendered = self.question_renderer.render(
            chinese_text=paper.chinese_text,
            metadata=metadata,
            output_path=img_path,
        )
        if not rendered:
            return None

        opening_path, captions, cue_durations = FishAudioService().generate_opening_audio(metadata)
        audio = self._audio_or_none(Path(opening_path))
        if not audio:
            raise RuntimeError("动态开场音频生成失败")
        duration = audio.duration
        base = self._with_duration(ImageClip(img_path), duration)
        layers = [base]
        cursor = 0.0
        opening_segments = []
        for (chinese, english), cue_duration in zip(captions, cue_durations):
            end = cursor + cue_duration
            opening_segments.append(SubtitleSegment(
                start=round(cursor, 3),
                end=round(end, 3),
                chinese=chinese,
                english=english,
            ))
            cursor = end
        layers += self._timed_subtitle_layers(
            opening_segments,
            duration,
            orientation="landscape",
            chinese_top=True,
            y_offset=-50,
        )
        clip = self._compose_layers(layers)
        # 倒计时和考试结束页必须复用无字幕题板，不能截取 t=0 的合成帧。
        clean_question_frame = np.array(Image.open(img_path).convert("RGB"))
        return (self._with_audio(clip, audio), clean_question_frame)

    def _create_countdown_clip(self, background_frame):
        bg_clip = self._image_clip_from_frame(background_frame, "countdown_bg.png")
        bg_clip = self._with_duration(bg_clip, 3.0)
        layers = [bg_clip]
        for idx, num in enumerate(["3", "2", "1"]):
            number_img = self._text_image(num, font_size=150, fill=(198, 42, 51, 230), box=(260, 230))
            layers.append(
                self._with_position(
                    self._with_start(self._with_duration(ImageClip(np.array(number_img)), 1.0), idx),
                    ("center", VIDEO_HEIGHT - 560),
                )
            )

        clip = self._compose_layers(layers)
        audio = self._audio_or_none(ASSET_COUNTDOWN_SFX)
        return self._with_audio(clip, audio) if audio else clip

    def _create_exam_end_clip(self, background_frame):
        audio = self._audio_or_none(ASSET_ENDING_EXAM_AUDIO)
        if not audio:
            return None
        bg_clip = self._with_duration(self._image_clip_from_frame(background_frame, "exam_end_bg.png"), audio.duration)
        layers = [bg_clip]
        layers += self._announcement_subtitle_layers(
            ASSET_ENDING_EXAM_AUDIO,
            [
                ("考试时间结束。", "Time is up."),
                ("请监考老师收卷。", "Invigilators, please collect the papers."),
            ],
            audio.duration,
            chinese_top=True,
            recognize_fixed_audio=True,
        )
        return self._with_audio(self._compose_layers(layers), audio)

    def _create_content_clip(self, config: VideoConfig):
        if not config.audio_path or not os.path.exists(config.audio_path):
            print("警告: 英文朗读音频不存在")
            return None

        audio = AudioFileClip(config.audio_path)
        duration = audio.duration
        segments = config.subtitle_segments or config.paper.subtitle_segments or []
        if any(english_word_count(segment.english) > 20 for segment in segments):
            audio.close()
            raise ValueError("检测到超过20词的旧字幕 cue，请重新按短 cue 生成 TTS 音频后再编码视频。")
        bg_clip = self._load_background_sequence(
            config.background_paths or [config.background_path],
            config.background_type,
            duration,
            segments,
            config.background_min_clip_duration,
            config.background_target_clip_duration,
            config.background_max_clip_duration,
            config.background_cut_sensitivity,
        )
        layers = [bg_clip]
        layers += self._timed_subtitle_layers(
            segments,
            duration,
            orientation=config.background_orientation,
            strict_lines=True,
        )
        return self._with_audio(self._compose_layers(layers), audio)

    def _create_keywords_clip(self, config: VideoConfig, metadata: ExamMetadata):
        img_path = str(TEMP_DIR / f"keywords_{config.paper.paper_id}.png")
        rendered = self.keywords_renderer.render(
            key_expressions=config.paper.key_expressions or [],
            metadata=metadata,
            output_path=img_path,
            background_path=config.keywords_bg_path,
        )
        if not rendered:
            return None

        closing_audio = self._audio_or_none(ASSET_CLOSING_AUDIO)
        chime_audio = self._audio_or_none(ASSET_DINGDONG_SFX)
        duration = closing_audio.duration + 1.5 if closing_audio else max(5.0, chime_audio.duration if chime_audio else 0.0)
        base = self._with_duration(ImageClip(img_path), duration)
        layers = [base]
        if closing_audio:
            layers += self._announcement_subtitle_layers(
                ASSET_CLOSING_AUDIO,
                [
                    ("同学们，翻译结束。", "The translation is over."),
                    ("想过四六级，点赞加关注。", "Want to pass CET-4 or CET-6? Like and follow."),
                ],
                closing_audio.duration,
                start=1.5,
                chinese_top=True,
                y_offset=-50,
                minimum_y=KEYWORDS.outer[3] + 30,
                recognize_fixed_audio=True,
            )
        clip = self._compose_layers(layers)
        audio_layers = []
        if chime_audio:
            audio_layers.append(chime_audio)
        if closing_audio:
            audio_layers.append(
                closing_audio.with_start(1.5)
                if hasattr(closing_audio, "with_start")
                else closing_audio.set_start(1.5)
            )
        if not audio_layers:
            return clip
        mixed_audio = CompositeAudioClip(audio_layers)
        return self._with_audio(clip, self._with_duration(mixed_audio, duration))

    def _load_background(self, path: str, kind: str, duration: float, source_start: Optional[float] = None):
        if kind == "video":
            clip = VideoFileClip(path).without_audio()
            if clip.duration < duration:
                clip = clip.with_effects([vfx.Loop(duration=duration)]) if hasattr(clip, "with_effects") else clip.loop(duration=duration)
            else:
                start = (
                    max(0.0, min(float(source_start), clip.duration - duration))
                    if source_start is not None
                    else max(0.0, (clip.duration - duration) / 2)
                )
                end = start + duration
                clip = clip.subclipped(start, end) if hasattr(clip, "subclipped") else clip.subclip(start, end)
        else:
            clip = ImageClip(path)
        clip = self._resize_cover(clip)
        return self._with_duration(clip, duration)

    def _load_background_sequence(
        self,
        paths: List[str],
        kind: str,
        duration: float,
        segments: List[SubtitleSegment],
        min_duration: float,
        target_duration: float,
        max_duration: float,
        sensitivity: str,
    ):
        valid_paths = [path for path in paths if path and os.path.exists(path)]
        if not valid_paths:
            return self._load_background(paths[0], kind, duration)

        durations = self._semantic_background_durations(
            duration,
            segments,
            min_duration,
            target_duration,
            max_duration,
            sensitivity,
        )
        assets = self._inspect_background_assets(valid_paths, kind)
        selector = AdaptiveBackgroundSelector(assets)
        clips = []
        cursor = 0.0
        for current_duration in durations:
            text = self._text_for_range(cursor, cursor + current_duration, segments)
            selected = selector.select(text, current_duration)
            clips.append(
                self._load_background(
                    selected.asset.path,
                    kind,
                    current_duration,
                    selected.source_start,
                )
            )
            print(
                f"[Background] {cursor:.2f}-{cursor + current_duration:.2f}s "
                f"{Path(selected.asset.path).name} @ {selected.source_start:.2f}s"
            )
            cursor += current_duration
        return self._with_duration(concatenate_videoclips(clips, method="chain"), duration)

    def _inspect_background_assets(self, paths: List[str], kind: str) -> List[BackgroundAsset]:
        if kind != "video":
            return [BackgroundAsset.from_path(path, float("inf"), "image") for path in paths]
        assets = []
        for path in paths:
            probe = VideoFileClip(path)
            try:
                assets.append(BackgroundAsset.from_path(path, float(probe.duration), "video"))
            finally:
                probe.close()
        return assets

    def _semantic_background_durations(
        self,
        duration: float,
        segments: List[SubtitleSegment],
        min_duration: float,
        target_duration: float,
        max_duration: float,
        sensitivity: str,
    ) -> List[float]:
        min_duration = max(1.0, float(min_duration or 4.0))
        max_duration = max(min_duration, float(max_duration or 10.0))
        target_duration = min(max_duration, max(min_duration, float(target_duration or 7.0)))
        if not segments:
            return self._fixed_background_durations(duration, target_duration)

        durations = []
        cursor = 0.0
        while duration - cursor > 0.001:
            end = self._next_semantic_boundary(
                cursor,
                duration,
                segments,
                min_duration,
                target_duration,
                max_duration,
                sensitivity,
            )
            if end <= cursor:
                end = min(duration, cursor + target_duration)
            durations.append(end - cursor)
            cursor = end
        return durations or [duration]

    def _next_semantic_boundary(
        self,
        cursor: float,
        duration: float,
        segments: List[SubtitleSegment],
        min_duration: float,
        target_duration: float,
        max_duration: float,
        sensitivity: str,
    ) -> float:
        minimum = cursor + min_duration
        maximum = min(duration, cursor + max_duration)
        target = min(maximum, max(minimum, cursor + target_duration))
        remaining = duration - cursor
        if remaining <= min_duration:
            return duration

        candidates = [
            segment.end
            for segment in segments
            if minimum <= segment.end <= maximum
            and (
                duration - segment.end >= min_duration
                or duration - segment.end < 0.001
            )
        ]
        natural = [
            boundary for boundary in candidates
            if self._is_sentence_boundary(boundary, segments)
        ]
        boundary_pool = natural or candidates
        threshold = CUT_THRESHOLDS.get(sensitivity, 0.45)
        worthwhile = [
            (boundary, self._change_at(cursor, boundary, duration, segments, target_duration))
            for boundary in boundary_pool
        ]
        worthwhile = [item for item in worthwhile if item[1] >= threshold]
        if worthwhile:
            return min(worthwhile, key=lambda item: (abs(item[0] - target), -item[1]))[0]

        if remaining <= max_duration:
            return duration
        if boundary_pool:
            latest_boundary = max(boundary_pool)
            if latest_boundary >= target:
                return latest_boundary
        if duration - maximum < min_duration:
            return duration - min_duration
        return maximum

    def _change_at(
        self,
        start: float,
        boundary: float,
        duration: float,
        segments: List[SubtitleSegment],
        target_duration: float,
    ) -> float:
        left = self._visual_intent(self._text_for_range(start, boundary, segments))
        right_end = min(duration, boundary + target_duration)
        right = self._visual_intent(self._text_for_range(boundary, right_end, segments))
        return self._change_strength(left, right)

    def _visual_intent(self, text: str) -> dict:
        lowered = text.lower()
        words = [word.lower() for word in WORD_PATTERN.findall(text)]
        keywords = tuple(dict.fromkeys(word for word in words if word not in STOPWORDS))
        if any(token in lowered for token in ("fight", "hard", "war", "战", "斗", "困难")):
            emotion = "intense"
        elif any(token in lowered for token in ("hope", "dream", "future", "希望", "梦想", "未来")):
            emotion = "hopeful"
        elif any(token in lowered for token in ("fail", "pain", "alone", "失败", "痛", "孤独")):
            emotion = "reflective"
        else:
            emotion = "neutral"
        return {"theme": self._visual_theme(lowered, keywords), "emotion": emotion, "keywords": keywords}

    def _visual_theme(self, lowered: str, keywords: tuple) -> str:
        scores = {
            theme: sum(token in lowered for token in hints)
            for theme, hints in THEME_HINTS.items()
        }
        best_theme, best_score = max(scores.items(), key=lambda item: item[1])
        if best_score:
            return best_theme
        return "general:" + ":".join(keywords[:2]) if keywords else "general"

    def _change_strength(self, left: dict, right: dict) -> float:
        if not right["keywords"]:
            return 0.0
        if left["theme"] == right["theme"]:
            theme_change = 0.0
        elif left["theme"].startswith("general") and right["theme"].startswith("general"):
            theme_change = 0.35
        else:
            theme_change = 0.65

        left_words, right_words = set(left["keywords"]), set(right["keywords"])
        union = left_words | right_words
        similarity = len(left_words & right_words) / len(union) if union else 1.0
        semantic_change = 0.3 * (1.0 - similarity)
        emotion_change = 0.2 if left["emotion"] != right["emotion"] else 0.0
        return min(1.0, theme_change + semantic_change + emotion_change)

    def _is_sentence_boundary(self, boundary: float, segments: List[SubtitleSegment]) -> bool:
        for segment in segments:
            if abs(segment.end - boundary) < 0.001:
                english = segment.english.strip()
                chinese = segment.chinese.strip()
                return bool(re.search(r"[.!?][\"'”’\)\]]*$", english)) or chinese.endswith(SENTENCE_ENDINGS)
        return False

    def _text_for_range(self, start: float, end: float, segments: List[SubtitleSegment]) -> str:
        return " ".join(
            f"{segment.english} {segment.chinese}"
            for segment in segments
            if segment.end > start and segment.start < end
        )

    def _fixed_background_durations(self, duration: float, target_duration: float) -> List[float]:
        durations = []
        remaining = duration
        target_duration = max(1.0, target_duration)
        while remaining > 0.001:
            current = min(target_duration, remaining)
            durations.append(current)
            remaining -= current
        return durations or [duration]

    def _resize_cover(self, clip):
        if round(clip.w) == VIDEO_WIDTH and round(clip.h) == VIDEO_HEIGHT:
            return clip
        scale = max(VIDEO_WIDTH / clip.w, VIDEO_HEIGHT / clip.h)
        new_size = (int(clip.w * scale), int(clip.h * scale))
        clip = clip.resized(new_size=new_size) if hasattr(clip, "resized") else clip.resize(newsize=new_size)
        x1 = max(0, (clip.w - VIDEO_WIDTH) // 2)
        y1 = max(0, (clip.h - VIDEO_HEIGHT) // 2)
        return clip.cropped(x1=x1, y1=y1, width=VIDEO_WIDTH, height=VIDEO_HEIGHT) if hasattr(clip, "cropped") else clip.crop(x1=x1, y1=y1, width=VIDEO_WIDTH, height=VIDEO_HEIGHT)

    def _timed_subtitle_layers(
        self,
        segments: List[SubtitleSegment],
        duration: float,
        orientation: str = "portrait",
        time_offset: float = 0.0,
        chinese_top: bool = False,
        y_offset: int = 0,
        minimum_y: Optional[int] = None,
        strict_lines: bool = False,
    ):
        layers = []
        if not segments:
            return layers
        for seg in segments:
            start = max(0.0, seg.start)
            end = min(duration, seg.end or duration)
            if end <= start:
                continue
            image = self.subtitle_renderer.render_card(
                seg.english,
                seg.chinese,
                chinese_top=chinese_top,
                max_english_lines=2 if strict_lines else None,
                max_chinese_lines=2 if strict_lines else None,
            )
            card_y = self._subtitle_position(
                image.height,
                orientation,
                y_offset=y_offset,
                minimum_y=minimum_y,
            )
            layers.append(
                self._with_position(
                    self._with_start(
                        self._with_duration(ImageClip(np.array(image)), end - start),
                        start + time_offset,
                    ),
                    ("center", card_y),
                )
            )
        return layers

    @staticmethod
    def _subtitle_position(
        content_height: int,
        orientation: str,
        y_offset: int = 0,
        minimum_y: Optional[int] = None,
    ) -> int:
        card_y = SUBTITLE.position_y(VIDEO_HEIGHT, content_height, orientation) + y_offset
        if minimum_y is not None:
            card_y = max(minimum_y, card_y)
        return max(0, min(VIDEO_HEIGHT - content_height, card_y))

    def _announcement_subtitle_layers(
        self,
        audio_path: Path,
        captions: List[Tuple[str, str]],
        duration: float,
        start: float = 0.0,
        chinese_top: bool = True,
        y_offset: int = -50,
        minimum_y: Optional[int] = None,
        boundary_shift: float = 0.0,
        recognize_fixed_audio: bool = False,
    ):
        segments = (
            self.fixed_audio_subtitles.segments_for(audio_path, duration, captions)
            if recognize_fixed_audio
            else align_captions_to_audio(audio_path, captions, duration)
        )
        if boundary_shift and len(segments) > 1:
            segments = [segment.model_copy(deep=True) for segment in segments]
            for index in range(1, len(segments)):
                boundary = max(
                    segments[index - 1].start + 0.1,
                    segments[index].start + boundary_shift,
                )
                boundary = min(segments[index].end - 0.1, boundary)
                segments[index - 1].end = boundary
                segments[index].start = boundary
        return self._timed_subtitle_layers(
            segments,
            duration,
            orientation="landscape",
            time_offset=start,
            chinese_top=chinese_top,
            y_offset=y_offset,
            minimum_y=minimum_y,
        )

    def _fixed_subtitle_layers(self, chinese: str, english: str, duration: float, start: float = 0.0, chinese_top: bool = True):
        image = self.subtitle_renderer.render_card(english, chinese, chinese_top=chinese_top)
        return [
            self._with_position(
                self._with_start(self._with_duration(ImageClip(np.array(image)), duration), start),
                ("center", VIDEO_HEIGHT - SUBTITLE.bottom - image.height),
            )
        ]

    def _text_image(self, text: str, font_size: int, fill: Tuple[int, int, int, int], box: Tuple[int, int]):
        image = Image.new("RGBA", box, (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        font = self._font(font_size)
        bbox = draw.textbbox((0, 0), text, font=font)
        x = (box[0] - (bbox[2] - bbox[0])) // 2
        y = (box[1] - (bbox[3] - bbox[1])) // 2
        draw.text((x, y), text, font=font, fill=fill)
        return image

    def _print_metadata(self, metadata: ExamMetadata) -> None:
        print("[Render Metadata]")
        print(f"Exam: {metadata.exam_full_title}")
        print(f"Level: {metadata.exam_level}")
        print(f"Section: {metadata.section_cn}")
        print(f"Topic: {metadata.topic_cn}")

    def _image_clip_from_frame(self, frame, filename: str):
        if frame is None:
            image = Image.new("RGB", self.size, "#f2eee8")
        else:
            image = Image.fromarray(frame).convert("RGB")
        path = TEMP_DIR / filename
        image.save(path)
        return ImageClip(str(path))

    def _audio_or_none(self, path: Path):
        if path and path.exists():
            return AudioFileClip(str(path))
        print(f"警告: 音频不存在: {path}")
        return None

    def _font(self, size: int):
        return load_font(size, "bold")

    def _with_duration(self, clip, duration: float):
        return clip.with_duration(duration) if hasattr(clip, "with_duration") else clip.set_duration(duration)

    def _with_audio(self, clip, audio):
        return clip.with_audio(audio) if hasattr(clip, "with_audio") else clip.set_audio(audio)

    def _with_position(self, clip, position):
        return clip.with_position(position) if hasattr(clip, "with_position") else clip.set_position(position)

    def _with_start(self, clip, start: float):
        return clip.with_start(start) if hasattr(clip, "with_start") else clip.set_start(start)

    def _compose_layers(self, layers):
        """以首层作为不透明背景，避免每帧重复创建并合成全画幅画布。"""
        if not layers:
            raise ValueError("视频合成至少需要一个图层")
        if len(layers) == 1:
            return layers[0]
        return CompositeVideoClip(layers, size=self.size, use_bgclip=True)
