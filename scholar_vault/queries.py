from __future__ import annotations

import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from .models import RunRecord, SourceCard
from .sources import (
    VaultPaths,
    dump_frontmatter,
    ensure_relative,
    load_run_records,
    load_source_cards,
    read_frontmatter_markdown,
    slugify_text,
    write_text,
    write_yaml,
)

QUERY_STATUSES = {"open", "active", "paused", "answered", "archived"}
QUERY_LIST_FIELDS = (
    "linked_runs",
    "linked_papers",
    "linked_syntheses",
    "linked_concepts",
    "scholar_labs_prompt_pack",
    "unread_linked_papers",
    "uncompiled_linked_papers",
)


def _now_iso() -> str:
    return datetime.now().astimezone().replace(microsecond=0).isoformat()


def _as_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _query_slug(value: str) -> str:
    raw = (value or "").strip().strip("/")
    if raw.startswith("queries/"):
        raw = raw.removeprefix("queries/").strip("/")
    if raw.endswith(".md"):
        raw = raw[: -len(".md")]
    path = Path(raw)
    if (
        not raw
        or path.is_absolute()
        or len(path.parts) != 1
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError("Query slug must be a single safe path segment.")
    return slugify_text(raw, max_length=80)


def _slug_from_question(question: str) -> str:
    return slugify_text(question, max_length=80)


def _query_path(paths: VaultPaths, slug: str) -> Path:
    return paths.queries / f"{slug}.md"


def _query_ref(slug: str) -> str:
    return f"queries/{slug}.md"


def _query_ref_exists(paths: VaultPaths, value: str) -> str | None:
    raw = (value or "").strip().strip("<>").strip()
    if raw.startswith("[[") and raw.endswith("]]"):
        raw = raw[2:-2].split("|", 1)[0].split("#", 1)[0].strip()
    if raw.startswith("queries/"):
        ref = raw if raw.endswith(".md") else f"{raw}.md"
    else:
        try:
            ref = _query_ref(_query_slug(raw))
        except ValueError:
            return None
    return ref if (paths.vault / ref).exists() else None


def _query_defaults(
    slug: str,
    question: str,
    *,
    project: str | None = None,
    priority: str = "normal",
) -> dict[str, Any]:
    now = _now_iso()
    return {
        "type": "research_query",
        "status": "open",
        "project": project or "",
        "question": question,
        "created": now,
        "updated": now,
        "linked_runs": [],
        "linked_papers": [],
        "linked_syntheses": [],
        "linked_concepts": [],
        "scholar_labs_prompt_pack": [],
        "priority": priority,
        "review_status": "unreviewed",
        "unread_linked_papers": [],
        "uncompiled_linked_papers": [],
    }


def _normalize_query_frontmatter(
    frontmatter: dict[str, Any],
    slug: str,
    *,
    question: str | None = None,
    project: str | None = None,
    priority: str | None = None,
) -> dict[str, Any]:
    query = _query_defaults(
        slug,
        question or str(frontmatter.get("question") or slug.replace("-", " ").title()),
        project=project if project is not None else str(frontmatter.get("project") or ""),
        priority=priority if priority is not None else str(frontmatter.get("priority") or "normal"),
    )
    query.update(frontmatter)
    query["type"] = "research_query"
    query["question"] = str(query.get("question") or question or slug.replace("-", " ").title())
    query["status"] = str(query.get("status") or "open")
    query["project"] = str(query.get("project") or "")
    query["created"] = str(query.get("created") or _now_iso())
    query["updated"] = str(query.get("updated") or query["created"])
    query["priority"] = str(query.get("priority") or "normal")
    query["review_status"] = str(query.get("review_status") or "unreviewed")
    for field in QUERY_LIST_FIELDS:
        query[field] = _as_string_list(query.get(field))
    return query


def _render_query_markdown(query: dict[str, Any]) -> str:
    frontmatter = dump_frontmatter(query).strip()
    question = query["question"]
    lines = [
        f"# {question}",
        "",
        "## Workbench",
        "![[bases/queries.base#Query outputs]]",
        "![[bases/queries.base#Queries needing Scholar Labs]]",
        "![[bases/queries.base#Queries with uncompiled linked papers]]",
        "![[bases/papers.base#Needs reading]]",
        "![[bases/scholar-labs-workbench.base#Prompt drafts]]",
        "",
        "## Linked runs",
        "No linked Scholar Labs runs yet.",
        "",
        "## Linked papers",
        "No linked papers yet.",
        "",
        "## Linked syntheses",
        "No linked syntheses yet.",
        "",
        "## Scholar Labs prompt pack",
        "Draft Scholar Labs prompts here before export/import.",
        "",
        "## Notes",
        "Use this note for the query-specific trail of decisions and next steps.",
        "",
    ]
    return f"---\n{frontmatter}\n---\n\n" + "\n".join(lines)


def _write_query_preserving_body(path: Path, query: dict[str, Any], body: str) -> None:
    write_text(path, f"---\n{dump_frontmatter(query).strip()}\n---\n\n{body.strip()}\n")


def _replace_refs_in_value(value: Any, replacements: dict[str, str]) -> Any:
    if isinstance(value, str):
        return replacements.get(value, value)
    if isinstance(value, list):
        return [_replace_refs_in_value(item, replacements) for item in value]
    if isinstance(value, dict):
        return {key: _replace_refs_in_value(item, replacements) for key, item in value.items()}
    return value


def _replace_refs_in_text(text: str, replacements: dict[str, str]) -> str:
    updated = text
    for old, new in sorted(replacements.items(), key=lambda item: len(item[0]), reverse=True):
        if "/" not in old and not old.endswith(".md"):
            continue
        updated = updated.replace(old, new)
    return updated


def _write_frontmatter_file(path: Path, frontmatter: dict[str, Any], body: str) -> None:
    write_text(path, f"---\n{dump_frontmatter(frontmatter).strip()}\n---\n\n{body.strip()}\n")


def _sync_paper_query_paths_frontmatter(frontmatter: dict[str, Any]) -> bool:
    linked_queries = _as_string_list(frontmatter.get("linked_queries"))
    linked_query_paths = _as_string_list(frontmatter.get("linked_query_paths"))
    normalized_query_paths = [
        query if query.startswith("queries/") and query.endswith(".md") else query
        for query in linked_queries
    ]
    merged_paths = sorted(
        set([*linked_query_paths, *normalized_query_paths]),
        key=str.casefold,
    )
    changed = False
    if linked_queries != frontmatter.get("linked_queries"):
        frontmatter["linked_queries"] = linked_queries
        changed = True
    if merged_paths != linked_query_paths:
        frontmatter["linked_query_paths"] = merged_paths
        changed = True
    return changed


def _refresh_query_navigation(paths: VaultPaths) -> dict[str, Any]:
    from .bases import rebuild_bases
    from .labs_prompts import write_prompt_packs_index
    from .self_improvement import write_self_improvement_dashboard

    return {
        "bases": rebuild_bases(paths.vault),
        "prompt_packs_index": write_prompt_packs_index(paths.vault),
        "self_improvement_dashboard": write_self_improvement_dashboard(paths.vault),
    }


def _load_query(paths: VaultPaths, slug: str) -> tuple[dict[str, Any], Path, str]:
    normalized_slug = _query_slug(slug)
    path = _query_path(paths, normalized_slug)
    if not path.exists():
        raise ValueError(f"Query does not exist: queries/{normalized_slug}.md")
    frontmatter, body = read_frontmatter_markdown(path)
    query = _normalize_query_frontmatter(frontmatter, normalized_slug)
    return query, path, body


def _query_rows(paths: VaultPaths) -> list[dict[str, Any]]:
    if not paths.queries.exists():
        return []
    rows: list[dict[str, Any]] = []
    for path in sorted(paths.queries.glob("*.md")):
        frontmatter, _ = read_frontmatter_markdown(path)
        query = _normalize_query_frontmatter(frontmatter, path.stem)
        rows.append(
            {
                "slug": path.stem,
                "question": query["question"],
                "status": query["status"],
                "project": query["project"],
                "priority": query["priority"],
                "review_status": query["review_status"],
                "path": ensure_relative(path, paths.vault),
                "linked_runs": len(query["linked_runs"]),
                "linked_papers": len(query["linked_papers"]),
                "linked_syntheses": len(query["linked_syntheses"]),
                "unread_linked_papers": len(query["unread_linked_papers"]),
            }
        )
    return rows


def query_list(vault: Path | str) -> dict[str, Any]:
    from .importer import initialize_vault

    paths = initialize_vault(vault, rebuild=False)
    rows = _query_rows(paths)
    return {"vault": str(paths.vault), "count": len(rows), "queries": rows}


def query_create(
    vault: Path | str,
    question: str,
    *,
    project: str | None = None,
    slug: str | None = None,
    priority: str = "normal",
) -> dict[str, Any]:
    from .bases import rebuild_bases
    from .importer import initialize_vault

    cleaned_question = re.sub(r"\s+", " ", question or "").strip()
    if not cleaned_question:
        raise ValueError("Question text must not be empty.")
    normalized_slug = _query_slug(slug or _slug_from_question(cleaned_question))
    paths = initialize_vault(vault, rebuild=False)
    path = _query_path(paths, normalized_slug)
    state = "unchanged"
    if path.exists():
        frontmatter, body = read_frontmatter_markdown(path)
        query = _normalize_query_frontmatter(
            frontmatter,
            normalized_slug,
            question=cleaned_question,
        )
        if query["question"] != cleaned_question:
            raise ValueError(
                f"Query already exists with a different question: queries/{normalized_slug}.md"
            )
        before = dump_frontmatter(frontmatter)
        normalized = dump_frontmatter(query)
        if before != normalized:
            _write_query_preserving_body(path, query, body)
            state = "updated"
    else:
        query = _query_defaults(
            normalized_slug,
            cleaned_question,
            project=project,
            priority=priority,
        )
        write_text(path, _render_query_markdown(query))
        state = "created"
    bases_summary = rebuild_bases(paths.vault)
    return {
        "vault": str(paths.vault),
        "query": ensure_relative(path, paths.vault),
        "slug": normalized_slug,
        "question": cleaned_question,
        "state": state,
        "bases": bases_summary,
    }


def query_show(vault: Path | str, slug: str) -> dict[str, Any]:
    from .importer import initialize_vault

    paths = initialize_vault(vault, rebuild=False)
    query, path, body = _load_query(paths, slug)
    return {
        "vault": str(paths.vault),
        "query": ensure_relative(path, paths.vault),
        "slug": path.stem,
        "frontmatter": query,
        "body": body.rstrip(),
    }


def _append_section_item(body: str, heading: str, bullet: str) -> str:
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
        if not line.strip().casefold().startswith("no linked")
    ]
    kept_lines.append(bullet)
    replacement = before + "\n" + "\n".join(kept_lines).strip() + "\n"
    return replacement + after


