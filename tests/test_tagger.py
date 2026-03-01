import json
from pathlib import Path

import pytest

from chatgpt_library_archiver import tagger
from chatgpt_library_archiver.ai import AIRequestTelemetry

TAGGING_WORKERS = 2
EXPECTED_TAGGED_ITEMS = 2
EXPECTED_TOKEN_OCCURRENCES = 2


def _write_metadata(tmp_path: Path, items):
    gallery = tmp_path / "gallery"
    (gallery / "images").mkdir(parents=True)
    with open(gallery / "metadata.json", "w", encoding="utf-8") as f:
        json.dump(items, f)
    for item in items:
        (gallery / "images" / item["filename"]).write_text("img")
    return gallery


def test_tag_missing_only(monkeypatch, tmp_path):
    gallery = _write_metadata(
        tmp_path,
        [
            {"id": "1", "filename": "a.jpg", "tags": ["keep"]},
            {"id": "2", "filename": "b.jpg", "tags": []},
        ],
    )

    monkeypatch.setattr(
        tagger,
        "ensure_tagging_config",
        lambda *a, **k: {
            "api_key": "k",
            "model": "m",
            "prompt": "p",
        },
    )
    telemetry = AIRequestTelemetry("tag", "file", 0.1, 2, 1, 1, 0)
    monkeypatch.setattr(
        tagger,
        "generate_tags",
        lambda *a, **k: (["x", "y"], telemetry),
    )

    count = tagger.tag_images(gallery_root=str(gallery))
    assert count == 1
    data = json.loads((gallery / "metadata.json").read_text())
    assert data[0]["tags"] == ["keep"]
    assert data[1]["tags"] == ["x", "y"]


def test_retag_all(monkeypatch, tmp_path):
    gallery = _write_metadata(
        tmp_path,
        [
            {"id": "1", "filename": "a.jpg", "tags": ["old"]},
            {"id": "2", "filename": "b.jpg", "tags": []},
        ],
    )

    monkeypatch.setattr(
        tagger,
        "ensure_tagging_config",
        lambda *a, **k: {
            "api_key": "k",
            "model": "m",
            "prompt": "p",
        },
    )
    telemetry = AIRequestTelemetry("tag", "file", 0.1, 1, 1, 0, 0)
    monkeypatch.setattr(
        tagger,
        "generate_tags",
        lambda *a, **k: (["new"], telemetry),
    )

    count = tagger.tag_images(gallery_root=str(gallery), re_tag=True)
    assert count == EXPECTED_TAGGED_ITEMS
    data = json.loads((gallery / "metadata.json").read_text())
    assert data[0]["tags"] == ["new"]
    assert data[1]["tags"] == ["new"]


def test_tag_specific_ids(monkeypatch, tmp_path):
    gallery = _write_metadata(
        tmp_path,
        [
            {"id": "1", "filename": "a.jpg", "tags": []},
            {"id": "2", "filename": "b.jpg", "tags": []},
        ],
    )

    monkeypatch.setattr(
        tagger,
        "ensure_tagging_config",
        lambda *a, **k: {
            "api_key": "k",
            "model": "m",
            "prompt": "p",
        },
    )
    telemetry = AIRequestTelemetry("tag", "file", 0.1, 1, 1, 0, 0)
    monkeypatch.setattr(
        tagger,
        "generate_tags",
        lambda *a, **k: (["tagged"], telemetry),
    )

    count = tagger.tag_images(gallery_root=str(gallery), ids=["2"])
    assert count == 1
    data = json.loads((gallery / "metadata.json").read_text())
    assert data[0]["tags"] == []
    assert data[1]["tags"] == ["tagged"]


def test_remove_all_tags(tmp_path):
    gallery = _write_metadata(
        tmp_path,
        [
            {"id": "1", "filename": "a.jpg", "tags": ["a"]},
            {"id": "2", "filename": "b.jpg", "tags": ["b"]},
        ],
    )

    count = tagger.tag_images(gallery_root=str(gallery), remove=True)
    assert count == EXPECTED_TAGGED_ITEMS
    data = json.loads((gallery / "metadata.json").read_text())
    assert data[0]["tags"] == []
    assert data[1]["tags"] == []


def test_remove_specific_ids(tmp_path):
    gallery = _write_metadata(
        tmp_path,
        [
            {"id": "1", "filename": "a.jpg", "tags": ["a"]},
            {"id": "2", "filename": "b.jpg", "tags": ["b"]},
        ],
    )

    count = tagger.tag_images(gallery_root=str(gallery), remove_ids=["1"])
    assert count == 1
    data = json.loads((gallery / "metadata.json").read_text())
    assert data[0]["tags"] == []
    assert data[1]["tags"] == ["b"]


