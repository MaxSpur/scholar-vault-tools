from __future__ import annotations

import re
import urllib.parse
from collections import Counter
from pathlib import Path
from typing import Any

from .models import SourceCard
from .sources import (
    VaultPaths,
    clean_markdown_text,
    ensure_relative,
    read_frontmatter_markdown,
)

ARTIFACT_INDEXES = {
    "paper-digests": ("Paper Digests", "No paper digest notes have been created yet."),
    "concepts": ("Concepts", "No concept cards have been created yet."),
    "syntheses": ("Syntheses", "No synthesis notes have been created yet."),
    "tasks": ("Tasks", "No follow-up task notes have been created yet."),
    "queries": ("Research Queries", "No research query notes have been created yet."),
    "projects": ("Projects", "No project workspaces have been created yet."),
    "proposals": ("Proposals", "No proposal workspaces have been created yet."),
}
ARTIFACT_DEFAULT_TYPES = {
    "paper-digests": "paper_digest",
    "concepts": "concept",
    "syntheses": "synthesis",
    "tasks": "task",
    "queries": "research_query",
    "projects": "project",
    "proposals": "proposal",
}
MARKDOWN_LINK_RE = re.compile(r"\[[^\]]+\]\((<?[^)>\n]+(?:\.md|/)?>?)\)")
WIKILINK_RE = re.compile(r"!?\[\[([^\]\n]+)\]\]")
PAPER_PATH_RE = re.compile(r"papers/[^)\]>\s]+\.md")
PDF_READING_NOTES_RE = re.compile(r"^###\s+PDF reading notes\b", re.IGNORECASE | re.MULTILINE)
VAULT_NOTE_ROOTS = {
    "bases",
    "concepts",
    "papers",
    "paper-digests",
    "projects",
    "proposals",
    "queries",
    "runs",
    "syntheses",
    "tasks",
}


def _compact_text(value: str | None, *, limit: int = 500) -> str:
    cleaned = clean_markdown_text(value)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3].rstrip(" .,;:") + "..."


def _markdown_cell(value: object) -> str:
    text = _compact_text(str(value) if value is not None else "", limit=220)
    return text.replace("|", r"\|") or "-"


def _markdown_table(
    headers: list[str],
    rows: list[list[object]],
    *,
    empty: str = "No rows.",
) -> list[str]:
    if not rows:
        return [empty]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(_markdown_cell(value) for value in row) + " |")
    return lines


def _paper_link(card: SourceCard) -> str:
    return f"[{card.title}](../papers/{card.slug}.md)"


def _artifact_link(artifact: dict[str, Any]) -> str:
    return f"[{artifact.get('title') or artifact.get('path')}](../{artifact.get('path')})"


def _display_path(path: Path, root: Path) -> str:
    try:
        return ensure_relative(path, root)
    except ValueError:
        return str(path)


def _card_ref(card: SourceCard) -> str:
    return f"papers/{card.slug}.md"


def _card_id(card: SourceCard) -> str:
    return card.citekey or card.slug


def _status_counts(cards: list[SourceCard], field: str) -> dict[str, int]:
    counts = Counter(str(getattr(card, field, None) or "missing") for card in cards)
    return dict(sorted(counts.items()))


def _card_has_valid_pdf(paths: VaultPaths, card: SourceCard) -> bool:
    if not card.pdf:
        return False
    pdf_path = Path(card.pdf)
    if not pdf_path.is_absolute():
        pdf_path = paths.vault / card.pdf
    return pdf_path.exists()


def _markdown_heading_re(heading: str) -> re.Pattern[str]:
    cleaned = re.sub(r"^#+\s*", "", heading or "").strip()
    if not cleaned:
        raise ValueError("Heading must not be empty.")
    return re.compile(
        rf"^#{{1,6}}\s+{re.escape(cleaned)}(?:$|[\s:—–-].*)",
        re.IGNORECASE | re.MULTILINE,
    )


def _first_markdown_heading(body: str) -> str | None:
    match = re.search(r"^#\s+(.+?)\s*$", body, flags=re.MULTILINE)
    return clean_markdown_text(match.group(1)) if match else None


def _artifact_title(path: Path, frontmatter: dict[str, Any], body: str) -> str:
    title = frontmatter.get("title")
    if isinstance(title, str) and title.strip():
        return clean_markdown_text(title)
    heading = _first_markdown_heading(body)
    if heading:
        return heading
    return path.stem.replace("-", " ").replace("_", " ").strip().title()


