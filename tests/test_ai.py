from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

from chatgpt_library_archiver import ai

EXPECTED_LATENCY = 0.5
EXPECTED_TOTAL_TOKENS = 5


# ---------------------------------------------------------------------------
# Helpers for constructing OpenAI SDK exceptions
# ---------------------------------------------------------------------------


def _fake_httpx_response(status_code: int = 429) -> httpx.Response:
    """Return a minimal ``httpx.Response`` accepted by OpenAI error constructors."""
    return httpx.Response(
        status_code,
        request=httpx.Request("POST", "https://api.openai.com/v1/responses"),
    )


def _make_status_error(cls: type, message: str = "err", status_code: int | None = None):
    """Construct an OpenAI ``APIStatusError`` subclass for testing."""
    code = status_code or {
        ai.RateLimitError: 429,
        ai.InternalServerError: 500,
        ai.AuthenticationError: 401,
        ai.BadRequestError: 400,
    }.get(cls, 500)
    return cls(message, response=_fake_httpx_response(code), body=None)


def _make_connection_error(cls: type):
    """Construct an ``APIConnectionError`` or ``APITimeoutError``."""
    req = httpx.Request("POST", "https://api.openai.com/v1/responses")
    if cls is ai.APITimeoutError:
        return cls(request=req)
    return cls(message="Connection error.", request=req)


# ---------------------------------------------------------------------------
# Client caching
# ---------------------------------------------------------------------------


def test_get_cached_client_reuses_instance(monkeypatch):
    created = []

    class FakeOpenAI:
        def __init__(self, api_key: str, **kwargs):
            created.append(api_key)
            self._kwargs = kwargs

    monkeypatch.setattr(ai, "OpenAI", FakeOpenAI)
    ai.reset_client_cache()

    first = ai.get_cached_client("key-123")
    second = ai.get_cached_client("key-123")

    assert first is second
    assert created == ["key-123"]


def test_get_cached_client_sets_max_retries_zero(monkeypatch):
    """7.2 — SDK client must have ``max_retries=0`` to avoid double-retry."""
    captured_kwargs: dict = {}

    class FakeOpenAI:
        def __init__(self, **kwargs):
            captured_kwargs.update(kwargs)

    monkeypatch.setattr(ai, "OpenAI", FakeOpenAI)
    ai.reset_client_cache()

    ai.get_cached_client("key-abc")
    assert captured_kwargs.get("max_retries") == 0


# ---------------------------------------------------------------------------
# resolve_config
# ---------------------------------------------------------------------------


def test_resolve_config_prefers_env_and_model_override(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "env")

    cfg = ai.resolve_config(
        source={"api_key": "file", "model": "file-model"},
        overrides={"model": "override"},
    )

    assert cfg["api_key"] == "env"
    assert cfg["model"] == "override"


def test_resolve_config_rejects_api_key_override(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "env")

    with pytest.raises(ValueError):
        ai.resolve_config(source=None, overrides={"api_key": "override"})


# ---------------------------------------------------------------------------
# _is_transient helper (7.1)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "error_cls",
    [
        ai.RateLimitError,
        ai.APIConnectionError,
        ai.APITimeoutError,
        ai.InternalServerError,
    ],
)
def test_is_transient_true(error_cls):
    """7.1 — Transient errors must be classified as retryable."""
    if error_cls in (ai.APIConnectionError, ai.APITimeoutError):
        exc = _make_connection_error(error_cls)
    else:
        exc = _make_status_error(error_cls)
    assert ai._is_transient(exc) is True


@pytest.mark.parametrize(
    "error_cls",
    [
        ai.AuthenticationError,
        ai.BadRequestError,
    ],
)
def test_is_transient_false(error_cls):
    """7.1 — Fatal errors must NOT be classified as transient."""
    exc = _make_status_error(error_cls)
    assert ai._is_transient(exc) is False


def test_is_transient_non_openai_error():
    """Non-OpenAI exceptions are not transient."""
    assert ai._is_transient(ValueError("oops")) is False


# ---------------------------------------------------------------------------
# call_image_endpoint — retry behaviour (7.1)
# ---------------------------------------------------------------------------


