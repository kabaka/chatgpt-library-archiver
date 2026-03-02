from __future__ import annotations

import getpass
import json
import os
import re
import sys
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from openai import OpenAI

from .ai import (
    DEFAULT_MODEL,
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
    with open(path, encoding="utf-8") as f:
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
    )
    parts = [p.strip() for p in text.replace("\n", ",").split(",")]
    cleaned: list[str] = []
    seen: set[str] = set()
    for p in parts:
        tag = re.sub(r"<[^>]+>", "", p).strip().lower()
        if tag and tag not in seen:
            seen.add(tag)
            cleaned.append(tag)
    return cleaned, telemetry


def tag_images(
    gallery_root: str = "gallery",
    ids: Iterable[str] | None = None,
    re_tag: bool = False,
    remove: bool = False,
    remove_ids: Iterable[str] | None = None,
    config_path: str = "tagging_config.json",
    prompt: str | None = None,
    model: str | None = None,
    max_workers: int = 4,
    allow_interactive: bool | None = None,
    telemetry_sink: Callable[[AIRequestTelemetry], None] | None = None,
) -> int:
    items = load_gallery_items(gallery_root)
    if not items:
        return 0

    ids_set = set(ids) if ids else None
    remove_ids_set = set(remove_ids) if remove_ids else None

    updated = 0
    if remove or remove_ids_set:
        for item in items:
            if remove or (remove_ids_set and item.id in remove_ids_set):
                item.tags = []
                updated += 1
    else:
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
                    image_path = os.path.join(gallery_root, "images", item.filename)
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
