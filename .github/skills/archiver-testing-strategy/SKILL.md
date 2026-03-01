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
├── test_ai.py              # OpenAI client, vision API mocking
├── test_bootstrap.py        # Bootstrap/venv creation
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

### Temporary Gallery Directory

```python
@pytest.fixture
def gallery_dir(tmp_path: Path) -> Path:
    """Provide an isolated gallery directory with subdirectories."""
    gallery = tmp_path / "gallery"
    gallery.mkdir()
    (gallery / "images").mkdir()
    (gallery / "thumbs" / "small").mkdir(parents=True)
    (gallery / "thumbs" / "medium").mkdir(parents=True)
    (gallery / "thumbs" / "large").mkdir(parents=True)
    return gallery
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

```python
@pytest.fixture
def mock_openai(monkeypatch):
    """Mock OpenAI client for AI/tagging tests."""
    client = MagicMock(spec=OpenAI)
    completion = MagicMock()
    completion.choices = [MagicMock(message=MagicMock(content="nature, sunset, landscape"))]
    completion.usage = MagicMock(total_tokens=150, prompt_tokens=100, completion_tokens=50)
    client.chat.completions.create.return_value = completion
    return client
```

## Mocking Strategy

| Dependency | Mock Approach | Why |
|------------|--------------|-----|
| `requests.Session` | `MagicMock(spec=Session)` | No real HTTP calls in tests |
| `OpenAI` client | `MagicMock(spec=OpenAI)` | No real API calls, no cost |
| `PIL.Image.open` | `MagicMock` or small real images | Fast, deterministic |
| Filesystem | `tmp_path` fixture | Isolated, auto-cleaned |
| `tqdm` | `disable=True` or mock | No progress bar noise in test output |
| `input()` | `monkeypatch.setattr("builtins.input", ...)` | No interactive prompts |

## Coverage Strategy

**85% project minimum** (enforced by `make test`).

**Currently omitted from coverage** (complex I/O-heavy modules):
- `bootstrap.py`, `cli/*`, `importer.py`, `incremental_downloader.py`, `tagger.py`

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
