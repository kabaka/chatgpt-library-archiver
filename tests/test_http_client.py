import hashlib
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from chatgpt_library_archiver.http_client import (
    _SENSITIVE_HEADERS,
    HttpClient,
    HttpError,
    SafeSession,
    _origin,
)

# ---------------------------------------------------------------------------
# SafeSession / redirect credential stripping (2.1)
# ---------------------------------------------------------------------------


class TestOriginHelper:
    """Tests for the ``_origin()`` helper."""

    def test_returns_scheme_host_port(self) -> None:
        assert _origin("https://example.com:8443/path") == (
            "https",
            "example.com",
            8443,
        )

    def test_default_port_is_none(self) -> None:
        assert _origin("https://example.com/path") == ("https", "example.com", None)

    def test_none_url(self) -> None:
        assert _origin(None) == (None, None, None)

    def test_empty_string(self) -> None:
        assert _origin("") == (None, None, None)


class TestSafeSession:
    """Tests for ``SafeSession.rebuild_auth()``."""

    @staticmethod
    def _make_args(
        original_url: str, redirect_url: str, headers: dict[str, str]
    ) -> tuple[MagicMock, MagicMock]:
        """Return ``(prepared_request, response)`` fakes for rebuild_auth."""
        prepared = MagicMock()
        prepared.url = redirect_url
        prepared.headers = dict(headers)

        response = MagicMock()
        response.request = SimpleNamespace(url=original_url)
        return prepared, response

    def test_strips_sensitive_headers_on_cross_origin(self) -> None:
        session = SafeSession()
        headers = {
            "Authorization": "Bearer tok",
            "Cookie": "sess=abc",
            "oai-device-id": "dev-1",
            "oai-client-version": "v1",
            "oai-language": "en",
            "Referer": "https://chatgpt.com/",
            "User-Agent": "archiver/1.0",
            "Accept": "image/png",
        }
        prepared, response = self._make_args(
            "https://chatgpt.com/api/img/1",
            "https://cdn.example.com/img/1",
            headers,
        )
        session.rebuild_auth(prepared, response)

        # Sensitive headers removed
        for h in _SENSITIVE_HEADERS:
            assert h not in prepared.headers, f"{h} was not stripped"

        # Non-sensitive headers preserved
        assert prepared.headers["User-Agent"] == "archiver/1.0"
        assert prepared.headers["Accept"] == "image/png"

    def test_preserves_headers_on_same_origin(self) -> None:
        session = SafeSession()
        headers = {
            "Authorization": "Bearer tok",
            "Cookie": "sess=abc",
        }
        prepared, response = self._make_args(
            "https://chatgpt.com/api/img/1",
            "https://chatgpt.com/api/img/2",
            headers,
        )
        session.rebuild_auth(prepared, response)
        assert prepared.headers["Authorization"] == "Bearer tok"
        assert prepared.headers["Cookie"] == "sess=abc"

    def test_strips_on_scheme_downgrade(self) -> None:
        """HTTPS → HTTP is a cross-origin redirect (different scheme)."""
        session = SafeSession()
        headers = {"Authorization": "Bearer tok"}
        prepared, response = self._make_args(
            "https://example.com/a",
            "http://example.com/b",
            headers,
        )
        session.rebuild_auth(prepared, response)
        assert "Authorization" not in prepared.headers

    def test_strips_on_port_change(self) -> None:
        session = SafeSession()
        headers = {"Authorization": "Bearer tok"}
        prepared, response = self._make_args(
            "https://example.com:443/a",
            "https://example.com:8443/b",
            headers,
        )
        session.rebuild_auth(prepared, response)
        assert "Authorization" not in prepared.headers


def test_http_client_uses_safe_session_by_default() -> None:
    """``HttpClient`` creates ``SafeSession`` instances when no factory given."""
    client = HttpClient()
    session = client._get_session()
    assert isinstance(session, SafeSession)
    client.close()


# ---------------------------------------------------------------------------
# Defaults and configuration (7.6, 7.7)
# ---------------------------------------------------------------------------


def test_default_backoff_factor_is_one() -> None:
    """7.6 — default backoff_factor should be 1.0 for polite retry."""
    client = HttpClient()
    adapter = client._create_session().get_adapter("https://")
    assert adapter.max_retries.backoff_factor == 1.0
    client.close()


def test_custom_backoff_factor() -> None:
    """Caller can override the backoff_factor."""
    client = HttpClient(backoff_factor=2.0)
    adapter = client._create_session().get_adapter("https://")
    assert adapter.max_retries.backoff_factor == 2.0
    client.close()


def test_default_timeout_is_connect_read_tuple() -> None:
    """7.7 — default timeout should be ``(10.0, 60.0)``."""
    client = HttpClient()
    assert client.timeout == (10.0, 60.0)
    client.close()


def test_custom_connect_and_read_timeouts() -> None:
    """7.7 — caller can set connect_timeout and read_timeout separately."""
    client = HttpClient(connect_timeout=5.0, read_timeout=120.0)
    assert client.timeout == (5.0, 120.0)
    client.close()


# ---------------------------------------------------------------------------
# Fake helpers for HttpClient tests
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Timeout tuple forwarding (7.7)
# ---------------------------------------------------------------------------


