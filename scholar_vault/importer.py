from __future__ import annotations

import hashlib
import shutil
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from pydantic import ValidationError

from .bibtex import extract_pdf_paths, parse_bibtex_file, split_bibtex_authors, write_library_bib
from .matcher import (
    best_pdf_match,
    build_pdf_candidate,
    match_candidate_to_cards,
)
from .models import (
    ImportLog,
    ImportLogEntry,
    ImportManifest,
    ImportManifestEntry,
    Link,
    MatchDecision,
    RationalePoint,
    RunRecord,
    RunResultRecord,
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
    load_import_manifests,
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


def _run_ref(run_id: str) -> str:
    return f"runs/{run_id}/index.md"


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
    if incoming.status == "candidate" and existing.status != "active":
        existing.status = "candidate"
    existing.citation_status = (
        "complete"
        if "complete" in {existing.citation_status, incoming.citation_status}
        else incoming.citation_status
        if incoming.citation_status == "preview"
        else existing.citation_status
    )
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
        incoming.citation_status = "preview"
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
    path = paths.runs / run_id / "index.yaml"
    if not path.exists():
        return None
    return _read_run_yaml(path)


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
    write_yaml(run_dir / "index.yaml", run.model_dump(exclude_none=True))
    cards_by_slug = {card.slug: card for card in cards}
    write_text(run_dir / "index.md", render_run_markdown(run, cards_by_slug))


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
                "keyword": ", ".join(card.topics) if card.topics else None,
                "note": note,
            }
        )
    return exported


def _rebuild_indexes(paths: VaultPaths) -> None:
    cards = load_source_cards(paths)
    runs = load_run_records(paths)
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
            and run_ref in card.discovered_in
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


def import_scholar_labs_run(
    vault: Path | str,
    export_path: Path | str,
    staging_path: Path | str,
    *,
    dry_run: bool = False,
    commit: bool = False,
    include_without_pdf: bool = False,
    confirm: ConfirmCallback | None = None,
) -> dict[str, int | str]:
    if dry_run and commit:
        raise ValueError("Use either dry-run or commit, not both.")

    paths = initialize_vault(vault)
    export_file = Path(export_path).expanduser().resolve()
    staging_dir = Path(staging_path).expanduser().resolve()
    export = _load_validated_scholar_export(paths, export_file)
    run_slug, run_date = _run_slug(export, export_file)
    run_ref = _run_ref(run_slug)
    existing_run = _load_run_record(paths, run_slug)
    if existing_run and not dry_run and not commit and confirm is not None:
        if not confirm(f"Run {run_slug} already exists. Resume and update it?"):
            raise ValueError(f"Run {run_slug} already exists.")

    raw_export_file = paths.raw_scholar_labs / f"{run_slug}.json"
    if not raw_export_file.exists():
        raw_export_file.write_text(export_file.read_text(encoding="utf-8"), encoding="utf-8")

    cards = load_source_cards(paths)
    existing_manifest = _load_manifest(paths, run_slug)
    existing_results = (
        {_result_key(result): result for result in existing_run.results}
        if existing_run
        else {}
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

    candidates = [build_pdf_candidate(path) for path in sorted(staging_dir.glob("*.pdf"))]
    remaining = list(candidates)
    run_results: list[RunResultRecord] = []
    manifest_entries: list[ImportManifestEntry] = []
    matched_files: list[str] = []
    unmatched_files: list[str] = []
    log_entries: list[ImportLogEntry] = []
    interactive = not dry_run and not commit

    for result in sorted(export.results, key=lambda item: item.rank):
        key = _result_key(result)
        prior_result = existing_results.get(key)
        prior_entry = existing_entries.get(key)
        if (
            prior_result
            and prior_result.status == "selected"
            and _paper_card_exists(paths, prior_result.paper_card)
        ):
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
        verified = False
        destination_path: str | None = None
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
            elif commit:
                if proposal.decision == "auto":
                    decision = "accepted"
                else:
                    run_status = "unmatched"
                    pdf_status = "unmatched"
            elif interactive:
                accepted = confirm(
                    f"Accept match {Path(proposal.candidate.path).name} -> {result.title} "
                    f"(score={proposal.score})?"
                ) if confirm is not None else proposal.decision == "auto"
                if accepted:
                    decision = "accepted"
                else:
                    decision = "rejected"
                    run_status = "unmatched"
                    pdf_status = "unmatched"

        if decision == "accepted" and proposal is not None:
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
                card.citation_status = "partial"
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
                )
            )
        else:
            if existing_paper_card:
                paper_card = existing_paper_card
            if include_without_pdf and not dry_run:
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
            if proposal is not None:
                unmatched_files.append(Path(proposal.candidate.path).name)
                if decision == "unresolved":
                    run_status = "unmatched"
                    pdf_status = "unmatched"
                    note = "Match proposed but not committed."
                elif decision == "rejected":
                    note = "User rejected the proposed match."

        if prior_result and paper_card is None and prior_result.paper_card and existing_paper_card:
            paper_card = existing_paper_card

        run_results.append(
            RunResultRecord(
                **result.model_dump(),
                status=run_status,
                pdf_status=pdf_status,
                paper_card=paper_card,
                proposed_pdf=(
                    proposal.candidate.path if proposal and proposal.candidate else None
                ),
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
        exported_at=export.exported_at,
        export_file=str(export_file),
        raw_export_file=ensure_relative(raw_export_file, paths.vault),
        staging_folder=str(staging_dir),
        result_count=len(export.results),
        include_without_pdf=include_without_pdf,
        results=run_results,
        matched_files=sorted(set(matched_files)),
        unmatched_files=sorted(set(unmatched_files)),
    )
    _write_manifest(paths, manifest)
    _write_run(paths, run_record, cards)
    if log_entries:
        _write_log(paths, "import-run", log_entries)
    _rebuild_indexes(paths)
    return {
        "papers": len([result for result in run_results if result.paper_card]),
        "selected": len([result for result in run_results if result.status == "selected"]),
        "matched": len([result for result in run_results if result.pdf_status == "attached"]),
        "unmatched": len(sorted(set(unmatched_files))),
        "run": run_slug,
    }


def resume_run(
    vault: Path | str,
    run_id: str,
    *,
    dry_run: bool = False,
    commit: bool = False,
    confirm: ConfirmCallback | None = None,
) -> dict[str, int | str]:
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
        confirm=confirm,
    )


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
        if not entry.destination_path or not entry.copied:
            continue
        destination_path = paths.vault / entry.destination_path
        if destination_path.exists() and entry.destination_path not in referenced_pdfs:
            destination = _archive_path(archive_root / "pdfs", destination_path.name)
            shutil.move(str(destination_path), str(destination))
            archived_pdfs += 1

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
            run_ref = _run_ref(run.slug)
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
    run_ref = _run_ref(run_id)
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
            card.pdf, _, _ = _copy_pdf_to_vault(
                paths,
                pdf_path,
                card,
                original_sha256=candidate.sha256 or _file_sha256(pdf_path),
            )
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
                token.strip()
                for token in (entry.get("keywords") or "").split(",")
                if token.strip()
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