def _resolve_run_ref(paths: VaultPaths, run_id: str) -> tuple[str, RunRecord]:
    normalized = (run_id or "").strip().strip("/")
    for run in load_run_records(paths):
        if run.slug == normalized:
            return run.slug, run
    raise ValueError(f"No run found for run id: {run_id}")


def _paper_ref(card: SourceCard) -> str:
    return f"papers/{card.slug}.md"


def _resolve_paper_ref(paths: VaultPaths, citekey: str) -> tuple[str, SourceCard]:
    normalized = (citekey or "").strip().strip("/")
    stem = Path(normalized).stem
    for card in load_source_cards(paths):
        candidates = {card.slug, _paper_ref(card)}
        if card.citekey:
            candidates.add(card.citekey)
        if normalized in candidates or stem == card.slug:
            return _paper_ref(card), card
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


def _linked_paper_lookup(paths: VaultPaths) -> dict[str, SourceCard]:
    cards = load_source_cards(paths)
    lookup: dict[str, SourceCard] = {}
    for card in cards:
        lookup[_paper_ref(card)] = card
        lookup[card.slug] = card
        if card.citekey:
            lookup[card.citekey] = card
    return lookup


def _refresh_query_unread_papers(paths: VaultPaths, query: dict[str, Any]) -> bool:
    lookup = _linked_paper_lookup(paths)
    unread = []
    uncompiled = []
    for ref in query.get("linked_papers") or []:
        card = lookup.get(ref) or lookup.get(Path(ref).stem)
        if card and card.reading_status == "unread":
            unread.append(_paper_ref(card))
        if card and card.compiled_status in {"uncompiled", "draft", "stale"}:
            uncompiled.append(_paper_ref(card))
    unread = sorted(set(unread), key=str.casefold)
    uncompiled = sorted(set(uncompiled), key=str.casefold)
    changed = False
    if unread != query.get("unread_linked_papers"):
        query["unread_linked_papers"] = unread
        changed = True
    if uncompiled != query.get("uncompiled_linked_papers"):
        query["uncompiled_linked_papers"] = uncompiled
        changed = True
    return changed


