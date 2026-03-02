import json

import pytest

from chatgpt_library_archiver import importer, thumbnails
from chatgpt_library_archiver.importer import ImportConfig

EXPECTED_IMPORTED_COUNT = 2
EXPECTED_METADATA_COUNT = 3


def always_yes(*_args, **_kwargs):
    return True


def test_import_single_file_move(monkeypatch, tmp_path, sample_png_bytes):
    monkeypatch.setattr(importer, "prompt_yes_no", always_yes)

    src = tmp_path / "sample.png"
    src.write_bytes(sample_png_bytes)

    gallery_root = tmp_path / "gallery"

    imported = importer.import_images(
        inputs=[str(src)],
        config=ImportConfig(
            gallery_root=str(gallery_root),
            tags=["tag1", "tag2"],
            conversation_links=["https://chat.openai.com/c/abc#def"],
        ),
    )

    assert len(imported) == 1
    assert not src.exists()

    dest = gallery_root / "images" / imported[0].filename
    assert dest.exists()
    assert dest.read_bytes() == sample_png_bytes

    for size in thumbnails.THUMBNAIL_SIZES:
        thumb = gallery_root / "thumbs" / size / imported[0].filename
        assert thumb.exists()

    metadata = json.loads((gallery_root / "metadata.json").read_text())
    assert metadata[0]["tags"] == ["tag1", "tag2"]
    assert metadata[0]["conversation_link"] == "https://chat.openai.com/c/abc#def"
    assert isinstance(metadata[0]["created_at"], float)
    assert metadata[0]["thumbnail"] == f"thumbs/medium/{imported[0].filename}"
    assert metadata[0]["thumbnails"]["small"] == f"thumbs/small/{imported[0].filename}"
    assert metadata[0]["thumbnails"]["large"] == f"thumbs/large/{imported[0].filename}"

    metadata = json.loads((gallery_root / "metadata.json").read_text())
    assert metadata[0]["tags"] == ["tag1", "tag2"]
    assert metadata[0]["conversation_link"] == "https://chat.openai.com/c/abc#def"
    assert isinstance(metadata[0]["created_at"], float)


def test_import_copy_keeps_source(monkeypatch, tmp_path, sample_png_bytes):
    monkeypatch.setattr(importer, "prompt_yes_no", always_yes)

    src = tmp_path / "copyme.jpg"
    src.write_bytes(sample_png_bytes)

    gallery_root = tmp_path / "gallery"

    importer.import_images(
        inputs=[str(src)],
        config=ImportConfig(
            gallery_root=str(gallery_root),
            copy_files=True,
        ),
    )

    assert src.exists()
    metadata = json.loads((gallery_root / "metadata.json").read_text())
    assert len(metadata) == 1
    for size in thumbnails.THUMBNAIL_SIZES:
        thumb = gallery_root / "thumbs" / size / metadata[0]["filename"]
        assert thumb.exists()


def test_recursive_directory_import(monkeypatch, tmp_path, sample_png_bytes):
    monkeypatch.setattr(importer, "prompt_yes_no", always_yes)

    gallery_root = tmp_path / "gallery"
    gallery_root.mkdir()
    images_dir = gallery_root / "images"
    images_dir.mkdir()
    existing = {
        "id": "existing",
        "filename": "existing.png",
        "created_at": "earlier",
    }
    (gallery_root / "metadata.json").write_text(json.dumps([existing]))

    folder = tmp_path / "folder"
    (folder / "nested").mkdir(parents=True)
    (folder / "nested" / "one.png").write_bytes(sample_png_bytes)
    (folder / "nested" / "two.PNG").write_bytes(sample_png_bytes)
    (folder / "nested" / "notes.txt").write_text("ignore")

    imported = importer.import_images(
        inputs=[str(folder)],
        config=ImportConfig(
            gallery_root=str(gallery_root),
            recursive=True,
            tags=["folder"],
        ),
    )

    # two png images imported, txt ignored
    assert len(imported) == EXPECTED_IMPORTED_COUNT

    metadata = json.loads((gallery_root / "metadata.json").read_text())
    assert len(metadata) == EXPECTED_METADATA_COUNT
    imported_ids = {entry.id for entry in imported}
    for entry in metadata:
        if entry["id"] in imported_ids:
            assert entry["tags"] == ["folder"]
            assert entry["thumbnail"].startswith("thumbs/medium/")
            assert entry["thumbnails"]["medium"].startswith("thumbs/medium/")
    filenames = {entry["filename"] for entry in metadata}
    assert any(name.endswith(".png") for name in filenames if name != "existing.png")


