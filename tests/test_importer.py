from __future__ import annotations

import json
from pathlib import Path

import yaml
from pypdf import PdfWriter

from scholar_vault.importer import (
    cleanup_run_selected_only,
    import_pdf_dropins,
    import_scholar_labs_run,
    initialize_vault,
    latest_run_id,
    rebuild_vault,
    rename_run,
    reset_vault,
    resume_run,
    undo_run,
)
from scholar_vault.models import RunRecord, RunResultRecord, ScholarLabsResult, SourceCard
from scholar_vault.sources import load_source_cards, run_note_path, write_yaml


def _write_fixture_copy(name: str, target: Path) -> Path:
    fixture = Path(__file__).parent / "fixtures" / name
    target.write_text(fixture.read_text(encoding="utf-8"), encoding="utf-8")
    return target


def _write_pdf_with_title(path: Path, title: str) -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.add_metadata({"/Title": title})
    with path.open("wb") as handle:
        writer.write(handle)


def _write_export(
    path: Path,
    result_count: int,
    *,
    prompt: str = "retrieval augmented generation evaluation with grounded evidence",
    exported_at: str = "2026-04-22T16:00:00+02:00",
) -> Path:
    results = []
    for index in range(result_count):
        results.append(
            {
                "rank": index + 1,
                "scholar_cid": f"cid-{index + 1:03d}",
                "title": f"Result Paper {index + 1}",
                "authors_preview": "Jane Smith, Omar Lee",
                "year": 2024,
                "venue_preview": "Test Venue",
                "publisher_or_host": "ACM",
                "summary": f"Summary for result {index + 1}.",
                "rationale_points": [{"label": "Test", "text": "Useful result."}],
                "links": [
                    {
                        "label": "publication",
                        "url": f"https://example.com/{index + 1}",
                        "kind": "html",
                    }
                ],
            }
        )
    payload = {
        "schema_version": "0.2",
        "source": "google_scholar_labs",
        "exported_at": exported_at,
        "prompt": prompt,
        "results": results,
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def _rewrite_export(path: Path, **updates: object) -> Path:
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload.update({key: value for key, value in updates.items() if key != "result_updates"})
    result_updates = updates.get("result_updates")
    if isinstance(result_updates, dict):
        payload["results"][0].update(result_updates)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def _run_yaml(vault: Path, run_id: str) -> dict:
    return yaml.safe_load((vault / "runs" / run_id / "index.yaml").read_text(encoding="utf-8"))


def _manifest_yaml(vault: Path, run_id: str) -> dict:
    return yaml.safe_load(
        (vault / "runs" / run_id / "import-manifest.yaml").read_text(encoding="utf-8")
    )


def _run_note_path(vault: Path, run_id: str) -> str:
    run_yaml = _run_yaml(vault, run_id)
    return run_note_path(
        run_id,
        run_yaml["date"],
        run_yaml.get("title"),
        run_yaml["prompt"],
        run_yaml.get("note_file"),
    )


def test_import_run_creates_only_selected_paper_cards(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    staging = tmp_path / "staging"
    exports = tmp_path / "exports"
    staging.mkdir()
    exports.mkdir()
    export_path = _write_export(exports / "sample.json", 30)

    for index in range(1, 4):
        _write_pdf_with_title(staging / f"paper-{index}.pdf", f"Result Paper {index}")

    summary = import_scholar_labs_run(vault, export_path, staging, commit=True)
    cards = load_source_cards(initialize_vault(vault))
    run_id = str(summary["run"])
    run_yaml = _run_yaml(vault, run_id)
    manifest = _manifest_yaml(vault, run_id)

    assert len(cards) == 3
    assert summary["selected"] == 3
    assert len(run_yaml["results"]) == 30
    assert len([result for result in run_yaml["results"] if result["status"] == "selected"]) == 3
    assert len([entry for entry in manifest["entries"] if entry.get("decision") == "accepted"]) == 3
    assert len(list((vault / "pdfs").glob("*.pdf"))) == 3
    assert len(list(staging.glob("*.pdf"))) == 3


def test_rejected_match_leaves_pdf_in_staging(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    staging = tmp_path / "staging"
    exports = tmp_path / "exports"
    staging.mkdir()
    exports.mkdir()
    export_path = _write_fixture_copy("sample_scholar_labs_export.json", exports / "sample.json")
    pdf_path = staging / "match.pdf"
    _write_pdf_with_title(pdf_path, "Evaluating Retrieval Augmented Generation Systems")

    summary = import_scholar_labs_run(
        vault,
        export_path,
        staging,
        confirm=lambda _prompt: False,
    )
    cards = load_source_cards(initialize_vault(vault))
    manifest = _manifest_yaml(vault, str(summary["run"]))

    assert pdf_path.exists()
    assert len(cards) == 0
    assert any(entry.get("decision") == "rejected" for entry in manifest["entries"])


def test_import_run_is_idempotent(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    staging = tmp_path / "staging"
    exports = tmp_path / "exports"
    staging.mkdir()
    exports.mkdir()
    export_path = _write_fixture_copy("sample_scholar_labs_export.json", exports / "sample.json")
    _write_pdf_with_title(
        staging / "match.pdf", "Evaluating Retrieval Augmented Generation Systems"
    )

    first = import_scholar_labs_run(vault, export_path, staging, commit=True)
    second = import_scholar_labs_run(vault, export_path, staging, commit=True)

    cards = load_source_cards(initialize_vault(vault))
    run_id = str(first["run"])
    run_yaml = _run_yaml(vault, run_id)

    assert first["selected"] == 1
    assert second["selected"] == 1
    assert len(cards) == 1
    assert len(list((vault / "runs").glob("*"))) == 1
    assert len([result for result in run_yaml["results"] if result["status"] == "selected"]) == 1
    assert len(list((vault / "pdfs").glob("*.pdf"))) == 1


def test_repeated_labs_result_adds_run_specific_summary_to_existing_card(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    staging = tmp_path / "staging"
    exports = tmp_path / "exports"
    staging.mkdir()
    exports.mkdir()
    first_export = _rewrite_export(
        _write_export(exports / "first.json", 1),
        prompt="first scholar labs prompt about collaborative immersive analytics",
        exported_at="2026-04-22T16:00:00+02:00",
        result_updates={"summary": "First Scholar Labs summary."},
    )
    second_export = _rewrite_export(
        _write_export(exports / "second.json", 1),
        prompt="second scholar labs prompt about mixed reality workspaces",
        exported_at="2026-04-23T16:00:00+02:00",
        result_updates={"summary": "Second Scholar Labs summary."},
    )
    _write_pdf_with_title(staging / "paper-1.pdf", "Result Paper 1")

    first = import_scholar_labs_run(
        vault,
        first_export,
        staging,
        commit=True,
        archive_matched=True,
    )
    second = import_scholar_labs_run(vault, second_export, staging, commit=True)

    cards = load_source_cards(initialize_vault(vault))
    second_run = _run_yaml(vault, str(second["run"]))

    assert len(cards) == 1
    assert second["selected"] == 1
    assert second_run["results"][0]["status"] == "selected"
    assert second_run["results"][0]["paper_card"] == f"papers/{cards[0].slug}.md"
    assert [source.summary for source in cards[0].summary_sources] == [
        "First Scholar Labs summary.",
        "Second Scholar Labs summary.",
    ]
    first_note = _run_note_path(vault, str(first["run"]))
    second_note = _run_note_path(vault, str(second["run"]))
    assert cards[0].summary_sources[0].run == first_note
    assert cards[0].summary_sources[1].run == second_note
    assert cards[0].discovered_in == [
        first_note,
        second_note,
    ]


def test_run_markdown_uses_obsidian_friendly_filename(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    staging = tmp_path / "staging"
    exports = tmp_path / "exports"
    staging.mkdir()
    exports.mkdir()
    export_path = _write_export(exports / "sample.json", 1)

    summary = import_scholar_labs_run(vault, export_path, staging, commit=True)
    run_id = str(summary["run"])
    note = _run_note_path(vault, run_id)

    assert (vault / note).exists()
    assert Path(note).name != f"{run_id}.md"
    assert not (vault / "runs" / run_id / "index.md").exists()
    assert f"../{note}" in (
        vault / "_indexes" / "prompts.md"
    ).read_text(encoding="utf-8")


def test_import_run_accepts_short_title_for_obsidian_graph(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    staging = tmp_path / "staging"
    exports = tmp_path / "exports"
    staging.mkdir()
    exports.mkdir()
    export_path = _write_export(exports / "sample.json", 1)

    summary = import_scholar_labs_run(
        vault,
        export_path,
        staging,
        commit=True,
        title="Urban Mobility Sources",
    )
    run_id = str(summary["run"])
    note = _run_note_path(vault, run_id)
    run_yaml = _run_yaml(vault, run_id)
    run_markdown = (vault / note).read_text(encoding="utf-8")

    assert run_yaml["title"] == "Urban Mobility Sources"
    assert note.endswith("/Urban Mobility Sources.md")
    assert "title: Urban Mobility Sources" in run_markdown
    assert "# Scholar Labs Run: Urban Mobility Sources" in run_markdown


def test_rename_run_updates_note_and_card_references(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    staging = tmp_path / "staging"
    exports = tmp_path / "exports"
    staging.mkdir()
    exports.mkdir()
    export_path = _write_export(exports / "sample.json", 1)
    _write_pdf_with_title(staging / "paper-1.pdf", "Result Paper 1")

    summary = import_scholar_labs_run(vault, export_path, staging, commit=True)
    run_id = str(summary["run"])
    old_note = _run_note_path(vault, run_id)
    rename_run(vault, run_id, "Renamed Run")
    new_note = _run_note_path(vault, run_id)
    cards = load_source_cards(initialize_vault(vault))

    assert old_note != new_note
    assert new_note.endswith("/Renamed Run.md")
    assert not (vault / old_note).exists()
    assert (vault / new_note).exists()
    assert cards[0].discovered_in == [new_note]
    assert cards[0].summary_sources[0].run == new_note


def test_rebuild_preserves_manual_obsidian_run_note_filename(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    staging = tmp_path / "staging"
    exports = tmp_path / "exports"
    staging.mkdir()
    exports.mkdir()
    export_path = _write_export(exports / "sample.json", 1)

    summary = import_scholar_labs_run(vault, export_path, staging, commit=True)
    run_id = str(summary["run"])
    original_note = vault / _run_note_path(vault, run_id)
    manual_note = original_note.parent / "Broad Proposal Support Search (Mobidec Postdoc).md"
    original_note.rename(manual_note)

    rebuild_vault(vault)

    note = _run_note_path(vault, run_id)
    run_yaml = _run_yaml(vault, run_id)
    assert note.endswith("/Broad Proposal Support Search (Mobidec Postdoc).md")
    assert (vault / note).exists()
    assert run_yaml["title"] == "Broad Proposal Support Search (Mobidec Postdoc)"
    assert run_yaml["note_file"] == "Broad Proposal Support Search (Mobidec Postdoc).md"


def test_rebuild_migrates_legacy_run_index_links_and_files(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    paths = initialize_vault(vault)
    run_id = "2026-04-22_legacy-index-run"
    legacy_ref = f"runs/{run_id}/index.md"
    run_dir = paths.runs / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "index.md").write_text("# Legacy index\n", encoding="utf-8")
    write_yaml(
        run_dir / "index.yaml",
        RunRecord(
            slug=run_id,
            date="2026-04-22",
            prompt="legacy index run",
            exported_at="2026-04-22T16:00:00+02:00",
            export_file="/tmp/export.json",
            raw_export_file="raw/scholar-labs/example.json",
            result_count=1,
            results=[
                RunResultRecord(
                    rank=1,
                    title="Legacy Paper",
                    status="selected",
                    pdf_status="attached",
                    paper_card="papers/legacy.md",
                )
            ],
        ).model_dump(exclude_none=True),
    )
    card = SourceCard(
        slug="legacy",
        citekey="legacy",
        title="Legacy Paper",
        source_kind="scholar_labs",
        discovered_in=[legacy_ref],
        summary="Legacy run summary.",
    )

    from scholar_vault.importer import _save_card  # noqa: PLC0415

    _save_card(paths, card)

    rebuild_vault(vault)

    migrated = load_source_cards(initialize_vault(vault))[0]
    named_ref = _run_note_path(vault, run_id)
    assert migrated.discovered_in == [named_ref]
    assert migrated.summary_sources[0].run == named_ref
    assert (vault / named_ref).exists()
    assert not (run_dir / "index.md").exists()


def test_rebuild_shortens_previous_long_generated_run_note_names(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    paths = initialize_vault(vault)
    run_id = "2026-04-23_find-key-papers-on-collaborative-immersive-analytics-for-dat"
    prompt = (
        "Find key papers on collaborative immersive analytics for data visualization "
        "in virtual reality."
    )
    run_dir = paths.runs / run_id
    run_dir.mkdir(parents=True)
    write_yaml(
        run_dir / "index.yaml",
        RunRecord(
            slug=run_id,
            date="2026-04-23",
            prompt=prompt,
            exported_at="2026-04-23T16:00:00+02:00",
            export_file="/tmp/export.json",
            raw_export_file="raw/scholar-labs/example.json",
            result_count=0,
            results=[],
        ).model_dump(exclude_none=True),
    )
    (run_dir / f"{run_id}.md").write_text(
        "---\ntype: scholar_labs_run\nrun_id: "
        f"{run_id}\n---\n\n# Legacy long run note\n",
        encoding="utf-8",
    )

    rebuild_vault(vault)

    note = _run_note_path(vault, run_id)
    assert note.endswith("/Collaborative Immersive Analytics Data Visualization Virtual.md")
    assert (vault / note).exists()
    assert not (run_dir / f"{run_id}.md").exists()


def test_import_labs_archives_matched_pdfs_and_leaves_unmatched_in_staging(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    staging = tmp_path / "staging"
    exports = tmp_path / "exports"
    staging.mkdir()
    exports.mkdir()
    export_path = _write_fixture_copy("sample_scholar_labs_export.json", exports / "sample.json")
    matched_pdf = staging / "match.pdf"
    unmatched_pdf = staging / "unmatched.pdf"
    _write_pdf_with_title(matched_pdf, "Evaluating Retrieval Augmented Generation Systems")
    _write_pdf_with_title(unmatched_pdf, "Completely Different Source")

    summary = import_scholar_labs_run(
        vault,
        export_path,
        staging,
        commit=True,
        archive_matched=True,
    )
    manifest = _manifest_yaml(vault, str(summary["run"]))

    assert summary["archived"] == 1
    assert not matched_pdf.exists()
    assert unmatched_pdf.exists()
    accepted = [entry for entry in manifest["entries"] if entry.get("decision") == "accepted"]
    assert len(accepted) == 1
    assert accepted[0]["moved"] is True
    assert accepted[0]["archived_original_path"] is not None
    assert (vault / accepted[0]["archived_original_path"]).exists()


def test_import_labs_archives_used_export_json_and_updates_run_metadata(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    staging = tmp_path / "staging"
    exports = tmp_path / "exports"
    staging.mkdir()
    exports.mkdir()
    export_path = _write_fixture_copy("sample_scholar_labs_export.json", exports / "sample.json")
    _write_pdf_with_title(
        staging / "match.pdf",
        "Evaluating Retrieval Augmented Generation Systems",
    )

    summary = import_scholar_labs_run(
        vault,
        export_path,
        staging,
        commit=True,
        archive_matched=True,
        archive_export=True,
    )
    run_id = str(summary["run"])
    archived_export = Path(str(summary["export_archived"]))
    run_yaml = _run_yaml(vault, run_id)
    manifest = _manifest_yaml(vault, run_id)

    assert not export_path.exists()
    assert archived_export.parent == exports / "used"
    assert archived_export.name == export_path.name
    assert archived_export.exists()
    assert run_yaml["export_file"] == str(archived_export)
    assert manifest["export_file"] == str(archived_export)


def test_dry_run_does_not_archive_used_export_json(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    staging = tmp_path / "staging"
    exports = tmp_path / "exports"
    staging.mkdir()
    exports.mkdir()
    export_path = _write_fixture_copy("sample_scholar_labs_export.json", exports / "sample.json")

    summary = import_scholar_labs_run(
        vault,
        export_path,
        staging,
        dry_run=True,
        archive_matched=True,
        archive_export=True,
    )

    assert export_path.exists()
    assert summary["export_archived"] == ""


def test_rerun_updates_existing_run_with_newly_staged_matches(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    staging = tmp_path / "staging"
    exports = tmp_path / "exports"
    staging.mkdir()
    exports.mkdir()
    export_path = _write_export(exports / "sample.json", 3)
    _write_pdf_with_title(staging / "paper-1.pdf", "Result Paper 1")

    first = import_scholar_labs_run(
        vault,
        export_path,
        staging,
        commit=True,
        archive_matched=True,
        archive_export=True,
    )
    run_id = str(first["run"])

    _write_pdf_with_title(staging / "paper-2.pdf", "Result Paper 2")
    _write_pdf_with_title(staging / "paper-3.pdf", "Result Paper 3")

    second = resume_run(vault, run_id, commit=True)
    cards = load_source_cards(initialize_vault(vault))
    run_yaml = _run_yaml(vault, run_id)

    assert first["selected"] == 1
    assert second["selected"] == 3
    assert len(cards) == 3
    assert len([result for result in run_yaml["results"] if result["status"] == "selected"]) == 3
    assert list(staging.glob("*.pdf")) == []


def test_latest_run_id_uses_most_recent_manifest(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    staging = tmp_path / "staging"
    exports = tmp_path / "exports"
    staging.mkdir()
    exports.mkdir()
    first_export = _write_export(
        exports / "first.json",
        1,
        prompt="first scholar labs prompt about local archives",
        exported_at="2026-04-21T16:00:00+02:00",
    )
    second_export = _write_export(
        exports / "second.json",
        1,
        prompt="second scholar labs prompt about immersive analytics",
        exported_at="2026-04-22T16:00:00+02:00",
    )

    first = import_scholar_labs_run(vault, first_export, staging, commit=True)
    second = import_scholar_labs_run(vault, second_export, staging, commit=True)
    first_manifest = _manifest_yaml(vault, str(first["run"]))
    second_manifest = _manifest_yaml(vault, str(second["run"]))
    first_manifest["created_at"] = "2026-04-21T10:00:00+02:00"
    second_manifest["created_at"] = "2026-04-23T10:00:00+02:00"
    write_yaml(vault / "runs" / str(first["run"]) / "import-manifest.yaml", first_manifest)
    write_yaml(vault / "runs" / str(second["run"]) / "import-manifest.yaml", second_manifest)

    assert latest_run_id(vault) == second["run"]


def test_accepted_match_copies_pdf_and_manifest_records_it(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    staging = tmp_path / "staging"
    exports = tmp_path / "exports"
    staging.mkdir()
    exports.mkdir()
    export_path = _write_fixture_copy("sample_scholar_labs_export.json", exports / "sample.json")
    pdf_path = staging / "match.pdf"
    _write_pdf_with_title(pdf_path, "Evaluating Retrieval Augmented Generation Systems")

    summary = import_scholar_labs_run(vault, export_path, staging, commit=True)
    manifest = _manifest_yaml(vault, str(summary["run"]))
    cards = load_source_cards(initialize_vault(vault))

    assert len(cards) == 1
    assert pdf_path.exists()
    assert cards[0].pdf is not None
    assert (vault / cards[0].pdf).exists()
    accepted = [entry for entry in manifest["entries"] if entry.get("decision") == "accepted"]
    assert len(accepted) == 1
    assert accepted[0]["copied"] is True
    assert accepted[0]["verified"] is True


def test_undo_archives_created_state_and_preserves_staging_original(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    staging = tmp_path / "staging"
    exports = tmp_path / "exports"
    staging.mkdir()
    exports.mkdir()
    export_path = _write_fixture_copy("sample_scholar_labs_export.json", exports / "sample.json")
    pdf_path = staging / "match.pdf"
    _write_pdf_with_title(pdf_path, "Evaluating Retrieval Augmented Generation Systems")

    summary = import_scholar_labs_run(vault, export_path, staging, commit=True)
    run_id = str(summary["run"])
    undo_summary = undo_run(vault, run_id)
    cards = load_source_cards(initialize_vault(vault))

    assert undo_summary["archived_cards"] == 1
    assert undo_summary["archived_pdfs"] == 1
    assert cards == []
    assert not (vault / "runs" / run_id).exists()
    assert pdf_path.exists()
    assert list((vault / "raw" / "imported" / "undo-archive" / run_id / "papers").glob("*.md"))


def test_undo_restores_archived_original_for_import_labs_flow(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    staging = tmp_path / "staging"
    exports = tmp_path / "exports"
    staging.mkdir()
    exports.mkdir()
    export_path = _write_fixture_copy("sample_scholar_labs_export.json", exports / "sample.json")
    pdf_path = staging / "match.pdf"
    _write_pdf_with_title(pdf_path, "Evaluating Retrieval Augmented Generation Systems")

    summary = import_scholar_labs_run(
        vault,
        export_path,
        staging,
        commit=True,
        archive_matched=True,
    )
    run_id = str(summary["run"])

    assert not pdf_path.exists()

    undo_summary = undo_run(vault, run_id)

    assert undo_summary["restored_originals"] == 1
    assert pdf_path.exists()


def test_import_pdf_creates_stub_card_and_copies_pdf(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    staging = tmp_path / "staging"
    staging.mkdir()
    initialize_vault(vault)

    pdf_path = staging / "local-rag.pdf"
    _write_pdf_with_title(pdf_path, "Local Retrieval Augmented Generation")

    summary = import_pdf_dropins(vault, staging)
    cards = load_source_cards(initialize_vault(vault))

    assert summary["imported"] == 1
    assert len(cards) == 1
    assert cards[0].source_kind == "pdf_drop"
    assert cards[0].pdf_status == "attached"
    assert cards[0].pdf is not None
    assert (vault / cards[0].pdf).exists()


def test_invalid_empty_export_does_not_create_run_or_papers(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    staging = tmp_path / "staging"
    exports = tmp_path / "exports"
    staging.mkdir()
    exports.mkdir()
    export_path = _write_fixture_copy(
        "failed_empty_scholar_labs_export.json",
        exports / "failed.json",
    )

    try:
        import_scholar_labs_run(vault, export_path, staging)
    except ValueError as exc:
        assert "wrong page" in str(exc) or "selectors are broken" in str(exc)
    else:
        raise AssertionError("Invalid export should not import successfully.")

    paths = initialize_vault(vault)

    assert list(paths.papers.glob("*.md")) == []
    assert list(paths.runs.glob("*/index.yaml")) == []
    assert list(paths.raw_scholar_labs.glob("invalid-*.json")) != []


def test_cleanup_run_selected_only_archives_candidate_only_cards(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    paths = initialize_vault(vault)
    run_id = "2026-04-22_cleanup-example"
    run_ref = f"runs/{run_id}/index.md"

    attached_card = SourceCard(
        slug="attached-card",
        citekey="attachedcard",
        title="Attached Card",
        source_kind="scholar_labs",
        discovered_in=[run_ref],
        pdf="pdfs/attached-card.pdf",
        pdf_status="attached",
    )
    candidate_card = SourceCard(
        slug="candidate-card",
        citekey="candidatecard",
        title="Candidate Card",
        source_kind="scholar_labs",
        discovered_in=[run_ref],
        pdf_status="missing",
        status="candidate",
        citation_status="missing",
    )
    _write_pdf_with_title(paths.pdfs / "attached-card.pdf", "Attached Card")
    write_yaml(
        paths.runs / run_id / "index.yaml",
        RunRecord(
            slug=run_id,
            date="2026-04-22",
            prompt="cleanup example",
            exported_at="2026-04-22T16:00:00+02:00",
            export_file="/tmp/export.json",
            raw_export_file="raw/scholar-labs/example.json",
            result_count=2,
            results=[
                RunResultRecord(
                    **ScholarLabsResult(
                        rank=1, scholar_cid="cid-a", title="Attached Card"
                    ).model_dump(),
                ),
                RunResultRecord(
                    **ScholarLabsResult(
                        rank=2, scholar_cid="cid-b", title="Candidate Card"
                    ).model_dump(),
                ),
            ],
        ).model_dump(exclude_none=True),
    )
    write_yaml(
        paths.runs / run_id / "import-manifest.yaml",
        {
            "run_id": run_id,
            "export_file": "/tmp/export.json",
            "staging_folder": "/tmp/staging",
            "created_at": "2026-04-22T16:00:00+02:00",
            "entries": [],
        },
    )

    from scholar_vault.importer import _save_card  # noqa: PLC0415

    _save_card(paths, attached_card)
    _save_card(paths, candidate_card)

    summary = cleanup_run_selected_only(vault, run_id)
    cards = load_source_cards(initialize_vault(vault))
    run_yaml = _run_yaml(vault, run_id)

    assert summary["archived"] == 1
    assert len(cards) == 1
    assert cards[0].slug == "attached-card"
    assert run_yaml["results"][0]["status"] == "selected"
    assert run_yaml["results"][1]["status"] == "candidate"
    assert list((paths.raw_imported / "cleanup-archive" / run_id).glob("*.md"))


def test_reset_vault_restores_init_like_state(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    staging = tmp_path / "staging"
    exports = tmp_path / "exports"
    staging.mkdir()
    exports.mkdir()
    export_path = _write_fixture_copy("sample_scholar_labs_export.json", exports / "sample.json")
    _write_pdf_with_title(
        staging / "match.pdf", "Evaluating Retrieval Augmented Generation Systems"
    )

    initialize_vault(vault)
    import_scholar_labs_run(vault, export_path, staging, commit=True)

    paths_before = initialize_vault(vault)
    assert list(paths_before.papers.glob("*.md")) != []
    assert list(paths_before.runs.glob("*/index.yaml")) != []

    summary = reset_vault(vault)
    paths_after = initialize_vault(vault)

    assert summary["removed"] > 0
    assert list(paths_after.papers.glob("*.md")) == []
    assert list(paths_after.runs.glob("*/index.yaml")) == []
    assert list(paths_after.pdfs.glob("*.pdf")) == []
    assert list(paths_after.raw_scholar_labs.glob("*.json")) == []
    assert (paths_after.indexes / "papers.md").exists()
    assert (paths_after.exports / "library.bib").exists()
    assert (paths_after.vault / "llms.txt").exists()
