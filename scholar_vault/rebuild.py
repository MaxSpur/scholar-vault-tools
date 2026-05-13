from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .bibtex import write_library_bib
from .citations import refresh_metadata_completeness
from .dashboards import _write_dashboard_indexes
from .models import RunRecord, SourceCard
from .neighbors import semantic_neighbors_export
from .obsidian import ARTIFACT_INDEXES, _collect_research_artifacts
from .render import (
    group_cards_by_topic,
    render_artifact_index,
    render_llms_full,
    render_llms_txt,
    render_missing_pdfs,
    render_paper_markdown,
    render_papers_index,
    render_prompts_index,
    render_topic_page,
    render_topics_index,
    render_unmatched_index,
    render_zotero_migration,
)
from .search_index import render_search_index
from .sources import (
    VaultPaths,
    ensure_relative,
    load_import_manifests,
    load_run_records,
    load_source_cards,
    topic_slug,
    write_json,
    write_text,
)

ManualSaveProgress = Any


def _manual_save_step(progress: ManualSaveProgress | None, message: str) -> None:
    if progress is not None:
        progress(message)


def initialize_vault(vault: Path | str, *, rebuild: bool = True) -> VaultPaths:
    from .importer import initialize_vault as initialize

    return initialize(vault, rebuild=rebuild)


def _run_ref(run: RunRecord) -> str:
    from .importer import _run_ref as run_ref

    return run_ref(run)


def _normalize_run_ref(ref: str, run_refs: dict[str, str] | None = None) -> str:
    from .importer import _normalize_run_ref as normalize_run_ref

    return normalize_run_ref(ref, run_refs)


def _backfill_summary_source_from_card(
    card: SourceCard,
    *,
    run_refs: dict[str, str] | None = None,
):
    from .importer import _backfill_summary_source_from_card as backfill_summary_source

    return backfill_summary_source(card, run_refs=run_refs)


def _merge_summary_sources(existing, incoming, *, run_refs: dict[str, str] | None = None):
    from .importer import _merge_summary_sources as merge_summary_sources

    return merge_summary_sources(existing, incoming, run_refs=run_refs)


def _repair_run_links_to_attached_cards(paths, runs, cards, manifests) -> int:
    from .importer import _repair_run_links_to_attached_cards as repair_run_links

    return repair_run_links(paths, runs, cards, manifests)


def _write_run(paths: VaultPaths, run: RunRecord, cards: list[SourceCard]) -> None:
    from .importer import _write_run as write_run

    write_run(paths, run, cards)


def _refresh_card_completeness(card: SourceCard) -> bool:
    before = (
        card.enrichment_status,
        tuple(card.enrichment_missing),
    )
    refresh_metadata_completeness(card)
    return before != (card.enrichment_status, tuple(card.enrichment_missing))


def _cards_to_library_json(cards: list[SourceCard]) -> list[dict]:
    return [card.model_dump(exclude_none=True) for card in cards]


def _cards_to_csl_json(cards: list[SourceCard]) -> list[dict]:
    exported = []
    for card in cards:
        authors = card.authors or ([card.authors_preview] if card.authors_preview else [])
        note = card.summary if card.summary and card.summary != "No summary yet." else None
        exported.append(
            {
                "id": card.citekey or card.slug,
                "type": "article-journal" if card.venue else "document",
                "title": card.title,
                "author": [{"literal": author} for author in authors],
                "issued": {"date-parts": [[card.year]]} if card.year else None,
                "container-title": card.venue,
                "DOI": card.doi,
                "URL": card.url,
                "abstract": card.abstract,
                "keyword": ", ".join(card.keywords) if card.keywords else None,
                "note": note,
            }
        )
    return exported


def _normalize_attached_pdf_filename(paths: VaultPaths, card: SourceCard) -> bool:
    if not card.pdf:
        return False
    pdf_path = paths.vault / card.pdf
    if not pdf_path.exists() or pdf_path.suffix == ".pdf":
        return False
    match = re.match(r"(.+)\.pdf-(\d+)$", pdf_path.name, flags=re.IGNORECASE)
    if not match:
        return False
    destination = pdf_path.with_name(f"{match.group(1)}-{match.group(2)}.pdf")
    if destination.exists():
        return False
    pdf_path.rename(destination)
    card.pdf = ensure_relative(destination, paths.vault)
    return True


