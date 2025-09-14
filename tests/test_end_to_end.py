import json
from urllib.parse import urlparse

from chatgpt_library_archiver import incremental_downloader


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, content=b"", headers=None):
        self.status_code = status_code
        self._json = json_data or {}
        self.content = content
        self.headers = headers or {}

    def json(self):
        return self._json


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

    # Seed legacy data
    legacy = tmp_path / "gallery" / "v1" / "images"
    legacy.mkdir(parents=True)
    (legacy / "1.jpg").write_bytes(b"old")
    with open(tmp_path / "gallery" / "v1" / "metadata_v1.json", "w", encoding="utf-8") as f:
        json.dump([{"id": "1", "filename": "1.jpg", "created_at": 1}], f)

    # Mock network requests for both metadata and image download
    calls = {"meta": 0}

    def fake_get(url, headers=None, timeout=None):
        parsed = urlparse(url)
        if parsed.scheme == "https" and parsed.netloc == "api.example.com":
            calls["meta"] += 1
            if calls["meta"] == 1:
                return FakeResponse(
                    json_data={
                        "items": [
                            {
                                "id": "1",
                                "url": "https://img.local/1.jpg",
                                "title": "old image",
                                "created_at": 1,
                            },
                            {
                                "id": "2",
                                "url": "https://img.local/2.jpg",
                                "title": "new image",
                                "created_at": 2,
                            },
                        ]
                    }
                )
            else:
                return FakeResponse(json_data={"items": []})
        elif url == "https://img.local/2.jpg":
            return FakeResponse(
                content=b"img2",
                headers={"Content-Type": "image/jpeg"},
            )
        elif url == "https://img.local/1.jpg":
            raise AssertionError("Should not re-download existing image")
        raise AssertionError(f"Unexpected URL {url}")

    monkeypatch.setattr(incremental_downloader.requests, "get", fake_get)

    # Run the full download + gallery generation flow
    incremental_downloader.main()

    img1 = tmp_path / "gallery" / "images" / "1.jpg"
    img2 = tmp_path / "gallery" / "images" / "2.jpg"
    meta_path = tmp_path / "gallery" / "metadata.json"
    html_path = tmp_path / "gallery" / "page_1.html"

    assert img1.exists()
    assert img2.exists()
    assert meta_path.exists()
    assert html_path.exists()

    data = json.loads(meta_path.read_text())
    ids = {item["id"] for item in data}
    assert ids == {"1", "2"}

    html = html_path.read_text()
    assert "images/1.jpg" in html
    assert "images/2.jpg" in html
