from __future__ import annotations

import json
import os

from click.exceptions import Exit
from typer.testing import CliRunner

from scholar_vault.cli import (
    _complete_only_modes,
    _complete_run_ids,
    _enrichment_progress_reporter,
    _fish_completion_script,
    _import_summary_lines,
    _show_enrichment_ui,
    _with_progress,
    _zsh_completion_path,
    _zsh_completion_script,
    app,
)
from scholar_vault.importer import initialize_vault
from scholar_vault.models import ImportCanceled, MatchReviewAbort
from scholar_vault.sources import write_yaml


def _write_cli_export(
    path,
    *,
    title: str | None = None,
    prompt: str = "retrieval augmented generation evaluation with grounded evidence",
):
    payload = {
        "schema_version": "0.2",
        "source": "google_scholar_labs",
        "exported_at": "2026-04-22T16:00:00+02:00",
        "prompt": prompt,
        "results": [
            {
                "rank": 1,
                "scholar_cid": "cid-001",
                "title": "Result Paper 1",
                "authors_preview": "Jane Smith",
                "year": 2024,
                "venue_preview": "Test Venue",
            }
        ],
    }
    if title is not None:
        payload["title"] = title
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


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


def test_enrichment_ui_filters_to_real_followup_issues(monkeypatch) -> None:
    from scholar_vault import gui

    shown: list[dict] = []

    def fake_show_enrichment_results(details, **_kwargs) -> None:
        shown.extend(details)

    monkeypatch.setattr(gui, "show_enrichment_results", fake_show_enrichment_results)

    result = _show_enrichment_ui(
        {
            "details": [
                {
                    "kind": "citation",
                    "category": "skipped",
                    "message": "citation verified",
                },
                {
                    "kind": "abstract",
                    "category": "unresolved",
                    "message": "no acceptable abstract found",
                },
            ]
        },
        abstracts=True,
    )

    assert result is True
    assert shown == [
        {
            "kind": "abstract",
            "category": "unresolved",
            "message": "no acceptable abstract found",
        }
    ]


def test_enrichment_ui_does_not_show_non_issue_skips(monkeypatch) -> None:
    from scholar_vault import gui

    called = False

    def fake_show_enrichment_results(*_args, **_kwargs) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(gui, "show_enrichment_results", fake_show_enrichment_results)

    result = _show_enrichment_ui(
        {
            "details": [
                {
                    "kind": "abstract",
                    "category": "skipped",
                    "message": "abstract fingerprint unchanged",
                }
            ]
        },
        abstracts=True,
    )

    assert result is False
    assert called is False


