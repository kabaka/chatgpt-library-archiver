import importlib
import importlib.util
import json
import os
import platform
import shutil
import subprocess
import sys
import venv
from pathlib import Path
from types import SimpleNamespace

import pytest

from chatgpt_library_archiver import importer, incremental_downloader, tagger
from chatgpt_library_archiver.metadata import GalleryItem


def test_main_sets_assume_yes(monkeypatch):
    module = importlib.import_module("chatgpt_library_archiver.__main__")
    previous_env = os.environ.pop("ARCHIVER_ASSUME_YES", None)

    class DummyCLI:
        def __init__(self) -> None:
            self.parsed = SimpleNamespace(yes=True)
            self.run_called_with: SimpleNamespace | None = None

        def parse_args(self, argv=None):
            return self.parsed

        def run(self, args):
            self.run_called_with = args
            return 42

    dummy_cli = DummyCLI()
    monkeypatch.setattr(module, "build_app", lambda printer=print: dummy_cli)

    expected_exit_code = 42
    result = module.main(["--yes"], printer=lambda _: None)

    assert result == expected_exit_code
    assert dummy_cli.run_called_with is dummy_cli.parsed
    assert os.environ["ARCHIVER_ASSUME_YES"] == "1"

    if previous_env is None:
        os.environ.pop("ARCHIVER_ASSUME_YES", None)
    else:
        os.environ["ARCHIVER_ASSUME_YES"] = previous_env


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

    cli = importlib.import_module("chatgpt_library_archiver.__main__")
    cli.main()

    assert called["remove_all"] is True
    assert called["gallery"] == "gallery"


def test_download_tag_new_flag(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    called = {}

    def fake_main(tag_new=False, browser=None):
        called["tag_new"] = tag_new
        called["browser"] = browser

    monkeypatch.setattr(incremental_downloader, "main", fake_main)
    monkeypatch.setattr(
        sys, "argv", ["chatgpt_library_archiver", "download", "--tag-new"]
    )

    cli = importlib.import_module("chatgpt_library_archiver.__main__")
    cli.main()

    assert called.get("tag_new") is True
    assert called.get("browser") is None


def test_download_browser_flag_edge(monkeypatch, tmp_path):
    """download --browser edge sets browser='edge' and passes it to the runner."""
    monkeypatch.chdir(tmp_path)

    called = {}

    def fake_main(tag_new=False, browser=None):
        called["tag_new"] = tag_new
        called["browser"] = browser

    monkeypatch.setattr(incremental_downloader, "main", fake_main)
    monkeypatch.setattr(
        sys, "argv", ["chatgpt_library_archiver", "download", "--browser", "edge"]
    )

    cli = importlib.import_module("chatgpt_library_archiver.__main__")
    cli.main()

    assert called["browser"] == "edge"
    assert called["tag_new"] is False


def test_download_browser_flag_chrome(monkeypatch, tmp_path):
    """download --browser chrome sets browser='chrome' and passes it to the runner."""
    monkeypatch.chdir(tmp_path)

    called = {}

    def fake_main(tag_new=False, browser=None):
        called["tag_new"] = tag_new
        called["browser"] = browser

    monkeypatch.setattr(incremental_downloader, "main", fake_main)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "chatgpt_library_archiver",
            "download",
            "--browser",
            "chrome",
            "--tag-new",
        ],
    )

    cli = importlib.import_module("chatgpt_library_archiver.__main__")
    cli.main()

    assert called["browser"] == "chrome"
    assert called["tag_new"] is True


def test_import_subcommand(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    called = {}

    def fake_import_images(**kwargs):
        called.update(kwargs)
        return [GalleryItem(id="abc", filename="example.png")]

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
            capture_output=True,
        )

        wheels = list(wheel_dir.glob("chatgpt_library_archiver-*.whl"))
        assert wheels, "Wheel build did not produce any artifacts"
        wheel_path = wheels[0]

        venv.EnvBuilder(with_pip=True, upgrade_deps=True).create(venv_dir)
        python_bin = bin_dir / python_name

        isolated_env = os.environ.copy()
        isolated_env.pop("PYTHONPATH", None)
        install_result = subprocess.run(
            [str(python_bin), "-m", "pip", "install", str(wheel_path)],
            check=True,
            capture_output=True,
            text=True,
            env=isolated_env,
        )

        script_path = bin_dir / script_name
        failure_message = (
            "console script not installed:\n"
            f"{install_result.stdout}\n{install_result.stderr}"
        )
        assert script_path.exists(), failure_message
        result = subprocess.run(
            [str(script_path), "--help"],
            check=True,
            capture_output=True,
            text=True,
            env=isolated_env,
        )
    finally:
        if build_dir.exists():
            shutil.rmtree(build_dir)

    assert "usage: chatgpt-archiver" in result.stdout


