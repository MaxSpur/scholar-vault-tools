from __future__ import annotations

import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from .discovery_adapters import DiscoveryPaper, DiscoveryProviderError, ProviderName, get_adapter
from .models import DiscoveryCandidate, DiscoveryStatus, SourceCard
from .sources import (
    VaultPaths,
    clean_markdown_text,
    ensure_relative,
    load_import_manifests,
    load_run_records,
    load_source_cards,
    normalize_doi,
    normalize_title,
    slugify_text,
    write_yaml,
)

DISCOVERY_STATUSES: set[str] = {"candidate", "selected", "rejected", "imported"}


def _now_iso() -> str:
    return datetime.now().astimezone().replace(microsecond=0).isoformat()


def _read_yaml_mapping(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError("Discovery candidate YAML must be a mapping.")
    return data


def _candidate_path(paths: VaultPaths, candidate_id: str) -> Path:
    return paths.discovery_candidates / f"{candidate_id}.yaml"


def _candidate_ref(paths: VaultPaths, candidate: DiscoveryCandidate) -> str:
    return ensure_relative(_candidate_path(paths, candidate.id), paths.vault)


def _query_ref(slug: str | None) -> str | None:
    if not slug:
        return None
    raw = str(slug).strip().strip("/")
    if raw.startswith("queries/"):
        return raw if raw.endswith(".md") else f"{raw}.md"
    if raw.endswith(".md"):
        return f"queries/{Path(raw).stem}.md"
    return f"queries/{raw}.md"


def _source_id_fragment(source_id: str | None) -> str:
    if not source_id:
        return ""
    return str(source_id).rstrip("/").rsplit("/", 1)[-1]


def _candidate_id(paper: DiscoveryPaper) -> str:
    source = paper.source
    if paper.source_id:
        key = _source_id_fragment(paper.source_id)
    elif paper.doi:
        key = f"doi-{normalize_doi(paper.doi)}"
    else:
        key = paper.title
    return f"{source}-{slugify_text(key, max_length=90)}"


def _candidate_from_paper(
    paper: DiscoveryPaper,
    *,
    seed_citekey: str | None = None,
    query: str | None = None,
    project: str | None = None,
) -> DiscoveryCandidate:
    return DiscoveryCandidate(
        id=_candidate_id(paper),
        source=paper.source,
        title=paper.title,
        authors=list(paper.authors),
        year=paper.year,
        doi=normalize_doi(paper.doi),
        url=paper.url,
        venue=paper.venue,
        abstract=clean_markdown_text(paper.abstract),
        cited_by_count=paper.cited_by_count,
        seed_citekey=seed_citekey,
        query=query,
        project=project,
        reason=paper.reason,
        status="candidate",
        linked_prompt_pack=None,
        linked_run=None,
    )


def _candidate_fingerprints(candidate: DiscoveryCandidate) -> list[tuple[str, str]]:
    fingerprints: list[tuple[str, str]] = []
    doi = normalize_doi(candidate.doi)
    if doi:
        fingerprints.append(("doi", doi))
    title = normalize_title(candidate.title)
    if title:
        fingerprints.append(("title", title))
    return fingerprints


def _card_fingerprints(card: SourceCard) -> set[tuple[str, str]]:
    fingerprints: set[tuple[str, str]] = set()
    doi = normalize_doi(card.doi)
    if doi:
        fingerprints.add(("doi", doi))
    title = normalize_title(card.title)
    if title:
        fingerprints.add(("title", title))
    if card.citekey:
        fingerprints.add(("citekey", card.citekey.casefold()))
    return fingerprints


def _candidate_matches_card(candidate: DiscoveryCandidate, cards: list[SourceCard]) -> bool:
    candidate_fingerprints = set(_candidate_fingerprints(candidate))
    for card in cards:
        card_fingerprints = _card_fingerprints(card)
        seed_key = (
            ("citekey", candidate.seed_citekey.casefold()) if candidate.seed_citekey else None
        )
        if seed_key and seed_key in card_fingerprints:
            if ("title", normalize_title(candidate.title)) in card_fingerprints:
                return True
        if candidate_fingerprints & card_fingerprints:
            return True
    return False


def _merge_candidate(
    existing: DiscoveryCandidate,
    incoming: DiscoveryCandidate,
) -> DiscoveryCandidate:
    merged = incoming.model_copy(deep=True)
    merged.status = existing.status
    merged.linked_prompt_pack = existing.linked_prompt_pack or incoming.linked_prompt_pack
    merged.linked_run = existing.linked_run or incoming.linked_run
    if existing.seed_citekey and not merged.seed_citekey:
        merged.seed_citekey = existing.seed_citekey
    if existing.query and not merged.query:
        merged.query = existing.query
    if existing.project and not merged.project:
        merged.project = existing.project
    return merged


def _write_candidate(paths: VaultPaths, candidate: DiscoveryCandidate) -> str:
    path = _candidate_path(paths, candidate.id)
    payload = candidate.model_dump()
    write_yaml(path, payload)
    return ensure_relative(path, paths.vault)


def load_discovery_candidates(paths: VaultPaths) -> list[DiscoveryCandidate]:
    candidates: list[DiscoveryCandidate] = []
    if not paths.discovery_candidates.exists():
        return candidates
    for path in sorted(paths.discovery_candidates.glob("*.yaml")):
        candidates.append(DiscoveryCandidate.model_validate(_read_yaml_mapping(path)))
    return candidates


def discovery_counts(paths: VaultPaths) -> dict[str, Any]:
    try:
        candidates = load_discovery_candidates(paths)
    except (OSError, ValueError):
        candidates = []
    status_counts = Counter(candidate.status for candidate in candidates)
    return {
        "discovery_candidates": len(candidates),
        "discovery_candidate_status": dict(sorted(status_counts.items())),
        "selected_discovery_candidates": status_counts.get("selected", 0),
        "open_discovery_candidates": status_counts.get("candidate", 0),
    }


def _candidate_by_identity(
    candidates: list[DiscoveryCandidate],
) -> tuple[dict[str, DiscoveryCandidate], dict[tuple[str, str], DiscoveryCandidate]]:
    by_id = {candidate.id: candidate for candidate in candidates}
    by_fingerprint: dict[tuple[str, str], DiscoveryCandidate] = {}
    for candidate in candidates:
        for fingerprint in _candidate_fingerprints(candidate):
            by_fingerprint.setdefault(fingerprint, candidate)
    return by_id, by_fingerprint


def _refresh_discovery_dashboards(paths: VaultPaths) -> None:
    from .dashboards import _write_dashboard_indexes
    from .obsidian import _collect_research_artifacts
    from .render import group_cards_by_topic
    from .self_improvement import write_self_improvement_dashboard

    cards = load_source_cards(paths)
    runs = load_run_records(paths)
    manifests = load_import_manifests(paths)
    artifacts = _collect_research_artifacts(paths)
    _write_dashboard_indexes(paths, cards, runs, manifests, artifacts, group_cards_by_topic(cards))
    write_self_improvement_dashboard(paths.vault)


def _store_candidate_papers(
    paths: VaultPaths,
    papers: list[DiscoveryPaper],
    *,
    seed_citekey: str | None = None,
    query: str | None = None,
    project: str | None = None,
) -> dict[str, Any]:
    cards = load_source_cards(paths)
    existing = load_discovery_candidates(paths)
    by_id, by_fingerprint = _candidate_by_identity(existing)
    created: list[DiscoveryCandidate] = []
    updated: list[DiscoveryCandidate] = []
    skipped_imported: list[dict[str, str]] = []
    skipped_duplicate: list[dict[str, str]] = []
    for paper in papers:
        incoming = _candidate_from_paper(
            paper,
            seed_citekey=seed_citekey,
            query=query,
            project=project,
        )
        if _candidate_matches_card(incoming, cards):
            skipped_imported.append({"id": incoming.id, "title": incoming.title})
            continue
        duplicate = by_id.get(incoming.id)
        if duplicate is None:
            for fingerprint in _candidate_fingerprints(incoming):
                duplicate = by_fingerprint.get(fingerprint)
                if duplicate is not None:
                    break
        if duplicate is not None:
            merged = _merge_candidate(duplicate, incoming)
            if merged != duplicate:
                _write_candidate(paths, merged)
                updated.append(merged)
                by_id[merged.id] = merged
                for fingerprint in _candidate_fingerprints(merged):
                    by_fingerprint[fingerprint] = merged
            else:
                skipped_duplicate.append({"id": duplicate.id, "title": duplicate.title})
            continue
        _write_candidate(paths, incoming)
        created.append(incoming)
        by_id[incoming.id] = incoming
        for fingerprint in _candidate_fingerprints(incoming):
            by_fingerprint[fingerprint] = incoming
    if created or updated:
        _refresh_discovery_dashboards(paths)
    return {
        "created": created,
        "updated": updated,
        "skipped_imported": skipped_imported,
        "skipped_duplicate": skipped_duplicate,
    }


def _candidate_rows(
    paths: VaultPaths,
    candidates: list[DiscoveryCandidate],
) -> list[dict[str, Any]]:
    rows = []
    for candidate in candidates:
        rows.append(
            {
                **candidate.model_dump(),
                "path": _candidate_ref(paths, candidate),
            }
        )
    return rows


def _discovery_summary(
    paths: VaultPaths,
    *,
    mode: str,
    sources: list[ProviderName],
    stored: dict[str, Any],
    errors: list[dict[str, str]],
) -> dict[str, Any]:
    candidates = [*stored["created"], *stored["updated"]]
    counts = discovery_counts(paths)
    return {
        "vault": str(paths.vault),
        "mode": mode,
        "sources": list(sources),
        "created": len(stored["created"]),
        "updated": len(stored["updated"]),
        "skipped_imported": len(stored["skipped_imported"]),
        "skipped_duplicate": len(stored["skipped_duplicate"]),
        "errors": errors,
        "counts": counts,
        "candidates": _candidate_rows(paths, candidates),
        "skipped_imported_candidates": stored["skipped_imported"],
        "skipped_duplicate_candidates": stored["skipped_duplicate"],
    }


def _combine_store_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    combined = {
        "created": [],
        "updated": [],
        "skipped_imported": [],
        "skipped_duplicate": [],
    }
    for result in results:
        for key in combined:
            combined[key].extend(result.get(key) or [])
    return combined


def _find_seed_card(paths: VaultPaths, citekey: str) -> SourceCard:
    raw = (citekey or "").strip()
    for card in load_source_cards(paths):
        if raw in {card.citekey, card.slug, f"papers/{card.slug}.md"}:
            return card
    raise ValueError(f"No paper card found for citekey or slug: {citekey}")


def discover_seed(
    vault: Path | str,
    *,
    citekey: str,
    sources: list[ProviderName],
    limit: int = 20,
    refresh: bool = False,
) -> dict[str, Any]:
    from .importer import initialize_vault

    paths = initialize_vault(vault, rebuild=False)
    card = _find_seed_card(paths, citekey)
    store_results = []
    errors: list[dict[str, str]] = []
    for source in sources:
        try:
            papers = get_adapter(source).neighborhood(
                title=card.title,
                doi=card.doi,
                limit=limit,
                cache_dir=paths.raw_discovery,
                refresh=refresh,
            )
        except DiscoveryProviderError as exc:
            errors.append({"source": source, "error": str(exc)})
            continue
        store_results.append(
            _store_candidate_papers(
                paths,
                papers,
                seed_citekey=card.citekey or card.slug,
                query=None,
                project=(card.linked_projects[0] if card.linked_projects else None),
            )
        )
    return _discovery_summary(
        paths,
        mode="seed",
        sources=sources,
        stored=_combine_store_results(store_results),
        errors=errors,
    )


def _search_text_from_query(paths: VaultPaths, query_slug: str) -> tuple[str, str, str | None]:
    from .queries import _load_query, _query_slug

    query, _path, body = _load_query(paths, _query_slug(query_slug))
    scope = re.sub(r"\s+", " ", clean_markdown_text(body))
    text = " ".join(
        item
        for item in [
            str(query.get("question") or ""),
            str(query.get("project") or ""),
            scope[:500],
        ]
        if item
    )
    return text, _query_ref(_query_slug(query_slug)) or "", str(query.get("project") or "") or None


def discover_query(
    vault: Path | str,
    *,
    query_slug: str,
    sources: list[ProviderName],
    limit: int = 20,
    refresh: bool = False,
) -> dict[str, Any]:
    from .importer import initialize_vault
    from .queries import _query_slug

    paths = initialize_vault(vault, rebuild=False)
    text, query_ref, project = _search_text_from_query(paths, query_slug)
    store_results = []
    errors: list[dict[str, str]] = []
    for source in sources:
        try:
            papers = get_adapter(source).search(
                text,
                limit=limit,
                cache_dir=paths.raw_discovery,
                refresh=refresh,
            )
        except DiscoveryProviderError as exc:
            errors.append({"source": source, "error": str(exc)})
            continue
        store_results.append(
            _store_candidate_papers(
                paths,
                papers,
                query=query_ref,
                project=project,
            )
        )
    summary = _discovery_summary(
        paths,
        mode="query",
        sources=sources,
        stored=_combine_store_results(store_results),
        errors=errors,
    )
    summary["query"] = query_ref
    summary["query_slug"] = _query_slug(query_slug)
    return summary


def _search_text_from_project(paths: VaultPaths, project_slug: str) -> tuple[str, str]:
    from .projects import _load_project, _project_slug

    project, _path, body = _load_project(paths, _project_slug(project_slug))
    scope = re.sub(r"\s+", " ", clean_markdown_text(body))
    title = str(project.get("title") or project.get("slug") or project_slug)
    return f"{title} {scope[:700]}".strip(), str(project.get("slug") or _project_slug(project_slug))


def discover_project(
    vault: Path | str,
    *,
    project: str,
    sources: list[ProviderName],
    limit: int = 20,
    refresh: bool = False,
) -> dict[str, Any]:
    from .importer import initialize_vault

    paths = initialize_vault(vault, rebuild=False)
    text, project_slug = _search_text_from_project(paths, project)
    store_results = []
    errors: list[dict[str, str]] = []
    for source in sources:
        try:
            papers = get_adapter(source).search(
                text,
                limit=limit,
                cache_dir=paths.raw_discovery,
                refresh=refresh,
            )
        except DiscoveryProviderError as exc:
            errors.append({"source": source, "error": str(exc)})
            continue
        store_results.append(
            _store_candidate_papers(
                paths,
                papers,
                query=None,
                project=project_slug,
            )
        )
    summary = _discovery_summary(
        paths,
        mode="project",
        sources=sources,
        stored=_combine_store_results(store_results),
        errors=errors,
    )
    summary["project"] = project_slug
    return summary


def list_discovery_candidates(vault: Path | str) -> dict[str, Any]:
    from .importer import initialize_vault

    paths = initialize_vault(vault, rebuild=False)
    candidates = load_discovery_candidates(paths)
    status_counts = Counter(candidate.status for candidate in candidates)
    return {
        "vault": str(paths.vault),
        "count": len(candidates),
        "counts": dict(sorted(status_counts.items())),
        "candidates": _candidate_rows(paths, candidates),
    }


def update_candidate_status(
    vault: Path | str,
    candidate_id: str,
    *,
    status: DiscoveryStatus,
    linked_run: str | None = None,
) -> dict[str, Any]:
    from .importer import initialize_vault

    paths = initialize_vault(vault, rebuild=False)
    path = _candidate_path(paths, candidate_id)
    if not path.exists():
        raise ValueError(f"Discovery candidate does not exist: {candidate_id}")
    candidate = DiscoveryCandidate.model_validate(_read_yaml_mapping(path))
    previous = candidate.status
    candidate.status = status
    if linked_run is not None:
        candidate.linked_run = linked_run
    _write_candidate(paths, candidate)
    _refresh_discovery_dashboards(paths)
    return {
        "vault": str(paths.vault),
        "id": candidate.id,
        "candidate": _candidate_ref(paths, candidate),
        "previous_status": previous,
        "status": candidate.status,
    }


def select_candidate(vault: Path | str, candidate_id: str) -> dict[str, Any]:
    return update_candidate_status(vault, candidate_id, status="selected")


def reject_candidate(vault: Path | str, candidate_id: str) -> dict[str, Any]:
    return update_candidate_status(vault, candidate_id, status="rejected")


def _candidate_id_from_ref(candidate_ref: str) -> str:
    raw = (candidate_ref or "").strip().strip("/")
    if raw.startswith("tasks/discovery-candidates/"):
        return Path(raw).stem
    if raw.endswith(".yaml"):
        return Path(raw).stem
    return raw


def mark_candidates_linked_run(
    vault: Path | str,
    candidate_refs: list[str],
    *,
    run_id: str,
) -> int:
    from .importer import initialize_vault

    paths = initialize_vault(vault, rebuild=False)
    changed = 0
    for candidate_ref in candidate_refs:
        candidate_id = _candidate_id_from_ref(candidate_ref)
        path = _candidate_path(paths, candidate_id)
        if not path.exists():
            continue
        candidate = DiscoveryCandidate.model_validate(_read_yaml_mapping(path))
        if candidate.status == "imported" and candidate.linked_run == run_id:
            continue
        candidate.status = "imported"
        candidate.linked_run = run_id
        _write_candidate(paths, candidate)
        changed += 1
    if changed:
        _refresh_discovery_dashboards(paths)
    return changed


def _candidate_matches_query(candidate: DiscoveryCandidate, query_slug: str) -> bool:
    query_ref = _query_ref(query_slug)
    return candidate.query in {query_slug, query_ref, Path(query_ref or "").stem}


def discovery_to_labs_prompts(
    vault: Path | str,
    *,
    query_slug: str,
    limit: int = 12,
) -> dict[str, Any]:
    from .importer import initialize_vault
    from .labs_prompts import SeedCandidate, generate_prompt_pack_from_seed_candidates
    from .queries import _query_slug

    paths = initialize_vault(vault, rebuild=False)
    normalized_query = _query_slug(query_slug)
    candidates = [
        candidate
        for candidate in load_discovery_candidates(paths)
        if _candidate_matches_query(candidate, normalized_query)
        and candidate.status in {"candidate", "selected"}
    ]
    candidates.sort(
        key=lambda item: (
            0 if item.status == "selected" else 1,
            -(item.cited_by_count or 0),
            item.title.casefold(),
        )
    )
    selected = candidates[:limit]
    if not selected:
        raise ValueError(
            f"No active discovery candidates found for query: queries/{normalized_query}.md"
        )
    seeds = [
        SeedCandidate(
            title=candidate.title,
            year=candidate.year,
            authors=tuple(candidate.authors),
            venue=candidate.venue,
            doi=candidate.doi,
            url=candidate.url,
            source="discovery",
            citation_count=candidate.cited_by_count,
            reason=candidate.reason,
        )
        for candidate in selected
    ]
    candidate_refs = [_candidate_ref(paths, candidate) for candidate in selected]
    prompt_summary = generate_prompt_pack_from_seed_candidates(
        paths.vault,
        query=normalized_query,
        seed_candidates=seeds,
        candidate_refs=candidate_refs,
    )
    for candidate in selected:
        candidate.linked_prompt_pack = str(prompt_summary["prompt_pack"])
        _write_candidate(paths, candidate)
    _refresh_discovery_dashboards(paths)
    return {
        **prompt_summary,
        "candidate_count": len(selected),
        "candidates": _candidate_rows(paths, selected),
    }


def _resolve_query_path(paths: VaultPaths, value: str | None) -> Path | None:
    if not value:
        return None
    raw = value.strip().strip("/")
    if raw.startswith("queries/"):
        path = paths.vault / raw
    else:
        path = paths.queries / (raw if raw.endswith(".md") else f"{raw}.md")
    return path


def _resolve_project_path(paths: VaultPaths, value: str | None) -> Path | None:
    if not value:
        return None
    raw = value.strip().strip("/")
    if raw.startswith("projects/"):
        path = paths.vault / raw
        return path if path.name == "index.md" else path / "index.md"
    return paths.projects / raw / "index.md"


def doctor_discovery(vault: Path | str) -> dict[str, Any]:
    paths = VaultPaths.from_root(vault)
    rows: list[dict[str, Any]] = []
    issue_counts = Counter(
        {
            "invalid_yaml": 0,
            "invalid_schema": 0,
            "invalid_status": 0,
            "missing_query": 0,
            "missing_project": 0,
            "missing_prompt_pack": 0,
            "missing_run": 0,
            "matches_imported_card": 0,
        }
    )
    cards = load_source_cards(paths)
    run_ids = {run.slug for run in load_run_records(paths)}
    for path in sorted(paths.discovery_candidates.glob("*.yaml")):
        row: dict[str, Any] = {
            "path": ensure_relative(path, paths.vault),
            "ok": True,
            "issues": [],
        }
        try:
            data = _read_yaml_mapping(path)
        except (OSError, yaml.YAMLError, ValueError) as exc:
            row["ok"] = False
            row["issues"].append(f"invalid YAML: {exc}")
            issue_counts["invalid_yaml"] += 1
            rows.append(row)
            continue
        try:
            candidate = DiscoveryCandidate.model_validate(data)
        except ValueError as exc:
            row["ok"] = False
            row["issues"].append(f"invalid schema: {exc}")
            issue_counts["invalid_schema"] += 1
            rows.append(row)
            continue
        row.update({"id": candidate.id, "status": candidate.status, "title": candidate.title})
        raw_status = str(data.get("status") or "")
        if raw_status not in DISCOVERY_STATUSES:
            row["issues"].append(f"invalid status: {raw_status or 'missing'}")
            issue_counts["invalid_status"] += 1
        query_path = _resolve_query_path(paths, candidate.query)
        if query_path is not None and not query_path.exists():
            row["issues"].append(f"missing query: {candidate.query}")
            issue_counts["missing_query"] += 1
        project_path = _resolve_project_path(paths, candidate.project)
        if project_path is not None and not project_path.exists():
            row["issues"].append(f"missing project: {candidate.project}")
            issue_counts["missing_project"] += 1
        prompt_pack_missing = (
            candidate.linked_prompt_pack
            and not (paths.vault / candidate.linked_prompt_pack).exists()
        )
        if prompt_pack_missing:
            row["issues"].append(f"missing prompt pack: {candidate.linked_prompt_pack}")
            issue_counts["missing_prompt_pack"] += 1
        if candidate.linked_run and candidate.linked_run not in run_ids:
            row["issues"].append(f"missing run: {candidate.linked_run}")
            issue_counts["missing_run"] += 1
        if candidate.status != "imported" and _candidate_matches_card(candidate, cards):
            row["issues"].append("candidate appears to match an imported paper card")
            issue_counts["matches_imported_card"] += 1
        row["ok"] = not row["issues"]
        rows.append(row)
    status_counts = discovery_counts(paths)
    raw_cache_files = (
        len(list(paths.raw_discovery.rglob("*.json"))) if paths.raw_discovery.exists() else 0
    )
    return {
        "vault": str(paths.vault),
        "ok": not any(issue_counts.values()),
        "issue_counts": dict(issue_counts),
        "counts": status_counts,
        "raw_cache_files": raw_cache_files,
        "candidates": rows,
    }