def _as_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _should_index_artifact_path(folder: str, path: Path, root: Path) -> bool:
    if folder == "projects":
        return path.name == "index.md"
    if folder == "queries":
        return len(path.relative_to(root).parts) == 1
    return True


def _collect_artifacts(paths: VaultPaths, folder: str) -> list[dict[str, Any]]:
    root = paths.vault / folder
    if not root.exists():
        return []
    artifacts: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*.md")):
        if any(part.startswith(".") for part in path.relative_to(root).parts):
            continue
        if not _should_index_artifact_path(folder, path, root):
            continue
        frontmatter, body = read_frontmatter_markdown(path)
        sources = _as_string_list(frontmatter.get("sources"))
        if folder == "paper-digests" and frontmatter.get("paper"):
            sources = _as_string_list(frontmatter.get("paper")) + sources
        artifacts.append(
            {
                "path": ensure_relative(path, paths.vault),
                "title": _artifact_title(path, frontmatter, body),
                "type": frontmatter.get("type") or ARTIFACT_DEFAULT_TYPES.get(folder, "note"),
                "created": frontmatter.get("created") or frontmatter.get("date"),
                "sources": sources,
            }
        )
    return artifacts


def _collect_research_artifacts(paths: VaultPaths) -> dict[str, list[dict[str, Any]]]:
    return {folder: _collect_artifacts(paths, folder) for folder in ARTIFACT_INDEXES}


def _markdown_files(root: Path) -> list[Path]:
    if root.is_file() and root.suffix.casefold() == ".md":
        return [root]
    if not root.exists():
        return []
    return [
        path
        for path in sorted(root.rglob("*.md"))
        if not any(part.startswith(".") for part in path.relative_to(root).parts)
    ]


def _extract_markdown_targets(text: str) -> list[str]:
    targets: list[str] = []
    for match in MARKDOWN_LINK_RE.finditer(text):
        target = match.group(1).strip("<>")
        if "://" in target or target.startswith("#"):
            continue
        targets.append(urllib.parse.unquote(target.split("#", 1)[0]))
    return [target for target in targets if target]


def _extract_wikilink_targets(text: str) -> list[str]:
    targets: list[str] = []
    for match in WIKILINK_RE.finditer(text):
        target = match.group(1).split("|", 1)[0].split("#", 1)[0].strip()
        if not target or "://" in target:
            continue
        targets.append(urllib.parse.unquote(target))
    return targets


def _extract_note_targets(text: str) -> list[str]:
    targets = [*_extract_markdown_targets(text), *_extract_wikilink_targets(text)]
    seen: set[str] = set()
    unique: list[str] = []
    for target in targets:
        key = target.strip()
        if key and key not in seen:
            seen.add(key)
            unique.append(key)
    return unique


def _extract_paper_refs(text: str) -> list[str]:
    refs = set(PAPER_PATH_RE.findall(text))
    for target in _extract_note_targets(text):
        if "papers/" in target and target.endswith(".md"):
            refs.add(target[target.index("papers/") :])
        elif target.startswith("papers/") and not Path(target).suffix:
            refs.add(f"{target}.md")
    return sorted(refs)


def _resolve_markdown_target(paths: VaultPaths, source: Path, target: str) -> Path:
    if "papers/" in target:
        return (paths.vault / target[target.index("papers/") :]).resolve()
    target_path = Path(target)
    if target_path.is_absolute():
        return target_path.resolve()
    if target_path.parts and target_path.parts[0] in VAULT_NOTE_ROOTS:
        return (paths.vault / target_path).resolve()
    return (source.parent / target_path).resolve()


def _resolve_note_target(paths: VaultPaths, source: Path, target: str) -> Path | None:
    target = target.split("|", 1)[0].split("#", 1)[0].strip()
    if not target or "://" in target:
        return None
    target_path = Path(target)
    if target_path.is_absolute():
        return target_path.resolve()
    if target_path.parts and target_path.parts[0] in VAULT_NOTE_ROOTS:
        candidate = (paths.vault / target_path).resolve()
        if candidate.suffix or candidate.exists():
            return candidate
        return candidate.with_suffix(".md")
    if "/" in target:
        candidate = (source.parent / target_path).resolve()
        if candidate.suffix or candidate.exists():
            return candidate
        return candidate.with_suffix(".md")
    matches = []
    for root_name in VAULT_NOTE_ROOTS:
        root = paths.vault / root_name
        if root.exists():
            matches.extend(path for path in root.rglob("*.md") if path.stem == target)
    if len(matches) == 1:
        return matches[0].resolve()
    return None
