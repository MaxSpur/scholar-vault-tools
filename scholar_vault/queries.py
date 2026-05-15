from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

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
)

QUERY_STATUSES = {"open", "active", "paused", "answered", "archived"}
QUERY_LIST_FIELDS = (
    "linked_runs",
    "linked_papers",
    "linked_syntheses",
    "linked_concepts",
    "scholar_labs_prompt_pack",
    "unread_linked_papers",
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
    for ref in query.get("linked_papers") or []:
        card = lookup.get(ref) or lookup.get(Path(ref).stem)
        if card and card.reading_status == "unread":
            unread.append(_paper_ref(card))
    unread = sorted(set(unread), key=str.casefold)
    if unread == query.get("unread_linked_papers"):
        return False
    query["unread_linked_papers"] = unread
    return True


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
    if query_ref in linked:
        return False
    linked.append(query_ref)
    frontmatter["linked_queries"] = sorted(linked, key=str.casefold)
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
    for ref in query.get("linked_papers") or []:
        card = paper_lookup.get(ref) or paper_lookup.get(Path(ref).stem)
        if card and card.reading_status == "unread":
            unread_papers.append(_paper_ref(card))
    run_ids = {run.slug for run in load_run_records(paths)}
    missing_runs = [ref for ref in query.get("linked_runs") or [] if ref not in run_ids]
    missing_syntheses = [
        ref for ref in query.get("linked_syntheses") or [] if not (paths.vault / ref).exists()
    ]
    issue_counts = {
        "missing_papers": len(missing_papers),
        "unread_linked_papers": len(unread_papers),
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
        },
        "issue_counts": issue_counts,
        "issues": {
            "missing_papers": missing_papers,
            "unread_linked_papers": unread_papers,
            "missing_runs": missing_runs,
            "missing_syntheses": missing_syntheses,
        },
        "frontmatter": query,
    }
