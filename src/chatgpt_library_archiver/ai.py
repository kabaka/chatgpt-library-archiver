"""Shared helpers for working with the OpenAI client."""

from __future__ import annotations

import base64
import logging
import mimetypes
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openai import (
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    InternalServerError,
    OpenAI,
    RateLimitError,
)

# Suppress debug logging from the OpenAI SDK and its httpx transport to
# prevent accidental API-key leakage through HTTP header logs.
logging.getLogger("openai").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)

DEFAULT_MODEL = "gpt-4.1-mini"

_CLIENT_CACHE: dict[str, OpenAI] = {}


@dataclass(slots=True)
class AIRequestTelemetry:
    """Telemetry describing a single OpenAI API request."""

    operation: str
    subject: str | None
    latency_s: float
    total_tokens: int | None
    prompt_tokens: int | None
    completion_tokens: int | None
    retries: int


@dataclass(slots=True)
class TaggingConfig:
    """Resolved configuration for AI tagging and renaming operations."""

    api_key: str
    model: str = DEFAULT_MODEL
    prompt: str = ""
    rename_prompt: str | None = None


def get_cached_client(api_key: str) -> OpenAI:
    """Return a cached ``OpenAI`` client for ``api_key``.

    The client is created with ``max_retries=0`` so that the SDK does not
    perform its own retries on top of the application-level retry loop in
    :func:`call_image_endpoint`.
    """

    client = _CLIENT_CACHE.get(api_key)
    if client is None:
        client = OpenAI(api_key=api_key, max_retries=0)
        _CLIENT_CACHE[api_key] = client
    return client


def reset_client_cache() -> None:
    """Clear the cached OpenAI clients (used by tests)."""

    _CLIENT_CACHE.clear()


def _env_override(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value:
            return value.strip()
    return None


def resolve_config(
    *,
    source: dict[str, Any] | None,
    overrides: dict[str, Any] | None = None,
) -> TaggingConfig:
    """Merge configuration from file, environment variables, and overrides."""

    if overrides and overrides.get("api_key") is not None:
        raise ValueError(
            "API key overrides are not supported; configure via file or environment."
        )

    merged: dict[str, Any] = {}
    if source:
        merged.update(source)

    env_api_key = _env_override(
        "CHATGPT_LIBRARY_ARCHIVER_OPENAI_API_KEY",
        "CHATGPT_LIBRARY_ARCHIVER_API_KEY",
        "OPENAI_API_KEY",
    )
    if env_api_key:
        merged["api_key"] = env_api_key

    env_overrides = {
        "model": _env_override("CHATGPT_LIBRARY_ARCHIVER_OPENAI_MODEL"),
        "prompt": _env_override("CHATGPT_LIBRARY_ARCHIVER_TAG_PROMPT"),
        "rename_prompt": _env_override("CHATGPT_LIBRARY_ARCHIVER_RENAME_PROMPT"),
    }
    merged.update({k: v for k, v in env_overrides.items() if v})

    if overrides:
        for key in ("model", "prompt", "rename_prompt"):
            value = overrides.get(key)
            if value is not None:
                merged[key] = value

    if not merged.get("api_key"):
        raise ValueError("tagging config missing 'api_key'")

    return TaggingConfig(
        api_key=merged["api_key"],
        model=merged.get("model", DEFAULT_MODEL),
        prompt=merged.get("prompt", ""),
        rename_prompt=merged.get("rename_prompt"),
    )


def encode_image(image_path: Path) -> tuple[str, str]:
    """Return ``(mime, data_url)`` for ``image_path`` suitable for API calls."""

    mime = mimetypes.guess_type(str(image_path))[0] or "image/jpeg"
    with image_path.open("rb") as fh:
        payload = base64.b64encode(fh.read()).decode("ascii")
    data_url = f"data:{mime};base64,{payload}"
    return mime, data_url


def _extract_usage(usage: Any | None) -> tuple[int | None, int | None, int | None]:
    if usage is None:
        return None, None, None
    total = getattr(usage, "total_tokens", None)
    prompt = getattr(usage, "prompt_tokens", None) or getattr(
        usage, "input_tokens", None
    )
    completion = getattr(usage, "completion_tokens", None) or getattr(
        usage, "output_tokens", None
    )
    return total, prompt, completion


def _is_transient(exc: Exception) -> bool:
    """Return ``True`` if *exc* is a transient OpenAI error worth retrying."""

    return isinstance(
        exc,
        (RateLimitError, APIConnectionError, APITimeoutError, InternalServerError),
    )


def call_image_endpoint(
    *,
    client: OpenAI,
    model: str,
    prompt: str,
    image_path: Path,
    operation: str,
    subject: str | None = None,
    on_retry: Callable[[int, float], None] | None = None,
    max_retries: int = 3,
    max_output_tokens: int = 300,
) -> tuple[str, AIRequestTelemetry, Any | None]:
    """Invoke ``client.responses.create`` with retries and telemetry.

    Parameters
    ----------
    max_output_tokens:
        Cap the number of completion tokens the model may generate.  Use
        ``300`` (default) for tagging and ``50`` for renaming.

    Raises
    ------
    AuthenticationError
        When the API key is invalid.  Not retried.
    BadRequestError
        When the request is rejected (e.g. content filter).  Not retried.
    """

    _, data_url = encode_image(image_path)
    retries = 0
    delay = 1.0
    start = time.perf_counter()
    while True:
        try:
            response = client.responses.create(
                model=model,
                input=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": prompt},
                            {"type": "input_image", "image_url": data_url},
                        ],
                    }
                ],
                max_output_tokens=max_output_tokens,
            )
            break
        except (AuthenticationError, BadRequestError):
            raise
        except Exception as exc:
            if not _is_transient(exc):
                raise
            if retries >= max_retries:
                raise
            if on_retry:
                on_retry(retries + 1, delay)
            time.sleep(delay)
            retries += 1
            delay *= 2

    latency = time.perf_counter() - start

    output_text = getattr(response, "output_text", None)
    text = "" if output_text is None else output_text.strip()

    usage = getattr(response, "usage", None)
    total, prompt_tokens, completion_tokens = _extract_usage(usage)
    telemetry = AIRequestTelemetry(
        operation=operation,
        subject=subject,
        latency_s=latency,
        total_tokens=total,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        retries=retries,
    )
    return text, telemetry, usage
