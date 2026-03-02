"""Utilities for importing arbitrary images into the gallery."""

from __future__ import annotations

import mimetypes
import re
import shutil
import unicodedata
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
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
class ImportConfig:
    """Configuration for an image import operation."""

    gallery_root: str = "gallery"
    copy_files: bool = False
    recursive: bool = False
    tags: list[str] = field(default_factory=list)
    title: str | None = None
    conversation_links: list[str] | None = None
    tag_new: bool = False
    config_path: str = "tagging_config.json"
    ai_rename: bool = False
    rename_model: str | None = None
    rename_prompt: str | None = None
    tag_prompt: str | None = None
    tag_model: str | None = None
    tag_workers: int = 4
    allow_interactive: bool | None = None
    telemetry_sink: Callable[[AIRequestTelemetry], None] | None = None

    def __post_init__(self) -> None:
        """Normalize tags by splitting comma-separated values."""
        normalized: list[str] = []
        for tag in self.tags:
            parts = [p.strip() for p in tag.split(",")]
            normalized.extend(p for p in parts if p)
        self.tags = normalized


@dataclass
class ImportItem:
    """Represents a single image scheduled for import."""

    source: Path
    conversation_link: str | None = None


@dataclass(slots=True)
class _AIContext:
    """Pre-resolved AI renaming dependencies."""

    client: OpenAI
    model: str
    prompt: str


@dataclass
class _ImportContext:
    """Mutable state for a single import run."""

    config: ImportConfig
    gallery_path: Path
    images_dir: Path
    existing_files: set[str]
    ai_ctx: _AIContext | None


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


def _apply_conversation_links(
    items: list[ImportItem],
    direct_files: list[Path],
    conversation_links: list[str] | None,
) -> None:
    """Attach conversation links to matching import items in-place."""
    if not conversation_links:
        return
    if len(conversation_links) != len(direct_files):
        raise ValueError(
            "Number of --conversation-link values must match direct file inputs."
        )
    link_map = dict(zip(direct_files, conversation_links, strict=False))
    for item in items:
        if item.source in link_map:
            item.conversation_link = link_map[item.source]


def _import_one_image(
    item: ImportItem,
    *,
    ctx: _ImportContext,
    reporter: StatusReporter,
) -> GalleryItem:
    """Import a single image file and return the created gallery item."""
    source_path = item.source
    reporter.log_status("Importing", source_path.name)

    slug: str | None = None
    if ctx.ai_ctx is not None:
        try:
            slug, telemetry = _generate_ai_slug(
                ctx.ai_ctx.client,
                ctx.ai_ctx.model,
                ctx.ai_ctx.prompt,
                source_path,
                reporter=reporter,
            )
            if ctx.config.telemetry_sink is not None:
                ctx.config.telemetry_sink(telemetry)
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
    filename = _unique_filename(slug, ext, ctx.existing_files)
    dest = ctx.images_dir / filename

    dest.parent.mkdir(parents=True, exist_ok=True)
    if ctx.config.copy_files:
        shutil.copy2(source_path, dest)
    else:
        shutil.move(source_path, dest)

    created_at = datetime.now(timezone.utc).timestamp()
    thumb_rels = thumbnails.thumbnail_relative_paths(filename)
    thumb_paths = {size: ctx.gallery_path / rel for size, rel in thumb_rels.items()}
    thumbnails.create_thumbnails(dest, thumb_paths, reporter=reporter)

    return GalleryItem(
        id=uuid.uuid4().hex,
        filename=filename,
        title=ctx.config.title or slug.replace("-", " ").title(),
        prompt=None,
        tags=list(ctx.config.tags),
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


def _run_post_import(
    imported: list[GalleryItem],
    config: ImportConfig,
    gallery_path: Path,
) -> None:
    """Run tagging and gallery generation after a successful import."""
    if config.tag_new:
        ids = [entry.id for entry in imported]
        tagger.tag_images(
            gallery_root=str(gallery_path),
            ids=ids,
            config_path=config.config_path,
            prompt=config.tag_prompt,
            model=config.tag_model,
            max_workers=config.tag_workers,
            allow_interactive=config.allow_interactive,
            telemetry_sink=config.telemetry_sink,
        )
    gallery.generate_gallery(gallery_root=str(gallery_path))


def import_images(
    *,
    inputs: Sequence[str],
    config: ImportConfig | None = None,
) -> list[GalleryItem]:
    """Import local images into the gallery.

    Parameters
    ----------
    inputs:
        File paths or directories to import.
    config:
        Import configuration.  Uses defaults when ``None``.
    """
    if config is None:
        config = ImportConfig()

    if not inputs:
        raise ValueError("No inputs supplied for import.")

    items, direct_files = _collect_inputs(inputs, config.recursive)

    if not items:
        raise ValueError("No importable images were found.")

    _apply_conversation_links(items, direct_files, config.conversation_links)

    gallery_path = Path(config.gallery_root)
    images_dir = gallery_path / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    data = load_gallery_items(gallery_path)
    existing_files = {entry.filename for entry in data if entry.filename}

    if not prompt_yes_no(
        f"Import {len(items)} image(s) into {gallery_path}?", default=True
    ):
        return []

    ai_ctx: _AIContext | None = None
    if config.ai_rename:
        client, model, cfg_prompt = _prepare_ai_client(
            config_path=config.config_path,
            model=config.rename_model,
            allow_interactive=config.allow_interactive,
        )
        ai_ctx = _AIContext(
            client=client,
            model=model,
            prompt=config.rename_prompt or cfg_prompt,
        )

    ctx = _ImportContext(
        config=config,
        gallery_path=gallery_path,
        images_dir=images_dir,
        existing_files=existing_files,
        ai_ctx=ai_ctx,
    )
    imported: list[GalleryItem] = []

    with StatusReporter(
        total=len(items), description="Importing images", unit="img"
    ) as reporter:
        for item in items:
            if not _is_image_file(item.source):
                reporter.advance()
                continue

            record = _import_one_image(
                item,
                ctx=ctx,
                reporter=reporter,
            )
            data.append(record)
            imported.append(record)
            reporter.advance()

    thumbnails.ensure_thumbnail_metadata(gallery_path, data)
    save_gallery_items(gallery_path, data)

    if imported:
        _run_post_import(imported, config, gallery_path)

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
