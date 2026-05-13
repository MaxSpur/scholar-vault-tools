from __future__ import annotations

from pathlib import Path

from pypdf import PdfWriter


def test_gui_module_imports() -> None:
    from scholar_vault import gui

    assert gui.GuiUnavailable is not None


def test_gui_dependency_loader_smoke() -> None:
    from scholar_vault.gui import _load_qt_modules

    modules = _load_qt_modules(require_fitz=True)

    assert "QApplication" in modules
    assert "QEventLoop" in modules
    assert "QFontDatabase" in modules
    assert "fitz" in modules


def test_summary_font_uses_system_font() -> None:
    from scholar_vault.gui import _load_qt_modules, _summary_font

    modules = _load_qt_modules(require_fitz=False)
    font = _summary_font(modules, 12, mono=True, bold=True)

    assert "Helvetica Neue Condensed" not in font.family()


def test_gui_pdf_preview_render_smoke(tmp_path: Path) -> None:
    from scholar_vault.gui import _load_qt_modules, _render_pdf_image

    pdf = tmp_path / "preview.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=300)
    with pdf.open("wb") as handle:
        writer.write(handle)

    modules = _load_qt_modules(require_fitz=True)
    image = _render_pdf_image(modules, str(pdf), full_page=False)

    assert image.width() > 0
    assert image.height() > 0


def test_preview_viewport_height_targets_top_third() -> None:
    from scholar_vault.gui import _preview_viewport_height

    assert _preview_viewport_height(1500) == 500
    assert _preview_viewport_height(900) == 430
    assert _preview_viewport_height(2400) == 640


def test_project_workspace_model_lists_projects_and_papers(tmp_path: Path) -> None:
    from scholar_vault.gui import _project_workspace_model
    from scholar_vault.importer import _save_card, initialize_vault
    from scholar_vault.models import SourceCard
    from scholar_vault.projects import project_scaffold
    from scholar_vault.sources import write_yaml

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
    (paths.concepts / "map-lenses.md").write_text(
        "---\ntype: concept\ntitle: Map Lenses\n---\n\n# Map Lenses\n",
        encoding="utf-8",
    )
    (paths.syntheses / "deformation-survey.md").write_text(
        "---\ntype: synthesis\ntitle: Deformation Survey\n---\n\n# Deformation Survey\n",
        encoding="utf-8",
    )
    (paths.tasks / "read-lenses.md").write_text(
        "---\ntype: task\ntitle: Read Lenses\n---\n\n# Read Lenses\n",
        encoding="utf-8",
    )
    run_id = "2026-04-22_map-lens-run"
    write_yaml(
        paths.runs / run_id / "index.yaml",
        {
            "slug": run_id,
            "date": "2026-04-22",
            "prompt": "map lens papers",
            "title": "Map Lens Run",
            "exported_at": "2026-04-22T10:00:00+02:00",
            "export_file": "/tmp/export.json",
            "raw_export_file": "raw/scholar-labs/export.json",
            "staging_folder": "/tmp/staging",
            "result_count": 0,
            "results": [],
        },
    )
    proposal = paths.proposals / "pepr-mobidec"
    proposal.mkdir(parents=True)
    (proposal / "index.md").write_text(
        "---\ntype: proposal\ntitle: PEPR Mobidec\n---\n\n# PEPR Mobidec\n",
        encoding="utf-8",
    )
    project_scaffold(vault, "map-lens-deformation")

    model = _project_workspace_model(vault)

    assert model["projects"][0]["slug"] == "map-lens-deformation"
    assert model["papers"][0]["key"] == "Schottler2021_GeospatialNetworks"
    assert model["papers"][0]["title"] == "Geospatial Networks"
    assert model["resources"]["Paper"][0]["target"] == "Schottler2021_GeospatialNetworks"
    assert model["resources"]["Run"][0]["target"] == run_id
    assert model["resources"]["Concept"][0]["target"] == "concepts/map-lenses.md"
    assert model["resources"]["Synthesis"][0]["target"] == "syntheses/deformation-survey.md"
    assert model["resources"]["Task"][0]["target"] == "tasks/read-lenses.md"
    assert model["resources"]["Proposal"][0]["target"] == "proposals/pepr-mobidec"