def refresh_query_derived_fields(paths: VaultPaths) -> int:
    refreshed = 0
    if not paths.queries.exists():
        return refreshed
    for query_path in sorted(paths.queries.glob("*.md")):
        frontmatter, body = read_frontmatter_markdown(query_path)
        query = _normalize_query_frontmatter(frontmatter, query_path.stem)
        if _refresh_query_unread_papers(paths, query):
            _write_query_preserving_body(query_path, query, body)
            refreshed += 1
    return refreshed


def _update_query_link(
    vault: Path | str,
    slug: str,
    *,
    field: str,
    ref: str,
    section: str,
    bullet: str,
) -> dict[str, Any]:
    from .bases import rebuild_bases
    from .importer import initialize_vault

    paths = initialize_vault(vault, rebuild=False)
    query, path, body = _load_query(paths, slug)
    values = list(query.get(field) or [])
    changed = False
    if ref not in values:
        values.append(ref)
        query[field] = sorted(values, key=str.casefold)
        query["updated"] = _now_iso()
        body = _append_section_item(body, section, bullet)
        changed = True
    if field == "linked_papers":
        changed = _refresh_query_unread_papers(paths, query) or changed
    if changed:
        _write_query_preserving_body(path, query, body)
    bases_summary = rebuild_bases(paths.vault)
    return {
        "vault": str(paths.vault),
        "query": ensure_relative(path, paths.vault),
        "field": field,
        "ref": ref,
        "changed": changed,
        "bases": bases_summary,
    }


