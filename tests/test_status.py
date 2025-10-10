from types import SimpleNamespace

from chatgpt_library_archiver.status import (
    StatusError,
    StatusReporter,
    format_status,
)


class DummyTqdm:
    def __init__(self) -> None:
        self._last_kwargs: dict[str, object] | None = None
        self.bar: SimpleNamespace | None = None
        self._writes: list[str] = []

    def __call__(self, *args, **kwargs):
        total = kwargs.get("total")
        self._last_kwargs = dict(kwargs)

        bar = SimpleNamespace(total=total, updates=[], refreshes=0, closed=False)

        def update(amount: int = 1) -> None:
            bar.updates.append(amount)

        def refresh() -> None:
            bar.refreshes += 1

        def close() -> None:
            bar.closed = True

        bar.update = update  # type: ignore[attr-defined]
        bar.refresh = refresh  # type: ignore[attr-defined]
        bar.close = close  # type: ignore[attr-defined]

        self.bar = bar
        return bar

    def write(self, message: str, *, file=None) -> None:
        self._writes.append(message)


def test_status_reporter_records_errors(capsys):
    with StatusReporter(disable=True) as reporter:
        reporter.report_error(
            "Download",
            "123",
            reason="boom",
            context={"url": "https://example"},
        )

    captured = capsys.readouterr().out
    assert "ERROR Download 123: boom" in captured
    assert len(reporter.errors) == 1
    err = reporter.errors[0]
    assert err.action == "Download"
    assert err.detail == "123"
    assert err.reason == "boom"
    assert err.context == {"url": "https://example"}


def test_status_error_as_dict_includes_optional_fields():
    error = StatusError(
        action="Download",
        detail="img",
        reason="failed",
        context={"status": 500},
        exception=RuntimeError("boom"),
    )

    payload = error.as_dict()
    assert payload["action"] == "Download"
    assert payload["detail"] == "img"
    assert payload["reason"] == "failed"
    assert payload["context"] == {"status": 500}
    assert "RuntimeError" in payload["exception"]


def test_format_status_handles_missing_parts():
    assert format_status("Download", "item") == "Download item"
    assert format_status("", "detail") == "detail"
    assert format_status("Action", "") == "Action"


def test_status_reporter_progress_controls(monkeypatch):
    dummy = DummyTqdm()
    monkeypatch.setattr("chatgpt_library_archiver.status.tqdm", dummy)

    with StatusReporter(total=2, disable=True) as reporter:
        reporter.log("starting")
        reporter.add_total(0)
        reporter.add_total(3)
        reporter.advance(2)
        expected_total = 10
        reporter.set_total(expected_total)

    assert dummy.bar is not None
    assert dummy.bar.total == expected_total
    assert dummy.bar.updates == [2]
    assert dummy.bar.refreshes >= 1
    assert dummy.bar.closed is True
    assert dummy._writes == ["starting"]
