from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_scrapling_profile_is_pinned_and_separate_from_base_requirements() -> None:
    base = (ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
    enhanced = (ROOT / "requirements-scrapling.txt").read_text(
        encoding="utf-8"
    ).lower()

    assert "scrapling" not in base
    assert "playwright" not in base
    assert "patchright" not in base
    assert "-r requirements.txt" in enhanced
    assert "scrapling[fetchers]==0.4.15" in enhanced


def test_default_image_remains_requests_only() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8").lower()

    assert "requirements-scrapling.txt" not in dockerfile
    assert "scrapling install" not in dockerfile
    assert "playwright install" not in dockerfile
    assert "chromium" not in dockerfile