def test_conversation_link_count_mismatch(monkeypatch, tmp_path):
    monkeypatch.setattr(importer, "prompt_yes_no", always_yes)

    f1 = tmp_path / "a.jpg"
    f2 = tmp_path / "b.jpg"
    f1.write_bytes(b"a")
    f2.write_bytes(b"b")

    with pytest.raises(ValueError):
        importer.import_images(
            inputs=[str(f1), str(f2)],
            config=ImportConfig(
                gallery_root=str(tmp_path / "gallery"),
                conversation_links=["only-one"],
            ),
        )


def test_regenerate_thumbnails_recreates_missing(
    tmp_path, monkeypatch, sample_png_bytes
):
    monkeypatch.setattr(importer, "prompt_yes_no", always_yes)

    src = tmp_path / "sample.png"
    src.write_bytes(sample_png_bytes)

    gallery_root = tmp_path / "gallery"
    imported = importer.import_images(
        inputs=[str(src)], config=ImportConfig(gallery_root=str(gallery_root))
    )
    filename = imported[0].filename
    thumb = gallery_root / "thumbs" / "medium" / filename
    thumb.unlink()

    metadata_path = gallery_root / "metadata.json"
    data = json.loads(metadata_path.read_text())
    data[0].pop("thumbnail", None)
    metadata_path.write_text(json.dumps(data))

    regenerated = importer.regenerate_thumbnails(
        gallery_root=str(gallery_root), force=False
    )

    assert regenerated == [filename]
    new_data = json.loads(metadata_path.read_text())
    assert new_data[0]["thumbnail"] == f"thumbs/medium/{filename}"
    assert new_data[0]["thumbnails"]["large"] == f"thumbs/large/{filename}"
    assert thumb.exists()
    for size in thumbnails.THUMBNAIL_SIZES:
        path = gallery_root / "thumbs" / size / filename
        assert path.exists()


# ---------------------------------------------------------------------------
# 10.7 — Unicode filenames, _slugify, and _unique_filename tests
# ---------------------------------------------------------------------------


def test_slugify_ascii_text():
    """_slugify normalizes to lowercase kebab-case."""
    assert importer._slugify("Hello World") == "hello-world"


def test_slugify_accented_characters():
    """Accented characters decompose to ASCII equivalents via NFKD."""
    assert importer._slugify("caf\u00e9 r\u00e9sum\u00e9") == "cafe-resume"


def test_slugify_chinese_characters_returns_fallback():
    """Non-ASCII characters with no Latin decomposition use the fallback."""
    assert importer._slugify("\u4f60\u597d\u4e16\u754c") == "image"


def test_slugify_emoji_returns_fallback():
    """Emoji characters are stripped and the fallback is returned."""
    assert importer._slugify("\U0001f3a8\U0001f58c\ufe0f") == "image"


def test_slugify_empty_string_returns_fallback():
    """Empty input returns the default fallback."""
    assert importer._slugify("") == "image"


def test_slugify_custom_fallback():
    """Custom fallback is used when text produces an empty slug."""
    assert importer._slugify("\u4f60\u597d", fallback="untitled") == "untitled"


def test_slugify_mixed_unicode_and_ascii():
    """Mixed content preserves the ASCII portion."""
    assert importer._slugify("hello-\u4e16\u754c-world") == "hello-world"


def test_unique_filename_no_collision():
    """First candidate is used when no collision exists."""
    existing: set[str] = set()
    result = importer._unique_filename("photo", ".png", existing)
    assert result == "photo.png"
    assert "photo.png" in existing


def test_unique_filename_with_collision():
    """Numeric suffix is added to resolve collisions."""
    existing = {"image.png"}
    result = importer._unique_filename("image", ".png", existing)
    assert result == "image-2.png"
    assert "image-2.png" in existing


def test_unique_filename_multiple_collisions():
    """Counter increments until a unique name is found."""
    existing = {"shot.jpg", "shot-2.jpg", "shot-3.jpg"}
    result = importer._unique_filename("shot", ".jpg", existing)
    assert result == "shot-4.jpg"
    assert "shot-4.jpg" in existing
