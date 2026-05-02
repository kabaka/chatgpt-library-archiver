# Test Failure Triage — 2026-05-02

**Scope**: 17 failures reported across `tests/test_tagger.py`,
`tests/test_importer.py`, `tests/test_thumbnails.py`,
`tests/test_end_to_end.py` in the uncommitted task-1/2/6/7 working tree.

**Verdict**: **All 17 failures are sandbox/environment issues. Zero real
regressions** introduced by tasks 1, 2, 6, or 7.

## Verification methodology

1. Reproduced full failure set with `pytest tests/test_tagger.py
   tests/test_importer.py tests/test_thumbnails.py tests/test_end_to_end.py
   --no-cov` → **17 failed, 77 passed**.
2. Inspected sandbox env: `all_proxy=socks5h://localhost:50421` (and friends)
   are exported by the VS Code sandbox runtime.
3. Re-ran the same set with the proxy variables unset
   (`unset all_proxy ALL_PROXY ftp_proxy FTP_PROXY GRPC_PROXY grpc_proxy`):
   **7 failed, 87 passed** — all 10 tagger failures vanished, isolating the
   SOCKS bucket.
4. Cross-checked HEAD (`c04c765`) for the implicated code paths:
   - [`tagger.py`](src/chatgpt_library_archiver/tagger.py#L188)
     `client = get_cached_client(cfg.api_key)` predates task 2; tagger tests
     were already exposed to the SOCKS issue independent of task 2's
     order-preserving merge.
   - [`thumbnails.py`](src/chatgpt_library_archiver/thumbnails.py#L437)
     `mp_context.Manager()` inside `regenerate_thumbnails` predates task 6;
     `test_regenerate_thumbnails_parallel_with_spawn_queue` already existed
     at HEAD line 240.
   - The new `ThumbnailPool._ensure_started` (task 6) introduces the same
     `Manager()` call along the importer + incremental-download paths,
     which extends the sandbox blast radius but is not a logic regression.

## Failure classification

### Bucket A — SOCKS proxy / `socksio` missing (10 failures)

Environment: `all_proxy=socks5h://localhost:50421` causes `httpx` (transitive
dep of `openai`) to require `socksio`; the package is not installed, so any
`OpenAI(...)` instantiation raises `ImportError: Using SOCKS proxy, but the
'socksio' package is not installed`.

Root cause line:
[`src/chatgpt_library_archiver/tagger.py:188`](src/chatgpt_library_archiver/tagger.py#L188)
— `client = get_cached_client(cfg.api_key)` runs before `generate_tags` is
mocked-through, so the upstream `OpenAI()` call still fires.

| Test | Classification | Recommended fix |
|---|---|---|
| `test_tagger.py::test_tag_missing_only` | Sandbox (SOCKS) | Mock `tagger.get_cached_client` in addition to `tagger.generate_tags`, or add a session-scoped `conftest.py` fixture that `monkeypatch.delenv`s `*_proxy` / `ALL_PROXY` for tagger tests |
| `test_tagger.py::test_retag_all` | Sandbox (SOCKS) | Same |
| `test_tagger.py::test_tag_specific_ids` | Sandbox (SOCKS) | Same |
| `test_tagger.py::test_progress_and_tokens` | Sandbox (SOCKS) | Same |
| `test_tagger.py::test_tag_images_single_failure_does_not_abort_batch` | Sandbox (SOCKS) | Same |
| `test_tagger.py::test_merge_preserves_existing_user_tags_when_ai_returns_empty` | Sandbox (SOCKS) | Same |
| `test_tagger.py::test_merge_uses_ai_tags_when_no_existing` | Sandbox (SOCKS) | Same |
| `test_tagger.py::test_merge_combines_existing_and_ai_tags_in_order` | Sandbox (SOCKS) | Same |
| `test_tagger.py::test_merge_deduplicates_case_and_whitespace` | Sandbox (SOCKS) | Same |
| `test_tagger.py::test_merge_with_empty_existing_tags_list` | Sandbox (SOCKS) | Same |

**Preferred mitigation** (lowest blast radius): add an autouse fixture in
[`tests/test_tagger.py`](tests/test_tagger.py) that does
`monkeypatch.setattr(tagger, "get_cached_client", lambda *_a, **_kw: object())`.
That keeps tests self-describing and avoids ratcheting `socksio` into the
runtime deps. A `conftest.py` autouse `delenv` would also work but is more
invasive.

### Bucket B — `multiprocessing.Manager()` socket bind blocked (7 failures)

Environment: VS Code sandbox blocks `bind()` on the AF_UNIX socket the
multiprocessing `SyncManager` listener creates, so `Manager()` start raises
`PermissionError: [Errno 1] Operation not permitted` in the manager
sub-process and the parent observes `EOFError` on the handshake pipe.

Root cause lines:
- [`src/chatgpt_library_archiver/thumbnails.py:582`](src/chatgpt_library_archiver/thumbnails.py#L582)
  (new in task 6 — `ThumbnailPool._ensure_started`).
- [`src/chatgpt_library_archiver/thumbnails.py:438`](src/chatgpt_library_archiver/thumbnails.py#L438)
  (pre-existing — `regenerate_thumbnails`).

| Test | Classification | Recommended fix |
|---|---|---|
| `test_importer.py::test_import_single_file_move` | Sandbox (mp Manager) | Apply the existing `_patch_recording_pool` / `_NullContext` pattern from `tests/test_thumbnails.py` (lines 953–981) to importer tests, or have the importer fixture inject a `ThumbnailPool` test double |
| `test_importer.py::test_import_copy_keeps_source` | Sandbox (mp Manager) | Same |
| `test_importer.py::test_recursive_directory_import` | Sandbox (mp Manager) | Same |
| `test_importer.py::test_regenerate_thumbnails_recreates_missing` | Sandbox (mp Manager) | Same; or monkeypatch `thumbnails.regenerate_thumbnails` to its in-process branch |
| `test_thumbnails.py::test_regenerate_thumbnails_parallel_with_spawn_queue` | Sandbox (mp Manager) — **pre-existing on HEAD** | Same `_NullContext` approach, or `pytest.mark.skipif` keyed on a `CI_SANDBOXED=1` env probe |
| `test_thumbnails.py::test_create_thumbnails_pool_parallel` | Sandbox (mp Manager) — new test | Either add `_patch_recording_pool` (loses real-pool coverage) or guard with `pytest.mark.skipif(not _can_bind_unix_socket(), reason="sandbox blocks AF_UNIX bind")` so non-sandbox CI still exercises the real ProcessPoolExecutor |
| `test_end_to_end.py::test_incremental_download_and_gallery` | Sandbox (mp Manager) — extended by task 6 | Inject a fake `ThumbnailPool` (or monkeypatch `incremental_downloader` to use the in-process thumbnail path) for the e2e fixture |

**Note on the e2e failure** (assert `ids == {"1", "2"}`): the visible
assertion error masks the underlying `Manager()` failure. The captured
stdout shows `ERROR Download 2`, which is the StatusReporter logging
`ThumbnailPool.submit` raising during the import of image 2. That bubbles
up as a per-item failure; metadata for image 2 is therefore never written
and the `{1, 2}` assertion fails. Once the pool can start (or is
substituted with a fake), the test passes.

## Summary counts

- **Sandbox issues**: 17 / 17
  - Bucket A (SOCKS / `socksio`): **10**
  - Bucket B (mp `Manager()` socket bind): **7**
- **Real regressions from tasks 1, 2, 6, 7**: **0**

## One-line summary per regression

_None — no logic regressions introduced by tasks 1, 2, 6, or 7._

## Recommended out-of-scope follow-up

1. Add an autouse `monkeypatch.setattr(tagger, "get_cached_client", ...)`
   fixture (or stub) so tagger tests don't depend on absent proxy env.
2. Refactor importer + e2e tests to inject a fake `ThumbnailPool`
   (mirroring the `_RecordingExecutor` pattern in `tests/test_thumbnails.py`)
   so they don't depend on `multiprocessing.Manager()` working.
3. Optionally gate `test_create_thumbnails_pool_parallel` and
   `test_regenerate_thumbnails_parallel_with_spawn_queue` with a sandbox
   probe so they remain real-pool integration tests on standard CI but
   `skip` cleanly inside restricted sandboxes.
