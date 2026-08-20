from pathlib import Path

from app.models import PexelsAsset
from app.services.pexels_service import PexelsService


class _FakeResponse:
    def __init__(self, payload=None, chunks=None):
        self._payload = payload or {}
        self._chunks = chunks or []

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload

    def iter_content(self, chunk_size):
        yield from self._chunks


def test_photo_search_accepts_ten_preview_items(monkeypatch):
    captured = {}

    def fake_get(url, **kwargs):
        captured.update(kwargs["params"])
        return _FakeResponse({"photos": []})

    monkeypatch.setattr("app.services.pexels_service.requests.get", fake_get)

    PexelsService(api_key="test-key").search("tea", "photo", "portrait", per_page=10)

    assert captured["per_page"] == 10


def test_single_image_download_overwrites_fixed_file_and_removes_siblings(tmp_path, monkeypatch):
    material_dir = tmp_path / "cover"
    material_dir.mkdir()
    target = material_dir / "background.jpg"
    target.write_bytes(b"old image")
    (material_dir / "old.jpg").write_bytes(b"obsolete")
    (material_dir / "old.jpg.asset.json").write_text("{}", encoding="utf-8")

    monkeypatch.setattr(
        "app.services.pexels_service.requests.get",
        lambda *args, **kwargs: _FakeResponse(chunks=[b"new ", b"image"]),
    )
    asset = PexelsAsset(
        asset_id="123",
        kind="photo",
        download_url="https://images.pexels.com/photo.jpg",
    )

    downloaded = PexelsService(api_key="test-key").download_single_image(asset, material_dir)

    assert downloaded is not None
    assert downloaded.local_path == str(target)
    assert target.read_bytes() == b"new image"
    assert list(material_dir.iterdir()) == [target]


def test_single_image_download_rejects_video(tmp_path):
    asset = PexelsAsset(asset_id="456", kind="video", download_url="https://example.com/video.mp4")

    try:
        PexelsService(api_key="test-key").download_single_image(asset, Path(tmp_path))
    except ValueError as exc:
        assert "Pexels 图片" in str(exc)
    else:
        raise AssertionError("视频不应被当作单图背景下载")