def test_progress_and_tokens(monkeypatch, capsys, tmp_path):
    gallery = _write_metadata(
        tmp_path,
        [
            {"id": "1", "filename": "a.jpg", "tags": []},
            {"id": "2", "filename": "b.jpg", "tags": []},
        ],
    )

    monkeypatch.setattr(
        tagger,
        "ensure_tagging_config",
        lambda *a, **k: {
            "api_key": "k",
            "model": "m",
            "prompt": "p",
        },
    )

    def fake_generate(*_args, **_kwargs):
        return ["t"], AIRequestTelemetry("tag", "file", 0.5, 7, 4, 3, 0)

    monkeypatch.setattr(tagger, "generate_tags", fake_generate)

    count = tagger.tag_images(
        gallery_root=str(gallery), re_tag=True, max_workers=TAGGING_WORKERS
    )
    assert count == EXPECTED_TAGGED_ITEMS

    out = capsys.readouterr().out
    assert "Uploading a.jpg" in out
    assert "Uploading b.jpg" in out
    assert "Received tags for 1" in out
    assert "Received tags for 2" in out
    assert out.count("tokens: 7") == EXPECTED_TOKEN_OCCURRENCES
    assert "latency: 0.50s" in out
    assert "Total tokens used: 14 | avg latency: 0.50s" in out


def test_ensure_tagging_config_respects_env(monkeypatch, tmp_path):
    config_path = tmp_path / "tagging.json"
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")

    cfg = tagger.ensure_tagging_config(str(config_path), allow_interactive=False)

    assert cfg["api_key"] == "env-key"
    assert cfg["prompt"] == tagger.DEFAULT_PROMPT
    assert not config_path.exists()


def test_ensure_tagging_config_missing_non_interactive(monkeypatch, tmp_path):
    config_path = tmp_path / "missing.json"
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(ValueError):
        tagger.ensure_tagging_config(str(config_path), allow_interactive=False)


# --- Tag sanitization tests (item 2.6) ---


class _FakeTelemetry:
    """Minimal stand-in returned by a mocked ``call_image_endpoint``."""

    total_tokens = 10
    latency_s = 0.1
    retries = 0


def _make_generate_tags(raw_text: str):
    """Return a function that calls the *real* ``generate_tags`` parsing logic
    but bypasses the API call by injecting ``raw_text`` as the response."""

    def _fake_call_image_endpoint(**kwargs):
        return raw_text, _FakeTelemetry(), None

    return _fake_call_image_endpoint


def _parse_via_generate_tags(monkeypatch, raw_text: str) -> list[str]:
    """Helper: patch ``call_image_endpoint`` to return *raw_text*, then invoke
    ``generate_tags`` and return just the tag list."""
    monkeypatch.setattr(
        tagger,
        "call_image_endpoint",
        lambda **kw: (raw_text, _FakeTelemetry(), None),
    )
    from unittest.mock import MagicMock

    tags, _ = tagger.generate_tags(
        image_path="dummy.jpg",
        client=MagicMock(),
        model="m",
        prompt="p",
    )
    return tags


def test_tags_html_stripped(monkeypatch):
    """HTML fragments in AI-generated tags must be stripped."""
    tags = _parse_via_generate_tags(
        monkeypatch,
        "<script>alert(1)</script>cat, <b>dog</b>, <img src=x onerror=alert(1)>bird",
    )
    assert "alert(1)cat" in tags
    assert "dog" in tags
    assert "bird" in tags
    for t in tags:
        assert "<" not in t and ">" not in t


def test_tags_lowercased(monkeypatch):
    """Tags must be normalized to lowercase."""
    tags = _parse_via_generate_tags(monkeypatch, "Cat, DOG, FiSh")
    assert tags == ["cat", "dog", "fish"]


def test_tags_deduplicated(monkeypatch):
    """Duplicate tags (after normalization) must be removed, preserving order."""
    tags = _parse_via_generate_tags(monkeypatch, "cat, dog, Cat, DOG, fish")
    assert tags == ["cat", "dog", "fish"]


def test_empty_tags_excluded(monkeypatch):
    """Tags that become empty after HTML stripping / whitespace trimming are dropped."""
    tags = _parse_via_generate_tags(monkeypatch, "<b></b>, , cat, <i> </i>, dog")
    assert tags == ["cat", "dog"]


# --- _write_config getpass tests (item 2.7) ---


def test_write_config_uses_getpass_for_api_key(monkeypatch, capsys, tmp_path):
    """_write_config must use getpass.getpass for the API key, not input()."""
    getpass_calls = []

    def fake_getpass(prompt):
        getpass_calls.append(prompt)
        return "sk-test1234567890abcdef"

    inputs = iter(["gpt-4.1-mini", ""])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    monkeypatch.setattr("chatgpt_library_archiver.tagger.getpass.getpass", fake_getpass)

    config_path = str(tmp_path / "tagging_config.json")
    cfg = tagger._write_config(config_path)

    # getpass was called once for the API key
    assert len(getpass_calls) == 1
    assert "api_key" in getpass_calls[0]

    # Masked confirmation was printed
    out = capsys.readouterr().out
    assert "\u2713 API key set: sk-test1..." in out

    # Config was written correctly
    assert cfg["api_key"] == "sk-test1234567890abcdef"
    assert cfg["model"] == "gpt-4.1-mini"
