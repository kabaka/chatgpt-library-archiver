---
name: archiver-testing-strategy
description: Pytest testing patterns for chatgpt-library-archiver — fixture design, HTTP and OpenAI mocking, filesystem isolation, metadata generators, and coverage strategy for the image archiver test suite
---

# Testing Strategy for ChatGPT Library Archiver

Pytest-based testing patterns for the archiver's test suite. Covers fixture design, mocking external dependencies (HTTP, OpenAI, Pillow), filesystem isolation, and coverage strategy.

**When to use this skill:**
- Designing tests for new features
- Setting up pytest fixtures
- Mocking HTTP requests, OpenAI API, or Pillow
- Improving test coverage
- Debugging flaky tests

## Test Organization

```
tests/
├── conftest.py              # Shared fixtures (gallery_dir, sample_png_bytes, write_metadata)
├── test_ai.py               # OpenAI client, vision API mocking, retry logic
├── test_bootstrap.py        # Bootstrap/venv creation
├── test_browser_extract.py  # Browser cookie extraction, AES-CBC crypto round-trips
├── test_cli.py              # CLI argument parsing, command dispatch
├── test_end_to_end.py       # Integration tests across modules
├── test_gallery.py          # Gallery generation, metadata sorting
├── test_http_client.py      # HTTP client, retry logic, downloads
├── test_importer.py         # Image import workflow
├── test_metadata.py         # Metadata parsing, normalization
├── test_pre_commit_hook.py  # Pre-commit hook behavior
├── test_status.py           # Status reporter, progress bars
├── test_tagger.py           # AI tagging workflow
├── test_thumbnails.py       # Thumbnail generation pipeline
└── test_utils.py            # Auth config, prompts, utilities
```

## Key Fixture Patterns

### Shared Fixtures (conftest.py)

The test suite shares common fixtures in `tests/conftest.py`:

```python
# Minimal valid PNG image bytes (reusable across tests)
@pytest.fixture
def sample_png_bytes() -> bytes:
    """Minimal valid 8x8 PNG image bytes."""
    return SAMPLE_PNG  # Module-level constant from _make_sample_png()

@pytest.fixture
def gallery_dir(tmp_path: Path) -> Path:
    """Isolated gallery directory with images/ and thumbs/ subdirectories."""
    gallery = tmp_path / "gallery"
    gallery.mkdir()
    (gallery / "images").mkdir()
    (gallery / "thumbs" / "small").mkdir(parents=True)
    (gallery / "thumbs" / "medium").mkdir(parents=True)
    (gallery / "thumbs" / "large").mkdir(parents=True)
    return gallery

@pytest.fixture
def write_metadata():
    """Return a callable that writes metadata.json under a gallery root.

    Usage:
        gallery = write_metadata(tmp_path / "gallery", items)
        gallery = write_metadata(tmp_path / "gallery", items, create_images=True)
    """
    def _write(root, items, *, create_images=False) -> Path:
        (root / "images").mkdir(parents=True, exist_ok=True)
        with open(root / "metadata.json", "w") as f:
            json.dump(items, f)
        if create_images:
            for item in items:
                (root / "images" / str(item["filename"])).write_text("img")
        return root
    return _write
```

### Metadata Fixtures

```python
@pytest.fixture
def sample_items() -> list[GalleryItem]:
    """Generate realistic GalleryItem list for testing."""
    return [
        GalleryItem(id="img-001", filename="sunset.png", created_at=1700000000.0,
                     title="Sunset", tags=["nature", "sunset"]),
        GalleryItem(id="img-002", filename="portrait.jpg", created_at=1700001000.0,
                     title=None, tags=[]),
    ]
```

### HTTP Mocking

```python
@pytest.fixture
def mock_session(monkeypatch):
    """Mock requests.Session for HTTP client tests."""
    session = MagicMock(spec=Session)
    response = MagicMock(spec=Response)
    response.status_code = 200
    response.headers = {"Content-Type": "image/png"}
    response.iter_content = MagicMock(return_value=[b"fake-image-data"])
    session.get.return_value = response
    return session
```

### OpenAI Mocking

