from chatgpt_library_archiver.metadata import (
    GalleryItem,
    created_at_sort_key,
    load_gallery_items,
    normalize_created_at,
    save_gallery_items,
)


def test_normalize_created_at_handles_iso_strings():
    value = "2024-01-02T03:04:05Z"
    normalized = normalize_created_at(value)
    assert isinstance(normalized, float)
    # created_at_sort_key should treat normalized float as-is
    assert created_at_sort_key(normalized) == normalized


def test_gallery_item_roundtrip_with_extras(tmp_path):
    gallery_root = tmp_path / "gallery"
    item = GalleryItem(
        id="abc",
        filename="image.jpg",
        title="Example",
        tags=["original"],
        checksum="sha256",
        content_type="image/jpeg",
        extra={"foo": "bar"},
    )
    save_gallery_items(gallery_root, [item])

    loaded = load_gallery_items(gallery_root)
    assert len(loaded) == 1
    loaded_item = loaded[0]
    assert loaded_item.id == "abc"
    assert loaded_item.filename == "image.jpg"
    assert loaded_item.title == "Example"
    assert loaded_item.checksum == "sha256"
    assert loaded_item.content_type == "image/jpeg"
    # extras are preserved without overwriting explicit values
    assert loaded_item.extra == {"foo": "bar"}