def test_enrichment_ui_mentions_keyword_followup(monkeypatch, tmp_path) -> None:
    from scholar_vault import cli

    vault = tmp_path / "vault"
    initialize_vault(vault)
    monkeypatch.setattr(cli, "_make_gui_progress", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cli, "_show_enrichment_ui", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(cli, "_keyword_followup_count", lambda *_args, **_kwargs: 11)
    monkeypatch.setattr(
        cli,
        "enrich_citations",
        lambda *_args, **_kwargs: {
            "processed": 2,
            "changed": 0,
            "skipped": 90,
            "generated": 0,
            "verified": 0,
            "ambiguous": 2,
            "unresolved": 0,
            "details": [{"kind": "citation", "category": "ambiguous"}],
        },
    )

    result = CliRunner().invoke(app, ["enrich-citations", "--vault", str(vault), "--ui"])

    assert result.exit_code == 0
    assert "Enriched citations: processed=2" in result.output
    assert "Publication keyword follow-up: 11 paper cards still missing keywords" in result.output
    assert "scholar-vault enrich --only missing-keywords --ui" in result.output


def test_enrich_command_runs_all_passes_by_default(monkeypatch, tmp_path) -> None:
    from scholar_vault import cli

    vault = tmp_path / "vault"
    initialize_vault(vault)
    received: dict[str, object] = {}

    def fake_enrich_vault(*_args, **kwargs):
        received.update(kwargs)
        return {
            "processed": 6,
            "changed": 3,
            "skipped": 2,
            "citation_enrichment": {"processed": 2, "changed": 1, "skipped": 1},
            "abstract_enrichment": {"processed": 2, "changed": 1, "skipped": 1},
            "keyword_enrichment": {"processed": 2, "changed": 1, "skipped": 0},
            "details": [],
        }

    monkeypatch.setattr(cli, "_make_gui_progress", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cli, "enrich_vault", fake_enrich_vault)

    result = CliRunner().invoke(app, ["enrich", "--vault", str(vault)])

    assert result.exit_code == 0
    assert received["only"] == "all"
    assert "Enriched vault: processed=6, changed=3, skipped=2." in result.output
    assert "Citations: processed=2, changed=1" in result.output
    assert "Abstracts: processed=2, changed=1" in result.output
    assert "Keywords: processed=2, changed=1" in result.output


def test_doctor_command_outputs_json(tmp_path) -> None:
    from scholar_vault.importer import _save_card  # noqa: PLC0415
    from scholar_vault.models import SourceCard  # noqa: PLC0415

    vault = tmp_path / "vault"
    paths = initialize_vault(vault)
    _save_card(paths, SourceCard(slug="source", citekey="source", title="Source"))

    result = CliRunner().invoke(app, ["doctor", "--vault", str(vault), "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["counts"]["paper_cards"] == 1
    assert payload["status_counts"]["enrichment_status"]["incomplete"] == 1
    assert payload["issue_counts"]["incomplete_enrichment"] == 1


def test_pdf_doctor_command_outputs_summary(tmp_path) -> None:
    vault = tmp_path / "vault"
    paths = initialize_vault(vault)
    (paths.pdfs / "orphan.pdf").write_bytes(b"%PDF-1.4 orphan\n")

    result = CliRunner().invoke(app, ["pdf-doctor", "--vault", str(vault)])

    assert result.exit_code == 0
    assert "Orphan PDFs" in result.output
    assert "pdfs/orphan.pdf" in result.output


def test_topic_map_command_dry_runs_mapping(tmp_path) -> None:
    from scholar_vault.importer import _save_card  # noqa: PLC0415
    from scholar_vault.models import SourceCard  # noqa: PLC0415

    vault = tmp_path / "vault"
    paths = initialize_vault(vault)
    _save_card(
        paths,
        SourceCard(slug="source", citekey="source", title="Source", topics=["Find"]),
    )
    mapping = tmp_path / "topics.yaml"
    mapping.write_text("Find: null\n", encoding="utf-8")

    result = CliRunner().invoke(
        app,
        ["topic-map", "--vault", str(vault), "--mapping", str(mapping)],
    )

    assert result.exit_code == 0
    assert "Dry-run topic map: 1 card(s) would change" in result.output
    assert "papers/source.md" in result.output


def test_topic_map_command_prompt_boilerplate_preset_dry_run(tmp_path) -> None:
    from scholar_vault.importer import _save_card  # noqa: PLC0415
    from scholar_vault.models import SourceCard  # noqa: PLC0415
    from scholar_vault.sources import load_source_cards  # noqa: PLC0415

    vault = tmp_path / "vault"
    paths = initialize_vault(vault)
    _save_card(
        paths,
        SourceCard(
            slug="source",
            citekey="source",
            title="Source",
            topics=["Find", "Mobility", "Peer Reviewed"],
        ),
    )

    result = CliRunner().invoke(
        app,
        ["topic-map", "--vault", str(vault), "--preset", "prompt-boilerplate", "--json"],
    )
    unchanged = load_source_cards(paths)[0]

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["applied"] is False
    assert payload["changed_cards"] == 1
    assert unchanged.topics == ["Find", "Mobility", "Peer Reviewed"]


def test_topic_map_command_prompt_boilerplate_preset_apply(tmp_path) -> None:
    from scholar_vault.importer import _save_card  # noqa: PLC0415
    from scholar_vault.models import SourceCard  # noqa: PLC0415
    from scholar_vault.sources import load_source_cards  # noqa: PLC0415

    vault = tmp_path / "vault"
    paths = initialize_vault(vault)
    _save_card(
        paths,
        SourceCard(
            slug="source",
            citekey="source",
            title="Source",
            topics=["Find", "Mobility", "Peer Reviewed"],
        ),
    )

    result = CliRunner().invoke(
        app,
        [
            "topic-map",
            "--vault",
            str(vault),
            "--preset",
            "prompt-boilerplate",
            "--apply",
            "--json",
        ],
    )
    changed = load_source_cards(paths)[0]

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["applied"] is True
    assert payload["changed_cards"] == 1
    assert changed.topics == ["Mobility"]


def test_proposal_audit_command_outputs_json(tmp_path) -> None:
    vault = tmp_path / "vault"
    paths = initialize_vault(vault)
    proposal = paths.proposals / "pepr-mobidec"
    proposal.mkdir(parents=True)
    (proposal / "outline.md").write_text("# Outline\n", encoding="utf-8")
    (proposal / "raw-idea.md").write_text(
        "# Raw Idea\n\n## Original User Notes - Verbatim\n",
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        app,
        ["proposal-audit", "--vault", str(vault), "proposals/pepr-mobidec", "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["counts"]["files"] == 2


def test_notes_missing_command_outputs_json(tmp_path) -> None:
    from scholar_vault.importer import _save_card  # noqa: PLC0415
    from scholar_vault.models import SourceCard  # noqa: PLC0415

    vault = tmp_path / "vault"
    paths = initialize_vault(vault)
    _save_card(
        paths,
        SourceCard(
            slug="source",
            citekey="source",
            title="Source",
            pdf="pdfs/source.pdf",
            pdf_status="attached",
        ),
    )

    result = CliRunner().invoke(
        app,
        ["notes-missing", "--vault", str(vault), "--heading", "PDF reading notes", "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["missing"] == 1
    assert payload["missing_cards"][0]["paper"] == "papers/source.md"


def test_maintenance_report_command_creates_report_and_task(tmp_path) -> None:
    from scholar_vault.importer import _save_card  # noqa: PLC0415
    from scholar_vault.models import SourceCard  # noqa: PLC0415

    vault = tmp_path / "vault"
    paths = initialize_vault(vault)
    (paths.pdfs / "source.pdf").write_bytes(b"%PDF-1.4 source\n")
    _save_card(
        paths,
        SourceCard(
            slug="source",
            citekey="source",
            title="Source",
            pdf="pdfs/source.pdf",
            pdf_status="attached",
            topics=["Find"],
        ),
    )

    result = CliRunner().invoke(
        app,
        ["maintenance-report", "--vault", str(vault), "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["report"] == "_indexes/maintenance-report.md"
    assert payload["task"].startswith("tasks/")
    assert payload["task"].endswith("-maintenance.md")
    assert (paths.indexes / "maintenance-report.md").exists()
    assert (paths.vault / payload["task"]).exists()
    assert payload["paper_cards_modified"] == 0
    assert payload["counts"]["reading_queue"] == 1


def test_concept_index_command_outputs_json(tmp_path) -> None:
    vault = tmp_path / "vault"
    paths = initialize_vault(vault)
    (paths.concepts / "method.md").write_text("# Method\n", encoding="utf-8")

    result = CliRunner().invoke(app, ["concept-index", "--vault", str(vault), "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["concepts"] == 1
    assert payload["index"] == "_indexes/concepts.md"


def test_project_commands_scaffold_list_link_map_and_audit(tmp_path) -> None:
    from scholar_vault.importer import _save_card  # noqa: PLC0415
    from scholar_vault.models import SourceCard  # noqa: PLC0415

    vault = tmp_path / "vault"
    paths = initialize_vault(vault)
    _save_card(
        paths,
        SourceCard(
            slug="geospatial-networks",
            citekey="Schottler2021_GeospatialNetworks",
            title="Geospatial Networks",
        ),
    )

    scaffold = CliRunner().invoke(
        app,
        ["project", "scaffold", "map-lens-deformation", "--vault", str(vault), "--json"],
    )
    linked = CliRunner().invoke(
        app,
        [
            "project",
            "link-paper",
            "map-lens-deformation",
            "Schottler2021_GeospatialNetworks",
            "--vault",
            str(vault),
            "--json",
        ],
    )
    listed = CliRunner().invoke(app, ["project", "list", "--vault", str(vault), "--json"])
    mapped = CliRunner().invoke(
        app,
        ["project", "map", "map-lens-deformation", "--vault", str(vault), "--json"],
    )
    audited = CliRunner().invoke(
        app,
        ["project", "audit", "map-lens-deformation", "--vault", str(vault), "--json"],
    )

    assert scaffold.exit_code == 0
    assert linked.exit_code == 0
    assert listed.exit_code == 0
    assert mapped.exit_code == 0
    assert audited.exit_code == 0
    assert json.loads(scaffold.output)["project"] == "projects/map-lens-deformation/index.md"
    assert json.loads(linked.output)["changed"] is True
    assert json.loads(listed.output)["projects"][0]["slug"] == "map-lens-deformation"
    assert json.loads(mapped.output)["project_map"] == (
        "projects/map-lens-deformation/project-map.md"
    )
    audit_payload = json.loads(audited.output)
    assert audit_payload["issue_counts"]["linked_papers_without_pdfs"] == 1


def test_proposal_sprint_scaffold_command_outputs_json(tmp_path) -> None:
    vault = tmp_path / "vault"
    initialize_vault(vault)

    result = CliRunner().invoke(
        app,
        [
            "proposal-sprint",
            "scaffold",
            "--vault",
            str(vault),
            "--title",
            "PEPR Mobidec",
            "pepr-mobidec",
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["proposal"] == "proposals/pepr-mobidec"
    assert "proposals/pepr-mobidec/source-matrix.md" in payload["files"]["created"]


def test_card_bibtex_command_prints_single_entry(tmp_path) -> None:
    from scholar_vault.importer import _save_card  # noqa: PLC0415
    from scholar_vault.models import SourceCard  # noqa: PLC0415

    vault = tmp_path / "vault"
    paths = initialize_vault(vault)
    _save_card(
        paths,
        SourceCard(
            slug="source",
            citekey="source",
            title="Source Paper",
            authors=["Jane Smith"],
            year=2024,
            venue="Proceedings of TestConf",
            citation_status="verified",
        ),
    )

    result = CliRunner().invoke(app, ["card-bibtex", "--vault", str(vault), "source"])

    assert result.exit_code == 0
    assert "@inproceedings{source," in result.output
    assert "booktitle = {Proceedings of TestConf}" in result.output


def test_bibtex_command_with_citekey_writes_single_entry(tmp_path) -> None:
    from scholar_vault.importer import _save_card  # noqa: PLC0415
    from scholar_vault.models import SourceCard  # noqa: PLC0415

    vault = tmp_path / "vault"
    paths = initialize_vault(vault)
    _save_card(
        paths,
        SourceCard(
            slug="source",
            citekey="source",
            title="Source Paper",
            authors=["Jane Smith"],
            year=2024,
            citation_status="verified",
        ),
    )
    output = tmp_path / "source.bib"

    result = CliRunner().invoke(
        app,
        ["bibtex", "--vault", str(vault), "--citekey", "source", "--output", str(output)],
    )

    assert result.exit_code == 0
    assert "Wrote" in result.output
    assert "@misc{source," in output.read_text(encoding="utf-8")


def test_card_bibtex_command_can_print_cite(tmp_path) -> None:
    from scholar_vault.importer import _save_card  # noqa: PLC0415
    from scholar_vault.models import SourceCard  # noqa: PLC0415

    vault = tmp_path / "vault"
    paths = initialize_vault(vault)
    _save_card(
        paths,
        SourceCard(
            slug="source",
            citekey="source",
            title="Source Paper",
            citation_status="verified",
        ),
    )

    result = CliRunner().invoke(
        app,
        ["card-bibtex", "--vault", str(vault), "--cite", "source"],
    )

    assert result.exit_code == 0
    assert result.output == "\\cite{source}\n"


def test_card_bibtex_command_can_copy_to_clipboard(tmp_path, monkeypatch) -> None:
    from scholar_vault import cli  # noqa: PLC0415
    from scholar_vault.importer import _save_card  # noqa: PLC0415
    from scholar_vault.models import SourceCard  # noqa: PLC0415

    vault = tmp_path / "vault"
    paths = initialize_vault(vault)
    _save_card(
        paths,
        SourceCard(
            slug="source",
            citekey="source",
            title="Source Paper",
            authors=["Jane Smith"],
            year=2024,
            citation_status="verified",
        ),
    )
    copied: dict[str, str] = {}

    def fake_copy(text: str) -> str:
        copied["text"] = text
        return "test-copy"

    monkeypatch.setattr(cli, "_copy_to_clipboard", fake_copy)

    result = CliRunner().invoke(
        app,
        ["card-bibtex", "--vault", str(vault), "--clipboard", "source"],
    )

    assert result.exit_code == 0
    assert "Copied BibLaTeX for source to clipboard with test-copy." in result.output
    assert copied["text"].startswith("@misc{source,")


def test_card_bibtex_command_can_omit_local_fields(tmp_path) -> None:
    from scholar_vault.importer import _save_card  # noqa: PLC0415
    from scholar_vault.models import SourceCard  # noqa: PLC0415

    vault = tmp_path / "vault"
    paths = initialize_vault(vault)
    _save_card(
        paths,
        SourceCard(
            slug="source",
            citekey="source",
            title="Source Paper",
            authors=["Jane Smith"],
            year=2024,
            pdf="pdfs/source.pdf",
            abstract="A useful abstract.",
            keywords=["Keyword"],
            citation_status="verified",
        ),
    )

    result = CliRunner().invoke(
        app,
        ["card-bibtex", "--vault", str(vault), "--no-local-fields", "source"],
    )

    assert result.exit_code == 0
    assert "abstract = " not in result.output
    assert "file = " not in result.output
    assert "keywords = " not in result.output


def test_bibtex_doctor_command_reports_json(tmp_path) -> None:
    from scholar_vault.importer import _save_card  # noqa: PLC0415
    from scholar_vault.models import SourceCard  # noqa: PLC0415

    vault = tmp_path / "vault"
    paths = initialize_vault(vault)
    _save_card(
        paths,
        SourceCard(
            slug="source",
            citekey="source",
            title="Source Paper",
            venue="Journal of Test Results",
            citation_status="missing",
        ),
    )

    result = CliRunner().invoke(app, ["biblatex-doctor", "--vault", str(vault), "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["issues"] == 1
    assert payload["rows"][0]["citekey"] == "source"
    assert "missing required author/editor for @article" in payload["rows"][0]["warnings"]


def test_reference_command_prints_apa_markdown(tmp_path) -> None:
    from scholar_vault.importer import _save_card  # noqa: PLC0415
    from scholar_vault.models import SourceCard  # noqa: PLC0415

    vault = tmp_path / "vault"
    paths = initialize_vault(vault)
    _save_card(
        paths,
        SourceCard(
            slug="source",
            citekey="source",
            title="Source Paper",
            authors=["Jane Smith"],
            year=2024,
            venue="Journal of Test Results",
            doi="10.1145/example",
            citation_status="verified",
        ),
    )

    result = CliRunner().invoke(app, ["reference", "--vault", str(vault), "source"])

    assert result.exit_code == 0
    assert (
        "Smith, J. (2024). Source Paper. *Journal of Test Results*. "
        "https://doi.org/10.1145/example"
    ) in result.output


def test_reference_command_can_copy_to_clipboard(tmp_path, monkeypatch) -> None:
    from scholar_vault import cli  # noqa: PLC0415
    from scholar_vault.importer import _save_card  # noqa: PLC0415
    from scholar_vault.models import SourceCard  # noqa: PLC0415

    vault = tmp_path / "vault"
    paths = initialize_vault(vault)
    _save_card(
        paths,
        SourceCard(
            slug="source",
            citekey="source",
            title="Source Paper",
            authors=["Jane Smith"],
            year=2024,
            citation_status="verified",
        ),
    )
    copied: dict[str, str] = {}

    def fake_copy(text: str) -> str:
        copied["text"] = text
        return "test-copy"

    monkeypatch.setattr(cli, "_copy_to_clipboard", fake_copy)

    result = CliRunner().invoke(
        app,
        ["reference", "--vault", str(vault), "--clipboard", "source"],
    )

    assert result.exit_code == 0
    assert "Copied reference to clipboard with test-copy." in result.output
    assert copied["text"].startswith("Smith, J. (2024). Source Paper.")


def test_references_command_writes_whole_vault_bibliography(tmp_path) -> None:
    from scholar_vault.importer import _save_card  # noqa: PLC0415
    from scholar_vault.models import SourceCard  # noqa: PLC0415

    vault = tmp_path / "vault"
    paths = initialize_vault(vault)
    _save_card(
        paths,
        SourceCard(
            slug="source",
            citekey="source",
            title="Source Paper",
            authors=["Jane Smith"],
            year=2024,
            citation_status="verified",
        ),
    )

    result = CliRunner().invoke(app, ["references", "--vault", str(vault)])

    assert result.exit_code == 0
    assert "Wrote 1 reference(s)" in result.output
    assert "Smith, J. (2024). Source Paper." in (
        paths.exports / "references-apa.md"
    ).read_text(encoding="utf-8")


def test_references_command_writes_single_rtf_document(tmp_path) -> None:
    from scholar_vault.importer import _save_card  # noqa: PLC0415
    from scholar_vault.models import SourceCard  # noqa: PLC0415

    vault = tmp_path / "vault"
    paths = initialize_vault(vault)
    _save_card(
        paths,
        SourceCard(
            slug="source",
            citekey="source",
            title="Source Paper",
            authors=["Jane Smith"],
            year=2024,
            citation_status="verified",
        ),
    )

    result = CliRunner().invoke(app, ["references", "--vault", str(vault), "--format", "rtf"])

    assert result.exit_code == 0
    rtf = (paths.exports / "references-apa.rtf").read_text(encoding="utf-8")
    assert rtf.startswith(r"{\rtf1\ansi ")
    assert rtf.count(r"{\rtf1\ansi") == 1
    assert "Smith, J. (2024). Source Paper." in rtf


def _write_test_skill(root, name: str, body: str) -> None:
    skill = root / name
    (skill / "agents").mkdir(parents=True, exist_ok=True)
    (skill / "SKILL.md").write_text(body, encoding="utf-8")
    (skill / "agents" / "openai.yaml").write_text(
        "interface:\n  display_name: Test\n",
        encoding="utf-8",
    )


def test_skills_diff_command_reports_target_only(tmp_path) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    _write_test_skill(source, "shared", "same\n")
    _write_test_skill(target, "shared", "same\n")
    _write_test_skill(target, "vault-only", "new\n")

    result = CliRunner().invoke(
        app,
        ["skills", "diff", "--source", str(source), "--target", str(target)],
    )

    assert result.exit_code == 0
    assert "vault-only: target-only" in result.output


def test_skills_adopt_command_requires_apply(tmp_path) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    _write_test_skill(target, "vault-only", "new\n")

    dry_run = CliRunner().invoke(
        app,
        ["skills", "adopt", "--source", str(source), "--target", str(target), "vault-only"],
    )

    assert dry_run.exit_code == 0
    assert "Dry-run" in dry_run.output
    assert not (source / "vault-only").exists()

    applied = CliRunner().invoke(
        app,
        [
            "skills",
            "adopt",
            "--source",
            str(source),
            "--target",
            str(target),
            "--apply",
            "vault-only",
        ],
    )

    assert applied.exit_code == 0
    assert (source / "vault-only" / "SKILL.md").exists()


def test_skills_publish_command_dry_run_and_apply(tmp_path) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    _write_test_skill(source, "repo-skill", "repo\n")

    dry_run = CliRunner().invoke(
        app,
        ["skills", "publish", "--source", str(source), "--target", str(target)],
    )

    assert dry_run.exit_code == 0
    assert "Dry-run" in dry_run.output
    assert not (target / "repo-skill").exists()

    applied = CliRunner().invoke(
        app,
        [
            "skills",
            "publish",
            "--source",
            str(source),
            "--target",
            str(target),
            "--apply",
        ],
    )

    assert applied.exit_code == 0
    assert (target / "repo-skill" / "SKILL.md").exists()


def test_filtered_gui_stderr_suppresses_known_noise(capfd) -> None:
    from scholar_vault.cli import _filtered_gui_stderr  # noqa: PLC0415

    with _filtered_gui_stderr():
        os.write(
            2,
            b'qt.qpa.fonts: Populating font family aliases took 355 ms. '
            b'Replace uses of missing font family "Helvetica Neue Condensed" with one '
            b"that exists to avoid this cost.\n",
        )
        os.write(
            2,
            b"2026-04-29 15:19:24.206 python[72896:795170] "
            b"TSMSendMessageToUIServer: CFMessagePortSendRequest FAILED(-1) "
            b"to send to port com.apple.tsm.uiserver\n",
        )
        os.write(2, b"real gui problem\n")

    captured = capfd.readouterr()
    assert "Helvetica Neue Condensed" not in captured.err
    assert "TSMSendMessageToUIServer" not in captured.err
    assert "real gui problem" in captured.err


def test_resolve_citation_alias_can_lock_metadata(tmp_path) -> None:
    from scholar_vault.importer import _save_card  # noqa: PLC0415
    from scholar_vault.models import SourceCard  # noqa: PLC0415
    from scholar_vault.sources import load_source_cards  # noqa: PLC0415

    vault = tmp_path / "vault"
    paths = initialize_vault(vault)
    _save_card(paths, SourceCard(slug="source", citekey="source", title="Source"))

    result = CliRunner().invoke(
        app,
        [
            "resolve-citation",
            "--vault",
            str(vault),
            "--citekey",
            "source",
            "--doi",
            "10.1145/example",
            "--authors",
            "Jane Smith",
            "--year",
            "2024",
            "--venue",
            "Example Venue",
            "--lock",
        ],
    )

    assert result.exit_code == 0
    saved = load_source_cards(paths)[0]
    assert saved.metadata_lock is True
    assert saved.citation_status == "verified"
    assert "locked" in result.output


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
            "keyword_enrichment": {"processed": 3, "changed": 1},
        }
    )

    output = "\n".join(lines)

    assert "3 reused from previous run manifest" in output
    assert "0 newly accepted staged PDFs" in output
    assert "No match-review prompts appeared" in output
    assert "citations checked 3 cards (0 updated, 3 unchanged)" in output
    assert "abstracts checked 3 cards (0 updated, 3 unchanged)" in output
    assert "keywords checked 3 cards (1 updated, 2 unchanged)" in output


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
        lambda _summary, *, ui, followup_pending, leftover_pending: events.append(
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


def test_import_finish_can_launch_leftover_staging_match(monkeypatch) -> None:
    from scholar_vault import cli

    events: list[str] = []

    class Progress:
        def close(self) -> None:
            events.append("close-progress")

    summary = {
        "vault": "/tmp/vault",
        "staging_folder": "/tmp/staging",
        "staging_pdfs_remaining": 2,
    }
    monkeypatch.setattr(cli, "_print_run_summary", lambda _summary: events.append("summary"))
    monkeypatch.setattr(
        cli,
        "_show_import_summary_ui",
        lambda _summary, *, ui, followup_pending, leftover_pending: (
            events.append("report") or "leftovers"
        ),
    )
    monkeypatch.setattr(
        cli,
        "_show_import_enrichment_followup",
        lambda _summary, *, ui: events.append("followup"),
    )
    monkeypatch.setattr(
        cli,
        "_run_staging_match_from_summary",
        lambda _summary: events.append("staging-match"),
    )

    cli._finish_import_workflow(summary, ui=True, progress_ui=Progress())

    assert events == ["summary", "report", "close-progress", "staging-match"]


def test_runs_command_lists_previous_runs(tmp_path) -> None:
    vault = tmp_path / "vault"
    paths = initialize_vault(vault)
    run_id = "2026-04-22_example-run"
    write_yaml(
        paths.runs / run_id / "index.yaml",
        {
            "slug": run_id,
            "date": "2026-04-22",
            "prompt": "find useful papers",
            "title": "Papers",
            "exported_at": "2026-04-22T10:00:00+02:00",
            "export_file": "/tmp/export.json",
            "raw_export_file": "raw/scholar-labs/export.json",
            "staging_folder": "/tmp/staging",
            "result_count": 2,
            "results": [
                {"rank": 1, "title": "Selected", "status": "selected"},
                {"rank": 2, "title": "Missing", "status": "unmatched"},
            ],
        },
    )

    result = CliRunner().invoke(app, ["runs", "--vault", str(vault)])

    assert result.exit_code == 0
    assert run_id in result.output
    assert "Papers" in result.output
    assert "1" in result.output
    assert "2" in result.output


def test_run_completion_uses_vault_runs(tmp_path) -> None:
    vault = tmp_path / "vault"
    paths = initialize_vault(vault)
    run_id = "2026-04-22_example-run"
    write_yaml(
        paths.runs / run_id / "index.yaml",
        {
            "slug": run_id,
            "date": "2026-04-22",
            "prompt": "find useful papers",
            "exported_at": "2026-04-22T10:00:00+02:00",
            "export_file": "/tmp/export.json",
            "raw_export_file": "raw/scholar-labs/export.json",
            "staging_folder": "/tmp/staging",
            "result_count": 0,
            "results": [],
        },
    )

    class Ctx:
        params = {"vault": vault}

    assert _complete_run_ids(Ctx(), [], "2026-04") == [run_id]
    assert _complete_only_modes("missing-") == [
        "missing-doi",
        "missing-bibtex",
        "missing-abstract",
        "missing-keywords",
    ]


def test_fish_completion_script_delegates_to_typer() -> None:
    script = _fish_completion_script()

    assert "_SCHOLAR_VAULT_COMPLETE=complete_fish" in script
    assert "_TYPER_COMPLETE_FISH_ACTION=get-args" in script
    assert "--command scholar-vault" in script


def test_install_fish_completion_writes_explicit_path(tmp_path) -> None:
    target = tmp_path / "fish" / "completions" / "scholar-vault.fish"
    result = CliRunner().invoke(app, ["install-fish-completion", "--path", str(target)])

    assert result.exit_code == 0
    assert target.exists()
    assert "_SCHOLAR_VAULT_COMPLETE=complete_fish" in target.read_text(encoding="utf-8")
    assert "Restart Fish" in result.output


def test_zsh_completion_path_uses_zdotdir(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ZDOTDIR", str(tmp_path))

    assert _zsh_completion_path() == tmp_path / ".zfunc" / "_scholar-vault"


def test_zsh_completion_script_is_autoloadable_function() -> None:
    script = _zsh_completion_script()

    assert script.startswith("#compdef scholar-vault\n")
    assert "_SCHOLAR_VAULT_COMPLETE=complete_zsh" in script
    assert "_TYPER_COMPLETE_ARGS=\"${words[1,$CURRENT]}\"" in script
    assert "compdef _scholar_vault_completion scholar-vault" not in script


def test_install_zsh_completion_writes_explicit_path(tmp_path) -> None:
    target = tmp_path / "zsh" / "site-functions" / "_scholar-vault"
    result = CliRunner().invoke(app, ["install-zsh-completion", "--path", str(target)])

    assert result.exit_code == 0
    assert target.exists()
    assert target.read_text(encoding="utf-8").startswith("#compdef scholar-vault\n")
    assert "fpath" in result.output


def test_rerun_checks_for_pdf_upgrades_by_default(tmp_path, monkeypatch) -> None:
    calls = []
    vault = tmp_path / "vault"
    initialize_vault(vault)

    def fake_resume_run(*_args, **kwargs):
        calls.append(kwargs)
        return {"run": "2026-04-22_example-run"}

    monkeypatch.setattr("scholar_vault.cli.resume_run", fake_resume_run)
    monkeypatch.setattr(
        "scholar_vault.cli._finish_import_workflow",
        lambda *_args, **_kwargs: None,
    )

    for command in ("rerun", "re-run"):
        result = CliRunner().invoke(
            app,
            [
                command,
                "--vault",
                str(vault),
                "--run",
                "2026-04-22_example-run",
                "--dry-run",
            ],
        )

        assert result.exit_code == 0
    assert [call["upgrade_pdfs"] for call in calls] == [True, True]


def test_rerun_can_keep_existing_pdfs(tmp_path, monkeypatch) -> None:
    calls = []
    vault = tmp_path / "vault"
    initialize_vault(vault)

    def fake_resume_run(*_args, **kwargs):
        calls.append(kwargs)
        return {"run": "2026-04-22_example-run"}

    monkeypatch.setattr("scholar_vault.cli.resume_run", fake_resume_run)
    monkeypatch.setattr(
        "scholar_vault.cli._finish_import_workflow",
        lambda *_args, **_kwargs: None,
    )

    for command in ("rerun", "re-run"):
        result = CliRunner().invoke(
            app,
            [
                command,
                "--vault",
                str(vault),
                "--run",
                "2026-04-22_example-run",
                "--dry-run",
                "--keep-existing-pdfs",
            ],
        )

        assert result.exit_code == 0
    assert [call["upgrade_pdfs"] for call in calls] == [False, False]


def test_match_staging_ui_imports_selected_pdf_match(tmp_path, monkeypatch) -> None:
    vault = tmp_path / "vault"
    staging = tmp_path / "staging"
    staging.mkdir()
    initialize_vault(vault)
    launched = []

    def fake_choose(*_args, **kwargs):
        kwargs["import_callback"](
            {
                "run_id": "2026-04-22_example-run",
                "rank": 5,
                "result_title": "Example Paper",
                "pdf_path": str(staging / "example.pdf"),
            }
        )
        return None

    monkeypatch.setattr("scholar_vault.cli._choose_staging_match_run_id", fake_choose)
    monkeypatch.setattr(
        "scholar_vault.cli._import_selected_staging_match",
        lambda selected_vault, row: launched.append((selected_vault, row)),
    )

    result = CliRunner().invoke(
        app,
        [
            "match-staging",
            "--vault",
            str(vault),
            "--staging",
            str(staging),
            "--ui",
        ],
    )

    assert result.exit_code == 0
    assert launched == [
        (
            vault.resolve(),
            {
                "run_id": "2026-04-22_example-run",
                "rank": 5,
                "result_title": "Example Paper",
                "pdf_path": str(staging / "example.pdf"),
            },
        )
    ]


def test_import_labs_checks_for_pdf_upgrades_by_default(tmp_path, monkeypatch) -> None:
    calls = []
    vault = tmp_path / "vault"
    staging = tmp_path / "staging"
    export = tmp_path / "export.json"
    initialize_vault(vault)
    staging.mkdir()
    _write_cli_export(export, title="CLI Export Title")

    def fake_import_scholar_labs_run(*_args, **kwargs):
        calls.append(kwargs)
        return {"run": "2026-04-22_example-run"}

    monkeypatch.setattr(
        "scholar_vault.cli.import_scholar_labs_run",
        fake_import_scholar_labs_run,
    )
    monkeypatch.setattr(
        "scholar_vault.cli._finish_import_workflow",
        lambda *_args, **_kwargs: None,
    )

    for command in ("import-labs", "import"):
        result = CliRunner().invoke(
            app,
            [
                command,
                "--vault",
                str(vault),
                "--staging",
                str(staging),
                "--export",
                str(export),
                "--dry-run",
            ],
        )

        assert result.exit_code == 0
    assert [call["upgrade_pdfs"] for call in calls] == [True, True]
    assert [call["archive_matched"] for call in calls] == [True, True]
    assert [call["archive_export"] for call in calls] == [True, True]
    assert [call["auto_enrich"] for call in calls] == [True, True]
    assert [call["title"] for call in calls] == ["CLI Export Title", "CLI Export Title"]


def test_import_labs_prompts_for_title_when_export_has_none(tmp_path, monkeypatch) -> None:
    calls = []
    vault = tmp_path / "vault"
    staging = tmp_path / "staging"
    export = tmp_path / "export.json"
    prompt = (
        "Find peer-reviewed papers on collaborative immersive analytics for multimodal "
        "urban mobility data, including VR and AR systems, shared workspaces, and "
        "evaluation methods that could support a postdoctoral proposal."
    )
    initialize_vault(vault)
    staging.mkdir()
    _write_cli_export(export, prompt=prompt)

    def fake_import_scholar_labs_run(*_args, **kwargs):
        calls.append(kwargs)
        return {"run": "2026-04-22_example-run"}

    monkeypatch.setattr(
        "scholar_vault.cli.import_scholar_labs_run",
        fake_import_scholar_labs_run,
    )
    monkeypatch.setattr(
        "scholar_vault.cli._finish_import_workflow",
        lambda *_args, **_kwargs: None,
    )

    result = CliRunner().invoke(
        app,
        [
            "import-labs",
            "--vault",
            str(vault),
            "--staging",
            str(staging),
            "--export",
            str(export),
            "--dry-run",
        ],
        input="Custom Prompted Run\n",
    )

    assert result.exit_code == 0
    assert prompt in result.output
    assert calls[0]["title"] == "Custom Prompted Run"


def test_import_pdf_cli_passes_no_enrich(tmp_path, monkeypatch) -> None:
    calls = []
    vault = tmp_path / "vault"
    staging = tmp_path / "staging"
    initialize_vault(vault)
    staging.mkdir()

    def fake_import_pdf_dropins(*args, **kwargs):
        calls.append((args, kwargs))
        return {
            "imported": 0,
            "created": 0,
            "updated_existing": 0,
            "pdfs": [],
            "citation_enrichment": {},
            "abstract_enrichment": {},
            "keyword_enrichment": {},
            "details": [],
        }

    monkeypatch.setattr("scholar_vault.cli.import_pdf_dropins", fake_import_pdf_dropins)

    result = CliRunner().invoke(
        app,
        [
            "import-pdf",
            "--vault",
            str(vault),
            "--staging",
            str(staging),
            "--no-enrich",
        ],
    )

    assert result.exit_code == 0
    assert calls[0][1]["auto_enrich"] is False
    assert calls[0][1]["pdf_paths"] is None


def test_import_pdf_ui_uses_selected_files(tmp_path, monkeypatch) -> None:
    calls = []
    vault = tmp_path / "vault"
    initialize_vault(vault)
    selected_pdf = tmp_path / "selected.pdf"
    selected_pdf.write_bytes(b"%PDF-1.4\n")

    def fake_choose_pdf_import_ui(_vault, _staging, *, auto_enrich):
        assert auto_enrich is True
        return {
            "pdfs": [str(selected_pdf)],
            "auto_enrich": True,
            "open_followup": False,
        }

    def fake_import_pdf_dropins(*args, **kwargs):
        calls.append((args, kwargs))
        return {
            "imported": 1,
            "created": 1,
            "updated_existing": 0,
            "pdfs": [{"citekey": "selected", "title": "Selected", "created": True}],
            "citation_enrichment": {"processed": 1, "changed": 1},
            "abstract_enrichment": {"processed": 1, "changed": 0},
            "keyword_enrichment": {"processed": 1, "changed": 0},
            "details": [],
        }

    monkeypatch.setattr("scholar_vault.cli._choose_pdf_import_ui", fake_choose_pdf_import_ui)
    monkeypatch.setattr("scholar_vault.cli.import_pdf_dropins", fake_import_pdf_dropins)
    monkeypatch.setattr("scholar_vault.cli._make_gui_progress", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        "scholar_vault.cli._show_pdf_import_summary_ui",
        lambda *_args, **_kwargs: False,
    )

    result = CliRunner().invoke(app, ["import-pdf", "--vault", str(vault), "--ui"])

    assert result.exit_code == 0
    assert calls[0][1]["pdf_paths"] == [str(selected_pdf)]
    assert calls[0][1]["auto_enrich"] is True
    assert "Imported 1 PDF file(s)." in result.output


def test_rebuild_command_prints_summary(tmp_path) -> None:
    vault = tmp_path / "vault"
    initialize_vault(vault)

    result = CliRunner().invoke(app, ["rebuild", "--vault", str(vault)])

    assert result.exit_code == 0
    assert "Rebuilt derived files" in result.output
    assert "- Papers: 0 total" in result.output
    assert "- Runs: 0 run notes refreshed" in result.output
    assert "- Derived outputs:" in result.output
