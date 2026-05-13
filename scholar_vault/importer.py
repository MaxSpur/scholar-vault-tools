from __future__ import annotations

import hashlib
import json
import re
import shutil
import urllib.parse
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from datetime import datetime
from pathlib import Path
from textwrap import dedent
from typing import Any

from pydantic import ValidationError

from .bibtex import (
    extract_pdf_paths,
    parse_bibtex_file,
    render_card_bibtex,
    split_bibtex_authors,
    write_library_bib,
)
from .citations import (
    EnrichmentOptions,
    EnrichmentProgress,
    EnrichmentResult,
    abstract_fingerprint,
    card_fingerprint,
    enrich_cards,
    extract_pdf_keywords,
    refresh_metadata_completeness,
)
from .matcher import (
    best_pdf_match,
    build_pdf_candidate,
    match_candidate_to_cards,
    score_title_match,
)
from .models import (
    ImportCanceled,
    ImportLog,
    ImportLogEntry,
    ImportManifest,
    ImportManifestEntry,
    Link,
    MatchDecision,
    MatchReviewRequest,
    PdfCandidate,
    RationalePoint,
    RunRecord,
    RunResultRecord,
    ScholarLabsExport,
    ScholarLabsResult,
    SourceCard,
    SummarySource,
)
from .references import REFERENCE_FORMATS, REFERENCE_STYLES, render_card_reference
from .render import (
    group_cards_by_topic,
    render_artifact_index,
    render_llms_full,
    render_llms_txt,
    render_missing_pdfs,
    render_paper_markdown,
    render_papers_index,
    render_project_map_markdown,
    render_project_markdown,
    render_prompts_index,
    render_run_markdown,
    render_topic_page,
    render_topics_index,
    render_unmatched_index,
    render_vault_agents,
    render_vault_readme,
    render_zotero_migration,
)
from .sources import (
    VaultPaths,
    build_card_slug,
    build_citekey,
    build_pdf_filename,
    clean_markdown_text,
    dump_frontmatter,
    ensure_relative,
    infer_run_title,
    infer_topics,
    infer_year,
    load_import_manifests,
    load_run_records,
    load_source_cards,
    normalize_copied_abstract,
    normalize_doi,
    normalize_keywords,
    normalize_title,
    parse_people,
    read_frontmatter_markdown,
    run_display_title,
    run_note_filename,
    run_note_path,
    slugify_text,
    topic_slug,
    write_json,
    write_text,
    write_yaml,
)

ConfirmCallback = Callable[[str], bool]
MatchReviewCallback = Callable[[MatchReviewRequest], bool]
ProgressCallback = Callable[[str, int | None, int | None], None]
ManualSaveProgress = Callable[[str], None]

PDF_SCAN_CACHE_FILENAME = ".scholar-vault-pdf-scan-cache"
PDF_SCAN_CACHE_SCHEMA_VERSION = 1
PROMPT_BOILERPLATE_TOPICS = (
    "Find",
    "Paper",
    "Papers",
    "Peer",
    "Peer Reviewed",
    "Reviewed",
    "Important",
    "That",
    "Study",
    "Studies",
    "Proposal",
    "Research",
    "Current",
    "Recent",
)
PROMPT_BOILERPLATE_TOPIC_MAP = {topic: None for topic in PROMPT_BOILERPLATE_TOPICS}
NOISY_TOPIC_KEYS = {
    normalize_title(topic)
    for topic in PROMPT_BOILERPLATE_TOPICS
} | {
    "scholar",
    "source",
    "sources",
}
SEARCH_STOPWORDS = {
    "about",
    "after",
    "also",
    "among",
    "based",
    "between",
    "could",
    "from",
    "have",
    "into",
    "more",
    "paper",
    "papers",
    "research",
    "results",
    "show",
    "shows",
    "study",
    "studies",
    "that",
    "their",
    "these",
    "this",
    "through",
    "using",
    "were",
    "with",
}
ARTIFACT_INDEXES = {
    "concepts": ("Concepts", "No concept cards have been created yet."),
    "syntheses": ("Syntheses", "No synthesis notes have been created yet."),
    "tasks": ("Tasks", "No follow-up task notes have been created yet."),
    "projects": ("Projects", "No project workspaces have been created yet."),
    "proposals": ("Proposals", "No proposal workspaces have been created yet."),
}
ARTIFACT_DEFAULT_TYPES = {
    "concepts": "concept",
    "syntheses": "synthesis",
    "tasks": "task",
    "projects": "project",
    "proposals": "proposal",
}


def _now_iso() -> str:
    return datetime.now().astimezone().replace(microsecond=0).isoformat()


def _manual_save_step(progress: ManualSaveProgress | None, message: str) -> None:
    if progress is not None:
        progress(message)


def _parse_datetime(value: str | None) -> datetime:
    if not value:
        return datetime.now().astimezone()
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now().astimezone()


def _run_slug(export: ScholarLabsExport, export_path: Path) -> tuple[str, str]:
    exported_at = _parse_datetime(export.exported_at)
    date = exported_at.date().isoformat()
    prompt_slug = slugify_text(export.prompt or export_path.stem, max_length=60)
    return f"{date}_{prompt_slug}", date


def _run_ref_from_parts(
    run_id: str,
    date: str,
    title: str | None,
    prompt: str,
    note_file: str | None = None,
) -> str:
    return run_note_path(run_id, date, title, prompt, note_file)


def _run_ref(run: RunRecord) -> str:
    return _run_ref_from_parts(run.slug, run.date, run.title, run.prompt, run.note_file)


def _legacy_run_ref(run_id: str) -> str:
    return f"runs/{run_id}/index.md"


def _normalize_run_ref(ref: str, run_refs: dict[str, str] | None = None) -> str:
    parts = Path(ref).parts
    if len(parts) == 3 and parts[0] == "runs":
        if run_refs and parts[1] in run_refs:
            return run_refs[parts[1]]
        if parts[2] == "index.md":
            stem_title = infer_run_title(parts[1])
            return _run_ref_from_parts(parts[1], parts[1].split("_", 1)[0], stem_title, stem_title)
    return ref


def _result_key(result: ScholarLabsResult | RunResultRecord) -> str:
    if result.scholar_cid:
        return f"cid:{result.scholar_cid}"
    return f"title:{normalize_title(result.title)}"


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _copy_invalid_export(paths: VaultPaths, export_file: Path, raw_text: str) -> str:
    timestamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    stem = slugify_text(export_file.stem, max_length=40)
    failed_path = paths.raw_scholar_labs / f"invalid-{timestamp}-{stem}.json"
    failed_path.write_text(raw_text, encoding="utf-8")
    return ensure_relative(failed_path, paths.vault)


def _load_validated_scholar_export(paths: VaultPaths, export_file: Path) -> ScholarLabsExport:
    raw_text = export_file.read_text(encoding="utf-8")
    try:
        return ScholarLabsExport.model_validate_json(raw_text)
    except ValidationError as exc:
        failed_copy = _copy_invalid_export(paths, export_file, raw_text)
        details = "; ".join(error["msg"] for error in exc.errors()) or "validation failed"
        raise ValueError(
            "Invalid Google Scholar Labs export. This likely means the browser exporter "
            "ran on the wrong page or its Scholar-specific gs_* selectors are broken. "
            f"The raw failed export was copied to {failed_copy}. Details: {details}"
        ) from exc


def _prefer_existing(value: str | None) -> bool:
    return bool(value and value.strip() and value.strip() != "No summary yet.")


def _merge_links(existing: list[Link], incoming: list[Link]) -> list[Link]:
    merged: list[Link] = []
    seen: set[tuple[str, str, str | None, int | None]] = set()
    for link in [*existing, *incoming]:
        key = (link.label, link.url, link.kind, link.count)
        if key not in seen:
            seen.add(key)
            merged.append(link)
    return merged


def _merge_rationale(
    existing: list[RationalePoint],
    incoming: list[RationalePoint],
) -> list[RationalePoint]:
    merged: list[RationalePoint] = []
    seen: set[tuple[str, str]] = set()
    for point in [*existing, *incoming]:
        key = (point.label, point.text)
        if key not in seen:
            seen.add(key)
            merged.append(point)
    return merged


def _summary_source_from_result(
    result: ScholarLabsResult,
    *,
    run_ref: str,
    prompt: str,
    run_refs: dict[str, str] | None = None,
) -> SummarySource | None:
    summary = clean_markdown_text(result.summary)
    if not _prefer_existing(summary):
        return None
    return SummarySource(
        run=_normalize_run_ref(run_ref, run_refs),
        prompt=prompt,
        rank=result.rank,
        summary=summary,
        rationale_points=result.rationale_points,
    )


def _merge_summary_sources(
    existing: list[SummarySource],
    incoming: list[SummarySource],
    *,
    run_refs: dict[str, str] | None = None,
) -> list[SummarySource]:
    merged: list[SummarySource] = []
    by_run: dict[str, int] = {}
    seen_without_run: set[str] = set()
    for source in [*existing, *incoming]:
        source = source.model_copy(deep=True)
        source.run = _normalize_run_ref(source.run, run_refs)
        source.summary = clean_markdown_text(source.summary)
        if not _prefer_existing(source.summary):
            continue
        if source.run:
            if source.run in by_run:
                merged[by_run[source.run]] = source
            else:
                by_run[source.run] = len(merged)
                merged.append(source)
            continue
        key = normalize_title(source.summary)
        if key not in seen_without_run:
            seen_without_run.add(key)
            merged.append(source)
    return merged


def _backfill_summary_source_from_card(
    card: SourceCard,
    *,
    run_refs: dict[str, str] | None = None,
) -> list[SummarySource]:
    if not _prefer_existing(card.summary) or card.summary_sources:
        return card.summary_sources
    return [
        SummarySource(
            run=_normalize_run_ref(run_ref, run_refs),
            summary=card.summary,
            rationale_points=card.why_this_source_matters,
        )
        for run_ref in card.discovered_in
    ]


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


def _should_replace_title(existing: SourceCard, incoming_title: str) -> bool:
    if not existing.title:
        return True
    if normalize_title(existing.title) == normalize_title(incoming_title):
        return False
    if existing.title == existing.slug.replace("-", " "):
        return True
    return len(existing.title.split()) < 3 and len(incoming_title.split()) >= 3


def _candidate_url(links: list[Link]) -> str | None:
    for kind in ("html", "publication", "landing"):
        for link in links:
            if (link.kind or "").casefold() == kind:
                return link.url
    return links[0].url if links else None


def _find_existing_card(
    cards: list[SourceCard],
    *,
    doi: str | None = None,
    scholar_cid: str | None = None,
    citekey: str | None = None,
    title: str | None = None,
) -> SourceCard | None:
    normalized_doi = normalize_doi(doi)
    normalized_title = normalize_title(title)
    for card in cards:
        if normalized_doi and normalize_doi(card.doi) == normalized_doi:
            return card
    for card in cards:
        if scholar_cid and card.scholar_cid == scholar_cid:
            return card
    for card in cards:
        if citekey and card.citekey == citekey:
            return card
    for card in cards:
        if normalized_title and normalize_title(card.title) == normalized_title:
            return card
    return None


def _new_card_from_result(
    result: ScholarLabsResult,
    *,
    run_ref: str,
    prompt: str,
    existing_cards: list[SourceCard],
) -> SourceCard:
    authors = parse_people(result.authors_preview)
    summary_source = _summary_source_from_result(result, run_ref=run_ref, prompt=prompt)
    citekey = build_citekey(
        result.title,
        authors,
        result.year,
        authors_preview=result.authors_preview,
        existing_keys=[card.citekey for card in existing_cards if card.citekey],
    )
    slug = build_card_slug(citekey, result.title, [card.slug for card in existing_cards])
    return SourceCard(
        slug=slug,
        citekey=citekey,
        title=result.title,
        authors_preview=result.authors_preview,
        authors=authors,
        year=result.year,
        venue=result.venue,
        url=_candidate_url(result.links),
        source_kind="scholar_labs",
        scholar_cid=result.scholar_cid,
        discovered_in=[run_ref],
        topics=infer_topics(prompt, result.rationale_points),
        status="active",
        pdf_status="missing",
        doi_status="missing",
        citation_status="missing",
        links=result.links,
        summary=clean_markdown_text(result.summary) or "No summary yet.",
        summary_sources=[summary_source] if summary_source else [],
        why_this_source_matters=result.rationale_points,
    )


def _merge_cards(existing: SourceCard, incoming: SourceCard) -> SourceCard:
    existing.discovered_in = [_normalize_run_ref(item) for item in existing.discovered_in]
    incoming.discovered_in = [_normalize_run_ref(item) for item in incoming.discovered_in]
    existing.summary_sources = _backfill_summary_source_from_card(existing)
    if _should_replace_title(existing, incoming.title):
        existing.title = incoming.title
    existing.citekey = existing.citekey or incoming.citekey
    existing.authors_preview = existing.authors_preview or incoming.authors_preview
    if not existing.authors and incoming.authors:
        existing.authors = incoming.authors
    existing.year = existing.year or incoming.year
    existing.venue = existing.venue or incoming.venue
    existing.doi = existing.doi or incoming.doi
    existing.url = existing.url or incoming.url
    existing.scholar_cid = existing.scholar_cid or incoming.scholar_cid
    existing.discovered_in = _merge_unique(existing.discovered_in, incoming.discovered_in)
    existing.topics = _merge_unique(existing.topics, incoming.topics)
    existing.keywords = _merge_unique(existing.keywords, incoming.keywords)
    if existing.keywords and existing.publication_keywords_status != "present":
        existing.publication_keywords_status = "present"
        existing.publication_keywords_source = (
            existing.publication_keywords_source
            or incoming.publication_keywords_source
            or "imported"
        )
    existing.links = _merge_links(existing.links, incoming.links)
    if not _prefer_existing(existing.summary) and incoming.summary:
        existing.summary = incoming.summary
    existing.summary_sources = _merge_summary_sources(
        existing.summary_sources,
        incoming.summary_sources,
    )
    existing.why_this_source_matters = _merge_rationale(
        existing.why_this_source_matters,
        incoming.why_this_source_matters,
    )
    if not existing.notes and incoming.notes:
        existing.notes = incoming.notes
    if incoming.pdf and not existing.pdf:
        existing.pdf = incoming.pdf
    if existing.pdf or incoming.pdf_status == "attached":
        existing.pdf_status = "attached"
    if incoming.status == "candidate" and existing.status != "active":
        existing.status = "candidate"
    if existing.citation_status in {"partial", "complete", "preview"}:
        existing.citation_status = "missing"
    if incoming.citation_status in {"generated", "verified"} and existing.citation_status not in {
        "verified",
        "manual_lock",
    }:
        existing.citation_status = incoming.citation_status
    return existing


def _save_card(paths: VaultPaths, card: SourceCard) -> None:
    write_text(paths.papers / f"{card.slug}.md", render_paper_markdown(card))


def _prepare_card_for_result(
    cards: list[SourceCard],
    result: ScholarLabsResult,
    *,
    run_ref: str,
    prompt: str,
    include_without_pdf: bool = False,
) -> tuple[SourceCard, bool, dict | None]:
    incoming = _new_card_from_result(result, run_ref=run_ref, prompt=prompt, existing_cards=cards)
    if include_without_pdf:
        incoming.status = "candidate"
        incoming.pdf_status = "missing"
        incoming.citation_status = "missing"
    existing = _find_existing_card(
        cards,
        scholar_cid=result.scholar_cid,
        citekey=incoming.citekey,
        title=result.title,
    )
    card_before = existing.model_dump(mode="python") if existing else None
    card = _merge_cards(existing, incoming) if existing else incoming
    if not existing:
        cards.append(card)
    return card, existing is None, card_before


def _copy_pdf_to_vault(
    paths: VaultPaths,
    source_pdf: Path,
    card: SourceCard,
    *,
    original_sha256: str,
) -> tuple[str, bool, bool]:
    if card.pdf:
        existing_destination = paths.vault / card.pdf
        if existing_destination.exists() and _file_sha256(existing_destination) == original_sha256:
            return card.pdf, False, True

    preferred_name = f"{slugify_text(card.citekey or card.slug, max_length=100)}.pdf"
    destination = paths.pdfs / preferred_name
    existing_names = [path.name for path in paths.pdfs.glob("*.pdf")]
    if destination.exists() and _file_sha256(destination) != original_sha256:
        filename = build_pdf_filename(
            card.title,
            card.authors,
            card.year,
            authors_preview=card.authors_preview,
            existing_names=existing_names,
        )
        destination = paths.pdfs / filename

    if destination.exists():
        verified = _file_sha256(destination) == original_sha256
        return ensure_relative(destination, paths.vault), False, verified

    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_destination = destination.with_suffix(".pdf.tmp")
    shutil.copy2(source_pdf, temp_destination)
    verified = _file_sha256(temp_destination) == original_sha256
    if not verified:
        temp_destination.unlink(missing_ok=True)
        raise ValueError(f"Copied PDF failed verification: {source_pdf}")
    temp_destination.replace(destination)
    return ensure_relative(destination, paths.vault), True, True


def _write_log(paths: VaultPaths, command: str, entries: list[ImportLogEntry]) -> None:
    log = ImportLog(command=command, created_at=_now_iso(), entries=entries)
    timestamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    write_yaml(
        paths.raw_imported / f"{timestamp}_{command}.yaml",
        log.model_dump(exclude_none=True),
    )


def _read_run_yaml(path: Path) -> RunRecord:
    import yaml

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return RunRecord.model_validate(data)


def _load_run_record(paths: VaultPaths, run_id: str) -> RunRecord | None:
    for run in load_run_records(paths):
        if run.slug == run_id:
            return run
    return None


def _load_manifest(paths: VaultPaths, run_id: str) -> ImportManifest | None:
    import yaml

    path = paths.runs / run_id / "import-manifest.yaml"
    if not path.exists():
        return None
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return ImportManifest.model_validate(data)


def _write_run(paths: VaultPaths, run: RunRecord, cards: list[SourceCard]) -> None:
    run_dir = paths.runs / run.slug
    run_dir.mkdir(parents=True, exist_ok=True)
    note_name = run_note_filename(run.date, run.title, run.prompt, run.note_file)
    run.note_file = note_name
    write_yaml(run_dir / "index.yaml", run.model_dump(exclude_none=True))
    cards_by_slug = {card.slug: card for card in cards}
    note_path = run_dir / note_name
    write_text(note_path, render_run_markdown(run, cards_by_slug))
    for markdown_path in run_dir.glob("*.md"):
        if markdown_path == note_path:
            continue
        frontmatter, _ = read_frontmatter_markdown(markdown_path)
        if markdown_path.name == "index.md" or markdown_path.stem.startswith(run.date):
            markdown_path.unlink()
        elif (
            frontmatter.get("type") == "scholar_labs_run"
            and frontmatter.get("run_id") == run.slug
        ):
            markdown_path.unlink()


def _write_manifest(paths: VaultPaths, manifest: ImportManifest) -> None:
    run_dir = paths.runs / manifest.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    write_yaml(run_dir / "import-manifest.yaml", manifest.model_dump(exclude_none=True))


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


def _compact_text(value: str | None, *, limit: int = 500) -> str:
    cleaned = clean_markdown_text(value)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3].rstrip(" .,;:") + "..."


def _markdown_cell(value: object) -> str:
    text = _compact_text(str(value) if value is not None else "", limit=220)
    return text.replace("|", r"\|") or "-"


def _markdown_table(
    headers: list[str],
    rows: list[list[object]],
    *,
    empty: str = "No rows.",
) -> list[str]:
    if not rows:
        return [empty]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(_markdown_cell(value) for value in row) + " |")
    return lines


def _paper_link(card: SourceCard) -> str:
    return f"[{card.title}](../papers/{card.slug}.md)"


def _artifact_link(artifact: dict[str, Any]) -> str:
    return f"[{artifact.get('title') or artifact.get('path')}](../{artifact.get('path')})"


def _reading_queue_rows(
    paths: VaultPaths,
    cards: list[SourceCard],
    *,
    heading: str = "PDF reading notes",
) -> list[dict[str, Any]]:
    heading_re = _markdown_heading_re(heading)
    rows: list[dict[str, Any]] = []
    for card in cards:
        if card.status != "active" or not (card.pdf_status == "attached" or card.pdf):
            continue
        if heading_re.search(card.notes or ""):
            continue
        rows.append(
            {
                "paper": f"papers/{card.slug}.md",
                "paper_link": _paper_link(card),
                "citekey": _card_id(card),
                "year": card.year,
                "pdf": card.pdf or "missing",
                "pdf_exists": _card_has_valid_pdf(paths, card),
            }
        )
    return rows


def _metadata_issue_label(card: SourceCard) -> list[str]:
    issue_states = {"incomplete", "ambiguous", "unresolved"}
    issues: list[str] = []
    if card.enrichment_refresh:
        issues.append("metadata refresh requested")
    if card.enrichment_status in issue_states or card.enrichment_missing:
        missing = ", ".join(card.enrichment_missing)
        label = f"metadata {card.enrichment_status}"
        issues.append(f"{label} ({missing})" if missing else label)
    if card.citation_status in {"ambiguous", "unresolved"}:
        issues.append(f"citation {card.citation_status}")
    if card.doi_status in {"ambiguous", "unresolved"}:
        issues.append(f"DOI {card.doi_status}")
    if card.abstract_status in {"missing", "ambiguous", "unresolved"}:
        issues.append(f"abstract {card.abstract_status}")
    if card.pdf and not card.keywords and card.publication_keywords_status != "absent":
        issues.append("missing publication keywords")
    return issues


