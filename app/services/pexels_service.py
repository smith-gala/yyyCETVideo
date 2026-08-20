"""
Pexels素材搜索和下载服务。
"""
import json
import mimetypes
import os
from pathlib import Path
from typing import List, Optional

import requests
from dotenv import load_dotenv

from app.config import PEXELS_API_KEY, PEXELS_PHOTOS_DIR, PEXELS_VIDEOS_DIR
from app.models import PexelsAsset


class PexelsService:
    """Search and download Pexels background assets."""

    BASE_URL = "https://api.pexels.com"

    def __init__(self, api_key: Optional[str] = None):
        load_dotenv(override=True)
        self.api_key = api_key or os.getenv("PEXELS_API_KEY", "") or PEXELS_API_KEY

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def search(self, query: str, kind: str, orientation: str, per_page: int = 30) -> List[PexelsAsset]:
        if not self.api_key:
            raise RuntimeError("PEXELS_API_KEY未配置")

        per_page = max(1, min(int(per_page), 80))
        if kind == "photo":
            return self._search_photos(query, orientation, per_page)
        return self._search_videos(query, orientation, per_page)

    def download(self, asset: PexelsAsset, directory: Optional[Path] = None) -> Optional[PexelsAsset]:
        if not asset.download_url:
            return None

        directory = directory or (PEXELS_PHOTOS_DIR if asset.kind == "photo" else PEXELS_VIDEOS_DIR)
        directory.mkdir(parents=True, exist_ok=True)
        extension = self._guess_extension(asset.download_url, "jpg" if asset.kind == "photo" else "mp4")
        filename = f"{asset.kind}_{asset.asset_id}_{asset.orientation}.{extension}"
        output_path = directory / filename

        if output_path.exists():
            asset.local_path = str(output_path)
            self._write_asset_metadata(output_path, asset)
            return asset

        headers = {"Authorization": self.api_key}
        response = requests.get(asset.download_url, headers=headers, timeout=120, stream=True)
        response.raise_for_status()

        with open(output_path, "wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 256):
                if chunk:
                    handle.write(chunk)

        asset.local_path = str(output_path)
        self._write_asset_metadata(output_path, asset)
        return asset

    def download_single_image(
        self,
        asset: PexelsAsset,
        directory: Path,
        filename: str = "background.jpg",
    ) -> Optional[PexelsAsset]:
        """下载并替换单图背景，保证目录内最终只有固定文件。"""
        if asset.kind != "photo":
            raise ValueError("单图背景只能使用 Pexels 图片")
        if not asset.download_url:
            return None

        safe_filename = Path(filename).name
        if not safe_filename or safe_filename != filename:
            raise ValueError("背景文件名无效")

        directory.mkdir(parents=True, exist_ok=True)
        output_path = directory / safe_filename
        temporary_path = directory / f".{safe_filename}.download"
        headers = {"Authorization": self.api_key}

        try:
            response = requests.get(asset.download_url, headers=headers, timeout=120, stream=True)
            response.raise_for_status()
            with open(temporary_path, "wb") as handle:
                for chunk in response.iter_content(chunk_size=1024 * 256):
                    if chunk:
                        handle.write(chunk)
            os.replace(temporary_path, output_path)
        finally:
            if temporary_path.exists():
                temporary_path.unlink()

        for path in directory.iterdir():
            if path.is_file() and path != output_path:
                path.unlink()

        asset.local_path = str(output_path)
        return asset

    @staticmethod
    def _write_asset_metadata(path: Path, asset: PexelsAsset) -> None:
        metadata_path = path.with_name(f"{path.name}.asset.json")
        metadata_path.write_text(
            json.dumps(
                {
                    "asset_id": asset.asset_id,
                    "title": asset.title,
                    "author": asset.author,
                    "pexels_url": asset.pexels_url,
                    "orientation": asset.orientation,
                    "duration": asset.duration,
                    "fps": asset.fps,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def _search_photos(self, query: str, orientation: str, per_page: int) -> List[PexelsAsset]:
        response = requests.get(
            f"{self.BASE_URL}/v1/search",
            headers={"Authorization": self.api_key},
            params={"query": query, "orientation": orientation, "per_page": per_page, "locale": "zh-CN"},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()

        assets = []
        for item in data.get("photos", []):
            src = item.get("src", {})
            assets.append(PexelsAsset(
                asset_id=str(item.get("id", "")),
                kind="photo",
                title=item.get("alt") or query,
                author=item.get("photographer", ""),
                preview_url=src.get("medium") or src.get("large") or "",
                download_url=src.get("large2x") or src.get("original") or src.get("large") or "",
                pexels_url=item.get("url", ""),
                orientation=orientation,
                width=int(item.get("width") or 0),
                height=int(item.get("height") or 0),
            ))
        return assets

    def _search_videos(self, query: str, orientation: str, per_page: int) -> List[PexelsAsset]:
        response = requests.get(
            f"{self.BASE_URL}/videos/search",
            headers={"Authorization": self.api_key},
            params={"query": query, "orientation": orientation, "per_page": per_page, "locale": "zh-CN"},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()

        assets = []
        for item in data.get("videos", []):
            files = item.get("video_files", [])
            best = self._select_video_file(files, orientation)
            if not best:
                continue
            assets.append(PexelsAsset(
                asset_id=str(item.get("id", "")),
                kind="video",
                title=query,
                author=item.get("user", {}).get("name", ""),
                preview_url=best.get("link", ""),
                download_url=best.get("link", ""),
                pexels_url=item.get("url", ""),
                orientation=orientation,
                width=int(best.get("width") or item.get("width") or 0),
                height=int(best.get("height") or item.get("height") or 0),
                duration=float(item.get("duration") or 0),
                fps=float(best.get("fps") or 0),
            ))
        return assets

    def _select_video_file(self, files: list, orientation: str) -> dict:
        target = {
            "portrait": (1080, 1920),
            "landscape": (1920, 1080),
            "square": (1080, 1080),
        }.get(orientation, (1080, 1920))

        candidates = []
        for item in files:
            if not isinstance(item, dict):
                continue
            try:
                width = int(item.get("width") or 0)
                height = int(item.get("height") or 0)
                fps = float(item.get("fps") or 0)
            except (TypeError, ValueError):
                continue
            if not item.get("link") or item.get("file_type") != "video/mp4" or width <= 0 or height <= 0:
                continue
            if orientation == "portrait" and width >= height:
                continue
            if orientation == "landscape" and width <= height:
                continue
            candidates.append((self._quality_score(width, height, fps, target), item))
        return max(candidates, key=lambda value: value[0], default=(0, {}))[1]

    def _quality_score(self, width: int, height: int, fps: float, target: tuple) -> float:
        target_width, target_height = target
        ratio_error = abs((width / height) - (target_width / target_height))
        size_error = (
            abs(width - target_width) / target_width
            + abs(height - target_height) / target_height
        )
        exact_bonus = 100 if (width, height) == target else 0
        hd_bonus = 25 if (width, height) in {(720, 1280), (1280, 720)} else 0
        resolution_bonus = 50 * min(1.0, (width * height) / (target_width * target_height))
        fps_bonus = min(max(fps - 24, 0), 36) / 6
        return exact_bonus + hd_bonus + resolution_bonus + fps_bonus - ratio_error * 500 - size_error * 20

    def _guess_extension(self, url: str, fallback: str) -> str:
        content_type = mimetypes.guess_type(url.split("?", 1)[0])[0]
        extension = mimetypes.guess_extension(content_type or "")
        if extension:
            return extension.lstrip(".")
        basename = os.path.basename(url.split("?", 1)[0])
        if "." in basename:
            return basename.rsplit(".", 1)[1].lower()
        return fallback
