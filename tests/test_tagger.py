import json
from unittest.mock import Mock

import pytest

from chatgpt_library_archiver import tagger
from chatgpt_library_archiver.ai import AIRequestTelemetry, TaggingConfig

TAGGING_WORKERS = 2
EXPECTED_TAGGED_ITEMS = 2
EXPECTED_TOKEN_OCCURRENCES = 2


def test_tag_missing_only(monkeypatch, tmp_path, write_metadata):
    gallery = write_metadata(
        tmp_path / "gallery",
        [
            {"id": "1", "filename": "a.jpg", "tags": ["keep"]},
            {"id": "2", "filename": "b.jpg", "tags": []},
        ],
        create_images=True,
    )

    mock_config = Mock(
        spec=tagger.ensure_tagging_config,
        return_value=TaggingConfig(api_key="k", model="m", prompt="p"),
    )
    monkeypatch.setattr(tagger, "ensure_tagging_config", mock_config)
    telemetry = AIRequestTelemetry("tag", "file", 0.1, 2, 1, 1, 0)
    mock_gen = Mock(spec=tagger.generate_tags, return_value=(["x", "y"], telemetry))
    monkeypatch.setattr(tagger, "generate_tags", mock_gen)

    count = tagger.tag_images(gallery_root=str(gallery))
    assert count == 1
    data = json.loads((gallery / "metadata.json").read_text())
    assert data[0]["tags"] == ["keep"]
    assert data[1]["tags"] == ["x", "y"]


def test_retag_all(monkeypatch, tmp_path, write_metadata):
    gallery = write_metadata(
        tmp_path / "gallery",
        [
            {"id": "1", "filename": "a.jpg", "tags": ["old"]},
            {"id": "2", "filename": "b.jpg", "tags": []},
        ],
        create_images=True,
    )

    mock_config = Mock(
        spec=tagger.ensure_tagging_config,
        return_value=TaggingConfig(api_key="k", model="m", prompt="p"),
    )
    monkeypatch.setattr(tagger, "ensure_tagging_config", mock_config)
    telemetry = AIRequestTelemetry("tag", "file", 0.1, 1, 1, 0, 0)
    mock_gen = Mock(spec=tagger.generate_tags, return_value=(["new"], telemetry))
    monkeypatch.setattr(tagger, "generate_tags", mock_gen)

    count = tagger.tag_images(gallery_root=str(gallery), re_tag=True)
    assert count == EXPECTED_TAGGED_ITEMS
    data = json.loads((gallery / "metadata.json").read_text())
    assert data[0]["tags"] == ["new"]
    assert data[1]["tags"] == ["new"]


def test_tag_specific_ids(monkeypatch, tmp_path, write_metadata):
    gallery = write_metadata(
        tmp_path / "gallery",
        [
            {"id": "1", "filename": "a.jpg", "tags": []},
            {"id": "2", "filename": "b.jpg", "tags": []},
        ],
        create_images=True,
    )

    mock_config = Mock(
        spec=tagger.ensure_tagging_config,
        return_value=TaggingConfig(api_key="k", model="m", prompt="p"),
    )
    monkeypatch.setattr(tagger, "ensure_tagging_config", mock_config)
    telemetry = AIRequestTelemetry("tag", "file", 0.1, 1, 1, 0, 0)
    mock_gen = Mock(spec=tagger.generate_tags, return_value=(["tagged"], telemetry))
    monkeypatch.setattr(tagger, "generate_tags", mock_gen)

    count = tagger.tag_images(gallery_root=str(gallery), ids=["2"])
    assert count == 1
    data = json.loads((gallery / "metadata.json").read_text())
    assert data[0]["tags"] == []
    assert data[1]["tags"] == ["tagged"]


def test_remove_all_tags(tmp_path, write_metadata):
    gallery = write_metadata(
        tmp_path / "gallery",
        [
            {"id": "1", "filename": "a.jpg", "tags": ["a"]},
            {"id": "2", "filename": "b.jpg", "tags": ["b"]},
        ],
        create_images=True,
    )

    count = tagger.remove_tags(gallery_root=str(gallery))
    assert count == EXPECTED_TAGGED_ITEMS
    data = json.loads((gallery / "metadata.json").read_text())
    assert data[0]["tags"] == []
    assert data[1]["tags"] == []


def test_remove_specific_ids(tmp_path, write_metadata):
    gallery = write_metadata(
        tmp_path / "gallery",
        [
            {"id": "1", "filename": "a.jpg", "tags": ["a"]},
            {"id": "2", "filename": "b.jpg", "tags": ["b"]},
        ],
        create_images=True,
    )

    count = tagger.remove_tags(gallery_root=str(gallery), ids=["1"])
    assert count == 1
    data = json.loads((gallery / "metadata.json").read_text())
    assert data[0]["tags"] == []
    assert data[1]["tags"] == ["b"]


def test_progress_and_tokens(monkeypatch, capsys, tmp_path, write_metadata):
    gallery = write_metadata(
        tmp_path / "gallery",
        [
            {"id": "1", "filename": "a.jpg", "tags": []},
            {"id": "2", "filename": "b.jpg", "tags": []},
        ],
        create_images=True,
    )

    mock_config = Mock(
        spec=tagger.ensure_tagging_config,
        return_value=TaggingConfig(api_key="k", model="m", prompt="p"),
    )
    monkeypatch.setattr(tagger, "ensure_tagging_config", mock_config)

    mock_gen = Mock(
        spec=tagger.generate_tags,
        return_value=(["t"], AIRequestTelemetry("tag", "file", 0.5, 7, 4, 3, 0)),
    )
    monkeypatch.setattr(tagger, "generate_tags", mock_gen)

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

    assert cfg.api_key == "env-key"
    assert cfg.prompt == tagger.DEFAULT_PROMPT
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


# --- Batch failure isolation test (item 4.4) ---


def test_tag_images_single_failure_does_not_abort_batch(
    monkeypatch,
    tmp_path,
    write_metadata,
):
    """When one image fails tagging, the others must still be tagged and saved."""
    gallery = write_metadata(
        tmp_path / "gallery",
        [
            {"id": "1", "filename": "a.jpg", "tags": []},
            {"id": "2", "filename": "b.jpg", "tags": ["original"]},
            {"id": "3", "filename": "c.jpg", "tags": []},
        ],
        create_images=True,
    )

    mock_config = Mock(
        spec=tagger.ensure_tagging_config,
        return_value=TaggingConfig(api_key="k", model="m", prompt="p"),
    )
    monkeypatch.setattr(tagger, "ensure_tagging_config", mock_config)

    telemetry = AIRequestTelemetry("tag", "file", 0.1, 2, 1, 1, 0)

    def tag_side_effect(image_path, client, model, prompt, *, reporter=None):
        if "b.jpg" in str(image_path):
            raise RuntimeError("API error for b.jpg")
        return (["new-tag"], telemetry)

    mock_gen = Mock(spec=tagger.generate_tags, side_effect=tag_side_effect)
    monkeypatch.setattr(tagger, "generate_tags", mock_gen)

    count = tagger.tag_images(
        gallery_root=str(gallery),
        re_tag=True,
        max_workers=1,
    )

    # Items 1 and 3 were tagged successfully
    assert count == 2

    # Metadata was saved with correct tags
    data = json.loads((gallery / "metadata.json").read_text())
    items_by_id = {item["id"]: item for item in data}
    assert items_by_id["1"]["tags"] == ["new-tag"]
    assert items_by_id["2"]["tags"] == ["original"]  # unchanged — error skipped
    assert items_by_id["3"]["tags"] == ["new-tag"]
