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


def test_get_json_rejects_non_mapping():
    url = "https://example.test/not-mapping"
    client = make_client({url: FakeResponse(json_data=[1, 2, 3])})
    with pytest.raises(HttpError) as exc:
        client.get_json(url)
    assert exc.value.reason == "JSON response must be an object"


def test_get_json_closes_response_on_error():
    url = "https://example.test/error"
    error_status = 500
    response = FakeResponse(status_code=error_status, json_data={"error": "boom"})
    client = make_client({url: response})
    with pytest.raises(HttpError) as exc:
        client.get_json(url)
    assert exc.value.status_code == error_status
    assert response.closed is True


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


def test_stream_download_validates_content_prefix(tmp_path):
    url = "https://example.test/image"
    response = FakeResponse(
        headers={"Content-Type": "text/plain"},
        body=b"abc",
    )
    client = make_client({url: response})
    destination = tmp_path / "image.download"
    with pytest.raises(HttpError) as exc:
        client.stream_download(
            url,
            destination,
            expected_content_prefixes=("image/",),
        )
    assert exc.value.reason == "Unexpected content type"
    assert response.closed is True
    assert not destination.exists()


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


def test_stream_download_allows_empty_payload(tmp_path):
    url = "https://example.test/empty"
    response = FakeResponse(headers={"Content-Type": "image/png"}, body=b"")
    client = make_client({url: response})
    destination = tmp_path / "empty.download"
    result = client.stream_download(url, destination, allow_empty=True)
    assert result.bytes_downloaded == 0
    assert destination.exists()
    assert destination.read_bytes() == b""


def test_http_client_close_releases_sessions():
    url = "https://example.test/json"

    class TrackingSession(FakeSession):
        def __init__(self, responses):
            super().__init__(responses)
            self.closed = False

        def close(self) -> None:
            self.closed = True

    responses = {url: FakeResponse(json_data={"ok": True})}
    session = TrackingSession(responses)
    client = HttpClient(session_factory=lambda: session)

    assert client.get_json(url) == {"ok": True}
    assert session.closed is False

    client.close()
    assert session.closed is True
