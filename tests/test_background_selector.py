from app.services.background_selector import AdaptiveBackgroundSelector, BackgroundAsset


def test_selector_uses_every_available_asset_before_reusing_any():
    assets = [
        BackgroundAsset(f"asset-{index}.mp4", 30.0, tags=("rice",))
        for index in range(3)
    ]
    selector = AdaptiveBackgroundSelector(assets, seed=7)

    first_round = [selector.select("rice", 5.0).asset.path for _ in range(3)]
    fourth = selector.select("rice", 5.0).asset.path

    assert len(set(first_round)) == 3
    assert fourth in set(first_round)


def test_selector_uses_non_overlapping_ranges_before_overlap_fallback():
    selector = AdaptiveBackgroundSelector(
        [BackgroundAsset("long.mp4", 15.0, tags=("rice",))],
        seed=3,
    )

    selections = [selector.select("rice", 5.0) for _ in range(3)]
    ranges = sorted((item.source_start, item.source_start + 5.0) for item in selections)

    assert all(left[1] <= right[0] + 0.001 for left, right in zip(ranges, ranges[1:]))
