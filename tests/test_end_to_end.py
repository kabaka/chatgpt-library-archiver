import hashlib
import io
import json
from urllib.parse import urlparse

from PIL import Image

from chatgpt_library_archiver import incremental_downloader
from chatgpt_library_archiver.http_client import DownloadResult


def _sample_png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (6, 6), color=(50, 120, 200)).save(buf, format="PNG")
    return buf.getvalue()


PNG_BYTES = _sample_png()


def test_incremental_download_and_gallery(monkeypatch, tmp_path):
    # Operate within a temporary working directory
    monkeypatch.chdir(tmp_path)

    # Provide dummy auth configuration without touching the filesystem
    monkeypatch.setattr(
        incremental_downloader,
        "ensure_auth_config",
        lambda path="auth.txt": {
            "url": "https://api.example.com?limit=1",
            "authorization": "Bearer token",
            "cookie": "session=abc",
            "referer": "https://chat.openai.com/library",
            "user_agent": "agent",
            "oai_client_version": "1",
            "oai_device_id": "dev",
            "oai_language": "en",
        },
    )

    # Auto-confirm all prompts
    monkeypatch.setattr(incremental_downloader, "prompt_yes_no", lambda msg: True)

    # Avoid real delays during the test
    monkeypatch.setattr(incremental_downloader.time, "sleep", lambda s: None)

    tagged = {}

    def fake_tag_images(gallery_root="gallery", ids=None, **kwargs):
        tagged["ids"] = list(ids or [])
        meta = tmp_path / gallery_root / "metadata.json"
        data = json.loads(meta.read_text())
        for item in data:
            if not ids or item["id"] in ids:
                item["tags"] = ["t"]
        meta.write_text(json.dumps(data))
        return len(tagged["ids"])

    monkeypatch.setattr(incremental_downloader.tagger, "tag_images", fake_tag_images)

    # Seed existing data
    images_dir = tmp_path / "gallery" / "images"
    images_dir.mkdir(parents=True)
    (images_dir / "1.png").write_bytes(PNG_BYTES)
    meta_path = tmp_path / "gallery" / "metadata.json"
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump([{"id": "1", "filename": "1.png", "created_at": 1}], f)

    # Mock network requests for both metadata and image download
    calls = {"meta": 0}

    class FakeHttpClient:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, exc_tb):
            return False

        def close(self):
            return None

        def get_json(self, url, headers=None):
            parsed = urlparse(url)
            if parsed.scheme == "https" and parsed.netloc == "api.example.com":
                calls["meta"] += 1
                if calls["meta"] == 1:
                    return {
                        "items": [
                            {
                                "id": "1",
                                "url": "https://img.local/1.png",
                                "title": "old image",
                                "created_at": 1,
                            },
                            {
                                "id": "2",
                                "url": "https://img.local/2.png",
                                "title": "new image",
                                "created_at": 2,
                            },
                        ]
                    }
                return {"items": []}
            raise AssertionError(f"Unexpected metadata URL {url}")

        def stream_download(self, url, destination, headers=None, **kwargs):
            if url == "https://img.local/2.png":
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(PNG_BYTES)
                checksum = hashlib.sha256(PNG_BYTES).hexdigest()
                return DownloadResult(
                    path=destination,
                    bytes_downloaded=len(PNG_BYTES),
                    checksum=checksum,
                    content_type="image/png",
                )
            if url == "https://img.local/1.png":
                raise AssertionError("Should not re-download existing image")
            raise AssertionError(f"Unexpected download URL {url}")

    monkeypatch.setattr(
        incremental_downloader,
        "create_http_client",
        FakeHttpClient,
    )

    # Run the full download + gallery generation flow
    incremental_downloader.main(tag_new=True)

    img1 = tmp_path / "gallery" / "images" / "1.png"
    img2 = tmp_path / "gallery" / "images" / "2.png"
    meta_path = tmp_path / "gallery" / "metadata.json"
    html_path = tmp_path / "gallery" / "index.html"

    assert img1.exists()
    assert img2.exists()
    assert meta_path.exists()
    assert html_path.exists()

    data = json.loads(meta_path.read_text())
    ids = {item["id"] for item in data}
    assert ids == {"1", "2"}
    assert tagged["ids"] == ["2"]
    for item in data:
        if item["id"] == "2":
            assert item.get("tags") == ["t"]
            assert item.get("checksum") == hashlib.sha256(PNG_BYTES).hexdigest()
            assert item.get("content_type") == "image/png"
        assert item["thumbnail"].startswith("thumbs/medium/")
        assert item["thumbnails"]["medium"].startswith("thumbs/medium/")

    html = html_path.read_text()
    assert "metadata.json" in html


def test_incremental_download_with_browser_calls_extract_auth(monkeypatch, tmp_path):
    """browser= passed → calls extract_auth_config, not ensure_auth_config."""
    monkeypatch.chdir(tmp_path)

    auth_calls = {"extract": 0, "ensure": 0}
    fake_config = {
        "url": "https://api.example.com?limit=1",
        "authorization": "Bearer tok",
        "cookie": "session=abc",
        "referer": "https://chat.openai.com/library",
        "user_agent": "agent",
        "oai_client_version": "1",
        "oai_device_id": "dev",
        "oai_language": "en",
    }

    def fake_extract(browser):
        auth_calls["extract"] += 1
        assert browser == "edge"
        return fake_config

    def fake_ensure(path="auth.txt"):
        auth_calls["ensure"] += 1
        return fake_config

    monkeypatch.setattr(
        "chatgpt_library_archiver.browser_extract.extract_auth_config",
        fake_extract,
    )
    monkeypatch.setattr(
        incremental_downloader,
        "ensure_auth_config",
        fake_ensure,
    )
    monkeypatch.setattr(incremental_downloader, "prompt_yes_no", lambda msg: False)

    (tmp_path / "gallery").mkdir()

    incremental_downloader.main(browser="edge")

    assert auth_calls["extract"] == 1
    assert auth_calls["ensure"] == 0


def test_incremental_download_without_browser_calls_ensure_auth(monkeypatch, tmp_path):
    """browser= None (default) → calls ensure_auth_config."""
    monkeypatch.chdir(tmp_path)

    auth_calls = {"extract": 0, "ensure": 0}
    fake_config = {
        "url": "https://api.example.com?limit=1",
        "authorization": "Bearer tok",
        "cookie": "session=abc",
        "referer": "https://chat.openai.com/library",
        "user_agent": "agent",
        "oai_client_version": "1",
        "oai_device_id": "dev",
        "oai_language": "en",
    }

    def fake_extract(browser):
        auth_calls["extract"] += 1
        return fake_config

    def fake_ensure(path="auth.txt"):
        auth_calls["ensure"] += 1
        return fake_config

    monkeypatch.setattr(
        "chatgpt_library_archiver.browser_extract.extract_auth_config",
        fake_extract,
    )
    monkeypatch.setattr(
        incremental_downloader,
        "ensure_auth_config",
        fake_ensure,
    )
    monkeypatch.setattr(incremental_downloader, "prompt_yes_no", lambda msg: False)

    (tmp_path / "gallery").mkdir()

    incremental_downloader.main()

    assert auth_calls["extract"] == 0
    assert auth_calls["ensure"] == 1
