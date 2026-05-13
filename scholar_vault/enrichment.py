from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

from .citations import (
    EnrichmentOptions,
    EnrichmentProgress,
    EnrichmentResult,
    abstract_fingerprint,
    card_fingerprint,
    refresh_metadata_completeness,
)
from .models import SourceCard
from .rebuild import _rebuild_indexes
from .render import render_paper_markdown
from .sources import (
    VaultPaths,
    clean_markdown_text,
    infer_year,
    load_source_cards,
    normalize_copied_abstract,
    normalize_doi,
    normalize_keywords,
    write_text,
)

ProgressCallback = Any
ManualSaveProgress = Any


def _manual_save_step(progress: ManualSaveProgress | None, message: str) -> None:
    if progress is not None:
        progress(message)


def _now_iso() -> str:
    return datetime.now().astimezone().replace(microsecond=0).isoformat()


def _merge_unique(existing: list[str], incoming: list[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for item in [*existing, *incoming]:
        cleaned = item.strip()
        if not cleaned:
            continue
        key = cleaned.casefold()
        if key not in seen:
            seen.add(key)
            merged.append(cleaned)
    return merged


def initialize_vault(vault: Path | str, *, rebuild: bool = True) -> VaultPaths:
    from .importer import initialize_vault as initialize

    return initialize(vault, rebuild=rebuild)


def _save_card(paths: VaultPaths, card: SourceCard) -> None:
    write_text(paths.papers / f"{card.slug}.md", render_paper_markdown(card))


def enrich_cards(paths: VaultPaths, cards: list[SourceCard], options: EnrichmentOptions, **kwargs):
    from . import importer

    return importer.enrich_cards(paths, cards, options, **kwargs)


def _enrichment_progress_message(
    card: SourceCard,
    status: str,
    *,
    abstracts: bool = False,
    keywords: bool = False,
) -> str:
    stage = "keywords" if keywords else "abstracts" if abstracts else "citations"
    identifier = card.citekey or card.slug
    title = " ".join((card.title or identifier).split())
    context: list[str] = []
    if keywords:
        context.append(
            f"state={card.publication_keywords_status if not card.keywords else 'present'}"
        )
        context.append(f"count={len(card.keywords)}")
        context.append(f"pdf={'yes' if card.pdf else 'no'}")
    elif abstracts:
        context.append(f"state={card.abstract_status}")
        if card.abstract_source:
            context.append(f"source={card.abstract_source}")
        context.append(f"pdf={'yes' if card.pdf else 'no'}")
        if card.abstract_lock:
            context.append("locked")
    else:
        context.append(f"state={card.citation_status}")
        if card.citation_source:
            context.append(f"source={card.citation_source}")
        if card.enrichment_missing:
            context.append(f"missing={','.join(card.enrichment_missing)}")
        if card.doi:
            context.append(f"doi={card.doi}")
    return f"Enriching {stage} [{status}]: {identifier} // {title} // {'; '.join(context)}"


def _enrichment_detail(
    paths: VaultPaths,
    card: SourceCard,
    result: EnrichmentResult,
    *,
    abstracts: bool,
    keywords: bool = False,
) -> dict[str, Any]:
    if result.skipped:
        category = "skipped"
    elif not abstracts and not keywords and card.enrichment_status == "incomplete":
        category = "incomplete"
    else:
        category = result.status

    if keywords:
        source = (
            result.source
            or card.publication_keywords_source
            or ("pdf_extracted" if card.keywords else None)
        )
    else:
        source = card.abstract_source if abstracts else card.citation_source or card.doi_source
    return {
        "kind": "keywords" if keywords else "abstract" if abstracts else "citation",
        "category": category,
        "status": result.status,
        "citekey": card.citekey or card.slug,
        "title": card.title,
        "paper_path": f"papers/{card.slug}.md",
        "paper_file": str(paths.papers / f"{card.slug}.md"),
        "pdf": card.pdf,
        "pdf_file": str(paths.vault / card.pdf) if card.pdf else None,
        "doi": card.doi,
        "authors": list(card.authors),
        "authors_preview": card.authors_preview,
        "year": card.year,
        "venue": card.venue,
        "url": card.url,
        "source": source,
        "missing_fields": list(result.missing_fields or card.enrichment_missing),
        "keywords": list(card.keywords),
        "message": result.message,
        "changed": result.changed,
        "skipped": result.skipped,
    }


def _clean_manual_field(value: str | int | None) -> str | None:
    if value is None:
        return None
    cleaned = clean_markdown_text(str(value))
    return cleaned or None


def _parse_manual_authors(authors: str | Iterable[str] | None) -> list[str] | None:
    if authors is None:
        return None
    if isinstance(authors, str):
        text = authors.replace("\r\n", "\n").replace("\r", "\n").strip()
        if not text:
            return None
        parts = re.split(r"\n+|;|\s+and\s+|\s*&\s*", text)
    else:
        parts = list(authors)
    cleaned = [clean_markdown_text(str(part)) for part in parts]
    return [author for author in cleaned if author]


def set_manual_metadata(
    vault: Path | str,
    citekey: str,
    *,
    doi: str | None = None,
    authors: str | Iterable[str] | None = None,
    year: str | int | None = None,
    venue: str | None = None,
    url: str | None = None,
    lock: bool = False,
    progress: ManualSaveProgress | None = None,
) -> dict[str, Any]:
    _manual_save_step(progress, "Opening vault")
    paths = initialize_vault(vault)
    _manual_save_step(progress, "Normalizing metadata fields")
    cleaned_doi = _clean_manual_field(doi)
    normalized_doi = normalize_doi(cleaned_doi) if cleaned_doi else None
    if normalized_doi and not normalized_doi.startswith("10."):
        raise ValueError("Manual DOI must look like a DOI, for example 10.xxxx/example.")
    cleaned_authors = _parse_manual_authors(authors)
    cleaned_year = infer_year(year)
    cleaned_venue = _clean_manual_field(venue)
    cleaned_url = _clean_manual_field(url)
    if not any([normalized_doi, cleaned_authors, cleaned_year, cleaned_venue, cleaned_url]):
        raise ValueError("Provide at least one metadata field to save.")

    _manual_save_step(progress, "Loading paper cards")
    cards = load_source_cards(paths)
    card = next((item for item in cards if item.citekey == citekey or item.slug == citekey), None)
    if card is None:
        raise ValueError(f"No paper card found for citekey or slug: {citekey}")

    _manual_save_step(progress, "Updating citation metadata")
    if normalized_doi:
        card.doi = normalized_doi
        card.doi_status = "verified"
        card.doi_source = "manual"
        card.doi_confidence = 1.0
    elif card.doi and card.doi_status == "ambiguous":
        card.doi = normalize_doi(card.doi)
        card.doi_status = "verified"
        card.doi_source = card.doi_source or "manual"
        card.doi_confidence = card.doi_confidence or 1.0
    elif not card.doi and card.doi_status == "ambiguous":
        card.doi_status = "missing"
        card.doi_source = None
        card.doi_confidence = None
    if cleaned_authors is not None:
        card.authors = cleaned_authors
        card.authors_preview = ", ".join(cleaned_authors)
    if cleaned_year:
        card.year = cleaned_year
    if cleaned_venue:
        card.venue = cleaned_venue
    if cleaned_url:
        card.url = cleaned_url

    checked_at = _now_iso()
    card.citation_status = "verified"
    card.citation_source = "manual"
    card.citation_last_checked = checked_at
    card.citation_enriched_at = checked_at
    card.citation_retries = 0
    card.citation_input_fingerprint = card_fingerprint(card)
    if lock:
        card.metadata_lock = True
    card.enrichment_refresh = False
    refresh_metadata_completeness(card)
    if card.enrichment_missing and card.metadata_lock:
        card.citation_skip_reason = (
            "manual metadata locked; missing fields accepted: "
            + ", ".join(card.enrichment_missing)
        )
    elif card.enrichment_missing:
        card.citation_status = "generated"
        refresh_metadata_completeness(card)
        card.citation_skip_reason = (
            f"manual metadata incomplete: {', '.join(card.enrichment_missing)}"
        )
    else:
        card.citation_skip_reason = None

    _manual_save_step(progress, "Writing paper card")
    _save_card(paths, card)
    _manual_save_step(progress, "Rebuilding derived files")
    _rebuild_indexes(paths, progress=progress)
    _manual_save_step(progress, "Manual save complete")
    return {
        "citekey": card.citekey or card.slug,
        "paper": f"papers/{card.slug}.md",
        "doi": card.doi,
        "authors": list(card.authors),
        "year": card.year,
        "venue": card.venue,
        "url": card.url,
        "metadata_lock": card.metadata_lock,
        "citation_status": card.citation_status,
        "doi_status": card.doi_status,
        "enrichment_status": card.enrichment_status,
        "missing_fields": list(card.enrichment_missing),
    }


def set_manual_abstract(
    vault: Path | str,
    citekey: str,
    abstract: str,
    *,
    source_url: str | None = None,
    lock: bool = True,
    progress: ManualSaveProgress | None = None,
) -> dict[str, str | bool]:
    _manual_save_step(progress, "Opening vault")
    paths = initialize_vault(vault)
    _manual_save_step(progress, "Cleaning abstract text")
    cleaned = clean_markdown_text(normalize_copied_abstract(abstract))
    if not cleaned:
        raise ValueError("Manual abstract text is empty.")

    _manual_save_step(progress, "Loading paper cards")
    cards = load_source_cards(paths)
    card = next((item for item in cards if item.citekey == citekey or item.slug == citekey), None)
    if card is None:
        raise ValueError(f"No paper card found for citekey or slug: {citekey}")

    _manual_save_step(progress, "Updating abstract metadata")
    checked_at = _now_iso()
    card.abstract = cleaned
    card.abstract_status = "manual_lock" if lock else "resolved"
    card.abstract_source = "manual"
    card.abstract_source_url = source_url
    card.abstract_confidence = 1.0
    card.abstract_last_checked = checked_at
    card.abstract_enriched_at = checked_at
    card.abstract_input_fingerprint = abstract_fingerprint(card)
    card.abstract_lock = lock
    card.enrichment_refresh = False
    _manual_save_step(progress, "Writing paper card")
    _save_card(paths, card)
    _manual_save_step(progress, "Rebuilding derived files")
    _rebuild_indexes(paths, progress=progress)
    _manual_save_step(progress, "Manual save complete")
    return {
        "citekey": card.citekey or card.slug,
        "paper": f"papers/{card.slug}.md",
        "locked": lock,
    }


def set_manual_keywords(
    vault: Path | str,
    citekey: str,
    keywords: str | Iterable[str],
    *,
    replace: bool = False,
    progress: ManualSaveProgress | None = None,
) -> dict[str, str | int | list[str]]:
    _manual_save_step(progress, "Opening vault")
    paths = initialize_vault(vault)
    _manual_save_step(progress, "Normalizing keyword separators")
    raw_keywords = keywords.splitlines() if isinstance(keywords, str) else keywords
    cleaned_keywords = normalize_keywords(raw_keywords)
    if not cleaned_keywords:
        raise ValueError("Manual keyword text is empty.")

    _manual_save_step(progress, "Loading paper cards")
    cards = load_source_cards(paths)
    card = next((item for item in cards if item.citekey == citekey or item.slug == citekey), None)
    if card is None:
        raise ValueError(f"No paper card found for citekey or slug: {citekey}")

    _manual_save_step(progress, "Updating keyword metadata")
    card.keywords = cleaned_keywords if replace else _merge_unique(card.keywords, cleaned_keywords)
    card.publication_keywords_status = "present"
    card.publication_keywords_source = "manual"
    card.enrichment_refresh = False
    card.enrichment_missing = [
        field for field in card.enrichment_missing if field != "keywords"
    ]
    _manual_save_step(progress, "Writing paper card")
    _save_card(paths, card)
    _manual_save_step(progress, "Rebuilding derived files")
    _rebuild_indexes(paths, progress=progress)
    _manual_save_step(progress, "Manual save complete")
    return {
        "citekey": card.citekey or card.slug,
        "paper": f"papers/{card.slug}.md",
        "count": len(card.keywords),
        "keywords": list(card.keywords),
    }


def confirm_no_publication_keywords(
    vault: Path | str,
    citekey: str,
    *,
    progress: ManualSaveProgress | None = None,
) -> dict[str, str | int | list[str]]:
    _manual_save_step(progress, "Opening vault")
    paths = initialize_vault(vault)
    _manual_save_step(progress, "Loading paper cards")
    cards = load_source_cards(paths)
    card = next((item for item in cards if item.citekey == citekey or item.slug == citekey), None)
    if card is None:
        raise ValueError(f"No paper card found for citekey or slug: {citekey}")

    _manual_save_step(progress, "Confirming source keyword absence")
    card.keywords = []
    card.publication_keywords_status = "absent"
    card.publication_keywords_source = "manual"
    card.enrichment_refresh = False
    card.enrichment_missing = [
        field for field in card.enrichment_missing if field != "keywords"
    ]
    _manual_save_step(progress, "Writing paper card")
    _save_card(paths, card)
    _manual_save_step(progress, "Rebuilding derived files")
    _rebuild_indexes(paths, progress=progress)
    _manual_save_step(progress, "Manual save complete")
    return {
        "citekey": card.citekey or card.slug,
        "paper": f"papers/{card.slug}.md",
        "count": 0,
        "keywords": [],
        "status": card.publication_keywords_status,
    }


def _enrichment_counts(details: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "processed": len([row for row in details if not row.get("skipped")]),
        "changed": len([row for row in details if row.get("changed")]),
        "skipped": len([row for row in details if row.get("skipped")]),
        "generated": len([row for row in details if row.get("status") == "generated"]),
        "resolved": len([row for row in details if row.get("status") == "resolved"]),
        "verified": len([row for row in details if row.get("status") == "verified"]),
        "ambiguous": len([row for row in details if row.get("status") == "ambiguous"]),
        "unresolved": len([row for row in details if row.get("status") == "unresolved"]),
    }


def _run_enrichment_pass(
    paths: VaultPaths,
    cards: list[SourceCard],
    options: EnrichmentOptions,
    *,
    abstracts: bool = False,
    keywords: bool = False,
    progress: ProgressCallback | None = None,
) -> tuple[list[EnrichmentResult], list[dict[str, Any]]]:
    def report_progress(card: SourceCard, index: int, total: int, status: str) -> None:
        if progress:
            progress(
                _enrichment_progress_message(
                    card,
                    status,
                    abstracts=abstracts,
                    keywords=keywords,
                ),
                index,
                total,
            )

    results = enrich_cards(paths, cards, options, progress=report_progress)
    details = [
        _enrichment_detail(paths, card, result, abstracts=abstracts, keywords=keywords)
        for card, result in zip(cards, results, strict=False)
    ]
    return results, details


def enrich_vault(
    vault: Path | str,
    *,
    citekey: str | None = None,
    only: str = "all",
    refresh: bool = False,
    refresh_abstracts: bool = False,
    retry_failed: bool = False,
    dry_run: bool = False,
    force: bool = False,
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    valid_only = {
        "all",
        "missing-doi",
        "missing-bibtex",
        "missing-abstract",
        "missing-keywords",
    }
    if only not in valid_only:
        raise ValueError(
            "--only must be one of: all, missing-doi, missing-bibtex, "
            "missing-abstract, missing-keywords"
        )

    paths = initialize_vault(vault)
    cards = load_source_cards(paths)
    filter_citekey = citekey
    if citekey:
        cards = [card for card in cards if citekey in {card.citekey, card.slug}]
        if not cards:
            raise ValueError(f"No paper card found for citekey: {citekey}")
        filter_citekey = None

    citation_details: list[dict[str, Any]] = []
    abstract_details: list[dict[str, Any]] = []
    keyword_details: list[dict[str, Any]] = []
    changed_slugs: set[str] = set()

    if only in {"all", "missing-doi", "missing-bibtex"}:
        citation_results, citation_details = _run_enrichment_pass(
            paths,
            cards,
            EnrichmentOptions(
                only=only,  # type: ignore[arg-type]
                citekey=filter_citekey,
                refresh=refresh,
                retry_failed=retry_failed,
                dry_run=dry_run,
                force=force,
            ),
            progress=progress,
        )
        changed_slugs.update(
            card.slug
            for card, result in zip(cards, citation_results, strict=False)
            if result.changed
        )

    if only in {"all", "missing-abstract"}:
        abstract_results, abstract_details = _run_enrichment_pass(
            paths,
            cards,
            EnrichmentOptions(
                only="missing-abstract" if only == "missing-abstract" else "all",
                citekey=filter_citekey,
                abstracts=True,
                refresh_abstracts=refresh_abstracts,
                retry_failed=retry_failed,
                dry_run=dry_run,
                force=force,
            ),
            abstracts=True,
            progress=progress,
        )
        changed_slugs.update(
            card.slug
            for card, result in zip(cards, abstract_results, strict=False)
            if result.changed
        )

    if only in {"all", "missing-keywords"}:
        keyword_results, keyword_details = _run_enrichment_pass(
            paths,
            cards,
            EnrichmentOptions(
                only="missing-keywords",
                citekey=filter_citekey,
                refresh=refresh,
                retry_failed=retry_failed,
                dry_run=dry_run,
                force=force,
            ),
            keywords=True,
            progress=progress,
        )
        changed_slugs.update(
            card.slug
            for card, result in zip(cards, keyword_results, strict=False)
            if result.changed
        )

    if not dry_run:
        for card in cards:
            if card.slug in changed_slugs:
                _save_card(paths, card)
        _rebuild_indexes(paths)

    details = [*citation_details, *abstract_details, *keyword_details]
    counts = _enrichment_counts(details)
    return {
        **counts,
        "citation_enrichment": _enrichment_counts(citation_details),
        "abstract_enrichment": _enrichment_counts(abstract_details),
        "keyword_enrichment": _enrichment_counts(keyword_details),
        "enrichment_details": citation_details,
        "abstract_details": abstract_details,
        "keyword_details": keyword_details,
        "details": details,
    }


def enrich_citations(
    vault: Path | str,
    *,
    citekey: str | None = None,
    only: str = "all",
    refresh: bool = False,
    abstracts: bool = False,
    refresh_abstracts: bool = False,
    retry_failed: bool = False,
    dry_run: bool = False,
    force: bool = False,
    progress: EnrichmentProgress | None = None,
) -> dict[str, Any]:
    valid_only = {
        "all",
        "missing-doi",
        "missing-bibtex",
        "missing-abstract",
        "missing-keywords",
    }
    if only not in valid_only:
        raise ValueError(
            "--only must be one of: all, missing-doi, missing-bibtex, "
            "missing-abstract, missing-keywords"
        )

    enrich_keywords = only == "missing-keywords"
    enrich_abstracts = (
        not enrich_keywords and (abstracts or refresh_abstracts or only == "missing-abstract")
    )

    paths = initialize_vault(vault)
    cards = load_source_cards(paths)
    options = EnrichmentOptions(
        only=only,  # type: ignore[arg-type]
        citekey=citekey,
        refresh=refresh,
        abstracts=enrich_abstracts,
        refresh_abstracts=refresh_abstracts,
        retry_failed=retry_failed,
        dry_run=dry_run,
        force=force,
    )
    results = enrich_cards(paths, cards, options, progress=progress)
    if citekey and all(result.skipped and result.message == "citekey filter" for result in results):
        raise ValueError(f"No paper card found for citekey: {citekey}")

    details = [
        _enrichment_detail(
            paths,
            card,
            result,
            abstracts=enrich_abstracts,
            keywords=enrich_keywords,
        )
        for card, result in zip(cards, results, strict=False)
    ]

    if not dry_run:
        for card, result in zip(cards, results, strict=False):
            if result.changed:
                _save_card(paths, card)
        _rebuild_indexes(paths)

    return {
        "processed": len([result for result in results if not result.skipped]),
        "changed": len([result for result in results if result.changed]),
        "skipped": len([result for result in results if result.skipped]),
        "generated": len([result for result in results if result.status == "generated"]),
        "resolved": len([result for result in results if result.status == "resolved"]),
        "verified": len([result for result in results if result.status == "verified"]),
        "ambiguous": len([result for result in results if result.status == "ambiguous"]),
        "unresolved": len([result for result in results if result.status == "unresolved"]),
        "abstracts": len(
            [
                result
                for result in results
                if enrich_abstracts and result.status in {"resolved", "verified"}
            ]
        ),
        "keywords": len(
            [
                result
                for result in results
                if enrich_keywords and result.status == "resolved"
            ]
        ),
        "details": details,
    }
