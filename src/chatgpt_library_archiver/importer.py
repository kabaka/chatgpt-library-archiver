"""Utilities for importing arbitrary images into the gallery."""

from __future__ import annotations

import mimetypes
import re
import shutil
import unicodedata
import uuid
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from openai import OpenAI

from . import gallery, tagger, thumbnails
from .ai import AIRequestTelemetry, call_image_endpoint, get_cached_client
from .metadata import GalleryItem, load_gallery_items, save_gallery_items
from .status import StatusReporter
from .utils import prompt_yes_no

IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    ".bmp",
    ".tiff",
    ".tif",
}

DEFAULT_RENAME_PROMPT = (
    "Create a short, descriptive filename slug (kebab-case, <=6 words) for this image."
)


@dataclass
class ImportItem:
    """Represents a single image scheduled for import."""

    source: Path
    conversation_link: str | None = None


def _is_image_file(path: Path) -> bool:
    if not path.is_file():
        return False
    ext = path.suffix.lower()
    if ext in IMAGE_EXTENSIONS:
        return True
    mime, _ = mimetypes.guess_type(path)
    return bool(mime and mime.startswith("image/"))


def _slugify(text: str, fallback: str = "image") -> str:
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    ascii_text = ascii_text.lower()
    ascii_text = re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-")
    return ascii_text or fallback


def _unique_filename(base: str, ext: str, existing: set[str]) -> str:
    candidate = f"{base}{ext}"
    counter = 2
    while candidate in existing:
        candidate = f"{base}-{counter}{ext}"
        counter += 1
    existing.add(candidate)
    return candidate


def _collect_inputs(
    inputs: Sequence[str], recursive: bool
) -> tuple[list[ImportItem], list[Path]]:
    items: list[ImportItem] = []
    original_files: list[Path] = []
    for raw in inputs:
        path = Path(raw)
        if not path.exists():
            raise FileNotFoundError(f"Input path not found: {path}")
        if path.is_file():
            items.append(ImportItem(source=path))
            original_files.append(path)
            continue
        if not recursive:
            raise ValueError(
                f"Directory '{path}' provided but --recursive flag not set."
            )
        for child in sorted(path.rglob("*")):
            if _is_image_file(child):
                items.append(ImportItem(source=child))
    return items, original_files


def _prepare_ai_client(
    *,
    config_path: str,
    model: str | None,
    allow_interactive: bool | None,
) -> tuple[OpenAI, str, str]:
    cfg = tagger.ensure_tagging_config(
        config_path,
        model=model,
        allow_interactive=allow_interactive,
    )
    client = get_cached_client(cfg.api_key)
    use_model = model or cfg.model
    rename_prompt = cfg.rename_prompt or DEFAULT_RENAME_PROMPT
    return client, use_model, rename_prompt


def _generate_ai_slug(
    client: OpenAI,
    model: str,
    prompt: str,
    image_path: Path,
    *,
    reporter: StatusReporter | None = None,
) -> tuple[str | None, AIRequestTelemetry]:
    def on_retry(attempt: int, delay: float) -> None:
        if reporter is not None:
            reporter.log_status(
                "Rate limited",
                f"{image_path.name} (retry {attempt} in {delay:.1f}s)",
            )

    text, telemetry, _usage = call_image_endpoint(
        client=client,
        model=model,
        prompt=prompt,
        image_path=image_path,
        operation="rename",
        subject=image_path.name,
        on_retry=on_retry,
        max_output_tokens=50,
    )
    slug = _slugify(text)
    return (slug or None), telemetry


