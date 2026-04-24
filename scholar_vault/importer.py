from __future__ import annotations

import hashlib
import re
import shutil
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .bibtex import extract_pdf_paths, parse_bibtex_file, split_bibtex_authors, write_library_bib
from .citations import (
    EnrichmentOptions,
    EnrichmentProgress,
    EnrichmentResult,
    abstract_fingerprint,
    enrich_cards,
)
from .matcher import (
    best_pdf_match,
    build_pdf_candidate,
    match_candidate_to_cards,
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
    RationalePoint,
    RunRecord,
    RunResultRecord,
    ScholarLabsExport,
    ScholarLabsResult,
    SourceCard,
    SummarySource,
)
from .render import (
    group_cards_by_topic,
    render_llms_full,
    render_llms_txt,
    render_missing_pdfs,
    render_paper_markdown,
    render_papers_index,
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
    ensure_relative,
    infer_run_title,
    infer_topics,
    load_import_manifests,
    load_run_records,
    load_source_cards,
    normalize_copied_abstract,
    normalize_doi,
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


def _now_iso() -> str:
    return datetime.now().astimezone().replace(microsecond=0).isoformat()


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
                "keyword": ", ".join(card.topics) if card.topics else None,
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


def _rebuild_indexes(paths: VaultPaths) -> dict[str, int]:
    runs = load_run_records(paths)
    run_refs = {run.slug: _run_ref(run) for run in runs}
    cards = load_source_cards(paths)
    cards_changed = False
    cards_normalized = 0
    pdf_filenames_normalized = 0
    for card in cards:
        card_changed = False
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
        if card_changed:
            cards_changed = True
            cards_normalized += 1
    paper_cards_written = 0
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

    manifests = load_import_manifests(paths)
    topic_cards = group_cards_by_topic(cards)

    write_text(paths.indexes / "prompts.md", render_prompts_index(runs))
    write_text(paths.indexes / "papers.md", render_papers_index(cards))
    write_text(paths.indexes / "topics.md", render_topics_index(topic_cards))
    write_text(paths.indexes / "missing-pdfs.md", render_missing_pdfs(runs))
    write_text(paths.indexes / "unmatched.md", render_unmatched_index(manifests))
    write_text(paths.indexes / "zotero-migration.md", render_zotero_migration())
    write_text(paths.vault / "llms.txt", render_llms_txt())
    write_text(paths.vault / "llms-full.txt", render_llms_full(cards, runs, manifests))
    write_json(paths.exports / "library.json", _cards_to_library_json(cards))
    write_json(paths.exports / "library.csl.json", _cards_to_csl_json(cards))
    write_library_bib(cards, paths.exports / "library.bib")

    for topic, topic_list in topic_cards.items():
        write_text(paths.topics / f"{topic_slug(topic)}.md", render_topic_page(topic, topic_list))
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
        "index_files_written": 6,
        "llm_files_written": 2,
        "export_files_written": 3,
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
    run_title = run_display_title(
        title or (existing_run.title if existing_run else None),
        export.prompt,
    )
    run_note_file = existing_run.note_file if existing_run and title is None else None
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
    candidates = []
    for index, path in enumerate(staged_pdf_paths, start=1):
        if progress:
            progress(f"Scanning staged PDF {path.name}", index, len(staged_pdf_paths))
        candidates.append(build_pdf_candidate(path))
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
    }

    sorted_results = sorted(export.results, key=lambda item: item.rank)
    total_results = len(sorted_results)
    for index, result in enumerate(sorted_results, start=1):
        if progress:
            progress(
                f"Checking Scholar Labs result {result.rank}: {result.title}",
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
            decision_summary["prior_selected_reused"] += 1
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

        existing_card = _find_existing_card(
            cards,
            scholar_cid=result.scholar_cid,
            title=result.title,
        )

        match = best_pdf_match(result.title, remaining)
        proposal = match if match.candidate and match.score >= 70 else None
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
            elif commit:
                if proposal.decision == "auto":
                    decision = "accepted"
                    decision_summary["commit_auto_accepted"] += 1
                else:
                    run_status = "unmatched"
                    pdf_status = "unmatched"
                    decision_summary["commit_proposals_skipped"] += 1
            elif interactive:
                if review_match is not None:
                    decision_summary["review_prompts"] += 1
                    accepted = review_match(_build_match_review_request(result, proposal))
                elif confirm is not None:
                    decision_summary["review_prompts"] += 1
                    accepted = confirm(
                        f"Accept match {Path(proposal.candidate.path).name} -> {result.title} "
                        f"(score={proposal.score})?"
                    )
                else:
                    accepted = proposal.decision == "auto"
                if accepted:
                    decision = "accepted"
                    decision_summary["review_accepted"] += 1
                else:
                    decision = "rejected"
                    run_status = "unmatched"
                    pdf_status = "unmatched"
                    decision_summary["review_rejected"] += 1

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
            if card.citation_status == "preview":
                card.citation_status = "missing"
            source_pdf = Path(proposal.candidate.path)
            if archive_matched and source_pdf.exists():
                archived_original_path = _archive_matched_pdf(paths, run_slug, source_pdf)
                moved = True
                archived_files.append(Path(archived_original_path).name)
                note = f"Archived matched staging PDF to {archived_original_path}."
            _save_card(paths, card)
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
                        f"Enriching citations [{status}]: {card.citekey or card.slug}",
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
                        f"Enriching abstracts [{status}]: {card.citekey or card.slug}",
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
            for card in selected_cards:
                _save_card(paths, card)

    citation_processed = len(enrichment_details)
    abstract_processed = len(abstract_details)
    citation_changed = sum(1 for row in enrichment_details if row.get("changed"))
    abstract_changed = sum(1 for row in abstract_details if row.get("changed"))

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
        "enrichment_details": enrichment_details,
        "abstract_details": abstract_details,
        "run": run_slug,
    }