def _metadata_issue_rows(cards: list[SourceCard]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for card in cards:
        refresh_metadata_completeness(card)
        issues = _metadata_issue_label(card)
        if not issues:
            continue
        rows.append(
            {
                "paper": f"papers/{card.slug}.md",
                "paper_link": _paper_link(card),
                "citekey": _card_id(card),
                "issues": issues,
                "doi": card.doi or "",
                "venue": card.venue or "",
            }
        )
    return rows


def _metadata_not_enriched_rows(cards: list[SourceCard]) -> list[dict[str, Any]]:
    return [
        {
            "paper": f"papers/{card.slug}.md",
            "paper_link": _paper_link(card),
            "citekey": _card_id(card),
            "title": card.title,
        }
        for card in cards
        if card.enrichment_status == "missing"
    ]


def _pdf_issue_summary(
    paths: VaultPaths,
    cards: list[SourceCard],
    manifests: list[ImportManifest],
) -> dict[str, Any]:
    referenced_pdf_paths: set[Path] = set()
    cards_without_pdf: list[dict[str, Any]] = []
    missing_card_pdfs: list[dict[str, Any]] = []
    for card in cards:
        if not card.pdf:
            cards_without_pdf.append(
                {
                    "paper": f"papers/{card.slug}.md",
                    "paper_link": _paper_link(card),
                    "citekey": _card_id(card),
                    "title": card.title,
                }
            )
            continue
        pdf_path = Path(card.pdf)
        if not pdf_path.is_absolute():
            pdf_path = paths.vault / pdf_path
        if pdf_path.exists():
            referenced_pdf_paths.add(pdf_path.resolve())
        else:
            missing_card_pdfs.append(
                {
                    "paper": f"papers/{card.slug}.md",
                    "paper_link": _paper_link(card),
                    "citekey": _card_id(card),
                    "pdf": card.pdf,
                }
            )
    pdf_files = sorted(paths.pdfs.glob("*.pdf"))
    orphan_pdfs = [
        _display_path(path, paths.vault)
        for path in pdf_files
        if path.resolve() not in referenced_pdf_paths
    ]
    duplicate_style = [
        _display_path(path, paths.vault)
        for path in pdf_files
        if re.search(r"-\d+\.pdf$", path.name, flags=re.IGNORECASE)
    ]
    unmatched_rows = _unmatched_rows_from_manifests(manifests)
    return {
        "cards_without_pdf": cards_without_pdf,
        "missing_card_pdfs": missing_card_pdfs,
        "orphan_pdfs": orphan_pdfs,
        "duplicate_style_filenames": duplicate_style,
        "historical_unmatched_entries": len(unmatched_rows),
        "repeated_unmatched_files": _repeated_unmatched_files(unmatched_rows),
    }


def _stale_topic_pages(paths: VaultPaths, topic_cards: dict[str, list[SourceCard]]) -> list[str]:
    active_slugs = {topic_slug(topic) for topic in topic_cards}
    return [
        ensure_relative(path, paths.vault)
        for path in sorted(paths.topics.glob("*.md"))
        if path.stem not in active_slugs
    ]


def _artifacts_without_sources(artifacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [artifact for artifact in artifacts if not artifact.get("sources")]


def _topic_opportunities(
    topic_cards: dict[str, list[SourceCard]],
    syntheses: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    synthesis_text = normalize_title(" ".join(str(item.get("title") or "") for item in syntheses))
    rows = []
    for topic, cards in sorted(topic_cards.items(), key=lambda item: (-len(item[1]), item[0])):
        if len(cards) < 2:
            continue
        topic_key = normalize_title(topic)
        if topic_key and topic_key in synthesis_text:
            continue
        rows.append(
            {
                "topic": topic,
                "papers": len(cards),
                "example_papers": ", ".join(card.title for card in cards[:3]),
            }
        )
    return rows[:20]


def _render_command_block(commands: list[str]) -> list[str]:
    lines = ["## Useful CLI commands", ""]
    for command in commands:
        lines.extend(["```fish", command, "```", ""])
    return lines


def _render_dashboard_index(
    paths: VaultPaths,
    cards: list[SourceCard],
    runs: list[RunRecord],
    manifests: list[ImportManifest],
    artifacts: dict[str, list[dict[str, Any]]],
    topic_cards: dict[str, list[SourceCard]],
) -> str:
    reading_rows = _reading_queue_rows(paths, cards)
    metadata_rows = _metadata_issue_rows(cards)
    pdf_summary = _pdf_issue_summary(paths, cards, manifests)
    topic_report = _topic_report(cards, limit=12)
    stale_topics = _stale_topic_pages(paths, topic_cards)
    concepts = artifacts.get("concepts") or []
    syntheses = artifacts.get("syntheses") or []
    tasks = artifacts.get("tasks") or []
    projects = artifacts.get("projects") or []
    issue_counts = {
        "Reading queue": len(reading_rows),
        "Metadata issues": len(metadata_rows),
        "Orphan PDFs": len(pdf_summary["orphan_pdfs"]),
        "Missing card PDFs": len(pdf_summary["missing_card_pdfs"]),
        "Historical unmatched records": pdf_summary["historical_unmatched_entries"],
        "Noisy topics": len(topic_report["noisy"]),
        "Stale topic pages": len(stale_topics),
        "Concepts": len(concepts),
        "Syntheses": len(syntheses),
        "Tasks": len(tasks),
        "Projects": len(projects),
    }
    lines = [
        "# Scholar Vault Dashboard",
        "",
        "Plain Markdown dashboard for Obsidian and CLI-oriented maintenance. No Obsidian "
        "plugin is required for these views.",
        "",
        "Scholar Labs summaries, generated indexes, and topic pages are navigation aids, not "
        "evidence. Read linked PDFs before factual synthesis.",
        "",
        "## Views",
        "",
        "- [Paper status](paper-status.md)",
        "- [Reading queue](reading-queue.md)",
        "- [Metadata issues](metadata-issues.md)",
        "- [PDF issues](pdf-issues.md)",
        "- [Synthesis dashboard](synthesis-dashboard.md)",
        "- [Search index](search-index.md)",
        "- [Projects](projects.md)",
        "",
        "## Open queues",
        "",
        *_markdown_table(
            ["Queue", "Count"],
            [[key, value] for key, value in issue_counts.items()],
        ),
        "",
        "## Reading queue preview",
        "",
        *_markdown_table(
            ["Paper", "Citekey", "PDF"],
            [
                [row["paper_link"], row["citekey"], row["pdf"]]
                for row in reading_rows[:10]
            ],
            empty="No selected attached papers are missing PDF reading notes.",
        ),
        "",
        "## Metadata issue preview",
        "",
        *_markdown_table(
            ["Paper", "Citekey", "Issues"],
            [
                [row["paper_link"], row["citekey"], "; ".join(row["issues"])]
                for row in metadata_rows[:10]
            ],
            empty="No actionable metadata, citation, abstract, or keyword issues found.",
        ),
        "",
        "## Topic noise preview",
        "",
        *_markdown_table(
            ["Topic", "Count"],
            [[row["topic"], row["count"]] for row in topic_report["noisy"][:12]],
            empty="No prompt-boilerplate topic labels detected.",
        ),
        "",
    ]
    lines.extend(
        _render_command_block(
            [
                "scholar-vault maintenance-report --vault /path/to/vault",
                'scholar-vault notes-missing --vault /path/to/vault --heading "PDF reading notes"',
                "scholar-vault enrich --vault /path/to/vault --ui",
                "scholar-vault pdf-doctor --vault /path/to/vault --json",
                "scholar-vault topic-map --vault /path/to/vault --preset prompt-boilerplate",
            ]
        )
    )
    return "\n".join(lines)


def _render_paper_status_index(
    paths: VaultPaths,
    cards: list[SourceCard],
    reading_rows: list[dict[str, Any]],
    metadata_rows: list[dict[str, Any]],
) -> str:
    attached = sum(1 for card in cards if _card_has_valid_pdf(paths, card))
    counts = [
        ["Paper cards", len(cards)],
        ["Attached PDF cards", attached],
        ["Missing PDF cards", len(cards) - attached],
        ["Reading queue", len(reading_rows)],
        ["Metadata issue cards", len(metadata_rows)],
    ]
    status_fields = [
        ("PDF status", _status_counts(cards, "pdf_status")),
        ("Enrichment status", _status_counts(cards, "enrichment_status")),
        ("Citation status", _status_counts(cards, "citation_status")),
        ("Abstract status", _status_counts(cards, "abstract_status")),
        ("Publication keyword status", _status_counts(cards, "publication_keywords_status")),
    ]
    lines = [
        "# Paper Status",
        "",
        *_markdown_table(["Metric", "Count"], counts),
        "",
    ]
    for title, status_counts in status_fields:
        lines.extend(
            [
                f"## {title}",
                "",
                *_markdown_table(
                    ["Status", "Count"],
                    [[key, value] for key, value in status_counts.items()],
                ),
                "",
            ]
        )
    lines.extend(
        _render_command_block(
            [
                "scholar-vault status --vault /path/to/vault --json",
                "scholar-vault rebuild --vault /path/to/vault",
            ]
        )
    )
    return "\n".join(lines)


def _render_reading_queue_index(reading_rows: list[dict[str, Any]]) -> str:
    lines = [
        "# Reading Queue",
        "",
        "Selected or attached paper cards missing a `PDF reading notes` heading under "
        "`## Notes`.",
        "",
        *_markdown_table(
            ["Paper", "Citekey", "Year", "PDF", "PDF exists"],
            [
                [
                    row["paper_link"],
                    row["citekey"],
                    row["year"] or "",
                    row["pdf"],
                    row["pdf_exists"],
                ]
                for row in reading_rows
            ],
            empty="No selected attached papers are missing PDF reading notes.",
        ),
        "",
    ]
    lines.extend(
        _render_command_block(
            [
                'scholar-vault notes-missing --vault /path/to/vault --heading "PDF reading notes"',
                "scholar-vault rebuild --vault /path/to/vault",
            ]
        )
    )
    return "\n".join(lines)


def _render_metadata_issues_index(
    metadata_rows: list[dict[str, Any]],
    diagnostic_rows: list[dict[str, Any]],
) -> str:
    lines = [
        "# Metadata Issues",
        "",
        "Actionable citation, DOI, enrichment, abstract, and publication-keyword follow-up.",
        "",
        "## Actionable issues",
        "",
        *_markdown_table(
            ["Paper", "Citekey", "Issues", "DOI", "Venue"],
            [
                [
                    row["paper_link"],
                    row["citekey"],
                    "; ".join(row["issues"]),
                    row["doi"],
                    row["venue"],
                ]
                for row in metadata_rows
            ],
            empty="No actionable metadata issues found.",
        ),
        "",
        "## Not-yet-enriched diagnostics",
        "",
        "These rows are diagnostics, not defects by themselves.",
        "",
        *_markdown_table(
            ["Paper", "Citekey"],
            [[row["paper_link"], row["citekey"]] for row in diagnostic_rows[:100]],
            empty="No papers are marked with untouched metadata enrichment.",
        ),
        "",
    ]
    lines.extend(
        _render_command_block(
            [
                "scholar-vault enrich --vault /path/to/vault --ui",
                "scholar-vault resolve-citation --vault /path/to/vault --citekey <citekey>",
                "scholar-vault set-abstract --vault /path/to/vault --citekey <citekey>",
                "scholar-vault set-keywords --vault /path/to/vault --citekey <citekey>",
            ]
        )
    )
    return "\n".join(lines)


def _render_pdf_issues_index(pdf_summary: dict[str, Any]) -> str:
    lines = [
        "# PDF Issues",
        "",
        "Vault PDF inventory view. Candidate results without cards are discovery context, not "
        "missing canonical sources.",
        "",
        "## Cards without a PDF field",
        "",
        *_markdown_table(
            ["Paper", "Citekey"],
            [
                [row["paper_link"], row["citekey"]]
                for row in pdf_summary["cards_without_pdf"]
            ],
            empty="No cards are missing a PDF field.",
        ),
        "",
        "## Card PDF files missing on disk",
        "",
        *_markdown_table(
            ["Paper", "Citekey", "PDF"],
            [
                [row["paper_link"], row["citekey"], row["pdf"]]
                for row in pdf_summary["missing_card_pdfs"]
            ],
            empty="No card PDF links point at missing files.",
        ),
        "",
        "## Orphan vault PDFs",
        "",
        *_markdown_table(
            ["PDF"],
            [[path] for path in pdf_summary["orphan_pdfs"]],
            empty="No orphan vault PDFs found.",
        ),
        "",
        "## Duplicate-style filenames",
        "",
        *_markdown_table(
            ["PDF"],
            [[path] for path in pdf_summary["duplicate_style_filenames"]],
            empty="No duplicate-style PDF filenames found.",
        ),
        "",
        "## Historical unmatched records",
        "",
        f"- Historical unmatched entries: {pdf_summary['historical_unmatched_entries']}",
        "",
        *_markdown_table(
            ["Filename", "Count", "Runs", "Best score"],
            [
                [
                    row["filename"],
                    row["count"],
                    ", ".join(row["runs"]),
                    row["best_score"],
                ]
                for row in pdf_summary["repeated_unmatched_files"]
            ],
            empty="No repeated historical unmatched files found.",
        ),
        "",
    ]
    lines.extend(
        _render_command_block(
            [
                "scholar-vault pdf-doctor --vault /path/to/vault --json",
                "scholar-vault match-staging --vault /path/to/vault --ui",
            ]
        )
    )
    return "\n".join(lines)


def _render_synthesis_dashboard(
    artifacts: dict[str, list[dict[str, Any]]],
    topic_cards: dict[str, list[SourceCard]],
    stale_topics: list[str],
    topic_report: dict[str, Any],
) -> str:
    concepts = artifacts.get("concepts") or []
    syntheses = artifacts.get("syntheses") or []
    tasks = artifacts.get("tasks") or []
    concept_needs = _artifacts_without_sources(concepts)
    synthesis_needs = _artifacts_without_sources(syntheses)
    opportunities = _topic_opportunities(topic_cards, syntheses)
    lines = [
        "# Synthesis Dashboard",
        "",
        "Concepts are reusable methods, algorithms, visual encodings, datasets, evaluation "
        "protocols, and terminology. Syntheses are evidence-backed cross-paper answers. "
        "Tasks are open questions, gaps, and next searches.",
        "",
        "## Research artifacts",
        "",
        *_markdown_table(
            ["Type", "Count"],
            [
                ["Concepts", len(concepts)],
                ["Syntheses", len(syntheses)],
                ["Tasks", len(tasks)],
            ],
        ),
        "",
        "## Concepts without source links",
        "",
        *_markdown_table(
            ["Concept", "Type"],
            [[_artifact_link(row), row.get("type") or "concept"] for row in concept_needs],
            empty="No concept cards are missing source links.",
        ),
        "",
        "## Syntheses without source links",
        "",
        *_markdown_table(
            ["Synthesis", "Type"],
            [[_artifact_link(row), row.get("type") or "synthesis"] for row in synthesis_needs],
            empty="No synthesis notes are missing source links.",
        ),
        "",
        "## Synthesis opportunities by topic",
        "",
        *_markdown_table(
            ["Topic", "Papers", "Example papers"],
            [
                [row["topic"], row["papers"], row["example_papers"]]
                for row in opportunities
            ],
            empty="No multi-paper topic opportunities detected.",
        ),
        "",
        "## Topic cleanup",
        "",
        *_markdown_table(
            ["Noisy topic", "Count"],
            [[row["topic"], row["count"]] for row in topic_report["noisy"]],
            empty="No prompt-boilerplate topic labels detected.",
        ),
        "",
        "## Stale generated topic pages",
        "",
        *_markdown_table(
            ["Topic page"],
            [[path] for path in stale_topics],
            empty="No stale generated topic pages detected.",
        ),
        "",
    ]
    lines.extend(
        _render_command_block(
            [
                "scholar-vault topic-map --vault /path/to/vault --preset prompt-boilerplate",
                (
                    "scholar-vault topic-map --vault /path/to/vault "
                    "--preset prompt-boilerplate --apply"
                ),
                "scholar-vault concept-index --vault /path/to/vault",
                "scholar-vault rebuild --vault /path/to/vault",
            ]
        )
    )
    return "\n".join(lines)


def _write_dashboard_indexes(
    paths: VaultPaths,
    cards: list[SourceCard],
    runs: list[RunRecord],
    manifests: list[ImportManifest],
    artifacts: dict[str, list[dict[str, Any]]],
    topic_cards: dict[str, list[SourceCard]],
) -> int:
    reading_rows = _reading_queue_rows(paths, cards)
    metadata_rows = _metadata_issue_rows(cards)
    diagnostic_rows = _metadata_not_enriched_rows(cards)
    pdf_summary = _pdf_issue_summary(paths, cards, manifests)
    topic_report = _topic_report(cards, limit=30)
    stale_topics = _stale_topic_pages(paths, topic_cards)
    outputs = {
        "dashboard.md": _render_dashboard_index(
            paths,
            cards,
            runs,
            manifests,
            artifacts,
            topic_cards,
        ),
        "paper-status.md": _render_paper_status_index(
            paths,
            cards,
            reading_rows,
            metadata_rows,
        ),
        "reading-queue.md": _render_reading_queue_index(reading_rows),
        "metadata-issues.md": _render_metadata_issues_index(metadata_rows, diagnostic_rows),
        "pdf-issues.md": _render_pdf_issues_index(pdf_summary),
        "synthesis-dashboard.md": _render_synthesis_dashboard(
            artifacts,
            topic_cards,
            stale_topics,
            topic_report,
        ),
    }
    for filename, content in outputs.items():
        write_text(paths.indexes / filename, content)
    return len(outputs)


def _pdf_reading_notes_snippet(card: SourceCard) -> str:
    match = re.search(
        r"(?ims)^#{3,6}\s+PDF reading notes[^\n]*\n(?P<body>.*?)(?=^#{1,6}\s+|\Z)",
        card.notes or "",
    )
    if not match:
        return ""
    return _compact_text(match.group("body"), limit=800)


def _should_index_artifact_path(folder: str, path: Path) -> bool:
    if folder == "projects":
        return path.name == "index.md"
    return True


def _artifact_search_rows(paths: VaultPaths, folder: str) -> list[dict[str, str]]:
    root = paths.vault / folder
    if not root.exists():
        return []
    rows: list[dict[str, str]] = []
    for path in sorted(root.rglob("*.md")):
        if any(part.startswith(".") for part in path.relative_to(root).parts):
            continue
        if not _should_index_artifact_path(folder, path):
            continue
        frontmatter, body = read_frontmatter_markdown(path)
        rows.append(
            {
                "path": ensure_relative(path, paths.vault),
                "title": _artifact_title(path, frontmatter, body),
                "type": str(frontmatter.get("type") or ARTIFACT_DEFAULT_TYPES.get(folder, "note")),
                "sources": ", ".join(_as_string_list(frontmatter.get("sources"))),
                "text": _compact_text(body, limit=900),
            }
        )
    return rows


def render_search_index(paths: VaultPaths, cards: list[SourceCard]) -> str:
    lines = [
        "# Search Index",
        "",
        "Compact plain-text search surface for Obsidian, shell tools, and agents. This file "
        "does not include full PDF text.",
        "",
        "## Papers",
        "",
    ]
    if not cards:
        lines.extend(["No paper cards found.", ""])
    for card in cards:
        lines.extend(
            [
                f"### {_card_id(card)} - {card.title}",
                "",
                f"- path: papers/{card.slug}.md",
                f"- citekey: {_card_id(card)}",
                f"- year: {card.year or ''}",
                f"- doi: {card.doi or ''}",
                f"- topics: {', '.join(card.topics)}",
                f"- publication_keywords: {', '.join(card.keywords)}",
                f"- abstract: {_compact_text(card.abstract, limit=900)}",
                f"- scholar_labs_summary: {_compact_text(card.summary, limit=900)}",
            ]
        )
        summaries = [
            _compact_text(source.summary, limit=500)
            for source in card.summary_sources
            if _compact_text(source.summary, limit=500)
        ]
        if summaries:
            lines.append(f"- run_summaries: {' / '.join(summaries[:3])}")
        reading_notes = _pdf_reading_notes_snippet(card)
        if reading_notes:
            lines.append(f"- pdf_reading_notes: {reading_notes}")
        lines.append("")
    for folder, title in [
        ("concepts", "Concepts"),
        ("syntheses", "Syntheses"),
        ("tasks", "Tasks"),
        ("projects", "Projects"),
        ("proposals", "Proposals"),
    ]:
        lines.extend([f"## {title}", ""])
        rows = _artifact_search_rows(paths, folder)
        if not rows:
            lines.extend([f"No {folder} notes found.", ""])
            continue
        for row in rows:
            lines.extend(
                [
                    f"### {row['title']}",
                    "",
                    f"- path: {row['path']}",
                    f"- type: {row['type']}",
                    f"- sources: {row['sources']}",
                    f"- text: {row['text']}",
                    "",
                ]
            )
    return "\n".join(lines)


def _terms_from_text(text: str | None) -> set[str]:
    normalized = normalize_title(text)
    return {
        token
        for token in normalized.split()
        if len(token) > 3 and token not in SEARCH_STOPWORDS
    }


def _value_map(values: list[str]) -> dict[str, str]:
    mapped: dict[str, str] = {}
    for value in values:
        key = normalize_title(value)
        if key and key not in mapped:
            mapped[key] = value
    return mapped


def _semantic_neighbor_rows(cards: list[SourceCard], *, limit: int = 5) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    features: dict[str, dict[str, Any]] = {}
    for card in cards:
        card_key = _card_id(card)
        features[card_key] = {
            "topics": _value_map(card.topics),
            "keywords": _value_map(card.keywords),
            "runs": set(card.discovered_in),
            "terms": _terms_from_text(f"{card.title} {card.abstract or ''}"),
            "doi": normalize_doi(card.doi),
        }
    for card in cards:
        card_key = _card_id(card)
        neighbors: list[dict[str, Any]] = []
        current = features[card_key]
        for other in cards:
            other_key = _card_id(other)
            if other_key == card_key:
                continue
            candidate = features[other_key]
            reasons: list[str] = []
            score = 0
            shared_topics = sorted(set(current["topics"]) & set(candidate["topics"]))
            for topic_key in shared_topics[:5]:
                reasons.append(f"shared topic: {current['topics'][topic_key]}")
            score += len(shared_topics) * 4
            shared_keywords = sorted(set(current["keywords"]) & set(candidate["keywords"]))
            for keyword_key in shared_keywords[:5]:
                reasons.append(f"shared keyword: {current['keywords'][keyword_key]}")
            score += len(shared_keywords) * 5
            shared_runs = sorted(current["runs"] & candidate["runs"])
            for run in shared_runs[:3]:
                reasons.append(f"same run: {run}")
            score += len(shared_runs) * 3
            shared_terms = sorted(current["terms"] & candidate["terms"])
            if shared_terms:
                reasons.append(
                    "similar title/abstract terms: " + ", ".join(shared_terms[:8])
                )
            score += min(len(shared_terms), 8)
            if current["doi"] and current["doi"] == candidate["doi"]:
                reasons.append(f"same DOI: {current['doi']}")
                score += 10
            if score <= 0:
                continue
            neighbors.append(
                {
                    "citekey": other_key,
                    "paper": f"papers/{other.slug}.md",
                    "title": other.title,
                    "score": score,
                    "reasons": reasons,
                }
            )
        neighbors.sort(key=lambda item: (-int(item["score"]), str(item["citekey"])))
        rows.append(
            {
                "citekey": card_key,
                "paper": f"papers/{card.slug}.md",
                "title": card.title,
                "neighbors": neighbors[:limit],
            }
        )
    return rows


def semantic_neighbors_export(cards: list[SourceCard]) -> dict[str, Any]:
    return {
        "schema_version": "0.1",
        "kind": "deterministic_navigation_neighbors",
        "evidence_warning": (
            "Navigation only. Shared metadata and text overlap are not evidence; read PDFs "
            "before factual synthesis."
        ),
        "method": [
            "shared topics",
            "shared publication keywords",
            "same Scholar Labs run",
            "title/abstract term overlap",
            "matching DOI metadata when present",
        ],
        "papers": _semantic_neighbor_rows(cards),
    }


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


def _first_markdown_heading(body: str) -> str | None:
    match = re.search(r"^#\s+(.+?)\s*$", body, flags=re.MULTILINE)
    return clean_markdown_text(match.group(1)) if match else None


def _artifact_title(path: Path, frontmatter: dict[str, Any], body: str) -> str:
    title = frontmatter.get("title")
    if isinstance(title, str) and title.strip():
        return clean_markdown_text(title)
    heading = _first_markdown_heading(body)
    if heading:
        return heading
    return path.stem.replace("-", " ").replace("_", " ").strip().title()


def _as_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _collect_artifacts(paths: VaultPaths, folder: str) -> list[dict[str, Any]]:
    root = paths.vault / folder
    if not root.exists():
        return []
    artifacts: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*.md")):
        if any(part.startswith(".") for part in path.relative_to(root).parts):
            continue
        if not _should_index_artifact_path(folder, path):
            continue
        frontmatter, body = read_frontmatter_markdown(path)
        artifacts.append(
            {
                "path": ensure_relative(path, paths.vault),
                "title": _artifact_title(path, frontmatter, body),
                "type": frontmatter.get("type") or ARTIFACT_DEFAULT_TYPES.get(folder, "note"),
                "created": frontmatter.get("created") or frontmatter.get("date"),
                "sources": _as_string_list(frontmatter.get("sources")),
            }
        )
    return artifacts


def _collect_research_artifacts(paths: VaultPaths) -> dict[str, list[dict[str, Any]]]:
    return {folder: _collect_artifacts(paths, folder) for folder in ARTIFACT_INDEXES}


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


def _clear_directory(path: Path) -> int:
    removed = 0
    if not path.exists():
        return removed
    for child in path.iterdir():
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink()
        removed += 1
    return removed


def initialize_vault(vault: Path | str, *, rebuild: bool = True) -> VaultPaths:
    paths = VaultPaths.from_root(vault)
    paths.ensure()
    config_path = paths.vault / "config.yaml"
    if not config_path.exists():
        write_yaml(
            config_path,
            {
                "schema_version": "0.1",
                "name": "scholar-vault",
                "source_kinds": [
                    "scholar_labs",
                    "pdf_drop",
                    "bibtex_import",
                    "doi_import",
                    "manual",
                ],
            },
        )
    if not (paths.vault / "README.md").exists():
        write_text(paths.vault / "README.md", render_vault_readme())
    if not (paths.vault / "AGENTS.md").exists():
        write_text(paths.vault / "AGENTS.md", render_vault_agents())
    if rebuild:
        _rebuild_indexes(paths)
    return paths


def reset_vault(vault: Path | str) -> dict[str, int]:
    paths = VaultPaths.from_root(vault)
    if not paths.vault.exists():
        raise ValueError(f"Vault does not exist: {paths.vault}")

    removed = 0
    for path in (
        paths.raw_scholar_labs,
        paths.raw_inbox,
        paths.raw_staging,
        paths.raw_unmatched,
        paths.raw_imported,
        paths.raw_metadata,
        paths.pdfs,
        paths.papers,
        paths.runs,
        paths.topics,
        paths.indexes,
        paths.exports,
    ):
        removed += _clear_directory(path)

    for file_path in (paths.vault / "llms.txt", paths.vault / "llms-full.txt"):
        if file_path.exists():
            file_path.unlink()
            removed += 1

    initialize_vault(paths.vault)
    return {"removed": removed}


def _consume_candidate(
    remaining: list,
    *,
    original_path: str | None = None,
    original_sha256: str | None = None,
) -> list:
    updated = []
    consumed = False
    for candidate in remaining:
        if consumed:
            updated.append(candidate)
            continue
        if original_path and candidate.path == original_path:
            consumed = True
            continue
        if original_sha256 and candidate.sha256 == original_sha256:
            consumed = True
            continue
        updated.append(candidate)
    return updated


def _paper_card_exists(paths: VaultPaths, paper_card: str | None) -> bool:
    if not paper_card:
        return False
    return (paths.vault / paper_card).exists()


def _archive_matched_pdf(paths: VaultPaths, run_id: str, source_pdf: Path) -> str:
    archive_dir = paths.raw_imported / "scholar-labs" / run_id / "matched-pdfs"
    destination = _archive_path(archive_dir, source_pdf.name)
    shutil.move(str(source_pdf), str(destination))
    return ensure_relative(destination, paths.vault)


def _archive_used_export(export_file: Path) -> tuple[Path, bool]:
    if export_file.parent.name == "used":
        return export_file, False
    destination = _archive_path(export_file.parent / "used", export_file.name)
    shutil.move(str(export_file), str(destination))
    return destination.resolve(), True


def _build_manifest_entry(
    result: ScholarLabsResult,
    match: MatchDecision | None,
    *,
    decision: str,
    paper_card: str | None,
    card_created: bool,
    card_preexisting: bool,
    card_before: dict | None,
    destination_path: str | None = None,
    copied: bool = False,
    moved: bool = False,
    archived_original_path: str | None = None,
    verified: bool = False,
    note: str | None = None,
) -> ImportManifestEntry:
    candidate = match.candidate if match else None
    return ImportManifestEntry(
        rank=result.rank,
        scholar_cid=result.scholar_cid,
        result_title=result.title,
        original_path=candidate.path if candidate else None,
        original_sha256=candidate.sha256 if candidate else None,
        proposed_match=result.title if candidate else None,
        score=match.score if match and candidate else None,
        decision=decision,
        destination_path=destination_path,
        copied=copied,
        moved=moved,
        archived_original_path=archived_original_path,
        paper_card=paper_card,
        paper_card_created=card_created,
        card_preexisting=card_preexisting,
        card_before=card_before,
        verified=verified,
        note=note,
    )


def _find_card_for_run_result(
    paths: VaultPaths,
    cards: list[SourceCard],
    result: RunResultRecord | ScholarLabsResult,
    run_ref: str,
) -> SourceCard | None:
    run_ref_parts = Path(run_ref).parts
    legacy_run_ref = (
        _legacy_run_ref(run_ref_parts[1])
        if len(run_ref_parts) >= 2 and run_ref_parts[0] == "runs"
        else ""
    )
    if isinstance(result, RunResultRecord) and result.paper_card:
        paper_path = paths.vault / result.paper_card
        if paper_path.exists():
            slug = paper_path.stem
            for card in cards:
                if card.slug == slug:
                    return card
    for card in cards:
        if result.scholar_cid and card.scholar_cid == result.scholar_cid:
            return card
    for card in cards:
        if (
            normalize_title(card.title) == normalize_title(result.title)
            and (run_ref in card.discovered_in or legacy_run_ref in card.discovered_in)
        ):
            return card
    return None


def _card_has_valid_pdf(paths: VaultPaths, card: SourceCard) -> bool:
    if not card.pdf:
        return False
    pdf_path = Path(card.pdf)
    if not pdf_path.is_absolute():
        pdf_path = paths.vault / card.pdf
    return pdf_path.exists()


def _card_pdf_sha256(paths: VaultPaths, card: SourceCard) -> str | None:
    if not _card_has_valid_pdf(paths, card):
        return None
    pdf_path = Path(card.pdf or "")
    if not pdf_path.is_absolute():
        pdf_path = paths.vault / pdf_path
    return _file_sha256(pdf_path)


def _candidate_replaces_card_pdf(
    paths: VaultPaths,
    card: SourceCard,
    candidate_sha256: str | None,
) -> bool:
    current_sha256 = _card_pdf_sha256(paths, card)
    return bool(candidate_sha256 and current_sha256 and candidate_sha256 != current_sha256)


def _record_pdf_metadata_from_candidate(card: SourceCard, candidate) -> None:
    doi = normalize_doi(candidate.doi)
    if doi and not normalize_doi(card.doi):
        card.doi = doi
        card.doi_status = "detected"
        card.doi_source = "pdf"
        card.doi_confidence = 0.95
    if card.citation_status not in {"manual_lock", "verified"}:
        card.citation_status = "missing"
        card.citation_source = None
        card.citation_skip_reason = None
        card.enrichment_status = "missing"
        card.enrichment_missing = []
        card.enrichment_refresh = True


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _build_match_review_request(
    result: ScholarLabsResult,
    proposal: MatchDecision,
) -> MatchReviewRequest:
    if proposal.candidate is None:
        raise ValueError("Cannot review a match proposal without a PDF candidate.")
    candidate = proposal.candidate
    pdf_path = Path(candidate.path)
    return MatchReviewRequest(
        rank=result.rank,
        scholar_cid=result.scholar_cid,
        result_title=result.title,
        authors_preview=result.authors_preview,
        year=result.year,
        venue=result.venue,
        summary=result.summary,
        pdf_path=candidate.path,
        pdf_filename=pdf_path.name,
        score=proposal.score,
        match_reason=proposal.reason,
        proposed_decision=proposal.decision,
        inferred_title=candidate.title,
        inferred_doi=candidate.doi,
        inferred_year=candidate.year,
        text_excerpt=candidate.text_excerpt,
    )


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


def _match_progress_identifier(result: ScholarLabsResult) -> str:
    words = re.findall(r"[a-z0-9]+", result.title.lower())
    filtered = [word for word in words if len(word) > 2][:5]
    compact = "".join(filtered)[:34]
    return f"r{result.rank:02d}-{compact or result.scholar_cid or 'result'}"


def _report_match_progress(
    progress: ProgressCallback | None,
    result: ScholarLabsResult,
    status: str,
    detail: str,
    index: int,
    total: int,
) -> None:
    if progress:
        progress(
            "Matching Scholar Labs result "
            f"{result.rank} [{status}]: {detail} // {_match_progress_identifier(result)}",
            index,
            total,
        )


def _pdf_scan_cache_path(staging_dir: Path) -> Path:
    return staging_dir / PDF_SCAN_CACHE_FILENAME


def _load_pdf_scan_cache(staging_dir: Path) -> dict[str, Any]:
    cache_path = _pdf_scan_cache_path(staging_dir)
    if not cache_path.exists():
        return {"schema_version": PDF_SCAN_CACHE_SCHEMA_VERSION, "entries": {}}
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schema_version": PDF_SCAN_CACHE_SCHEMA_VERSION, "entries": {}}
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != PDF_SCAN_CACHE_SCHEMA_VERSION
    ):
        return {"schema_version": PDF_SCAN_CACHE_SCHEMA_VERSION, "entries": {}}
    entries = payload.get("entries")
    if not isinstance(entries, dict):
        payload["entries"] = {}
    return payload


def _pdf_cache_entry_key(path: Path) -> str:
    return path.name


def _pdf_cache_stat(path: Path) -> dict[str, int]:
    stat = path.stat()
    return {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def _cached_pdf_candidate(
    cache: dict[str, Any],
    path: Path,
) -> PdfCandidate | None:
    entries = cache.get("entries")
    if not isinstance(entries, dict):
        return None
    entry = entries.get(_pdf_cache_entry_key(path))
    if not isinstance(entry, dict):
        return None
    try:
        current = _pdf_cache_stat(path)
    except OSError:
        return None
    if entry.get("size") != current["size"] or entry.get("mtime_ns") != current["mtime_ns"]:
        return None
    candidate_data = entry.get("candidate")
    if not isinstance(candidate_data, dict):
        return None
    candidate_data = dict(candidate_data)
    candidate_data["path"] = str(path)
    try:
        return PdfCandidate.model_validate(candidate_data)
    except ValidationError:
        return None


def _write_pdf_scan_cache(
    staging_dir: Path,
    candidates: list[PdfCandidate],
) -> None:
    entries: dict[str, Any] = {}
    for candidate in candidates:
        path = Path(candidate.path)
        try:
            stat = _pdf_cache_stat(path)
        except OSError:
            continue
        entries[_pdf_cache_entry_key(path)] = {
            **stat,
            "candidate": candidate.model_dump(mode="json"),
        }
    try:
        write_json(
            _pdf_scan_cache_path(staging_dir),
            {
                "schema_version": PDF_SCAN_CACHE_SCHEMA_VERSION,
                "entries": entries,
            },
        )
    except OSError:
        pass


def _build_staged_pdf_candidates(
    staging_dir: Path,
    staged_pdf_paths: list[Path],
    *,
    dry_run: bool,
    progress: ProgressCallback | None,
) -> tuple[list[PdfCandidate], int]:
    cache = _load_pdf_scan_cache(staging_dir)
    candidates: list[PdfCandidate] = []
    cache_hits = 0
    total = len(staged_pdf_paths)
    for index, path in enumerate(staged_pdf_paths, start=1):
        cached = _cached_pdf_candidate(cache, path)
        if cached is not None:
            cache_hits += 1
            if progress:
                progress(f"Using cached staged PDF scan {path.name}", index, total)
            candidates.append(cached)
            continue
        if progress:
            progress(f"Scanning staged PDF {path.name}", index, total)
        candidates.append(build_pdf_candidate(path))
    if not dry_run:
        _write_pdf_scan_cache(staging_dir, candidates)
    return candidates, cache_hits


def _run_title_from_inputs(
    export: ScholarLabsExport,
    existing_run: RunRecord | None,
    title: str | None,
) -> tuple[str, bool]:
    explicit_title = clean_markdown_text(title)
    if explicit_title:
        return run_display_title(explicit_title, export.prompt), True

    export_title = clean_markdown_text(export.title)
    existing_title = clean_markdown_text(existing_run.title if existing_run else None)
    inferred_title = infer_run_title(export.prompt)

    if export_title and (
        not existing_title or normalize_title(existing_title) == normalize_title(inferred_title)
    ):
        return run_display_title(export_title, export.prompt), bool(
            existing_title and normalize_title(existing_title) != normalize_title(export_title)
        )

    return run_display_title(existing_title or export_title or None, export.prompt), False


def import_scholar_labs_run(
    vault: Path | str,
    export_path: Path | str,
    staging_path: Path | str,
    *,
    dry_run: bool = False,
    commit: bool = False,
    include_without_pdf: bool = False,
    archive_matched: bool = False,
    archive_export: bool = False,
    auto_enrich: bool = False,
    upgrade_pdfs: bool = False,
    title: str | None = None,
    confirm: ConfirmCallback | None = None,
    review_match: MatchReviewCallback | None = None,
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    if dry_run and commit:
        raise ValueError("Use either dry-run or commit, not both.")

    paths = initialize_vault(vault)
    export_file = Path(export_path).expanduser().resolve()
    staging_dir = Path(staging_path).expanduser().resolve()
    if progress:
        progress(f"Reading Scholar Labs export {export_file.name}", None, None)
    export = _load_validated_scholar_export(paths, export_file)
    run_slug, run_date = _run_slug(export, export_file)
    existing_run = _load_run_record(paths, run_slug)
    run_title, title_changes_existing = _run_title_from_inputs(export, existing_run, title)
    run_note_file = (
        existing_run.note_file if existing_run and not title_changes_existing else None
    )
    run_ref = _run_ref_from_parts(run_slug, run_date, run_title, export.prompt, run_note_file)
    if existing_run and not dry_run and not commit and confirm is not None:
        if not confirm(f"Run {run_slug} already exists. Resume and update it?"):
            raise ImportCanceled(f"Run {run_slug} already exists. Import canceled.")

    raw_export_file = paths.raw_scholar_labs / f"{run_slug}.json"
    if not raw_export_file.exists():
        raw_export_file.write_text(export_file.read_text(encoding="utf-8"), encoding="utf-8")

    cards = load_source_cards(paths)
    existing_manifest = _load_manifest(paths, run_slug)
    existing_results = (
        {_result_key(result): result for result in existing_run.results} if existing_run else {}
    )
    existing_entries = (
        {
            (
                f"cid:{entry.scholar_cid}"
                if entry.scholar_cid
                else f"title:{normalize_title(entry.result_title)}"
            ): entry
            for entry in existing_manifest.entries
            if entry.result_title or entry.scholar_cid
        }
        if existing_manifest
        else {}
    )

    staged_pdf_paths = sorted(staging_dir.glob("*.pdf"))
    if progress:
        progress(f"Scanning {len(staged_pdf_paths)} staged PDFs", 0, len(staged_pdf_paths))
    candidates, pdf_scan_cache_hits = _build_staged_pdf_candidates(
        staging_dir,
        staged_pdf_paths,
        dry_run=dry_run,
        progress=progress,
    )
    remaining = list(candidates)
    run_results: list[RunResultRecord] = []
    manifest_entries: list[ImportManifestEntry] = []
    matched_files: list[str] = []
    unmatched_files: list[str] = []
    log_entries: list[ImportLogEntry] = []
    archived_files: list[str] = []
    interactive = not dry_run and not commit
    decision_summary: dict[str, int | bool] = {
        "existing_run": bool(existing_run),
        "export_results": len(export.results),
        "staged_pdfs_scanned": len(staged_pdf_paths),
        "staged_pdf_cache_hits": pdf_scan_cache_hits,
        "prior_selected_reused": 0,
        "existing_cards_linked": 0,
        "new_staged_pdf_matches": 0,
        "review_prompts": 0,
        "review_accepted": 0,
        "review_rejected": 0,
        "commit_auto_accepted": 0,
        "commit_proposals_skipped": 0,
        "proposed_not_committed": 0,
        "results_without_candidate": 0,
        "pdf_upgrade_candidates": 0,
        "pdf_upgrades": 0,
        "pdf_upgrade_skipped": 0,
        "other_runs_synced": 0,
    }

    sorted_results = sorted(export.results, key=lambda item: item.rank)
    total_results = len(sorted_results)
    for index, result in enumerate(sorted_results, start=1):
        _report_match_progress(
            progress,
            result,
            "prior",
            "checking previous run manifest",
            index,
            total_results,
        )
        key = _result_key(result)
        prior_result = existing_results.get(key)
        prior_entry = existing_entries.get(key)
        if (
            prior_result
            and prior_result.status == "selected"
            and _paper_card_exists(paths, prior_result.paper_card)
        ):
            prior_card = _find_card_for_run_result(paths, cards, prior_result, run_ref)
            upgrade_proposal = None
            if upgrade_pdfs and prior_card and _card_has_valid_pdf(paths, prior_card):
                upgrade_candidates = [
                    candidate
                    for candidate in remaining
                    if _candidate_replaces_card_pdf(paths, prior_card, candidate.sha256)
                ]
                if upgrade_candidates:
                    _report_match_progress(
                        progress,
                        result,
                        "upgrade",
                        f"scoring {len(upgrade_candidates)} staged replacement candidates",
                        index,
                        total_results,
                    )
                    match = best_pdf_match(
                        result.title,
                        upgrade_candidates,
                        expected_doi=prior_card.doi,
                    )
                    upgrade_proposal = (
                        match if match.candidate and match.score >= 70 else None
                    )
                    if upgrade_proposal and upgrade_proposal.candidate:
                        decision_summary["pdf_upgrade_candidates"] += 1
                        _report_match_progress(
                            progress,
                            result,
                            "upgrade-proposed",
                            f"{Path(upgrade_proposal.candidate.path).name}; "
                            f"score={upgrade_proposal.score}; "
                            f"reason={upgrade_proposal.reason}; "
                            f"decision={upgrade_proposal.decision}",
                            index,
                            total_results,
                        )
            upgrade_decision = "unresolved"
            if upgrade_proposal is not None and upgrade_proposal.candidate:
                if dry_run:
                    decision_summary["proposed_not_committed"] += 1
                    decision_summary["pdf_upgrade_skipped"] += 1
                    _report_match_progress(
                        progress,
                        result,
                        "dry-run",
                        "PDF upgrade proposal recorded but not committed",
                        index,
                        total_results,
                    )
                elif commit:
                    if upgrade_proposal.decision == "auto":
                        upgrade_decision = "accepted"
                        decision_summary["commit_auto_accepted"] += 1
                    else:
                        decision_summary["commit_proposals_skipped"] += 1
                        decision_summary["pdf_upgrade_skipped"] += 1
                        _report_match_progress(
                            progress,
                            result,
                            "skipped",
                            "PDF upgrade review proposal skipped by --commit",
                            index,
                            total_results,
                        )
                elif interactive:
                    decision_summary["review_prompts"] += 1
                    _report_match_progress(
                        progress,
                        result,
                        "review",
                        "waiting for PDF upgrade decision",
                        index,
                        total_results,
                    )
                    if review_match is not None:
                        accepted = review_match(
                            _build_match_review_request(result, upgrade_proposal)
                        )
                    elif confirm is not None:
                        accepted = confirm(
                            f"Replace attached PDF for {result.title} with "
                            f"{Path(upgrade_proposal.candidate.path).name} "
                            f"(score={upgrade_proposal.score})?"
                        )
                    else:
                        accepted = upgrade_proposal.decision == "auto"
                    if accepted:
                        upgrade_decision = "accepted"
                        decision_summary["review_accepted"] += 1
                    else:
                        upgrade_decision = "rejected"
                        decision_summary["review_rejected"] += 1
                        decision_summary["pdf_upgrade_skipped"] += 1
                elif upgrade_proposal.decision == "auto":
                    upgrade_decision = "accepted"

            if (
                upgrade_decision == "accepted"
                and upgrade_proposal is not None
                and upgrade_proposal.candidate
                and prior_card
            ):
                card_before = prior_card.model_dump(mode="python")
                candidate_path = Path(upgrade_proposal.candidate.path)
                destination_path, copied, verified = _copy_pdf_to_vault(
                    paths,
                    candidate_path,
                    prior_card,
                    original_sha256=upgrade_proposal.candidate.sha256
                    or _file_sha256(candidate_path),
                )
                prior_card.pdf = destination_path
                prior_card.pdf_status = "attached"
                prior_card.status = "active"
                prior_card.keywords = _merge_unique(
                    prior_card.keywords,
                    extract_pdf_keywords(upgrade_proposal.candidate.text_excerpt),
                )
                if prior_card.keywords:
                    prior_card.publication_keywords_status = "present"
                    prior_card.publication_keywords_source = "pdf_extracted"
                _record_pdf_metadata_from_candidate(prior_card, upgrade_proposal.candidate)
                archived_original_path = None
                moved = False
                note = "Replaced existing vault PDF with a staged upgrade."
                if archive_matched and candidate_path.exists():
                    archived_original_path = _archive_matched_pdf(paths, run_slug, candidate_path)
                    moved = True
                    archived_files.append(Path(archived_original_path).name)
                    note = f"Archived upgraded staging PDF to {archived_original_path}."
                _save_card(paths, prior_card)
                decision_summary["other_runs_synced"] += _sync_attached_card_to_matching_runs(
                    paths,
                    prior_card,
                    exclude_run_id=run_slug,
                )
                paper_card = f"papers/{prior_card.slug}.md"
                decision_summary["pdf_upgrades"] += 1
                matched_files.append(Path(upgrade_proposal.candidate.path).name)
                remaining = _consume_candidate(
                    remaining,
                    original_path=upgrade_proposal.candidate.path,
                    original_sha256=upgrade_proposal.candidate.sha256,
                )
                run_results.append(
                    RunResultRecord(
                        **result.model_dump(),
                        status="selected",
                        pdf_status="attached",
                        paper_card=paper_card,
                        proposed_pdf=upgrade_proposal.candidate.path,
                        proposed_sha256=upgrade_proposal.candidate.sha256,
                        score=upgrade_proposal.score,
                        decision="accepted",
                    )
                )
                manifest_entries.append(
                    _build_manifest_entry(
                        result,
                        upgrade_proposal,
                        decision="accepted",
                        paper_card=paper_card,
                        card_created=False,
                        card_preexisting=True,
                        card_before=card_before,
                        destination_path=destination_path,
                        copied=copied,
                        moved=moved,
                        archived_original_path=archived_original_path,
                        verified=verified,
                        note=note,
                    )
                )
                log_entries.append(
                    ImportLogEntry(
                        source_path=upgrade_proposal.candidate.path,
                        destination_path=destination_path,
                        status="upgraded",
                        score=upgrade_proposal.score,
                        note=note,
                    )
                )
                _report_match_progress(
                    progress,
                    result,
                    "upgraded",
                    f"replaced attached PDF for {prior_card.citekey or prior_card.slug}",
                    index,
                    total_results,
                )
                continue

            decision_summary["prior_selected_reused"] += 1
            _report_match_progress(
                progress,
                result,
                "reused",
                f"selected in prior run; card={prior_result.paper_card or 'unknown'}",
                index,
                total_results,
            )
            run_results.append(prior_result)
            if prior_entry:
                manifest_entries.append(prior_entry)
                remaining = _consume_candidate(
                    remaining,
                    original_path=prior_entry.original_path,
                    original_sha256=prior_entry.original_sha256,
                )
                if prior_entry.original_path:
                    matched_files.append(Path(prior_entry.original_path).name)
            continue

        _report_match_progress(
            progress,
            result,
            "card",
            "checking canonical vault cards",
            index,
            total_results,
        )
        existing_card = _find_existing_card(
            cards,
            scholar_cid=result.scholar_cid,
            title=result.title,
        )
        if existing_card:
            pdf_state = "pdf=yes" if _card_has_valid_pdf(paths, existing_card) else "pdf=no"
            _report_match_progress(
                progress,
                result,
                "card-found",
                f"{existing_card.citekey or existing_card.slug}; {pdf_state}",
                index,
                total_results,
            )
        else:
            _report_match_progress(
                progress,
                result,
                "card-none",
                "no existing vault card",
                index,
                total_results,
            )

        _report_match_progress(
            progress,
            result,
            "pdf",
            f"scoring {len(remaining)} staged PDF candidates",
            index,
            total_results,
        )
        match = best_pdf_match(result.title, remaining)
        proposal = match if match.candidate and match.score >= 70 else None
        if proposal is not None and proposal.candidate:
            _report_match_progress(
                progress,
                result,
                "proposed",
                f"{Path(proposal.candidate.path).name}; score={proposal.score}; "
                f"reason={proposal.reason}; decision={proposal.decision}",
                index,
                total_results,
            )
        elif match.candidate:
            _report_match_progress(
                progress,
                result,
                "below-threshold",
                f"{Path(match.candidate.path).name}; score={match.score}; reason={match.reason}",
                index,
                total_results,
            )
        else:
            _report_match_progress(
                progress,
                result,
                "pdf-none",
                "no staged PDF candidates remain",
                index,
                total_results,
            )
        decision = "unresolved"
        run_status = "candidate"
        pdf_status = "missing"
        paper_card: str | None = None
        card_created = False
        card_preexisting = False
        card_before: dict | None = None
        copied = False
        moved = False
        verified = False
        destination_path: str | None = None
        archived_original_path: str | None = None
        note: str | None = None
        existing_paper_card = (
            prior_result.paper_card
            if (
                prior_result
                and prior_result.paper_card
                and _paper_card_exists(paths, prior_result.paper_card)
            )
            else None
        )

        if proposal is not None:
            if dry_run:
                run_status = "unmatched"
                pdf_status = "unmatched"
                decision_summary["proposed_not_committed"] += 1
                _report_match_progress(
                    progress,
                    result,
                    "dry-run",
                    "proposal recorded but not committed",
                    index,
                    total_results,
                )
            elif commit:
                if proposal.decision == "auto":
                    decision = "accepted"
                    decision_summary["commit_auto_accepted"] += 1
                    _report_match_progress(
                        progress,
                        result,
                        "accepted",
                        "auto-accepted by --commit threshold",
                        index,
                        total_results,
                    )
                else:
                    run_status = "unmatched"
                    pdf_status = "unmatched"
                    decision_summary["commit_proposals_skipped"] += 1
                    _report_match_progress(
                        progress,
                        result,
                        "skipped",
                        "review proposal skipped by --commit",
                        index,
                        total_results,
                    )
            elif interactive:
                if review_match is not None:
                    decision_summary["review_prompts"] += 1
                    _report_match_progress(
                        progress,
                        result,
                        "review",
                        "waiting for GUI match decision",
                        index,
                        total_results,
                    )
                    accepted = review_match(_build_match_review_request(result, proposal))
                elif confirm is not None:
                    decision_summary["review_prompts"] += 1
                    _report_match_progress(
                        progress,
                        result,
                        "review",
                        "waiting for terminal match decision",
                        index,
                        total_results,
                    )
                    accepted = confirm(
                        f"Accept match {Path(proposal.candidate.path).name} -> {result.title} "
                        f"(score={proposal.score})?"
                    )
                else:
                    accepted = proposal.decision == "auto"
                if accepted:
                    decision = "accepted"
                    decision_summary["review_accepted"] += 1
                    _report_match_progress(
                        progress,
                        result,
                        "accepted",
                        "review accepted proposed staged PDF",
                        index,
                        total_results,
                    )
                else:
                    decision = "rejected"
                    run_status = "unmatched"
                    pdf_status = "unmatched"
                    decision_summary["review_rejected"] += 1
                    _report_match_progress(
                        progress,
                        result,
                        "rejected",
                        "review rejected proposed staged PDF",
                        index,
                        total_results,
                    )

        if decision == "accepted" and proposal is not None:
            decision_summary["new_staged_pdf_matches"] += 1
            card, card_created, card_before = _prepare_card_for_result(
                cards,
                result,
                run_ref=run_ref,
                prompt=export.prompt,
            )
            card_preexisting = not card_created
            destination_path, copied, verified = _copy_pdf_to_vault(
                paths,
                Path(proposal.candidate.path),
                card,
                original_sha256=proposal.candidate.sha256
                or _file_sha256(Path(proposal.candidate.path)),
            )
            card.pdf = destination_path
            card.pdf_status = "attached"
            card.status = "active"
            card.keywords = _merge_unique(
                card.keywords,
                extract_pdf_keywords(proposal.candidate.text_excerpt),
            )
            if card.keywords:
                card.publication_keywords_status = "present"
                card.publication_keywords_source = "pdf_extracted"
            if card.citation_status == "preview":
                card.citation_status = "missing"
            source_pdf = Path(proposal.candidate.path)
            if archive_matched and source_pdf.exists():
                archived_original_path = _archive_matched_pdf(paths, run_slug, source_pdf)
                moved = True
                archived_files.append(Path(archived_original_path).name)
                note = f"Archived matched staging PDF to {archived_original_path}."
            _save_card(paths, card)
            decision_summary["other_runs_synced"] += _sync_attached_card_to_matching_runs(
                paths,
                card,
                exclude_run_id=run_slug,
            )
            paper_card = f"papers/{card.slug}.md"
            run_status = "selected"
            pdf_status = "attached"
            matched_files.append(Path(proposal.candidate.path).name)
            remaining = _consume_candidate(
                remaining,
                original_path=proposal.candidate.path,
                original_sha256=proposal.candidate.sha256,
            )
            log_entries.append(
                ImportLogEntry(
                    source_path=proposal.candidate.path,
                    destination_path=destination_path,
                    status="copied",
                    score=proposal.score,
                    note=note,
                )
            )
        else:
            linked_existing_card = False
            if existing_card and _card_has_valid_pdf(paths, existing_card) and not dry_run:
                card, card_created, card_before = _prepare_card_for_result(
                    cards,
                    result,
                    run_ref=run_ref,
                    prompt=export.prompt,
                )
                card_preexisting = not card_created
                _save_card(paths, card)
                paper_card = f"papers/{card.slug}.md"
                destination_path = card.pdf
                verified = True
                decision = "accepted"
                run_status = "selected"
                pdf_status = "attached"
                note = "Linked existing paper card already in vault."
                linked_existing_card = True
                decision_summary["existing_cards_linked"] += 1
                decision_summary["other_runs_synced"] += _sync_attached_card_to_matching_runs(
                    paths,
                    card,
                    exclude_run_id=run_slug,
                )
                _report_match_progress(
                    progress,
                    result,
                    "linked",
                    f"linked existing card {card.citekey or card.slug}",
                    index,
                    total_results,
                )
            if not linked_existing_card and existing_paper_card:
                paper_card = existing_paper_card
            if not linked_existing_card and include_without_pdf and not dry_run:
                card, card_created, card_before = _prepare_card_for_result(
                    cards,
                    result,
                    run_ref=run_ref,
                    prompt=export.prompt,
                    include_without_pdf=True,
                )
                card_preexisting = not card_created
                _save_card(paths, card)
                paper_card = f"papers/{card.slug}.md"
            if not linked_existing_card and proposal is not None:
                unmatched_files.append(Path(proposal.candidate.path).name)
                if decision == "unresolved":
                    run_status = "unmatched"
                    pdf_status = "unmatched"
                    note = "Match proposed but not committed."
                elif decision == "rejected":
                    note = "User rejected the proposed match."
            if not linked_existing_card and proposal is None:
                decision_summary["results_without_candidate"] += 1
                _report_match_progress(
                    progress,
                    result,
                    "unresolved",
                    "no staged PDF candidate above threshold",
                    index,
                    total_results,
                )

        if prior_result and paper_card is None and prior_result.paper_card and existing_paper_card:
            paper_card = existing_paper_card

        run_results.append(
            RunResultRecord(
                **result.model_dump(),
                status=run_status,
                pdf_status=pdf_status,
                paper_card=paper_card,
                proposed_pdf=(proposal.candidate.path if proposal and proposal.candidate else None),
                proposed_sha256=(
                    proposal.candidate.sha256 if proposal and proposal.candidate else None
                ),
                score=proposal.score if proposal else None,
                decision=decision,
            )
        )
        manifest_entries.append(
            _build_manifest_entry(
                result,
                proposal,
                decision=decision,
                paper_card=paper_card,
                card_created=card_created,
                card_preexisting=card_preexisting,
                card_before=card_before,
                destination_path=destination_path,
                copied=copied,
                moved=moved,
                archived_original_path=archived_original_path,
                verified=verified,
                note=note,
            )
        )

    for candidate in remaining:
        unmatched_files.append(Path(candidate.path).name)
        manifest_entries.append(
            ImportManifestEntry(
                original_path=candidate.path,
                original_sha256=candidate.sha256,
                decision="unresolved",
                note="No Scholar Labs result exceeded the matching threshold.",
            )
        )

    manifest = ImportManifest(
        run_id=run_slug,
        export_file=str(export_file),
        staging_folder=str(staging_dir),
        created_at=_now_iso(),
        entries=manifest_entries,
    )

    run_record = RunRecord(
        slug=run_slug,
        date=run_date,
        prompt=export.prompt,
        title=run_title,
        note_file=run_note_file,
        exported_at=export.exported_at,
        export_file=str(export_file),
        raw_export_file=ensure_relative(raw_export_file, paths.vault),
        staging_folder=str(staging_dir),
        result_count=len(export.results),
        include_without_pdf=include_without_pdf,
        archive_matched_from_staging=archive_matched,
        results=run_results,
        matched_files=sorted(set(matched_files)),
        unmatched_files=sorted(set(unmatched_files)),
    )
    if progress:
        progress("Writing run manifest", None, None)
    _write_manifest(paths, manifest)
    _write_run(paths, run_record, cards)

    enrichment_results: list[EnrichmentResult] = []
    enrichment_details: list[dict[str, Any]] = []
    abstract_details: list[dict[str, Any]] = []
    keyword_details: list[dict[str, Any]] = []
    if auto_enrich and not dry_run:
        selected_slugs = {
            Path(result.paper_card).stem
            for result in run_results
            if result.status == "selected" and result.paper_card
        }
        selected_cards = [card for card in cards if card.slug in selected_slugs]
        if selected_cards:

            def report_citation_progress(
                card: SourceCard,
                index: int,
                total: int,
                status: str,
            ) -> None:
                if progress:
                    progress(
                        _enrichment_progress_message(card, status, abstracts=False),
                        index,
                        total,
                    )

            def report_abstract_progress(
                card: SourceCard,
                index: int,
                total: int,
                status: str,
            ) -> None:
                if progress:
                    progress(
                        _enrichment_progress_message(card, status, abstracts=True),
                        index,
                        total,
                    )

            def report_keyword_progress(
                card: SourceCard,
                index: int,
                total: int,
                status: str,
            ) -> None:
                if progress:
                    progress(
                        _enrichment_progress_message(card, status, keywords=True),
                        index,
                        total,
                    )

            citation_results = enrich_cards(
                paths,
                selected_cards,
                EnrichmentOptions(),
                progress=report_citation_progress,
            )
            enrichment_results.extend(citation_results)
            enrichment_details.extend(
                _enrichment_detail(paths, card, result, abstracts=False)
                for card, result in zip(selected_cards, citation_results, strict=False)
            )
            abstract_results = enrich_cards(
                paths,
                selected_cards,
                EnrichmentOptions(abstracts=True),
                progress=report_abstract_progress,
            )
            enrichment_results.extend(abstract_results)
            abstract_details.extend(
                _enrichment_detail(paths, card, result, abstracts=True)
                for card, result in zip(selected_cards, abstract_results, strict=False)
            )
            keyword_results = enrich_cards(
                paths,
                selected_cards,
                EnrichmentOptions(only="missing-keywords"),
                progress=report_keyword_progress,
            )
            enrichment_results.extend(keyword_results)
            keyword_details.extend(
                _enrichment_detail(paths, card, result, abstracts=False, keywords=True)
                for card, result in zip(selected_cards, keyword_results, strict=False)
            )
            for card in selected_cards:
                _save_card(paths, card)

    citation_processed = len(enrichment_details)
    abstract_processed = len(abstract_details)
    keyword_processed = len(keyword_details)
    citation_changed = sum(1 for row in enrichment_details if row.get("changed"))
    abstract_changed = sum(1 for row in abstract_details if row.get("changed"))
    keyword_changed = sum(1 for row in keyword_details if row.get("changed"))

    if log_entries:
        _write_log(paths, "import-labs" if archive_matched else "import-run", log_entries)
    if progress:
        progress("Rebuilding indexes and exports", None, None)
    _rebuild_indexes(paths)

    archived_export_path = ""
    if archive_export and not dry_run:
        archived_export, archived = _archive_used_export(export_file)
        if archived:
            archived_export_path = str(archived_export)
            manifest.export_file = archived_export_path
            run_record.export_file = archived_export_path
            _write_manifest(paths, manifest)
            _write_run(paths, run_record, load_source_cards(paths))

    return {
        "papers": len([result for result in run_results if result.paper_card]),
        "selected": len([result for result in run_results if result.status == "selected"]),
        "matched": len([result for result in run_results if result.pdf_status == "attached"]),
        "unmatched": len(sorted(set(unmatched_files))),
        "archived": len(sorted(set(archived_files))),
        "unselected_results": len(
            [result for result in run_results if result.status != "selected"]
        ),
        "decision_summary": decision_summary,
        "export_archived": archived_export_path,
        "enriched": len([result for result in enrichment_results if result.changed]),
        "citation_enrichment": {
            "processed": citation_processed,
            "changed": citation_changed,
        },
        "abstract_enrichment": {
            "processed": abstract_processed,
            "changed": abstract_changed,
        },
        "keyword_enrichment": {
            "processed": keyword_processed,
            "changed": keyword_changed,
        },
        "enrichment_details": enrichment_details,
        "abstract_details": abstract_details,
        "keyword_details": keyword_details,
        "run": run_slug,
        "vault": str(paths.vault),
        "staging_folder": str(staging_dir),
        "staging_pdfs_remaining": len(sorted(staging_dir.glob("*.pdf"))),
    }


def resume_run(
    vault: Path | str,
    run_id: str,
    *,
    dry_run: bool = False,
    commit: bool = False,
    auto_enrich: bool = False,
    upgrade_pdfs: bool = False,
    confirm: ConfirmCallback | None = None,
    review_match: MatchReviewCallback | None = None,
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    paths = initialize_vault(vault)
    run = _load_run_record(paths, run_id)
    if run is None:
        raise ValueError(f"Run does not exist: {run_id}")
    if not run.export_file or not run.staging_folder:
        raise ValueError(f"Run {run_id} does not record export_file and staging_folder.")
    return import_scholar_labs_run(
        paths.vault,
        run.export_file,
        run.staging_folder,
        dry_run=dry_run,
        commit=commit,
        include_without_pdf=run.include_without_pdf,
        archive_matched=run.archive_matched_from_staging,
        archive_export=run.archive_matched_from_staging,
        auto_enrich=auto_enrich,
        upgrade_pdfs=upgrade_pdfs,
        title=None,
        confirm=confirm,
        review_match=review_match,
        progress=progress,
    )


def latest_run_id(vault: Path | str) -> str:
    paths = initialize_vault(vault)
    manifest_candidates: list[tuple[datetime, str]] = []
    for manifest in load_import_manifests(paths):
        manifest_candidates.append((_parse_datetime(manifest.created_at), manifest.run_id))
    if manifest_candidates:
        return max(manifest_candidates, key=lambda item: (item[0], item[1]))[1]

    run_candidates = [
        (_parse_datetime(run.exported_at), run.slug) for run in load_run_records(paths)
    ]
    if run_candidates:
        return max(run_candidates, key=lambda item: (item[0], item[1]))[1]
    raise ValueError(f"No runs found in vault: {paths.vault}")


def rename_run(vault: Path | str, run_id: str, title: str) -> dict[str, str]:
    paths = initialize_vault(vault)
    run = _load_run_record(paths, run_id)
    if run is None:
        raise ValueError(f"Run does not exist: {run_id}")

    old_ref = _run_ref(run)
    run.title = run_display_title(title, run.prompt)
    run.note_file = None
    new_ref = _run_ref(run)
    cards = load_source_cards(paths)
    for card in cards:
        card_changed = False
        updated_discovered = [
            new_ref if Path(item).parts[:2] == ("runs", run_id) else item
            for item in card.discovered_in
        ]
        if updated_discovered != card.discovered_in:
            card.discovered_in = updated_discovered
            card_changed = True
        for source in card.summary_sources:
            if Path(source.run).parts[:2] == ("runs", run_id):
                source.run = new_ref
                card_changed = True
        if card_changed:
            _save_card(paths, card)

    _write_run(paths, run, load_source_cards(paths))
    _rebuild_indexes(paths)
    return {"run": run_id, "title": run.title or "", "old_ref": old_ref, "new_ref": new_ref}


def _archive_path(base_dir: Path, filename: str) -> Path:
    base_dir.mkdir(parents=True, exist_ok=True)
    destination = base_dir / filename
    counter = 2
    while destination.exists():
        destination = base_dir / f"{Path(filename).stem}-{counter}{Path(filename).suffix}"
        counter += 1
    return destination


def undo_run(vault: Path | str, run_id: str) -> dict[str, int]:
    paths = initialize_vault(vault)
    run = _load_run_record(paths, run_id)
    manifest = _load_manifest(paths, run_id)
    if run is None or manifest is None:
        raise ValueError(f"Run or manifest does not exist: {run_id}")

    archive_root = paths.raw_imported / "undo-archive" / run_id
    archived_cards = 0
    restored_cards = 0
    restored_originals = 0

    for entry in manifest.entries:
        if not entry.paper_card:
            continue
        card_path = paths.vault / entry.paper_card
        if entry.paper_card_created:
            if card_path.exists():
                destination = _archive_path(archive_root / "papers", Path(entry.paper_card).name)
                shutil.move(str(card_path), str(destination))
                archived_cards += 1
        elif entry.card_before:
            restored = SourceCard.model_validate(entry.card_before)
            _save_card(paths, restored)
            restored_cards += 1

    current_cards = load_source_cards(paths)
    archived_pdfs = 0
    referenced_pdfs = {card.pdf for card in current_cards if card.pdf}
    for entry in manifest.entries:
        if entry.destination_path and entry.copied:
            destination_path = paths.vault / entry.destination_path
            if destination_path.exists() and entry.destination_path not in referenced_pdfs:
                destination = _archive_path(archive_root / "pdfs", destination_path.name)
                shutil.move(str(destination_path), str(destination))
                archived_pdfs += 1
        if entry.moved and entry.archived_original_path and entry.original_path:
            archived_original = paths.vault / entry.archived_original_path
            original_path = Path(entry.original_path)
            if archived_original.exists() and not original_path.exists():
                original_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(archived_original), str(original_path))
                restored_originals += 1

    run_dir = paths.runs / run_id
    if run_dir.exists():
        destination = archive_root / "run"
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            shutil.rmtree(destination)
        shutil.move(str(run_dir), str(destination))

    _rebuild_indexes(paths)
    return {
        "archived_cards": archived_cards,
        "restored_cards": restored_cards,
        "archived_pdfs": archived_pdfs,
        "restored_originals": restored_originals,
    }


def _run_result_matches_card(card: SourceCard, result: RunResultRecord) -> bool:
    if card.scholar_cid and result.scholar_cid and result.scholar_cid == card.scholar_cid:
        return True
    return normalize_title(result.title) == normalize_title(card.title)


def _manifest_entry_matches_card(card: SourceCard, entry: ImportManifestEntry) -> bool:
    if card.scholar_cid and entry.scholar_cid and entry.scholar_cid == card.scholar_cid:
        return True
    return normalize_title(entry.result_title) == normalize_title(card.title)


def _sync_manifest_entry_to_card(entry: ImportManifestEntry, card: SourceCard) -> bool:
    paper_card = f"papers/{card.slug}.md"
    changed = False
    updates = {
        "decision": "accepted",
        "paper_card": paper_card,
        "destination_path": card.pdf,
        "card_preexisting": True,
        "verified": True,
        "note": "Linked to attached paper card from another run.",
    }
    for key, value in updates.items():
        if getattr(entry, key) != value:
            setattr(entry, key, value)
            changed = True
    return changed


def _repair_run_links_to_attached_cards(
    paths: VaultPaths,
    runs: list[RunRecord],
    cards: list[SourceCard],
    manifests: list[ImportManifest],
) -> int:
    attached_cards = [card for card in cards if _card_has_valid_pdf(paths, card)]
    manifests_by_run = {manifest.run_id: manifest for manifest in manifests}
    synced = 0

    for run in runs:
        run_changed = False
        run_ref = _run_ref(run)
        for result in run.results:
            card = next(
                (item for item in attached_cards if _run_result_matches_card(item, result)),
                None,
            )
            if card is None:
                continue
            paper_card = f"papers/{card.slug}.md"
            if (
                result.status != "selected"
                or result.pdf_status != "attached"
                or result.paper_card != paper_card
            ):
                result.status = "selected"
                result.pdf_status = "attached"
                result.paper_card = paper_card
                synced += 1
                run_changed = True
            if run_ref not in card.discovered_in:
                card.discovered_in.append(run_ref)
                synced += 1
        manifest = manifests_by_run.get(run.slug)
        if manifest is not None:
            manifest_changed = False
            for entry in manifest.entries:
                card = next(
                    (
                        item
                        for item in attached_cards
                        if _manifest_entry_matches_card(item, entry)
                    ),
                    None,
                )
                if card is not None:
                    manifest_changed = _sync_manifest_entry_to_card(entry, card) or manifest_changed
            if manifest_changed:
                _write_manifest(paths, manifest)
                if not run_changed:
                    synced += 1
    return synced


def _sync_attached_card_to_matching_runs(
    paths: VaultPaths,
    card: SourceCard,
    *,
    exclude_run_id: str | None = None,
) -> int:
    if not _card_has_valid_pdf(paths, card):
        return 0

    paper_card = f"papers/{card.slug}.md"
    changed_runs: list[RunRecord] = []
    updated_results = 0
    for run in load_run_records(paths):
        if exclude_run_id and run.slug == exclude_run_id:
            continue
        changed = False
        for result in run.results:
            if not _run_result_matches_card(card, result):
                continue
            if (
                result.status != "selected"
                or result.pdf_status != "attached"
                or result.paper_card != paper_card
            ):
                result.status = "selected"
                result.pdf_status = "attached"
                result.paper_card = paper_card
                updated_results += 1
                changed = True
        if changed:
            run_ref = _run_ref(run)
            if run_ref not in card.discovered_in:
                card.discovered_in.append(run_ref)
            changed_runs.append(run)

    if not changed_runs:
        return 0

    _save_card(paths, card)
    cards = load_source_cards(paths)
    for run in changed_runs:
        manifest = _load_manifest(paths, run.slug)
        if manifest is not None:
            manifest_changed = False
            for entry in manifest.entries:
                if not _manifest_entry_matches_card(card, entry):
                    continue
                manifest_changed = _sync_manifest_entry_to_card(entry, card) or manifest_changed
            if manifest_changed:
                _write_manifest(paths, manifest)
        _write_run(paths, run, cards)
    return updated_results


def _find_result_in_run(
    run: RunRecord,
    *,
    rank: int | None = None,
    scholar_cid: str | None = None,
    title: str | None = None,
) -> RunResultRecord:
    normalized_title = normalize_title(title)
    for result in run.results:
        if scholar_cid and result.scholar_cid and result.scholar_cid == scholar_cid:
            return result
    for result in run.results:
        if rank is not None and result.rank == rank:
            if not normalized_title or normalize_title(result.title) == normalized_title:
                return result
    if normalized_title:
        for result in run.results:
            if normalize_title(result.title) == normalized_title:
                return result
    raise ValueError(f"No matching result found in run {run.slug}.")


def _replace_manifest_entry(
    manifest: ImportManifest,
    result: RunResultRecord,
    accepted_entry: ImportManifestEntry,
    candidate: PdfCandidate,
) -> None:
    result_key = _result_key(result)
    updated_entries: list[ImportManifestEntry] = []
    replaced = False
    for entry in manifest.entries:
        entry_key = (
            f"cid:{entry.scholar_cid}"
            if entry.scholar_cid
            else f"title:{normalize_title(entry.result_title)}"
        )
        if entry_key == result_key:
            if not replaced:
                updated_entries.append(accepted_entry)
                replaced = True
            continue
        if (
            candidate.path
            and entry.original_path == candidate.path
            and entry.decision != "accepted"
        ):
            continue
        if (
            candidate.sha256
            and entry.original_sha256 == candidate.sha256
            and entry.decision != "accepted"
        ):
            continue
        updated_entries.append(entry)
    if not replaced:
        updated_entries.append(accepted_entry)
    manifest.entries = updated_entries


def _enrich_touched_cards(
    paths: VaultPaths,
    cards: list[SourceCard],
    *,
    progress: ProgressCallback | None = None,
) -> tuple[
    list[EnrichmentResult],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    unique_cards = list({card.slug: card for card in cards}.values())
    enrichment_results: list[EnrichmentResult] = []
    enrichment_details: list[dict[str, Any]] = []
    abstract_details: list[dict[str, Any]] = []
    keyword_details: list[dict[str, Any]] = []
    if not unique_cards:
        return enrichment_results, enrichment_details, abstract_details, keyword_details

    def report_citation_progress(
        card: SourceCard,
        index: int,
        total: int,
        status: str,
    ) -> None:
        if progress:
            progress(
                _enrichment_progress_message(card, status, abstracts=False),
                index,
                total,
            )

    def report_abstract_progress(
        card: SourceCard,
        index: int,
        total: int,
        status: str,
    ) -> None:
        if progress:
            progress(
                _enrichment_progress_message(card, status, abstracts=True),
                index,
                total,
            )

    def report_keyword_progress(
        card: SourceCard,
        index: int,
        total: int,
        status: str,
    ) -> None:
        if progress:
            progress(
                _enrichment_progress_message(card, status, keywords=True),
                index,
                total,
            )

    citation_results = enrich_cards(
        paths,
        unique_cards,
        EnrichmentOptions(),
        progress=report_citation_progress,
    )
    enrichment_results.extend(citation_results)
    enrichment_details.extend(
        _enrichment_detail(paths, card, result, abstracts=False)
        for card, result in zip(unique_cards, citation_results, strict=False)
    )
    abstract_results = enrich_cards(
        paths,
        unique_cards,
        EnrichmentOptions(abstracts=True),
        progress=report_abstract_progress,
    )
    enrichment_results.extend(abstract_results)
    abstract_details.extend(
        _enrichment_detail(paths, card, result, abstracts=True)
        for card, result in zip(unique_cards, abstract_results, strict=False)
    )
    keyword_results = enrich_cards(
        paths,
        unique_cards,
        EnrichmentOptions(only="missing-keywords"),
        progress=report_keyword_progress,
    )
    enrichment_results.extend(keyword_results)
    keyword_details.extend(
        _enrichment_detail(paths, card, result, abstracts=False, keywords=True)
        for card, result in zip(unique_cards, keyword_results, strict=False)
    )
    for card in unique_cards:
        _save_card(paths, card)
    return enrichment_results, enrichment_details, abstract_details, keyword_details


def import_staged_pdf_match(
    vault: Path | str,
    run_id: str,
    pdf_path: Path | str,
    *,
    rank: int | None = None,
    scholar_cid: str | None = None,
    result_title: str | None = None,
    score: int | None = None,
    match_reason: str | None = None,
    auto_enrich: bool = True,
    archive_matched: bool = True,
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    paths = initialize_vault(vault)
    run = _load_run_record(paths, run_id)
    if run is None:
        raise ValueError(f"Run does not exist: {run_id}")

    source_pdf = Path(pdf_path).expanduser().resolve()
    if not source_pdf.exists():
        raise ValueError(f"PDF does not exist: {source_pdf}")
    if source_pdf.suffix.casefold() != ".pdf":
        raise ValueError(f"Expected a PDF file: {source_pdf}")

    if progress:
        progress(f"Scanning targeted PDF {source_pdf.name}", 1, 1)
    candidate = build_pdf_candidate(source_pdf)
    run_ref = _run_ref(run)
    cards = load_source_cards(paths)
    result = _find_result_in_run(
        run,
        rank=rank,
        scholar_cid=scholar_cid,
        title=result_title,
    )

    existing_card = _find_card_for_run_result(paths, cards, result, run_ref)
    if existing_card and _card_has_valid_pdf(paths, existing_card):
        paper_card = f"papers/{existing_card.slug}.md"
        return {
            "papers": 1,
            "selected": 1,
            "matched": 1,
            "unmatched": len(set(run.unmatched_files)),
            "archived": 0,
            "unselected_results": len([item for item in run.results if item.status != "selected"]),
            "decision_summary": {
                "existing_run": True,
                "export_results": len(run.results),
                "staged_pdfs_scanned": 1,
                "staged_pdf_cache_hits": 0,
                "prior_selected_reused": 1,
                "existing_cards_linked": 0,
                "new_staged_pdf_matches": 0,
                "review_prompts": 0,
                "review_accepted": 0,
                "review_rejected": 0,
                "commit_auto_accepted": 0,
                "commit_proposals_skipped": 0,
                "proposed_not_committed": 0,
                "results_without_candidate": 0,
                "pdf_upgrade_candidates": 0,
                "pdf_upgrades": 0,
                "pdf_upgrade_skipped": 0,
                "other_runs_synced": 0,
                "targeted_import": True,
            },
            "export_archived": "",
            "enriched": 0,
            "citation_enrichment": {"processed": 0, "changed": 0},
            "abstract_enrichment": {"processed": 0, "changed": 0},
            "keyword_enrichment": {"processed": 0, "changed": 0},
            "enrichment_details": [],
            "abstract_details": [],
            "keyword_details": [],
            "run": run.slug,
            "vault": str(paths.vault),
            "staging_folder": run.staging_folder,
            "staging_pdfs_remaining": (
                len(sorted(Path(run.staging_folder).expanduser().glob("*.pdf")))
                if run.staging_folder
                else 0
            ),
            "paper_card": paper_card,
            "note": "Run result already has an attached vault PDF.",
        }

    proposal = MatchDecision(
        candidate=candidate,
        score=(
            score
            if score is not None
            else score_title_match(result.title, candidate.title or source_pdf.stem)
        ),
        decision="auto",
        reason=match_reason or "targeted-staging-match",
    )

    if progress:
        progress(f"Creating or updating card for {result.title}", 1, 1)
    card, card_created, card_before = _prepare_card_for_result(
        cards,
        result,
        run_ref=run_ref,
        prompt=run.prompt,
    )
    destination_path, copied, verified = _copy_pdf_to_vault(
        paths,
        source_pdf,
        card,
        original_sha256=candidate.sha256 or _file_sha256(source_pdf),
    )
    card.pdf = destination_path
    card.pdf_status = "attached"
    card.status = "active"
    card.keywords = _merge_unique(card.keywords, extract_pdf_keywords(candidate.text_excerpt))
    if card.keywords:
        card.publication_keywords_status = "present"
        card.publication_keywords_source = card.publication_keywords_source or "pdf_extracted"
    _record_pdf_metadata_from_candidate(card, candidate)

    archived_original_path = None
    moved = False
    archived_files: list[str] = []
    note = "Copied targeted staging PDF into the vault."
    staging_dir = Path(run.staging_folder).expanduser().resolve() if run.staging_folder else None
    if (
        archive_matched
        and source_pdf.exists()
        and staging_dir is not None
        and _is_relative_to(source_pdf, staging_dir)
    ):
        archived_original_path = _archive_matched_pdf(paths, run.slug, source_pdf)
        moved = True
        archived_files.append(Path(archived_original_path).name)
        note = f"Archived targeted staging PDF to {archived_original_path}."

    _save_card(paths, card)
    paper_card = f"papers/{card.slug}.md"
    result.status = "selected"
    result.pdf_status = "attached"
    result.paper_card = paper_card
    result.proposed_pdf = candidate.path
    result.proposed_sha256 = candidate.sha256
    result.score = proposal.score
    result.decision = "accepted"

    original_name = source_pdf.name
    run.matched_files = sorted(set([*run.matched_files, original_name]))
    run.unmatched_files = sorted(name for name in set(run.unmatched_files) if name != original_name)

    manifest = _load_manifest(paths, run.slug) or ImportManifest(
        run_id=run.slug,
        export_file=run.export_file,
        staging_folder=run.staging_folder,
        created_at=_now_iso(),
        entries=[],
    )
    accepted_entry = _build_manifest_entry(
        result,
        proposal,
        decision="accepted",
        paper_card=paper_card,
        card_created=card_created,
        card_preexisting=not card_created,
        card_before=card_before,
        destination_path=destination_path,
        copied=copied,
        moved=moved,
        archived_original_path=archived_original_path,
        verified=verified,
        note=note,
    )
    _replace_manifest_entry(manifest, result, accepted_entry, candidate)
    _write_manifest(paths, manifest)

    synced = _sync_attached_card_to_matching_runs(paths, card, exclude_run_id=run.slug)
    _write_run(paths, run, load_source_cards(paths))
    _write_log(
        paths,
        "match-staging",
        [
            ImportLogEntry(
                source_path=candidate.path,
                destination_path=destination_path,
                status="accepted",
                score=proposal.score,
                note=note,
            )
        ],
    )

    enrichment_results: list[EnrichmentResult] = []
    enrichment_details: list[dict[str, Any]] = []
    abstract_details: list[dict[str, Any]] = []
    keyword_details: list[dict[str, Any]] = []
    if auto_enrich:
        enrichment_results, enrichment_details, abstract_details, keyword_details = (
            _enrich_touched_cards(paths, [card], progress=progress)
        )

    if progress:
        progress("Rebuilding indexes and exports", None, None)
    _rebuild_indexes(paths)

    citation_processed = len(enrichment_details)
    abstract_processed = len(abstract_details)
    keyword_processed = len(keyword_details)
    citation_changed = sum(1 for row in enrichment_details if row.get("changed"))
    abstract_changed = sum(1 for row in abstract_details if row.get("changed"))
    keyword_changed = sum(1 for row in keyword_details if row.get("changed"))
    return {
        "papers": 1,
        "selected": len([item for item in run.results if item.status == "selected"]),
        "matched": len([item for item in run.results if item.pdf_status == "attached"]),
        "unmatched": len(sorted(set(run.unmatched_files))),
        "archived": len(sorted(set(archived_files))),
        "unselected_results": len([item for item in run.results if item.status != "selected"]),
        "decision_summary": {
            "existing_run": True,
            "export_results": len(run.results),
            "staged_pdfs_scanned": 1,
            "staged_pdf_cache_hits": 0,
            "prior_selected_reused": 0,
            "existing_cards_linked": 0,
            "new_staged_pdf_matches": 1,
            "review_prompts": 0,
            "review_accepted": 0,
            "review_rejected": 0,
            "commit_auto_accepted": 0,
            "commit_proposals_skipped": 0,
            "proposed_not_committed": 0,
            "results_without_candidate": 0,
            "pdf_upgrade_candidates": 0,
            "pdf_upgrades": 0,
            "pdf_upgrade_skipped": 0,
            "other_runs_synced": synced,
            "targeted_import": True,
        },
        "export_archived": "",
        "enriched": len([result for result in enrichment_results if result.changed]),
        "citation_enrichment": {
            "processed": citation_processed,
            "changed": citation_changed,
        },
        "abstract_enrichment": {
            "processed": abstract_processed,
            "changed": abstract_changed,
        },
        "keyword_enrichment": {
            "processed": keyword_processed,
            "changed": keyword_changed,
        },
        "enrichment_details": enrichment_details,
        "abstract_details": abstract_details,
        "keyword_details": keyword_details,
        "run": run.slug,
        "vault": str(paths.vault),
        "staging_folder": str(staging_dir) if staging_dir else run.staging_folder,
        "staging_pdfs_remaining": (
            len(sorted(staging_dir.glob("*.pdf"))) if staging_dir and staging_dir.exists() else 0
        ),
        "paper_card": paper_card,
        "pdf": destination_path,
        "note": note,
    }


def attach_pdf(vault: Path | str, citekey: str, pdf_path: Path | str) -> dict[str, str | bool]:
    paths = initialize_vault(vault)
    cards = load_source_cards(paths)
    card = next((item for item in cards if item.citekey == citekey), None)
    if card is None:
        raise ValueError(f"No paper card found for citekey: {citekey}")

    source_pdf = Path(pdf_path).expanduser().resolve()
    destination_path, copied, verified = _copy_pdf_to_vault(
        paths,
        source_pdf,
        card,
        original_sha256=_file_sha256(source_pdf),
    )
    card.pdf = destination_path
    card.pdf_status = "attached"
    card.status = "active"
    _save_card(paths, card)
    _sync_attached_card_to_matching_runs(paths, card)
    _rebuild_indexes(paths)
    return {"pdf": destination_path, "copied": copied, "verified": verified}


def list_unmatched(vault: Path | str) -> list[dict[str, str | int | None]]:
    paths = initialize_vault(vault)
    rows: list[dict[str, str | int | None]] = []
    for manifest in load_import_manifests(paths):
        for entry in manifest.entries:
            if entry.original_path and entry.decision != "accepted":
                rows.append(
                    {
                        "run_id": manifest.run_id,
                        "original_path": entry.original_path,
                        "proposed_match": entry.proposed_match,
                        "score": entry.score,
                        "decision": entry.decision,
                    }
                )
    return rows


def _run_result_has_attached_pdf(
    paths: VaultPaths,
    cards_by_path: dict[str, SourceCard],
    result: RunResultRecord,
) -> bool:
    if not result.paper_card:
        return False
    card = cards_by_path.get(result.paper_card)
    return bool(card and _card_has_valid_pdf(paths, card))


def find_staged_run_matches(
    vault: Path | str,
    staging_path: Path | str,
    *,
    title: str | None = None,
    pdf_path: Path | str | None = None,
    min_score: int = 60,
    limit: int = 50,
    unselected_only: bool = False,
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    paths = initialize_vault(vault)
    staging_dir = Path(staging_path).expanduser().resolve()
    query_title = clean_markdown_text(title)
    query_pdf = Path(pdf_path).expanduser().resolve() if pdf_path else None
    if min_score < 0 or min_score > 100:
        raise ValueError("--min-score must be between 0 and 100.")
    if limit < 0:
        raise ValueError("--limit must be 0 or greater.")

    runs = sorted(
        load_run_records(paths),
        key=lambda item: (_parse_datetime(item.exported_at), item.slug),
        reverse=True,
    )
    cards_by_path = {f"papers/{card.slug}.md": card for card in load_source_cards(paths)}

    candidates: list[PdfCandidate] = []
    query_pdf_candidate: PdfCandidate | None = None
    cache_hits = 0
    if query_pdf is not None:
        if progress:
            progress(f"Scanning PDF {query_pdf.name}", 1, 1)
        query_pdf_candidate = build_pdf_candidate(query_pdf)
        if not query_title:
            candidates = [query_pdf_candidate]
    elif not query_title:
        staged_pdf_paths = sorted(staging_dir.glob("*.pdf"))
        if progress:
            progress(f"Scanning {len(staged_pdf_paths)} staged PDFs", 0, len(staged_pdf_paths))
        candidates, cache_hits = _build_staged_pdf_candidates(
            staging_dir,
            staged_pdf_paths,
            dry_run=True,
            progress=progress,
        )

    rows: list[dict[str, Any]] = []
    total_results = sum(len(run.results) for run in runs) or 1
    seen_results = 0
    for run in runs:
        for result in run.results:
            seen_results += 1
            if progress:
                progress(
                    f"Scoring previous run result {result.title}",
                    seen_results,
                    total_results,
                )
            attached = _run_result_has_attached_pdf(paths, cards_by_path, result)
            if unselected_only and result.status == "selected" and attached:
                continue

            row_base = {
                "run_id": run.slug,
                "run_title": run.title or infer_run_title(run.prompt),
                "exported_at": run.exported_at,
                "rank": result.rank,
                "scholar_cid": result.scholar_cid,
                "result_title": result.title,
                "authors_preview": result.authors_preview,
                "year": result.year,
                "venue": result.venue,
                "summary": result.summary,
                "rationale_points": [
                    point.model_dump(exclude_none=True) for point in result.rationale_points
                ],
                "status": result.status,
                "pdf_status": result.pdf_status,
                "paper_card": result.paper_card,
                "attached": attached,
            }

            if query_title:
                score = score_title_match(query_title, result.title)
                if score >= min_score:
                    rows.append(
                        {
                            **row_base,
                            "score": score,
                            "decision": "query",
                            "reason": "typed-title+pdf" if query_pdf_candidate else "typed-title",
                            "query_title": query_title,
                            "pdf_path": str(query_pdf) if query_pdf else None,
                            "pdf_filename": query_pdf.name if query_pdf else None,
                            "pdf_title": query_pdf_candidate.title if query_pdf_candidate else None,
                        }
                    )

            for candidate in candidates:
                match = best_pdf_match(result.title, [candidate])
                if match.score < min_score:
                    continue
                rows.append(
                    {
                        **row_base,
                        "score": match.score,
                        "decision": match.decision,
                        "reason": match.reason,
                        "query_title": query_title or None,
                        "pdf_path": candidate.path,
                        "pdf_filename": Path(candidate.path).name,
                        "pdf_title": candidate.title,
                    }
                )

    rows.sort(
        key=lambda row: (
            int(row["score"]),
            str(row.get("exported_at") or ""),
            -int(row.get("rank") or 0),
        ),
        reverse=True,
    )
    if limit:
        rows = rows[:limit]
    scanned_count = len(candidates) + (1 if query_pdf_candidate and query_title else 0)
    return {
        "runs": len(runs),
        "staged_pdfs_scanned": scanned_count,
        "staged_pdf_cache_hits": cache_hits,
        "query_title": query_title or None,
        "query_pdf": str(query_pdf) if query_pdf else None,
        "min_score": min_score,
        "matches": rows,
    }


def clean_staging(vault: Path | str, staging_path: Path | str) -> dict[str, int]:
    paths = initialize_vault(vault)
    staging_dir = Path(staging_path).expanduser().resolve()
    vault_hashes = {_file_sha256(path) for path in paths.pdfs.glob("*.pdf")}
    moved = 0
    kept = 0
    archive_dir = paths.raw_imported / "clean-staging"

    for pdf_path in sorted(staging_dir.glob("*.pdf")):
        pdf_hash = _file_sha256(pdf_path)
        if pdf_hash in vault_hashes:
            destination = _archive_path(archive_dir, pdf_path.name)
            shutil.move(str(pdf_path), str(destination))
            moved += 1
        else:
            kept += 1
    return {"moved": moved, "kept": kept}


def cleanup_run_selected_only(vault: Path | str, run_id: str) -> dict[str, int]:
    paths = initialize_vault(vault)
    run = _load_run_record(paths, run_id)
    if run is None:
        raise ValueError(f"Run does not exist: {run_id}")

    cards = load_source_cards(paths)
    run_ref = _run_ref(run)
    archive_dir = paths.raw_imported / "cleanup-archive" / run_id
    archived = 0
    kept = 0

    for result in run.results:
        card = _find_card_for_run_result(paths, cards, result, run_ref)
        if card is None:
            result.paper_card = None
            if result.status == "selected":
                result.status = "candidate"
                result.pdf_status = "missing"
            continue
        if _card_has_valid_pdf(paths, card):
            result.status = "selected"
            result.pdf_status = "attached"
            result.paper_card = f"papers/{card.slug}.md"
            kept += 1
            continue
        if card.source_kind == "scholar_labs":
            card_path = paths.papers / f"{card.slug}.md"
            if card_path.exists():
                destination = _archive_path(archive_dir, card_path.name)
                shutil.move(str(card_path), str(destination))
                archived += 1
            result.status = "candidate"
            result.pdf_status = "missing"
            result.paper_card = None
        else:
            kept += 1

    cards = load_source_cards(paths)
    _write_run(paths, run, cards)
    _rebuild_indexes(paths)
    return {"archived": archived, "kept": kept}


def import_pdf_dropins(
    vault: Path | str,
    staging_path: Path | str | None = None,
    *,
    pdf_paths: Iterable[Path | str] | None = None,
    auto_enrich: bool = False,
    confirm: ConfirmCallback | None = None,
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    del confirm
    paths = initialize_vault(vault)
    staging_dir = Path(staging_path).expanduser().resolve() if staging_path else None
    if pdf_paths is None:
        if staging_dir is None:
            raise ValueError("import-pdf needs a staging folder or explicit PDF paths.")
        pdf_files = sorted(staging_dir.glob("*.pdf"))
    else:
        pdf_files = sorted(
            {
                Path(pdf_path).expanduser().resolve()
                for pdf_path in pdf_paths
                if str(pdf_path).strip()
                and Path(pdf_path).expanduser().resolve().suffix.casefold() == ".pdf"
            }
        )
    cards = load_source_cards(paths)
    log_entries: list[ImportLogEntry] = []
    imported = 0
    created = 0
    updated_existing = 0
    imported_cards: list[SourceCard] = []
    imported_rows: list[dict[str, Any]] = []

    if progress:
        progress(f"Importing {len(pdf_files)} PDF files", None, None)

    for index, pdf_path in enumerate(pdf_files, start=1):
        if progress:
            progress(f"Importing PDF {pdf_path.name}", index, len(pdf_files))
        candidate = build_pdf_candidate(pdf_path)
        existing, score = match_candidate_to_cards(candidate, cards)
        card_created = False

        if existing and score >= 90:
            card = existing
            updated_existing += 1
        else:
            title = candidate.title or pdf_path.stem.replace("_", " ").replace("-", " ")
            authors: list[str] = []
            citekey = build_citekey(
                title,
                authors,
                candidate.year,
                existing_keys=[card.citekey for card in cards if card.citekey],
            )
            card = SourceCard(
                slug=build_card_slug(
                    citekey,
                    title,
                    [existing_card.slug for existing_card in cards],
                ),
                citekey=citekey,
                title=title,
                authors=authors,
                year=candidate.year,
                doi=normalize_doi(candidate.doi),
                keywords=extract_pdf_keywords(candidate.text_excerpt),
                source_kind="pdf_drop",
                status="active",
                pdf_status="missing",
                doi_status="detected" if candidate.doi else "missing",
                doi_source="pdf" if candidate.doi else None,
                doi_confidence=0.95 if candidate.doi else None,
                citation_status="missing",
                summary="No summary yet.",
            )
            if card.keywords:
                card.publication_keywords_status = "present"
                card.publication_keywords_source = "pdf_extracted"
            cards.append(card)
            card_created = True
            created += 1

        if candidate.doi and not card.doi:
            card.doi = normalize_doi(candidate.doi)
            card.doi_status = "detected"
            card.doi_source = "pdf"
            card.doi_confidence = 0.95
        if candidate.year and not card.year:
            card.year = candidate.year
        if not card.title and candidate.title:
            card.title = candidate.title
        card.keywords = _merge_unique(card.keywords, extract_pdf_keywords(candidate.text_excerpt))
        if card.keywords:
            card.publication_keywords_status = "present"
            card.publication_keywords_source = (
                card.publication_keywords_source or "pdf_extracted"
            )
        if not card.pdf:
            card.pdf, _, _ = _copy_pdf_to_vault(
                paths,
                pdf_path,
                card,
                original_sha256=candidate.sha256 or _file_sha256(pdf_path),
            )
        card.pdf_status = "attached"
        if card.citation_status in {"partial", "complete", "preview"}:
            card.citation_status = "missing"
        _save_card(paths, card)
        imported += 1
        imported_cards.append(card)
        imported_rows.append(
            {
                "source": str(pdf_path),
                "citekey": card.citekey or card.slug,
                "title": card.title,
                "paper": f"papers/{card.slug}.md",
                "paper_file": str(paths.papers / f"{card.slug}.md"),
                "pdf": card.pdf,
                "pdf_file": str(paths.vault / card.pdf) if card.pdf else None,
                "matched_existing": bool(existing and score >= 90),
                "created": card_created,
                "score": score if existing else None,
            }
        )
        log_entries.append(
            ImportLogEntry(
                source_path=str(pdf_path),
                destination_path=card.pdf,
                status="imported",
                score=score if existing else None,
            )
        )

    enrichment_results: list[EnrichmentResult] = []
    enrichment_details: list[dict[str, Any]] = []
    abstract_details: list[dict[str, Any]] = []
    keyword_details: list[dict[str, Any]] = []
    if auto_enrich and imported_cards:
        unique_cards = list({card.slug: card for card in imported_cards}.values())

        def report_citation_progress(
            card: SourceCard,
            index: int,
            total: int,
            status: str,
        ) -> None:
            if progress:
                progress(
                    _enrichment_progress_message(card, status, abstracts=False),
                    index,
                    total,
                )

        def report_abstract_progress(
            card: SourceCard,
            index: int,
            total: int,
            status: str,
        ) -> None:
            if progress:
                progress(
                    _enrichment_progress_message(card, status, abstracts=True),
                    index,
                    total,
                )

        def report_keyword_progress(
            card: SourceCard,
            index: int,
            total: int,
            status: str,
        ) -> None:
            if progress:
                progress(
                    _enrichment_progress_message(card, status, keywords=True),
                    index,
                    total,
                )

        citation_results = enrich_cards(
            paths,
            unique_cards,
            EnrichmentOptions(),
            progress=report_citation_progress,
        )
        enrichment_results.extend(citation_results)
        enrichment_details.extend(
            _enrichment_detail(paths, card, result, abstracts=False)
            for card, result in zip(unique_cards, citation_results, strict=False)
        )
        abstract_results = enrich_cards(
            paths,
            unique_cards,
            EnrichmentOptions(abstracts=True),
            progress=report_abstract_progress,
        )
        enrichment_results.extend(abstract_results)
        abstract_details.extend(
            _enrichment_detail(paths, card, result, abstracts=True)
            for card, result in zip(unique_cards, abstract_results, strict=False)
        )
        keyword_results = enrich_cards(
            paths,
            unique_cards,
            EnrichmentOptions(only="missing-keywords"),
            progress=report_keyword_progress,
        )
        enrichment_results.extend(keyword_results)
        keyword_details.extend(
            _enrichment_detail(paths, card, result, abstracts=False, keywords=True)
            for card, result in zip(unique_cards, keyword_results, strict=False)
        )
        for card in unique_cards:
            _save_card(paths, card)

    if log_entries:
        _write_log(paths, "import-pdf", log_entries)
    if progress:
        progress("Rebuilding indexes and exports", None, None)
    _rebuild_indexes(paths)
    details = [*enrichment_details, *abstract_details, *keyword_details]
    return {
        "imported": imported,
        "created": created,
        "updated_existing": updated_existing,
        "pdfs": imported_rows,
        "enriched": len([result for result in enrichment_results if result.changed]),
        "citation_enrichment": _enrichment_counts(enrichment_details),
        "abstract_enrichment": _enrichment_counts(abstract_details),
        "keyword_enrichment": _enrichment_counts(keyword_details),
        "enrichment_details": enrichment_details,
        "abstract_details": abstract_details,
        "keyword_details": keyword_details,
        "details": details,
        "vault": str(paths.vault),
        "staging_folder": str(staging_dir) if staging_dir else None,
    }


def import_bibtex(vault: Path | str, bib_path: Path | str) -> dict[str, int]:
    paths = initialize_vault(vault)
    cards = load_source_cards(paths)
    imported = 0
    entries = parse_bibtex_file(Path(bib_path).expanduser().resolve())

    for entry in entries:
        authors = split_bibtex_authors(entry.get("author"))
        title = entry.get("title", "").strip()
        citekey = entry.get("ID")
        existing_keys = [card.citekey for card in cards if card.citekey]
        derived_citekey = citekey or build_citekey(
            title,
            authors,
            None,
            existing_keys=existing_keys,
        )
        incoming = SourceCard(
            slug=build_card_slug(
                derived_citekey,
                title or citekey or "untitled",
                [card.slug for card in cards],
            ),
            citekey=derived_citekey,
            title=title or citekey or "Untitled entry",
            authors_preview=", ".join(authors) if authors else None,
            authors=authors,
            year=int(entry["year"]) if entry.get("year", "").isdigit() else None,
            venue=entry.get("journal") or entry.get("booktitle") or entry.get("publisher"),
            doi=normalize_doi(entry.get("doi")),
            url=entry.get("url"),
            source_kind="bibtex_import",
            keywords=normalize_keywords(entry.get("keywords")),
            doi_status="detected" if normalize_doi(entry.get("doi")) else "missing",
            doi_source="bibtex" if normalize_doi(entry.get("doi")) else None,
            doi_confidence=0.9 if normalize_doi(entry.get("doi")) else None,
            citation_status="generated" if title and authors and entry.get("year") else "missing",
            citation_source="bibtex" if title and authors and entry.get("year") else None,
            summary="No summary yet.",
            notes=entry.get("note", "").strip(),
            links=(
                [Link(label="publication", url=entry["url"], kind="html")]
                if entry.get("url")
                else []
            ),
        )
        existing = _find_existing_card(
            cards,
            doi=incoming.doi,
            title=incoming.title,
            citekey=incoming.citekey,
        )
        card = _merge_cards(existing, incoming) if existing else incoming
        if not existing:
            cards.append(card)
        if not card.pdf:
            for pdf_candidate in extract_pdf_paths(entry):
                pdf_path = Path(pdf_candidate).expanduser()
                if pdf_path.exists():
                    try:
                        card.pdf = (
                            ensure_relative(pdf_path.resolve(), paths.vault)
                            if paths.vault in pdf_path.resolve().parents
                            else str(pdf_path.resolve())
                        )
                    except ValueError:
                        card.pdf = str(pdf_path.resolve())
                    card.pdf_status = "attached"
                    break
        _save_card(paths, card)
        imported += 1

    _rebuild_indexes(paths)
    return {"imported": imported}


def import_doi(vault: Path | str, doi: str) -> dict[str, int]:
    paths = initialize_vault(vault)
    cards = load_source_cards(paths)
    normalized_doi = normalize_doi(doi) or doi.strip().lower()
    existing = _find_existing_card(cards, doi=normalized_doi)
    if existing is None:
        citekey = build_citekey(
            normalized_doi,
            [],
            None,
            existing_keys=[card.citekey for card in cards if card.citekey],
        )
        existing = SourceCard(
            slug=build_card_slug(citekey, normalized_doi, [card.slug for card in cards]),
            citekey=citekey,
            title=f"DOI import {normalized_doi}",
            doi=normalized_doi,
            source_kind="doi_import",
            doi_status="detected",
            doi_source="manual",
            doi_confidence=1.0,
            citation_status="missing",
            pdf_status="missing",
            summary="No summary yet.",
        )
        cards.append(existing)
    _save_card(paths, existing)
    _rebuild_indexes(paths)
    return {"imported": 1}


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


def rebuild_vault(vault: Path | str) -> dict[str, int]:
    paths = initialize_vault(vault, rebuild=False)
    return _rebuild_indexes(paths)


def export_bibtex(
    vault: Path | str,
    *,
    include_local_fields: bool = True,
) -> Path:
    paths = initialize_vault(vault, rebuild=False)
    cards = load_source_cards(paths)
    return write_library_bib(
        cards,
        paths.exports / "library.bib",
        metadata_root=paths.raw_metadata,
        include_local_fields=include_local_fields,
    )


def export_card_bibtex(
    vault: Path | str,
    citekey: str,
    *,
    output: Path | str | None = None,
    include_vault_note: bool = False,
    include_local_fields: bool = True,
    cite: bool = False,
) -> dict[str, Any]:
    paths = initialize_vault(vault, rebuild=False)
    cards = load_source_cards(paths)
    card = next(
        (
            candidate
            for candidate in cards
            if citekey in {candidate.citekey, candidate.slug}
        ),
        None,
    )
    if card is None:
        raise ValueError(f"No paper card found for citekey: {citekey}")
    if cite:
        citekey_value = card.citekey or card.slug
        content = f"\\cite{{{citekey_value}}}\n"
        rendered = None
    else:
        rendered = render_card_bibtex(
            card,
            metadata_root=paths.raw_metadata,
            include_vault_note=include_vault_note,
            include_local_fields=include_local_fields,
            require_ready=False,
        )
        if rendered is None:
            raise ValueError(f"Cannot render BibLaTeX for {citekey}: missing title")
        content = rendered.entry.rstrip() + "\n"
    output_path = Path(output).expanduser().resolve() if output is not None else None
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(content, encoding="utf-8")
    return {
        "vault": str(paths.vault),
        "citekey": card.citekey or card.slug,
        "paper": _card_ref(card),
        "source": "cite" if cite else rendered.source,
        "entry_type": None if cite else rendered.entry_type,
        "warnings": [] if cite else list(rendered.warnings),
        "output": str(output_path) if output_path else None,
        "bibtex": content,
        "content": content,
        "content_kind": "cite" if cite else "biblatex",
    }


def bibtex_doctor(vault: Path | str) -> dict[str, Any]:
    paths = initialize_vault(vault, rebuild=False)
    cards = load_source_cards(paths)
    rows: list[dict[str, Any]] = []
    rendered_count = 0
    for card in cards:
        rendered = render_card_bibtex(
            card,
            metadata_root=paths.raw_metadata,
            include_vault_note=False,
            include_local_fields=True,
            require_ready=False,
        )
        if rendered is None:
            rows.append(
                {
                    "citekey": card.citekey or card.slug,
                    "paper": _card_ref(card),
                    "title": card.title,
                    "entry_type": None,
                    "source": None,
                    "warnings": ["cannot render BibLaTeX: missing title"],
                }
            )
            continue
        rendered_count += 1
        if rendered.warnings:
            rows.append(
                {
                    "citekey": card.citekey or card.slug,
                    "paper": _card_ref(card),
                    "title": card.title,
                    "entry_type": rendered.entry_type,
                    "source": rendered.source,
                    "warnings": list(rendered.warnings),
                }
            )
    return {
        "vault": str(paths.vault),
        "cards": len(cards),
        "rendered": rendered_count,
        "issues": len(rows),
        "rows": rows,
    }


def export_card_reference(
    vault: Path | str,
    citekey: str,
    *,
    output: Path | str | None = None,
    style: str = "apa",
    output_format: str = "markdown",
) -> dict[str, Any]:
    paths = initialize_vault(vault, rebuild=False)
    cards = load_source_cards(paths)
    card = next(
        (
            candidate
            for candidate in cards
            if citekey in {candidate.citekey, candidate.slug}
        ),
        None,
    )
    if card is None:
        raise ValueError(f"No paper card found for citekey: {citekey}")
    rendered = render_card_reference(
        card,
        metadata_root=paths.raw_metadata,
        style=style,
        output_format=output_format,
    )
    if rendered is None:
        raise ValueError(f"Cannot render reference for {citekey}: missing title")
    output_path = Path(output).expanduser().resolve() if output is not None else None
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered.content, encoding="utf-8")
    return {
        "vault": str(paths.vault),
        "citekey": card.citekey or card.slug,
        "paper": _card_ref(card),
        "source": rendered.source,
        "style": rendered.style,
        "format": rendered.output_format,
        "warnings": list(rendered.warnings),
        "output": str(output_path) if output_path else None,
        "content": rendered.content,
    }


def export_references(
    vault: Path | str,
    *,
    output: Path | str | None = None,
    style: str = "apa",
    output_format: str = "markdown",
) -> dict[str, Any]:
    style = style.casefold()
    output_format = output_format.casefold()
    if style not in REFERENCE_STYLES:
        raise ValueError(f"Unsupported reference style: {style}")
    if output_format not in REFERENCE_FORMATS:
        raise ValueError(f"Unsupported reference format: {output_format}")
    paths = initialize_vault(vault, rebuild=False)
    cards = load_source_cards(paths)
    rendered_entries = []
    rows: list[dict[str, Any]] = []
    for card in sorted(cards, key=lambda item: (item.authors[0] if item.authors else item.title)):
        rendered = render_card_reference(
            card,
            metadata_root=paths.raw_metadata,
            style=style,
            output_format=output_format,
            wrap_rtf=False,
        )
        if rendered is None:
            rows.append(
                {
                    "citekey": card.citekey or card.slug,
                    "paper": _card_ref(card),
                    "warnings": ["cannot render reference: missing title"],
                }
            )
            continue
        rendered_entries.append(rendered.content.rstrip())
        if rendered.warnings:
            rows.append(
                {
                    "citekey": card.citekey or card.slug,
                    "paper": _card_ref(card),
                    "warnings": list(rendered.warnings),
                }
            )
    extension = {"markdown": "md", "plain": "txt", "rtf": "rtf"}[output_format]
    output_path = (
        Path(output).expanduser().resolve()
        if output is not None
        else paths.exports / f"references-{style}.{extension}"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_format == "rtf":
        content = r"{\rtf1\ansi " + "\n".join(rendered_entries).rstrip() + "\n}\n"
    else:
        content = "\n\n".join(rendered_entries).rstrip() + "\n"
    output_path.write_text(content, encoding="utf-8")
    return {
        "vault": str(paths.vault),
        "style": style,
        "format": output_format,
        "output": str(output_path),
        "references": len(rendered_entries),
        "warnings": rows,
    }


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


def _display_path(path: Path, root: Path) -> str:
    try:
        return ensure_relative(path, root)
    except ValueError:
        return str(path)


def _card_ref(card: SourceCard) -> str:
    return f"papers/{card.slug}.md"


def _card_id(card: SourceCard) -> str:
    return card.citekey or card.slug


def _status_counts(cards: list[SourceCard], field: str) -> dict[str, int]:
    counts = Counter(str(getattr(card, field, None) or "missing") for card in cards)
    return dict(sorted(counts.items()))


def _card_issue(card: SourceCard, *, issue: str) -> dict[str, Any]:
    return {
        "citekey": _card_id(card),
        "paper": _card_ref(card),
        "title": card.title,
        "issue": issue,
        "doi": card.doi,
        "venue": card.venue,
        "citation_status": card.citation_status,
        "doi_status": card.doi_status,
        "enrichment_status": card.enrichment_status,
        "enrichment_missing": list(card.enrichment_missing),
        "abstract_status": card.abstract_status,
        "publication_keywords_status": card.publication_keywords_status,
        "pdf": card.pdf,
    }


def _card_followup_kinds(card: SourceCard) -> list[str]:
    issue_states = {"incomplete", "ambiguous", "unresolved"}
    kinds: list[str] = []
    if card.enrichment_refresh:
        kinds.append("refresh")
    if card.enrichment_status in issue_states or card.enrichment_missing:
        kinds.append("metadata")
    if card.citation_status in issue_states:
        kinds.append("citation")
    if card.abstract_status in issue_states:
        kinds.append("abstract")
    if (
        card.pdf
        and not card.keywords
        and card.publication_keywords_status != "absent"
    ):
        kinds.append("keywords")
    if card.doi_status in {"ambiguous", "unresolved"}:
        kinds.append("doi")
    return kinds


def _refresh_card_completeness(card: SourceCard) -> bool:
    before = (
        card.enrichment_status,
        tuple(card.enrichment_missing),
    )
    refresh_metadata_completeness(card)
    return before != (card.enrichment_status, tuple(card.enrichment_missing))


def _topic_report(cards: list[SourceCard], *, limit: int = 30) -> dict[str, Any]:
    counts = Counter(topic for card in cards for topic in card.topics)
    noisy = [
        {"topic": topic, "count": count}
        for topic, count in counts.most_common()
        if normalize_title(topic) in NOISY_TOPIC_KEYS
    ]
    return {
        "topic_count": len(counts),
        "top": [
            {"topic": topic, "count": count}
            for topic, count in counts.most_common(limit)
        ],
        "noisy": noisy,
    }


def _run_issue_summary(
    run: RunRecord,
    cards_by_path: dict[str, SourceCard],
) -> dict[str, Any]:
    status_counts = Counter(result.status for result in run.results)
    pdf_status_counts = Counter(result.pdf_status for result in run.results)
    followups: Counter[str] = Counter()
    missing_candidates = 0
    for result in run.results:
        if result.paper_card and result.paper_card in cards_by_path:
            followups.update(_card_followup_kinds(cards_by_path[result.paper_card]))
            continue
        if result.pdf_status != "attached":
            missing_candidates += 1
    return {
        "run_id": run.slug,
        "title": run.title or infer_run_title(run.prompt),
        "result_count": len(run.results),
        "status_counts": dict(sorted(status_counts.items())),
        "pdf_status_counts": dict(sorted(pdf_status_counts.items())),
        "missing_candidate_pdfs": missing_candidates,
        "candidate_results_without_cards": missing_candidates,
        "followups": dict(sorted(followups.items())),
    }


def _unmatched_rows_from_manifests(
    manifests: list[ImportManifest],
) -> list[dict[str, str | int | None]]:
    rows: list[dict[str, str | int | None]] = []
    for manifest in manifests:
        for entry in manifest.entries:
            if entry.original_path and entry.decision != "accepted":
                rows.append(
                    {
                        "run_id": manifest.run_id,
                        "original_path": entry.original_path,
                        "filename": Path(entry.original_path).name,
                        "proposed_match": entry.proposed_match,
                        "score": entry.score,
                        "decision": entry.decision,
                    }
                )
    return rows


def _repeated_unmatched_files(
    rows: list[dict[str, str | int | None]],
) -> list[dict[str, Any]]:
    by_name: dict[str, list[dict[str, str | int | None]]] = defaultdict(list)
    for row in rows:
        by_name[str(row["filename"])].append(row)
    repeated = [
        {
            "filename": filename,
            "count": len(items),
            "runs": sorted({str(item["run_id"]) for item in items}),
            "best_score": max(
                int(item["score"] or 0)
                for item in items
            ),
        }
        for filename, items in by_name.items()
        if len(items) > 1
    ]
    repeated.sort(key=lambda item: (int(item["count"]), int(item["best_score"])), reverse=True)
    return repeated


def pdf_doctor(
    vault: Path | str,
    *,
    staging_path: Path | str | None = None,
) -> dict[str, Any]:
    paths = VaultPaths.from_root(vault)
    cards = load_source_cards(paths)
    manifests = load_import_manifests(paths)
    pdf_files = sorted(paths.pdfs.glob("*.pdf"))
    unmatched_rows = _unmatched_rows_from_manifests(manifests)

    referenced_pdf_paths: set[Path] = set()
    cards_without_pdf: list[dict[str, Any]] = []
    missing_card_pdfs: list[dict[str, Any]] = []
    for card in cards:
        if not card.pdf:
            cards_without_pdf.append(_card_issue(card, issue="card has no pdf field"))
            continue
        pdf_path = Path(card.pdf)
        if not pdf_path.is_absolute():
            pdf_path = paths.vault / pdf_path
        if pdf_path.exists():
            referenced_pdf_paths.add(pdf_path.resolve())
        else:
            missing_card_pdfs.append(
                {
                    **_card_issue(card, issue="card pdf file is missing"),
                    "pdf": card.pdf,
                }
            )

    orphan_pdfs = [
        _display_path(path, paths.vault)
        for path in pdf_files
        if path.resolve() not in referenced_pdf_paths
    ]
    duplicate_style = [
        _display_path(path, paths.vault)
        for path in pdf_files
        if re.search(r"-\d+\.pdf$", path.name, flags=re.IGNORECASE)
    ]

    hashes: dict[str, list[str]] = defaultdict(list)
    hash_errors: list[dict[str, str]] = []
    for path in pdf_files:
        try:
            hashes[_file_sha256(path)].append(_display_path(path, paths.vault))
        except OSError as exc:
            hash_errors.append({"path": _display_path(path, paths.vault), "error": str(exc)})
    duplicate_hashes = [
        {"sha256": digest, "files": files}
        for digest, files in sorted(hashes.items())
        if len(files) > 1
    ]

    staging_summary: dict[str, Any] | None = None
    if staging_path is not None:
        staging_dir = Path(staging_path).expanduser().resolve()
        staged_pdfs = sorted(staging_dir.glob("*.pdf"))
        vault_hashes = {digest: files for digest, files in hashes.items()}
        staged_duplicates: list[dict[str, Any]] = []
        actionable_staged_pdfs: list[str] = []
        for staged_pdf in staged_pdfs:
            try:
                digest = _file_sha256(staged_pdf)
            except OSError as exc:
                hash_errors.append({"path": str(staged_pdf), "error": str(exc)})
                continue
            if digest in vault_hashes:
                staged_duplicates.append(
                    {
                        "staging_pdf": str(staged_pdf),
                        "sha256": digest,
                        "vault_pdfs": vault_hashes[digest],
                    }
                )
            else:
                actionable_staged_pdfs.append(str(staged_pdf))
        staging_summary = {
            "path": str(staging_dir),
            "pdf_count": len(staged_pdfs),
            "duplicates_in_vault": staged_duplicates,
            "duplicate_count": len(staged_duplicates),
            "actionable_pdfs": actionable_staged_pdfs,
            "actionable_pdf_count": len(actionable_staged_pdfs),
        }

    return {
        "vault": str(paths.vault),
        "pdf_files": len(pdf_files),
        "cards": len(cards),
        "cards_with_pdf": len(cards) - len(cards_without_pdf),
        "cards_without_pdf": cards_without_pdf,
        "missing_card_pdfs": missing_card_pdfs,
        "orphan_pdfs": orphan_pdfs,
        "duplicate_style_filenames": duplicate_style,
        "duplicate_hashes": duplicate_hashes,
        "repeated_unmatched_files": _repeated_unmatched_files(unmatched_rows),
        "unmatched_entries": len(unmatched_rows),
        "historical_unmatched_entries": len(unmatched_rows),
        "hash_errors": hash_errors,
        "staging": staging_summary,
    }


def doctor_vault(
    vault: Path | str,
    *,
    staging_path: Path | str | None = None,
    topic_limit: int = 30,
) -> dict[str, Any]:
    paths = VaultPaths.from_root(vault)
    cards = load_source_cards(paths)
    for card in cards:
        refresh_metadata_completeness(card)
    runs = load_run_records(paths)
    manifests = load_import_manifests(paths)
    unmatched_rows = _unmatched_rows_from_manifests(manifests)
    cards_by_path = {_card_ref(card): card for card in cards}
    pdf_summary = pdf_doctor(vault, staging_path=staging_path)
    missing_candidates = [
        {
            "run_id": run.slug,
            "rank": result.rank,
            "title": result.title,
            "authors_preview": result.authors_preview,
            "year": result.year,
            "pdf_status": result.pdf_status,
            "status": result.status,
        }
        for run in runs
        for result in run.results
        if result.pdf_status != "attached" and not result.paper_card
    ]
    metadata_issues = {
        "ambiguous_citations": [
            _card_issue(card, issue="ambiguous citation")
            for card in cards
            if card.citation_status == "ambiguous" or card.doi_status == "ambiguous"
        ],
        "unresolved_citations": [
            _card_issue(card, issue="unresolved citation")
            for card in cards
            if card.citation_status == "unresolved" or card.doi_status == "unresolved"
        ],
        "incomplete_enrichment": [
            _card_issue(card, issue="incomplete metadata")
            for card in cards
            if card.enrichment_status == "incomplete"
        ],
        "missing_abstracts": [
            _card_issue(card, issue="missing abstract")
            for card in cards
            if card.abstract_status in {"missing", "ambiguous", "unresolved"}
        ],
        "missing_keywords": [
            _card_issue(card, issue="missing publication keywords")
            for card in cards
            if card.pdf and not card.keywords and card.publication_keywords_status != "absent"
        ],
    }
    metadata_notes = {
        "metadata_not_enriched": [
            _card_issue(card, issue="metadata not enriched")
            for card in cards
            if card.enrichment_status == "missing"
        ],
    }
    staging_summary = pdf_summary.get("staging") or {}
    return {
        "vault": str(paths.vault),
        "counts": {
            "paper_cards": len(cards),
            "runs": len(runs),
            "topic_pages": len(list(paths.topics.glob("*.md"))),
            "pdf_files": len(list(paths.pdfs.glob("*.pdf"))),
            "attached_pdf_cards": sum(1 for card in cards if _card_has_valid_pdf(paths, card)),
            "missing_pdf_cards": sum(1 for card in cards if not _card_has_valid_pdf(paths, card)),
            "missing_candidate_pdfs": len(missing_candidates),
            "candidate_results_without_cards": len(missing_candidates),
            "unmatched_entries": len(unmatched_rows),
            "historical_unmatched_entries": len(unmatched_rows),
            "active_staging_pdfs": staging_summary.get("pdf_count"),
            "active_staging_duplicates": staging_summary.get("duplicate_count"),
            "active_staging_actionable_pdfs": staging_summary.get("actionable_pdf_count"),
        },
        "status_counts": {
            "pdf_status": _status_counts(cards, "pdf_status"),
            "enrichment_status": _status_counts(cards, "enrichment_status"),
            "citation_status": _status_counts(cards, "citation_status"),
            "doi_status": _status_counts(cards, "doi_status"),
            "abstract_status": _status_counts(cards, "abstract_status"),
            "publication_keywords_status": _status_counts(
                cards,
                "publication_keywords_status",
            ),
        },
        "issue_counts": {
            key: len(value)
            for key, value in metadata_issues.items()
        },
        "diagnostic_counts": {
            key: len(value)
            for key, value in metadata_notes.items()
        },
        "metadata_issues": metadata_issues,
        "metadata_notes": metadata_notes,
        "runs": [
            _run_issue_summary(run, cards_by_path)
            for run in sorted(
                runs,
                key=lambda item: (_parse_datetime(item.exported_at), item.slug),
                reverse=True,
            )
        ],
        "missing_candidate_pdfs": missing_candidates,
        "candidate_results_without_cards": missing_candidates,
        "topics": _topic_report(cards, limit=topic_limit),
        "pdfs": pdf_summary,
    }


def topic_map_report(
    vault: Path | str,
    *,
    limit: int = 30,
) -> dict[str, Any]:
    paths = VaultPaths.from_root(vault)
    cards = load_source_cards(paths)
    return {"vault": str(paths.vault), **_topic_report(cards, limit=limit)}


def topic_preset_mapping(preset: str) -> dict[str, Any]:
    if preset == "prompt-boilerplate":
        return dict(PROMPT_BOILERPLATE_TOPIC_MAP)
    raise ValueError(f"Unknown topic cleanup preset: {preset}")


def _topic_replacements(value: Any) -> list[str]:
    if value is None or value is False:
        return []
    if isinstance(value, list):
        values = value
    else:
        values = [value]
    cleaned = [clean_markdown_text(str(item)) for item in values]
    return [item for item in cleaned if item]


def apply_topic_map(
    vault: Path | str,
    mapping: dict[str, Any],
    *,
    apply: bool = False,
) -> dict[str, Any]:
    paths = VaultPaths.from_root(vault)
    cards = load_source_cards(paths)
    normalized_mapping = {
        normalize_title(str(source)): _topic_replacements(target)
        for source, target in mapping.items()
        if normalize_title(str(source))
    }
    changed_cards: list[dict[str, Any]] = []
    removed_counter: Counter[str] = Counter()
    added_counter: Counter[str] = Counter()
    for card in cards:
        old_topics = list(card.topics)
        new_topics: list[str] = []
        seen: set[str] = set()
        for topic in old_topics:
            key = normalize_title(topic)
            replacements = normalized_mapping.get(key)
            if replacements is None:
                replacements = [topic]
            else:
                removed_counter[topic] += 1
            for replacement in replacements:
                replacement_key = replacement.casefold()
                if replacement_key in seen:
                    continue
                seen.add(replacement_key)
                new_topics.append(replacement)
                if replacement != topic:
                    added_counter[replacement] += 1
        if new_topics != old_topics:
            changed_cards.append(
                {
                    "citekey": _card_id(card),
                    "paper": _card_ref(card),
                    "title": card.title,
                    "before": old_topics,
                    "after": new_topics,
                }
            )
            if apply:
                card.topics = new_topics
                _save_card(paths, card)
    rebuild_summary = _rebuild_indexes(paths) if apply and changed_cards else None
    return {
        "vault": str(paths.vault),
        "applied": apply,
        "mapping": {
            source: _topic_replacements(target)
            for source, target in mapping.items()
        },
        "changed_cards": len(changed_cards),
        "changes": changed_cards,
        "removed_topics": dict(sorted(removed_counter.items())),
        "added_topics": dict(sorted(added_counter.items())),
        "rebuild": rebuild_summary,
    }


MARKDOWN_LINK_RE = re.compile(r"\[[^\]]+\]\((<?[^)>\n]+(?:\.md|/)?>?)\)")
PAPER_PATH_RE = re.compile(r"papers/[^)\]>\s]+\.md")
PDF_READING_NOTES_RE = re.compile(r"^###\s+PDF reading notes\b", re.IGNORECASE | re.MULTILINE)
VAULT_NOTE_ROOTS = {
    "concepts",
    "papers",
    "projects",
    "proposals",
    "runs",
    "syntheses",
    "tasks",
}
PROPOSAL_ROLE_RE = re.compile(
    r"Proposal role\s*:\s*(Core|Supporting|Discarded)\b",
    re.IGNORECASE,
)
ROLE_CELL_RE = re.compile(r"\|\s*(Core|Supporting|Discarded)\s*\|", re.IGNORECASE)
ORIGINAL_NOTES_RE = re.compile(
    r"^#+\s+Original User Notes - Verbatim\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def _markdown_heading_re(heading: str) -> re.Pattern[str]:
    cleaned = re.sub(r"^#+\s*", "", heading or "").strip()
    if not cleaned:
        raise ValueError("Heading must not be empty.")
    return re.compile(
        rf"^#{{1,6}}\s+{re.escape(cleaned)}(?:$|[\s:—–-].*)",
        re.IGNORECASE | re.MULTILINE,
    )


def notes_missing(vault: Path | str, *, heading: str = "PDF reading notes") -> dict[str, Any]:
    paths = VaultPaths.from_root(vault)
    cards = load_source_cards(paths)
    heading_re = _markdown_heading_re(heading)
    eligible_cards = [
        card
        for card in cards
        if card.status == "active" and (card.pdf_status == "attached" or bool(card.pdf))
    ]
    rows = []
    for card in eligible_cards:
        pdf_path = (paths.vault / card.pdf).resolve() if card.pdf else None
        row = {
            "paper": _card_ref(card),
            "citekey": card.citekey,
            "title": card.title,
            "year": card.year,
            "pdf": card.pdf,
            "pdf_exists": bool(pdf_path and pdf_path.exists()),
        }
        if not heading_re.search(card.notes or ""):
            rows.append(row)
    return {
        "vault": str(paths.vault),
        "heading": re.sub(r"^#+\s*", "", heading or "").strip(),
        "eligible_cards": len(eligible_cards),
        "present": len(eligible_cards) - len(rows),
        "missing": len(rows),
        "missing_cards": rows,
        "ok": not rows,
    }


def _metadata_issue_count(summary: dict[str, Any]) -> int:
    issue_counts = summary.get("issue_counts") or {}
    return sum(int(value or 0) for value in issue_counts.values())


def _report_table(headers: list[str], rows: list[list[object]], *, empty: str) -> list[str]:
    return _markdown_table(headers, rows, empty=empty)


def _render_maintenance_report(
    *,
    report_date: str,
    status_summary: dict[str, Any],
    pdf_summary: dict[str, Any],
    notes_summary: dict[str, Any],
    artifacts: dict[str, list[dict[str, Any]]],
    topic_cards: dict[str, list[SourceCard]],
) -> str:
    counts = status_summary.get("counts") or {}
    topics = status_summary.get("topics") or {}
    staging = pdf_summary.get("staging")
    concepts = artifacts.get("concepts") or []
    syntheses = artifacts.get("syntheses") or []
    tasks = artifacts.get("tasks") or []
    concept_needs = _artifacts_without_sources(concepts)
    synthesis_needs = _artifacts_without_sources(syntheses)
    opportunities = _topic_opportunities(topic_cards, syntheses)
    metadata_issues = status_summary.get("metadata_issues") or {}
    lines = [
        f"# Maintenance Report - {report_date}",
        "",
        "Generated triage report. It writes this report and a task note only; it does not "
        "modify paper cards, PDFs, run records, metadata, topics, or provenance.",
        "",
        "Scholar Labs candidate results without canonical paper cards are discovery context, "
        "not defects in the selected-only workflow.",
        "",
        "## Status / Doctor Summary",
        "",
        *_report_table(
            ["Metric", "Count"],
            [
                ["Paper cards", counts.get("paper_cards", 0)],
                ["Runs", counts.get("runs", 0)],
                ["PDF files", counts.get("pdf_files", 0)],
                ["Attached PDF cards", counts.get("attached_pdf_cards", 0)],
                ["Missing PDF cards", counts.get("missing_pdf_cards", 0)],
                [
                    "Candidate results without cards",
                    counts.get("candidate_results_without_cards", 0),
                ],
                ["Historical unmatched entries", counts.get("historical_unmatched_entries", 0)],
                ["Active staging PDFs", counts.get("active_staging_pdfs") or 0],
                [
                    "Active staging actionable PDFs",
                    counts.get("active_staging_actionable_pdfs") or 0,
                ],
            ],
            empty="No status rows.",
        ),
        "",
        "## PDF Doctor Summary",
        "",
        *_report_table(
            ["Issue", "Count"],
            [
                ["Cards without PDF field", len(pdf_summary.get("cards_without_pdf") or [])],
                ["Missing card PDF files", len(pdf_summary.get("missing_card_pdfs") or [])],
                ["Orphan PDFs", len(pdf_summary.get("orphan_pdfs") or [])],
                [
                    "Duplicate-style filenames",
                    len(pdf_summary.get("duplicate_style_filenames") or []),
                ],
                ["Duplicate PDF hashes", len(pdf_summary.get("duplicate_hashes") or [])],
                [
                    "Repeated unmatched files",
                    len(pdf_summary.get("repeated_unmatched_files") or []),
                ],
            ],
            empty="No PDF issue rows.",
        ),
        "",
        "## Reading Queue",
        "",
        f"- Eligible attached cards: {notes_summary.get('eligible_cards', 0)}",
        f"- Missing `{notes_summary.get('heading')}`: {notes_summary.get('missing', 0)}",
        "",
        *_report_table(
            ["Paper", "Citekey", "PDF"],
            [
                [
                    f"[{row['title']}](../{row['paper']})",
                    row.get("citekey") or "",
                    row.get("pdf") or "",
                ]
                for row in notes_summary.get("missing_cards", [])[:50]
            ],
            empty="No selected attached papers are missing PDF reading notes.",
        ),
        "",
        "## Enrichment Issues",
        "",
        *_report_table(
            ["Issue class", "Count"],
            [
                [key.replace("_", " "), len(rows)]
                for key, rows in sorted(metadata_issues.items())
            ],
            empty="No enrichment issue rows.",
        ),
        "",
        "## Candidate Discovery Backlog",
        "",
        "These rows are optional discovery context unless you choose to fetch/import PDFs.",
        "",
        *_report_table(
            ["Run", "Rank", "Title", "Status"],
            [
                [
                    row.get("run_id"),
                    row.get("rank"),
                    row.get("title"),
                    row.get("status"),
                ]
                for row in status_summary.get("candidate_results_without_cards", [])[:50]
            ],
            empty="No candidate-only Scholar Labs results found.",
        ),
        "",
        "## Historical Unmatched Records",
        "",
        f"- Historical unmatched entries: {pdf_summary.get('historical_unmatched_entries', 0)}",
        "",
        *_report_table(
            ["Filename", "Count", "Runs", "Best score"],
            [
                [row["filename"], row["count"], ", ".join(row["runs"]), row["best_score"]]
                for row in pdf_summary.get("repeated_unmatched_files", [])
            ],
            empty="No repeated historical unmatched records.",
        ),
        "",
        "## Active Staging Issues",
        "",
    ]
    if staging:
        lines.extend(
            [
                f"- Staging folder: {staging.get('path')}",
                f"- PDFs in staging: {staging.get('pdf_count', 0)}",
                f"- Already duplicated in vault: {staging.get('duplicate_count', 0)}",
                f"- Actionable non-duplicate PDFs: {staging.get('actionable_pdf_count', 0)}",
                "",
            ]
        )
    else:
        lines.extend(
            [
                "No staging folder was provided or configured for this report.",
                "",
            ]
        )
    lines.extend(
        [
            "## Topic Noise",
            "",
            *_report_table(
                ["Topic", "Count"],
                [[row["topic"], row["count"]] for row in topics.get("noisy", [])],
                empty="No prompt-boilerplate topic labels detected.",
            ),
            "",
            "## Concepts, Syntheses, And Tasks",
            "",
            *_report_table(
                ["Artifact type", "Count", "Needs source links"],
                [
                    ["Concepts", len(concepts), len(concept_needs)],
                    ["Syntheses", len(syntheses), len(synthesis_needs)],
                    ["Tasks", len(tasks), ""],
                ],
                empty="No research artifacts found.",
            ),
            "",
            "## Missing Synthesis Opportunities",
            "",
            *_report_table(
                ["Topic", "Papers", "Example papers"],
                [
                    [row["topic"], row["papers"], row["example_papers"]]
                    for row in opportunities
                ],
                empty="No multi-paper topic opportunities detected.",
            ),
            "",
        ]
    )
    lines.extend(
        _render_command_block(
            [
                "scholar-vault status --vault /path/to/vault --json",
                "scholar-vault pdf-doctor --vault /path/to/vault --json",
                'scholar-vault notes-missing --vault /path/to/vault --heading "PDF reading notes"',
                "scholar-vault enrich --vault /path/to/vault --ui",
                "scholar-vault topic-map --vault /path/to/vault --preset prompt-boilerplate",
                (
                    "scholar-vault topic-map --vault /path/to/vault "
                    "--preset prompt-boilerplate --apply"
                ),
                "scholar-vault rebuild --vault /path/to/vault",
            ]
        )
    )
    return "\n".join(lines)


def _render_maintenance_task(
    *,
    report_date: str,
    report_path: str,
    status_summary: dict[str, Any],
    notes_summary: dict[str, Any],
) -> str:
    counts = status_summary.get("counts") or {}
    issue_total = _metadata_issue_count(status_summary)
    lines = [
        f"# {report_date} maintenance",
        "",
        f"Report: [{report_path}](../{report_path})",
        "",
        "## Checklist",
        "",
        f"- [ ] Review reading queue ({notes_summary.get('missing', 0)} papers).",
        f"- [ ] Resolve enrichment issues ({issue_total} issue rows).",
        f"- [ ] Check active staging PDFs ({counts.get('active_staging_actionable_pdfs') or 0}).",
        "- [ ] Run topic cleanup dry-run before applying prompt-boilerplate changes.",
        "- [ ] Add/update concepts or syntheses only after reading PDFs as evidence.",
        "",
        "## Commands",
        "",
        "```fish",
        "scholar-vault maintenance-report --vault /path/to/vault",
        "scholar-vault enrich --vault /path/to/vault --ui",
        "scholar-vault rebuild --vault /path/to/vault",
        "```",
        "",
    ]
    return "\n".join(lines)


def maintenance_report(
    vault: Path | str,
    *,
    staging_path: Path | str | None = None,
    report_date: str | None = None,
) -> dict[str, Any]:
    paths = VaultPaths.from_root(vault)
    paths.indexes.mkdir(parents=True, exist_ok=True)
    paths.tasks.mkdir(parents=True, exist_ok=True)
    current_date = report_date or datetime.now().astimezone().date().isoformat()
    status_summary = doctor_vault(paths.vault, staging_path=staging_path)
    pdf_summary = status_summary.get("pdfs") or pdf_doctor(paths.vault, staging_path=staging_path)
    notes_summary = notes_missing(paths.vault, heading="PDF reading notes")
    cards = load_source_cards(paths)
    topic_cards = group_cards_by_topic(cards)
    artifacts = _collect_research_artifacts(paths)
    report_path = paths.indexes / "maintenance-report.md"
    task_path = paths.tasks / f"{current_date}-maintenance.md"
    write_text(
        report_path,
        _render_maintenance_report(
            report_date=current_date,
            status_summary=status_summary,
            pdf_summary=pdf_summary,
            notes_summary=notes_summary,
            artifacts=artifacts,
            topic_cards=topic_cards,
        ),
    )
    write_text(
        task_path,
        _render_maintenance_task(
            report_date=current_date,
            report_path=ensure_relative(report_path, paths.vault),
            status_summary=status_summary,
            notes_summary=notes_summary,
        ),
    )
    topics = status_summary.get("topics") or {}
    return {
        "vault": str(paths.vault),
        "date": current_date,
        "report": ensure_relative(report_path, paths.vault),
        "task": ensure_relative(task_path, paths.vault),
        "paper_cards_modified": 0,
        "counts": {
            "reading_queue": notes_summary.get("missing", 0),
            "metadata_issue_rows": _metadata_issue_count(status_summary),
            "candidate_results_without_cards": len(
                status_summary.get("candidate_results_without_cards", [])
            ),
            "historical_unmatched_entries": pdf_summary.get("historical_unmatched_entries", 0),
            "active_staging_actionable_pdfs": (
                (pdf_summary.get("staging") or {}).get("actionable_pdf_count") or 0
            ),
            "noisy_topics": len(topics.get("noisy", [])),
            "concepts_without_sources": len(
                _artifacts_without_sources(artifacts.get("concepts") or [])
            ),
            "syntheses_without_sources": len(
                _artifacts_without_sources(artifacts.get("syntheses") or [])
            ),
        },
    }


PROJECT_LIST_FIELDS = (
    "related_papers",
    "related_runs",
    "related_concepts",
    "related_syntheses",
    "related_tasks",
    "related_proposals",
    "outputs",
)


def _project_slug(slug: str) -> str:
    raw = (slug or "").strip().strip("/")
    if raw.startswith("projects/"):
        raw = raw.removeprefix("projects/").strip("/")
    if raw.endswith("/index.md"):
        raw = raw[: -len("/index.md")]
    path = Path(raw)
    if (
        not raw
        or path.is_absolute()
        or len(path.parts) != 1
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError("Project slug must be a single safe path segment.")
    return slugify_text(raw, max_length=80)


def _project_title(slug: str, title: str | None) -> str:
    cleaned = (title or "").strip()
    if cleaned:
        return cleaned
    return slug.replace("-", " ").replace("_", " ").title()


def _project_index_path(paths: VaultPaths, slug: str) -> Path:
    return paths.projects / slug / "index.md"


def _project_map_path(paths: VaultPaths, slug: str) -> Path:
    return paths.projects / slug / "project-map.md"


def _project_defaults(slug: str, title: str | None = None) -> dict[str, Any]:
    now = _now_iso()
    project = {
        "type": "project",
        "title": _project_title(slug, title),
        "slug": slug,
        "status": "active",
        "created": now,
        "updated": now,
    }
    for field in PROJECT_LIST_FIELDS:
        project[field] = []
    return project


def _normalize_project_frontmatter(frontmatter: dict[str, Any], slug: str) -> dict[str, Any]:
    project = _project_defaults(slug, str(frontmatter.get("title") or ""))
    project.update(frontmatter)
    project["type"] = "project"
    project["slug"] = slug
    project["title"] = str(project.get("title") or _project_title(slug, None))
    project["status"] = str(project.get("status") or "active")
    project["created"] = str(project.get("created") or _now_iso())
    project["updated"] = str(project.get("updated") or project["created"])
    for field in PROJECT_LIST_FIELDS:
        project[field] = _as_string_list(project.get(field))
    return project


def _load_project(paths: VaultPaths, slug: str) -> tuple[dict[str, Any], Path, str]:
    normalized_slug = _project_slug(slug)
    project_path = _project_index_path(paths, normalized_slug)
    if not project_path.exists():
        raise ValueError(f"Project does not exist: projects/{normalized_slug}")
    frontmatter, body = read_frontmatter_markdown(project_path)
    project = _normalize_project_frontmatter(frontmatter, normalized_slug)
    return project, project_path, body


def _write_project_preserving_body(path: Path, project: dict[str, Any], body: str) -> None:
    write_text(path, f"---\n{dump_frontmatter(project).strip()}\n---\n\n{body.strip()}\n")


def _project_list(paths: VaultPaths) -> list[dict[str, Any]]:
    if not paths.projects.exists():
        return []
    rows: list[dict[str, Any]] = []
    for project_path in sorted(paths.projects.glob("*/index.md")):
        frontmatter, _ = read_frontmatter_markdown(project_path)
        slug = project_path.parent.name
        project = _normalize_project_frontmatter(frontmatter, slug)
        rows.append(
            {
                "slug": slug,
                "title": project["title"],
                "status": project["status"],
                "path": ensure_relative(project_path, paths.vault),
                "project_map": (
                    ensure_relative(_project_map_path(paths, slug), paths.vault)
                    if _project_map_path(paths, slug).exists()
                    else None
                ),
                "related_papers": len(project.get("related_papers") or []),
                "related_concepts": len(project.get("related_concepts") or []),
                "related_syntheses": len(project.get("related_syntheses") or []),
                "related_tasks": len(project.get("related_tasks") or []),
                "related_runs": len(project.get("related_runs") or []),
            }
        )
    return rows


def project_list(vault: Path | str) -> dict[str, Any]:
    paths = initialize_vault(vault, rebuild=False)
    projects = _project_list(paths)
    return {"vault": str(paths.vault), "count": len(projects), "projects": projects}


def project_scaffold(
    vault: Path | str,
    slug: str,
    *,
    title: str | None = None,
) -> dict[str, Any]:
    paths = initialize_vault(vault, rebuild=False)
    normalized_slug = _project_slug(slug)
    project_dir = paths.projects / normalized_slug
    project_dir.mkdir(parents=True, exist_ok=True)
    project_path = _project_index_path(paths, normalized_slug)
    state = "unchanged"
    if not project_path.exists():
        project = _project_defaults(normalized_slug, title)
        write_text(project_path, render_project_markdown(project))
        state = "created"
    else:
        frontmatter, body = read_frontmatter_markdown(project_path)
        project = _normalize_project_frontmatter(frontmatter, normalized_slug)
        if title and project.get("title") != title:
            project["title"] = title
            project["updated"] = _now_iso()
            _write_project_preserving_body(project_path, project, body)
            state = "updated"
    rebuild_summary = _rebuild_indexes(paths)
    return {
        "vault": str(paths.vault),
        "project": ensure_relative(project_path, paths.vault),
        "slug": normalized_slug,
        "title": _project_title(normalized_slug, title),
        "state": state,
        "rebuild": rebuild_summary,
    }


def _resolve_project_paper_ref(paths: VaultPaths, citekey: str) -> str:
    cards = load_source_cards(paths)
    for card in cards:
        if citekey in {card.citekey, card.slug, f"papers/{card.slug}.md"}:
            return _card_ref(card)
    raise ValueError(f"No paper card found for citekey or slug: {citekey}")


def _normalize_artifact_ref(
    paths: VaultPaths,
    folder: str,
    value: str,
    *,
    require_exists: bool = True,
) -> str:
    raw = (value or "").strip().strip("/")
    if raw.startswith(f"{folder}/"):
        raw = raw.removeprefix(f"{folder}/")
    candidate = Path(raw)
    if (
        not raw
        or candidate.is_absolute()
        or any(part in {"", ".", ".."} for part in candidate.parts)
    ):
        raise ValueError(f"{folder[:-1].title()} reference must stay inside {folder}/.")
    if candidate.suffix != ".md":
        candidate = candidate.with_suffix(".md")
    path = paths.vault / folder / candidate
    if require_exists and not path.exists():
        raise ValueError(f"Linked {folder[:-1]} does not exist: {folder}/{candidate}")
    return ensure_relative(path, paths.vault)


def _resolve_project_run_ref(paths: VaultPaths, run_id: str) -> str:
    normalized = (run_id or "").strip().strip("/")
    for run in load_run_records(paths):
        if run.slug == normalized:
            return run.slug
    raise ValueError(f"No run found for run id: {run_id}")


def _resolve_project_task_ref(paths: VaultPaths, task_path: str) -> str:
    return _normalize_artifact_ref(paths, "tasks", task_path)


def _append_project_section_item(body: str, heading: str, bullet: str) -> str:
    if bullet in body:
        return body
    pattern = re.compile(rf"(^##\s+{re.escape(heading)}\s*$)", re.MULTILINE)
    match = pattern.search(body)
    if not match:
        return body.rstrip() + f"\n\n## {heading}\n{bullet}\n"
    next_match = re.search(r"^##\s+", body[match.end() :], flags=re.MULTILINE)
    section_end = len(body) if next_match is None else match.end() + next_match.start()
    before = body[: match.end()]
    section = body[match.end() : section_end]
    after = body[section_end:]
    kept_lines = [
        line
        for line in section.strip().splitlines()
        if not line.strip().casefold().startswith("- no linked")
    ]
    kept_lines.append(bullet)
    replacement = before + "\n" + "\n".join(kept_lines).strip() + "\n"
    return replacement + after


def _update_project_link(
    vault: Path | str,
    slug: str,
    *,
    field: str,
    ref: str,
    section: str | None = None,
    bullet: str | None = None,
) -> dict[str, Any]:
    paths = initialize_vault(vault, rebuild=False)
    project, project_path, body = _load_project(paths, slug)
    values = list(project.get(field) or [])
    changed = False
    if ref not in values:
        values.append(ref)
        project[field] = sorted(values, key=str.casefold)
        project["updated"] = _now_iso()
        changed = True
    if changed and section and bullet:
        body = _append_project_section_item(body, section, bullet)
    if changed:
        _write_project_preserving_body(project_path, project, body)
        rebuild_summary = _rebuild_indexes(paths)
    else:
        rebuild_summary = None
    return {
        "vault": str(paths.vault),
        "project": ensure_relative(project_path, paths.vault),
        "field": field,
        "ref": ref,
        "changed": changed,
        "rebuild": rebuild_summary,
    }


def project_link_paper(vault: Path | str, slug: str, citekey: str) -> dict[str, Any]:
    paths = initialize_vault(vault, rebuild=False)
    ref = _resolve_project_paper_ref(paths, citekey)
    return _update_project_link(
        paths.vault,
        slug,
        field="related_papers",
        ref=ref,
        section="Linked sources",
        bullet=f"- [{ref}](../../{ref})",
    )


def project_link_concept(vault: Path | str, slug: str, concept_slug: str) -> dict[str, Any]:
    paths = initialize_vault(vault, rebuild=False)
    ref = _normalize_artifact_ref(paths, "concepts", concept_slug)
    return _update_project_link(
        paths.vault,
        slug,
        field="related_concepts",
        ref=ref,
        section="Linked concepts",
        bullet=f"- [{ref}](../../{ref})",
    )


def project_link_synthesis(
    vault: Path | str,
    slug: str,
    synthesis_slug: str,
) -> dict[str, Any]:
    paths = initialize_vault(vault, rebuild=False)
    ref = _normalize_artifact_ref(paths, "syntheses", synthesis_slug)
    return _update_project_link(
        paths.vault,
        slug,
        field="related_syntheses",
        ref=ref,
        section="Linked syntheses",
        bullet=f"- [{ref}](../../{ref})",
    )


def project_link_run(vault: Path | str, slug: str, run_id: str) -> dict[str, Any]:
    paths = initialize_vault(vault, rebuild=False)
    ref = _resolve_project_run_ref(paths, run_id)
    return _update_project_link(
        paths.vault,
        slug,
        field="related_runs",
        ref=ref,
        section="Linked sources",
        bullet=f"- Run: `{ref}`",
    )


def project_link_task(vault: Path | str, slug: str, task_path: str) -> dict[str, Any]:
    paths = initialize_vault(vault, rebuild=False)
    ref = _resolve_project_task_ref(paths, task_path)
    return _update_project_link(
        paths.vault,
        slug,
        field="related_tasks",
        ref=ref,
        section="Open questions and tasks",
        bullet=f"- [{ref}](../../{ref})",
    )


def _card_by_ref(cards: list[SourceCard], ref: str) -> SourceCard | None:
    normalized = ref.strip()
    stem = Path(normalized).stem
    for card in cards:
        if normalized in {_card_ref(card), card.slug, card.citekey or ""} or stem == card.slug:
            return card
    return None


def _artifact_row(paths: VaultPaths, ref: str) -> dict[str, Any]:
    path = paths.vault / ref
    if not path.exists():
        return {"path": ref, "title": ref, "exists": False}
    frontmatter, body = read_frontmatter_markdown(path)
    return {
        "path": ensure_relative(path, paths.vault),
        "title": _artifact_title(path, frontmatter, body),
        "exists": True,
    }


def _run_row(paths: VaultPaths, run_id: str, runs: list[RunRecord]) -> dict[str, Any]:
    for run in runs:
        if run.slug == run_id:
            return {
                "id": run.slug,
                "title": run_display_title(run.title, run.prompt),
                "path": _run_ref(run),
                "exists": True,
            }
    return {"id": run_id, "title": run_id, "path": None, "exists": False}


def _project_map_data(paths: VaultPaths, project: dict[str, Any]) -> dict[str, Any]:
    cards = load_source_cards(paths)
    runs = load_run_records(paths)
    gaps: list[str] = []
    actions: list[str] = []
    paper_rows: list[dict[str, Any]] = []
    for ref in project.get("related_papers") or []:
        card = _card_by_ref(cards, ref)
        if card is None:
            paper_rows.append(
                {
                    "path": ref,
                    "title": ref,
                    "citekey": "",
                    "pdf_status": "missing card",
                    "metadata_status": "missing card",
                    "read_notes_status": "-",
                }
            )
            gaps.append(f"Linked paper does not resolve: {ref}")
            continue
        pdf_exists = _card_has_valid_pdf(paths, card)
        has_notes = bool(PDF_READING_NOTES_RE.search(card.notes or ""))
        if not card.pdf or not pdf_exists:
            gaps.append(f"Linked paper needs a PDF: {_card_id(card)}")
        elif not has_notes:
            gaps.append(f"Linked paper needs PDF reading notes: {_card_id(card)}")
        if card.enrichment_status in {"missing", "incomplete", "ambiguous", "unresolved"}:
            gaps.append(
                f"Linked paper has metadata status `{card.enrichment_status}`: {_card_id(card)}"
            )
        paper_rows.append(
            {
                "path": _card_ref(card),
                "title": card.title,
                "citekey": _card_id(card),
                "pdf_status": "attached" if card.pdf and pdf_exists else "missing",
                "metadata_status": card.enrichment_status,
                "read_notes_status": "present" if has_notes else "missing",
            }
        )
    concept_rows = [
        _artifact_row(paths, ref) for ref in project.get("related_concepts") or []
    ]
    synthesis_rows = [
        _artifact_row(paths, ref) for ref in project.get("related_syntheses") or []
    ]
    task_rows = [_artifact_row(paths, ref) for ref in project.get("related_tasks") or []]
    run_rows = [_run_row(paths, ref, runs) for ref in project.get("related_runs") or []]
    for label, rows in [
        ("concept", concept_rows),
        ("synthesis", synthesis_rows),
        ("task", task_rows),
        ("run", run_rows),
    ]:
        for row in rows:
            if not row.get("exists"):
                gaps.append(f"Linked {label} does not resolve: {row.get('path') or row.get('id')}")
    if not paper_rows:
        actions.append("Link project source papers with `scholar-vault project link-paper`.")
    if any("needs a PDF" in gap for gap in gaps):
        actions.append("Attach PDFs for linked papers before using them as evidence.")
    if any("PDF reading notes" in gap for gap in gaps):
        actions.append("Read linked PDFs and add `### PDF reading notes` to paper cards.")
    if any("metadata status" in gap for gap in gaps):
        actions.append("Run `scholar-vault enrich --ui` for linked paper metadata issues.")
    actions.append(f"Run `scholar-vault project audit {project['slug']}` after link changes.")
    return {
        "project": f"projects/{project['slug']}/index.md",
        "generated": _now_iso(),
        "papers": paper_rows,
        "concepts": concept_rows,
        "syntheses": synthesis_rows,
        "tasks": task_rows,
        "runs": run_rows,
        "gaps": sorted(set(gaps), key=str.casefold),
        "recommended_next_actions": actions,
    }


def project_map(vault: Path | str, slug: str) -> dict[str, Any]:
    paths = initialize_vault(vault, rebuild=False)
    project, project_path, _ = _load_project(paths, slug)
    map_data = _project_map_data(paths, project)
    map_path = _project_map_path(paths, project["slug"])
    write_text(map_path, render_project_map_markdown(project, map_data))
    return {
        "vault": str(paths.vault),
        "project": ensure_relative(project_path, paths.vault),
        "project_map": ensure_relative(map_path, paths.vault),
        "linked_papers": len(map_data["papers"]),
        "gaps": len(map_data["gaps"]),
        "recommended_next_actions": len(map_data["recommended_next_actions"]),
    }


def _project_issue(message: str, **extra: Any) -> dict[str, Any]:
    issue = {"message": message}
    issue.update(extra)
    return issue


def _project_broken_links(paths: VaultPaths, project_dir: Path) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for path in _markdown_files(project_dir):
        text = path.read_text(encoding="utf-8")
        for target in _extract_markdown_targets(text):
            resolved = _resolve_markdown_target(paths, path, target)
            if not resolved.exists():
                issues.append(
                    _project_issue(
                        "Markdown link does not resolve",
                        file=_display_path(path, paths.vault),
                        target=target,
                    )
                )
    return issues


def project_audit(vault: Path | str, slug: str) -> dict[str, Any]:
    paths = initialize_vault(vault, rebuild=False)
    project, project_path, _ = _load_project(paths, slug)
    cards = load_source_cards(paths)
    issues: dict[str, list[dict[str, Any]]] = {
        "missing_linked_papers": [],
        "linked_papers_without_pdfs": [],
        "linked_papers_without_pdf_reading_notes": [],
        "missing_linked_concepts": [],
        "missing_linked_syntheses": [],
        "missing_linked_tasks": [],
        "missing_linked_runs": [],
        "broken_links": [],
        "stale_project_map": [],
    }
    for ref in project.get("related_papers") or []:
        card = _card_by_ref(cards, ref)
        if card is None:
            issues["missing_linked_papers"].append(
                _project_issue("Linked paper card does not exist", paper=ref)
            )
            continue
        if not card.pdf or not _card_has_valid_pdf(paths, card):
            issues["linked_papers_without_pdfs"].append(
                _project_issue("Linked paper has no existing PDF", paper=_card_ref(card))
            )
        elif not PDF_READING_NOTES_RE.search(card.notes or ""):
            issues["linked_papers_without_pdf_reading_notes"].append(
                _project_issue("Linked paper lacks PDF reading notes", paper=_card_ref(card))
            )
    for field, key in [
        ("related_concepts", "missing_linked_concepts"),
        ("related_syntheses", "missing_linked_syntheses"),
        ("related_tasks", "missing_linked_tasks"),
    ]:
        for ref in project.get(field) or []:
            if not (paths.vault / ref).exists():
                issues[key].append(_project_issue("Linked file does not exist", target=ref))
    run_ids = {run.slug for run in load_run_records(paths)}
    for run_id in project.get("related_runs") or []:
        if run_id not in run_ids:
            issues["missing_linked_runs"].append(
                _project_issue("Linked run does not exist", run=run_id)
            )
    issues["broken_links"] = _project_broken_links(paths, project_path.parent)
    map_path = _project_map_path(paths, project["slug"])
    if not map_path.exists():
        issues["stale_project_map"].append(
            _project_issue("Project map is missing", target=ensure_relative(map_path, paths.vault))
        )
    else:
        map_frontmatter, _ = read_frontmatter_markdown(map_path)
        if map_frontmatter.get("project_updated") != project.get("updated"):
            issues["stale_project_map"].append(
                _project_issue(
                    "Project map was generated from an older project revision",
                    target=ensure_relative(map_path, paths.vault),
                )
            )
    issue_counts = {key: len(rows) for key, rows in issues.items()}
    return {
        "vault": str(paths.vault),
        "project": ensure_relative(project_path, paths.vault),
        "ok": not any(issue_counts.values()),
        "counts": {
            "linked_papers": len(project.get("related_papers") or []),
            "linked_concepts": len(project.get("related_concepts") or []),
            "linked_syntheses": len(project.get("related_syntheses") or []),
            "linked_tasks": len(project.get("related_tasks") or []),
            "linked_runs": len(project.get("related_runs") or []),
        },
        "issue_counts": issue_counts,
        "issues": issues,
    }


def _resolve_proposal_path(paths: VaultPaths, proposal: Path | str) -> Path:
    proposal_path = Path(proposal).expanduser()
    if not proposal_path.is_absolute():
        proposal_path = paths.vault / proposal_path
    return proposal_path.resolve()


def _markdown_files(root: Path) -> list[Path]:
    if root.is_file() and root.suffix.casefold() == ".md":
        return [root]
    if not root.exists():
        return []
    return [
        path
        for path in sorted(root.rglob("*.md"))
        if not any(part.startswith(".") for part in path.relative_to(root).parts)
    ]


def _extract_markdown_targets(text: str) -> list[str]:
    targets: list[str] = []
    for match in MARKDOWN_LINK_RE.finditer(text):
        target = match.group(1).strip("<>")
        if "://" in target or target.startswith("#"):
            continue
        targets.append(urllib.parse.unquote(target.split("#", 1)[0]))
    return [target for target in targets if target]


def _extract_paper_refs(text: str) -> list[str]:
    refs = set(PAPER_PATH_RE.findall(text))
    for target in _extract_markdown_targets(text):
        if "papers/" in target and target.endswith(".md"):
            refs.add(target[target.index("papers/") :])
    return sorted(refs)


def _resolve_markdown_target(paths: VaultPaths, source: Path, target: str) -> Path:
    if "papers/" in target:
        return (paths.vault / target[target.index("papers/") :]).resolve()
    target_path = Path(target)
    if target_path.is_absolute():
        return target_path.resolve()
    if target_path.parts and target_path.parts[0] in VAULT_NOTE_ROOTS:
        return (paths.vault / target_path).resolve()
    return (source.parent / target_path).resolve()


def _evidence_matrix_targets(path: Path) -> list[str]:
    frontmatter, _ = read_frontmatter_markdown(path)
    targets = _as_string_list(frontmatter.get("evidence_matrix"))
    targets.extend(_as_string_list(frontmatter.get("evidence_matrices")))
    return targets


def _collect_declared_evidence_matrices(
    paths: VaultPaths,
    outline_files: list[Path],
) -> tuple[list[Path], list[dict[str, Any]]]:
    matrices: list[Path] = []
    issues: list[dict[str, Any]] = []
    seen: set[Path] = set()
    for outline_file in outline_files:
        for target in _evidence_matrix_targets(outline_file):
            resolved = _resolve_markdown_target(paths, outline_file, target)
            if resolved.exists() and resolved.suffix.casefold() == ".md":
                if resolved not in seen:
                    matrices.append(resolved)
                    seen.add(resolved)
                continue
            issues.append(
                _proposal_issue(
                    outline_file,
                    paths.vault,
                    "evidence_matrix link does not resolve",
                    target=target,
                )
            )
    return matrices, issues


def _line_for_ref(text: str, ref: str) -> str:
    slug = Path(ref).stem
    for line in text.splitlines():
        if ref in line or slug in line:
            return line
    return ""


def _line_has_proposal_role(line: str) -> bool:
    return bool(PROPOSAL_ROLE_RE.search(line) or ROLE_CELL_RE.search(line))


def _proposal_issue(file: Path, root: Path, message: str, **extra: Any) -> dict[str, Any]:
    issue = {
        "file": _display_path(file, root),
        "message": message,
    }
    issue.update(extra)
    return issue


def _proposal_slug(slug: str) -> str:
    raw = (slug or "").strip().strip("/")
    if raw.startswith("proposals/"):
        raw = raw.removeprefix("proposals/").strip("/")
    path = Path(raw)
    if (
        not raw
        or path.is_absolute()
        or len(path.parts) != 1
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError("Proposal slug must be a single safe path segment.")
    return slugify_text(raw, max_length=80)


def _proposal_title(slug: str, title: str | None) -> str:
    cleaned = (title or "").strip()
    if cleaned:
        return cleaned
    return slug.replace("-", " ").replace("_", " ").title()


def _proposal_scaffold_texts(slug: str, title: str) -> dict[str, str]:
    today = datetime.now().astimezone().date().isoformat()
    title_yaml = json.dumps(title)
    slug_yaml = json.dumps(slug)
    proposal_yaml = json.dumps(f"proposals/{slug}")
    return {
        "index.md": dedent(
            f"""
            ---
            type: proposal
            title: {title_yaml}
            slug: {slug_yaml}
            created: {today}
            ---

            # {title}

            ## Workspace Links

            - [Outline](outline.md)
            - [Source matrix](source-matrix.md)
            - [Reading log](reading-log.md)
            - [Raw idea](raw-idea.md)

            ## Evidence Checks

            - `scholar-vault notes-missing --heading "PDF reading notes"`
            - `scholar-vault proposal-audit proposals/{slug}`
            """
        ).strip()
        + "\n",
        "outline.md": dedent(
            f"""
            ---
            type: proposal_outline
            title: {json.dumps(f"{title} Outline")}
            proposal: {proposal_yaml}
            evidence_matrix: source-matrix.md
            created: {today}
            ---

            # {title} Outline

            ## Workspace Links

            - [Source matrix](source-matrix.md)
            - [Reading log](reading-log.md)
            - [Raw idea](raw-idea.md)

            ## Core Claim

            ## Structure

            ## Evidence To Add
            """
        ).strip()
        + "\n",
        "source-matrix.md": dedent(
            f"""
            ---
            type: proposal_source_matrix
            title: {json.dumps(f"{title} Source Matrix")}
            proposal: {proposal_yaml}
            created: {today}
            ---

            # {title} Source Matrix

            | Source | Proposal role | PDF evidence | Used in | Notes |
            | --- | --- | --- | --- | --- |

            Proposal role values: Core, Supporting, Discarded.
            """
        ).strip()
        + "\n",
        "reading-log.md": dedent(
            f"""
            ---
            type: proposal_reading_log
            title: {json.dumps(f"{title} Reading Log")}
            proposal: {proposal_yaml}
            created: {today}
            ---

            # {title} Reading Log

            | Date | Paper | Status | PDF reading notes | Proposal role | Next action |
            | --- | --- | --- | --- | --- | --- |
            """
        ).strip()
        + "\n",
        "raw-idea.md": dedent(
            f"""
            ---
            type: proposal_raw_idea
            title: {json.dumps(f"{title} Raw Idea")}
            proposal: {proposal_yaml}
            created: {today}
            ---

            # {title} Raw Idea

            ## Original User Notes - Verbatim

            ## Working Interpretation
            """
        ).strip()
        + "\n",
    }


PROPOSAL_REQUIRED_SNIPPETS = {
    "index.md": [
        (
            "## Workspace Links",
            "## Workspace Links\n\n"
            "- [Outline](outline.md)\n"
            "- [Source matrix](source-matrix.md)\n"
            "- [Reading log](reading-log.md)\n"
            "- [Raw idea](raw-idea.md)",
        ),
        (
            "scholar-vault proposal-audit",
            "## Evidence Checks\n\n"
            '- `scholar-vault notes-missing --heading "PDF reading notes"`\n'
            "- `scholar-vault proposal-audit proposals/{slug}`",
        ),
    ],
    "outline.md": [
        (
            "## Workspace Links",
            "## Workspace Links\n\n"
            "- [Source matrix](source-matrix.md)\n"
            "- [Reading log](reading-log.md)\n"
            "- [Raw idea](raw-idea.md)",
        ),
        ("## Evidence To Add", "## Evidence To Add"),
    ],
    "source-matrix.md": [
        (
            "| Source | Proposal role | PDF evidence | Used in | Notes |",
            "| Source | Proposal role | PDF evidence | Used in | Notes |\n"
            "| --- | --- | --- | --- | --- |\n\n"
            "Proposal role values: Core, Supporting, Discarded.",
        )
    ],
    "reading-log.md": [
        (
            "| Date | Paper | Status | PDF reading notes | Proposal role | Next action |",
            "| Date | Paper | Status | PDF reading notes | Proposal role | Next action |\n"
            "| --- | --- | --- | --- | --- | --- |",
        )
    ],
    "raw-idea.md": [
        ("## Original User Notes - Verbatim", "## Original User Notes - Verbatim"),
    ],
}


def _write_or_update_scaffold_file(
    path: Path,
    initial_text: str,
    *,
    slug: str,
) -> str:
    if not path.exists():
        write_text(path, initial_text)
        return "created"
    text = path.read_text(encoding="utf-8")
    additions = [
        snippet.format(slug=slug)
        for marker, snippet in PROPOSAL_REQUIRED_SNIPPETS.get(path.name, [])
        if marker not in text
    ]
    if not additions:
        return "unchanged"
    write_text(path, text.rstrip() + "\n\n" + "\n\n".join(additions) + "\n")
    return "updated"


def proposal_sprint_scaffold(
    vault: Path | str,
    slug: str,
    *,
    title: str | None = None,
) -> dict[str, Any]:
    paths = initialize_vault(vault, rebuild=False)
    normalized_slug = _proposal_slug(slug)
    proposal_title = _proposal_title(normalized_slug, title)
    proposal_dir = paths.proposals / normalized_slug
    proposal_dir.mkdir(parents=True, exist_ok=True)
    template_texts = _proposal_scaffold_texts(normalized_slug, proposal_title)
    file_states: dict[str, list[str]] = {"created": [], "updated": [], "unchanged": []}
    for filename, initial_text in template_texts.items():
        state = _write_or_update_scaffold_file(
            proposal_dir / filename,
            initial_text,
            slug=normalized_slug,
        )
        file_states[state].append(ensure_relative(proposal_dir / filename, paths.vault))
    rebuild_summary = _rebuild_indexes(paths)
    return {
        "vault": str(paths.vault),
        "proposal": ensure_relative(proposal_dir, paths.vault),
        "title": proposal_title,
        "files": file_states,
        "rebuild": rebuild_summary,
    }


def proposal_audit(
    vault: Path | str,
    proposal: Path | str,
) -> dict[str, Any]:
    paths = VaultPaths.from_root(vault)
    proposal_path = _resolve_proposal_path(paths, proposal)
    files = _markdown_files(proposal_path)
    if not files:
        raise ValueError(f"No Markdown files found for proposal path: {proposal_path}")

    card_text_by_ref = {
        f"papers/{card.slug}.md": (paths.papers / f"{card.slug}.md").read_text(encoding="utf-8")
        for card in load_source_cards(paths)
    }
    outline_files = [path for path in files if "outline" in path.name.casefold()]
    local_source_matrix_files = [path for path in files if "matrix" in path.name.casefold()]
    declared_source_matrix_files, broken_matrix_links = _collect_declared_evidence_matrices(
        paths,
        outline_files,
    )
    source_matrix_files = sorted(
        {*local_source_matrix_files, *declared_source_matrix_files},
        key=lambda path: _display_path(path, paths.vault),
    )
    files = sorted(
        {*files, *declared_source_matrix_files},
        key=lambda path: _display_path(path, paths.vault),
    )
    file_texts = {path: path.read_text(encoding="utf-8") for path in files}
    raw_idea_files = [
        path
        for path in files
        if "idea" in path.name.casefold()
        and ("raw" in path.name.casefold() or "original" in path.name.casefold())
    ]
    draft_files = [
        path
        for path in files
        if any(token in path.name.casefold() for token in ["draft", "claim", "outline"])
    ]

    all_paper_refs = sorted(
        {ref for text in file_texts.values() for ref in _extract_paper_refs(text)}
    )
    read_paper_refs = [
        ref for ref in all_paper_refs if PDF_READING_NOTES_RE.search(card_text_by_ref.get(ref, ""))
    ]
    role_lookup: dict[str, bool] = {}
    for ref in all_paper_refs:
        role_lookup[ref] = any(
            _line_has_proposal_role(_line_for_ref(text, ref))
            for text in file_texts.values()
        ) or _line_has_proposal_role(card_text_by_ref.get(ref, ""))

    outline_missing_notes = []
    for file in outline_files:
        for ref in _extract_paper_refs(file_texts[file]):
            if not PDF_READING_NOTES_RE.search(card_text_by_ref.get(ref, "")):
                outline_missing_notes.append(
                    _proposal_issue(
                        file,
                        paths.vault,
                        "outline citation lacks PDF reading notes",
                        paper=ref,
                    )
                )

    read_without_role = [
        {"paper": ref, "message": "read paper lacks Proposal role"}
        for ref in read_paper_refs
        if not role_lookup.get(ref)
    ]

    for file in source_matrix_files:
        for target in _extract_markdown_targets(file_texts[file]):
            resolved = _resolve_markdown_target(paths, file, target)
            if not resolved.exists():
                broken_matrix_links.append(
                    _proposal_issue(
                        file,
                        paths.vault,
                        "source matrix link does not resolve",
                        target=target,
                    )
                )

    raw_idea_missing = []
    if not raw_idea_files:
        raw_idea_missing.append(
            {
                "file": None,
                "message": "no raw/original idea card found",
            }
        )
    for file in raw_idea_files:
        if not ORIGINAL_NOTES_RE.search(file_texts[file]):
            raw_idea_missing.append(
                _proposal_issue(
                    file,
                    paths.vault,
                    "raw idea card lacks Original User Notes - Verbatim heading",
                )
            )

    draft_scholar_labs_only = []
    draft_missing_notes = []
    for file in draft_files:
        text = file_texts[file]
        for line_number, line in enumerate(text.splitlines(), start=1):
            if "scholar labs summar" in line.casefold():
                draft_scholar_labs_only.append(
                    _proposal_issue(
                        file,
                        paths.vault,
                        "draft claim references Scholar Labs summary",
                        line=line_number,
                    )
                )
        for ref in _extract_paper_refs(text):
            if not PDF_READING_NOTES_RE.search(card_text_by_ref.get(ref, "")):
                draft_missing_notes.append(
                    _proposal_issue(
                        file,
                        paths.vault,
                        "draft citation lacks PDF reading notes",
                        paper=ref,
                    )
                )

    issues = {
        "outline_citations_without_pdf_reading_notes": outline_missing_notes,
        "read_papers_without_proposal_role": read_without_role,
        "broken_source_matrix_links": broken_matrix_links,
        "raw_idea_missing_original_notes": raw_idea_missing,
        "draft_claims_using_scholar_labs_summaries": draft_scholar_labs_only,
        "draft_citations_without_pdf_reading_notes": draft_missing_notes,
    }
    issue_counts = {key: len(value) for key, value in issues.items()}
    return {
        "vault": str(paths.vault),
        "proposal": _display_path(proposal_path, paths.vault),
        "files": [_display_path(path, paths.vault) for path in files],
        "counts": {
            "files": len(files),
            "paper_refs": len(all_paper_refs),
            "read_papers": len(read_paper_refs),
            "outline_files": len(outline_files),
            "source_matrix_files": len(source_matrix_files),
            "raw_idea_files": len(raw_idea_files),
            "draft_files": len(draft_files),
        },
        "issue_counts": issue_counts,
        "issues": issues,
        "ok": not any(issue_counts.values()),
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
