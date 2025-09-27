import json
import sys
from pathlib import Path

from chatgpt_library_archiver import importer, incremental_downloader, tagger


def test_gallery_subcommand(monkeypatch, tmp_path):
    # Run within temporary directory
    monkeypatch.chdir(tmp_path)

    # Ensure downloader is not invoked
    def fail(tag_new=False):  # pragma: no cover - should not be called
        raise AssertionError("incremental downloader should not run")

    monkeypatch.setattr(incremental_downloader, "main", fail)

    # Seed existing gallery data
    gallery = Path("gallery")
    (gallery / "images").mkdir(parents=True)
    (gallery / "images" / "a.jpg").write_text("img")
    with open(gallery / "metadata.json", "w", encoding="utf-8") as f:
        json.dump([{"id": "1", "filename": "a.jpg", "created_at": 1}], f)

    # Invoke CLI to regenerate gallery
    monkeypatch.setattr(sys, "argv", ["chatgpt_library_archiver", "gallery"])
    import importlib

    cli = importlib.import_module("chatgpt_library_archiver.__main__")
    cli.main()

    # Gallery regenerated from existing metadata
    assert Path("gallery/images/a.jpg").exists()
    data = json.loads(Path("gallery/metadata.json").read_text())
    assert data[0]["id"] == "1"
    assert Path("gallery/index.html").exists()


def test_tag_subcommand(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    # create minimal gallery
    gallery = Path("gallery")
    (gallery / "images").mkdir(parents=True)
    (gallery / "images" / "a.jpg").write_text("img")
    with open(gallery / "metadata.json", "w", encoding="utf-8") as f:
        json.dump([{"id": "1", "filename": "a.jpg", "tags": ["old"]}], f)

    called = {}

    def fake_main(args):
        called["gallery"] = args.gallery
        called["remove_all"] = args.remove_all
        return 0

    monkeypatch.setattr(tagger, "main", fake_main)
    monkeypatch.setattr(
        sys, "argv", ["chatgpt_library_archiver", "tag", "--remove-all"]
    )
    import importlib

    cli = importlib.import_module("chatgpt_library_archiver.__main__")
    cli.main()

    assert called["remove_all"] is True
    assert called["gallery"] == "gallery"


def test_download_tag_new_flag(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    called = {}

    def fake_main(tag_new=False):
        called["tag_new"] = tag_new

    monkeypatch.setattr(incremental_downloader, "main", fake_main)
    monkeypatch.setattr(
        sys, "argv", ["chatgpt_library_archiver", "download", "--tag-new"]
    )
    import importlib

    cli = importlib.import_module("chatgpt_library_archiver.__main__")
    cli.main()

    assert called.get("tag_new") is True


def test_import_subcommand(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    called = {}

    def fake_import_images(**kwargs):
        called.update(kwargs)
        return [{"id": "abc"}]

    monkeypatch.setattr(importer, "import_images", fake_import_images)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "chatgpt_library_archiver",
            "import",
            "example.png",
            "--copy",
            "--tag",
            "demo",
        ],
    )

    import importlib

    cli = importlib.import_module("chatgpt_library_archiver.__main__")
    cli.main()

    assert called["inputs"] == ["example.png"]
    assert called["copy_files"] is True
    assert called["tags"] == ["demo"]
