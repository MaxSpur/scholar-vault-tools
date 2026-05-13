from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

from .models import RunRecord, SourceCard
from .obsidian import (
    ARTIFACT_INDEXES,
    PDF_READING_NOTES_RE,
    _artifact_title,
    _as_string_list,
    _card_has_valid_pdf,
    _card_id,
    _card_ref,
    _collect_research_artifacts,
    _display_path,
    _extract_markdown_targets,
    _markdown_files,
    _resolve_markdown_target,
)
from .render import (
    render_artifact_index,
    render_llms_full,
    render_llms_txt,
    render_project_map_markdown,
    render_project_markdown,
)
from .sources import (
    VaultPaths,
    dump_frontmatter,
    ensure_relative,
    load_import_manifests,
    load_run_records,
    load_source_cards,
    read_frontmatter_markdown,
    run_display_title,
    slugify_text,
    write_text,
)

PROJECT_LIST_FIELDS = (
    "related_papers",
    "related_runs",
    "related_concepts",
    "related_syntheses",
    "related_tasks",
    "related_proposals",
    "outputs",
)


def _now_iso() -> str:
    return datetime.now().astimezone().replace(microsecond=0).isoformat()


def initialize_vault(vault: Path | str, *, rebuild: bool = True) -> VaultPaths:
    from .importer import initialize_vault as initialize

    return initialize(vault, rebuild=rebuild)


def _run_ref(run: RunRecord) -> str:
    from .importer import _run_ref as run_ref

    return run_ref(run)


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


def _refresh_project_navigation(paths: VaultPaths) -> dict[str, int | bool]:
    artifacts = _collect_research_artifacts(paths)
    title, empty_message = ARTIFACT_INDEXES["projects"]
    write_text(
        paths.indexes / "projects.md",
        render_artifact_index(
            title,
            artifacts.get("projects") or [],
            empty_message=empty_message,
        ),
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
        "index_files_written": 1,
        "llm_files_written": 2,
        "full_rebuild": False,
    }


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
    rebuild_summary = _refresh_project_navigation(paths)
    return {
        "vault": str(paths.vault),
        "project": ensure_relative(project_path, paths.vault),
        "slug": normalized_slug,
        "title": _project_title(normalized_slug, title),
        "state": state,
        "refresh": rebuild_summary,
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


def _resolve_project_proposal_ref(paths: VaultPaths, proposal_path: str) -> str:
    raw = (proposal_path or "").strip().strip("/")
    if not raw:
        raise ValueError("Proposal reference must not be empty.")
    if not raw.startswith("proposals/"):
        raw = f"proposals/{raw}"
    candidate = Path(raw)
    if (
        candidate.is_absolute()
        or not candidate.parts
        or candidate.parts[0] != "proposals"
        or any(part in {"", ".", ".."} for part in candidate.parts)
    ):
        raise ValueError("Proposal reference must stay inside proposals/.")
    path = paths.vault / candidate
    if path.exists():
        return ensure_relative(path, paths.vault)
    if candidate.suffix:
        raise ValueError(f"Linked proposal does not exist: {candidate}")
    markdown_path = path.with_suffix(".md")
    if markdown_path.exists():
        return ensure_relative(markdown_path, paths.vault)
    raise ValueError(f"Linked proposal does not exist: {candidate}")


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
        rebuild_summary = _refresh_project_navigation(paths)
    else:
        rebuild_summary = None
    return {
        "vault": str(paths.vault),
        "project": ensure_relative(project_path, paths.vault),
        "field": field,
        "ref": ref,
        "changed": changed,
        "refresh": rebuild_summary,
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


def project_link_proposal(vault: Path | str, slug: str, proposal_path: str) -> dict[str, Any]:
    paths = initialize_vault(vault, rebuild=False)
    ref = _resolve_project_proposal_ref(paths, proposal_path)
    return _update_project_link(
        paths.vault,
        slug,
        field="related_proposals",
        ref=ref,
        section="Linked proposals",
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


def _proposal_row(paths: VaultPaths, ref: str) -> dict[str, Any]:
    cleaned = (ref or "").strip().strip("/")
    candidate = Path(cleaned)
    if (
        not cleaned
        or candidate.is_absolute()
        or any(part in {"", ".", ".."} for part in candidate.parts)
        or not candidate.parts
        or candidate.parts[0] != "proposals"
    ):
        return {"path": ref, "title": ref, "exists": False}
    path = paths.vault / candidate
    if not path.exists():
        return {"path": cleaned, "title": cleaned, "exists": False}
    if path.is_dir():
        markdown_files = sorted(
            child for child in path.glob("*.md") if not child.name.startswith(".")
        )
        title_path = path / "index.md"
        if not title_path.exists() and markdown_files:
            title_path = markdown_files[0]
        if title_path.exists():
            frontmatter, body = read_frontmatter_markdown(title_path)
            title = _artifact_title(title_path, frontmatter, body)
        else:
            title = path.name.replace("-", " ").replace("_", " ").title()
        return {"path": ensure_relative(path, paths.vault), "title": title, "exists": True}
    if path.suffix.casefold() == ".md":
        frontmatter, body = read_frontmatter_markdown(path)
        title = _artifact_title(path, frontmatter, body)
    else:
        title = path.name
    return {"path": ensure_relative(path, paths.vault), "title": title, "exists": True}


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
    proposal_rows = [
        _proposal_row(paths, ref) for ref in project.get("related_proposals") or []
    ]
    for label, rows in [
        ("concept", concept_rows),
        ("synthesis", synthesis_rows),
        ("task", task_rows),
        ("proposal", proposal_rows),
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
        "proposals": proposal_rows,
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
        "missing_linked_proposals": [],
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
    for ref in project.get("related_proposals") or []:
        row = _proposal_row(paths, ref)
        if not row.get("exists"):
            issues["missing_linked_proposals"].append(
                _project_issue("Linked proposal does not exist", target=ref)
            )
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
            "linked_proposals": len(project.get("related_proposals") or []),
            "linked_runs": len(project.get("related_runs") or []),
        },
        "issue_counts": issue_counts,
        "issues": issues,
    }
