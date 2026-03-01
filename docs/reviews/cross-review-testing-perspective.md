# Cross-Review: Testing & Quality Perspective

**Date:** 2026-03-01
**Reviewer role:** Testing strategy specialist
**Reports reviewed:**
1. [Code Quality & Architecture](code-quality-architecture.md) — @python-developer
2. [Image Pipeline & Thumbnail](image-pipeline.md) — @image-processing-specialist
3. [OpenAI Integration](openai-integration.md) — @openai-specialist

**Cross-reference:** [Test Coverage & Strategy](test-coverage-strategy.md) — own prior report

---

## Executive Summary

The three reviewed reports converge on two systemic patterns that are both **testability blockers** and **production reliability risks**:

1. **Batch-abort-on-first-failure** — Both the thumbnail pipeline (`future.result()` without try/except) and the tagger thread pool (`fut.result()` without try/except) will abort an entire batch when a single item fails. This pattern is untested today, meaning both the current broken behavior and any future fix lack regression protection.

2. **High-parameter orchestration functions** — `import_images()` (16 params), `tag_images()` (11 params), and `incremental_downloader.main()` (~240 lines with closures) are the hardest modules to test. Every review flagged these as complex; from a testing perspective, they are the primary reason these modules are excluded from coverage enforcement.

The good news: the codebase already has strong testing foundations (91% line coverage on measured modules, spec-based HTTP fakes, real crypto round-trips, real Pillow processing). The gaps identified below are specific and actionable — they represent missing test *scenarios*, not missing test *infrastructure*.

---

## Report 1: Code Quality & Architecture

### Findings That Are Directly Testable