def test_project_workspace_rows_have_readable_size_and_compact_badges() -> None:
    from scholar_vault.gui import (
        _application,
        _load_qt_modules,
        _project_list_item_widget,
        _project_resource_badges,
    )

    modules = _load_qt_modules(require_fitz=False)
    _application(modules)
    paper_row = {
        "kind": "Paper",
        "key": "LongPaperKey",
        "title": "A very long paper title that must not be vertically squashed",
        "path": "papers/long-paper.md",
        "pdf": "attached",
        "status": "complete",
    }
    project_row = {
        "kind": "Project",
        "key": "map-lens-deformation",
        "title": "Map deformation techniques for web tile maps",
        "path": "projects/map-lens-deformation/index.md",
    }

    item, _widget = _project_list_item_widget(
        modules,
        paper_row,
        selected_callback=lambda _item: None,
        row_height=48,
    )
    _project_item, project_widget = _project_list_item_widget(
        modules,
        project_row,
        selected_callback=lambda _item: None,
        show_badges=False,
        row_height=50,
    )
    project_labels = [label.text() for label in project_widget.findChildren(modules["QLabel"])]

    assert item.sizeHint().height() == 48
    assert _project_resource_badges(paper_row) == [
        ("PDF", "#45ffb0", "#021007"),
        ("OK", "#69ffad", "#021007"),
    ]
    assert "PROJ" not in project_labels


def test_confidence_color_thresholds() -> None:
    from scholar_vault.gui import _confidence_color

    assert _confidence_color(100) == "#0067d8"
    assert _confidence_color(95) == "#238200"
    assert _confidence_color(82) == "#a46f00"
    assert _confidence_color(76) == "#c86a00"
    assert _confidence_color(70) == "#b00020"


def test_match_dialog_abort_result_raises() -> None:
    from scholar_vault.gui import _ABORT_DIALOG_CODE, _match_dialog_result
    from scholar_vault.models import MatchReviewAbort

    try:
        _match_dialog_result({}, _ABORT_DIALOG_CODE)
    except MatchReviewAbort:
        pass
    else:
        raise AssertionError("Abort dialog result should raise MatchReviewAbort.")


def test_import_summary_model_highlights_reused_manifest() -> None:
    from scholar_vault.gui import _import_summary_model

    model = _import_summary_model(
        {
            "run": "2026-04-23_example",
            "selected": 19,
            "unselected_results": 11,
            "decision_summary": {
                "export_results": 30,
                "prior_selected_reused": 19,
                "existing_cards_linked": 0,
                "new_staged_pdf_matches": 0,
                "review_prompts": 0,
                "review_rejected": 0,
                "results_without_candidate": 11,
            },
            "citation_enrichment": {"processed": 19, "changed": 1},
            "abstract_enrichment": {"processed": 19, "changed": 0},
            "enrichment_details": [
                {"category": "verified"},
                {"category": "skipped", "skipped": True},
            ],
            "abstract_details": [{"category": "unresolved"}],
        },
        ["Processed run 2026-04-23_example."],
    )

    assert model["status"] == "CHECK"
    assert model["flow"][0] == ("EXPORT", 30, "#8bffd0")
    assert model["flow"][2] == ("REUSED", 19, "#41e893")
    assert "No review prompts" in model["notice"]
    assert model["breakdown"][0][1] == 11
    assert model["enrichment"][0]["checked"] == 19
    assert model["enrichment"][0]["updated"] == 1
    assert model["enrichment"][0]["unchanged"] == 18
    assert model["enrichment"][0]["skipped"] == 1
    assert model["enrichment"][1]["checked"] == 19
    assert model["enrichment"][1]["issues"] == 1
    assert model["followup_issues"] == 1


def test_progress_finished_state_marks_report_ready() -> None:
    from scholar_vault.gui import _progress_finished_state

    state = _progress_finished_state()

    assert state["stage"] == "REPORT READY"
    assert state["substage"].startswith("Import, enrichment, and rebuild finished")
    assert "scrollable" in state["substage"]
    assert state["counter"] == "DONE"
    assert state["action"] == "Close Log"


