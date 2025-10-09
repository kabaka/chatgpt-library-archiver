"""HTTP utilities with retry/backoff, streaming downloads, and validation."""

from __future__ import annotations

import hashlib
import threading
from collections.abc import Callable, Iterable, Mapping, MutableSet
from dataclasses import dataclass
from pathlib import Path

from requests import Response, Session
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class HttpError(RuntimeError):
    """Exception raised when an HTTP request fails validation."""

    def __init__(
        self,
        *,
        url: str,
        status_code: int | None = None,
        reason: str,
        details: Mapping[str, object] | None = None,
        response: Response | None = None,
    ) -> None:
        self.url = url
        self.status_code = status_code
        self.reason = reason
        self.details = dict(details or {})
        self.response = response
        message = reason
        if status_code is not None:
            message = f"{status_code} {reason}"
        super().__init__(message)

    @property
    def context(self) -> dict[str, object]:
        """Structured details describing the failure."""

        payload = {"url": self.url, **self.details}
        if self.status_code is not None:
            payload["status_code"] = self.status_code
        return payload


@dataclass(slots=True)
class DownloadResult:
    """Metadata returned after a successful download."""

    path: Path
    bytes_downloaded: int
    checksum: str
    content_type: str | None


def _default_retry(
    *,
    retries: int,
    backoff_factor: float,
    status_forcelist: Iterable[int],
) -> Retry:
    return Retry(
        total=retries,
        connect=retries,
        read=retries,
        backoff_factor=backoff_factor,
        status_forcelist=list(status_forcelist),
        allowed_methods=("GET", "HEAD"),
        raise_on_status=False,
    )


class HttpClient:
    """Reusable HTTP client with retries and streaming helpers."""

    def __init__(
        self,
        *,
        timeout: float = 30.0,
        retries: int = 3,
        backoff_factor: float = 0.5,
        status_forcelist: Iterable[int] | None = None,
        session_factory: Callable[[], Session] | None = None,
    ) -> None:
        self.timeout = timeout
        self._retry = _default_retry(
            retries=retries,
            backoff_factor=backoff_factor,
            status_forcelist=status_forcelist or (429, 500, 502, 503, 504),
        )
        self._session_factory = session_factory or Session
        self._sessions: MutableSet[Session] = set()
        self._lock = threading.Lock()
        self._local = threading.local()

    def _create_session(self) -> Session:
        session = self._session_factory()
        adapter = HTTPAdapter(max_retries=self._retry)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        with self._lock:
            self._sessions.add(session)
        return session

    def _get_session(self) -> Session:
        session = getattr(self._local, "session", None)
        if session is None:
            session = self._create_session()
            self._local.session = session
        return session

    def close(self) -> None:
        """Close all underlying sessions."""

        with self._lock:
            sessions = list(self._sessions)
            self._sessions.clear()
        for session in sessions:
            session.close()

    def __enter__(self) -> HttpClient:
        return self

    def __exit__(self, exc_type, exc, exc_tb) -> None:  # type: ignore[override]
        self.close()

    def get_json(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        expected_content_types: Iterable[str] | None = None,
    ) -> Mapping[str, object]:
        """Fetch ``url`` and return the parsed JSON body.

        Raises :class:`HttpError` if the response is not JSON or the
        status code indicates an error.
        """

        response = self._get_session().get(url, headers=headers, timeout=self.timeout)
        content_type = response.headers.get("Content-Type", "")
        if response.status_code >= 400:
            raise HttpError(
                url=url,
                status_code=response.status_code,
                reason="HTTP request failed",
                details={"content_type": content_type},
                response=response,
            )

        if expected_content_types:
            if not any(
                content_type.lower().startswith(expected.lower())
                for expected in expected_content_types
            ):
                raise HttpError(
                    url=url,
                    status_code=response.status_code,
                    reason="Unexpected content type",
                    details={"content_type": content_type},
                    response=response,
                )
        else:
            if "json" not in content_type.lower():
                raise HttpError(
                    url=url,
                    status_code=response.status_code,
                    reason="Response is not JSON",
                    details={"content_type": content_type},
                    response=response,
                )

        try:
            data = response.json()
        except Exception as exc:  # pragma: no cover - requests wraps errors
            raise HttpError(
                url=url,
                status_code=response.status_code,
                reason="Failed to decode JSON",
                details={"content_type": content_type},
                response=response,
            ) from exc

        if not isinstance(data, Mapping):
            raise HttpError(
                url=url,
                status_code=response.status_code,
                reason="JSON response must be an object",
                details={"content_type": content_type},
                response=response,
            )
        return data

    def stream_download(
        self,
        url: str,
        destination: Path,
        *,
        headers: Mapping[str, str] | None = None,
        chunk_size: int = 1024 * 64,
        allow_empty: bool = False,
        expected_content_prefixes: Iterable[str] | None = None,
        expected_checksum: str | None = None,
    ) -> DownloadResult:
        """Download ``url`` to ``destination`` streaming the payload.

        The file is written incrementally. If ``expected_content_prefixes`` is
        provided, the ``Content-Type`` header must begin with one of the
        prefixes. When ``expected_checksum`` is supplied, the SHA-256 digest of
        the downloaded content must match it.
        """

        session = self._get_session()
        response = session.get(url, headers=headers, timeout=self.timeout, stream=True)
        content_type = response.headers.get("Content-Type")
        if response.status_code >= 400:
            response.close()
            raise HttpError(
                url=url,
                status_code=response.status_code,
                reason="HTTP request failed",
                details={"content_type": content_type},
                response=response,
            )

        if expected_content_prefixes and content_type:
            lowered = content_type.lower()
            if not any(
                lowered.startswith(prefix.lower())
                for prefix in expected_content_prefixes
            ):
                response.close()
                raise HttpError(
                    url=url,
                    status_code=response.status_code,
                    reason="Unexpected content type",
                    details={"content_type": content_type},
                    response=response,
                )

        destination.parent.mkdir(parents=True, exist_ok=True)

        hasher = hashlib.sha256()
        bytes_downloaded = 0
        try:
            with destination.open("wb") as fh:
                for chunk in response.iter_content(chunk_size=chunk_size):
                    if not chunk:
                        continue
                    fh.write(chunk)
                    hasher.update(chunk)
                    bytes_downloaded += len(chunk)
        except Exception:
            if destination.exists():
                destination.unlink()
            response.close()
            raise
        finally:
            response.close()

        if bytes_downloaded == 0 and not allow_empty:
            if destination.exists():
                destination.unlink()
            raise HttpError(
                url=url,
                status_code=response.status_code,
                reason="Empty response body",
                details={"content_type": content_type},
                response=response,
            )

        checksum = hasher.hexdigest()
        if expected_checksum and checksum != expected_checksum:
            if destination.exists():
                destination.unlink()
            raise HttpError(
                url=url,
                status_code=response.status_code,
                reason="Checksum mismatch",
                details={
                    "content_type": content_type,
                    "expected_checksum": expected_checksum,
                    "actual_checksum": checksum,
                },
                response=response,
            )

        return DownloadResult(
            path=destination,
            bytes_downloaded=bytes_downloaded,
            checksum=checksum,
            content_type=content_type,
        )
