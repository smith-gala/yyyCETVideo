import numpy as np
from moviepy import ImageClip

from app.pipeline.video_pipeline import VideoPipeline


def _pipeline(size=(8, 8)):
    pipeline = VideoPipeline.__new__(VideoPipeline)
    pipeline.size = size
    return pipeline


def test_compose_layers_returns_single_background_without_compositor():
    background = ImageClip(np.zeros((8, 8, 3), dtype=np.uint8)).with_duration(1)
    try:
        assert _pipeline()._compose_layers([background]) is background
    finally:
        background.close()


def test_compose_layers_preserves_background_and_alpha_overlay_pixels():
    background_array = np.full((8, 8, 3), (20, 40, 60), dtype=np.uint8)
    overlay_array = np.zeros((4, 4, 4), dtype=np.uint8)
    overlay_array[..., :3] = (220, 120, 20)
    overlay_array[..., 3] = 128
    background = ImageClip(background_array).with_duration(1)
    overlay = ImageClip(overlay_array).with_duration(1).with_position((2, 2))
    composite = _pipeline()._compose_layers([background, overlay]).with_duration(1)
    try:
        frame = composite.get_frame(0)
        assert np.array_equal(frame[0, 0], background_array[0, 0])
        expected_blend = np.array([120, 80, 40])
        assert np.all(np.abs(frame[3, 3].astype(int) - expected_blend) <= 1)
    finally:
        composite.close()
        overlay.close()
        background.close()
