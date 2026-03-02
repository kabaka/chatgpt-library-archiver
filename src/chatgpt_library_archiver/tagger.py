from __future__ import annotations

import getpass
import json
import re
import sys
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from openai import OpenAI

from .ai import (
    DEFAULT_MODEL,
    DEFAULT_TAG_SYSTEM_PROMPT,
    AIRequestTelemetry,
    TaggingConfig,
    call_image_endpoint,
    get_cached_client,
    resolve_config,
)
from .metadata import GalleryItem, load_gallery_items, save_gallery_items
from .status import StatusReporter
from .utils import mask_sensitive, prompt_yes_no, write_secure_file

DEFAULT_PROMPT = (
    "Generate concise, comma-separated descriptive tags for this image in the style of"
    " booru archives."
)

SAVE_INTERVAL = 10


def _load_config(path: str) -> dict:
    with Path(path).open(encoding="utf-8") as f:
        return json.load(f)


def _write_config(path: str) -> dict:
    print("\nTagging configuration not found. Let's create it.\n")
    api_key = getpass.getpass("api_key = ").strip()
    if api_key:
        print(f"  \u2713 API key set: {mask_sensitive(api_key)}")
    model = input(f"model [{DEFAULT_MODEL}] = ").strip() or DEFAULT_MODEL
    prompt = input("prompt [leave blank for default] = ").strip() or DEFAULT_PROMPT
    cfg = {"api_key": api_key, "model": model, "prompt": prompt}
    write_secure_file(path, json.dumps(cfg, indent=2))
    print(f"\nSaved configuration to {path}.\n")
    return cfg


def ensure_tagging_config(
    path: str = "tagging_config.json",
    *,
    model: str | None = None,
    prompt: str | None = None,
    rename_prompt: str | None = None,
    allow_interactive: bool | None = None,
) -> TaggingConfig:
    if allow_interactive is None:
        allow_interactive = sys.stdin is not None and sys.stdin.isatty()

    overrides = {
        "model": model,
        "prompt": prompt,
        "rename_prompt": rename_prompt,
    }

    try:
        cfg = _load_config(path)
        resolved = resolve_config(source=cfg, overrides=overrides)
    except FileNotFoundError:
        cfg = None
        try:
            resolved = resolve_config(source=None, overrides=overrides)
        except ValueError:
            if allow_interactive and prompt_yes_no(f"{path} not found. Create it now?"):
                cfg = _write_config(path)
                resolved = resolve_config(source=cfg, overrides=overrides)
            else:
                raise

    if not resolved.prompt:
        resolved.prompt = DEFAULT_PROMPT
    return resolved


def generate_tags(
    image_path: str,
    client: OpenAI,
    model: str,
    prompt: str,
    *,
    reporter: StatusReporter | None = None,
) -> tuple[list[str], AIRequestTelemetry]:
    path = Path(image_path)

    def on_retry(attempt: int, delay: float) -> None:
        if reporter is not None:
            reporter.log_status(
                "Rate limited",
                f"{path.name} (retry {attempt} in {delay:.1f}s)",
            )

    text, telemetry, _usage = call_image_endpoint(
        client=client,
        model=model,
        prompt=prompt,
        image_path=path,
        operation="tag",
        subject=path.name,
        on_retry=on_retry,
        system_prompt=DEFAULT_TAG_SYSTEM_PROMPT,
    )
    parts = [p.strip() for p in text.replace("\n", ",").split(",")]
    cleaned: list[str] = []
    seen: set[str] = set()
    for p in parts:
        tag = normalize_tag(p)
        if tag and tag not in seen:
            seen.add(tag)
            cleaned.append(tag)
    return cleaned, telemetry


def normalize_tag(raw: str) -> str:
    """Normalize a single tag string for consistent storage."""
    tag = re.sub(r"<[^>]+>", "", raw)  # strip HTML tags
    tag = tag.replace("_", " ")  # underscores → spaces
    tag = re.sub(r"\s+", " ", tag).strip()  # collapse whitespace
    tag = tag.lower()  # lowercase
    tag = tag.rstrip(".!?,;:")  # strip trailing punctuation
    return tag


