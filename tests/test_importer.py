from __future__ import annotations

import json
from pathlib import Path

import yaml
from pypdf import PdfWriter

from scholar_vault.citations import EnrichmentResult
from scholar_vault.importer import (
    PDF_SCAN_CACHE_FILENAME,
    apply_topic_map,
    cleanup_run_selected_only,
    concept_index,
    confirm_no_publication_keywords,
    doctor_vault,
    enrich_vault,
    find_staged_run_matches,
    import_bibtex,
    import_pdf_dropins,
    import_scholar_labs_run,
    import_staged_pdf_match,
    initialize_vault,
    latest_run_id,
    maintenance_report,
    notes_missing,
    pdf_doctor,
    project_audit,
    project_link_concept,
    project_link_paper,
    project_link_proposal,
    project_link_synthesis,
    project_link_task,
    project_map,
    project_scaffold,
    proposal_audit,
    proposal_sprint_scaffold,
    rebuild_vault,
    rename_run,
    reset_vault,
    resume_run,
    set_manual_abstract,
    set_manual_keywords,
    set_manual_metadata,
    topic_map_report,
    undo_run,
)
from scholar_vault.models import (
    MatchReviewAbort,
    PdfCandidate,
    RunRecord,
    RunResultRecord,
    ScholarLabsResult,
    SourceCard,
)
from scholar_vault.render import render_paper_markdown, render_vault_agents
from scholar_vault.sources import (
    VaultPaths,
    dump_frontmatter,
    load_source_cards,
    read_frontmatter_markdown,
    run_note_path,
    write_yaml,
)


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


def test_enrich_vault_runs_all_enrichment_queues_by_default(tmp_path, monkeypatch) -> None:
    from scholar_vault.importer import _save_card  # noqa: PLC0415

    vault = tmp_path / "vault"
    paths = initialize_vault(vault)
    _save_card(paths, SourceCard(slug="source", citekey="source", title="Source"))
    calls: list[tuple[str, bool, bool, bool]] = []

    def fake_enrich_cards(_paths, cards, options, **_kwargs):
        calls.append((options.only, options.abstracts, options.refresh, options.refresh_abstracts))
        status = (
            "resolved"
            if options.abstracts or options.only == "missing-keywords"
            else "verified"
        )
        return [
            EnrichmentResult(
                card.citekey or card.slug,
                status,
                "ok",
            )
            for card in cards
        ]

    monkeypatch.setattr("scholar_vault.enrichment.enrich_cards", fake_enrich_cards)

    summary = enrich_vault(vault, refresh=True, refresh_abstracts=True, dry_run=True)

    assert calls == [
        ("all", False, True, False),
        ("all", True, False, True),
        ("missing-keywords", False, True, False),
    ]
    assert summary["citation_enrichment"]["processed"] == 1
    assert summary["abstract_enrichment"]["processed"] == 1
    assert summary["keyword_enrichment"]["processed"] == 1


def test_enrich_vault_only_filters_to_keyword_queue(tmp_path, monkeypatch) -> None:
    from scholar_vault.importer import _save_card  # noqa: PLC0415

    vault = tmp_path / "vault"
    paths = initialize_vault(vault)
    _save_card(paths, SourceCard(slug="source", citekey="source", title="Source"))
    calls: list[tuple[str, list[str]]] = []

    def fake_enrich_cards(_paths, cards, options, **_kwargs):
        calls.append((options.only, [card.slug for card in cards]))
        return [
            EnrichmentResult(
                card.citekey or card.slug,
                "unresolved",
                "no keywords found in attached PDF",
                missing_fields=("keywords",),
            )
            for card in cards
        ]

    monkeypatch.setattr("scholar_vault.enrichment.enrich_cards", fake_enrich_cards)

    summary = enrich_vault(vault, citekey="source", only="missing-keywords", dry_run=True)

    assert calls == [("missing-keywords", ["source"])]
    assert summary["citation_enrichment"]["processed"] == 0
    assert summary["abstract_enrichment"]["processed"] == 0
    assert summary["keyword_enrichment"]["unresolved"] == 1


def test_doctor_vault_reports_metadata_topic_and_pdf_issues(tmp_path: Path) -> None:
    from scholar_vault.importer import _save_card  # noqa: PLC0415

    vault = tmp_path / "vault"
    paths = initialize_vault(vault)
    attached_pdf = paths.pdfs / "attached.pdf"
    attached_pdf.write_bytes(b"%PDF-1.4 attached\n")
    duplicate_pdf = paths.pdfs / "attached-2.pdf"
    duplicate_pdf.write_bytes(b"%PDF-1.4 attached\n")
    _save_card(
        paths,
        SourceCard(
            slug="ambiguous",
            citekey="ambiguous",
            title="Ambiguous Paper",
            pdf="pdfs/attached.pdf",
            pdf_status="attached",
            topics=["Find", "Mobility"],
            citation_status="ambiguous",
            doi_status="ambiguous",
            enrichment_status="ambiguous",
            publication_keywords_status="missing",
        ),
    )
    _save_card(
        paths,
        SourceCard(
            slug="incomplete",
            citekey="incomplete",
            title="Incomplete Paper",
            topics=["Papers"],
            enrichment_status="incomplete",
            enrichment_missing=["venue"],
        ),
    )

    summary = doctor_vault(vault)

    assert summary["counts"]["paper_cards"] == 2
    assert summary["issue_counts"]["ambiguous_citations"] == 1
    assert summary["issue_counts"]["incomplete_enrichment"] == 1
    assert summary["issue_counts"]["missing_keywords"] == 1
    assert summary["topics"]["noisy"][0]["topic"] == "Find"
    assert summary["pdfs"]["duplicate_style_filenames"] == ["pdfs/attached-2.pdf"]
    assert summary["pdfs"]["orphan_pdfs"] == ["pdfs/attached-2.pdf"]


def test_rebuild_refreshes_stale_enrichment_completeness(tmp_path: Path) -> None:
    from scholar_vault.importer import _save_card  # noqa: PLC0415

    vault = tmp_path / "vault"
    paths = initialize_vault(vault)
    _save_card(
        paths,
        SourceCard(
            slug="verified",
            citekey="verified",
            title="Verified Paper",
            doi="10.1145/example",
            authors=["Jane Smith"],
            year=2024,
            venue="Example Venue",
            citation_status="verified",
            enrichment_status="missing",
        ),
    )

    summary = doctor_vault(vault)
    rebuild_vault(vault)
    saved = load_source_cards(paths)[0]

    assert summary["status_counts"]["enrichment_status"]["complete"] == 1
    assert saved.enrichment_status == "complete"
    assert saved.enrichment_missing == []


def test_pdf_doctor_reports_staging_duplicates_and_repeated_unmatched(
    tmp_path: Path,
) -> None:
    from scholar_vault.importer import _write_manifest  # noqa: PLC0415
    from scholar_vault.models import ImportManifest, ImportManifestEntry  # noqa: PLC0415

    vault = tmp_path / "vault"
    staging = tmp_path / "staging"
    staging.mkdir()
    paths = initialize_vault(vault)
    vault_pdf = paths.pdfs / "source.pdf"
    vault_pdf.write_bytes(b"%PDF-1.4 source\n")
    staged_pdf = staging / "source-copy.pdf"
    staged_pdf.write_bytes(b"%PDF-1.4 source\n")
    for run_id in ["run-a", "run-b"]:
        _write_manifest(
            paths,
            ImportManifest(
                run_id=run_id,
                export_file="/tmp/export.json",
                staging_folder=str(staging),
                created_at="2026-04-28T10:00:00+02:00",
                entries=[
                    ImportManifestEntry(
                        original_path=str(staging / "repeat.pdf"),
                        decision="unresolved",
                        score=72,
                    )
                ],
            ),
        )

    summary = pdf_doctor(vault, staging_path=staging)

    assert summary["staging"]["pdf_count"] == 1
    assert summary["staging"]["duplicates_in_vault"][0]["staging_pdf"] == str(staged_pdf)
    assert summary["repeated_unmatched_files"][0]["filename"] == "repeat.pdf"
    assert summary["repeated_unmatched_files"][0]["count"] == 2


def test_topic_map_dry_run_and_apply(tmp_path: Path) -> None:
    from scholar_vault.importer import _save_card  # noqa: PLC0415

    vault = tmp_path / "vault"
    paths = initialize_vault(vault)
    _save_card(
        paths,
        SourceCard(
            slug="source",
            citekey="source",
            title="Source",
            topics=["Find", "OD Flows", "Papers"],
        ),
    )

    report = topic_map_report(vault)
    dry_run = apply_topic_map(
        vault,
        {"Find": None, "Papers": None, "OD Flows": "Origin-Destination Flows"},
    )
    unchanged = load_source_cards(initialize_vault(vault))[0]
    applied = apply_topic_map(
        vault,
        {"Find": None, "Papers": None, "OD Flows": "Origin-Destination Flows"},
        apply=True,
    )
    changed = load_source_cards(initialize_vault(vault))[0]

    assert any(row["topic"] == "Find" for row in report["noisy"])
    assert dry_run["applied"] is False
    assert dry_run["changed_cards"] == 1
    assert unchanged.topics == ["Find", "OD Flows", "Papers"]
    assert applied["applied"] is True
    assert changed.topics == ["Origin-Destination Flows"]


