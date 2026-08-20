"""为正文时间线自适应选择背景素材和源视频片段。"""
from __future__ import annotations

import json
import random
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path


TOKEN_PATTERN = re.compile(r"[a-zA-Z0-9]+|[\u3400-\u9fff]{2,}")


@dataclass(frozen=True)
class BackgroundAsset:
    path: str
    duration: float
    media_type: str = "video"
    tags: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def from_path(cls, path: str, duration: float, media_type: str) -> "BackgroundAsset":
        return cls(path, duration, media_type, _load_tags(Path(path)))


@dataclass(frozen=True)
class BackgroundSelection:
    asset: BackgroundAsset
    source_start: float


class AdaptiveBackgroundSelector:
    """素材充足时优先不重复；不足时选择使用最少且重叠最小的片段。"""

    def __init__(self, assets: list[BackgroundAsset], seed: int = 0):
        if not assets:
            raise ValueError("没有可用的背景素材")
        self.assets = assets
        self.random = random.Random(seed)
        self.usage: Counter[str] = Counter()
        self.used_ranges: dict[str, list[tuple[float, float]]] = {}
        self.last_asset = ""

    def select(self, text: str, duration: float) -> BackgroundSelection:
        keywords = {token.lower() for token in TOKEN_PATTERN.findall(text)}
        long_enough = [asset for asset in self.assets if asset.duration >= duration]
        pool = long_enough or self.assets

        # 只要还有没用过的素材，就不重复；全部用完后才进入复用兜底。
        unused = [asset for asset in pool if self.usage[asset.path] == 0]
        if unused:
            pool = unused
        else:
            least_used = min(self.usage[asset.path] for asset in pool)
            pool = [asset for asset in pool if self.usage[asset.path] == least_used]

        alternatives = [asset for asset in pool if asset.path != self.last_asset]
        if alternatives:
            pool = alternatives

        def score(asset: BackgroundAsset) -> tuple[float, float]:
            relevance = len(keywords.intersection(asset.tags)) * 2
            duration_bonus = 0.2 if asset.duration >= duration else 0.0
            return relevance + duration_bonus, self.random.random()

        asset = max(pool, key=score)
        source_start = self._source_start(asset, duration)
        self.usage[asset.path] += 1
        self.last_asset = asset.path
        if asset.media_type == "video":
            source_end = min(asset.duration, source_start + duration)
            self.used_ranges.setdefault(asset.path, []).append((source_start, source_end))
        return BackgroundSelection(asset, round(source_start, 3))

    def _source_start(self, asset: BackgroundAsset, duration: float) -> float:
        if asset.media_type == "image" or asset.duration <= duration:
            return 0.0
        used = self._merged_ranges(self.used_ranges.get(asset.path, []))
        available = asset.duration - duration
        slots: list[tuple[float, float]] = []
        cursor = 0.0
        for start, end in used:
            if start - cursor >= duration:
                slots.append((cursor, start - duration))
            cursor = max(cursor, end)
        if asset.duration - cursor >= duration:
            slots.append((cursor, available))
        if slots:
            widest = max(end - start for start, end in slots)
            best = [slot for slot in slots if abs((slot[1] - slot[0]) - widest) < 0.001]
            start, end = self.random.choice(best)
            # 从空闲区间边缘取片段，避免随机落在中间把可用空间切碎。
            return self.random.choice((start, end)) if end > start else start

        # 素材已经没有完整空闲区间：选择与历史片段重叠最少的位置。
        candidates = {0.0, available}
        for start, end in used:
            candidates.add(max(0.0, min(available, start - duration)))
            candidates.add(max(0.0, min(available, end)))
        return min(
            candidates,
            key=lambda start: (
                self._overlap(start, start + duration, used),
                self.random.random(),
            ),
        )

    @staticmethod
    def _merged_ranges(ranges: list[tuple[float, float]]) -> list[tuple[float, float]]:
        merged: list[list[float]] = []
        for start, end in sorted(ranges):
            if not merged or start > merged[-1][1]:
                merged.append([start, end])
            else:
                merged[-1][1] = max(merged[-1][1], end)
        return [(start, end) for start, end in merged]

    @staticmethod
    def _overlap(start: float, end: float, ranges: list[tuple[float, float]]) -> float:
        return sum(
            max(0.0, min(end, used_end) - max(start, used_start))
            for used_start, used_end in ranges
        )


def _load_tags(path: Path) -> tuple[str, ...]:
    text_parts = [path.stem]
    sidecar = path.with_name(f"{path.name}.asset.json")
    if sidecar.is_file():
        try:
            payload = json.loads(sidecar.read_text(encoding="utf-8-sig"))
            text_parts.extend(
                str(payload.get(key, "")) for key in ("title", "query", "author")
            )
        except (OSError, ValueError, TypeError):
            pass
    return tuple(dict.fromkeys(token.lower() for token in TOKEN_PATTERN.findall(" ".join(text_parts))))
