import json
from pathlib import Path
from types import SimpleNamespace

from chatgpt_library_archiver import tagger


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
        lambda path="tagging_config.json": {
            "api_key": "k",
            "model": "m",
            "prompt": "p",
        },
    )
    monkeypatch.setattr(tagger, "generate_tags", lambda *a, **k: (["x", "y"], None))

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
        lambda path="tagging_config.json": {
            "api_key": "k",
            "model": "m",
            "prompt": "p",
        },
    )
    monkeypatch.setattr(tagger, "generate_tags", lambda *a, **k: (["new"], None))

    count = tagger.tag_images(gallery_root=str(gallery), re_tag=True)
    assert count == 2
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
        lambda path="tagging_config.json": {
            "api_key": "k",
            "model": "m",
            "prompt": "p",
        },
    )
    monkeypatch.setattr(tagger, "generate_tags", lambda *a, **k: (["tagged"], None))

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
    assert count == 2
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
        lambda path="tagging_config.json": {
            "api_key": "k",
            "model": "m",
            "prompt": "p",
        },
    )
    monkeypatch.setattr(
        tagger,
        "generate_tags",
        lambda *a, **k: (["t"], SimpleNamespace(total_tokens=7)),
    )

    count = tagger.tag_images(gallery_root=str(gallery), re_tag=True, max_workers=2)
    assert count == 2

    out = capsys.readouterr().out
    assert "Uploading a.jpg" in out
    assert "Uploading b.jpg" in out
    assert "Received tags for 1" in out
    assert "Received tags for 2" in out
    assert out.count("tokens: 7") == 2
    assert "Total tokens used: 14" in out
