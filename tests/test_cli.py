import json
import sys
from pathlib import Path

from chatgpt_library_archiver import incremental_downloader


def test_gallery_subcommand(monkeypatch, tmp_path):
    # Run within temporary directory
    monkeypatch.chdir(tmp_path)

    # Ensure downloader is not invoked
    def fail():  # pragma: no cover - should not be called
        raise AssertionError("incremental downloader should not run")

    monkeypatch.setattr(incremental_downloader, "main", fail)

    # Seed legacy gallery structure
    legacy = Path("gallery") / "v1"
    (legacy / "images").mkdir(parents=True)
    (legacy / "images" / "a.jpg").write_text("img")
    with open(legacy / "metadata_v1.json", "w", encoding="utf-8") as f:
        json.dump([{"id": "1", "filename": "a.jpg", "created_at": 1}], f)

    # Invoke CLI to regenerate gallery
    monkeypatch.setattr(sys, "argv", ["chatgpt_library_archiver", "gallery"])
    import importlib

    cli = importlib.import_module("chatgpt_library_archiver.__main__")
    cli.main()

    # Legacy directory removed and unified gallery generated
    assert not legacy.exists()
    assert Path("gallery/images/a.jpg").exists()
    data = json.loads(Path("gallery/metadata.json").read_text())
    assert data[0]["id"] == "1"
    assert Path("gallery/page_1.html").exists()
