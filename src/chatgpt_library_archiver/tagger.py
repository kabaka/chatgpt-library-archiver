import argparse
import base64
import json
import mimetypes
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Iterable, List, Optional, Tuple

from openai import OpenAI

from .utils import prompt_yes_no

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
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    print(f"\nSaved configuration to {path}.\n")
    return cfg


def ensure_tagging_config(path: str = "tagging_config.json") -> dict:
    try:
        cfg = _load_config(path)
    except FileNotFoundError:
        if prompt_yes_no(f"{path} not found. Create it now?"):
            cfg = _write_config(path)
        else:
            raise
    if not cfg.get("api_key"):
        raise ValueError("tagging config missing 'api_key'")
    cfg.setdefault("model", "gpt-4.1-mini")
    cfg.setdefault("prompt", DEFAULT_PROMPT)
    return cfg


def generate_tags(
    image_path: str, client: OpenAI, model: str, prompt: str
) -> Tuple[List[str], Optional[Any]]:
    mime = mimetypes.guess_type(image_path)[0] or "image/jpeg"
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    image_url = f"data:{mime};base64,{b64}"
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
    parts = [p.strip() for p in text.replace("\n", ",").split(",")]
    tags = [p for p in parts if p]
    usage = getattr(response, "usage", None)
    return tags, usage


def tag_images(
    gallery_root: str = "gallery",
    ids: Optional[Iterable[str]] = None,
    re_tag: bool = False,
    remove: bool = False,
    remove_ids: Optional[Iterable[str]] = None,
    config_path: str = "tagging_config.json",
    prompt: Optional[str] = None,
    model: Optional[str] = None,
    max_workers: int = 4,
) -> int:
    meta_path = os.path.join(gallery_root, "metadata.json")
    if not os.path.isfile(meta_path):
        return 0
    with open(meta_path, encoding="utf-8") as f:
        data = json.load(f)

    ids_set = set(ids) if ids else None
    remove_ids_set = set(remove_ids) if remove_ids else None

    updated = 0
    if remove or remove_ids_set:
        for item in data:
            if remove or remove_ids_set and item.get("id") in remove_ids_set:
                item["tags"] = []
                updated += 1
    else:
        cfg = ensure_tagging_config(config_path)
        client = OpenAI(api_key=cfg["api_key"])
        use_prompt = prompt or cfg.get("prompt", DEFAULT_PROMPT)
        use_model = model or cfg.get("model", "gpt-4.1-mini")
        to_tag = []
        for item in data:
            if ids_set and item.get("id") not in ids_set:
                continue
            if not ids_set and not re_tag and item.get("tags"):
                continue
            to_tag.append(item)

        if to_tag:
            print(f"Tagging {len(to_tag)} images.", flush=True)

            total_tokens = 0

            def process(item):
                image_path = os.path.join(gallery_root, "images", item["filename"])
                print(f"Uploading {item['filename']}...", flush=True)
                tags, usage = generate_tags(image_path, client, use_model, use_prompt)
                item["tags"] = tags
                tokens = (
                    getattr(usage, "total_tokens", None) if usage is not None else None
                )
                if tokens is not None:
                    print(
                        f"Received tags for {item['id']} (tokens: {tokens})",
                        flush=True,
                    )
                else:
                    print(f"Received tags for {item['id']}", flush=True)
                return tokens or 0

            with ThreadPoolExecutor(max_workers=max_workers) as ex:
                futures = [ex.submit(process, item) for item in to_tag]
                for fut in as_completed(futures):
                    total_tokens += fut.result()
                    updated += 1

            if total_tokens:
                print(f"Total tokens used: {total_tokens}", flush=True)

    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return updated


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
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
        "--workers",
        type=int,
        default=4,
        help="Number of parallel workers",
    )
    return parser.parse_args(argv)


def main(args: Optional[argparse.Namespace] = None) -> int:
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
    )


if __name__ == "__main__":
    count = main()
    print(f"Updated {count} images.")
