import requests
import os
import json
import mimetypes
import time
from urllib.parse import quote
from glob import glob
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor

from .utils import ensure_auth_config, prompt_yes_no
from .gallery import generate_gallery


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


def main():
    # Load auth (prompt if missing)
    config = ensure_auth_config("auth.txt")
    base_url = config["url"]
    headers = build_headers(config)

    # Step 1: Load all existing IDs
    os.makedirs("gallery", exist_ok=True)
    existing_ids = set()
    metadata_files = sorted(glob("gallery/v*/metadata_v*.json"))
    for path in metadata_files:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            existing_ids.update(item["id"] for item in data)

    print(f"Found {len(existing_ids)} previously downloaded image IDs.")

    if not prompt_yes_no("Proceed to download all new images from your account?"):
        print("Aborted by user.")
        return

    # Step 2: Create next version folder
    existing_versions = [
        int(p.split("v")[-1])
        for p in os.listdir("gallery")
        if p.startswith("v") and os.path.isdir(os.path.join("gallery", p))
    ]
    next_version = max(existing_versions, default=0) + 1
    version_folder = f"gallery/v{next_version}"
    os.makedirs(os.path.join(version_folder, "images"), exist_ok=True)
    print(f"Saving new images to: {version_folder}/")

    # Step 3: Download new items only
    max_workers = 14
    cursor = None
    new_metadata = []
    consecutive_empty_pages = 0

    def download_image(meta, folder):
        try:
            response = requests.get(meta["url"], headers=headers, timeout=30)
            content_type = response.headers.get("Content-Type", "")
            ext = mimetypes.guess_extension(content_type) or ".jpg"
            filename = f"{meta['id']}{ext}"
            filepath = os.path.join(folder, "images", filename)

            with open(filepath, 'wb') as f:
                f.write(response.content)

            meta["filename"] = filename
            return (True, meta)
        except Exception as e:
            return (False, meta["id"], str(e))

    print("Fetching metadata from API...")

    while True:
        url = base_url + (f"&after={quote(cursor)}" if cursor else "")
        response = requests.get(url, headers=headers)

        if response.status_code != 200:
            print("Error during fetch:", response.status_code)
            if response.status_code in (401, 403):
                if prompt_yes_no(
                    "Auth seems invalid/expired. Re-enter credentials now?"
                ):
                    config = ensure_auth_config("auth.txt")
                    headers = build_headers(config)
                    continue
            break

        data = response.json()
        items = data.get("items", [])
        if not items:
            print("No more items in API.")
            break

        # Filter only new items
        new_items = [item for item in items if item.get("id") not in existing_ids]

        if not new_items:
            consecutive_empty_pages += 1
            if consecutive_empty_pages >= 2:
                print("No new images found in 2 pages. Stopping.")
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

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            results = list(
                tqdm(
                    executor.map(lambda m: download_image(m, version_folder), metas),
                    total=len(metas),
                    desc="Downloading images",
                    unit="img",
                    dynamic_ncols=True,
                    bar_format="{desc}: {percentage:3.0f}%|{bar}| {n_fmt}/{total_fmt}",
                    disable=False,
                    mininterval=1,
                )
            )

        for result in results:
            if result[0]:
                new_metadata.append(result[1])
                existing_ids.add(result[1]["id"])
            else:
                print(f"Failed: {result[1]}: {result[2]}")

        cursor = data.get("cursor")
        if not cursor:
            break

        time.sleep(0.5)

    # Save metadata
    if new_metadata:
        meta_path = os.path.join(version_folder, f"metadata_v{next_version}.json")
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(new_metadata, f, indent=2)
        print(f"Saved {len(new_metadata)} new images to {version_folder}/")
    else:
        print("No new images to download. Cleaning up...")
        try:
            os.rmdir(os.path.join(version_folder, "images"))
            os.rmdir(version_folder)
        except OSError:
            pass

    # Regenerate gallery pages and index after downloads
    generate_gallery()


if __name__ == "__main__":
    main()
