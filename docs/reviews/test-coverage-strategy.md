# Test Coverage & Strategy Review

**Date:** 2026-03-01
**Suite:** 136 tests across 14 test files
**Runtime:** ~23.5s (18.4s dominated by one test)
**Framework:** pytest + pytest-cov
**Threshold:** 85% line coverage (enforced by `make test`)

---

## 1. Coverage Analysis

### Measured Modules (included in coverage enforcement)

| Module | Stmts | Miss | Branch | BrPart | Line % | Branch % |
|--------|-------|------|--------|--------|--------|----------|
| `__init__.py` | 2 | 0 | 0 | 0 | 100% | 100% |
| `__main__.py` | 15 | 1 | 4 | 1 | 93% | 89% |
| `ai.py` | 90 | 2 | 26 | 4 | 98% | 95% |
| `gallery.py` | 25 | 4 | 10 | 1 | 84% | 80% |
| `http_client.py` | 123 | 17 | 38 | 8 | 86% | 80% |
| `metadata.py` | 101 | 2 | 28 | 5 | 98% | 95% |
| `status.py` | 84 | 4 | 26 | 5 | 95% | 92% |
| `thumbnails.py` | 191 | 28 | 90 | 12 | 85% | 81% |
| `utils.py` | 62 | 6 | 26 | 6 | 90% | 86% |
| **TOTAL** | **693** | **64** | **248** | **42** | **91%** | **86%** |

### Omitted Modules (excluded from coverage enforcement)

