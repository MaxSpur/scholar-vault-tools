from __future__ import annotations

import shutil
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from .bibtex import extract_pdf_paths, parse_bibtex_file, split_bibtex_authors, write_library_bib
from .matcher import (
    best_pdf_match,
    build_pdf_candidate,
    match_candidate_to_cards,
    score_title_match,
)
from .models import (
    ImportLog,
    ImportLogEntry,
    Link,
    RationalePoint,
    RunRecord,
    ScholarLabsExport,
    ScholarLabsResult,
    SourceCard,
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
    infer_topics,
    load_run_records,
    load_source_cards,
    normalize_doi,
    normalize_title,
    parse_people,
    slugify_text,
    topic_slug,
    write_json,
    write_text,
    write_yaml,
)

ConfirmCallback = Callable[[str], bool]


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
    existing_normalized = normalize_title(existing.title)
    incoming_normalized = normalize_title(incoming_title)
    if existing_normalized == incoming_normalized:
        return False
    if existing.title == existing.slug.replace("-", " "):
        return True
    if len(existing.title.split()) < 3 and len(incoming_title.split()) >= 3:
        return True
    return False


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
    if normalized_title:
        best_card: SourceCard | None = None
        best_score = 0
        for card in cards:
            score = score_title_match(title, card.title)
            if score > best_score:
                best_card = card
                best_score = score
        if best_score >= 96:
            return best_card
    return None


def _new_card_from_result(
    result: ScholarLabsResult,
    *,
    run_ref: str,
    prompt: str,
    existing_cards: list[SourceCard],
) -> SourceCard:
    authors = parse_people(result.authors_preview)
    citekey = build_citekey(
        result.title,
        authors,
        result.year,
        authors_preview=result.authors_preview,
        existing_keys=[card.citekey for card in existing_cards if card.citekey],
    )
    slug = build_card_slug(citekey, result.title, [card.slug for card in existing_cards])
    citation_status = (
        "complete" if result.title and authors and result.year and result.venue else "partial"
    )
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
        citation_status=citation_status,
        links=result.links,
        summary=clean_markdown_text(result.summary) or "No summary yet.",
        why_this_source_matters=result.rationale_points,
    )


def _merge_cards(existing: SourceCard, incoming: SourceCard) -> SourceCard:
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
    existing.citation_status = (
        "complete"
        if "complete" in {existing.citation_status, incoming.citation_status}
        else "partial"
    )
    return existing


def _save_card(paths: VaultPaths, card: SourceCard) -> None:
    path = paths.papers / f"{card.slug}.md"
    write_text(path, render_paper_markdown(card))


def _move_pdf_to_vault(paths: VaultPaths, source_pdf: Path, card: SourceCard) -> str:
    if card.pdf:
        destination = paths.vault / card.pdf
        if destination.exists():
            return card.pdf
    filename = build_pdf_filename(
        card.title,
        card.authors,
        card.year,
        authors_preview=card.authors_preview,
        existing_names=[path.name for path in paths.pdfs.glob("*.pdf")],
    )
    destination = paths.pdfs / filename
    if source_pdf.resolve() != destination.resolve():
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source_pdf.exists():
            shutil.move(str(source_pdf), str(destination))
    return ensure_relative(destination, paths.vault)


def _write_log(paths: VaultPaths, command: str, entries: list[ImportLogEntry]) -> None:
    log = ImportLog(command=command, created_at=_now_iso(), entries=entries)
    timestamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    path = paths.raw_imported / f"{timestamp}_{command}.yaml"
    write_yaml(path, log.model_dump(exclude_none=True))


def _write_run(paths: VaultPaths, run: RunRecord, cards: list[SourceCard]) -> None:
    run_dir = paths.runs / run.slug
    run_dir.mkdir(parents=True, exist_ok=True)
    write_yaml(run_dir / "index.yaml", run.model_dump(exclude_none=True))
    cards_by_slug = {card.slug: card for card in cards}
    write_text(run_dir / "index.md", render_run_markdown(run, cards_by_slug))


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
                "keyword": ", ".join(card.topics) if card.topics else None,
                "note": note,
            }
        )
    return exported


def _rebuild_indexes(paths: VaultPaths) -> None:
    cards = load_source_cards(paths)
    runs = load_run_records(paths)
    cards_by_slug = {card.slug: card for card in cards}
    topic_cards = group_cards_by_topic(cards)

    write_text(paths.indexes / "prompts.md", render_prompts_index(runs))
    write_text(paths.indexes / "papers.md", render_papers_index(cards))
    write_text(paths.indexes / "topics.md", render_topics_index(topic_cards))
    write_text(paths.indexes / "missing-pdfs.md", render_missing_pdfs(cards))
    raw_unmatched = [
        path.relative_to(paths.vault).as_posix()
        for path in sorted(paths.raw_unmatched.rglob("*"))
        if path.is_file()
    ]
    write_text(paths.indexes / "unmatched.md", render_unmatched_index(cards, raw_unmatched))
    write_text(paths.indexes / "zotero-migration.md", render_zotero_migration())
    write_text(paths.vault / "llms.txt", render_llms_txt())
    write_text(paths.vault / "llms-full.txt", render_llms_full(cards, runs))
    write_json(paths.exports / "library.json", _cards_to_library_json(cards))
    write_json(paths.exports / "library.csl.json", _cards_to_csl_json(cards))
    write_library_bib(cards, paths.exports / "library.bib")

    for topic, topic_list in topic_cards.items():
        write_text(paths.topics / f"{topic_slug(topic)}.md", render_topic_page(topic, topic_list))
    for run in runs:
        _write_run(paths, run, list(cards_by_slug.values()))


