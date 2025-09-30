import importlib.util
import json
import os
import platform
import shutil
import subprocess
import sys
import venv
from pathlib import Path

import pytest
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


def test_gallery_subcommand_with_thumbnails(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    calls = {}

    def fake_regen(gallery_root="gallery", force=False):
        calls["gallery_root"] = gallery_root
        calls["force"] = force
        return ["a.jpg"]

    monkeypatch.setattr(importer, "regenerate_thumbnails", fake_regen)

    gallery = Path("gallery")
    (gallery / "images").mkdir(parents=True)
    (gallery / "images" / "a.jpg").write_text("img")
    with open(gallery / "metadata.json", "w", encoding="utf-8") as f:
        json.dump([{"id": "1", "filename": "a.jpg", "created_at": 1}], f)

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "chatgpt_library_archiver",
            "gallery",
            "--gallery",
            "gallery",
            "--regenerate-thumbnails",
            "--force-thumbnails",
        ],
    )
    import importlib

    cli = importlib.import_module("chatgpt_library_archiver.__main__")
    cli.main()

    assert calls["gallery_root"] == "gallery"
    assert calls["force"] is True


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
    monkeypatch.setattr(importer, "regenerate_thumbnails", lambda **kwargs: [])
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


@pytest.mark.skipif(
    platform.python_implementation() != "CPython",
    reason="Building wheels is only supported on CPython",
)
def test_console_script_help_via_built_wheel(tmp_path):
    if importlib.util.find_spec("build") is None:
        pytest.skip("build package is required to build wheels for this test")

    project_root = Path(__file__).resolve().parents[1]
    wheel_dir = tmp_path / "wheel"
    wheel_dir.mkdir()
    build_dir = project_root / "build"

    venv_dir = tmp_path / "venv"
    bin_dir = venv_dir / ("Scripts" if os.name == "nt" else "bin")
    python_name = "python.exe" if os.name == "nt" else "python"
    script_name = "chatgpt-archiver.exe" if os.name == "nt" else "chatgpt-archiver"

    try:
        subprocess.run(
            [
                sys.executable,
                "-m",
                "build",
                "--wheel",
                "--outdir",
                str(wheel_dir),
            ],
            cwd=project_root,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        wheels = list(wheel_dir.glob("chatgpt_library_archiver-*.whl"))
        assert wheels, "Wheel build did not produce any artifacts"
        wheel_path = wheels[0]

        venv.EnvBuilder(with_pip=True).create(venv_dir)
        python_bin = bin_dir / python_name

        subprocess.run(
            [str(python_bin), "-m", "pip", "install", str(wheel_path)],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        script_path = bin_dir / script_name
        result = subprocess.run(
            [str(script_path), "--help"],
            check=True,
            capture_output=True,
            text=True,
        )
    finally:
        if build_dir.exists():
            shutil.rmtree(build_dir)

    assert "usage: chatgpt-archiver" in result.stdout