def test_progress_parts_name_import_substages() -> None:
    from scholar_vault.gui import (
        _progress_item_text,
        _progress_log_color,
        _progress_log_html,
        _progress_parts,
        _progress_step_text,
    )

    assert _progress_parts("Reading Scholar Labs export export.json") == (
        "READING EXPORT",
        "Validating Scholar Labs JSON and loading prior run state",
        "export.json",
    )
    assert _progress_parts("Scanning staged PDF example.pdf") == (
        "PDF SCAN",
        "Extracting PDF title, DOI, year, and first-page text",
        "example.pdf",
    )
    assert _progress_parts("Importing PDF direct-paper.pdf") == (
        "PDF IMPORT",
        "Extracting title, DOI, year, keywords, and matching existing cards",
        "direct-paper.pdf",
    )
    assert _progress_parts("Using cached staged PDF scan example.pdf") == (
        "PDF SCAN",
        "Using cached PDF title, DOI, year, and first-page text",
        "example.pdf",
    )
    assert _progress_parts("Enriching abstracts [skipped]: nafis2024paper") == (
        "ABSTRACT ENRICHMENT",
        "SKIPPED // no change; existing state, lock, cache, or retry rule",
        "nafis2024paper",
    )
    assert _progress_parts(
        "Enriching abstracts [result:crossref DOI abstract lookup -> 1 abstract candidate]: "
        "nafis2024paper // Are We There Yet? // state=missing; pdf=yes"
    ) == (
        "ABSTRACT ENRICHMENT",
        "RESULT // crossref DOI abstract lookup -> 1 abstract candidate",
        "nafis2024paper // Are We There Yet? // state=missing; pdf=yes",
    )
    assert _progress_parts(
        "Enriching keywords [result:PDF keyword extraction -> added 3 keywords]: "
        "nafis2024paper // Are We There Yet? // state=present; count=3; pdf=yes"
    ) == (
        "KEYWORD ENRICHMENT",
        "RESULT // PDF keyword extraction -> added 3 keywords",
        "nafis2024paper // Are We There Yet? // state=present; count=3; pdf=yes",
    )
    assert (
        _progress_item_text(
            "Enriching abstracts [checking]: nafis2024paper // Are We There Yet? // "
            "state=unresolved; pdf=yes"
        )
        == "nafis2024paper"
    )
    assert (
        _progress_item_text("Checking Scholar Labs result 3: Example Paper")
        == "r03-examplepaper"
    )
    assert (
        _progress_item_text(
            "Matching Scholar Labs result 12 [pdf]: scoring 4 staged PDF candidates // "
            "r12-collaborativeimmersiveanalytics"
        )
        == "r12-collaborativeimmersiveanalytics"
    )
    assert (
        _progress_step_text("Checking Scholar Labs result 3: Example Paper", 3, 20)
        == "[3/20] MATCHING: Comparing this result with prior decisions, vault cards, "
        "and staged PDFs // rank 3 // r03-examplepaper"
    )
    assert _progress_log_color("Enriching abstracts [unresolved]: example") == "#ff3b4f"
    assert (
        _progress_log_color(
            "Enriching abstracts [attempt:crossref DOI abstract lookup]: example"
        )
        == "#ffb000"
    )
    assert (
        _progress_log_color(
            "Enriching abstracts [skip-pass:europepmc abstract lookup]: example"
        )
        == "#a7b2aa"
    )
    log_html = _progress_log_html("Enriching citations [verified]: example", 1, 3)
    assert "&nbsp;1/3&nbsp;" in log_html
    assert "CITATION ENRICHMENT" in log_html
    assert "ok; trusted metadata present" in log_html
    assert "example" in log_html
    assert "Example Title" not in _progress_log_html(
        "Enriching citations [verified]: example // Example Title // state=verified",
        1,
        3,
    )
    assert "state" in _progress_log_html(
        "Enriching abstracts [checking]: example // Example Title // state=missing; pdf=yes",
        1,
        3,
    )
    unresolved_html = _progress_log_html(
        "Enriching abstracts [checking]: example // Example Title // "
        "state=unresolved; source=manual; pdf=no; locked",
        1,
        3,
    )
    assert "color:#ff3b4f; font-weight:800;\">=unresolved" in unresolved_html
    assert "color:#8bffd0; font-weight:800;\">=manual" in unresolved_html
    assert "color:#ff3b4f; font-weight:800;\">=no" in unresolved_html
    assert "color:#8bffd0; font-weight:800;\">locked" in unresolved_html


