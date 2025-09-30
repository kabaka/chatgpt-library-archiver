import io
import json

import pytest
from PIL import Image

from chatgpt_library_archiver import importer, thumbnails


def _sample_png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), color=(200, 100, 50)).save(buf, format="PNG")
    return buf.getvalue()


PNG_BYTES = _sample_png()


def always_yes(*_args, **_kwargs):
    return True


def test_import_single_file_move(monkeypatch, tmp_path):
    monkeypatch.setattr(importer, "prompt_yes_no", always_yes)

    src = tmp_path / "sample.png"
    src.write_bytes(PNG_BYTES)

    gallery_root = tmp_path / "gallery"

    imported = importer.import_images(
        inputs=[str(src)],
        gallery_root=str(gallery_root),
        tags=["tag1", "tag2"],
        conversation_links=["https://chat.openai.com/c/abc#def"],
    )

    assert len(imported) == 1
    assert not src.exists()

    dest = gallery_root / "images" / imported[0]["filename"]
    assert dest.exists()
    assert dest.read_bytes() == PNG_BYTES

    for size in thumbnails.THUMBNAIL_SIZES:
        thumb = gallery_root / "thumbs" / size / imported[0]["filename"]
        assert thumb.exists()

    metadata = json.loads((gallery_root / "metadata.json").read_text())
    assert metadata[0]["tags"] == ["tag1", "tag2"]
    assert metadata[0]["conversation_link"] == "https://chat.openai.com/c/abc#def"
    assert isinstance(metadata[0]["created_at"], float)
    assert metadata[0]["thumbnail"] == f"thumbs/medium/{imported[0]['filename']}"
    assert metadata[0]["thumbnails"]["small"] == f"thumbs/small/{imported[0]['filename']}"
    assert metadata[0]["thumbnails"]["large"] == f"thumbs/large/{imported[0]['filename']}"

    metadata = json.loads((gallery_root / "metadata.json").read_text())
    assert metadata[0]["tags"] == ["tag1", "tag2"]
    assert metadata[0]["conversation_link"] == "https://chat.openai.com/c/abc#def"
    assert isinstance(metadata[0]["created_at"], float)


def test_import_copy_keeps_source(monkeypatch, tmp_path):
    monkeypatch.setattr(importer, "prompt_yes_no", always_yes)

    src = tmp_path / "copyme.jpg"
    src.write_bytes(PNG_BYTES)

    gallery_root = tmp_path / "gallery"

    importer.import_images(
        inputs=[str(src)],
        gallery_root=str(gallery_root),
        copy_files=True,
    )

    assert src.exists()
    metadata = json.loads((gallery_root / "metadata.json").read_text())
    assert len(metadata) == 1
    for size in thumbnails.THUMBNAIL_SIZES:
        thumb = gallery_root / "thumbs" / size / metadata[0]["filename"]
        assert thumb.exists()


def test_recursive_directory_import(monkeypatch, tmp_path):
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
    (folder / "nested" / "one.png").write_bytes(PNG_BYTES)
    (folder / "nested" / "two.PNG").write_bytes(PNG_BYTES)
    (folder / "nested" / "notes.txt").write_text("ignore")

    imported = importer.import_images(
        inputs=[str(folder)],
        gallery_root=str(gallery_root),
        recursive=True,
        tags=["folder"],
    )

    # two png images imported, txt ignored
    assert len(imported) == 2

    metadata = json.loads((gallery_root / "metadata.json").read_text())
    assert len(metadata) == 3
    imported_ids = {entry["id"] for entry in imported}
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
            gallery_root=str(tmp_path / "gallery"),
            conversation_links=["only-one"],
        )


def test_regenerate_thumbnails_recreates_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(importer, "prompt_yes_no", always_yes)

    src = tmp_path / "sample.png"
    src.write_bytes(PNG_BYTES)

    gallery_root = tmp_path / "gallery"
    imported = importer.import_images(inputs=[str(src)], gallery_root=str(gallery_root))
    filename = imported[0]["filename"]
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