def _link_query_on_paper(paths: VaultPaths, paper_ref: str, query_ref: str) -> bool:
    paper_path = paths.vault / paper_ref
    frontmatter, body = read_frontmatter_markdown(paper_path)
    linked = _as_string_list(frontmatter.get("linked_queries"))
    changed = False
    if query_ref not in linked:
        linked.append(query_ref)
        frontmatter["linked_queries"] = sorted(linked, key=str.casefold)
        changed = True
    changed = _sync_paper_query_paths_frontmatter(frontmatter) or changed
    if not changed:
        return False
    write_text(
        paper_path,
        f"---\n{dump_frontmatter(frontmatter).strip()}\n---\n\n{body.strip()}\n",
    )
    return True


def query_link_run(vault: Path | str, slug: str, run_id: str) -> dict[str, Any]:
    from .importer import initialize_vault

    paths = initialize_vault(vault, rebuild=False)
    ref, _ = _resolve_run_ref(paths, run_id)
    return _update_query_link(
        paths.vault,
        slug,
        field="linked_runs",
        ref=ref,
        section="Linked runs",
        bullet=f"- Run: `{ref}`",
    )


def query_link_paper(vault: Path | str, slug: str, citekey: str) -> dict[str, Any]:
    from .importer import initialize_vault

    paths = initialize_vault(vault, rebuild=False)
    _load_query(paths, slug)
    paper_ref, card = _resolve_paper_ref(paths, citekey)
    query_ref = _query_ref(_query_slug(slug))
    paper_changed = _link_query_on_paper(paths, paper_ref, query_ref)
    summary = _update_query_link(
        paths.vault,
        slug,
        field="linked_papers",
        ref=paper_ref,
        section="Linked papers",
        bullet=f"- [{card.title}](../{paper_ref})",
    )
    summary["paper_changed"] = paper_changed
    return summary


def query_link_synthesis(vault: Path | str, slug: str, path_or_slug: str) -> dict[str, Any]:
    from .importer import initialize_vault

    paths = initialize_vault(vault, rebuild=False)
    ref = _normalize_artifact_ref(paths, "syntheses", path_or_slug)
    return _update_query_link(
        paths.vault,
        slug,
        field="linked_syntheses",
        ref=ref,
        section="Linked syntheses",
        bullet=f"- [{ref}](../{ref})",
    )


