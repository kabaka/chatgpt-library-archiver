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
                                "title": "test image",
                                "created_at": 1,
                            }
                        ]
                    }
                )
            else:
                return FakeResponse(json_data={"items": []})
        elif url == "https://img.local/1.jpg":
            return FakeResponse(
                content=b"img",
                headers={"Content-Type": "image/jpeg"},
            )
        raise AssertionError(f"Unexpected URL {url}")

    monkeypatch.setattr(incremental_downloader.requests, "get", fake_get)

    # Run the full download + gallery generation flow
    incremental_downloader.main()

    img_path = tmp_path / "gallery" / "images" / "1.jpg"
    meta_path = tmp_path / "gallery" / "metadata.json"
    html_path = tmp_path / "gallery" / "page_1.html"

    assert img_path.exists()
    assert meta_path.exists()
    assert html_path.exists()

    data = json.loads(meta_path.read_text())
    assert data[0]["id"] == "1"

    html = html_path.read_text()
    assert "images/1.jpg" in html
