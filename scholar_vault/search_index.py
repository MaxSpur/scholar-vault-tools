from __future__ import annotations

import re

from .models import SourceCard
from .obsidian import (
    ARTIFACT_DEFAULT_TYPES,
    _artifact_title,
    _as_string_list,
    _card_id,
    _compact_text,
    _should_index_artifact_path,
)
from .sources import VaultPaths, ensure_relative, read_frontmatter_markdown


def _pdf_reading_notes_snippet(card: SourceCard) -> str:
    match = re.search(
        r"(?ims)^#{3,6}\s+PDF reading notes[^\n]*\n(?P<body>.*?)(?=^#{1,6}\s+|\Z)",
        card.notes or "",
    )
    if not match:
        return ""
    return _compact_text(match.group("body"), limit=800)


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