def _rebuild_indexes(
    paths: VaultPaths,
    *,
    progress: ManualSaveProgress | None = None,
) -> dict[str, int]:
    _manual_save_step(progress, "Loading run records")
    runs = load_run_records(paths)
    run_refs = {run.slug: _run_ref(run) for run in runs}
    _manual_save_step(progress, "Loading paper cards")
    cards = load_source_cards(paths)
    _manual_save_step(progress, "Loading import manifests")
    manifests = load_import_manifests(paths)
    cards_changed = False
    cards_normalized = 0
    pdf_filenames_normalized = 0
    _manual_save_step(progress, "Normalizing paper card references")
    for card in cards:
        card_changed = False
        if _refresh_card_completeness(card):
            card_changed = True
        normalized_discovered_in = [
            _normalize_run_ref(item, run_refs) for item in card.discovered_in
        ]
        if normalized_discovered_in != card.discovered_in:
            card.discovered_in = normalized_discovered_in
            card_changed = True
        backfilled_sources = _backfill_summary_source_from_card(card, run_refs=run_refs)
        normalized_sources = _merge_summary_sources(backfilled_sources, [], run_refs=run_refs)
        if normalized_sources != card.summary_sources:
            card.summary_sources = normalized_sources
            card_changed = True
        if _normalize_attached_pdf_filename(paths, card):
            card_changed = True
            pdf_filenames_normalized += 1
        if card.keywords and card.publication_keywords_status != "present":
            card.publication_keywords_status = "present"
            card.publication_keywords_source = card.publication_keywords_source or "imported"
            card_changed = True
        if card_changed:
            cards_changed = True
            cards_normalized += 1
    _manual_save_step(progress, "Repairing run links to attached PDFs")
    cross_run_links_synced = _repair_run_links_to_attached_cards(
        paths,
        runs,
        cards,
        manifests,
    )
    cards_changed = cards_changed or bool(cross_run_links_synced)
    paper_cards_written = 0
    _manual_save_step(progress, "Rendering paper cards")
    for card in cards:
        rendered = render_paper_markdown(card)
        paper_path = paths.papers / f"{card.slug}.md"
        should_write = (
            cards_changed
            or not paper_path.exists()
            or paper_path.read_text(encoding="utf-8") != rendered
        )
        if should_write:
            write_text(paper_path, rendered)
            paper_cards_written += 1
    topic_cards = group_cards_by_topic(cards)
    artifacts = _collect_research_artifacts(paths)

    _manual_save_step(progress, "Writing index pages")
    write_text(paths.indexes / "prompts.md", render_prompts_index(runs))
    write_text(paths.indexes / "papers.md", render_papers_index(cards))
    write_text(paths.indexes / "topics.md", render_topics_index(topic_cards))
    write_text(paths.indexes / "missing-pdfs.md", render_missing_pdfs(runs))
    write_text(paths.indexes / "unmatched.md", render_unmatched_index(manifests))
    write_text(paths.indexes / "zotero-migration.md", render_zotero_migration())
    for folder, (title, empty_message) in ARTIFACT_INDEXES.items():
        write_text(
            paths.indexes / f"{folder}.md",
            render_artifact_index(
                title,
                artifacts.get(folder) or [],
                empty_message=empty_message,
            ),
        )
    dashboard_files_written = _write_dashboard_indexes(
        paths,
        cards,
        runs,
        manifests,
        artifacts,
        topic_cards,
    )
    write_text(paths.indexes / "search-index.md", render_search_index(paths, cards))
    _manual_save_step(progress, "Writing LLM context files")
    write_text(paths.vault / "llms.txt", render_llms_txt())
    write_text(
        paths.vault / "llms-full.txt",
        render_llms_full(cards, runs, manifests, artifacts),
    )
    _manual_save_step(progress, "Writing library exports")
    write_json(paths.exports / "library.json", _cards_to_library_json(cards))
    write_json(paths.exports / "library.csl.json", _cards_to_csl_json(cards))
    write_json(paths.exports / "semantic-neighbors.json", semantic_neighbors_export(cards))
    write_library_bib(cards, paths.exports / "library.bib", metadata_root=paths.raw_metadata)

    _manual_save_step(progress, "Writing topic pages")
    for topic, topic_list in topic_cards.items():
        write_text(paths.topics / f"{topic_slug(topic)}.md", render_topic_page(topic, topic_list))
    _manual_save_step(progress, "Writing run notes")
    for run in runs:
        _write_run(paths, run, cards)
    return {
        "papers": len(cards),
        "runs": len(runs),
        "manifests": len(manifests),
        "topics": len(topic_cards),
        "paper_cards_written": paper_cards_written,
        "cards_normalized": cards_normalized,
        "pdf_filenames_normalized": pdf_filenames_normalized,
        "cross_run_links_synced": cross_run_links_synced,
        "index_files_written": 6 + len(ARTIFACT_INDEXES) + dashboard_files_written + 1,
        "llm_files_written": 2,
        "export_files_written": 4,
        "topic_pages_written": len(topic_cards),
        "run_notes_written": len(runs),
    }


def rebuild_vault(vault: Path | str) -> dict[str, int]:
    paths = initialize_vault(vault, rebuild=False)
    return _rebuild_indexes(paths)


def concept_index(vault: Path | str) -> dict[str, Any]:
    paths = initialize_vault(vault, rebuild=False)
    artifacts = _collect_research_artifacts(paths)
    concepts = artifacts.get("concepts") or []
    title, empty_message = ARTIFACT_INDEXES["concepts"]
    index_path = paths.indexes / "concepts.md"
    write_text(
        index_path,
        render_artifact_index(title, concepts, empty_message=empty_message),
    )
    cards = load_source_cards(paths)
    runs = load_run_records(paths)
    manifests = load_import_manifests(paths)
    write_text(paths.vault / "llms.txt", render_llms_txt())
    write_text(
        paths.vault / "llms-full.txt",
        render_llms_full(cards, runs, manifests, artifacts),
    )
    return {
        "vault": str(paths.vault),
        "index": ensure_relative(index_path, paths.vault),
        "concepts": len(concepts),
        "llm_files_written": 2,
    }
