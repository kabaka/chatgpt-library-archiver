from chatgpt_library_archiver.status import StatusReporter


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