def query_status(vault: Path | str, slug: str) -> dict[str, Any]:
    from .importer import initialize_vault

    paths = initialize_vault(vault, rebuild=False)
    query, path, _ = _load_query(paths, slug)
    paper_lookup = _linked_paper_lookup(paths)
    missing_papers = [
        ref
        for ref in query.get("linked_papers") or []
        if ref not in paper_lookup and Path(ref).stem not in paper_lookup
    ]
    unread_papers = []
    uncompiled_papers = []
    for ref in query.get("linked_papers") or []:
        card = paper_lookup.get(ref) or paper_lookup.get(Path(ref).stem)
        if card and card.reading_status == "unread":
            unread_papers.append(_paper_ref(card))
        if card and card.compiled_status in {"uncompiled", "draft", "stale"}:
            uncompiled_papers.append(_paper_ref(card))
    run_ids = {run.slug for run in load_run_records(paths)}
    missing_runs = [ref for ref in query.get("linked_runs") or [] if ref not in run_ids]
    missing_syntheses = [
        ref for ref in query.get("linked_syntheses") or [] if not (paths.vault / ref).exists()
    ]
    issue_counts = {
        "missing_papers": len(missing_papers),
        "unread_linked_papers": len(unread_papers),
        "uncompiled_linked_papers": len(uncompiled_papers),
        "missing_runs": len(missing_runs),
        "missing_syntheses": len(missing_syntheses),
        "needs_scholar_labs": int(
            query["status"] in {"open", "active"}
            and not query["linked_runs"]
            and not query["scholar_labs_prompt_pack"]
        ),
    }
    return {
        "vault": str(paths.vault),
        "query": ensure_relative(path, paths.vault),
        "slug": path.stem,
        "ok": not any(
            issue_counts[key]
            for key in ["missing_papers", "missing_runs", "missing_syntheses"]
        ),
        "counts": {
            "linked_runs": len(query["linked_runs"]),
            "linked_papers": len(query["linked_papers"]),
            "linked_syntheses": len(query["linked_syntheses"]),
            "unread_linked_papers": len(unread_papers),
            "uncompiled_linked_papers": len(uncompiled_papers),
        },
        "issue_counts": issue_counts,
        "issues": {
            "missing_papers": missing_papers,
            "unread_linked_papers": unread_papers,
            "uncompiled_linked_papers": uncompiled_papers,
            "missing_runs": missing_runs,
            "missing_syntheses": missing_syntheses,
        },
        "frontmatter": query,
    }


def _query_prompt_pack_path_replacements(
    paths: VaultPaths,
    old_slug: str,
    new_slug: str,
) -> dict[str, str]:
    old_dir = paths.queries / old_slug
    new_dir = paths.queries / new_slug
    replacements: dict[str, str] = {}
    if old_dir.exists():
        if new_dir.exists():
            raise ValueError(f"Query support directory already exists: queries/{new_slug}/")
        new_dir.parent.mkdir(parents=True, exist_ok=True)
        old_dir.rename(new_dir)
    prompt_dir = new_dir / "prompt-packs"
    if not prompt_dir.exists():
        return replacements
    prefix = f"query-{old_slug}-"
    new_prefix = f"query-{new_slug}-"
    for path in sorted(prompt_dir.glob("*.md")):
        old_ref = f"queries/{old_slug}/prompt-packs/{path.name}"
        final_path = path
        if path.name.startswith(prefix):
            final_path = path.with_name(new_prefix + path.name[len(prefix) :])
            if final_path.exists():
                final_ref = ensure_relative(final_path, paths.vault)
                raise ValueError(
                    f"Prompt-pack destination already exists: {final_ref}"
                )
            path.rename(final_path)
        replacements[old_ref] = ensure_relative(final_path, paths.vault)
    return replacements


def _prompt_pack_paths(paths: VaultPaths) -> list[Path]:
    paths_to_scan = [paths.tasks / "scholar-labs-prompts"]
    if paths.queries.exists():
        paths_to_scan.extend(sorted(paths.queries.glob("*/prompt-packs")))
    return sorted(
        {
            path
            for folder in paths_to_scan
            if folder.exists()
            for path in folder.glob("*.md")
        }
    )