def initialize_vault(vault: Path | str) -> VaultPaths:
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
    _rebuild_indexes(paths)
    return paths


def import_scholar_labs_run(
    vault: Path | str,
    export_path: Path | str,
    staging_path: Path | str,
    *,
    confirm: ConfirmCallback | None = None,
) -> dict[str, int | str]:
    paths = initialize_vault(vault)
    export_file = Path(export_path).expanduser().resolve()
    staging_dir = Path(staging_path).expanduser().resolve()
    export = ScholarLabsExport.model_validate_json(export_file.read_text(encoding="utf-8"))
    run_slug, run_date = _run_slug(export, export_file)
    raw_export_file = paths.raw_scholar_labs / f"{run_slug}.json"
    if not raw_export_file.exists():
        raw_export_file.write_text(export_file.read_text(encoding="utf-8"), encoding="utf-8")

    cards = load_source_cards(paths)
    candidates = [build_pdf_candidate(path) for path in sorted(staging_dir.glob("*.pdf"))]
    remaining = list(candidates)
    log_entries: list[ImportLogEntry] = []
    paper_slugs: list[str] = []
    matched_files: list[str] = []

    run_ref = f"runs/{run_slug}/index.md"

    for result in sorted(export.results, key=lambda item: item.rank):
        incoming = _new_card_from_result(
            result,
            run_ref=run_ref,
            prompt=export.prompt,
            existing_cards=cards,
        )
        existing = _find_existing_card(
            cards,
            scholar_cid=result.scholar_cid,
            title=result.title,
            citekey=incoming.citekey,
        )
        card = _merge_cards(existing, incoming) if existing else incoming
        if not existing:
            cards.append(card)

        if card.pdf_status != "attached" and remaining:
            decision = best_pdf_match(result.title, remaining, expected_doi=card.doi)
            accepted = decision.decision == "auto"
            if (
                decision.decision == "review"
                and confirm is not None
                and decision.candidate is not None
            ):
                accepted = confirm(
                    f"Match {Path(decision.candidate.path).name} "
                    f"to {card.title}? score={decision.score}"
                )
            if accepted and decision.candidate is not None:
                source_pdf = Path(decision.candidate.path)
                card.pdf = _move_pdf_to_vault(paths, source_pdf, card)
                card.pdf_status = "attached"
                matched_files.append(source_pdf.name)
                remaining = [
                    candidate
                    for candidate in remaining
                    if candidate.path != decision.candidate.path
                ]
                log_entries.append(
                    ImportLogEntry(
                        source_path=str(source_pdf),
                        destination_path=card.pdf,
                        status="matched",
                        score=decision.score,
                    )
                )

        _save_card(paths, card)
        paper_slugs.append(card.slug)

    unmatched_files: list[str] = []
    for candidate in remaining:
        source_pdf = Path(candidate.path)
        destination = paths.raw_unmatched / source_pdf.name
        if source_pdf.exists():
            shutil.move(str(source_pdf), str(destination))
        relative_destination = ensure_relative(destination, paths.vault)
        unmatched_files.append(relative_destination)
        log_entries.append(
            ImportLogEntry(
                source_path=str(source_pdf),
                destination_path=relative_destination,
                status="unmatched",
            )
        )

    run_record = RunRecord(
        slug=run_slug,
        date=run_date,
        prompt=export.prompt,
        exported_at=export.exported_at,
        export_file=str(export_file),
        raw_export_file=ensure_relative(raw_export_file, paths.vault),
        result_count=len(export.results),
        results=export.results,
        paper_slugs=paper_slugs,
        matched_files=matched_files,
        unmatched_files=unmatched_files,
    )
    _write_run(paths, run_record, cards)
    if log_entries:
        _write_log(paths, "import-run", log_entries)
    _rebuild_indexes(paths)
    return {
        "papers": len(paper_slugs),
        "matched": len(matched_files),
        "unmatched": len(unmatched_files),
        "run": run_slug,
    }


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
                citation_status="partial",
                summary="No summary yet.",
            )
            cards.append(card)

        if candidate.doi and not card.doi:
            card.doi = normalize_doi(candidate.doi)
        if candidate.year and not card.year:
            card.year = candidate.year
        if not card.title and candidate.title:
            card.title = candidate.title
        if not card.pdf:
            card.pdf = _move_pdf_to_vault(paths, pdf_path, card)
        card.pdf_status = "attached"
        card.citation_status = "complete" if card.title and card.year and card.doi else "partial"
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


def import_bibtex(
    vault: Path | str,
    bib_path: Path | str,
) -> dict[str, int]:
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
            citation_status="complete" if title and authors and entry.get("year") else "partial",
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
            citation_status="partial",
            pdf_status="missing",
            summary="No summary yet.",
        )
        cards.append(existing)
    _save_card(paths, existing)
    _rebuild_indexes(paths)
    return {"imported": 1}


def rebuild_vault(vault: Path | str) -> None:
    paths = initialize_vault(vault)
    _rebuild_indexes(paths)


def export_bibtex(vault: Path | str) -> Path:
    paths = initialize_vault(vault)
    cards = load_source_cards(paths)
    return write_library_bib(cards, paths.exports / "library.bib")