def _make_dummy_responses(error_on_first, error_cls):
    """Return a ``DummyResponses`` that raises on call 1, succeeds on call 2."""

    class DummyResponses:
        def __init__(self):
            self.calls = 0

        def create(self, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                raise error_on_first
            return SimpleNamespace(
                output_text="slug",
                usage=SimpleNamespace(
                    total_tokens=5,
                    prompt_tokens=2,
                    completion_tokens=3,
                ),
            )

    return DummyResponses()


@pytest.mark.parametrize(
    "error_cls",
    [
        ai.RateLimitError,
        ai.APIConnectionError,
        ai.APITimeoutError,
        ai.InternalServerError,
    ],
)
def test_call_image_endpoint_retries_transient_errors(monkeypatch, tmp_path, error_cls):
    """7.1 — All transient error types should trigger retry."""
    image_path = tmp_path / "image.png"
    image_path.write_bytes(b"data")

    if error_cls in (ai.APIConnectionError, ai.APITimeoutError):
        exc = _make_connection_error(error_cls)
    else:
        exc = _make_status_error(error_cls)

    client = SimpleNamespace(responses=_make_dummy_responses(exc, error_cls))

    monkeypatch.setattr(ai.time, "sleep", lambda _s: None)
    monkeypatch.setattr(ai.time, "perf_counter", iter([0.0, 0.5]).__next__)

    attempts: list[int] = []
    result, telemetry, _usage = ai.call_image_endpoint(
        client=client,
        model="m",
        prompt="p",
        image_path=image_path,
        operation="tag",
        subject="image.png",
        on_retry=lambda attempt, _delay: attempts.append(attempt),
    )

    assert result == "slug"
    assert telemetry.retries == 1
    assert attempts == [1]


def test_call_image_endpoint_retries(monkeypatch, tmp_path):
    """Original retry test — preserved for backwards compatibility."""
    image_path = tmp_path / "image.png"
    image_path.write_bytes(b"data")

    attempts: list[int] = []

    class DummyResponses:
        def __init__(self):
            self.calls = 0

        def create(self, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                raise _make_status_error(ai.RateLimitError)
            return SimpleNamespace(
                output_text="slug",
                usage=SimpleNamespace(
                    total_tokens=5,
                    prompt_tokens=2,
                    completion_tokens=3,
                ),
            )

    client = SimpleNamespace(responses=DummyResponses())

    monkeypatch.setattr(ai.time, "sleep", lambda _s: None)
    monkeypatch.setattr(ai.time, "perf_counter", iter([0.0, 0.5]).__next__)

    result, telemetry, usage = ai.call_image_endpoint(
        client=client,
        model="m",
        prompt="p",
        image_path=image_path,
        operation="rename",
        subject="image.png",
        on_retry=lambda attempt, _delay: attempts.append(attempt),
    )

    assert result == "slug"
    assert telemetry.retries == 1
    assert pytest.approx(telemetry.latency_s, 0.01) == EXPECTED_LATENCY
    assert telemetry.total_tokens == EXPECTED_TOTAL_TOKENS
    assert usage.total_tokens == EXPECTED_TOTAL_TOKENS
    assert attempts == [1]


def test_call_image_endpoint_exhausts_retries_raises(monkeypatch, tmp_path):
    """When all retries are exhausted the final exception propagates."""
    image_path = tmp_path / "image.png"
    image_path.write_bytes(b"data")

    class AlwaysFails:
        def create(self, **_kwargs):
            raise _make_status_error(ai.RateLimitError)

    client = SimpleNamespace(responses=AlwaysFails())
    monkeypatch.setattr(ai.time, "sleep", lambda _s: None)
    monkeypatch.setattr(ai.time, "perf_counter", lambda: 0.0)

    with pytest.raises(ai.RateLimitError):
        ai.call_image_endpoint(
            client=client,
            model="m",
            prompt="p",
            image_path=image_path,
            operation="tag",
            max_retries=2,
        )


# ---------------------------------------------------------------------------
# call_image_endpoint — fatal errors NOT retried (7.3)
# ---------------------------------------------------------------------------


def test_call_image_endpoint_authentication_error_not_retried(monkeypatch, tmp_path):
    """7.3 — AuthenticationError must propagate immediately without retry."""
    image_path = tmp_path / "image.png"
    image_path.write_bytes(b"data")

    class FailsAuth:
        def create(self, **_kwargs):
            raise _make_status_error(ai.AuthenticationError, "Invalid API key", 401)

    client = SimpleNamespace(responses=FailsAuth())
    monkeypatch.setattr(ai.time, "sleep", lambda _s: None)
    monkeypatch.setattr(ai.time, "perf_counter", lambda: 0.0)

    retries_attempted: list[int] = []
    with pytest.raises(ai.AuthenticationError):
        ai.call_image_endpoint(
            client=client,
            model="m",
            prompt="p",
            image_path=image_path,
            operation="tag",
            on_retry=lambda attempt, _delay: retries_attempted.append(attempt),
        )
    # No retries should have been attempted
    assert retries_attempted == []


def test_call_image_endpoint_bad_request_not_retried(monkeypatch, tmp_path):
    """7.3 — BadRequestError (content filter) must propagate without retry."""
    image_path = tmp_path / "image.png"
    image_path.write_bytes(b"data")

    class FailsBadRequest:
        def create(self, **_kwargs):
            raise _make_status_error(ai.BadRequestError, "Content filtered", 400)

    client = SimpleNamespace(responses=FailsBadRequest())
    monkeypatch.setattr(ai.time, "sleep", lambda _s: None)
    monkeypatch.setattr(ai.time, "perf_counter", lambda: 0.0)

    retries_attempted: list[int] = []
    with pytest.raises(ai.BadRequestError):
        ai.call_image_endpoint(
            client=client,
            model="m",
            prompt="p",
            image_path=image_path,
            operation="tag",
            on_retry=lambda attempt, _delay: retries_attempted.append(attempt),
        )
    assert retries_attempted == []


# ---------------------------------------------------------------------------
# call_image_endpoint — output_text validation (7.4)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("output_text", [None, ""])
def test_call_image_endpoint_handles_empty_output_text(
    monkeypatch,
    tmp_path,
    output_text,
):
    """7.4 — When output_text is None or empty, return empty string."""
    image_path = tmp_path / "image.png"
    image_path.write_bytes(b"data")

    class EmptyResponse:
        def create(self, **_kwargs):
            return SimpleNamespace(
                output_text=output_text,
                usage=SimpleNamespace(
                    total_tokens=5,
                    prompt_tokens=2,
                    completion_tokens=3,
                ),
            )

    client = SimpleNamespace(responses=EmptyResponse())
    monkeypatch.setattr(ai.time, "perf_counter", iter([0.0, 0.1]).__next__)

    result, telemetry, _usage = ai.call_image_endpoint(
        client=client,
        model="m",
        prompt="p",
        image_path=image_path,
        operation="tag",
    )

    assert result == ""
    assert telemetry.retries == 0


def test_call_image_endpoint_handles_missing_output_text_attr(monkeypatch, tmp_path):
    """7.4 — If response has no output_text attribute at all, return empty."""
    image_path = tmp_path / "image.png"
    image_path.write_bytes(b"data")

    class NoAttrResponse:
        def create(self, **_kwargs):
            return SimpleNamespace(
                usage=SimpleNamespace(
                    total_tokens=5,
                    prompt_tokens=2,
                    completion_tokens=3,
                ),
            )

    client = SimpleNamespace(responses=NoAttrResponse())
    monkeypatch.setattr(ai.time, "perf_counter", iter([0.0, 0.1]).__next__)

    result, _telemetry, _usage = ai.call_image_endpoint(
        client=client,
        model="m",
        prompt="p",
        image_path=image_path,
        operation="tag",
    )

    assert result == ""


# ---------------------------------------------------------------------------
# call_image_endpoint — max_output_tokens (7.5)
# ---------------------------------------------------------------------------


def test_call_image_endpoint_passes_max_output_tokens(monkeypatch, tmp_path):
    """7.5 — max_output_tokens is forwarded to responses.create()."""
    image_path = tmp_path / "image.png"
    image_path.write_bytes(b"data")

    captured_kwargs: dict = {}

    class CapturingResponses:
        def create(self, **kwargs):
            captured_kwargs.update(kwargs)
            return SimpleNamespace(
                output_text="tag1, tag2",
                usage=SimpleNamespace(
                    total_tokens=5,
                    prompt_tokens=2,
                    completion_tokens=3,
                ),
            )

    client = SimpleNamespace(responses=CapturingResponses())
    monkeypatch.setattr(ai.time, "perf_counter", iter([0.0, 0.1]).__next__)

    ai.call_image_endpoint(
        client=client,
        model="m",
        prompt="p",
        image_path=image_path,
        operation="tag",
        max_output_tokens=50,
    )

    assert captured_kwargs["max_output_tokens"] == 50


def test_call_image_endpoint_default_max_output_tokens(monkeypatch, tmp_path):
    """7.5 — default max_output_tokens is 300."""
    image_path = tmp_path / "image.png"
    image_path.write_bytes(b"data")

    captured_kwargs: dict = {}

    class CapturingResponses:
        def create(self, **kwargs):
            captured_kwargs.update(kwargs)
            return SimpleNamespace(
                output_text="tag1, tag2",
                usage=SimpleNamespace(
                    total_tokens=5,
                    prompt_tokens=2,
                    completion_tokens=3,
                ),
            )

    client = SimpleNamespace(responses=CapturingResponses())
    monkeypatch.setattr(ai.time, "perf_counter", iter([0.0, 0.1]).__next__)

    ai.call_image_endpoint(
        client=client,
        model="m",
        prompt="p",
        image_path=image_path,
        operation="tag",
    )

    assert captured_kwargs["max_output_tokens"] == 300
