"""Shared pytest fixtures for chatgpt-library-archiver test suite."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from PIL import Image


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers."""
    config.addinivalue_line(
        "markers", "slow: marks tests as slow (deselected by default)"
    )
    config.addinivalue_line(
        "markers",
        "integration: marks integration tests requiring external resources",
    )


def _make_sample_png() -> bytes:
    """Create a minimal valid PNG image."""
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), color=(10, 20, 30)).save(buf, format="PNG")
    return buf.getvalue()


SAMPLE_PNG = _make_sample_png()


@pytest.fixture
def sample_png_bytes() -> bytes:
    """Minimal valid 8x8 PNG image bytes."""
    return SAMPLE_PNG


@pytest.fixture
def gallery_dir(tmp_path: Path) -> Path:
    """Isolated gallery directory with images/ and thumbs/ subdirectories."""
    gallery = tmp_path / "gallery"
    gallery.mkdir()
    (gallery / "images").mkdir()
    (gallery / "thumbs" / "small").mkdir(parents=True)
    (gallery / "thumbs" / "medium").mkdir(parents=True)
    (gallery / "thumbs" / "large").mkdir(parents=True)
    return gallery


@pytest.fixture
def write_metadata():
    """Return a callable that writes metadata.json under a gallery root.

    Usage::

        gallery = write_metadata(tmp_path / "gallery", items)
        gallery = write_metadata(tmp_path / "gallery", items, create_images=True)
    """

    def _write(
        root: Path, items: list[dict[str, object]], *, create_images: bool = False
    ) -> Path:
        (root / "images").mkdir(parents=True, exist_ok=True)
        with open(root / "metadata.json", "w", encoding="utf-8") as f:
            json.dump(items, f)
        if create_images:
            for item in items:
                (root / "images" / str(item["filename"])).write_text("img")
        return root

    return _write
