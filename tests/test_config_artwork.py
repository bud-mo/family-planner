"""Tests for the artwork slideshow interval config field."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from app.config import ArtworkConfig, load_config


def test_default_interval_is_30() -> None:
    assert ArtworkConfig().slideshow_interval_minutes == 30


def test_interval_below_one_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ArtworkConfig(slideshow_interval_minutes=0)


def test_interval_roundtrips() -> None:
    cfg = ArtworkConfig(slideshow_interval_minutes=10)
    restored = ArtworkConfig.model_validate(cfg.model_dump())
    assert restored.slideshow_interval_minutes == 10


def test_legacy_config_without_key_applies_default(tmp_path: Path) -> None:
    # A pre-v0.9.0 config that has no slideshow_interval_minutes must still load.
    path = tmp_path / "config.yaml"
    path.write_text(
        yaml.dump({"artwork": {"query": "x", "source": "endpoint", "folder": "pictures"}}),
        encoding="utf-8",
    )
    config = load_config(path)
    assert config.artwork.slideshow_interval_minutes == 30