# ===================================================================
# extract-auth subcommand
# ===================================================================


def test_extract_auth_argument_parsing():
    """Parser accepts --browser, --output, --dry-run, --no-verify."""
    from chatgpt_library_archiver.cli.commands.extract_auth import ExtractAuthCommand

    captured: list[str] = []
    cmd = ExtractAuthCommand(printer=captured.append)

    import argparse

    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers()
    cmd.register(subparsers)

    args = parser.parse_args(
        [
            "extract-auth",
            "--browser",
            "chrome",
            "--output",
            "out.txt",
            "--dry-run",
            "--no-verify",
        ]
    )
    assert args.browser == "chrome"
    assert args.output == "out.txt"
    assert args.dry_run is True
    assert args.no_verify is True


def test_extract_auth_argument_defaults():
    """Default values for browser, output, dry_run, no_verify."""
    import argparse

    from chatgpt_library_archiver.cli.commands.extract_auth import ExtractAuthCommand

    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers()
    cmd = ExtractAuthCommand(printer=lambda _: None)
    cmd.register(subparsers)

    args = parser.parse_args(["extract-auth"])
    assert args.browser == "edge"
    assert args.output == "auth.txt"
    assert args.dry_run is False
    assert args.no_verify is False


def test_extract_auth_handle_writes_file(monkeypatch, tmp_path):
    """handle() calls write_auth_from_browser and prints confirmation."""
    from chatgpt_library_archiver.cli.commands.extract_auth import ExtractAuthCommand

    fake_config = {"url": "https://example.com", "authorization": "Bearer tok"}
    monkeypatch.setattr(
        "chatgpt_library_archiver.browser_extract.write_auth_from_browser",
        lambda browser, auth_path: fake_config,
    )
    # Stub out verification
    monkeypatch.setattr(
        "chatgpt_library_archiver.browser_extract.extract_auth_config",
        lambda browser: fake_config,
    )

    captured: list[str] = []
    cmd = ExtractAuthCommand(printer=captured.append)

    output_path = str(tmp_path / "auth.txt")
    args = SimpleNamespace(
        browser="edge", output=output_path, dry_run=False, no_verify=True
    )
    result = cmd.handle(args)
    assert result == 0
    assert any("Credentials written" in s for s in captured)


def test_extract_auth_handle_dry_run(monkeypatch):
    """handle() with dry_run prints masked config without writing."""
    from chatgpt_library_archiver.cli.commands.extract_auth import ExtractAuthCommand

    fake_config = {
        "url": "https://example.com",
        "authorization": "Bearer long-token-value-here",
        "cookie": "__Secure-next-auth.session-token=long-cookie-val",
    }
    monkeypatch.setattr(
        "chatgpt_library_archiver.browser_extract.extract_auth_config",
        lambda browser: fake_config,
    )

    captured: list[str] = []
    cmd = ExtractAuthCommand(printer=captured.append)

    args = SimpleNamespace(
        browser="edge", output="auth.txt", dry_run=True, no_verify=True
    )
    result = cmd.handle(args)
    assert result == 0
    assert any("dry run" in s.lower() for s in captured)
    # Sensitive keys should be masked (authorization, cookie)
    joined = "\n".join(captured)
    assert "long-token-value-here" not in joined
    assert "long-cookie-val" not in joined


def test_extract_auth_handle_error_returns_1(monkeypatch):
    """handle() returns 1 and prints message on BrowserExtractError."""
    from chatgpt_library_archiver.browser_extract import BrowserExtractError
    from chatgpt_library_archiver.cli.commands.extract_auth import ExtractAuthCommand

    def _fail(browser):
        raise BrowserExtractError("simulated error")

    def _fail2(browser, output):
        raise BrowserExtractError("simulated error")

    monkeypatch.setattr(
        "chatgpt_library_archiver.browser_extract.extract_auth_config",
        _fail,
    )
    monkeypatch.setattr(
        "chatgpt_library_archiver.browser_extract.write_auth_from_browser",
        _fail2,
    )

    captured: list[str] = []
    cmd = ExtractAuthCommand(printer=captured.append)

    args = SimpleNamespace(
        browser="edge", output="auth.txt", dry_run=False, no_verify=True
    )
    result = cmd.handle(args)
    assert result == 1
    assert any("Error" in s for s in captured)
