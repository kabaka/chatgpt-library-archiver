from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from openai import OpenAI

from .ai import (
    AIRequestTelemetry,
    call_image_endpoint,
    get_cached_client,
    resolve_config,
)
from .metadata import GalleryItem, load_gallery_items, save_gallery_items
from .status import StatusReporter
from .utils import prompt_yes_no, write_secure_file

DEFAULT_PROMPT = (
    "Generate concise, comma-separated descriptive tags for this image in the style of"
    " booru archives."
)


def _load_config(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _write_config(path: str) -> dict:
    print("\nTagging configuration not found. Let's create it.\n")
    api_key = input("api_key = ").strip()
    model = input("model [gpt-4.1-mini] = ").strip() or "gpt-4.1-mini"
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
) -> dict:
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

    resolved.setdefault("prompt", DEFAULT_PROMPT)
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
    tags = [p for p in parts if p]
    return tags, telemetry


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
        client = get_cached_client(cfg["api_key"])
        use_prompt = prompt or cfg.get("prompt", DEFAULT_PROMPT)
        use_model = model or cfg.get("model", "gpt-4.1-mini")
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
                    futures = [ex.submit(process, item) for item in to_tag]
                    for fut in as_completed(futures):
                        telemetry = fut.result()
                        if telemetry.total_tokens is not None:
                            total_tokens += telemetry.total_tokens
                        total_latency += telemetry.latency_s
                        telemetry_count += 1
                        updated += 1
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


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Tag images with OpenAI")
    parser.add_argument("--gallery", default="gallery")
    parser.add_argument("--config", default="tagging_config.json")
    parser.add_argument("--all", action="store_true", help="Re-tag all images")
    parser.add_argument("--ids", nargs="+", help="Tag only specific image IDs")
    parser.add_argument("--remove-all", action="store_true", help="Remove all tags")
    parser.add_argument("--remove-ids", nargs="+", help="Remove tags for specific IDs")
    parser.add_argument("--prompt", help="Override tagging prompt")
    parser.add_argument("--model", help="Override model ID")
    parser.add_argument(
        "--no-config-prompt",
        action="store_true",
        help="Fail if configuration is missing instead of prompting",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Number of parallel workers",
    )
    return parser.parse_args(argv)


def main(args: argparse.Namespace | None = None) -> int:
    if args is None:
        args = parse_args()
    re_tag = args.all or bool(args.ids)
    return tag_images(
        gallery_root=args.gallery,
        ids=args.ids,
        re_tag=re_tag,
        remove=args.remove_all,
        remove_ids=args.remove_ids,
        config_path=args.config,
        prompt=args.prompt,
        model=args.model,
        max_workers=args.workers,
        allow_interactive=not getattr(args, "no_config_prompt", False),
    )


if __name__ == "__main__":
    count = main()
    print(f"Updated {count} images.")
