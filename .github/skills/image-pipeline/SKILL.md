---
name: image-pipeline
description: Pillow-based image processing patterns for thumbnail generation, format handling, EXIF correction, concurrent multiprocessing pipelines, and graceful error recovery for the archiver's image pipeline
---

# Image Pipeline Patterns

Pillow-based image processing patterns for chatgpt-library-archiver's thumbnail generation and image handling pipeline.

**When to use this skill:**
- Generating or modifying thumbnails
- Handling new image formats
- Optimizing image processing performance
- Dealing with corrupt or malformed images
- Designing concurrent image pipelines

## Thumbnail Generation Pattern

The archiver generates three thumbnail sizes for each image:

| Size | Dimensions | Use |
|------|-----------|-----|
| small | 150×150 | Grid view |
| medium | 250×250 | Detail view |
| large | 400×400 | Lightbox preview |

### Standard Thumbnail Workflow

```python
from PIL import Image, ImageOps, UnidentifiedImageError

def create_thumbnail(source: Path, dest: Path, size: tuple[int, int]) -> None:
    """Create a thumbnail preserving aspect ratio with EXIF correction."""
    try:
        with Image.open(source) as img:
            # 1. Fix EXIF orientation FIRST
            img = ImageOps.exif_transpose(img)

            # 2. Convert RGBA to RGB for JPEG output
            if img.mode == "RGBA" and dest.suffix.lower() in (".jpg", ".jpeg"):
                img = img.convert("RGB")

            # 3. Resize proportionally (modifies in place)
            img.thumbnail(size, Image.LANCZOS)

            # 4. Save with appropriate quality
            save_kwargs = _save_kwargs_for_format(dest.suffix)
            img.save(dest, **save_kwargs)

    except UnidentifiedImageError:
        # Corrupt or unsupported file — skip, don't crash
        pass
    except OSError:
        # Truncated file, permission error, etc.
        pass
```

### Format-Specific Save Settings

```python
def _save_kwargs_for_format(suffix: str) -> dict:
    suffix = suffix.lower()
    if suffix in (".jpg", ".jpeg"):
        return {"quality": 85, "optimize": True}
    elif suffix == ".png":
        return {"optimize": True}
    elif suffix == ".webp":
        return {"quality": 85, "method": 4}
    else:
        return {}
```

## Concurrent Processing

The archiver uses `ProcessPoolExecutor` for CPU-bound thumbnail work:

### Key Patterns

1. **Process pool** (not thread pool) for image manipulation — GIL doesn't release during Pillow C operations
2. **Status queue** for cross-process progress reporting — uses `multiprocessing.Manager().Queue()`
3. **Graceful error collection** — failed images are recorded but don't stop the pipeline
4. **Batch processing** — submit all images, collect results via `as_completed`

### Multiprocessing Safety

```python
# Worker function must be top-level (picklable)
def _thumbnail_worker(source: Path, dest: Path, size: tuple[int, int],
                       status_queue) -> str | None:
    """Process one thumbnail. Returns error message or None on success."""
    try:
        create_thumbnail(source, dest, size)
        status_queue.put(f"Created {dest.name}")
        return None
    except Exception as e:
        return f"{source.name}: {e}"
```

## Error Handling

### Common Failure Modes

| Error | Cause | Handling |
|-------|-------|----------|
| `UnidentifiedImageError` | Corrupt file, unsupported format | Skip image, log warning |
| `OSError` (truncated) | Incomplete download | Skip image, log warning |
| `DecompressionBombError` | Image exceeds pixel limit | Skip or raise limit explicitly |
| `MemoryError` | Very large image | Consider `Image.MAX_IMAGE_PIXELS` |

### Defense Against Decompression Bombs

```python
# Set a safe pixel limit (default is 178M pixels)
Image.MAX_IMAGE_PIXELS = 200_000_000  # ~200MP, adjust as needed
```

## EXIF Orientation

Always apply `ImageOps.exif_transpose()` before any resize or crop operation. This fixes images rotated by camera orientation metadata. Without this step, thumbnails may appear rotated compared to the full-size image.

## Supported Formats

```python
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff", ".tif"}
```

When adding new formats, verify:
1. Pillow supports reading and writing the format
2. Thumbnail quality is acceptable
3. EXIF handling works (or is N/A)
4. The gallery HTML can display it in `<img>` tags

## Performance Tips

- **Resize before quality**: `Image.thumbnail()` is faster on smaller images
- **Reuse images**: If generating all three sizes, open the source once, resize from largest to smallest
- **Avoid re-processing**: Check if thumbnail already exists and is newer than source
- **Process pool sizing**: Default to `multiprocessing.cpu_count()` workers; cap at a reasonable limit (e.g., 8) to avoid memory exhaustion