The OpenAI SDK uses dynamic API composition, so `MagicMock(spec=OpenAI)` breaks on attribute access (e.g. `client.responses`). Use `SimpleNamespace` to build lightweight fakes instead:

```python
from types import SimpleNamespace

class DummyResponses:
    """Fake responses endpoint for testing call_image_endpoint."""
    def __init__(self):
        self.calls = 0

    def create(self, **_kwargs):
        self.calls += 1
        return SimpleNamespace(
            output_text="nature, sunset, landscape",
            usage=SimpleNamespace(
                total_tokens=150, prompt_tokens=100, completion_tokens=50,
            ),
        )

client = SimpleNamespace(responses=DummyResponses())
```

For project-level functions (e.g. `generate_tags`, `ensure_tagging_config`), use `Mock(spec=...)` to catch signature drift:

```python
from unittest.mock import Mock
from chatgpt_library_archiver.ai import AIRequestTelemetry, TaggingConfig

telemetry = AIRequestTelemetry("tag", "file", 0.1, 2, 1, 1, 0)
mock_gen = Mock(spec=tagger.generate_tags, return_value=(["x", "y"], telemetry))
monkeypatch.setattr(tagger, "generate_tags", mock_gen)

mock_config = Mock(
    spec=tagger.ensure_tagging_config,
    return_value=TaggingConfig(api_key="k", model="m", prompt="p"),
)
monkeypatch.setattr(tagger, "ensure_tagging_config", mock_config)
```

## Mocking Strategy

| Dependency | Mock Approach | Why |
|------------|--------------|-----|
| `requests.Session` | Custom `FakeSession` / `FakeResponse` classes | Realistic interface with explicit status codes, headers, streaming |
| `OpenAI` client | `SimpleNamespace(responses=DummyResponses())` | SDK uses dynamic API composition; `MagicMock(spec=OpenAI)` breaks |
| Project functions | `Mock(spec=tagger.generate_tags, ...)` | Catches signature drift via spec validation |
| `PIL.Image.open` | Small real images via Pillow | Fast, deterministic, tests actual image processing |
| Filesystem | `tmp_path` fixture | Isolated, auto-cleaned |
| `tqdm` | `disable=True` or mock | No progress bar noise in test output |
| `input()` / `getpass()` | `monkeypatch.setattr("builtins.input", ...)` | No interactive prompts |
| `time.sleep` / `time.perf_counter` | `monkeypatch.setattr(ai.time, "sleep", ...)` | Deterministic timing in retry tests |

## Coverage Strategy

**85% project minimum** (enforced by `make test`).

**Currently omitted from coverage** (complex I/O-heavy modules):
- `bootstrap.py`, `browser_extract.py`, `cli/*`, `importer.py`, `incremental_downloader.py`, `tagger.py`

**Prioritize coverage for:**
- `metadata.py` — Data integrity, parsing edge cases
- `http_client.py` — Retry logic, error handling, download validation
- `gallery.py` — Sorting, file generation
- `thumbnails.py` — Image pipeline, concurrent processing
- `ai.py` — Client caching, config resolution, API call patterns
- `status.py` — Reporter lifecycle, error collection
- `utils.py` — Auth parsing, prompt logic

## Test Naming Convention

```python
def test_<function>_<scenario>_<expected>():
    """Docstring describing the test scenario."""
```

Examples:
- `test_load_gallery_items_with_empty_metadata_returns_empty_list`
- `test_download_file_with_404_raises_http_error`
- `test_normalize_created_at_with_iso_string_returns_float`

## Common Edge Cases to Test

- Empty gallery (no images, no metadata)
- Corrupt or truncated metadata JSON
- Missing required fields in metadata entries
- Images with no EXIF data
- Very large image files (memory limits)
- Network timeouts and HTTP errors (4xx, 5xx)
- Rate limit responses from OpenAI
- Unicode in filenames and titles
- Concurrent access to shared metadata file

## Running Tests

```bash
make test          # Full suite with coverage
pytest tests/test_metadata.py              # Single file
pytest tests/test_metadata.py::test_name   # Single test
pytest -x          # Stop on first failure
pytest -v          # Verbose output
pytest --cov-report=html                   # HTML coverage report
```