def import_images(
    *,
    inputs: Sequence[str],
    gallery_root: str = "gallery",
    copy_files: bool = False,
    recursive: bool = False,
    tags: Iterable[str] | None = None,
    title: str | None = None,
    conversation_links: Sequence[str] | None = None,
    tag_new: bool = False,
    config_path: str = "tagging_config.json",
    ai_rename: bool = False,
    rename_model: str | None = None,
    rename_prompt: str | None = None,
    tag_prompt: str | None = None,
    tag_model: str | None = None,
    tag_workers: int = 4,
    allow_interactive: bool | None = None,
    telemetry_sink: Callable[[AIRequestTelemetry], None] | None = None,
) -> list[GalleryItem]:
    if not inputs:
        raise ValueError("No inputs supplied for import.")

    items, direct_files = _collect_inputs(inputs, recursive)

    if not items:
        raise ValueError("No importable images were found.")

    if conversation_links:
        if len(conversation_links) != len(direct_files):
            raise ValueError(
                "Number of --conversation-link values must match direct file inputs."
            )
        link_map = {
            path: link
            for path, link in zip(direct_files, conversation_links, strict=False)
        }
        for item in items:
            if item.source in link_map:
                item.conversation_link = link_map[item.source]

    gallery_path = Path(gallery_root)
    images_dir = gallery_path / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    data = load_gallery_items(gallery_path)
    existing_files = {entry.filename for entry in data if entry.filename}

    tags_list: list[str] = []
    if tags:
        for tag in tags:
            parts = [p.strip() for p in tag.split(",")]
            tags_list.extend([p for p in parts if p])

    if not prompt_yes_no(
        f"Import {len(items)} image(s) into {gallery_path}?", default=True
    ):
        return []

    ai_client: OpenAI | None = None
    ai_model: str | None = None
    ai_prompt: str | None = None
    if ai_rename:
        ai_client, ai_model, cfg_prompt = _prepare_ai_client(
            config_path=config_path,
            model=rename_model,
            allow_interactive=allow_interactive,
        )
        ai_prompt = rename_prompt or cfg_prompt

    imported: list[GalleryItem] = []

    with StatusReporter(
        total=len(items), description="Importing images", unit="img"
    ) as reporter:
        for item in items:
            source_path = item.source
            if not _is_image_file(source_path):
                reporter.advance()
                continue

            reporter.log_status("Importing", source_path.name)

            slug: str | None = None
            if ai_client is not None and ai_model is not None:
                try:
                    slug, telemetry = _generate_ai_slug(
                        ai_client,
                        ai_model,
                        ai_prompt or DEFAULT_RENAME_PROMPT,
                        source_path,
                        reporter=reporter,
                    )
                    if telemetry_sink is not None:
                        telemetry_sink(telemetry)
                    if telemetry.total_tokens is not None:
                        reporter.log_status(
                            "AI rename",
                            (
                                f"{source_path.name} tokens: {telemetry.total_tokens}, "
                                f"latency: {telemetry.latency_s:.2f}s"
                            ),
                        )
                except Exception:
                    slug = None

            if not slug:
                slug = _slugify(source_path.stem)

            ext = source_path.suffix.lower() or ".jpg"
            filename = _unique_filename(slug, ext, existing_files)
            dest = images_dir / filename

            dest.parent.mkdir(parents=True, exist_ok=True)
            if copy_files:
                shutil.copy2(source_path, dest)
            else:
                shutil.move(source_path, dest)

            created_at = datetime.now(timezone.utc).timestamp()
            thumb_rels = thumbnails.thumbnail_relative_paths(filename)
            thumb_paths = {size: gallery_path / rel for size, rel in thumb_rels.items()}
            thumbnails.create_thumbnails(dest, thumb_paths, reporter=reporter)

            record = GalleryItem(
                id=uuid.uuid4().hex,
                filename=filename,
                title=title or slug.replace("-", " ").title(),
                prompt=None,
                tags=list(tags_list),
                created_at=created_at,
                width=None,
                height=None,
                url=None,
                conversation_id=None,
                message_id=None,
                conversation_link=item.conversation_link,
                thumbnails=thumb_rels,
                thumbnail=thumb_rels["medium"],
            )
            data.append(record)
            imported.append(record)
            reporter.advance()

    thumbnails.regenerate_thumbnails(gallery_path, data)
    save_gallery_items(gallery_path, data)

    if imported:
        if tag_new:
            ids = [entry.id for entry in imported]
            tagger.tag_images(
                gallery_root=str(gallery_path),
                ids=ids,
                config_path=config_path,
                prompt=tag_prompt,
                model=tag_model,
                max_workers=tag_workers,
                allow_interactive=allow_interactive,
                telemetry_sink=telemetry_sink,
            )
        gallery.generate_gallery(gallery_root=str(gallery_path))

    return imported


def regenerate_thumbnails(*, gallery_root: str, force: bool = False) -> list[str]:
    gallery_path = Path(gallery_root)
    data = load_gallery_items(gallery_path)
    if not data:
        return []
    with StatusReporter(
        description="Regenerating thumbnails", unit="thumb"
    ) as reporter:
        processed, updated = thumbnails.regenerate_thumbnails(
            gallery_path, data, force=force, reporter=reporter
        )
    if updated:
        save_gallery_items(gallery_path, data)
    return processed
