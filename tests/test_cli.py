from __future__ import annotations

from click.exceptions import Exit

from scholar_vault.cli import _with_progress
from scholar_vault.models import MatchReviewAbort


def test_interactive_progress_uses_plain_lines(capsys) -> None:
    def action(report):
        report("Reading export", None, None)
        report("Matching result", 1, 2)
        return "done"

    result = _with_progress("Importing Scholar Labs run", action, interactive=True)

    captured = capsys.readouterr().out
    assert result == "done"
    assert "Importing Scholar Labs run" in captured
    assert "Reading export" in captured
    assert "[1/2] Matching result" in captured


def test_interactive_progress_abort_exits_without_followup(capsys) -> None:
    def action(report):
        report("Before abort", None, None)
        raise MatchReviewAbort("Import aborted from match review.")

    try:
        _with_progress("Importing Scholar Labs run", action, interactive=True)
    except Exit as exc:
        assert exc.exit_code == 130
    else:
        raise AssertionError("Abort should stop the command.")

    captured = capsys.readouterr().out
    assert "Before abort" in captured
    assert "Import aborted from match review." in captured


def test_progress_reports_to_gui_progress() -> None:
    calls = []

    class FakeProgress:
        def __call__(self, message, current=None, total=None):
            calls.append((message, current, total))

    def action(report):
        report("Enriching abstracts", 1, 3)
        return "done"

    result = _with_progress(
        "Importing Scholar Labs run",
        action,
        gui_progress=FakeProgress(),
    )

    assert result == "done"
    assert calls == [("Enriching abstracts", 1, 3)]
