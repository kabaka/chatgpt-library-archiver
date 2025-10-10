from __future__ import annotations

from types import SimpleNamespace

import pytest

from chatgpt_library_archiver import ai


def test_get_cached_client_reuses_instance(monkeypatch):
    created = []

    class FakeOpenAI:
        def __init__(self, api_key: str):
            created.append(api_key)

    monkeypatch.setattr(ai, "OpenAI", FakeOpenAI)
    ai.reset_client_cache()

    first = ai.get_cached_client("key-123")
    second = ai.get_cached_client("key-123")

    assert first is second
    assert created == ["key-123"]


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


def test_call_image_endpoint_retries(monkeypatch, tmp_path):
    image_path = tmp_path / "image.png"
    image_path.write_bytes(b"data")

    attempts: list[int] = []

    class DummyResponses:
        def __init__(self):
            self.calls = 0

        def create(self, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                fake_response = SimpleNamespace(
                    request=object(), status_code=429, headers={}
                )
                raise ai.RateLimitError("limit", response=fake_response, body=None)
            return SimpleNamespace(
                output_text="slug",
                usage=SimpleNamespace(
                    total_tokens=5, prompt_tokens=2, completion_tokens=3
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
    assert pytest.approx(telemetry.latency_s, 0.01) == 0.5
    assert telemetry.total_tokens == 5
    assert usage.total_tokens == 5
    assert attempts == [1]