def resume_run(
    vault: Path | str,
    run_id: str,
    *,
    dry_run: bool = False,
    commit: bool = False,
    auto_enrich: bool = False,
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
        title=run.title,
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

    runs = load_run_records(paths)
    run_ref = None
    for run in runs:
        changed = False
        for result in run.results:
            if result.scholar_cid and result.scholar_cid == card.scholar_cid:
                result.status = "selected"
                result.pdf_status = "attached"
                result.paper_card = f"papers/{card.slug}.md"
                changed = True
            elif normalize_title(result.title) == normalize_title(card.title):
                result.status = "selected"
                result.pdf_status = "attached"
                result.paper_card = f"papers/{card.slug}.md"
                changed = True
        if changed:
            run_ref = _run_ref(run)
            if run_ref not in card.discovered_in:
                card.discovered_in.append(run_ref)
            _write_run(paths, run, load_source_cards(paths))
    _save_card(paths, card)
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
    staging_path: Path | str,
    *,
    confirm: ConfirmCallback | None = None,
) -> dict[str, int]:
    del confirm
    paths = initialize_vault(vault)
    staging_dir = Path(staging_path).expanduser().resolve()
    cards = load_source_cards(paths)
    log_entries: list[ImportLogEntry] = []
    imported = 0

    for pdf_path in sorted(staging_dir.glob("*.pdf")):
        candidate = build_pdf_candidate(pdf_path)
        existing, score = match_candidate_to_cards(candidate, cards)

        if existing and score >= 90:
            card = existing
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
                source_kind="pdf_drop",
                status="active",
                pdf_status="missing",
                doi_status="detected" if candidate.doi else "missing",
                doi_source="pdf" if candidate.doi else None,
                doi_confidence=0.95 if candidate.doi else None,
                citation_status="missing",
                summary="No summary yet.",
            )
            cards.append(card)

        if candidate.doi and not card.doi:
            card.doi = normalize_doi(candidate.doi)
            card.doi_status = "detected"
            card.doi_source = "pdf"
            card.doi_confidence = 0.95
        if candidate.year and not card.year:
            card.year = candidate.year
        if not card.title and candidate.title:
            card.title = candidate.title
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
        log_entries.append(
            ImportLogEntry(
                source_path=str(pdf_path),
                destination_path=card.pdf,
                status="imported",
                score=score if existing else None,
            )
        )

    if log_entries:
        _write_log(paths, "import-pdf", log_entries)
    _rebuild_indexes(paths)
    return {"imported": imported}


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
            topics=[
                token.strip() for token in (entry.get("keywords") or "").split(",") if token.strip()
            ],
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
) -> dict[str, Any]:
    if result.skipped:
        category = "skipped"
    elif not abstracts and card.enrichment_status == "incomplete":
        category = "incomplete"
    else:
        category = result.status

    source = card.abstract_source if abstracts else card.citation_source or card.doi_source
    return {
        "kind": "abstract" if abstracts else "citation",
        "category": category,
        "status": result.status,
        "citekey": card.citekey or card.slug,
        "title": card.title,
        "paper_path": f"papers/{card.slug}.md",
        "paper_file": str(paths.papers / f"{card.slug}.md"),
        "pdf": card.pdf,
        "pdf_file": str(paths.vault / card.pdf) if card.pdf else None,
        "doi": card.doi,
        "source": source,
        "missing_fields": list(card.enrichment_missing),
        "message": result.message,
        "changed": result.changed,
        "skipped": result.skipped,
    }


def set_manual_abstract(
    vault: Path | str,
    citekey: str,
    abstract: str,
    *,
    source_url: str | None = None,
    lock: bool = True,
) -> dict[str, str | bool]:
    paths = initialize_vault(vault)
    cleaned = clean_markdown_text(normalize_copied_abstract(abstract))
    if not cleaned:
        raise ValueError("Manual abstract text is empty.")

    cards = load_source_cards(paths)
    card = next((item for item in cards if item.citekey == citekey or item.slug == citekey), None)
    if card is None:
        raise ValueError(f"No paper card found for citekey or slug: {citekey}")

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
    _save_card(paths, card)
    _rebuild_indexes(paths)
    return {
        "citekey": card.citekey or card.slug,
        "paper": f"papers/{card.slug}.md",
        "locked": lock,
    }


def rebuild_vault(vault: Path | str) -> dict[str, int]:
    paths = initialize_vault(vault, rebuild=False)
    return _rebuild_indexes(paths)


def export_bibtex(vault: Path | str) -> Path:
    paths = initialize_vault(vault)
    cards = load_source_cards(paths)
    return write_library_bib(cards, paths.exports / "library.bib")


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
    if only not in {"all", "missing-doi", "missing-bibtex", "missing-abstract"}:
        raise ValueError("--only must be one of: missing-doi, missing-bibtex, missing-abstract")

    enrich_abstracts = abstracts or refresh_abstracts or only == "missing-abstract"

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
        _enrichment_detail(paths, card, result, abstracts=enrich_abstracts)
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
        "details": details,
    }