These modules are listed in `[tool.coverage.run] omit` in [pyproject.toml](pyproject.toml#L93):

| Module | Has Test File | Test Count | Notes |
|--------|--------------|------------|-------|
| `bootstrap.py` | Yes (`test_bootstrap.py`) | 7 | Well-tested despite omission |
| `browser_extract.py` | Yes (`test_browser_extract.py`) | ~40 | Extensively tested |
| `cli/*` | Yes (via `test_cli.py`) | ~15 | Covered through CLI integration |
| `importer.py` | Yes (`test_importer.py`) | 6 | Real image I/O tests |
| `incremental_downloader.py` | Yes (`test_end_to_end.py`) | 3 | E2E integration tests |
| `tagger.py` | Yes (`test_tagger.py`) | 8 | Good mock coverage |

**Key insight:** The omitted modules actually have substantial test suites (79+ tests). The omission from coverage enforcement is reasonable — they're I/O-heavy orchestration modules — but the tests themselves provide meaningful verification.

### Specific Uncovered Lines

**[gallery.py](src/chatgpt_library_archiver/gallery.py#L45-L49)** — `if __name__ == "__main__"` block. Low priority.

**[http_client.py](src/chatgpt_library_archiver/http_client.py):**
- [Lines 44–47](src/chatgpt_library_archiver/http_client.py#L44-L47): `HttpError.context` property never exercised directly (only indirectly through E2E tests)
- [Lines 157–161](src/chatgpt_library_archiver/http_client.py#L157-L161): `expected_content_types` parameter path in `get_json`
- [Lines 223–224](src/chatgpt_library_archiver/http_client.py#L223-L224): HTTP error status path in `stream_download`
- [Lines 255–270](src/chatgpt_library_archiver/http_client.py#L255-L270): Empty response body and exception-during-write paths

**[thumbnails.py](src/chatgpt_library_archiver/thumbnails.py):**
- [Lines 96–98](src/chatgpt_library_archiver/thumbnails.py#L96-L98): BMP/TIFF/GIF format inference paths
- [Lines 128–140](src/chatgpt_library_archiver/thumbnails.py#L128-L140): WebP, GIF, and BMP `_prepare_for_format` branches
- [Lines 181–184](src/chatgpt_library_archiver/thumbnails.py#L181-L184): `UnidentifiedImageError` / `OSError` handling in `create_thumbnails`
- [Lines 206–209](src/chatgpt_library_archiver/thumbnails.py#L206-L209): Error reporting in `_create_thumbnails_worker`

**[utils.py](src/chatgpt_library_archiver/utils.py):**
- [Line 47](src/chatgpt_library_archiver/utils.py#L47): The `while True` re-prompt loop on invalid input
- [Line 80](src/chatgpt_library_archiver/utils.py#L80): Empty field re-prompt in `prompt_and_write_auth`
- [Lines 96–109](src/chatgpt_library_archiver/utils.py#L96-L109): Re-enter credentials flow in `ensure_auth_config`

---

## 2. Test Quality Assessment

### Strengths

**Comprehensive assertions.** Tests generally verify multiple properties rather than just checking for non-failure. Example from [test_end_to_end.py](tests/test_end_to_end.py#L87-L102):

```python
data = json.loads(meta_path.read_text())
ids = {item["id"] for item in data}
assert ids == {"1", "2"}
assert tagged["ids"] == ["2"]
for item in data:
    if item["id"] == "2":
        assert item.get("tags") == ["t"]
        assert item.get("checksum") == hashlib.sha256(PNG_BYTES).hexdigest()
        assert item.get("content_type") == "image/png"
    assert item["thumbnail"].startswith("thumbs/medium/")
```

**Error-path testing.** The browser_extract tests cover numerous failure modes — wrong key, invalid padding, non-UTF-8, corrupt lengths, missing DBs, unsupported browsers, platform checks:

```python
def test_decrypt_cookie_value_wrong_key_raises():
    encrypted = _encrypt_value("hello", _FAKE_KEY)
    wrong_key = _derive_key("wrong-password")
    with pytest.raises(CookieDecryptionError, match=r"padding|UTF-8"):
        _decrypt_cookie_value(encrypted, wrong_key)
```

**Real cryptographic round-trips.** [test_browser_extract.py](tests/test_browser_extract.py#L55-L80) creates real encrypted cookies with AES-128-CBC and decrypts them, testing the actual algorithm rather than mocking it away. This includes the v24 domain-hash variant.

### Weaknesses

**Some tests verify structure over behavior.** Several gallery template tests only assert that specific CSS/HTML strings exist in the template file, not that they produce correct rendering behavior:

```python
def test_gallery_has_sticky_header():
    html = resources.read_text("chatgpt_library_archiver", "gallery_index.html")
    assert '<header class="top-bar">' in html
    assert "position: sticky" in html
```

These are essentially snapshot/regression tests. They'd pass even if the CSS was in a comment or applied to the wrong element.

**Missing negative assertions in some tests.** For example, `test_tag_missing_only` verifies the tagged item got tags but doesn't check that the already-tagged item was *not* re-tagged by verifying it wasn't passed to `generate_tags`:

```python
# test_tagger.py - verifies outcome but not that generate_tags wasn't called for item 1
assert data[0]["tags"] == ["keep"]  # correct but generate_tags mock always returns same result
```

---

## 3. Mock Strategy

### Good Patterns

**Spec-based fakes for HTTP.** [test_http_client.py](tests/test_http_client.py#L5-L42) defines `FakeResponse` and `FakeSession` with realistic interfaces and explicit status codes, headers, and streaming bodies. The `HttpClient` accepts a `session_factory` injection point that makes this clean:

```python
def make_client(responses: dict[str, FakeResponse]) -> HttpClient:
    return HttpClient(session_factory=lambda: FakeSession(responses))
```

**Real image bytes.** Multiple test files generate real (tiny) PNG images via Pillow rather than using arbitrary bytes. This ensures thumbnail generation and import workflows process actual images:

```python
def _sample_png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (6, 6), color=(50, 120, 200)).save(buf, format="PNG")
    return buf.getvalue()
```

**Crypto round-trip mocks.** Browser extract tests use real AES-128-CBC encryption/decryption with real PBKDF2 key derivation, only mocking the keychain access and file paths.

### Concerning Patterns

**Duplicated helper code.** `_sample_png()` / `PNG_BYTES` is defined independently in three files:
- [test_end_to_end.py](tests/test_end_to_end.py#L8-L12)
- [test_importer.py](tests/test_importer.py#L9-L13)
- [test_thumbnails.py](tests/test_thumbnails.py#L10-L14)

Each uses slightly different colors and sizes. These should be consolidated into a shared `conftest.py` fixture.

**Mock helpers at module bottom.** In [test_browser_extract.py](tests/test_browser_extract.py#L675-L771), `_make_mock_http_client` and `_make_mock_http_client_for_scrape` are defined after the tests that use them. This fails the readability principle of defining helpers before usage. The tests that call these helpers are at line ~350+ while the definitions are at line ~675+.

**Lambda mocks lose interface verification.** Several tests replace module functions with bare lambdas:

```python
monkeypatch.setattr(tagger, "generate_tags", lambda *a, **k: (["x", "y"], telemetry))
```

These accept any signature without complaint. If `generate_tags` changes its API, these tests would still pass — they don't verify the call interface. Using `MagicMock(spec=...)` or explicit function signatures would catch regressions.

---

## 4. Test Isolation

### Status: Good

- **Filesystem:** All file-based tests use `tmp_path` or `tempfile.TemporaryDirectory`. The `monkeypatch.chdir(tmp_path)` pattern in CLI tests ensures safe working-directory isolation.
- **Environment variables:** `monkeypatch.setenv()` and `monkeypatch.delenv()` used consistently. The [test_bootstrap.py](tests/test_bootstrap.py#L8-L11) `restore_env` autouse fixture is a good pattern.
- **Module state:** `ai.reset_client_cache()` is called explicitly in [test_ai.py](tests/test_ai.py#L17). This is the only global state mutation.
- **No ordering dependencies detected.** Tests can run in any order.

### Minor Observations

- [test_cli.py::test_main_sets_assume_yes](tests/test_cli.py#L9-L30) manually saves/restores `os.environ["ARCHIVER_ASSUME_YES"]` instead of using `monkeypatch.setenv()`. This pattern is fragile — if the test raises before the restoration `finally` block, environment state leaks:

```python
previous_env = os.environ.pop("ARCHIVER_ASSUME_YES", None)
# ...
if previous_env is None:
    os.environ.pop("ARCHIVER_ASSUME_YES", None)
else:
    os.environ["ARCHIVER_ASSUME_YES"] = previous_env
```

This should use `monkeypatch.setenv` / `monkeypatch.delenv` instead.

---

## 5. Fixture Design

### Current State

The test suite uses minimal shared fixtures — most setup is inline within test functions. This is a conscious trade-off: high locality (easy to read each test in isolation) versus some duplication.

**Existing fixtures:**
- `restore_env` (autouse, `test_bootstrap.py`) — clears `VIRTUAL_ENV`
- Standard pytest fixtures: `tmp_path`, `monkeypatch`, `capsys`
- No `conftest.py` file exists

### Recommendations

**Missing `conftest.py`.** The testing skill recommends shared fixtures for:
1. `gallery_dir` — tmp_path with images/thumbs subdirectory structure
2. `sample_items` — realistic `GalleryItem` list
3. `mock_session` — pre-configured mock HTTP session

Currently, each test file recreates these patterns independently. A `conftest.py` would reduce the ~15 instances of directory-setup boilerplate.

**Helper duplication to centralize:**

| Helper | Files Using It | Recommendation |
|--------|---------------|----------------|
| `_sample_png()` / `PNG_BYTES` | 3 files | → `conftest.py` fixture |
| `write_metadata()` / `_write_metadata()` | 2 files (different names!) | → `conftest.py` fixture |
| `always_yes()` | 1 file (but pattern repeated elsewhere) | → `conftest.py` fixture |

---

## 6. Missing Tests (Prioritized)

### High Priority

1. **Corrupt/malformed metadata JSON.** `load_gallery_items` calls `json.load()` but no test verifies behavior with truncated JSON, non-list JSON root, or non-dict items within the list. The function has a `isinstance(raw, Mapping)` guard ([metadata.py line 198](src/chatgpt_library_archiver/metadata.py#L198)) that silently skips non-mapping items — this is untested behavior.

2. **HTTP streaming exception during write.** [http_client.py lines 259–263](src/chatgpt_library_archiver/http_client.py#L259-L263) handle the case where an exception occurs during `iter_content` — the partial file is deleted. No test covers this.

3. **Empty response body rejection.** [http_client.py lines 268–270](src/chatgpt_library_archiver/http_client.py#L268-L270) — when `allow_empty=False` (default) and zero bytes are received. No test for this path.

4. **`_prepare_for_format` non-PNG/JPEG branches.** [thumbnails.py lines 128–140](src/chatgpt_library_archiver/thumbnails.py#L128-L140) — WebP, GIF, BMP format-specific preparation logic is entirely untested.

5. **Thumbnail creation failure handling.** [thumbnails.py lines 181–184](src/chatgpt_library_archiver/thumbnails.py#L181-L184) — `FileNotFoundError`, `UnidentifiedImageError`, and `OSError` are caught and re-raised as `RuntimeError`. No test covers this.

### Medium Priority

6. **Unicode in filenames.** No test imports or downloads an image with non-ASCII characters in the filename. The `_slugify` function in [importer.py](src/chatgpt_library_archiver/importer.py#L57-L62) handles Unicode normalization, but it's untested.

7. **`get_json` with `expected_content_types`.** [http_client.py lines 157–161](src/chatgpt_library_archiver/http_client.py#L157-L161) — the `expected_content_types` parameter is untested.

8. **`HttpError.context` property.** The structured error details property ([http_client.py lines 44–47](src/chatgpt_library_archiver/http_client.py#L44-L47)) is never directly asserted in tests.

9. **`GalleryItem.from_dict` with missing required fields.** No test verifies behavior when `id` or `filename` is missing from the input dict.

10. **`_coerce_optional_int` / `_coerce_optional_str` edge cases.** Float-to-int coercion and whitespace-only string handling.

### Low Priority

11. **`prompt_yes_no` invalid input loop.** [utils.py line 47](src/chatgpt_library_archiver/utils.py#L47) — the `while True` loop that re-prompts on invalid input (not "y", "n", or empty).

12. **`gallery.py` `__main__` block.** Standard `if __name__ == "__main__"` pattern — not worth testing.

13. **Thread safety of `HttpClient._get_session`.** `_get_session` uses `threading.local` — no concurrent test exercises this.

---

## 7. Integration & End-to-End Tests

### What Exists

**Strong E2E test:** [test_end_to_end.py::test_incremental_download_and_gallery](tests/test_end_to_end.py#L17-L102) exercises the full download → metadata update → thumbnail generation → tagging → gallery generation flow. It mocks HTTP and auth but uses real filesystem, metadata, and Pillow operations.

**CLI integration tests:** [test_cli.py](tests/test_cli.py) covers all subcommands (`gallery`, `tag`, `download`, `import`, `extract-auth`) at the argument-parsing and dispatch level.

**Real wheel build test:** [test_console_script_help_via_built_wheel](tests/test_cli.py#L180-L227) builds an actual wheel, installs it in a fresh venv, and runs `chatgpt-archiver --help`. This is a true end-to-end packaging test.

**Importer E2E:** [test_importer.py](tests/test_importer.py) performs real file moves/copies, thumbnail generation, and metadata updates using actual Pillow operations.

### Gaps

1. **No error recovery E2E test.** No test exercises the download flow when some images fail and others succeed, verifying that partial results are saved correctly.

2. **No auth refresh E2E test.** The incremental_downloader has auth-refresh logic for 401/403 responses — no integration test covers this path.

3. **No gallery-only regeneration E2E.** While `test_gallery_subcommand` mocks the gallery generator, no test verifies the real gallery generation → HTML output → metadata sorting pipeline from scratch.

---

## 8. Test Maintainability

### Naming Convention Adherence

The skill prescribes `test_<function>_<scenario>_<expected>`. Adherence varies:

| Example | Follows Convention? |
|---------|-------------------|
| `test_decrypt_cookie_value_roundtrip` | Partial — missing expected |
| `test_get_json_invalid_content_type` | Partial — missing expected |
| `test_extract_cookies_missing_db_raises` | **Yes** |
| `test_download_browser_flag_edge` | Partial — missing expected |
| `test_gallery_subcommand` | **No** — too generic |
| `test_import_single_file_move` | Partial — describes scenario, not expected result |
| `test_incremental_download_and_gallery` | **No** — describes what, not expectation |

~30% of tests follow the full convention. Most describe the scenario but omit the expected outcome from the name.

### Docstrings

Good docstring coverage in `test_browser_extract.py` (every test has one). Sparse elsewhere — `test_gallery.py`, `test_metadata.py`, `test_http_client.py`, `test_importer.py`, and `test_thumbnails.py` have few or no docstrings.

### Anti-Patterns Detected

1. **Module reimport pattern.** Several CLI tests use `importlib.import_module("chatgpt_library_archiver.__main__")` — this reimports the module on each call, which is wasteful and confusing:

   ```python
   cli = importlib.import_module("chatgpt_library_archiver.__main__")
   cli.main()
   ```

   A direct `from chatgpt_library_archiver.__main__ import main` at the test module top would be cleaner.

2. **Magic numbers without context.** Some tests define expected values as module-level constants that obscure intent:

   ```python
   EXPECTED_IMPORTED_COUNT = 2
   EXPECTED_METADATA_COUNT = 3
   TAGGING_WORKERS = 2
   EXPECTED_TOKEN_OCCURRENCES = 2
   ```

   These constants separate the expected value from its semantic meaning. Inline values with comments would be more readable.

3. **Overly long test functions.** `test_incremental_download_and_gallery` is ~90 lines including setup. Breaking the mock setup into fixtures would improve readability.

---

## 9. Performance

### Timing Breakdown

| Test | Duration | Category |
|------|----------|----------|
| `test_console_script_help_via_built_wheel` | **18.37s** | Builds wheel + creates venv |
| `test_regenerate_thumbnails_parallel_with_spawn_queue` | 0.29s | Real multiprocessing spawn |
| Gallery JS tests (5 tests) | 0.12–0.22s each | Node.js subprocess |
| Everything else | <0.06s | Fast |

### Observations

- **78% of runtime is one test.** `test_console_script_help_via_built_wheel` accounts for 18.37s of 23.5s total. This test is valuable (verifies packaging) but should be marked with a custom marker (e.g., `@pytest.mark.slow`) and excluded from default runs.

- **Gallery JS tests add ~0.8s.** Five tests each spawn a Node.js subprocess. These are good tests but could be consolidated—currently each test extracts the JS from the template independently.

- **The spawn-context test (0.29s)** is the only test that uses real multiprocessing. It's appropriate for its purpose but slightly slow.

- **Excluding the wheel test,** the suite runs in ~5s — well within acceptable limits for the 136-test suite.

### Recommendation

```python
# Add to conftest.py:
import pytest

def pytest_configure(config):
    config.addinivalue_line("markers", "slow: marks tests as slow (deselect with '-m not slow')")

# Then mark the wheel test:
@pytest.mark.slow
@pytest.mark.skipif(...)
def test_console_script_help_via_built_wheel(tmp_path):
    ...
```

---

## 10. Alignment with Testing Skill

| Skill Recommendation | Actual Implementation | Status |
|---------------------|-----------------------|--------|
| `test_<fn>_<scenario>_<expected>` naming | ~30% compliance | **Partial** |
| `gallery_dir` shared fixture | Not implemented | **Missing** |
| `sample_items` shared fixture | Not implemented | **Missing** |
| `mock_session` shared fixture | Not implemented | **Missing** |
| `MagicMock(spec=Session)` for HTTP | Custom `FakeSession` class (better) | **Exceeded** |
| `MagicMock(spec=OpenAI)` for AI | `SimpleNamespace` mocks | **Different approach** |
| `tmp_path` for filesystem isolation | Consistently used | **Compliant** |
| 85% project minimum | 91% line / 86% branch | **Passing** |
| Empty gallery edge case | Tested in `test_gallery.py` | **Compliant** |
| Corrupt metadata JSON | Not tested | **Missing** |
| Unicode in filenames | Not tested | **Missing** |
| Network timeouts | Not tested | **Missing** |
| Rate limit responses | Tested in `test_ai.py` | **Compliant** |
| `disable=True` for tqdm | Used in `test_status.py` | **Compliant** |
| `monkeypatch.setattr("builtins.input", ...)` | Used in `test_utils.py` | **Compliant** |

---

## Prioritized Recommendations

### P0 — Quick Wins (Low effort, high value)

1. **Create `tests/conftest.py`** with shared `gallery_dir`, `sample_png_bytes`, and `write_metadata` fixtures to eliminate duplication across 5+ test files.

2. **Mark `test_console_script_help_via_built_wheel` as `@pytest.mark.slow`** and update `addopts` to skip by default: `addopts = "-q -m 'not slow'"`. Run in CI only.

3. **Fix the manual env save/restore** in [test_cli.py::test_main_sets_assume_yes](tests/test_cli.py#L10) — replace with `monkeypatch.setenv`/`monkeypatch.delenv`.

### P1 — Coverage Gaps (Medium effort, high value)

4. **Add corrupt metadata tests** — truncated JSON, non-list root, items missing `id` or `filename`. The silent-skip behavior in `load_gallery_items` needs explicit verification.

5. **Add HTTP streaming failure test** — mock `iter_content` to raise mid-stream and verify partial file cleanup.

6. **Add empty response body test** (without `allow_empty=True`) for `stream_download`.

7. **Add thumbnail format-specific tests** — test WebP, GIF, BMP input images through `create_thumbnails` to cover `_prepare_for_format` branches.

8. **Add thumbnail creation failure test** — `FileNotFoundError` or corrupt image input to `create_thumbnails`.

### P2 — Robustness (Medium effort, medium value)

9. **Test `_slugify` and `_unique_filename`** in the importer with Unicode input, empty input, and collision scenarios.

10. **Test `ensure_auth_config` re-entry path** — where the user says "yes" to re-entering credentials after partial config detection.

11. **Add `HttpError.context` property assertions** to existing error-path tests.

12. **Add integration test for partial download failure** — some images fail while others succeed, verify saved state.

### P3 — Quality of Life (Lower priority)

13. **Improve test naming** — audit test names against `test_<fn>_<scenario>_<expected>` convention.

14. **Add docstrings** to tests in `test_gallery.py`, `test_metadata.py`, `test_http_client.py`, `test_importer.py`, `test_thumbnails.py`.

15. **Consolidate gallery JS test extraction** — the `_extract_filter_fn()`, `_extract_viewer_script()`, `_extract_thumb_handler()` helpers each independently parse the full HTML template. A shared fixture could parse once.

16. **Replace `importlib.import_module` pattern** in CLI tests with direct imports.

17. **Consider adding branch coverage enforcement** — change `make test` from `--cov-fail-under=85` (line-only) to also enforce branch coverage, since branch coverage is currently 86% (close to the threshold).