def test_match_confidence_detail_explains_score_source() -> None:
    from scholar_vault.gui import _confidence_detail_text
    from scholar_vault.models import MatchReviewRequest

    request = MatchReviewRequest(
        rank=5,
        result_title="Visualization in virtual reality: a systematic review",
        pdf_path="/tmp/example.pdf",
        pdf_filename="example.pdf",
        score=76,
        match_reason="title",
        proposed_decision="review",
    )

    detail = _confidence_detail_text(request)

    assert "source: PDF title text" in detail
    assert "-24 from exact" in detail
    assert "fuzzy PDF-title similarity" in detail


def test_confirmation_model_makes_existing_run_prompt_readable() -> None:
    from scholar_vault.gui import _confirmation_model

    model = _confirmation_model(
        "Run 2026-04-23_find-key-papers-on-collaborative-immersive-analytics-for-dat "
        "already exists. Resume and update it?"
    )

    assert model["heading"] == "Resume Existing Run?"
    assert model["detail_label"] == "RUN"
    assert model["detail"] == (
        "2026-04-23_find-key-papers-on-collaborative-immersive-analytics-for-dat"
    )
    assert model["accept"] == "Resume"
    assert model["reject"] == "Cancel"


def test_run_picker_model_sorts_and_counts_runs() -> None:
    from scholar_vault.gui import _run_picker_model
    from scholar_vault.models import RunRecord

    older = RunRecord.model_validate(
        {
            "slug": "2026-04-21_old-run",
            "date": "2026-04-21",
            "prompt": "older prompt",
            "title": "Older Run",
            "exported_at": "2026-04-21T09:00:00+02:00",
            "export_file": "/tmp/old.json",
            "raw_export_file": "raw/scholar-labs/old.json",
            "result_count": 2,
            "results": [
                {
                    "rank": 1,
                    "title": "Selected",
                    "status": "selected",
                    "pdf_status": "attached",
                },
                {"rank": 2, "title": "Missing", "status": "unmatched"},
            ],
            "matched_files": ["a.pdf"],
            "unmatched_files": ["b.pdf"],
        }
    )
    newer = RunRecord.model_validate(
        {
            "slug": "2026-04-22_new-run",
            "date": "2026-04-22",
            "prompt": (
                "newer prompt with enough detail that it should stay complete in the "
                "run picker model instead of being abbreviated"
            ),
            "exported_at": "2026-04-22T10:30:00+02:00",
            "export_file": "/tmp/new.json",
            "raw_export_file": "raw/scholar-labs/new.json",
            "result_count": 3,
            "results": [
                {
                    "rank": 1,
                    "title": "Selected",
                    "status": "selected",
                    "pdf_status": "attached",
                },
                {"rank": 2, "title": "Candidate", "status": "candidate"},
                {"rank": 3, "title": "Missing", "status": "unmatched"},
            ],
        }
    )

    model = _run_picker_model(
        [older, newer],
        "/tmp/vault",
        issue_summaries={
            "2026-04-22_new-run": {
                "count": 2,
                "kinds": {"abstract": 1, "metadata": 1},
            }
        },
    )

    assert model["rows"][0]["run_id"] == "2026-04-22_new-run"
    assert model["rows"][0]["is_latest"] is True
    assert model["rows"][0]["selected"] == 1
    assert model["rows"][0]["total"] == 3
    assert model["rows"][0]["issues"] == 2
    assert model["rows"][0]["issue_text"] == "2 FOLLOW-UPS: ABSTRACT, METADATA"
    assert "abbreviated" in model["rows"][0]["prompt"]
    assert model["rows"][0]["title"] == "2026-04-22_new-run"
    assert model["rows"][1]["run_id"] == "2026-04-21_old-run"
    assert model["rows"][1]["accepted_now"] == 1
    assert model["rows"][1]["unmatched_files"] == 1