def _rewrite_markdown_frontmatter_refs(
    path: Path,
    replacements: dict[str, str],
    *,
    sync_paper_query_paths: bool = False,
) -> bool:
    frontmatter, body = read_frontmatter_markdown(path)
    updated_frontmatter = _replace_refs_in_value(frontmatter, replacements)
    if sync_paper_query_paths:
        _sync_paper_query_paths_frontmatter(updated_frontmatter)
    updated_body = _replace_refs_in_text(body, replacements)
    if updated_frontmatter == frontmatter and updated_body == body:
        return False
    _write_frontmatter_file(path, updated_frontmatter, updated_body)
    return True


def _rewrite_yaml_refs(path: Path, replacements: dict[str, str]) -> tuple[bool, dict[str, Any]]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return False, {}
    updated = _replace_refs_in_value(data, replacements)
    if updated == data:
        return False, data
    write_yaml(path, updated)
    return True, updated


def _rewrite_query_references(
    paths: VaultPaths,
    replacements: dict[str, str],
) -> dict[str, int]:
    counts = {
        "papers": 0,
        "prompt_packs": 0,
        "runs": 0,
        "queue_items": 0,
        "discovery_candidates": 0,
        "feedback": 0,
    }
    for paper_path in sorted(paths.papers.glob("*.md")):
        counts["papers"] += int(
            _rewrite_markdown_frontmatter_refs(
                paper_path,
                replacements,
                sync_paper_query_paths=True,
            )
        )
    for prompt_path in _prompt_pack_paths(paths):
        counts["prompt_packs"] += int(_rewrite_markdown_frontmatter_refs(prompt_path, replacements))
    for run_path in sorted(paths.runs.glob("*/index.yaml")):
        changed, data = _rewrite_yaml_refs(run_path, replacements)
        if not changed:
            continue
        counts["runs"] += 1
        try:
            from .importer import _write_run

            _write_run(paths, RunRecord.model_validate(data), load_source_cards(paths))
        except Exception:
            # The YAML was still repaired; leave rendering diagnostics to run doctors.
            pass
    for queue_path in sorted(paths.task_queue.glob("*.yaml")):
        counts["queue_items"] += int(_rewrite_yaml_refs(queue_path, replacements)[0])
    for candidate_path in sorted(paths.discovery_candidates.glob("*.yaml")):
        counts["discovery_candidates"] += int(_rewrite_yaml_refs(candidate_path, replacements)[0])
    for feedback_path in sorted(paths.feedback_ratings.glob("*.yaml")):
        counts["feedback"] += int(_rewrite_yaml_refs(feedback_path, replacements)[0])
    return counts


def query_rename(
    vault: Path | str,
    slug: str,
    new_slug: str,
) -> dict[str, Any]:
    from .importer import initialize_vault

    paths = initialize_vault(vault, rebuild=False)
    old_slug = _query_slug(slug)
    normalized_new_slug = _query_slug(new_slug)
    if old_slug == normalized_new_slug:
        raise ValueError("New query slug must differ from the old slug.")
    query, old_path, body = _load_query(paths, old_slug)
    new_path = _query_path(paths, normalized_new_slug)
    if new_path.exists():
        raise ValueError(f"Query already exists: queries/{normalized_new_slug}.md")

    prompt_replacements = _query_prompt_pack_path_replacements(
        paths,
        old_slug,
        normalized_new_slug,
    )
    path_replacements = {
        _query_ref(old_slug): _query_ref(normalized_new_slug),
        **prompt_replacements,
    }
    data_replacements = {**path_replacements, old_slug: _query_ref(normalized_new_slug)}
    query = _replace_refs_in_value(query, path_replacements)
    query["updated"] = _now_iso()
    updated_body = _replace_refs_in_text(body, path_replacements)
    _write_query_preserving_body(new_path, query, updated_body)
    old_path.unlink()

    reference_counts = _rewrite_query_references(paths, data_replacements)
    refresh = _refresh_query_navigation(paths)
    return {
        "vault": str(paths.vault),
        "previous_query": _query_ref(old_slug),
        "query": ensure_relative(new_path, paths.vault),
        "previous_slug": old_slug,
        "slug": normalized_new_slug,
        "prompt_pack_paths_updated": len(prompt_replacements),
        "references_updated": reference_counts,
        "refresh": refresh,
    }