def _write_export(
    path: Path,
    result_count: int,
    *,
    prompt: str = "retrieval augmented generation evaluation with grounded evidence",
    exported_at: str = "2026-04-22T16:00:00+02:00",
    title: str | None = None,
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
    if title is not None:
        payload["title"] = title
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


def test_import_run_strips_scholar_resource_labels_from_titles(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    staging = tmp_path / "staging"
    exports = tmp_path / "exports"
    staging.mkdir()
    exports.mkdir()
    export_path = _rewrite_export(
        _write_export(exports / "sample.json", 1),
        result_updates={"title": "[PDF][PDF] A Survey on Interactive Lenses"},
    )
    _write_pdf_with_title(staging / "paper-1.pdf", "A Survey on Interactive Lenses")

    import_scholar_labs_run(vault, export_path, staging, commit=True)
    cards = load_source_cards(initialize_vault(vault))
    run_id = latest_run_id(vault)
    run_yaml = _run_yaml(vault, run_id)

    assert cards[0].title == "A Survey on Interactive Lenses"
    assert "[PDF]" not in cards[0].citekey
    assert "pdfpdf" not in str(cards[0].citekey)
    assert run_yaml["results"][0]["title"] == "A Survey on Interactive Lenses"


def test_import_run_uses_export_title_for_run_note(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    staging = tmp_path / "staging"
    exports = tmp_path / "exports"
    staging.mkdir()
    exports.mkdir()
    export_path = _write_export(exports / "sample.json", 1, title="Curated Mobility Sources")
    _write_pdf_with_title(staging / "paper-1.pdf", "Result Paper 1")

    summary = import_scholar_labs_run(vault, export_path, staging, commit=True)
    run_id = str(summary["run"])
    run_yaml = _run_yaml(vault, run_id)

    assert run_yaml["title"] == "Curated Mobility Sources"
    assert (vault / "runs" / run_id / "Curated Mobility Sources.md").exists()


def test_import_run_reuses_staged_pdf_scan_cache(tmp_path: Path, monkeypatch) -> None:
    vault = tmp_path / "vault"
    staging = tmp_path / "staging"
    exports = tmp_path / "exports"
    staging.mkdir()
    exports.mkdir()
    export_path = _write_export(exports / "sample.json", 1)
    _write_pdf_with_title(staging / "paper-1.pdf", "Result Paper 1")

    import_scholar_labs_run(vault, export_path, staging, commit=True)
    cache_path = staging / PDF_SCAN_CACHE_FILENAME

    assert cache_path.exists()

    def fail_build(_path: Path) -> PdfCandidate:
        raise AssertionError("cached PDF scan should be reused")

    monkeypatch.setattr("scholar_vault.importer.build_pdf_candidate", fail_build)

    summary = import_scholar_labs_run(vault, export_path, staging, commit=True)

    assert summary["decision_summary"]["staged_pdf_cache_hits"] == 1


def test_import_run_refreshes_stale_pdf_scan_cache(tmp_path: Path, monkeypatch) -> None:
    vault = tmp_path / "vault"
    staging = tmp_path / "staging"
    exports = tmp_path / "exports"
    staging.mkdir()
    exports.mkdir()
    export_path = _write_export(exports / "sample.json", 1)
    pdf_path = staging / "paper-1.pdf"
    _write_pdf_with_title(pdf_path, "Result Paper 1")

    import_scholar_labs_run(vault, export_path, staging, commit=True)
    pdf_path.write_bytes(pdf_path.read_bytes() + b"\n% changed")
    calls = []

    def fake_build(path: Path) -> PdfCandidate:
        calls.append(path)
        return PdfCandidate(
            path=str(path),
            title="Result Paper 1",
            doi=None,
            year=2024,
            text_excerpt="",
            metadata={},
            sha256="changed",
            size=path.stat().st_size,
        )

    monkeypatch.setattr("scholar_vault.importer.build_pdf_candidate", fake_build)

    summary = import_scholar_labs_run(vault, export_path, staging, commit=True)

    assert calls == [pdf_path]
    assert summary["decision_summary"]["staged_pdf_cache_hits"] == 0


def test_resume_promotes_export_title_when_existing_title_was_inferred(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    staging = tmp_path / "staging"
    exports = tmp_path / "exports"
    staging.mkdir()
    exports.mkdir()
    export_path = _write_export(exports / "sample.json", 1)
    _write_pdf_with_title(staging / "paper-1.pdf", "Result Paper 1")

    first = import_scholar_labs_run(vault, export_path, staging, commit=True)
    run_id = str(first["run"])
    _rewrite_export(export_path, title="Curated Rerun Sources")

    resume_run(vault, run_id, commit=True)
    run_yaml = _run_yaml(vault, run_id)

    assert run_yaml["title"] == "Curated Rerun Sources"
    assert (vault / "runs" / run_id / "Curated Rerun Sources.md").exists()


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


def test_reimport_reuses_prior_selected_matches_without_review(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    staging = tmp_path / "staging"
    exports = tmp_path / "exports"
    staging.mkdir()
    exports.mkdir()
    export_path = _write_export(exports / "sample.json", 1)
    _write_pdf_with_title(staging / "paper-1.pdf", "Result Paper 1")

    first = import_scholar_labs_run(vault, export_path, staging, commit=True)

    def fail_review(_request):
        raise AssertionError("Previously selected matches should not be reviewed again.")

    second = import_scholar_labs_run(
        vault,
        export_path,
        staging,
        confirm=lambda _prompt: True,
        review_match=fail_review,
    )

    assert first["selected"] == 1
    assert second["selected"] == 1
    assert second["decision_summary"]["existing_run"] is True
    assert second["decision_summary"]["prior_selected_reused"] == 1
    assert second["decision_summary"]["new_staged_pdf_matches"] == 0
    assert second["decision_summary"]["review_prompts"] == 0


def test_reimport_can_upgrade_prior_selected_pdf(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    staging = tmp_path / "staging"
    exports = tmp_path / "exports"
    staging.mkdir()
    exports.mkdir()
    export_path = _write_export(exports / "sample.json", 1)
    old_pdf = staging / "paper-1-preprint.pdf"
    _write_pdf_with_title(old_pdf, "Result Paper 1")

    first = import_scholar_labs_run(vault, export_path, staging, commit=True)
    card = load_source_cards(initialize_vault(vault))[0]
    first_pdf = card.pdf

    better_pdf = staging / "paper-1-published.pdf"
    _write_pdf_with_title(better_pdf, "Result Paper 1 Published Version")
    requests = []

    def review_match(request):
        requests.append(request)
        return True

    second = import_scholar_labs_run(
        vault,
        export_path,
        staging,
        upgrade_pdfs=True,
        review_match=review_match,
    )
    upgraded = load_source_cards(initialize_vault(vault))[0]
    run_id = str(second["run"])
    run_yaml = _run_yaml(vault, run_id)
    manifest = _manifest_yaml(vault, run_id)

    assert first["selected"] == 1
    assert requests
    assert requests[0].pdf_filename == "paper-1-published.pdf"
    assert upgraded.pdf != first_pdf
    assert upgraded.pdf_status == "attached"
    assert upgraded.enrichment_refresh is True
    assert second["decision_summary"]["pdf_upgrades"] == 1
    assert second["decision_summary"]["prior_selected_reused"] == 0
    assert run_yaml["results"][0]["proposed_pdf"] == str(better_pdf)
    assert manifest["entries"][0]["card_preexisting"] is True
    assert manifest["entries"][0]["card_before"]["pdf"] == first_pdf


def test_structured_match_review_accepts_pdf(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    staging = tmp_path / "staging"
    exports = tmp_path / "exports"
    staging.mkdir()
    exports.mkdir()
    export_path = _write_fixture_copy("sample_scholar_labs_export.json", exports / "sample.json")
    pdf_path = staging / "match.pdf"
    _write_pdf_with_title(pdf_path, "Evaluating Retrieval Augmented Generation Systems")
    requests = []

    def review_match(request):
        requests.append(request)
        return True

    summary = import_scholar_labs_run(
        vault,
        export_path,
        staging,
        review_match=review_match,
    )
    manifest = _manifest_yaml(vault, str(summary["run"]))
    cards = load_source_cards(initialize_vault(vault))

    assert len(requests) == 1
    assert requests[0].result_title == "Evaluating Retrieval Augmented Generation Systems"
    assert requests[0].pdf_filename == "match.pdf"
    assert requests[0].score == 100
    assert requests[0].match_reason == "title"
    assert requests[0].inferred_title == "Evaluating Retrieval Augmented Generation Systems"
    assert len(cards) == 1
    assert any(entry.get("decision") == "accepted" for entry in manifest["entries"])


def test_match_review_abort_stops_before_enrichment(tmp_path: Path, monkeypatch) -> None:
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

    def review_match(_request):
        raise MatchReviewAbort("Import aborted from match review.")

    def fail_enrich(*_args, **_kwargs):
        raise AssertionError("Abort must stop before enrichment.")

    monkeypatch.setattr("scholar_vault.importer.enrich_cards", fail_enrich)

    try:
        import_scholar_labs_run(
            vault,
            export_path,
            staging,
            review_match=review_match,
            auto_enrich=True,
        )
    except MatchReviewAbort:
        pass
    else:
        raise AssertionError("Import should abort immediately.")

    cards = load_source_cards(initialize_vault(vault))
    assert cards == []


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


def test_rebuild_rerenders_existing_paper_cards_with_latest_template(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    paths = initialize_vault(vault)
    card = SourceCard(
        slug="quick-access",
        citekey="quickaccess",
        title="Quick Access Paper",
        pdf="pdfs/quick-access.pdf",
        pdf_status="attached",
        summary="A summary.",
    )
    _write_pdf_with_title(paths.pdfs / "quick-access.pdf", "Quick Access Paper")
    stale = render_without_quick_access(card)
    (paths.papers / "quick-access.md").write_text(stale, encoding="utf-8")

    summary = rebuild_vault(vault)

    rendered = (paths.papers / "quick-access.md").read_text(encoding="utf-8")
    assert summary["papers"] == 1
    assert summary["paper_cards_written"] == 1
    assert summary["index_files_written"] == 22
    assert summary["export_files_written"] == 4
    assert "## Quick access" in rendered
    assert "[Open local PDF](../pdfs/quick-access.pdf)" in rendered


def test_rebuild_exports_library_with_list_valued_cached_csl(tmp_path: Path) -> None:
    from scholar_vault.importer import _save_card  # noqa: PLC0415

    vault = tmp_path / "vault"
    paths = initialize_vault(vault)
    _save_card(
        paths,
        SourceCard(
            slug="list-csl",
            citekey="listcsl",
            title="List Valued CSL Metadata",
            citation_status="verified",
        ),
    )
    cache_dir = paths.raw_metadata / "listcsl"
    cache_dir.mkdir(parents=True)
    (cache_dir / "citation.csl.json").write_text(
        json.dumps(
            {
                "type": ["article-journal"],
                "title": ["List Valued CSL Metadata"],
                "author": [{"given": ["Ada"], "family": ["Lee"]}],
                "container-title": ["Journal of Test Results"],
                "ISSN": ["1234-5678", "8765-4321"],
                "issued": {"date-parts": [[2025]]},
            }
        ),
        encoding="utf-8",
    )

    rebuild_vault(vault)

    library = (paths.exports / "library.bib").read_text(encoding="utf-8")
    assert "@article{listcsl," in library
    assert "journaltitle = {Journal of Test Results}" in library
    assert "issn = {1234-5678, 8765-4321}" in library


def test_initialize_vault_writes_full_agents_template(tmp_path: Path) -> None:
    vault = tmp_path / "vault"

    paths = initialize_vault(vault)
    agents = (paths.vault / "AGENTS.md").read_text(encoding="utf-8")
    template = (Path(__file__).parents[1] / "VAULT_AGENTS_TEMPLATE.md").read_text(
        encoding="utf-8"
    )

    assert agents.startswith("# Scholar Vault Agent Notes")
    assert render_vault_agents() == template.rstrip() + "\n"
    assert agents == render_vault_agents()
    assert "Linked `pdfs/*.pdf` files are the canonical evidence artifacts." in agents
    assert "skills adopt AGENTS.md" in agents
    assert 'scholar-vault notes-missing --heading "PDF reading notes"' in agents
    assert "scholar-vault project scaffold <slug>" in agents
    assert "Projects are lenses over the shared vault" in agents
    assert "scholar-vault proposal-sprint scaffold <slug>" in agents
    assert "scholar-vault proposal-audit proposals/<slug>" in agents
    assert "$scholar-vault-research-loop" in agents


def test_rebuild_indexes_research_artifacts(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    paths = initialize_vault(vault)
    (paths.concepts / "flow-maps.md").write_text(
        (
            "---\n"
            "type: concept\n"
            "title: Flow Maps\n"
            "sources:\n"
            "  - papers/source.md\n"
            "---\n\n"
            "# Flow Maps\n"
        ),
        encoding="utf-8",
    )
    (paths.syntheses / "od-flow.md").write_text("# OD-flow Synthesis\n", encoding="utf-8")
    (paths.projects / "map-lens-deformation").mkdir(parents=True)
    (paths.projects / "map-lens-deformation" / "index.md").write_text(
        (
            "---\n"
            "type: project\n"
            "title: Map Lens Deformation\n"
            "slug: map-lens-deformation\n"
            "---\n\n"
            "# Map Lens Deformation\n"
        ),
        encoding="utf-8",
    )
    (paths.proposals / "pepr-mobidec").mkdir(parents=True)
    (paths.proposals / "pepr-mobidec" / "outline.md").write_text(
        "# Proposal Outline\n",
        encoding="utf-8",
    )

    rebuild_vault(vault)

    concepts_index = (paths.indexes / "concepts.md").read_text(encoding="utf-8")
    syntheses_index = (paths.indexes / "syntheses.md").read_text(encoding="utf-8")
    projects_index = (paths.indexes / "projects.md").read_text(encoding="utf-8")
    proposals_index = (paths.indexes / "proposals.md").read_text(encoding="utf-8")
    dashboard = (paths.indexes / "dashboard.md").read_text(encoding="utf-8")
    llms = (paths.vault / "llms.txt").read_text(encoding="utf-8")
    llms_full = (paths.vault / "llms-full.txt").read_text(encoding="utf-8")

    assert "[Flow Maps](../concepts/flow-maps.md)" in concepts_index
    assert "[OD-flow Synthesis](../syntheses/od-flow.md)" in syntheses_index
    assert "[Map Lens Deformation](../projects/map-lens-deformation/index.md)" in projects_index
    assert "[Proposal Outline](../proposals/pepr-mobidec/outline.md)" in proposals_index
    assert "[Projects](projects.md)" in dashboard
    assert "| Projects | 1 |" in dashboard
    assert "_indexes/concepts.md" in llms
    assert "_indexes/projects.md" in llms
    assert "Concepts:" in llms_full
    assert "Projects:" in llms_full


def test_project_scaffold_creates_valid_workspace(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    paths = initialize_vault(vault)

    summary = project_scaffold(vault, "map-lens-deformation")
    project_path = paths.projects / "map-lens-deformation" / "index.md"
    frontmatter, body = read_frontmatter_markdown(project_path)
    projects_index = (paths.indexes / "projects.md").read_text(encoding="utf-8")

    assert summary["project"] == "projects/map-lens-deformation/index.md"
    assert summary["state"] == "created"
    assert frontmatter["type"] == "project"
    assert frontmatter["slug"] == "map-lens-deformation"
    assert frontmatter["status"] == "active"
    assert frontmatter["related_papers"] == []
    assert frontmatter["related_proposals"] == []
    assert "## Goal" in body
    assert "## Linked sources" in body
    assert "[Map Lens Deformation](../projects/map-lens-deformation/index.md)" in projects_index


def test_project_scaffold_and_link_do_not_rewrite_paper_cards(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    paths = initialize_vault(vault)
    paper = SourceCard(
        slug="side-effect-paper",
        citekey="SideEffect2026",
        title="Side Effect Paper",
    )
    paper_path = paths.papers / "side-effect-paper.md"
    original_text = (
        f"---\n{dump_frontmatter(paper.frontmatter()).strip()}\n---\n\n"
        "# Side Effect Paper\n\n"
        "## Notes\n\n"
        "Custom body that should not be normalized by project commands.\n"
    )
    paper_path.write_text(original_text, encoding="utf-8")

    project_scaffold(vault, "map-lens-deformation")
    project_link_paper(vault, "map-lens-deformation", "SideEffect2026")

    assert paper_path.read_text(encoding="utf-8") == original_text


def test_project_link_paper_is_idempotent(tmp_path: Path) -> None:
    from scholar_vault.importer import _save_card  # noqa: PLC0415

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
    project_scaffold(vault, "map-lens-deformation")

    first = project_link_paper(
        vault,
        "map-lens-deformation",
        "Schottler2021_GeospatialNetworks",
    )
    second = project_link_paper(
        vault,
        "map-lens-deformation",
        "Schottler2021_GeospatialNetworks",
    )
    frontmatter, body = read_frontmatter_markdown(
        paths.projects / "map-lens-deformation" / "index.md"
    )

    assert first["changed"] is True
    assert second["changed"] is False
    assert frontmatter["related_papers"] == ["papers/geospatial-networks.md"]
    assert body.count("- [papers/geospatial-networks.md]") == 1


def test_project_link_concept_is_idempotent(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    paths = initialize_vault(vault)
    (paths.concepts / "flow-maps.md").write_text("# Flow Maps\n", encoding="utf-8")
    project_scaffold(vault, "map-lens-deformation")

    first = project_link_concept(vault, "map-lens-deformation", "flow-maps")
    second = project_link_concept(vault, "map-lens-deformation", "flow-maps")
    frontmatter, body = read_frontmatter_markdown(
        paths.projects / "map-lens-deformation" / "index.md"
    )

    assert first["changed"] is True
    assert second["changed"] is False
    assert frontmatter["related_concepts"] == ["concepts/flow-maps.md"]
    assert body.count("- [concepts/flow-maps.md]") == 1


def test_project_map_renders_linked_records(tmp_path: Path) -> None:
    from scholar_vault.importer import _save_card  # noqa: PLC0415

    vault = tmp_path / "vault"
    paths = initialize_vault(vault)
    _write_pdf_with_title(paths.pdfs / "flow.pdf", "Flow Paper")
    _save_card(
        paths,
        SourceCard(
            slug="flow-paper",
            citekey="Flow2026",
            title="Flow Paper",
            pdf="pdfs/flow.pdf",
            pdf_status="attached",
            enrichment_status="complete",
            notes="### PDF reading notes\nRead notes.",
        ),
    )
    (paths.concepts / "flow-maps.md").write_text("# Flow Maps\n", encoding="utf-8")
    (paths.syntheses / "flow-synthesis.md").write_text(
        "# Flow Synthesis\n",
        encoding="utf-8",
    )
    (paths.tasks / "flow-task.md").write_text("# Flow Task\n", encoding="utf-8")
    project_scaffold(vault, "map-lens-deformation")
    project_link_paper(vault, "map-lens-deformation", "Flow2026")
    project_link_concept(vault, "map-lens-deformation", "flow-maps")
    project_link_synthesis(vault, "map-lens-deformation", "flow-synthesis")
    project_link_task(vault, "map-lens-deformation", "flow-task")

    summary = project_map(vault, "map-lens-deformation")
    text = (paths.projects / "map-lens-deformation" / "project-map.md").read_text(
        encoding="utf-8"
    )

    assert summary["project_map"] == "projects/map-lens-deformation/project-map.md"
    assert "Flow Paper" in text
    assert "Flow2026" in text
    assert "attached" in text
    assert "present" in text
    assert "Flow Maps" in text
    assert "Flow Synthesis" in text
    assert "Flow Task" in text


def test_project_map_renders_related_proposals(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    paths = initialize_vault(vault)
    proposal = paths.proposals / "pepr-mobidec"
    proposal.mkdir(parents=True)
    (proposal / "index.md").write_text(
        "---\ntype: proposal\ntitle: PEPR Mobidec\n---\n\n# PEPR Mobidec\n",
        encoding="utf-8",
    )
    project_scaffold(vault, "map-lens-deformation")
    project_path = paths.projects / "map-lens-deformation" / "index.md"
    frontmatter, body = read_frontmatter_markdown(project_path)
    frontmatter["related_proposals"] = ["proposals/pepr-mobidec"]
    project_path.write_text(
        f"---\n{dump_frontmatter(frontmatter).strip()}\n---\n\n{body}",
        encoding="utf-8",
    )

    project_map(vault, "map-lens-deformation")
    text = (paths.projects / "map-lens-deformation" / "project-map.md").read_text(
        encoding="utf-8"
    )

    assert "## Linked proposals" in text
    assert "PEPR Mobidec" in text
    assert "../../proposals/pepr-mobidec" in text


def test_project_link_proposal_is_idempotent(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    paths = initialize_vault(vault)
    proposal = paths.proposals / "pepr-mobidec"
    proposal.mkdir(parents=True)
    (proposal / "index.md").write_text(
        "---\ntype: proposal\ntitle: PEPR Mobidec\n---\n\n# PEPR Mobidec\n",
        encoding="utf-8",
    )
    project_scaffold(vault, "map-lens-deformation")

    first = project_link_proposal(vault, "map-lens-deformation", "pepr-mobidec")
    second = project_link_proposal(vault, "map-lens-deformation", "proposals/pepr-mobidec")
    frontmatter, body = read_frontmatter_markdown(
        paths.projects / "map-lens-deformation" / "index.md"
    )

    assert first["changed"] is True
    assert second["changed"] is False
    assert frontmatter["related_proposals"] == ["proposals/pepr-mobidec"]
    assert body.count("- [proposals/pepr-mobidec](../../proposals/pepr-mobidec)") == 1


def test_project_audit_detects_missing_linked_paper(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    paths = initialize_vault(vault)
    project_scaffold(vault, "map-lens-deformation")
    project_path = paths.projects / "map-lens-deformation" / "index.md"
    frontmatter, body = read_frontmatter_markdown(project_path)
    frontmatter["related_papers"] = ["papers/missing.md"]
    frontmatter["updated"] = "2026-05-13T12:00:00+02:00"
    project_path.write_text(
        f"---\n{dump_frontmatter(frontmatter).strip()}\n---\n\n{body}",
        encoding="utf-8",
    )

    summary = project_audit(vault, "map-lens-deformation")

    assert summary["ok"] is False
    assert summary["issue_counts"]["missing_linked_papers"] == 1
    assert summary["issues"]["missing_linked_papers"][0]["paper"] == "papers/missing.md"


def test_project_audit_detects_missing_related_proposal(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    paths = initialize_vault(vault)
    project_scaffold(vault, "map-lens-deformation")
    project_path = paths.projects / "map-lens-deformation" / "index.md"
    frontmatter, body = read_frontmatter_markdown(project_path)
    frontmatter["related_proposals"] = ["proposals/missing-proposal"]
    project_path.write_text(
        f"---\n{dump_frontmatter(frontmatter).strip()}\n---\n\n{body}",
        encoding="utf-8",
    )

    summary = project_audit(vault, "map-lens-deformation")

    assert summary["ok"] is False
    assert summary["issue_counts"]["missing_linked_proposals"] == 1
    assert summary["issues"]["missing_linked_proposals"][0]["target"] == (
        "proposals/missing-proposal"
    )


def test_maintenance_report_writes_index_and_task(tmp_path: Path) -> None:
    from scholar_vault.importer import _save_card  # noqa: PLC0415

    vault = tmp_path / "vault"
    paths = initialize_vault(vault)
    _write_pdf_with_title(paths.pdfs / "unread.pdf", "Unread Paper")
    _save_card(
        paths,
        SourceCard(
            slug="unread",
            citekey="unread",
            title="Unread Paper",
            pdf="pdfs/unread.pdf",
            pdf_status="attached",
            topics=["Find", "Mobility"],
            summary="Scholar Labs summary text.",
        ),
    )

    summary = maintenance_report(vault, report_date="2026-05-13")

    report = paths.indexes / "maintenance-report.md"
    task = paths.tasks / "2026-05-13-maintenance.md"
    report_text = report.read_text(encoding="utf-8")
    task_text = task.read_text(encoding="utf-8")
    assert summary["report"] == "_indexes/maintenance-report.md"
    assert summary["task"] == "tasks/2026-05-13-maintenance.md"
    assert summary["paper_cards_modified"] == 0
    assert summary["counts"]["reading_queue"] == 1
    assert summary["counts"]["noisy_topics"] == 1
    assert "# Maintenance Report - 2026-05-13" in report_text
    assert "Status / Doctor Summary" in report_text
    assert "Scholar Labs candidate results without canonical paper cards" in report_text
    assert (
        "scholar-vault topic-map --vault /path/to/vault --preset prompt-boilerplate"
        in report_text
    )
    assert "Review reading queue (1 papers)" in task_text


def test_rebuild_writes_dashboards_search_index_and_semantic_neighbors(tmp_path: Path) -> None:
    from scholar_vault.importer import _save_card  # noqa: PLC0415

    vault = tmp_path / "vault"
    paths = initialize_vault(vault)
    _write_pdf_with_title(paths.pdfs / "flow-a.pdf", "Flow Paper A")
    _write_pdf_with_title(paths.pdfs / "flow-b.pdf", "Flow Paper B")
    _save_card(
        paths,
        SourceCard(
            slug="flow-a",
            citekey="flowa",
            title="Origin Destination Flow Maps",
            pdf="pdfs/flow-a.pdf",
            pdf_status="attached",
            discovered_in=["runs/2026-04-22_flows/Flow Search.md"],
            topics=["Mobility", "Find"],
            keywords=["Origin-destination", "Flow maps"],
            abstract="This paper evaluates origin destination flow map visual encodings.",
            summary="Scholar Labs summary for flow maps.",
            notes="### PDF reading notes - 2026-05-13\nPDF-grounded notes about flows.",
        ),
    )
    _save_card(
        paths,
        SourceCard(
            slug="flow-b",
            citekey="flowb",
            title="Mobility Flow Evaluation",
            pdf="pdfs/flow-b.pdf",
            pdf_status="attached",
            discovered_in=["runs/2026-04-22_flows/Flow Search.md"],
            topics=["Mobility"],
            keywords=["Origin-destination"],
            abstract="Evaluation of mobility origin destination representations.",
            summary="Second summary.",
        ),
    )
    _save_card(
        paths,
        SourceCard(slug="unrelated", citekey="unrelated", title="Unrelated Source"),
    )
    (paths.concepts / "flow-maps.md").write_text(
        "# Flow Maps\nReusable concept.\n",
        encoding="utf-8",
    )
    (paths.syntheses / "mobility-flows.md").write_text(
        "# Mobility Flows\nCross-paper synthesis.\n",
        encoding="utf-8",
    )
    (paths.tasks / "2026-05-13-research-gaps.md").write_text(
        "# Research Gaps\nFind missing evaluation papers.\n",
        encoding="utf-8",
    )
    (paths.proposals / "mobility").mkdir(parents=True)
    (paths.proposals / "mobility" / "outline.md").write_text(
        "# Mobility Proposal\n",
        encoding="utf-8",
    )

    first_summary = rebuild_vault(vault)
    generated_files = [
        paths.indexes / "dashboard.md",
        paths.indexes / "paper-status.md",
        paths.indexes / "reading-queue.md",
        paths.indexes / "metadata-issues.md",
        paths.indexes / "pdf-issues.md",
        paths.indexes / "synthesis-dashboard.md",
        paths.indexes / "self-improvement.md",
        paths.indexes / "search-index.md",
        paths.exports / "semantic-neighbors.json",
    ]
    snapshots = {path: path.read_text(encoding="utf-8") for path in generated_files}
    second_summary = rebuild_vault(vault)
    semantic = json.loads((paths.exports / "semantic-neighbors.json").read_text(encoding="utf-8"))
    flow_a = next(row for row in semantic["papers"] if row["citekey"] == "flowa")

    assert first_summary["index_files_written"] == 22
    assert first_summary["export_files_written"] == 4
    assert "Scholar Vault Dashboard" in snapshots[paths.indexes / "dashboard.md"]
    assert "[Reading queue](reading-queue.md)" in snapshots[paths.indexes / "dashboard.md"]
    assert "Origin Destination Flow Maps" in snapshots[paths.indexes / "search-index.md"]
    assert "PDF-grounded notes about flows" in snapshots[paths.indexes / "search-index.md"]
    assert "Flow Maps" in snapshots[paths.indexes / "search-index.md"]
    assert (
        "This file does not include full PDF text"
        in snapshots[paths.indexes / "search-index.md"]
    )
    assert flow_a["neighbors"][0]["citekey"] == "flowb"
    assert any("shared topic: Mobility" in reason for reason in flow_a["neighbors"][0]["reasons"])
    assert any("same run:" in reason for reason in flow_a["neighbors"][0]["reasons"])
    assert second_summary["paper_cards_written"] == 0
    for path in generated_files:
        assert path.read_text(encoding="utf-8") == snapshots[path]


def test_notes_missing_reports_attached_cards_without_heading(tmp_path: Path) -> None:
    from scholar_vault.importer import _save_card  # noqa: PLC0415

    vault = tmp_path / "vault"
    paths = initialize_vault(vault)
    _save_card(
        paths,
        SourceCard(
            slug="read-paper",
            citekey="readpaper",
            title="Read Paper",
            pdf="pdfs/read-paper.pdf",
            pdf_status="attached",
            notes="### PDF reading notes - 2026-04-28\nEvidence from the PDF.",
        ),
    )
    _save_card(
        paths,
        SourceCard(
            slug="unread-paper",
            citekey="unreadpaper",
            title="Unread Paper",
            pdf="pdfs/unread-paper.pdf",
            pdf_status="attached",
        ),
    )
    _save_card(
        paths,
        SourceCard(
            slug="candidate",
            citekey="candidate",
            title="Candidate",
            status="candidate",
        ),
    )

    summary = notes_missing(vault, heading="PDF reading notes")

    assert summary["eligible_cards"] == 2
    assert summary["present"] == 1
    assert summary["missing"] == 1
    assert summary["missing_cards"][0]["paper"] == "papers/unread-paper.md"


def test_concept_index_refreshes_concept_index_and_llms(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    paths = initialize_vault(vault)
    (paths.concepts / "flow-maps.md").write_text(
        (
            "---\n"
            "type: concept\n"
            "title: Flow Maps\n"
            "sources:\n"
            "  - papers/source.md\n"
            "---\n\n"
            "# Flow Maps\n"
        ),
        encoding="utf-8",
    )

    summary = concept_index(vault)

    concepts_index = (paths.indexes / "concepts.md").read_text(encoding="utf-8")
    llms_full = (paths.vault / "llms-full.txt").read_text(encoding="utf-8")
    assert summary["concepts"] == 1
    assert summary["index"] == "_indexes/concepts.md"
    assert "[Flow Maps](../concepts/flow-maps.md)" in concepts_index
    assert "Concepts:" in llms_full


def test_proposal_sprint_scaffold_creates_and_updates_workspace(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    paths = initialize_vault(vault)
    summary = proposal_sprint_scaffold(vault, "pepr-mobidec", title="PEPR Mobidec")

    proposal = paths.proposals / "pepr-mobidec"
    assert summary["proposal"] == "proposals/pepr-mobidec"
    assert (proposal / "source-matrix.md").exists()
    assert (proposal / "reading-log.md").exists()
    assert (proposal / "outline.md").exists()
    assert "Original User Notes - Verbatim" in (
        proposal / "raw-idea.md"
    ).read_text(encoding="utf-8")
    outline_text = (proposal / "outline.md").read_text(encoding="utf-8")
    assert "evidence_matrix: source-matrix.md" in outline_text
    assert "[Source matrix](source-matrix.md)" in outline_text

    (proposal / "outline.md").write_text("# Custom Outline\n", encoding="utf-8")
    updated = proposal_sprint_scaffold(vault, "proposals/pepr-mobidec")

    assert "proposals/pepr-mobidec/outline.md" in updated["files"]["updated"]
    assert "# Custom Outline" in (proposal / "outline.md").read_text(encoding="utf-8")
    assert "_indexes/proposals.md" in (paths.vault / "llms.txt").read_text(encoding="utf-8")


def test_proposal_audit_reports_evidence_gaps(tmp_path: Path) -> None:
    from scholar_vault.importer import _save_card  # noqa: PLC0415

    vault = tmp_path / "vault"
    paths = initialize_vault(vault)
    _save_card(
        paths,
        SourceCard(
            slug="read-paper",
            citekey="readpaper",
            title="Read Paper",
            notes="### PDF reading notes - 2026-04-28\nEvidence from the PDF.",
        ),
    )
    _save_card(
        paths,
        SourceCard(slug="unread-paper", citekey="unreadpaper", title="Unread Paper"),
    )
    proposal = paths.proposals / "pepr-mobidec"
    proposal.mkdir(parents=True)
    (proposal / "outline.md").write_text(
        "# Outline\n\n"
        "- Claim from [Read Paper](../../papers/read-paper.md).\n"
        "- Claim from [Unread Paper](../../papers/unread-paper.md).\n"
        "- Scholar Labs summary says this is relevant.\n",
        encoding="utf-8",
    )
    (proposal / "source-matrix.md").write_text(
        "# Source Matrix\n\n"
        "| Source | Proposal role |\n"
        "| --- | --- |\n"
        "| [Read Paper](../../papers/read-paper.md) | Proposal role: Core |\n"
        "| [Broken](../../papers/missing-paper.md) | Proposal role: Supporting |\n",
        encoding="utf-8",
    )
    (proposal / "raw-idea.md").write_text(
        "# Raw Idea\n\n## Original User Notes - Verbatim\n\nUser note.",
        encoding="utf-8",
    )

    summary = proposal_audit(vault, "proposals/pepr-mobidec")

    assert summary["ok"] is False
    assert summary["issue_counts"]["outline_citations_without_pdf_reading_notes"] == 1
    assert summary["issue_counts"]["broken_source_matrix_links"] == 1
    assert summary["issue_counts"]["draft_claims_using_scholar_labs_summaries"] == 1
    assert summary["issues"]["outline_citations_without_pdf_reading_notes"][0]["paper"] == (
        "papers/unread-paper.md"
    )


def test_proposal_audit_follows_outline_evidence_matrix_field(tmp_path: Path) -> None:
    from scholar_vault.importer import _save_card  # noqa: PLC0415

    vault = tmp_path / "vault"
    paths = initialize_vault(vault)
    _save_card(
        paths,
        SourceCard(
            slug="read-paper",
            citekey="readpaper",
            title="Read Paper",
            notes="### PDF reading notes - 2026-04-28\nEvidence from the PDF.",
        ),
    )
    proposal = paths.proposals / "pepr-mobidec"
    proposal.mkdir(parents=True)
    (proposal / "proposal-outline.md").write_text(
        "---\n"
        "type: proposal_outline\n"
        "evidence_matrix: syntheses/pepr-evidence-matrix.md\n"
        "---\n\n"
        "# Proposal Outline\n\n"
        "- Claim from [Read Paper](../../papers/read-paper.md).\n",
        encoding="utf-8",
    )
    (proposal / "raw-idea.md").write_text(
        "# Raw Idea\n\n## Original User Notes - Verbatim\n\nUser note.",
        encoding="utf-8",
    )
    (paths.syntheses / "pepr-evidence-matrix.md").write_text(
        "# Evidence Matrix\n\n"
        "| Source | Proposal role |\n"
        "| --- | --- |\n"
        "| [Read Paper](../papers/read-paper.md) | Proposal role: Core |\n"
        "| [Broken](../papers/missing-paper.md) | Proposal role: Supporting |\n",
        encoding="utf-8",
    )

    summary = proposal_audit(vault, "proposals/pepr-mobidec")

    assert summary["counts"]["source_matrix_files"] == 1
    assert "syntheses/pepr-evidence-matrix.md" in summary["files"]
    assert summary["issue_counts"]["read_papers_without_proposal_role"] == 0
    assert summary["issue_counts"]["broken_source_matrix_links"] == 1
    assert summary["issues"]["broken_source_matrix_links"][0]["file"] == (
        "syntheses/pepr-evidence-matrix.md"
    )


def test_proposal_audit_reports_missing_evidence_matrix_target(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    paths = initialize_vault(vault)
    proposal = paths.proposals / "pepr-mobidec"
    proposal.mkdir(parents=True)
    (proposal / "proposal-outline.md").write_text(
        "---\n"
        "type: proposal_outline\n"
        "evidence_matrix: syntheses/missing-evidence-matrix.md\n"
        "---\n\n"
        "# Proposal Outline\n",
        encoding="utf-8",
    )
    (proposal / "raw-idea.md").write_text(
        "# Raw Idea\n\n## Original User Notes - Verbatim\n\nUser note.",
        encoding="utf-8",
    )

    summary = proposal_audit(vault, "proposals/pepr-mobidec")

    assert summary["counts"]["source_matrix_files"] == 0
    assert summary["issue_counts"]["broken_source_matrix_links"] == 1
    assert summary["issues"]["broken_source_matrix_links"][0]["message"] == (
        "evidence_matrix link does not resolve"
    )


def render_without_quick_access(card: SourceCard) -> str:
    return (
        "---\n"
        + yaml.safe_dump(card.frontmatter(), sort_keys=False)
        + "---\n\n"
        + f"# {card.title}\n\n"
        + "## Abstract\nNo abstract yet.\n\n"
        + f"## Scholar Labs summary\n{card.summary}\n\n"
        + "## Why this source matters\n- No rationale captured yet.\n\n"
        + "## Files\n"
        + f"- PDF: [{card.pdf}](../{card.pdf})\n\n"
        + "## Notes\nNo notes yet.\n"
    )


def test_rebuild_migrates_pdf_collision_suffix_before_extension(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    paths = initialize_vault(vault)
    bad_pdf = paths.pdfs / "paper.pdf-2"
    _write_pdf_with_title(bad_pdf, "Paper")
    card = SourceCard(
        slug="paper",
        citekey="paper",
        title="Paper",
        pdf="pdfs/paper.pdf-2",
        pdf_status="attached",
    )

    from scholar_vault.importer import _save_card  # noqa: PLC0415

    _save_card(paths, card)

    rebuild_vault(vault)
    migrated = load_source_cards(initialize_vault(vault))[0]

    assert migrated.pdf == "pdfs/paper-2.pdf"
    assert not bad_pdf.exists()
    assert (paths.pdfs / "paper-2.pdf").exists()


def test_rebuild_cleans_existing_scholar_resource_title_prefixes(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    paths = initialize_vault(vault)
    run_id = "2026-04-22_bad-title-run"
    run_dir = paths.runs / run_id
    run_dir.mkdir(parents=True)
    write_yaml(
        run_dir / "index.yaml",
        {
            "slug": run_id,
            "date": "2026-04-22",
            "prompt": "bad title run",
            "exported_at": "2026-04-22T16:00:00+02:00",
            "export_file": "/tmp/export.json",
            "raw_export_file": "raw/scholar-labs/example.json",
            "result_count": 1,
            "results": [
                {
                    "rank": 1,
                    "title": "[HTML][HTML] Mapping Digital Solutions",
                    "status": "selected",
                    "pdf_status": "attached",
                    "paper_card": "papers/milovanovic2025htmlhtmlmapping.md",
                }
            ],
        },
    )
    (paths.papers / "milovanovic2025htmlhtmlmapping.md").write_text(
        """---
type: paper
citekey: milovanovic2025htmlhtmlmapping
title: "[HTML][HTML] Mapping Digital Solutions"
source_kind: scholar_labs
pdf_status: attached
---

# [HTML][HTML] Mapping Digital Solutions

## Scholar Labs summary
No summary yet.
""",
        encoding="utf-8",
    )

    rebuild_vault(vault)
    card = load_source_cards(initialize_vault(vault))[0]
    run_yaml = _run_yaml(vault, run_id)
    card_text = (paths.papers / "milovanovic2025htmlhtmlmapping.md").read_text(
        encoding="utf-8"
    )

    assert card.title == "Mapping Digital Solutions"
    assert run_yaml["results"][0]["title"] == "Mapping Digital Solutions"
    assert "# Mapping Digital Solutions" in card_text
    assert "[HTML][HTML]" not in card_text


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


def test_import_labs_auto_enriches_selected_cards_and_run_markdown(
    tmp_path: Path,
    monkeypatch,
) -> None:
    vault = tmp_path / "vault"
    staging = tmp_path / "staging"
    exports = tmp_path / "exports"
    staging.mkdir()
    exports.mkdir()
    export_path = _write_export(exports / "sample.json", 1)
    _write_pdf_with_title(staging / "paper-1.pdf", "Result Paper 1")

    def fake_enrich_cards(paths, cards, options, progress=None):
        del paths
        for card in cards:
            if progress:
                progress(card, 1, len(cards), "verified")
            if options.only == "missing-keywords":
                card.keywords = ["Retrieval", "Benchmarking"]
            elif options.abstracts:
                card.abstract = "Recovered provider abstract."
                card.abstract_status = "resolved"
                card.abstract_source = "crossref"
            else:
                card.authors = ["Jane Smith", "Omar Lee"]
                card.venue = "Journal of Enriched Metadata"
                card.doi = "10.1145/example"
                card.url = "https://doi.org/10.1145/example"
                card.citation_status = "verified"
        return [
            EnrichmentResult(card.citekey or card.slug, "verified", "enriched", changed=True)
            for card in cards
        ]

    monkeypatch.setattr("scholar_vault.importer.enrich_cards", fake_enrich_cards)

    summary = import_scholar_labs_run(
        vault,
        export_path,
        staging,
        commit=True,
        archive_matched=True,
        auto_enrich=True,
    )
    cards = load_source_cards(initialize_vault(vault))
    run_markdown = (vault / _run_note_path(vault, str(summary["run"]))).read_text(
        encoding="utf-8"
    )

    assert summary["enriched"] == 3
    assert len(summary["enrichment_details"]) == 1
    assert len(summary["abstract_details"]) == 1
    assert len(summary["keyword_details"]) == 1
    assert summary["enrichment_details"][0]["kind"] == "citation"
    assert summary["abstract_details"][0]["kind"] == "abstract"
    assert summary["keyword_details"][0]["kind"] == "keywords"
    assert cards[0].venue == "Journal of Enriched Metadata"
    assert cards[0].doi == "10.1145/example"
    assert cards[0].abstract == "Recovered provider abstract."
    assert cards[0].keywords == ["Retrieval", "Benchmarking"]
    assert "Venue: Journal of Enriched Metadata" in run_markdown
    assert "[10.1145/example](https://doi.org/10.1145/example)" in run_markdown
    assert "[pdfs/" in run_markdown


def test_set_manual_abstract_locks_and_rerenders_card(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    paths = initialize_vault(vault)
    card = SourceCard(
        slug="smith2024rag",
        citekey="smith2024rag",
        title="Evaluating Retrieval Augmented Generation Systems",
    )
    (paths.papers / "smith2024rag.md").write_text(
        render_paper_markdown(card),
        encoding="utf-8",
    )

    progress_steps: list[str] = []
    summary = set_manual_abstract(
        vault,
        "smith2024rag",
        "Manual abstract.\n\nSecond paragraph.",
        source_url="https://example.com/abstract",
        progress=progress_steps.append,
    )
    saved = load_source_cards(initialize_vault(vault))[0]
    rendered = (paths.papers / "smith2024rag.md").read_text(encoding="utf-8")

    assert summary["locked"] is True
    assert saved.abstract == "Manual abstract.\n\nSecond paragraph."
    assert saved.abstract_status == "manual_lock"
    assert saved.abstract_source == "manual"
    assert saved.abstract_source_url == "https://example.com/abstract"
    assert saved.abstract_lock is True
    assert "## Abstract\nManual abstract.\n\nSecond paragraph." in rendered
    assert progress_steps[:6] == [
        "Opening vault",
        "Cleaning abstract text",
        "Loading paper cards",
        "Updating abstract metadata",
        "Writing paper card",
        "Rebuilding derived files",
    ]
    assert "Writing library exports" in progress_steps
    assert progress_steps[-1] == "Manual save complete"


def test_set_manual_keywords_normalizes_and_rerenders_card(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    paths = initialize_vault(vault)
    card = SourceCard(
        slug="smith2024rag",
        citekey="smith2024rag",
        title="Evaluating Retrieval Augmented Generation Systems",
    )
    (paths.papers / "smith2024rag.md").write_text(
        render_paper_markdown(card),
        encoding="utf-8",
    )

    progress_steps: list[str] = []
    summary = set_manual_keywords(
        vault,
        "smith2024rag",
        "Index Terms--Retrieval | Benchmarking\nCollaborative analysis",
        progress=progress_steps.append,
    )
    saved = load_source_cards(initialize_vault(vault))[0]
    rendered = (paths.papers / "smith2024rag.md").read_text(encoding="utf-8")

    assert summary["count"] == 3
    assert saved.keywords == ["Retrieval", "Benchmarking", "Collaborative analysis"]
    assert "## Keywords\n- Retrieval\n- Benchmarking\n- Collaborative analysis" in rendered
    assert "Normalizing keyword separators" in progress_steps
    assert "Writing topic pages" in progress_steps
    assert progress_steps[-1] == "Manual save complete"


def test_set_manual_metadata_resolves_ambiguous_card(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    paths = initialize_vault(vault)
    card = SourceCard(
        slug="smith2024rag",
        citekey="smith2024rag",
        title="Evaluating Retrieval Augmented Generation Systems",
        doi_status="ambiguous",
        citation_status="ambiguous",
        citation_skip_reason="ambiguous crossref candidate score=82",
        enrichment_status="ambiguous",
        enrichment_missing=["doi", "authors", "year", "venue"],
    )
    (paths.papers / "smith2024rag.md").write_text(
        render_paper_markdown(card),
        encoding="utf-8",
    )

    progress_steps: list[str] = []
    summary = set_manual_metadata(
        vault,
        "smith2024rag",
        doi="https://doi.org/10.1145/example",
        authors="Jane Smith; John Doe",
        year="2024",
        venue="Proceedings of Example Research",
        url="https://example.com/paper",
        progress=progress_steps.append,
    )
    saved = load_source_cards(initialize_vault(vault))[0]
    rendered = (paths.papers / "smith2024rag.md").read_text(encoding="utf-8")

    assert summary["missing_fields"] == []
    assert saved.doi == "10.1145/example"
    assert saved.authors == ["Jane Smith", "John Doe"]
    assert saved.year == 2024
    assert saved.venue == "Proceedings of Example Research"
    assert saved.url == "https://example.com/paper"
    assert saved.doi_status == "verified"
    assert saved.doi_source == "manual"
    assert saved.citation_status == "verified"
    assert saved.citation_source == "manual"
    assert saved.enrichment_status == "complete"
    assert saved.enrichment_missing == []
    assert saved.metadata_lock is False
    assert saved.citation_skip_reason is None
    assert "- DOI: [10.1145/example](https://doi.org/10.1145/example)" in rendered
    assert "- Metadata: `complete`" in rendered
    assert "Normalizing metadata fields" in progress_steps
    assert "Writing index pages" in progress_steps
    assert progress_steps[-1] == "Manual save complete"


def test_set_manual_metadata_lock_accepts_thesis_without_doi_or_venue(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    paths = initialize_vault(vault)
    card = SourceCard(
        slug="smith2024thesis",
        citekey="smith2024thesis",
        title="Evaluating Retrieval Augmented Generation Systems",
        doi_status="ambiguous",
        citation_status="ambiguous",
        citation_skip_reason="ambiguous crossref candidate score=42",
        enrichment_status="ambiguous",
        enrichment_missing=["doi", "venue"],
    )
    (paths.papers / "smith2024thesis.md").write_text(
        render_paper_markdown(card),
        encoding="utf-8",
    )

    summary = set_manual_metadata(
        vault,
        "smith2024thesis",
        authors="Jane Smith",
        year="2024",
        url="https://example.edu/thesis.pdf",
        lock=True,
    )
    saved = load_source_cards(initialize_vault(vault))[0]
    status = doctor_vault(vault)

    assert summary["metadata_lock"] is True
    assert summary["enrichment_status"] == "manual_lock"
    assert summary["missing_fields"] == ["doi", "venue"]
    assert saved.citation_status == "verified"
    assert saved.doi_status == "missing"
    assert saved.metadata_lock is True
    assert saved.citation_skip_reason == (
        "manual metadata locked; missing fields accepted: doi, venue"
    )
    assert status["issue_counts"]["ambiguous_citations"] == 0
    assert status["issue_counts"]["incomplete_enrichment"] == 0


def test_confirm_no_publication_keywords_marks_keyword_step_done(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    paths = initialize_vault(vault)
    pdf_path = paths.pdfs / "smith2024rag.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    card = SourceCard(
        slug="smith2024rag",
        citekey="smith2024rag",
        title="Evaluating Retrieval Augmented Generation Systems",
        pdf="pdfs/smith2024rag.pdf",
        pdf_status="attached",
        enrichment_missing=["keywords"],
    )
    (paths.papers / "smith2024rag.md").write_text(
        render_paper_markdown(card),
        encoding="utf-8",
    )

    progress_steps: list[str] = []
    summary = confirm_no_publication_keywords(
        vault,
        "smith2024rag",
        progress=progress_steps.append,
    )
    saved = load_source_cards(initialize_vault(vault))[0]
    rendered = (paths.papers / "smith2024rag.md").read_text(encoding="utf-8")

    assert summary["status"] == "absent"
    assert saved.publication_keywords_status == "absent"
    assert saved.publication_keywords_source == "manual"
    assert saved.keywords == []
    assert "keywords" not in saved.enrichment_missing
    assert "## Keywords\nNo publication keywords listed in the source." in rendered
    assert "Confirming source keyword absence" in progress_steps
    assert progress_steps[-1] == "Manual save complete"


def test_set_manual_abstract_normalizes_preview_pdf_copy(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    paths = initialize_vault(vault)
    card = SourceCard(
        slug="nafis2024collaborative",
        citekey="nafis2024collaborative",
        title="Collaborative Immersive Analytics",
    )
    (paths.papers / "nafis2024collaborative.md").write_text(
        render_paper_markdown(card),
        encoding="utf-8",
    )

    set_manual_abstract(
        vault,
        "nafis2024collaborative",
        "Abstract. Collaborative immersive analytics offers a promising fron-\n"
        "tier for domain experts. This research studies us-\n"
        "ability in XR.\n\nKeywords: Immersive Analytics",
    )
    saved = load_source_cards(initialize_vault(vault))[0]

    assert saved.abstract == (
        "Collaborative immersive analytics offers a promising frontier for domain "
        "experts. This research studies usability in XR."
    )


def test_find_staged_run_matches_scores_leftover_pdf_against_previous_runs(
    tmp_path: Path,
    monkeypatch,
) -> None:
    vault = tmp_path / "vault"
    staging = tmp_path / "staging"
    export = tmp_path / "run.json"
    staging.mkdir()
    _rewrite_export(
        _write_export(export, 1, title="Residual PDF Search"),
        result_updates={"title": "Collaborative Immersive Analytics in Virtual Reality"},
    )
    import_scholar_labs_run(vault, export, staging, commit=True)
    pdf_path = staging / "leftover.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")

    def fake_build(path: Path) -> PdfCandidate:
        return PdfCandidate(
            path=str(path),
            title="Collaborative Immersive Analytics in Virtual Reality",
            text_excerpt="Collaborative Immersive Analytics in Virtual Reality",
            sha256="sha-leftover",
            size=path.stat().st_size,
        )

    monkeypatch.setattr("scholar_vault.importer.build_pdf_candidate", fake_build)

    summary = find_staged_run_matches(vault, staging, min_score=90)

    assert summary["runs"] == 1
    assert summary["staged_pdfs_scanned"] == 1
    assert summary["matches"][0]["pdf_filename"] == "leftover.pdf"
    assert summary["matches"][0]["run_title"] == "Residual PDF Search"
    assert summary["matches"][0]["result_title"] == (
        "Collaborative Immersive Analytics in Virtual Reality"
    )
    assert summary["matches"][0]["score"] == 100


def test_find_staged_run_matches_accepts_typed_title_query(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    staging = tmp_path / "staging"
    export = tmp_path / "run.json"
    staging.mkdir()
    _rewrite_export(
        _write_export(export, 1, title="Residual PDF Search"),
        result_updates={"title": "Origin-Destination Flow Data Smoothing and Mapping"},
    )
    import_scholar_labs_run(vault, export, staging, commit=True)

    summary = find_staged_run_matches(
        vault,
        staging,
        title="Origin destination flow data smoothing mapping",
        min_score=80,
    )

    assert summary["staged_pdfs_scanned"] == 0
    assert summary["matches"][0]["reason"] == "typed-title"
    assert summary["matches"][0]["run_id"].startswith("2026-04-22")
    assert summary["matches"][0]["score"] >= 90


def test_find_staged_run_matches_uses_title_to_search_and_pdf_to_import(
    tmp_path: Path,
    monkeypatch,
) -> None:
    vault = tmp_path / "vault"
    staging = tmp_path / "staging"
    export = tmp_path / "run.json"
    title = "Focus Glue Context: An Improved Fisheye Approach for Web Map Services"
    staging.mkdir()
    _rewrite_export(
        _write_export(export, 1, title="Residual PDF Search"),
        result_updates={"title": title},
    )
    import_scholar_labs_run(vault, export, staging, commit=True)
    pdf_path = staging / "1653771.1653788.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")

    def fake_build(path: Path) -> PdfCandidate:
        return PdfCandidate(
            path=str(path),
            title="Focus+Glue+Context: an improved fisheye approach for web map services",
            text_excerpt=title,
            sha256="sha-focus",
            size=path.stat().st_size,
        )

    monkeypatch.setattr("scholar_vault.importer.build_pdf_candidate", fake_build)

    summary = find_staged_run_matches(
        vault,
        staging,
        title=title,
        pdf_path=pdf_path,
        min_score=90,
    )

    assert summary["staged_pdfs_scanned"] == 1
    assert summary["matches"][0]["reason"] == "typed-title+pdf"
    assert summary["matches"][0]["pdf_path"] == str(pdf_path.resolve())
    assert summary["matches"][0]["pdf_title"].startswith("Focus+Glue+Context")
    assert summary["matches"][0]["summary"]


def test_import_staged_pdf_match_attaches_one_pdf_to_one_run_result(
    tmp_path: Path,
    monkeypatch,
) -> None:
    vault = tmp_path / "vault"
    staging = tmp_path / "staging"
    export = tmp_path / "run.json"
    title = "Focus Glue Context: An Improved Fisheye Approach for Web Map Services"
    staging.mkdir()
    _rewrite_export(
        _write_export(export, 1, title="Residual PDF Search"),
        result_updates={"title": title},
    )
    run_summary = import_scholar_labs_run(vault, export, staging, commit=True)
    pdf_path = staging / "1653771.1653788.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")

    def fake_build(path: Path) -> PdfCandidate:
        return PdfCandidate(
            path=str(path),
            title=title,
            text_excerpt=f"{title}\nKeywords: web maps, fisheye",
            sha256=None,
            size=path.stat().st_size,
        )

    monkeypatch.setattr("scholar_vault.importer.build_pdf_candidate", fake_build)

    summary = import_staged_pdf_match(
        vault,
        run_summary["run"],
        pdf_path,
        rank=1,
        result_title=title,
        score=100,
        auto_enrich=False,
    )
    run_yaml = _run_yaml(vault, run_summary["run"])
    manifest = _manifest_yaml(vault, run_summary["run"])
    cards = load_source_cards(initialize_vault(vault))

    assert summary["decision_summary"]["targeted_import"] is True
    assert summary["decision_summary"]["new_staged_pdf_matches"] == 1
    assert summary["archived"] == 1
    assert not pdf_path.exists()
    assert run_yaml["results"][0]["status"] == "selected"
    assert run_yaml["results"][0]["pdf_status"] == "attached"
    assert run_yaml["results"][0]["paper_card"].startswith("papers/")
    assert manifest["entries"][0]["decision"] == "accepted"
    assert manifest["entries"][0]["paper_card"] == run_yaml["results"][0]["paper_card"]
    assert cards[0].pdf
    assert (vault / cards[0].pdf).exists()
    assert cards[0].summary
    assert "web maps" in cards[0].keywords


def test_imported_pdf_syncs_matching_previous_runs(tmp_path: Path, monkeypatch) -> None:
    vault = tmp_path / "vault"
    staging = tmp_path / "staging"
    staging.mkdir()
    title = "Collaborative Immersive Analytics in Virtual Reality"
    first_export = tmp_path / "first.json"
    second_export = tmp_path / "second.json"
    _rewrite_export(
        _write_export(
            first_export,
            1,
            title="First Run",
            prompt="find collaborative immersive analytics papers",
            exported_at="2026-04-22T16:00:00+02:00",
        ),
        result_updates={"title": title},
    )
    _rewrite_export(
        _write_export(
            second_export,
            1,
            title="Second Run",
            prompt="find virtual reality collaboration papers",
            exported_at="2026-04-23T16:00:00+02:00",
        ),
        result_updates={"title": title},
    )
    first = import_scholar_labs_run(vault, first_export, staging, commit=True)
    pdf_path = staging / "leftover.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")

    def fake_build(path: Path) -> PdfCandidate:
        return PdfCandidate(
            path=str(path),
            title=title,
            text_excerpt=title,
            sha256=None,
            size=path.stat().st_size,
        )

    monkeypatch.setattr("scholar_vault.importer.build_pdf_candidate", fake_build)

    second = import_scholar_labs_run(vault, second_export, staging, commit=True)
    first_run = _run_yaml(vault, first["run"])
    first_manifest = _manifest_yaml(vault, first["run"])
    second_run = _run_yaml(vault, second["run"])
    cards = load_source_cards(initialize_vault(vault))

    assert second["decision_summary"]["other_runs_synced"] == 1
    assert first_run["results"][0]["status"] == "selected"
    assert first_run["results"][0]["pdf_status"] == "attached"
    assert first_run["results"][0]["paper_card"] == second_run["results"][0]["paper_card"]
    assert first_manifest["entries"][0]["decision"] == "accepted"
    assert first_manifest["entries"][0]["paper_card"] == second_run["results"][0]["paper_card"]
    assert any(f"runs/{first['run']}/" in ref for ref in cards[0].discovered_in)
    assert any(f"runs/{second['run']}/" in ref for ref in cards[0].discovered_in)


def test_rebuild_repairs_missing_run_links_to_attached_cards(
    tmp_path: Path,
    monkeypatch,
) -> None:
    vault = tmp_path / "vault"
    staging = tmp_path / "staging"
    staging.mkdir()
    title = "Collaborative Immersive Analytics in Virtual Reality"
    first_export = tmp_path / "first.json"
    second_export = tmp_path / "second.json"
    _rewrite_export(
        _write_export(
            first_export,
            1,
            title="First Run",
            prompt="find collaborative immersive analytics papers",
            exported_at="2026-04-22T16:00:00+02:00",
        ),
        result_updates={"title": title},
    )
    _rewrite_export(
        _write_export(
            second_export,
            1,
            title="Second Run",
            prompt="find virtual reality collaboration papers",
            exported_at="2026-04-23T16:00:00+02:00",
        ),
        result_updates={"title": title},
    )
    first = import_scholar_labs_run(vault, first_export, staging, commit=True)
    pdf_path = staging / "leftover.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")

    def fake_build(path: Path) -> PdfCandidate:
        return PdfCandidate(
            path=str(path),
            title=title,
            text_excerpt=title,
            sha256=None,
            size=path.stat().st_size,
        )

    monkeypatch.setattr("scholar_vault.importer.build_pdf_candidate", fake_build)
    second = import_scholar_labs_run(vault, second_export, staging, commit=True)

    first_run_path = vault / "runs" / str(first["run"]) / "index.yaml"
    first_run = _run_yaml(vault, first["run"])
    first_run["results"][0]["status"] = "candidate"
    first_run["results"][0]["pdf_status"] = "missing"
    first_run["results"][0].pop("paper_card", None)
    write_yaml(first_run_path, first_run)

    first_manifest_path = vault / "runs" / str(first["run"]) / "import-manifest.yaml"
    first_manifest = _manifest_yaml(vault, first["run"])
    first_manifest["entries"][0]["decision"] = "unresolved"
    first_manifest["entries"][0].pop("paper_card", None)
    first_manifest["entries"][0].pop("destination_path", None)
    first_manifest["entries"][0]["verified"] = False
    write_yaml(first_manifest_path, first_manifest)

    paths = VaultPaths.from_root(vault)
    card = load_source_cards(paths)[0]
    card.discovered_in = [
        ref for ref in card.discovered_in if f"runs/{first['run']}/" not in ref
    ]
    (paths.papers / f"{card.slug}.md").write_text(
        render_paper_markdown(card),
        encoding="utf-8",
    )

    summary = rebuild_vault(vault)
    repaired_run = _run_yaml(vault, first["run"])
    repaired_manifest = _manifest_yaml(vault, first["run"])
    repaired_card = load_source_cards(VaultPaths.from_root(vault))[0]
    second_run = _run_yaml(vault, second["run"])

    assert summary["cross_run_links_synced"] >= 1
    assert repaired_run["results"][0]["status"] == "selected"
    assert repaired_run["results"][0]["pdf_status"] == "attached"
    assert repaired_run["results"][0]["paper_card"] == second_run["results"][0]["paper_card"]
    assert repaired_manifest["entries"][0]["decision"] == "accepted"
    assert repaired_manifest["entries"][0]["paper_card"] == second_run["results"][0]["paper_card"]
    assert any(f"runs/{first['run']}/" in ref for ref in repaired_card.discovered_in)


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


def test_import_pdf_accepts_explicit_files_and_auto_enriches_touched_cards(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from scholar_vault import importer

    vault = tmp_path / "vault"
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    initialize_vault(vault)
    pdf_path = downloads / "direct-paper.pdf"
    _write_pdf_with_title(pdf_path, "Direct Paper Import")
    calls: list[tuple[str, bool, list[str]]] = []

    def fake_enrich_cards(_paths, cards, options, **_kwargs):
        calls.append((options.only, options.abstracts, [card.slug for card in cards]))
        status = (
            "resolved"
            if options.abstracts or options.only == "missing-keywords"
            else "verified"
        )
        return [
            EnrichmentResult(card.citekey or card.slug, status, "ok", changed=True)
            for card in cards
        ]

    monkeypatch.setattr(importer, "enrich_cards", fake_enrich_cards)

    summary = import_pdf_dropins(vault, pdf_paths=[pdf_path], auto_enrich=True)

    assert summary["imported"] == 1
    assert summary["created"] == 1
    assert summary["citation_enrichment"]["processed"] == 1
    assert summary["abstract_enrichment"]["processed"] == 1
    assert summary["keyword_enrichment"]["processed"] == 1
    slug = calls[0][2][0]
    assert calls == [
        ("all", False, [slug]),
        ("all", True, [slug]),
        ("missing-keywords", False, [slug]),
    ]


def test_import_bibtex_stores_paper_keywords_separately_from_topics(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    bib = tmp_path / "paper.bib"
    initialize_vault(vault)
    bib.write_text(
        """
@inproceedings{smith2024rag,
  title = {Evaluating Retrieval Augmented Generation Systems},
  author = {Jane Smith},
  year = {2024},
  keywords = {Retrieval, Benchmarking; Evaluation}
}
""".strip(),
        encoding="utf-8",
    )

    import_bibtex(vault, bib)
    cards = load_source_cards(initialize_vault(vault))

    assert cards[0].keywords == ["Retrieval", "Benchmarking", "Evaluation"]
    assert cards[0].topics == []


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
