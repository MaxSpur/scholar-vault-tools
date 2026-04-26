from __future__ import annotations

from click.exceptions import Exit
from typer.testing import CliRunner

from scholar_vault.cli import (
    _enrichment_progress_reporter,
    _import_summary_lines,
    _with_progress,
    app,
)
from scholar_vault.importer import initialize_vault
from scholar_vault.models import ImportCanceled, MatchReviewAbort


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
    assert calls == [("Enriching abstracts", 1, 3), ("Complete", None, None)]


def test_enrichment_progress_reporter_includes_stage() -> None:
    calls = []

    class Card:
        citekey = "example2024paper"
        slug = "example-paper"
        title = "Example Paper"
        abstract_status = "unresolved"
        abstract_source = None
        abstract_lock = False
        pdf = "pdfs/example.pdf"
        citation_status = "missing"
        citation_source = None
        enrichment_missing = []
        doi = None

    progress = _enrichment_progress_reporter(
        lambda message, current, total: calls.append((message, current, total)),
        abstracts=True,
    )
    progress(Card(), 2, 5, "skipped")

    assert calls == [
        (
            "Enriching abstracts [skipped]: example2024paper // Example Paper // "
            "state=unresolved; pdf=yes",
            2,
            5,
        )
    ]


def test_import_canceled_exits_cleanly(capsys) -> None:
    def action(_report):
        raise ImportCanceled("Run example already exists. Import canceled.")

    try:
        _with_progress("Importing Scholar Labs run", action, interactive=True)
    except Exit as exc:
        assert exc.exit_code == 0
    else:
        raise AssertionError("Import cancellation should stop the command.")

    captured = capsys.readouterr().out
    assert "Run example already exists. Import canceled." in captured


def test_import_summary_explains_reused_prior_matches() -> None:
    lines = _import_summary_lines(
        {
            "run": "2026-04-23_example",
            "selected": 3,
            "unselected_results": 2,
            "unmatched": 4,
            "archived": 0,
            "decision_summary": {
                "export_results": 5,
                "staged_pdfs_scanned": 4,
                "prior_selected_reused": 3,
                "existing_cards_linked": 0,
                "new_staged_pdf_matches": 0,
                "review_prompts": 0,
                "review_accepted": 0,
                "review_rejected": 0,
            },
            "citation_enrichment": {"processed": 3, "changed": 0},
            "abstract_enrichment": {"processed": 3, "changed": 0},
        }
    )

    output = "\n".join(lines)

    assert "3 reused from previous run manifest" in output
    assert "0 newly accepted staged PDFs" in output
    assert "No match-review prompts appeared" in output
    assert "citations checked 3 cards (0 updated, 3 unchanged)" in output
    assert "abstracts checked 3 cards (0 updated, 3 unchanged)" in output


def test_import_finish_keeps_progress_until_followup(monkeypatch) -> None:
    from scholar_vault import cli

    events: list[str] = []

    class Progress:
        def close(self) -> None:
            events.append("close-progress")

    summary = {"abstract_details": [{"category": "unresolved"}]}
    monkeypatch.setattr(cli, "_print_run_summary", lambda _summary: events.append("summary"))
    monkeypatch.setattr(
        cli,
        "_show_import_summary_ui",
        lambda _summary, *, ui, followup_pending: events.append(
            f"report:{ui}:{followup_pending}"
        ),
    )
    monkeypatch.setattr(
        cli,
        "_show_import_enrichment_followup",
        lambda _summary, *, ui: events.append(f"followup:{ui}"),
    )

    cli._finish_import_workflow(summary, ui=True, progress_ui=Progress())

    assert events == ["summary", "report:True:True", "followup:True", "close-progress"]


def test_rebuild_command_prints_summary(tmp_path) -> None:
    vault = tmp_path / "vault"
    initialize_vault(vault)

    result = CliRunner().invoke(app, ["rebuild", "--vault", str(vault)])

    assert result.exit_code == 0
    assert "Rebuilt derived files" in result.output
    assert "- Papers: 0 total" in result.output
    assert "- Runs: 0 run notes refreshed" in result.output
    assert "- Derived outputs:" in result.output
