"""Shared pytest fixtures and test helpers for chatgpt-library-archiver."""

from __future__ import annotations

import base64
import io
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from openai import RateLimitError
from PIL import Image


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers."""
    config.addinivalue_line(
        "markers", "slow: marks tests as slow (deselected by default)"
    )
    config.addinivalue_line(
        "markers",
        "integration: marks integration tests requiring external resources",
    )


def _make_sample_png() -> bytes:
    """Create a minimal valid PNG image."""
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), color=(10, 20, 30)).save(buf, format="PNG")
    return buf.getvalue()


SAMPLE_PNG = _make_sample_png()


@pytest.fixture
def sample_png_bytes() -> bytes:
    """Minimal valid 8x8 PNG image bytes."""
    return SAMPLE_PNG


@pytest.fixture
def gallery_dir(tmp_path: Path) -> Path:
    """Isolated gallery directory with images/ and thumbs/ subdirectories."""
    gallery = tmp_path / "gallery"
    gallery.mkdir()
    (gallery / "images").mkdir()
    (gallery / "thumbs" / "small").mkdir(parents=True)
    (gallery / "thumbs" / "medium").mkdir(parents=True)
    (gallery / "thumbs" / "large").mkdir(parents=True)
    return gallery


@pytest.fixture
def write_metadata():
    """Return a callable that writes metadata.json under a gallery root.

    Usage::

        gallery = write_metadata(tmp_path / "gallery", items)
        gallery = write_metadata(tmp_path / "gallery", items, create_images=True)
    """

    def _write(
        root: Path, items: list[dict[str, object]], *, create_images: bool = False
    ) -> Path:
        (root / "images").mkdir(parents=True, exist_ok=True)
        with open(root / "metadata.json", "w", encoding="utf-8") as f:
            json.dump(items, f)
        if create_images:
            for item in items:
                (root / "images" / str(item["filename"])).write_text("img")
        return root

    return _write


# ---------------------------------------------------------------------------
# Reusable OpenAI mock helpers
# ---------------------------------------------------------------------------


class CapturingResponses:
    """Fake ``responses`` endpoint that records every ``create()`` call.

    Each call's keyword arguments are appended to :attr:`call_kwargs_list`
    so callers (or :func:`assert_api_called_with_max_tokens`) can inspect
    them after the code under test has run.

    Usage::

        responses = CapturingResponses()
        client = SimpleNamespace(responses=responses)
        # … pass *client* to the function under test …
        assert responses.call_kwargs_list[-1]["max_output_tokens"] == 300
    """

    def __init__(
        self,
        output_text: str = "tag1, tag2",
        total_tokens: int = 5,
        prompt_tokens: int = 2,
        completion_tokens: int = 3,
    ) -> None:
        self.call_kwargs_list: list[dict[str, object]] = []
        self._output_text = output_text
        self._total_tokens = total_tokens
        self._prompt_tokens = prompt_tokens
        self._completion_tokens = completion_tokens

    def create(self, **kwargs: object) -> SimpleNamespace:
        self.call_kwargs_list.append(kwargs)
        return SimpleNamespace(
            output_text=self._output_text,
            usage=SimpleNamespace(
                total_tokens=self._total_tokens,
                prompt_tokens=self._prompt_tokens,
                completion_tokens=self._completion_tokens,
            ),
        )


# ---------------------------------------------------------------------------
# Test assertion helpers
# ---------------------------------------------------------------------------


def assert_api_called_with_max_tokens(
    mock_client: object, expected_max_tokens: int
) -> None:
    """Assert ``responses.create`` was called with the expected token budget.

    The *mock_client* must be a ``SimpleNamespace``-based mock whose
    ``responses`` attribute has a ``call_kwargs_list`` attribute — a list
    of dicts captured from each ``create(**kwargs)`` invocation.

    Use :class:`CapturingResponses` (or a similar recording pattern) to
    populate ``call_kwargs_list`` automatically.

    Raises :class:`AssertionError` if the mock was never called or if
    ``max_output_tokens`` does not match *expected_max_tokens* in the
    most recent call.
    """

    responses = getattr(mock_client, "responses", None)
    assert responses is not None, "mock_client has no 'responses' attribute"

    call_list: list[dict[str, object]] | None = getattr(
        responses, "call_kwargs_list", None
    )
    assert call_list is not None, (
        "mock_client.responses must have a 'call_kwargs_list' attribute; "
        "use CapturingResponses or a similar recording pattern"
    )
    assert len(call_list) > 0, "responses.create() was never called"

    last_kwargs = call_list[-1]
    actual = last_kwargs.get("max_output_tokens")
    assert actual == expected_max_tokens, (
        f"Expected max_output_tokens={expected_max_tokens}, got {actual}"
    )


def assert_encoded_image_within(data_url: str, max_dim: int) -> None:
    """Assert that the image in a base64 data URL fits within *max_dim*.

    Parses the ``data:<mime>;base64,<payload>`` URL, decodes the base64
    payload, opens the result with Pillow, and asserts that **both**
    width and height are ≤ *max_dim*.
    """

    _, payload = data_url.split(",", 1)
    raw = base64.b64decode(payload)
    img = Image.open(io.BytesIO(raw))
    w, h = img.size
    assert w <= max_dim and h <= max_dim, (
        f"Image dimensions ({w}\u00d7{h}) exceed max_dim={max_dim}"
    )


def make_rate_limit_error(retry_after: str | None = None) -> RateLimitError:
    """Create a realistic ``openai.RateLimitError`` for testing.

    Parameters
    ----------
    retry_after:
        If provided, the ``Retry-After`` header value to include on the
        mock HTTP response.  Pass ``None`` (the default) to omit the
        header entirely.

    Returns
    -------
    openai.RateLimitError
        A properly constructed exception with status code 429 and the
        specified ``Retry-After`` header, ready to be raised in tests.
    """

    headers: dict[str, str] = {}
    if retry_after is not None:
        headers["Retry-After"] = retry_after

    response = httpx.Response(
        429,
        headers=headers,
        request=httpx.Request("POST", "https://api.openai.com/v1/responses"),
    )
    return RateLimitError("Rate limit exceeded", response=response, body=None)