def query_archive(
    vault: Path | str,
    slug: str,
    *,
    notes: str = "",
) -> dict[str, Any]:
    from .importer import initialize_vault

    paths = initialize_vault(vault, rebuild=False)
    query, path, body = _load_query(paths, slug)
    previous_status = query["status"]
    changed = previous_status != "archived"
    query["status"] = "archived"
    query["updated"] = _now_iso()
    if notes.strip():
        body = _append_section_item(body, "Notes", f"- Archived: {notes.strip()}")
        changed = True
    if changed:
        _write_query_preserving_body(path, query, body)
    refresh = _refresh_query_navigation(paths)
    return {
        "vault": str(paths.vault),
        "query": ensure_relative(path, paths.vault),
        "slug": path.stem,
        "previous_status": previous_status,
        "status": "archived",
        "changed": changed,
        "refresh": refresh,
    }


def query_doctor(vault: Path | str, *, fix: bool = False) -> dict[str, Any]:
    from .importer import initialize_vault

    paths = initialize_vault(vault, rebuild=False)
    issues: list[dict[str, Any]] = []
    fixes = Counter()
    query_refs = {
        ensure_relative(path, paths.vault)
        for path in sorted(paths.queries.glob("*.md"))
    }

    for query_path in sorted(paths.queries.glob("*.md")):
        query, _, body = _load_query(paths, query_path.stem)
        changed = False
        for paper_ref in _as_string_list(query.get("linked_papers")):
            paper_path = paths.vault / paper_ref
            if not paper_path.exists():
                issues.append(
                    {
                        "kind": "missing linked paper",
                        "query": ensure_relative(query_path, paths.vault),
                        "ref": paper_ref,
                    }
                )
                continue
            paper_frontmatter, paper_body = read_frontmatter_markdown(paper_path)
            paper_changed = _sync_paper_query_paths_frontmatter(paper_frontmatter)
            query_ref = ensure_relative(query_path, paths.vault)
            linked_queries = _as_string_list(paper_frontmatter.get("linked_queries"))
            if query_ref not in linked_queries:
                issues.append(
                    {
                        "kind": "missing paper query backlink",
                        "query": query_ref,
                        "paper": paper_ref,
                    }
                )
                if fix:
                    linked_queries.append(query_ref)
                    paper_frontmatter["linked_queries"] = sorted(linked_queries, key=str.casefold)
                    paper_changed = True
            if fix and paper_changed:
                _write_frontmatter_file(paper_path, paper_frontmatter, paper_body)
                fixes["paper_backlinks"] += 1
        prompt_pack_refs = _as_string_list(query.get("scholar_labs_prompt_pack"))
        existing_pack_refs = [ref for ref in prompt_pack_refs if (paths.vault / ref).exists()]
        if len(existing_pack_refs) != len(prompt_pack_refs):
            issues.append(
                {
                    "kind": "missing query prompt pack",
                    "query": ensure_relative(query_path, paths.vault),
                    "refs": sorted(set(prompt_pack_refs) - set(existing_pack_refs)),
                }
            )
        if fix and existing_pack_refs != prompt_pack_refs:
            query["scholar_labs_prompt_pack"] = existing_pack_refs
            changed = True
        if fix and changed:
            _write_query_preserving_body(query_path, query, body)
            fixes["query_notes"] += 1

    for paper_path in sorted(paths.papers.glob("*.md")):
        frontmatter, body = read_frontmatter_markdown(paper_path)
        linked_queries = _as_string_list(frontmatter.get("linked_queries"))
        normalized = []
        for query_ref in linked_queries:
            resolved = _query_ref_exists(paths, query_ref)
            if resolved is None:
                issues.append(
                    {
                        "kind": "missing paper linked query",
                        "paper": ensure_relative(paper_path, paths.vault),
                        "ref": query_ref,
                    }
                )
                normalized.append(query_ref)
            else:
                normalized.append(resolved)
        if fix:
            frontmatter["linked_queries"] = sorted(set(normalized), key=str.casefold)
            if _sync_paper_query_paths_frontmatter(frontmatter):
                _write_frontmatter_file(paper_path, frontmatter, body)
                fixes["paper_query_paths"] += 1

    for prompt_path in _prompt_pack_paths(paths):
        frontmatter, body = read_frontmatter_markdown(prompt_path)
        query_ref = str(frontmatter.get("query") or "")
        resolved_query_ref = _query_ref_exists(paths, query_ref) if query_ref else None
        if query_ref and resolved_query_ref is None:
            issues.append(
                {
                    "kind": "missing prompt pack query",
                    "prompt_pack": ensure_relative(prompt_path, paths.vault),
                    "query": query_ref,
                }
            )
            continue
        pack_ref = ensure_relative(prompt_path, paths.vault)
        if resolved_query_ref:
            query_path = paths.vault / resolved_query_ref
            query, _, query_body = _load_query(paths, Path(resolved_query_ref).stem)
            packs = _as_string_list(query.get("scholar_labs_prompt_pack"))
            if pack_ref not in packs:
                issues.append(
                    {
                        "kind": "missing query prompt pack backlink",
                        "query": resolved_query_ref,
                        "prompt_pack": pack_ref,
                    }
                )
                if fix:
                    packs.append(pack_ref)
                    query["scholar_labs_prompt_pack"] = sorted(packs, key=str.casefold)
                    _write_query_preserving_body(query_path, query, query_body)
                    fixes["prompt_pack_backlinks"] += 1
            if fix and query_ref != resolved_query_ref:
                frontmatter["query"] = resolved_query_ref
                _write_frontmatter_file(prompt_path, frontmatter, body)
                fixes["prompt_pack_queries"] += 1

    yaml_targets = [
        ("run_query_paths", sorted(paths.runs.glob("*/index.yaml")), "query"),
        ("queue_query_paths", sorted(paths.task_queue.glob("*.yaml")), "query"),
        ("discovery_query_paths", sorted(paths.discovery_candidates.glob("*.yaml")), "query"),
    ]
    for fix_key, files, field in yaml_targets:
        for path in files:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if not isinstance(data, dict) or not data.get(field):
                continue
            ref = str(data[field])
            resolved = _query_ref_exists(paths, ref)
            if resolved is None:
                issues.append(
                    {
                        "kind": f"missing {field}",
                        "path": ensure_relative(path, paths.vault),
                        "ref": ref,
                    }
                )
                continue
            if fix and ref != resolved:
                data[field] = resolved
                write_yaml(path, data)
                fixes[fix_key] += 1
                if fix_key == "run_query_paths":
                    try:
                        from .importer import _write_run

                        _write_run(paths, RunRecord.model_validate(data), load_source_cards(paths))
                    except Exception:
                        pass

    for feedback_path in sorted(paths.feedback_ratings.glob("*.yaml")):
        data = yaml.safe_load(feedback_path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict) or data.get("target_type") != "query":
            continue
        target = str(data.get("target") or "")
        resolved = _query_ref_exists(paths, target)
        if resolved is None:
            issues.append(
                {
                    "kind": "missing feedback query target",
                    "path": ensure_relative(feedback_path, paths.vault),
                    "ref": target,
                }
            )
            continue
        if fix and target != resolved:
            data["target"] = resolved
            write_yaml(feedback_path, data)
            fixes["feedback_query_targets"] += 1

    issue_counts = Counter(str(issue["kind"]) for issue in issues)
    if fix and any(fixes.values()):
        refresh = _refresh_query_navigation(paths)
        post_fix = query_doctor(paths.vault, fix=False)
        post_fix["fix"] = True
        post_fix["fixes"] = dict(sorted(fixes.items()))
        post_fix["issues_before_fix"] = issues
        post_fix["issue_counts_before_fix"] = dict(sorted(issue_counts.items()))
        post_fix["refresh"] = refresh
        return post_fix
    refresh = None
    return {
        "vault": str(paths.vault),
        "ok": not issues,
        "issue_counts": dict(sorted(issue_counts.items())),
        "issues": issues,
        "fix": fix,
        "fixes": dict(sorted(fixes.items())),
        "query_count": len(query_refs),
        "refresh": refresh,
    }
