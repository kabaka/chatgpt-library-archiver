"""Tests for shared test helpers defined in conftest.py."""

from __future__ import annotations

import base64
import io
from types import SimpleNamespace

import pytest
from conftest import (
    CapturingResponses,
    assert_api_called_with_max_tokens,
    assert_encoded_image_within,
    make_rate_limit_error,
)
from PIL import Image

# ---------------------------------------------------------------------------
# CapturingResponses
# ---------------------------------------------------------------------------


class TestCapturingResponses:
    """Verify the CapturingResponses fake records calls correctly."""

    def test_records_call_kwargs(self):
        responses = CapturingResponses()
        responses.create(model="m", input=[], max_output_tokens=300)

        assert len(responses.call_kwargs_list) == 1
        assert responses.call_kwargs_list[0]["max_output_tokens"] == 300

    def test_returns_configured_output(self):
        responses = CapturingResponses(output_text="hello", total_tokens=10)
        result = responses.create(model="m")

        assert result.output_text == "hello"
        assert result.usage.total_tokens == 10


# ---------------------------------------------------------------------------
# assert_api_called_with_max_tokens
# ---------------------------------------------------------------------------


class TestAssertApiCalledWithMaxTokens:
    """Exercise the token-budget assertion helper."""

    def test_passes_when_max_output_tokens_matches(self):
        responses = CapturingResponses()
        client = SimpleNamespace(responses=responses)
        responses.create(model="m", input=[], max_output_tokens=300)

        assert_api_called_with_max_tokens(client, 300)

    def test_fails_when_max_output_tokens_differs(self):
        responses = CapturingResponses()
        client = SimpleNamespace(responses=responses)
        responses.create(model="m", input=[], max_output_tokens=300)

        with pytest.raises(AssertionError, match="Expected max_output_tokens=50"):
            assert_api_called_with_max_tokens(client, 50)

    def test_fails_when_create_never_called(self):
        responses = CapturingResponses()
        client = SimpleNamespace(responses=responses)

        with pytest.raises(AssertionError, match="never called"):
            assert_api_called_with_max_tokens(client, 300)

    def test_checks_most_recent_call(self):
        """When create() is called multiple times, the last call is checked."""
        responses = CapturingResponses()
        client = SimpleNamespace(responses=responses)
        responses.create(max_output_tokens=100)
        responses.create(max_output_tokens=50)

        assert_api_called_with_max_tokens(client, 50)

    def test_fails_without_call_kwargs_list(self):
        """A mock without call_kwargs_list raises a clear error."""
        client = SimpleNamespace(responses=SimpleNamespace())

        with pytest.raises(AssertionError, match="call_kwargs_list"):
            assert_api_called_with_max_tokens(client, 300)


# ---------------------------------------------------------------------------
# assert_encoded_image_within
# ---------------------------------------------------------------------------


def _make_data_url(width: int, height: int, fmt: str = "PNG") -> str:
    """Build a base64 data URL for a solid-color image of the given size."""
    img = Image.new("RGB", (width, height), (0, 128, 255))
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    mime = {"PNG": "image/png", "JPEG": "image/jpeg"}[fmt]
    payload = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:{mime};base64,{payload}"


class TestAssertEncodedImageWithin:
    """Exercise the image-resize verification helper."""

    def test_passes_when_image_within_bounds(self):
        data_url = _make_data_url(100, 80)
        assert_encoded_image_within(data_url, 100)

    def test_passes_when_image_exactly_at_limit(self):
        data_url = _make_data_url(64, 64)
        assert_encoded_image_within(data_url, 64)

    def test_fails_when_width_exceeds_max(self):
        data_url = _make_data_url(200, 100)
        with pytest.raises(AssertionError, match="exceed"):
            assert_encoded_image_within(data_url, 150)

    def test_fails_when_height_exceeds_max(self):
        data_url = _make_data_url(100, 200)
        with pytest.raises(AssertionError, match="exceed"):
            assert_encoded_image_within(data_url, 150)

    def test_handles_jpeg_data_url(self):
        data_url = _make_data_url(50, 50, fmt="JPEG")
        assert_encoded_image_within(data_url, 50)


# ---------------------------------------------------------------------------
# make_rate_limit_error
# ---------------------------------------------------------------------------


class TestMakeRateLimitError:
    """Exercise the Retry-After header factory."""

    def test_creates_rate_limit_error_instance(self):
        from openai import RateLimitError

        err = make_rate_limit_error()
        assert isinstance(err, RateLimitError)

    def test_status_code_is_429(self):
        err = make_rate_limit_error()
        assert err.response.status_code == 429

    def test_includes_retry_after_header(self):
        err = make_rate_limit_error(retry_after="30")
        assert err.response.headers.get("retry-after") == "30"

    def test_no_retry_after_header_when_none(self):
        err = make_rate_limit_error()
        assert "retry-after" not in err.response.headers

    def test_can_be_raised_and_caught(self):
        from openai import RateLimitError

        err = make_rate_limit_error(retry_after="60")
        with pytest.raises(RateLimitError):
            raise err

    def test_retry_after_accessible_from_caught_exception(self):
        """Verify the header survives a raise/catch round-trip."""
        from openai import RateLimitError

        with pytest.raises(RateLimitError) as exc_info:
            raise make_rate_limit_error(retry_after="120")
        assert exc_info.value.response.headers.get("retry-after") == "120"
