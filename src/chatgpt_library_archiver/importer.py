"""Utilities for importing arbitrary images into the gallery."""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import re
import shutil
import unicodedata
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from openai import OpenAI

from . import gallery, tagger, thumbnails
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


def _load_metadata(path: Path) -> list[dict]:
    if path.is_file():
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    return []


def _write_metadata(path: Path, data: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)


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
    *, config_path: str, model: str | None
) -> tuple[OpenAI, str, str]:
    cfg = tagger.ensure_tagging_config(config_path)
    client = OpenAI(api_key=cfg["api_key"])
    use_model = model or cfg.get("model", "gpt-4.1-mini")
    rename_prompt = cfg.get("rename_prompt", DEFAULT_RENAME_PROMPT)
    return client, use_model, rename_prompt


def _generate_ai_slug(
    client: OpenAI, model: str, prompt: str, image_path: Path
) -> str | None:
    mime = mimetypes.guess_type(str(image_path))[0] or "image/jpeg"
    with open(image_path, "rb") as fh:
        payload = base64.b64encode(fh.read()).decode("ascii")
    image_url = f"data:{mime};base64,{payload}"
    response = client.responses.create(
        model=model,
        input=[
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": prompt},
                    {"type": "input_image", "image_url": image_url},
                ],
            }
        ],
    )
    text = response.output_text.strip()
    slug = _slugify(text)
    return slug or None


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
) -> list[dict]:
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
        link_map = {path: link for path, link in zip(direct_files, conversation_links)}
        for item in items:
            if item.source in link_map:
                item.conversation_link = link_map[item.source]

    gallery_path = Path(gallery_root)
    images_dir = gallery_path / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    metadata_path = gallery_path / "metadata.json"

    data = _load_metadata(metadata_path)
    existing_files = {entry.get("filename", "") for entry in data}
    existing_files.discard("")

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
            config_path=config_path, model=rename_model
        )
        ai_prompt = rename_prompt or cfg_prompt

    imported: list[dict] = []

    for item in items:
        source_path = item.source
        if not _is_image_file(source_path):
            continue

        slug: str | None = None
        if ai_client is not None and ai_model is not None:
            try:
                slug = _generate_ai_slug(
                    ai_client,
                    ai_model,
                    ai_prompt or DEFAULT_RENAME_PROMPT,
                    source_path,
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
        thumb_rel = thumbnails.thumbnail_relative_path(filename)
        thumb_path = gallery_path / thumb_rel
        thumbnails.create_thumbnail(dest, thumb_path)

        record = {
            "id": uuid.uuid4().hex,
            "filename": filename,
            "title": title or slug.replace("-", " ").title(),
            "prompt": None,
            "tags": list(tags_list),
            "created_at": created_at,
            "width": None,
            "height": None,
            "url": None,
            "conversation_id": None,
            "message_id": None,
            "conversation_link": item.conversation_link,
            "thumbnail": thumb_rel,
        }
        data.append(record)
        imported.append(record)

    thumbnails.regenerate_thumbnails(gallery_path, data)
    _write_metadata(metadata_path, data)

    if imported:
        if tag_new:
            ids = [entry["id"] for entry in imported]
            tagger.tag_images(
                gallery_root=str(gallery_path),
                ids=ids,
                config_path=config_path,
                prompt=tag_prompt,
                model=tag_model,
                max_workers=tag_workers,
            )
        gallery.generate_gallery(gallery_root=str(gallery_path))

    return imported


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import images into the gallery")
    parser.add_argument("inputs", nargs="*", help="Files or directories to import")
    parser.add_argument("--gallery", default="gallery", help="Gallery root path")
    parser.add_argument(
        "--copy",
        action="store_true",
        help="Copy files instead of moving them",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Recurse into directories when importing",
    )
    parser.add_argument(
        "--tag",
        dest="tags",
        action="append",
        default=[],
        help="Add tag(s) to imported images. Can be repeated or comma-separated.",
    )
    parser.add_argument("--title", help="Override title for all imported images")
    parser.add_argument(
        "--conversation-link",
        dest="conversation_links",
        action="append",
        help="Conversation link for corresponding direct file inputs.",
    )
    parser.add_argument(
        "--tag-new",
        action="store_true",
        help="Tag imported images using OpenAI",
    )
    parser.add_argument(
        "--config",
        default="tagging_config.json",
        help="Path to tagging/AI configuration",
    )
    parser.add_argument(
        "--ai-rename",
        action="store_true",
        help="Use OpenAI to generate descriptive filenames",
    )
    parser.add_argument("--rename-model", help="Model to use for AI renaming")
    parser.add_argument("--rename-prompt", help="Prompt override for AI renaming")
    parser.add_argument(
        "--tag-prompt",
        help="Prompt override for tagging imported images",
    )
    parser.add_argument(
        "--tag-model",
        help="Model override for tagging imported images",
    )
    parser.add_argument(
        "--tag-workers",
        type=int,
        default=4,
        help="Parallel workers when tagging imported images",
    )
    parser.add_argument(
        "--regenerate-thumbnails",
        action="store_true",
        help="Regenerate thumbnails for the entire gallery and exit",
    )
    parser.add_argument(
        "--force-thumbnails",
        action="store_true",
        help="When regenerating thumbnails, overwrite existing files",
    )
    return parser.parse_args(argv)


def main(args: argparse.Namespace | None = None) -> int:
    if args is None:
        args = parse_args()
    if args.regenerate_thumbnails and not args.inputs:
        regenerated = regenerate_thumbnails(
            gallery_root=args.gallery, force=args.force_thumbnails
        )
        return len(regenerated)

    if not args.inputs:
        raise ValueError("No inputs supplied for import.")

    imported = import_images(
        inputs=args.inputs,
        gallery_root=args.gallery,
        copy_files=args.copy,
        recursive=args.recursive,
        tags=args.tags,
        title=args.title,
        conversation_links=args.conversation_links,
        tag_new=args.tag_new,
        config_path=args.config,
        ai_rename=args.ai_rename,
        rename_model=args.rename_model,
        rename_prompt=args.rename_prompt,
        tag_prompt=args.tag_prompt,
        tag_model=args.tag_model,
        tag_workers=args.tag_workers,
    )
    if args.regenerate_thumbnails:
        regenerate_thumbnails(
            gallery_root=args.gallery, force=args.force_thumbnails
        )
    return len(imported)


def regenerate_thumbnails(*, gallery_root: str, force: bool = False) -> list[str]:
    gallery_path = Path(gallery_root)
    metadata_path = gallery_path / "metadata.json"
    data = _load_metadata(metadata_path)
    if not data:
        return []
    processed, updated = thumbnails.regenerate_thumbnails(
        gallery_path, data, force=force
    )
    if updated:
        _write_metadata(metadata_path, data)
    return processed


if __name__ == "__main__":
    count = main()
    print(f"Imported {count} images.")