def remove_tags(
    gallery_root: str = "gallery",
    ids: Iterable[str] | None = None,
) -> int:
    """Remove tags from gallery items.

    When *ids* is ``None`` tags are cleared from **all** items.  Otherwise only
    items whose id appears in *ids* are affected.

    Returns the number of items whose tags were cleared.
    """
    items = load_gallery_items(gallery_root)
    if not items:
        return 0

    ids_set = set(ids) if ids else None
    updated = 0
    for item in items:
        if ids_set is None or item.id in ids_set:
            item.tags = []
            updated += 1

    save_gallery_items(gallery_root, items)
    return updated


def tag_images(
    gallery_root: str = "gallery",
    ids: Iterable[str] | None = None,
    re_tag: bool = False,
    config_path: str = "tagging_config.json",
    prompt: str | None = None,
    model: str | None = None,
    max_workers: int = 4,
    allow_interactive: bool | None = None,
    telemetry_sink: Callable[[AIRequestTelemetry], None] | None = None,
) -> int:
    """Generate AI tags for gallery images.

    Returns the number of items successfully tagged.
    """
    items = load_gallery_items(gallery_root)
    if not items:
        return 0

    ids_set = set(ids) if ids else None

    updated = 0
    cfg = ensure_tagging_config(
        config_path,
        allow_interactive=allow_interactive,
    )
    client = get_cached_client(cfg.api_key)
    use_prompt = prompt or cfg.prompt
    use_model = model or cfg.model
    to_tag = []
    for item in items:
        if ids_set and item.id not in ids_set:
            continue
        if not ids_set and not re_tag and item.tags:
            continue
        to_tag.append(item)

    if to_tag:
        with StatusReporter(
            total=len(to_tag), description="Tagging images", unit="img"
        ) as reporter:
            reporter.log_status("Tagging", f"{len(to_tag)} images.")

            total_tokens = 0
            total_latency = 0.0
            telemetry_count = 0

            def process(item: GalleryItem):
                image_path = str(Path(gallery_root) / "images" / item.filename)
                reporter.log_status("Uploading", item.filename)
                tags, telemetry = generate_tags(
                    image_path,
                    client,
                    use_model,
                    use_prompt,
                    reporter=reporter,
                )
                item.tags = tags
                tokens = telemetry.total_tokens
                if telemetry_sink is not None:
                    telemetry_sink(telemetry)
                if tokens is not None:
                    reporter.log_status(
                        "Received tags for",
                        (
                            f"{item.id} (tokens: {tokens}, "
                            f"latency: {telemetry.latency_s:.2f}s)"
                        ),
                    )
                else:
                    reporter.log_status("Received tags for", item.id)
                return telemetry

            with ThreadPoolExecutor(max_workers=max_workers) as ex:
                future_to_item = {ex.submit(process, item): item for item in to_tag}
                for fut in as_completed(future_to_item):
                    item = future_to_item[fut]
                    try:
                        telemetry = fut.result()
                    except Exception as exc:
                        reporter.report_error(
                            "Tagging failed",
                            item.filename,
                            reason=str(exc),
                            exception=exc,
                        )
                        reporter.advance()
                        continue
                    if telemetry.total_tokens is not None:
                        total_tokens += telemetry.total_tokens
                    total_latency += telemetry.latency_s
                    telemetry_count += 1
                    updated += 1
                    if updated % SAVE_INTERVAL == 0:
                        save_gallery_items(gallery_root, items)
                    reporter.advance()

            if telemetry_count:
                avg_latency = total_latency / telemetry_count
                if total_tokens:
                    reporter.log(
                        f"Total tokens used: {total_tokens} | "
                        f"avg latency: {avg_latency:.2f}s"
                    )
                else:
                    reporter.log(f"Avg latency: {avg_latency:.2f}s")
            elif total_tokens:
                reporter.log(f"Total tokens used: {total_tokens}")

    save_gallery_items(gallery_root, items)
    return updated
