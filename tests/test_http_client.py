import hashlib

import pytest

from chatgpt_library_archiver.http_client import HttpClient, HttpError


class FakeResponse:
    def __init__(
        self,
        *,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
        json_data: dict | None = None,
        body: bytes = b"",
    ) -> None:
        self.status_code = status_code
        self.headers = headers or {"Content-Type": "application/json"}
        self._json = json_data
        self._body = body
        self.closed = False

    def json(self):
        if self._json is None:
            raise ValueError("no json")
        return self._json

    def iter_content(self, chunk_size: int = 8192):
        for idx in range(0, len(self._body), chunk_size):
            yield self._body[idx : idx + chunk_size]

    def close(self):
        self.closed = True


class FakeSession:
    def __init__(self, responses: dict[str, FakeResponse]):
        self._responses = responses

    def mount(self, prefix: str, adapter) -> None:  # pragma: no cover - no-op
        return None

    def get(self, url: str, headers=None, timeout=None, stream: bool = False):
        try:
            response = self._responses.pop(url)
        except KeyError as err:  # pragma: no cover - defensive
            raise AssertionError(f"Unexpected URL {url}") from err
        return response

    def close(self) -> None:  # pragma: no cover - no-op
        return None


def make_client(responses: dict[str, FakeResponse]) -> HttpClient:
    return HttpClient(session_factory=lambda: FakeSession(responses))


def test_get_json_success():
    url = "https://example.test/data"
    client = make_client({url: FakeResponse(json_data={"items": []})})
    data = client.get_json(url)
    assert data == {"items": []}


def test_get_json_invalid_content_type():
    url = "https://example.test/data"
    client = make_client({url: FakeResponse(headers={"Content-Type": "text/html"})})
    with pytest.raises(HttpError) as exc:
        client.get_json(url)
    assert exc.value.reason == "Response is not JSON"


def test_stream_download_writes_file(tmp_path):
    url = "https://example.test/image"
    payload = b"hello world"
    responses = {
        url: FakeResponse(
            headers={"Content-Type": "image/png"},
            body=payload,
        )
    }
    client = make_client(responses)
    destination = tmp_path / "image.download"
    result = client.stream_download(url, destination)
    assert destination.read_bytes() == payload
    assert result.checksum == hashlib.sha256(payload).hexdigest()
    assert result.content_type == "image/png"


def test_stream_download_checksum_mismatch(tmp_path):
    url = "https://example.test/image"
    payload = b"abc"
    responses = {
        url: FakeResponse(
            headers={"Content-Type": "image/png"},
            body=payload,
        )
    }
    client = make_client(responses)
    destination = tmp_path / "image.download"
    with pytest.raises(HttpError) as exc:
        client.stream_download(
            url,
            destination,
            expected_checksum="deadbeef",
        )
    assert exc.value.reason == "Checksum mismatch"
    assert not destination.exists()
