import json
import mimetypes
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote

import requests
from tqdm import tqdm

from . import tagger, thumbnails
from .gallery import generate_gallery
from .status import StatusReporter
from .utils import ensure_auth_config, prompt_yes_no


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

    existing_ids = set()
    existing_metadata = []
    metadata_path = gallery_root / "metadata.json"
    if metadata_path.is_file():
        with open(metadata_path, encoding="utf-8") as f:
            existing_metadata = json.load(f)
            existing_ids.update(item["id"] for item in existing_metadata)

    with StatusReporter(
        total=0, description="Overall progress", unit="img", position=1
    ) as progress:
        progress.log(f"Found {len(existing_ids)} previously downloaded image IDs.")

        if not prompt_yes_no("Proceed to download all new images from your account?"):
            progress.log("Aborted by user.")
            return

        # Step 2: Download new items only
        max_workers = 14
        cursor = None
        new_metadata = []
        consecutive_empty_pages = 0

        def download_image(meta):
            try:
                response = requests.get(meta["url"], headers=headers, timeout=30)
                content_type = response.headers.get("Content-Type", "")
                ext = mimetypes.guess_extension(content_type) or ".jpg"
                filename = f"{meta['id']}{ext}"
                filepath = images_dir / filename

                with open(filepath, "wb") as f:
                    f.write(response.content)

                meta["filename"] = filename
                thumb_rel = thumbnails.thumbnail_relative_path(filename)
                thumb_path = gallery_root / thumb_rel
                thumbnails.create_thumbnail(filepath, thumb_path, reporter=progress)
                meta["thumbnail"] = thumb_rel
                return (True, meta)
            except Exception as e:
                return (False, meta["id"], str(e))

        progress.log("Fetching metadata from API...")

        while True:
            url = base_url + (f"&after={quote(cursor)}" if cursor else "")
            response = requests.get(url, headers=headers)

            if response.status_code != 200:
                progress.log(f"Error during fetch: {response.status_code}")
                if response.status_code in (401, 403) and prompt_yes_no(
                    "Auth seems invalid/expired. Re-enter credentials now?"
                ):
                    config = ensure_auth_config("auth.txt")
                    headers = build_headers(config)
                    continue
                break

            data = response.json()
            items = data.get("items", [])
            if not items:
                progress.log("No more items in API.")
                break

            # Filter only new items
            new_items = [item for item in items if item.get("id") not in existing_ids]

            if not new_items:
                consecutive_empty_pages += 1
                if consecutive_empty_pages >= 2:
                    progress.log("No new images found in 2 pages. Stopping.")
                    break
                else:
                    cursor = data.get("cursor")
                    if not cursor:
                        break
                    continue

            consecutive_empty_pages = 0  # Reset if we got new content

            metas = []
            for item in new_items:
                image_url = item.get("url")
                image_id = item.get("id")
                if not image_url or not image_id:
                    continue

                meta = {
                    "id": image_id,
                    "filename": "",
                    "title": item.get("title", ""),
                    "prompt": item.get("prompt"),
                    "tags": item.get("tags", []),
                    "created_at": item.get("created_at"),
                    "width": item.get("width"),
                    "height": item.get("height"),
                    "url": image_url,
                    "conversation_id": item.get("conversation_id"),
                    "message_id": item.get("message_id"),
                }
                meta["conversation_link"] = (
                    f"https://chat.openai.com/c/{meta['conversation_id']}#{meta['message_id']}"
                )
                metas.append(meta)

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
                            "{desc}: {percentage:3.0f}%|{bar}| " "{n_fmt}/{total_fmt}"
                        ),
                        disable=progress.disable,
                        mininterval=1,
                        position=0,
                    )
                )

            for result in results:
                if result[0]:
                    new_metadata.append(result[1])
                    existing_ids.add(result[1]["id"])
                    progress.advance()
                else:
                    progress.log(f"Failed: {result[1]}: {result[2]}")

            cursor = data.get("cursor")
            if not cursor:
                break

            time.sleep(0.5)

        # Save metadata
        if new_metadata:
            existing_metadata.extend(new_metadata)
            _, updated = thumbnails.regenerate_thumbnails(
                gallery_root, existing_metadata, reporter=progress
            )
            with open(metadata_path, "w", encoding="utf-8") as f:
                json.dump(existing_metadata, f, indent=2)
            progress.log(f"Saved {len(new_metadata)} new images to gallery/")
            if tag_new:
                ids = [m["id"] for m in new_metadata]
                progress.log("Tagging new images...")
                tagger.tag_images(ids=ids)
        else:
            progress.log("No new images to download.")

    # Regenerate gallery pages and index after downloads (including tags)
    generate_gallery()


if __name__ == "__main__":
    main()