def test_staging_match_model_formats_rows() -> None:
    from scholar_vault.gui import _staging_match_model

    model = _staging_match_model(
        {
            "runs": 3,
            "staged_pdfs_scanned": 2,
            "staged_pdf_cache_hits": 1,
            "min_score": 70,
            "matches": [
                {
                    "run_id": "2026-04-22_example",
                    "run_title": "Example Run",
                    "rank": 4,
                    "score": 92,
                    "result_title": "Origin-Destination Flow Data Smoothing and Mapping",
                    "pdf_filename": "leftover.pdf",
                    "pdf_path": "/tmp/leftover.pdf",
                    "pdf_title": "Origin-Destination Flow Data Smoothing and Mapping",
                    "paper_card": "papers/origin-destination.md",
                    "attached": True,
                    "reason": "title",
                    "decision": "auto",
                    "status": "selected",
                    "pdf_status": "attached",
                }
            ],
        }
    )

    assert model["runs"] == 3
    assert model["scanned"] == 2
    assert model["cache_hits"] == 1
    assert model["rows"][0]["score_color"] == "#45ffb0"
    assert model["rows"][0]["run_id"] == "2026-04-22_example"
    assert model["rows"][0]["pdf_path"] == "/tmp/leftover.pdf"
    assert model["rows"][0]["paper_card"] == "papers/origin-destination.md"
    assert model["rows"][0]["attached"] is True
    assert model["rows"][0]["state"] == "selected / attached / already attached"


def test_skill_sync_selection_helpers_keep_direction_on_buttons() -> None:
    from scholar_vault.gui import (
        _skill_sync_can_pull,
        _skill_sync_can_update,
        _skill_sync_default_selected,
        _skill_sync_row_text,
    )

    source_newer = {"status": "changed", "newer": "source"}
    target_newer = {"status": "changed", "newer": "target"}
    source_only = {"status": "source-only"}
    target_only = {"status": "target-only"}

    assert _skill_sync_default_selected(source_newer) is True
    assert _skill_sync_default_selected(source_only) is True
    assert _skill_sync_can_update(source_newer) is True
    assert _skill_sync_can_pull(source_newer) is True
    assert _skill_sync_can_update(target_newer) is True
    assert _skill_sync_can_pull(target_newer) is True
    assert _skill_sync_can_update(source_only) is True
    assert _skill_sync_can_pull(source_only) is False
    assert _skill_sync_can_update(target_only) is False
    assert _skill_sync_can_pull(target_only) is True

    text = _skill_sync_row_text(
        {"status": "changed", "newer": "source", "changed_files": 2}
    )
    assert "repository newer" in text
    assert "2 files differ" in text
    assert "update vault" not in text
    assert "pull vault" not in text


def test_move_staged_pdf_to_trash_uses_staging_trash_folder(tmp_path: Path) -> None:
    from scholar_vault.gui import _move_staged_pdf_to_trash

    staging = tmp_path / "staging"
    staging.mkdir()
    pdf = staging / "leftover.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")

    destination = _move_staged_pdf_to_trash(str(staging), str(pdf))

    assert destination == staging / "trash" / "leftover.pdf"
    assert destination.exists()
    assert not pdf.exists()


def test_missing_abstract_issue_is_resolvable() -> None:
    from scholar_vault.gui import _can_resolve_missing_abstract

    assert _can_resolve_missing_abstract(
        {
            "kind": "abstract",
            "category": "skipped",
            "message": "abstract previously failed",
            "paper_file": "/tmp/vault/papers/example.md",
            "citekey": "example2024paper",
        }
    )


def test_manual_metadata_issue_is_resolvable() -> None:
    from scholar_vault.gui import _can_resolve_manual_metadata

    assert _can_resolve_manual_metadata(
        {
            "kind": "citation",
            "category": "ambiguous",
            "missing_fields": ["doi", "authors", "venue"],
            "paper_file": "/tmp/vault/papers/example.md",
            "citekey": "example2024paper",
        }
    )


def test_pending_issue_count_drops_when_row_resolves() -> None:
    from scholar_vault.gui import _pending_issue_count

    details = [
        {
            "kind": "citation",
            "category": "ambiguous",
            "message": "ambiguous crossref candidate score=82",
        },
        {
            "kind": "keywords",
            "category": "unresolved",
            "message": "no keywords found in attached PDF",
        },
        {
            "kind": "keywords",
            "category": "resolved",
            "message": "manual keywords saved",
        },
    ]

    assert _pending_issue_count(details) == 2
    details[0]["category"] = "resolved"
    assert _pending_issue_count(details) == 1
