"""Typed models and helpers for gallery metadata persistence."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, cast


def metadata_path(gallery_root: str | Path) -> Path:
    """Return the path to ``metadata.json`` for ``gallery_root``."""

    return Path(gallery_root) / "metadata.json"


def normalize_created_at(value: Any) -> float | None:
    """Convert assorted ``created_at`` values into a float timestamp."""

    normalized: float | None
    if value is None:
        normalized = None
    elif isinstance(value, int | float):
        normalized = float(value)
    elif isinstance(value, str):
        text = value.strip()
        normalized = None if not text else _parse_created_at_string(text)
    else:
        normalized = None
    return normalized


def _parse_created_at_string(text: str) -> float | None:
    try:
        return float(text)
    except ValueError:
        normalized_text = text[:-1] + "+00:00" if text.endswith("Z") else text
        try:
            return datetime.fromisoformat(normalized_text).timestamp()
        except ValueError:
            return None


def _coerce_optional_int(value: Any) -> int | None:
    if isinstance(value, int | float):
        return int(value)
    return None


def _coerce_optional_str(value: Any) -> str | None:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return None


def created_at_sort_key(value: Any) -> float:
    """Return a sortable timestamp for ``created_at`` values."""

    normalized = normalize_created_at(value)
    return normalized if normalized is not None else 0.0


def _default_tags() -> list[str]:
    return []


def _default_thumbnail_map() -> dict[str, str]:
    return {}


def _default_extra() -> dict[str, Any]:
    return {}


@dataclass(slots=True)
class GalleryItem:
    """Typed representation of a gallery item."""

    id: str
    filename: str
    title: str = ""
    prompt: str | None = None
    tags: list[str] = field(default_factory=_default_tags)
    created_at: float | None = None
    width: int | None = None
    height: int | None = None
    url: str | None = None
    conversation_id: str | None = None
    message_id: str | None = None
    conversation_link: str | None = None
    thumbnails: dict[str, str] = field(default_factory=_default_thumbnail_map)
    thumbnail: str | None = None
    checksum: str | None = None
    content_type: str | None = None
    extra: dict[str, Any] = field(default_factory=_default_extra, repr=False)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> GalleryItem:
        """Create an item from a JSON-compatible mapping."""

        raw_thumbnails = data.get("thumbnails")
        extras = {
            key: value
            for key, value in data.items()
            if key
            not in {
                "id",
                "filename",
                "title",
                "prompt",
                "tags",
                "created_at",
                "width",
                "height",
                "url",
                "conversation_id",
                "message_id",
                "conversation_link",
                "thumbnails",
                "thumbnail",
                "checksum",
                "content_type",
            }
        }
        thumbnail_entries: dict[str, str] = {}
        if isinstance(raw_thumbnails, Mapping):
            for size_obj, path_obj in cast(
                Mapping[object, object], raw_thumbnails
            ).items():
                if isinstance(size_obj, str) and isinstance(path_obj, str):
                    thumbnail_entries[size_obj] = path_obj

        raw_tags = data.get("tags")
        tags: list[str] = []
        if isinstance(raw_tags, Iterable):
            for tag_obj in cast(Iterable[object], raw_tags):
                if isinstance(tag_obj, str):
                    tags.append(tag_obj)

        return cls(
            id=str(data.get("id", "")),
            filename=str(data.get("filename", "")),
            title=str(data.get("title", "") or ""),
            prompt=data.get("prompt"),
            tags=tags,
            created_at=normalize_created_at(data.get("created_at")),
            width=_coerce_optional_int(data.get("width")),
            height=_coerce_optional_int(data.get("height")),
            url=_coerce_optional_str(data.get("url")),
            conversation_id=_coerce_optional_str(data.get("conversation_id")),
            message_id=_coerce_optional_str(data.get("message_id")),
            conversation_link=_coerce_optional_str(data.get("conversation_link")),
            thumbnails=thumbnail_entries,
            thumbnail=_coerce_optional_str(data.get("thumbnail")),
            checksum=_coerce_optional_str(data.get("checksum")),
            content_type=_coerce_optional_str(data.get("content_type")),
            extra=extras,
        )

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
            items.append(GalleryItem.from_dict(cast(Mapping[str, Any], raw)))
    return items


def save_gallery_items(gallery_root: str | Path, items: Iterable[GalleryItem]) -> None:
    """Persist ``items`` to ``metadata.json`` within ``gallery_root``."""

    path = metadata_path(gallery_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump([item.to_dict() for item in items], fh, indent=2)
