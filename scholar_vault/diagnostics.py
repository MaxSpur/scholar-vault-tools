from __future__ import annotations

import hashlib
import re
import subprocess
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from .citations import refresh_metadata_completeness
from .digests import compile_status_summary
from .models import ImportManifest, RunRecord, SourceCard
from .obsidian import (
    _card_has_valid_pdf,
    _card_id,
    _card_ref,
    _display_path,
    _markdown_heading_re,
    _status_counts,
)
from .sources import (
    VaultPaths,
    infer_run_title,
    load_import_manifests,
    load_run_records,
    load_source_cards,
)
from .topics import _topic_report

CANONICAL_TOP_LEVELS = {
    "papers",
    "paper-digests",
    "pdfs",
    "raw",
    "concepts",
    "syntheses",
    "tasks",
    "queries",
    "projects",
    "proposals",
}
GENERATED_TOP_LEVELS = {"_indexes", "topics", "_exports", "bases"}
GENERATED_FILES = {"llms.txt", "llms-full.txt"}
RUN_CANONICAL_FILES = {"index.yaml", "import-manifest.yaml"}


def _parse_datetime(value: str | None) -> datetime:
    if not value:
        return datetime.now().astimezone()
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now().astimezone()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


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


def _git_path_top_level(path: str) -> str:
    clean = path.strip("/")
    if not clean:
        return "."
    return clean.split("/", 1)[0]


def _classify_git_path(path: str) -> str:
    clean = path.strip("/")
    top_level = _git_path_top_level(clean)
    if clean in GENERATED_FILES or top_level in GENERATED_TOP_LEVELS:
        return "generated"
    if top_level == "runs":
        name = Path(clean).name
        return "canonical" if name in RUN_CANONICAL_FILES else "generated"
    if top_level == "projects" and Path(clean).name == "project-map.md":
        return "generated"
    if top_level in CANONICAL_TOP_LEVELS:
        return "canonical"
    return "other"


def _parse_git_status_porcelain_z(raw: bytes) -> list[dict[str, str]]:
    parts = raw.decode("utf-8", errors="replace").split("\0")
    entries: list[dict[str, str]] = []
    index = 0
    while index < len(parts):
        item = parts[index]
        index += 1
        if not item:
            continue
        status = item[:2]
        path = item[3:]
        if "R" in status or "C" in status:
            if index < len(parts) and parts[index]:
                path = parts[index]
                index += 1
        entries.append({"status": status, "path": path})
    return entries


def git_summary(vault: Path | str) -> dict[str, Any]:
    root = Path(vault).expanduser().resolve()
    try:
        git_root = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
            check=True,
            capture_output=True,
        ).stdout.decode("utf-8", errors="replace").strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError(f"Vault is not a git repository: {root}") from exc

    status = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain=v1", "-z", "--untracked-files=all"],
        check=True,
        capture_output=True,
    )
    rows = []
    by_top_level: dict[str, dict[str, int]] = {}
    by_class: Counter[str] = Counter()
    for entry in _parse_git_status_porcelain_z(status.stdout):
        path = entry["path"]
        classification = _classify_git_path(path)
        top_level = _git_path_top_level(path)
        by_class[classification] += 1
        folder_counts = by_top_level.setdefault(
            top_level,
            {"canonical": 0, "generated": 0, "other": 0, "total": 0},
        )
        folder_counts[classification] += 1
        folder_counts["total"] += 1
        rows.append(
            {
                "path": path,
                "status": entry["status"],
                "top_level": top_level,
                "classification": classification,
            }
        )
    return {
        "vault": str(root),
        "git_root": git_root,
        "changed": len(rows),
        "by_class": {key: by_class.get(key, 0) for key in ["canonical", "generated", "other"]},
        "by_top_level": dict(sorted(by_top_level.items())),
        "files": sorted(rows, key=lambda row: row["path"]),
    }


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
    compile_summary = compile_status_summary(paths, cards=cards)
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
            "compile_needs_action": compile_summary.get("needs_action"),
            "paper_digests": compile_summary.get("digests"),
        },
        "status_counts": {
            "pdf_status": _status_counts(cards, "pdf_status"),
            "reading_status": _status_counts(cards, "reading_status"),
            "compiled_status": _status_counts(cards, "compiled_status"),
            "review_status": _status_counts(cards, "review_status"),
            "evidence_level": _status_counts(cards, "evidence_level"),
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
        "compile": compile_summary,
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
