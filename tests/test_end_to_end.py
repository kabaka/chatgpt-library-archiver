import hashlib
import json
from urllib.parse import urlparse

from chatgpt_library_archiver import incremental_downloader
from chatgpt_library_archiver.http_client import DownloadResult
from chatgpt_library_archiver.incremental_downloader import _sanitize_id


def test_incremental_download_and_gallery(monkeypatch, tmp_path, sample_png_bytes):
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
    (images_dir / "1.png").write_bytes(sample_png_bytes)
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
                destination.write_bytes(sample_png_bytes)
                checksum = hashlib.sha256(sample_png_bytes).hexdigest()
                return DownloadResult(
                    path=destination,
                    bytes_downloaded=len(sample_png_bytes),
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
            assert item.get("checksum") == hashlib.sha256(sample_png_bytes).hexdigest()
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


# -------------------------------------------------------------------
# _sanitize_id tests
# -------------------------------------------------------------------


class TestSanitizeId:
    def test_normal_hex_id_unchanged(self):
        assert _sanitize_id("s_1ef6abc") == "s_1ef6abc"

    def test_path_traversal_stripped(self):
        result = _sanitize_id("../../etc/cron.d/evil")
        assert "/" not in result
        assert ".." not in result
        assert result == "______etc_cron_d_evil"

    def test_absolute_path_stripped(self):
        result = _sanitize_id("/etc/passwd")
        assert "/" not in result
        assert result == "_etc_passwd"

    def test_null_bytes_removed(self):
        result = _sanitize_id("abc\x00def")
        assert "\x00" not in result
        assert result == "abcdef"

    def test_empty_string_returns_fallback(self):
        assert _sanitize_id("") == "unknown"

    def test_only_unsafe_chars_returns_fallback(self):
        assert _sanitize_id("../../../") == "unknown"

    def test_unicode_normalized(self):
        # e-acute (é) → stripped to e via NFKD + ascii encode
        result = _sanitize_id("café")
        assert result == "cafe"

    def test_hyphens_and_underscores_preserved(self):
        assert _sanitize_id("my-image_01") == "my-image_01"

    def test_windows_path_separators(self):
        result = _sanitize_id("..\\..\\windows\\system32")
        assert "\\" not in result
        assert result == "______windows_system32"

    def test_spaces_replaced(self):
        result = _sanitize_id("my image id")
        assert " " not in result
        assert result == "my_image_id"


# -------------------------------------------------------------------
# Path traversal integration test
# -------------------------------------------------------------------


def test_path_traversal_does_not_escape_gallery(
    monkeypatch, tmp_path, sample_png_bytes
):
    """A malicious item.id with path traversal must not write outside gallery."""
    monkeypatch.chdir(tmp_path)

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
    monkeypatch.setattr(incremental_downloader, "prompt_yes_no", lambda msg: True)
    monkeypatch.setattr(incremental_downloader.time, "sleep", lambda s: None)
    monkeypatch.setattr(incremental_downloader.tagger, "tag_images", lambda **kw: 0)

    images_dir = tmp_path / "gallery" / "images"
    images_dir.mkdir(parents=True)
    meta_path = tmp_path / "gallery" / "metadata.json"
    meta_path.write_text("[]")

    malicious_id = "../../escape"

    class FakeHttpClient:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def close(self):
            return None

        def get_json(self, url, headers=None):
            parsed = urlparse(url)
            if parsed.netloc == "api.example.com":
                return {
                    "items": [
                        {
                            "id": malicious_id,
                            "url": "https://img.local/bad.png",
                            "created_at": 1,
                        }
                    ]
                }
            return {"items": []}

        def stream_download(self, url, destination, headers=None, **kwargs):
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(sample_png_bytes)
            return DownloadResult(
                path=destination,
                bytes_downloaded=len(sample_png_bytes),
                checksum=hashlib.sha256(sample_png_bytes).hexdigest(),
                content_type="image/png",
            )

    monkeypatch.setattr(
        incremental_downloader,
        "create_http_client",
        FakeHttpClient,
    )

    incremental_downloader.main()

    # The sanitised id should produce a safe filename inside images/
    escaped_path = tmp_path / "escape.png"
    assert not escaped_path.exists(), "File escaped gallery directory!"

    # Verify the file landed safely inside gallery/images/
    safe_files = list(images_dir.glob("*.png"))
    assert len(safe_files) == 1
    assert safe_files[0].parent == images_dir