class _TimeoutCapture:
    """Fake session that records the timeout passed to ``get()``."""

    captured_timeouts: list[object]

    def __init__(self) -> None:
        self.captured_timeouts = []

    def mount(self, prefix: str, adapter) -> None:
        return None

    def get(self, url: str, **kwargs):
        self.captured_timeouts.append(kwargs.get("timeout"))
        return FakeResponse(json_data={"ok": True})

    def close(self) -> None:
        return None


def test_timeout_tuple_passed_to_get_json() -> None:
    """7.7 — ``get_json`` should pass the ``(connect, read)`` tuple."""
    capture = _TimeoutCapture()
    client = HttpClient(
        connect_timeout=3.0,
        read_timeout=45.0,
        session_factory=lambda: capture,
    )
    client.get_json("https://example.test/data")
    assert capture.captured_timeouts == [(3.0, 45.0)]
    client.close()


def test_timeout_tuple_passed_to_stream_download(tmp_path) -> None:
    """7.7 — ``stream_download`` should pass the ``(connect, read)`` tuple."""

    class _StreamCapture:
        captured_timeouts: list[object]

        def __init__(self) -> None:
            self.captured_timeouts = []

        def mount(self, prefix: str, adapter) -> None:
            return None

        def get(self, url: str, **kwargs):
            self.captured_timeouts.append(kwargs.get("timeout"))
            return FakeResponse(headers={"Content-Type": "image/png"}, body=b"img")

        def close(self) -> None:
            return None

    capture = _StreamCapture()
    client = HttpClient(
        connect_timeout=7.0,
        read_timeout=90.0,
        session_factory=lambda: capture,
    )
    client.stream_download("https://example.test/img", tmp_path / "out.png")
    assert capture.captured_timeouts == [(7.0, 90.0)]
    client.close()


# ---------------------------------------------------------------------------
# get_json tests
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Download size limit (2.2)
# ---------------------------------------------------------------------------


def test_stream_download_exceeds_max_bytes(tmp_path):
    """When payload exceeds ``max_bytes``, the download is aborted and the
    partial file is cleaned up."""
    url = "https://example.test/big"
    payload = b"x" * 2048
    responses = {
        url: FakeResponse(
            headers={"Content-Type": "image/png"},
            body=payload,
        )
    }
    client = make_client(responses)
    destination = tmp_path / "big.download"
    with pytest.raises(HttpError) as exc:
        client.stream_download(url, destination, max_bytes=1024)
    assert exc.value.reason == "Download exceeds size limit"
    assert exc.value.details["max_bytes"] == 1024
    assert not destination.exists(), "partial file should be removed"


def test_stream_download_within_max_bytes(tmp_path):
    """A download smaller than ``max_bytes`` succeeds normally."""
    url = "https://example.test/small"
    payload = b"ok" * 100  # 200 bytes
    responses = {
        url: FakeResponse(
            headers={"Content-Type": "image/png"},
            body=payload,
        )
    }
    client = make_client(responses)
    destination = tmp_path / "small.download"
    result = client.stream_download(url, destination, max_bytes=1024)
    assert result.bytes_downloaded == len(payload)
    assert destination.read_bytes() == payload


def test_stream_download_max_bytes_none_means_unlimited(tmp_path):
    """When ``max_bytes`` is ``None`` (default), no limit is enforced."""
    url = "https://example.test/huge"
    payload = b"y" * 5000
    responses = {
        url: FakeResponse(
            headers={"Content-Type": "image/png"},
            body=payload,
        )
    }
    client = make_client(responses)
    destination = tmp_path / "huge.download"
    result = client.stream_download(url, destination)
    assert result.bytes_downloaded == len(payload)


def test_stream_download_max_bytes_exact_boundary(tmp_path):
    """Payload exactly equal to ``max_bytes`` should succeed (limit is
    exclusive, i.e. we raise only when bytes_downloaded > max_bytes)."""
    url = "https://example.test/exact"
    payload = b"z" * 1024
    responses = {
        url: FakeResponse(
            headers={"Content-Type": "image/png"},
            body=payload,
        )
    }
    client = make_client(responses)
    destination = tmp_path / "exact.download"
    result = client.stream_download(url, destination, max_bytes=1024)
    assert result.bytes_downloaded == 1024


# ---------------------------------------------------------------------------
# 10.2 — HTTP streaming failure test
# ---------------------------------------------------------------------------


def test_stream_download_midstream_failure_cleans_up_partial(tmp_path):
    """When iter_content raises mid-stream the partial file is deleted."""
    url = "https://example.test/image"

    class FailingResponse(FakeResponse):
        def iter_content(self, chunk_size=8192):
            yield b"partial data"
            raise ConnectionError("connection dropped")

    response = FailingResponse(headers={"Content-Type": "image/png"})
    client = make_client({url: response})
    destination = tmp_path / "partial.download"

    with pytest.raises(ConnectionError, match="connection dropped"):
        client.stream_download(url, destination)

    assert not destination.exists(), "partial file should be cleaned up"


# ---------------------------------------------------------------------------
# 10.3 — Empty response body rejection test
# ---------------------------------------------------------------------------


def test_stream_download_rejects_empty_body_by_default(tmp_path):
    """Zero bytes with allow_empty=False (default) raises HttpError."""
    url = "https://example.test/empty"
    response = FakeResponse(headers={"Content-Type": "image/png"}, body=b"")
    client = make_client({url: response})
    destination = tmp_path / "empty.download"

    with pytest.raises(HttpError) as exc:
        client.stream_download(url, destination)

    assert exc.value.reason == "Empty response body"
    assert not destination.exists(), "empty file should be removed"