| Finding | Section | How to Test |
|---------|---------|-------------|
| `importer.py` swallows AI rename exceptions silently (§3) | Error Handling | Mock `call_image_endpoint` to raise, assert `StatusReporter.report_error()` is called (or assert it *isn't* — to document the current behavior as a known gap) |
| `_scrape_client_version()` returns `""` on any failure (§3) | Error Handling | Already partially covered in `test_browser_extract.py`; add a test that confirms the empty-string fallback and verifies logging if logging is added |
| `incremental_downloader` safety-net `except Exception` blocks marked `# pragma: no cover` (§3) | Error Handling | These are explicitly untested. Create fault-injection tests that trigger the safety nets and verify they log errors rather than silently swallowing them |
| Bare `dict` returns from 7 functions (§2) | Type Safety | Not directly testable per se, but **typed config models would make tests more expressive** — asserting `config.api_key` instead of `config["api_key"]` catches typo bugs in tests too |
| Metadata saved only after all downloads complete (§8) | Data Flow | E2E test: mock HTTP to fail mid-batch, assert that metadata from successful downloads was persisted |
| Thumbnail regeneration called twice during import (§8) | Data Flow | Instrument `create_thumbnails` with a call counter; assert it's called N times (once per file), not N + full-gallery |
| `tag_images()` conflates generate and remove (§11) | API Design | Currently tested separately (`test_tag_missing_only`, `test_remove_all_tags`), but the boolean-flag API makes it impossible to test *interactions* between modes cleanly |

### Missing Test Scenarios to Catch These Issues

1. **AI rename exception logging** — No test currently exercises the `except Exception: slug = None` path in `importer.py` L246. A test should:
   ```python
   def test_import_ai_rename_failure_falls_back_to_filename(monkeypatch, tmp_path):
       """When AI rename raises, import continues with the original filename stem."""
       monkeypatch.setattr(ai, "call_image_endpoint", Mock(side_effect=RuntimeError("API down")))
       # ... run import_images with ai_rename=True ...
       # Assert: file imported with slugified original name, no crash
   ```

2. **Incremental metadata save** — No test currently verifies that progress is lost on mid-batch crash. A test should:
   ```python
   def test_download_crash_midway_preserves_completed_items(monkeypatch, tmp_path):
       """If download fails on item 3 of 5, items 1-2 are in metadata.json."""
       # Mock HTTP to succeed for first 2 items, then raise
       # Assert metadata.json contains exactly 2 items
   ```

3. **Redundant thumbnail call** — The double-call pattern in `importer.py` is a performance issue but also a correctness concern (race conditions if metadata changes between calls). Test with a counting mock:
   ```python
   def test_import_creates_thumbnails_per_file_not_full_gallery(monkeypatch, tmp_path):
       calls = []
       monkeypatch.setattr(thumbnails, "create_thumbnails", lambda *a, **k: calls.append(1))
       monkeypatch.setattr(thumbnails, "regenerate_thumbnails", lambda *a, **k: calls.append("regen"))
       # Import 3 files
       assert calls.count(1) == 3
       assert calls.count("regen") == 1  # Documents current behavior
   ```

### Recommended Test Patterns for Remediations

**Typed config models (§2, §6):** If `TaggingConfig` and `AuthConfig` dataclasses are introduced, tests should use `pytest.raises(TypeError)` or `pytest.raises(ValidationError)` for invalid construction, and factory fixtures for valid configs:

```python
@pytest.fixture
def tagging_config() -> TaggingConfig:
    return TaggingConfig(api_key="test-key", model="gpt-4.1-mini", prompt="test prompt")
```

This replaces the 6+ occurrences of `lambda *a, **k: {"api_key": "k", "model": "m", "prompt": "p"}` scattered across `test_tagger.py`.

**Decomposed `import_images()` (§4):** If the 16-parameter function is split into `ImportConfig` + smaller functions, each extracted function becomes independently testable with focused fixtures instead of requiring the full orchestration mock setup. This is the single biggest testability win available.

**`download_image()` returning a DTO instead of mutating (§9):** If `download_image()` returns a `DownloadResult`-style object instead of mutating `GalleryItem` in-place, tests can assert return values instead of inspecting mutation side effects — a much cleaner arrange→act→assert pattern.

### How Testability Should Influence Remediation Design

- **Decompose before adding coverage.** The architecture review's recommendation to split `import_images()` and `incremental_downloader.main()` should happen *before* writing new tests for those modules, because writing tests against the current 16-parameter API will create test maintenance debt that slows down future refactors.
- **Typed configs enable parametrized testing.** With raw `dict` configs, parametrized tests need inline dict literals. With dataclasses, `pytest.mark.parametrize` can use `dataclasses.replace()` to vary one field at a time — more readable, more maintainable.
- **Return values over mutations.** The architecture review notes that `download_image()` mutates items in-place from threads. Converting to return-value-based design simultaneously fixes the fragile concurrency pattern AND makes unit tests trivial.

---

## Report 2: Image Pipeline & Thumbnail

### Findings That Are Directly Testable

| Finding | Section | How to Test |
|---------|---------|-------------|
| Batch abort on single bad image — parallel mode (§3, §5) | Error Recovery | Mock one worker to raise `RuntimeError`; assert batch continues and errors are collected |
| Batch abort on single bad image — serial mode (§5) | Error Recovery | Pass a corrupt image path to `create_thumbnails`; assert `RuntimeError` is raised (documents current behavior) |
| No `Image.MAX_IMAGE_PIXELS` protection (§4) | Security | `monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100)` and attempt to create a thumbnail of a 20×20 image; assert `DecompressionBombError` is raised and handled |
| No worker count cap (§3) | Concurrency | Parametrized test: `max_workers=None` on a machine with many cores; assert effective workers ≤ 8 (after the fix) |
| RGBA→RGB for JPEG uses black background (§6) | Format Handling | Create RGBA PNG with transparent region, generate JPEG thumbnail, verify pixel values are white (255,255,255) not black (0,0,0) — after the fix |
| No mtime-based freshness check (§8) | Incremental | Create thumbnail, modify source image, run `regenerate_thumbnails` without `force=True`; assert thumbnail is NOT regenerated (documents current behavior) |
| Animated GIF/WebP flattened to frame 0 (§6) | Format Handling | Create a 2-frame GIF, generate thumbnail, assert result is static and represents frame 0 |

### Missing Test Scenarios — Priority Order

**P1: Batch error recovery (currently `test_thumbnails.py` has 0 error-path tests)**

```python
@pytest.mark.parametrize("max_workers", [1, 2])
def test_regenerate_thumbnails_bad_image_does_not_abort_batch(monkeypatch, tmp_path, max_workers):
    """A corrupt image should be skipped; other images should still get thumbnails."""
    gallery_root = tmp_path
    images_dir = gallery_root / "images"
    images_dir.mkdir()

    # One good image, one corrupt
    (images_dir / "good.png").write_bytes(PNG_BYTES)
    (images_dir / "bad.png").write_bytes(b"not an image")

    metadata = [{"filename": "good.png"}, {"filename": "bad.png"}]
    reporter = RecordingReporter()

    processed, updated = thumbnails.regenerate_thumbnails(
        gallery_root, metadata, force=True, reporter=reporter, max_workers=max_workers,
    )

    # After fix: good.png processed, bad.png error collected
    # Before fix: this test documents that the batch aborts
    assert "good.png" in processed
```

This test pattern should be written *first* to characterize the current (broken) behavior, then updated after the fix.

**P1: Thumbnail creation failure paths**

```python
def test_create_thumbnails_missing_source_raises_runtime_error(tmp_path):
    """FileNotFoundError is wrapped in RuntimeError with source path in message."""
    missing = tmp_path / "nonexistent.png"
    dest_map = {size: tmp_path / f"{size}.png" for size in thumbnails.THUMBNAIL_SIZES}
    with pytest.raises(RuntimeError, match="nonexistent.png"):
        thumbnails.create_thumbnails(missing, dest_map)


def test_create_thumbnails_corrupt_image_raises_runtime_error(tmp_path):
    """UnidentifiedImageError is wrapped in RuntimeError."""
    corrupt = tmp_path / "bad.png"
    corrupt.write_bytes(b"not a valid image")
    dest_map = {size: tmp_path / f"{size}.png" for size in thumbnails.THUMBNAIL_SIZES}
    with pytest.raises(RuntimeError, match="bad.png"):
        thumbnails.create_thumbnails(corrupt, dest_map)
```

These are referenced in my coverage report ([test-coverage-strategy.md §6, items 4–5](test-coverage-strategy.md)) as high-priority gaps. The code at [thumbnails.py L181–184](../src/chatgpt_library_archiver/thumbnails.py#L181) catches these exceptions — it just has zero test coverage.

**P2: Format-specific branches in `_prepare_for_format`**

```python
@pytest.mark.parametrize("ext,mode,expected_mode", [
    (".webp", "RGBA", "RGBA"),   # WebP preserves transparency
    (".gif", "RGB", "P"),         # GIF converts to palette
    (".bmp", "RGB", "RGB"),       # BMP passthrough
    (".jpg", "RGBA", "RGB"),      # JPEG strips alpha
])
def test_prepare_for_format_mode_conversion(ext, mode, expected_mode, tmp_path):
    """Each format triggers the correct mode conversion."""
    source = tmp_path / f"test{ext}"
    img = Image.new(mode, (50, 50), color=(100, 100, 100, 128) if "A" in mode else (100, 100, 100))
    # Save in a compatible format first, then test _prepare_for_format
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    with Image.open(buf) as opened:
        prepared, fmt, kwargs = thumbnails._prepare_for_format(opened, ext)
        assert prepared.mode == expected_mode
```

This covers the 5 untested branches at [thumbnails.py L96–140](../src/chatgpt_library_archiver/thumbnails.py#L96) identified in both the image pipeline review (§6) and my coverage report (§1).

**P2: Incremental skip behavior**

```python
def test_regenerate_thumbnails_skips_existing(tmp_path):
    """When all thumbnail sizes exist on disk, the image is skipped."""
    gallery_root = tmp_path
    images_dir = gallery_root / "images"
    images_dir.mkdir()
    (images_dir / "photo.png").write_bytes(PNG_BYTES)

    # Pre-create all thumbnail files
    for size in thumbnails.THUMBNAIL_SIZES:
        thumb_dir = gallery_root / "thumbs" / size
        thumb_dir.mkdir(parents=True)
        (thumb_dir / "photo.png").write_bytes(b"existing")

    create_calls = []
    monkeypatch.setattr(thumbnails, "create_thumbnails", lambda *a, **k: create_calls.append(1))

    metadata = [{"filename": "photo.png"}]
    processed, updated = thumbnails.regenerate_thumbnails(gallery_root, metadata, force=False)

    assert create_calls == []  # Should not regenerate
    assert processed == []
```

### Recommended Test Patterns for Remediations

**Batch error recovery (P1 fix from image pipeline review):** After the fix wraps `future.result()` in try/except, the test pattern should verify three things:
1. Good images still produce thumbnails
2. Bad images are reported via `StatusReporter.report_error()`
3. The return value includes error information (either in the tuple or via reporter)

Use `@pytest.mark.parametrize("max_workers", [1, 2])` to test both serial and parallel code paths with the same test logic.

**Decompression bomb protection (P2 fix):** After `Image.MAX_IMAGE_PIXELS` is set at module scope:
```python
def test_decompression_bomb_raises_on_oversized_image(monkeypatch, tmp_path):
    """Images exceeding MAX_IMAGE_PIXELS are rejected."""
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100)  # Very low threshold
    img = Image.new("RGB", (20, 20))  # 400 pixels > 100
    source = tmp_path / "bomb.png"
    img.save(source)
    dest_map = {size: tmp_path / f"{size}.png" for size in thumbnails.THUMBNAIL_SIZES}
    with pytest.raises(RuntimeError, match="bomb.png"):
        thumbnails.create_thumbnails(source, dest_map)
```

**Worker count cap:** After the fix caps at `min(os.cpu_count(), 8)`:
```python
def test_regenerate_thumbnails_caps_workers_at_eight(monkeypatch, tmp_path):
    monkeypatch.setattr(os, "cpu_count", lambda: 64)
    # Capture the ProcessPoolExecutor kwargs
    # Assert max_workers == 8
```

### How Testability Should Influence Remediation Design

- **Error recovery should use the reporter, not return values.** The image pipeline review suggests returning errors alongside `(processed, updated)`. From a testing perspective, routing errors through `StatusReporter.report_error()` is better — it means tests can use the existing `RecordingReporter` mock without changing the function signature. The reporter already has a `report_error()` method and an `errors` list; leverage the existing infrastructure.
- **Create a `ThumbnailError` exception before fixing batch recovery.** The architecture review (§3) suggests replacing the generic `RuntimeError` wrap. Do this *first* — then the batch recovery try/except can catch `ThumbnailError` specifically, and tests can assert the exact exception type.
- **The `_prepare_for_format` function is already well-isolated.** Unlike the orchestration functions that need decomposition before testing, `_prepare_for_format` is a pure function (image in → image + kwargs out). Add tests for it immediately — no refactoring needed.

---

## Report 3: OpenAI Integration

### Findings That Are Directly Testable

| Finding | Section | How to Test |
|---------|---------|-------------|
| Only `RateLimitError` caught in retry loop (§2, §4) | Error Handling | `pytest.mark.parametrize` over `[APIConnectionError, APITimeoutError, RateLimitError]`; assert all three trigger retry |
| No `AuthenticationError` handling (§4) | Error Handling | Mock client to raise `AuthenticationError`; assert clear error message, not traceback |
| No `BadRequestError` handling for content filtering (§4) | Error Handling | Mock client to raise `BadRequestError`; assert image is skipped, batch continues |
| `response.output_text` not validated (§4) | Error Handling | Mock response with `output_text=None`; assert no `AttributeError` crash |
| Thread pool `fut.result()` without try/except in tagger (§4, §11) | Resilience | Submit 3 items where item 2 raises; assert items 1 and 3 are still tagged |
| SDK double-retry (max_retries=2 default × code retry=3) (§1) | Rate Limiting | Assert `OpenAI()` is called with `max_retries=0` (after fix); currently no test verifies constructor kwargs |
| No `max_tokens` on API calls (§3, §5) | Cost Management | Assert `responses.create` is called with `max_tokens` kwarg |
| `encode_image` untested (§8) | Image Encoding | Test with real small PNG, JPEG, and BMP files; assert correct MIME type and valid base64 data URL |
| No image resize before encoding (§5, §8) | Cost Management | After fix: assert encoded image dimensions ≤ 1024px |

### Missing Test Scenarios — Priority Order

**P1: Error type coverage in `call_image_endpoint`**

Currently [test_ai.py](../tests/test_ai.py) has exactly one retry test (`test_call_image_endpoint_retries`) that covers only `RateLimitError`. The OpenAI review identifies three more error types that should retry and two that should fail immediately:

```python
@pytest.mark.parametrize("error_cls", [
    ai.RateLimitError,
    # After fix, these should also retry:
    # openai.APIConnectionError,
    # openai.APITimeoutError,
])
def test_call_image_endpoint_retries_transient_errors(monkeypatch, tmp_path, error_cls):
    """Transient API errors trigger retry with backoff."""
    # Similar to existing test_call_image_endpoint_retries but parametrized


@pytest.mark.parametrize("error_cls,match", [
    (openai.AuthenticationError, "Invalid API key"),
    (openai.BadRequestError, "content filter"),
])
def test_call_image_endpoint_fatal_errors_not_retried(monkeypatch, tmp_path, error_cls, match):
    """Fatal API errors raise immediately without retry."""
    # Assert retries == 0 and specific error message
```

**P1: Retry exhaustion**

No test currently covers what happens when all retries are used up. The current code will let the final `RateLimitError` propagate uncaught:

```python
def test_call_image_endpoint_exhausts_retries_raises(monkeypatch, tmp_path):
    """After max_retries attempts, the original error propagates."""
    image_path = tmp_path / "test.png"
    image_path.write_bytes(b"data")

    client = SimpleNamespace(responses=SimpleNamespace(
        create=Mock(side_effect=ai.RateLimitError("limit", response=mock_response, body=None))
    ))
    monkeypatch.setattr(ai.time, "sleep", lambda _: None)

    with pytest.raises(ai.RateLimitError):
        ai.call_image_endpoint(client=client, model="m", prompt="p",
                               image_path=image_path, operation="tag", subject="test.png")
```

**P1: Tagger batch failure isolation**

```python
def test_tag_images_single_failure_does_not_abort_batch(monkeypatch, tmp_path):
    """A single image API failure should not prevent other images from being tagged."""
    gallery = _write_metadata(tmp_path, [
        {"id": "1", "filename": "good.jpg", "tags": []},
        {"id": "2", "filename": "bad.jpg", "tags": []},
        {"id": "3", "filename": "also_good.jpg", "tags": []},
    ])

    call_count = 0
    def fake_generate(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if "bad.jpg" in str(args):
            raise RuntimeError("Content filtered")
        return ["tagged"], AIRequestTelemetry("tag", "file", 0.1, 1, 1, 0, 0)

    monkeypatch.setattr(tagger, "ensure_tagging_config", lambda *a, **k: {"api_key": "k", "model": "m", "prompt": "p"})
    monkeypatch.setattr(tagger, "generate_tags", fake_generate)

    count = tagger.tag_images(gallery_root=str(gallery), re_tag=True)

    # After fix: count == 2 (good + also_good tagged, bad skipped)
    # Before fix: this test will raise RuntimeError — documenting the bug
    data = json.loads((gallery / "metadata.json").read_text())
    tagged_ids = [item["id"] for item in data if item["tags"]]
    assert "1" in tagged_ids
    assert "3" in tagged_ids
```

**P2: `encode_image` unit tests**

```python
class TestEncodeImage:
    def test_png_returns_correct_mime_and_data_url(self, tmp_path):
        img_path = tmp_path / "test.png"
        Image.new("RGB", (10, 10)).save(img_path)
        mime, data_url = ai.encode_image(img_path)
        assert mime == "image/png"
        assert data_url.startswith("data:image/png;base64,")
        # Verify round-trip: decode base64, open with Pillow
        b64_data = data_url.split(",", 1)[1]
        decoded = base64.b64decode(b64_data)
        img = Image.open(io.BytesIO(decoded))
        assert img.size == (10, 10)

    def test_unknown_extension_defaults_to_jpeg_mime(self, tmp_path):
        img_path = tmp_path / "test.xyz"
        img_path.write_bytes(b"fake")
        mime, data_url = ai.encode_image(img_path)
        assert mime == "image/jpeg"  # Fallback

    def test_zero_byte_file_raises(self, tmp_path):
        img_path = tmp_path / "empty.png"
        img_path.write_bytes(b"")
        # After fix: should raise ValueError("Empty file")
        # Before fix: produces invalid base64
```

**P2: `output_text` validation**

```python
@pytest.mark.parametrize("output_text", [None, ""])
def test_call_image_endpoint_handles_empty_response(monkeypatch, tmp_path, output_text):
    """Missing or empty output_text should not raise AttributeError."""
    image_path = tmp_path / "test.png"
    image_path.write_bytes(b"data")

    client = SimpleNamespace(responses=SimpleNamespace(
        create=Mock(return_value=SimpleNamespace(
            output_text=output_text,
            usage=SimpleNamespace(total_tokens=0, prompt_tokens=0, completion_tokens=0),
        ))
    ))

    result, telemetry, usage = ai.call_image_endpoint(
        client=client, model="m", prompt="p",
        image_path=image_path, operation="tag", subject="test.png",
    )
    assert result == ""  # After fix: graceful empty result
```

### Recommended Test Patterns for Remediations

**OpenAI error hierarchy testing:** Use `pytest.mark.parametrize` with the exception class as the parameter. This ensures every new error handler has a corresponding test without duplicating test logic:

```python
TRANSIENT_ERRORS = [RateLimitError, APIConnectionError, APITimeoutError]
FATAL_ERRORS = [AuthenticationError, BadRequestError]

@pytest.mark.parametrize("error_cls", TRANSIENT_ERRORS)
def test_retries_transient(error_cls, ...): ...

@pytest.mark.parametrize("error_cls", FATAL_ERRORS)
def test_no_retry_fatal(error_cls, ...): ...
```

**Replace lambda mocks with spec-based mocks in `test_tagger.py`:** The current test suite uses bare lambdas for `generate_tags` and `ensure_tagging_config`:

```python
monkeypatch.setattr(tagger, "generate_tags", lambda *a, **k: (["x", "y"], telemetry))
```

If `generate_tags` changes its signature (e.g., adding a required `config` parameter), this lambda will silently continue to work, hiding a real regression. Replace with:

```python
mock_generate = Mock(spec=tagger.generate_tags, return_value=(["x", "y"], telemetry))
monkeypatch.setattr(tagger, "generate_tags", mock_generate)
```

This validates that calls match the real function's signature.

**OpenAI client constructor kwargs:** After the fix sets `max_retries=0` and `timeout=60.0`:

```python
def test_get_cached_client_sets_no_sdk_retries(monkeypatch):
    """Client is created with max_retries=0 to prevent double retry."""
    constructor_kwargs = {}
    class SpyOpenAI:
        def __init__(self, **kwargs):
            constructor_kwargs.update(kwargs)
    monkeypatch.setattr(ai, "OpenAI", SpyOpenAI)
    ai.reset_client_cache()
    ai.get_cached_client("test-key")
    assert constructor_kwargs["max_retries"] == 0
    assert constructor_kwargs["timeout"] == 60.0
```

### How Testability Should Influence Remediation Design

- **Separate error classification from retry logic.** The OpenAI review recommends catching `APIConnectionError` and `APITimeoutError` in the retry loop. Rather than expanding the `except` clause, introduce a helper `_is_transient(exc) -> bool` that returns `True` for retryable errors. This helper is trivially testable in isolation and makes the retry loop's catch clause a single `except openai.APIError as exc: if _is_transient(exc): ...`.
- **Add an early health-check method.** The review suggests verifying the API key before starting a batch. Design this as a standalone `verify_api_key(client, model) -> bool` function, not embedded in the batch flow. This makes it independently testable and reusable.
- **`max_tokens` should be a config parameter, not hardcoded.** If `max_tokens` is added to `TaggingConfig`, it becomes testable via config validation tests and overridable in tests without monkeypatching.

---

## Cross-Cutting Themes

### 1. Lambda Mocks Are a Systemic Test Quality Risk

Both `test_tagger.py` and `test_ai.py` use lambda or `SimpleNamespace` mocks that accept any arguments silently. My [test coverage report §3](test-coverage-strategy.md) flagged this under "Concerning Patterns." The OpenAI and architecture reviews both recommend function signature changes — these changes would silently pass through the lambda mocks without any test failure.

**Recommendation:** Adopt a project-wide convention: use `Mock(spec=target_function)` or `MagicMock(spec=TargetClass)` for all non-trivial mocks. Lambdas are acceptable only for truly trivial stubs (e.g., `lambda: None` for callbacks).

### 2. The `conftest.py` Gap Amplifies Duplication

All three reviews identify patterns that need similar test fixtures:
- **Architecture review:** Typed config models → need a `tagging_config` fixture
- **Image pipeline review:** Format-specific tests → need a `sample_image(format, mode)` factory
- **OpenAI review:** Error type parametrization → need a `mock_openai_error(cls)` factory

My prior report identified `_sample_png()` duplication across 3 files and `_write_metadata()` duplication across 2 files. Creating `tests/conftest.py` with shared fixtures would reduce duplication and make adopting the new test patterns recommended above significantly easier.

### 3. Batch Failure Isolation Is the #1 Cross-Report Finding

| Report | Module | How it manifests |
|--------|--------|-----------------|
| Architecture (§3) | `tagger.py` | `fut.result()` without try/except |
| Image Pipeline (§3, §5) | `thumbnails.py` | `future.result()` without try/except |
| OpenAI (§4, §11) | `tagger.py` | Single image failure aborts entire batch |
| Architecture (§8) | `incremental_downloader.py` | Metadata only saved after all downloads |

The fix pattern is identical in all three modules: wrap `future.result()` (or the serial equivalent) in try/except, collect errors, and continue. **Write a single parametrized test fixture that validates this pattern:**

```python
# conftest.py
@pytest.fixture
def assert_batch_continues_on_failure():
    """Verify that batch processing continues when a single item fails."""
    def _check(process_fn, good_items, bad_item, **kwargs):
        items = good_items + [bad_item]
        results = process_fn(items, **kwargs)
        assert len(results.successes) == len(good_items)
        assert len(results.errors) == 1
    return _check
```

### 4. Untested Except Clauses Map

Combining all three reviews with my coverage data, here is the complete map of untested exception handlers in measured modules:

| Location | Exception Caught | Current Behavior | Test Exists? |
|----------|-----------------|------------------|-------------|
| [thumbnails.py L181](../src/chatgpt_library_archiver/thumbnails.py#L181) | `FileNotFoundError`, `UnidentifiedImageError`, `OSError` | Wraps in `RuntimeError` | **No** |
| [thumbnails.py L241](../src/chatgpt_library_archiver/thumbnails.py#L241) | (none — `future.result()` propagates) | Batch aborts | **No** |
| [http_client.py L223](../src/chatgpt_library_archiver/http_client.py#L223) | HTTP error status in `stream_download` | Raises `HttpError` | **No** |
| [http_client.py L259](../src/chatgpt_library_archiver/http_client.py#L259) | Exception during `iter_content` write | Deletes partial file | **No** |
| [http_client.py L268](../src/chatgpt_library_archiver/http_client.py#L268) | Empty response body | Raises `HttpError` | **No** |
| [ai.py L134](../src/chatgpt_library_archiver/ai.py#L134) | `RateLimitError` only | Retries with backoff | **Yes** (1 test) |
| [utils.py L47](../src/chatgpt_library_archiver/utils.py#L47) | Invalid `prompt_yes_no` input | Re-prompts | **No** |

Each of these represents a production error path that has zero test coverage. Adding tests for the first 5 rows would bring the measured modules' branch coverage from 86% closer to 90%.

---

## Prioritized Test Implementation Plan

### Phase 1: Characterize Current Behavior (do before any code changes)

These tests document the existing (sometimes broken) behavior, creating a regression baseline:

| # | Test | File | Effort |
|---|------|------|--------|
| 1 | Thumbnail creation with missing/corrupt source raises `RuntimeError` | `test_thumbnails.py` | Small |
| 2 | Batch thumbnail abort on single bad image (parametrize serial+parallel) | `test_thumbnails.py` | Small |
| 3 | `encode_image` MIME detection and base64 round-trip | `test_ai.py` | Small |
| 4 | `call_image_endpoint` retry exhaustion propagates error | `test_ai.py` | Small |
| 5 | `call_image_endpoint` with `output_text=None` | `test_ai.py` | Small |
| 6 | HTTP `stream_download` with mid-stream exception cleans up partial file | `test_http_client.py` | Small |

### Phase 2: Create Shared Infrastructure

| # | Action | File | Effort |
|---|--------|------|--------|
| 7 | Create `tests/conftest.py` with `gallery_dir`, `sample_png_bytes`, `write_metadata` fixtures | `conftest.py` | Medium |
| 8 | Replace lambda mocks with `Mock(spec=...)` in `test_tagger.py` | `test_tagger.py` | Small |
| 9 | Add `@pytest.mark.slow` marker and skip in default runs | `conftest.py`, `test_cli.py` | Small |

### Phase 3: Test the Fixes (after code remediations)

| # | Test | Validates Fix From | Effort |
|---|------|--------------------|--------|
| 10 | Batch thumbnail recovery — bad image skipped, good images processed | Image Pipeline §3, §5 | Small |
| 11 | Tagger batch isolation — single failure, other items still tagged | OpenAI §4, §11 | Medium |
| 12 | Retry loop catches `APIConnectionError` + `APITimeoutError` | OpenAI §2 | Small |
| 13 | `AuthenticationError` produces clear message, no retry | OpenAI §4 | Small |
| 14 | `_prepare_for_format` parametrized over all formats | Image Pipeline §6 | Small |
| 15 | Incremental skip with mtime-based freshness | Image Pipeline §8 | Medium |
| 16 | Decompression bomb protection | Image Pipeline §4 | Small |

### Phase 4: Integration and Edge Cases

| # | Test | Effort |
|---|------|--------|
| 17 | E2E: partial download failure preserves completed items in metadata | Medium |
| 18 | Tagger `telemetry_sink` callback receives correct data | Small |
| 19 | `_slugify` with Unicode input, empty input, collision scenarios | Small |
| 20 | Concurrent tagging with `max_workers > 1` verifies no race conditions | Medium |

---

## Agreement and Disagreement with Other Reviews

### I strongly agree with:

- **Image Pipeline P1 (batch error recovery)** — This is the most testable and highest-impact fix. The test pattern is straightforward, the fix is small, and the current behavior is clearly wrong.
- **OpenAI §4 (per-image failure isolation in tagger)** — Same pattern, same priority. These two fixes should be done together since they share the identical try/except-around-`future.result()` pattern.
- **Architecture §4 (decompose `import_images`)** — From a testing perspective, this is the enabler for everything else. The 16-parameter function is the #1 reason it's excluded from coverage enforcement.

### I mildly disagree with:

- **Architecture §2 recommending strict pyright expansion as a top-5 item.** Type checking is valuable but doesn't substitute for test coverage. The 5+ modules with suppressed complexity warnings are a bigger testing barrier than the lack of strict type checks. I'd prioritize decomposition (enabling testing) over stricter type checking (catching type-level bugs).
- **OpenAI review rating `max_tokens` as High priority.** From a testing perspective, `max_tokens` is a trivial assertion (`assert "max_tokens" in create_kwargs`). The real high-priority testing gap is error isolation — it's the difference between "one bad image crashes a 500-image batch" and "one bad image is logged and skipped."

### I'd add:

- **The `conftest.py` gap should be addressed before any new tests are written.** Both the image pipeline and OpenAI reviews recommend new test patterns that would benefit from shared fixtures. Creating `conftest.py` first prevents further duplication of `_write_metadata`, `_sample_png`, and gallery directory setup.
