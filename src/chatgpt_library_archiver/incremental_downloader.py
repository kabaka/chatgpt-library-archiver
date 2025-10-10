"""Incremental downloader for ChatGPT image library assets."""

from __future__ import annotations

import mimetypes
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote

from tqdm import tqdm

from . import tagger, thumbnails
from .gallery import generate_gallery
from .http_client import HttpClient, HttpError
from .metadata import (
    GalleryItem,
    load_gallery_items,
    normalize_created_at,
    save_gallery_items,
)
from .status import StatusReporter
from .utils import ensure_auth_config, prompt_yes_no

MAX_EMPTY_PAGE_RETRIES = 2


def build_headers(config: dict) -> dict:
    return {
        "Authorization": config["authorization"],
        "Cookie": config["cookie"],
        "User-Agent": config["user_agent"],
        "Accept": "application/json",
        "Referer": config["referer"],
        "oai-client-version": config["oai_client_version"],
        "oai-device-id": config["oai_device_id"],
        "oai-language": config["oai_language"],
    }


def create_http_client() -> HttpClient:
    """Factory for the shared HTTP client used by downloads."""

    return HttpClient(timeout=30.0)


def main(tag_new: bool = False) -> None:
    # Load auth (prompt if missing)
    config = ensure_auth_config("auth.txt")
    base_url = config["url"]
    headers = build_headers(config)

    # Step 1: Load all existing IDs
    gallery_root = Path("gallery")
    gallery_root.mkdir(exist_ok=True)
    images_dir = gallery_root / "images"
    images_dir.mkdir(exist_ok=True)

    existing_metadata = load_gallery_items(gallery_root)
    existing_ids = {item.id for item in existing_metadata}

    with (
        StatusReporter(
            total=0, description="Overall progress", unit="img", position=1
        ) as progress,
        create_http_client() as client,
    ):
        progress.log(f"Found {len(existing_ids)} previously downloaded image IDs.")

        if not prompt_yes_no("Proceed to download all new images from your account?"):
            progress.log("Aborted by user.")
            return

        # Step 2: Download new items only
        max_workers = 14
        cursor: str | None = None
        new_metadata: list[GalleryItem] = []
        consecutive_empty_pages = 0

        def download_image(item: GalleryItem):
            try:
                if not item.url:
                    raise ValueError("Missing URL for gallery item")
                temp_path = images_dir / f"{item.id}.download"
                result = client.stream_download(
                    item.url,
                    temp_path,
                    headers=headers,
                    expected_content_prefixes=("image/",),
                )
                raw_type = (result.content_type or "").split(";", 1)[0].strip()
                ext = mimetypes.guess_extension(raw_type) or ".jpg"
                filename = f"{item.id}{ext}"
                filepath = images_dir / filename
                if filepath.exists():
                    filepath.unlink()
                temp_path.replace(filepath)

                item.filename = filename
                item.checksum = result.checksum
                item.content_type = result.content_type
                thumb_rels = thumbnails.thumbnail_relative_paths(filename)
                thumb_paths = {
                    size: gallery_root / rel for size, rel in thumb_rels.items()
                }
                thumbnails.create_thumbnails(filepath, thumb_paths, reporter=progress)
                item.thumbnails = thumb_rels
                item.thumbnail = thumb_rels["medium"]
                return ("ok", item, "", None)
            except HttpError as exc:
                return ("error", item, exc.reason, exc)
            except Exception as exc:  # pragma: no cover - safety net
                return ("error", item, str(exc), exc)

        progress.log("Fetching metadata from API...")

        while True:
            url = base_url + (f"&after={quote(cursor)}" if cursor else "")
            try:
                data = client.get_json(url, headers=headers)
            except HttpError as exc:
                progress.report_error(
                    "Fetch metadata",
                    url,
                    reason=exc.reason,
                    context=exc.context,
                    exception=exc,
                )
                if exc.status_code in (401, 403) and prompt_yes_no(
                    "Auth seems invalid/expired. Re-enter credentials now?"
                ):
                    config = ensure_auth_config("auth.txt")
                    headers = build_headers(config)
                    continue
                break
            except Exception as exc:  # pragma: no cover - safety net
                progress.report_error(
                    "Fetch metadata",
                    url,
                    reason=str(exc),
                    context={"url": url},
                    exception=exc,
                )
                break

            items = data.get("items") if isinstance(data, dict) else None
            if not isinstance(items, list):
                progress.report_error(
                    "Fetch metadata",
                    url,
                    reason="Response missing 'items' list",
                    context={"url": url},
                )
                break
            if not items:
                progress.log("No more items in API.")
                break

            # Filter only new items
            new_items = [item for item in items if item.get("id") not in existing_ids]

            if not new_items:
                consecutive_empty_pages += 1
                if consecutive_empty_pages >= MAX_EMPTY_PAGE_RETRIES:
                    message = (
                        f"No new images found in {MAX_EMPTY_PAGE_RETRIES} pages."
                        " Stopping."
                    )
                    progress.log(message)
                    break
                cursor = data.get("cursor") if isinstance(data, dict) else None
                if not cursor:
                    break
                continue

            consecutive_empty_pages = 0  # Reset if we got new content

            metas: list[GalleryItem] = []
            for item in new_items:
                image_url = item.get("url")
                image_id = item.get("id")
                if not image_url or not image_id:
                    continue
                conversation_id = item.get("conversation_id")
                message_id = item.get("message_id")
                conversation_link = None
                if conversation_id and message_id:
                    conversation_link = (
                        f"https://chat.openai.com/c/{conversation_id}#{message_id}"
                    )

                metas.append(
                    GalleryItem(
                        id=image_id,
                        filename="",
                        title=item.get("title", ""),
                        prompt=item.get("prompt"),
                        tags=list(item.get("tags") or []),
                        created_at=normalize_created_at(item.get("created_at")),
                        width=item.get("width"),
                        height=item.get("height"),
                        url=image_url,
                        conversation_id=conversation_id,
                        message_id=message_id,
                        conversation_link=conversation_link,
                    )
                )

            progress.add_total(len(metas))

            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                results = list(
                    tqdm(
                        executor.map(download_image, metas),
                        total=len(metas),
                        desc="Downloading images",
                        unit="img",
                        dynamic_ncols=True,
                        bar_format=(
                            "{desc}: {percentage:3.0f}%|{bar}| {n_fmt}/{total_fmt}"
                        ),
                        disable=progress.disable,
                        mininterval=1,
                        position=0,
                    )
                )

            for status, payload, message, exc in results:
                if status == "ok":
                    item = payload
                    new_metadata.append(item)
                    existing_ids.add(item.id)
                    progress.advance()
                else:
                    item = payload
                    progress.report_error(
                        "Download",
                        item.id,
                        reason=message,
                        context={"url": item.url or ""},
                        exception=exc,
                    )

            cursor = data.get("cursor") if isinstance(data, dict) else None
            if not cursor:
                break

            time.sleep(0.5)

        # Save metadata
        if new_metadata:
            existing_metadata.extend(new_metadata)
            _, updated = thumbnails.regenerate_thumbnails(
                gallery_root, existing_metadata, reporter=progress
            )
            save_gallery_items(gallery_root, existing_metadata)
            progress.log(f"Saved {len(new_metadata)} new images to gallery/")
            if tag_new:
                ids = [m.id for m in new_metadata]
                progress.log("Tagging new images...")
                tagger.tag_images(ids=ids)
        else:
            progress.log("No new images to download.")

    # Regenerate gallery pages and index after downloads (including tags)
    generate_gallery()


if __name__ == "__main__":
    main()
