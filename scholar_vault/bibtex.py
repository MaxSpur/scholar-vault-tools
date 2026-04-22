from __future__ import annotations

import re
from pathlib import Path

import bibtexparser

from .models import SourceCard


def parse_bibtex_file(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8") as handle:
        database = bibtexparser.load(handle)
    return [dict(entry) for entry in database.entries]


def split_bibtex_authors(value: str | None) -> list[str]:
    if not value:
        return []
    return [author.strip() for author in value.split(" and ") if author.strip()]


def extract_pdf_paths(entry: dict[str, str]) -> list[str]:
    candidates: list[str] = []
    for key in ("file", "pdf", "local-url"):
        value = entry.get(key)
        if not value:
            continue
        if value.lower().endswith(".pdf"):
            candidates.append(value)
            continue
        for chunk in value.split(";"):
            matches = re.findall(r"(\/[^:;]+\.pdf|[A-Za-z]:\\[^:;]+\.pdf)", chunk)
            candidates.extend(matches)
    return candidates


def _escape_bibtex(value: str) -> str:
    return value.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")


def card_to_bibtex(card: SourceCard) -> str | None:
    if not card.title:
        return None
    entry_type = "article" if card.venue else "misc"
    key = card.citekey or card.slug
    fields: list[tuple[str, str]] = [("title", card.title)]
    if card.authors:
        fields.append(("author", " and ".join(card.authors)))
    elif card.authors_preview:
        fields.append(("author", card.authors_preview))
    if card.year:
        fields.append(("year", str(card.year)))
    if card.venue:
        field_name = "journal" if entry_type == "article" else "howpublished"
        fields.append((field_name, card.venue))
    if card.doi:
        fields.append(("doi", card.doi))
    if card.url:
        fields.append(("url", card.url))
    if card.pdf:
        fields.append(("file", card.pdf))
    if card.topics:
        fields.append(("keywords", ", ".join(card.topics)))
    notes: list[str] = []
    if card.summary and card.summary != "No summary yet.":
        notes.append(f"Summary: {card.summary}")
    if card.why_this_source_matters:
        rationale = "; ".join(
            f"{point.label}: {point.text}" if point.label else point.text
            for point in card.why_this_source_matters
        )
        notes.append(f"Why this source matters: {rationale}")
    if notes:
        fields.append(("note", " | ".join(notes)))

    lines = [f"@{entry_type}{{{key},"]
    for index, (field_name, value) in enumerate(fields):
        suffix = "," if index < len(fields) - 1 else ""
        lines.append(f"  {field_name} = {{{_escape_bibtex(value)}}}{suffix}")
    lines.append("}")
    return "\n".join(lines)


def write_library_bib(cards: list[SourceCard], path: Path) -> Path:
    entries = [entry for card in cards if (entry := card_to_bibtex(card))]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n\n".join(entries).rstrip() + "\n", encoding="utf-8")
    return path
