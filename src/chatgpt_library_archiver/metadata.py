"""Typed models and helpers for gallery metadata persistence."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


def metadata_path(gallery_root: str | Path) -> Path:
    """Return the path to ``metadata.json`` for ``gallery_root``."""

    return Path(gallery_root) / "metadata.json"


def normalize_created_at(value: Any) -> float | None:
    """Convert assorted ``created_at`` values into a float timestamp."""

    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            if text.endswith("Z"):
                text = text[:-1] + "+00:00"
            try:
                return datetime.fromisoformat(text).timestamp()
            except ValueError:
                return None
    return None


def created_at_sort_key(value: Any) -> float:
    """Return a sortable timestamp for ``created_at`` values."""

    normalized = normalize_created_at(value)
    return normalized if normalized is not None else 0.0


@dataclass(slots=True)
class GalleryItem:
    """Typed representation of a gallery item."""

    id: str
    filename: str
    title: str = ""
    prompt: str | None = None
    tags: list[str] = field(default_factory=list)
    created_at: float | None = None
    width: int | None = None
    height: int | None = None
    url: str | None = None
    conversation_id: str | None = None
    message_id: str | None = None
    conversation_link: str | None = None
    thumbnails: dict[str, str] = field(default_factory=dict)
    thumbnail: str | None = None
    checksum: str | None = None
    content_type: str | None = None
    extra: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> GalleryItem:
        """Create an item from a JSON-compatible mapping."""

        known = {
            "id": str(data.get("id", "")),
            "filename": data.get("filename", ""),
            "title": data.get("title", "") or "",
            "prompt": data.get("prompt"),
            "tags": list(data.get("tags") or []),
            "created_at": normalize_created_at(data.get("created_at")),
            "width": data.get("width"),
            "height": data.get("height"),
            "url": data.get("url"),
            "conversation_id": data.get("conversation_id"),
            "message_id": data.get("message_id"),
            "conversation_link": data.get("conversation_link"),
            "thumbnails": dict(data.get("thumbnails") or {}),
            "thumbnail": data.get("thumbnail"),
            "checksum": data.get("checksum"),
            "content_type": data.get("content_type"),
        }
        extras = {key: value for key, value in data.items() if key not in known}
        return cls(**known, extra=extras)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation of the item."""

        payload: dict[str, Any] = {
            "id": self.id,
            "filename": self.filename,
            "title": self.title,
            "prompt": self.prompt,
            "tags": list(self.tags),
            "created_at": self.created_at,
            "width": self.width,
            "height": self.height,
            "url": self.url,
            "conversation_id": self.conversation_id,
            "message_id": self.message_id,
            "conversation_link": self.conversation_link,
            "thumbnails": dict(self.thumbnails),
            "thumbnail": self.thumbnail,
            "checksum": self.checksum,
            "content_type": self.content_type,
        }
        payload.update(self.extra)
        return payload


def load_gallery_items(gallery_root: str | Path) -> list[GalleryItem]:
    """Load all gallery items for ``gallery_root``."""

    path = metadata_path(gallery_root)
    if not path.is_file():
        return []
    with open(path, encoding="utf-8") as fh:
        raw_items = json.load(fh)
    items: list[GalleryItem] = []
    for raw in raw_items:
        if isinstance(raw, Mapping):
            items.append(GalleryItem.from_dict(raw))
    return items


def save_gallery_items(gallery_root: str | Path, items: Iterable[GalleryItem]) -> None:
    """Persist ``items`` to ``metadata.json`` within ``gallery_root``."""

    path = metadata_path(gallery_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump([item.to_dict() for item in items], fh, indent=2)
