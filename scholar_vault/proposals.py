from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from textwrap import dedent
from typing import Any

from .obsidian import (
    PDF_READING_NOTES_RE,
    _as_string_list,
    _display_path,
    _extract_markdown_targets,
    _extract_paper_refs,
    _markdown_files,
    _resolve_markdown_target,
)
from .rebuild import _rebuild_indexes
from .sources import (
    VaultPaths,
    ensure_relative,
    load_source_cards,
    read_frontmatter_markdown,
    slugify_text,
    write_text,
)

PROPOSAL_ROLE_RE = re.compile(
    r"Proposal role\s*:\s*(Core|Supporting|Discarded)\b",
    re.IGNORECASE,
)
ROLE_CELL_RE = re.compile(r"\|\s*(Core|Supporting|Discarded)\s*\|", re.IGNORECASE)
ORIGINAL_NOTES_RE = re.compile(
    r"^#+\s+Original User Notes - Verbatim\s*$",
    re.IGNORECASE | re.MULTILINE,
)
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


def initialize_vault(vault: Path | str, *, rebuild: bool = True) -> VaultPaths:
    from .importer import initialize_vault as initialize

    return initialize(vault, rebuild=rebuild)


def _resolve_proposal_path(paths: VaultPaths, proposal: Path | str) -> Path:
    proposal_path = Path(proposal).expanduser()
    if not proposal_path.is_absolute():
        proposal_path = paths.vault / proposal_path
    return proposal_path.resolve()


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
