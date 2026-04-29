from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import bibtexparser

from .models import SourceCard
from .sources import clean_markdown_text, normalize_doi

BIBTEX_READY_STATUSES = {"generated", "verified"}
BIBTEX_FIELD_ORDER = [
    "author",
    "editor",
    "title",
    "journal",
    "booktitle",
    "series",
    "volume",
    "number",
    "pages",
    "publisher",
    "address",
    "institution",
    "school",
    "year",
    "month",
    "doi",
    "url",
    "isbn",
    "issn",
    "abstract",
    "keywords",
    "file",
    "note",
]


@dataclass(frozen=True)
class BibtexRenderResult:
    entry: str
    source: str
    warnings: tuple[str, ...] = ()


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
    cleaned = re.sub(r"\s+", " ", str(value)).strip()
    if cleaned.count("{") == cleaned.count("}"):
        return cleaned.replace("\\", "\\\\")
    return cleaned.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")


def _metadata_dir(metadata_root: Path | None, card: SourceCard) -> Path | None:
    if metadata_root is None:
        return None
    return metadata_root / (card.citekey or card.slug)


def _parse_raw_bibtex(raw_bibtex: str) -> tuple[str, dict[str, str]] | None:
    try:
        database = bibtexparser.loads(raw_bibtex)
    except Exception:
        return None
    if not database.entries:
        return None
    entry = dict(database.entries[0])
    entry_type = str(entry.pop("ENTRYTYPE", "misc") or "misc").lower()
    entry.pop("ID", None)
    fields = {
        str(key).lower(): clean_markdown_text(str(value))
        for key, value in entry.items()
        if value is not None and str(value).strip()
    }
    return entry_type, fields


def rekey_bibtex(raw_bibtex: str, key: str) -> str:
    return re.sub(r"^@\s*([^{]+)\{[^,]+,", rf"@\1{{{key},", raw_bibtex.strip(), count=1)


def _csl_person_name(person: dict[str, Any]) -> str:
    literal = clean_markdown_text(person.get("literal"))
    if literal:
        return literal
    given = clean_markdown_text(person.get("given"))
    family = clean_markdown_text(person.get("family"))
    return " ".join(part for part in [given, family] if part).strip()


def _csl_year(csl: dict[str, Any]) -> str | None:
    issued = csl.get("issued") or csl.get("published") or {}
    date_parts = issued.get("date-parts") or []
    if date_parts and date_parts[0]:
        return str(date_parts[0][0])
    return None


def _csl_month(csl: dict[str, Any]) -> str | None:
    issued = csl.get("issued") or csl.get("published") or {}
    date_parts = issued.get("date-parts") or []
    if date_parts and date_parts[0] and len(date_parts[0]) >= 2:
        return str(date_parts[0][1])
    return None


def _csl_entry_type(csl_type: str | None) -> str:
    csl_type = (csl_type or "").casefold()
    if csl_type in {"article-journal", "article-magazine", "article-newspaper"}:
        return "article"
    if csl_type in {"paper-conference", "proceedings"}:
        return "inproceedings"
    if csl_type == "chapter":
        return "incollection"
    if csl_type == "book":
        return "book"
    if csl_type == "report":
        return "techreport"
    if csl_type == "thesis":
        return "phdthesis"
    if csl_type == "manuscript":
        return "unpublished"
    return "misc"


def _venue_field_name(entry_type: str) -> str:
    if entry_type == "article":
        return "journal"
    if entry_type in {"inproceedings", "incollection"}:
        return "booktitle"
    if entry_type == "techreport":
        return "institution"
    if entry_type == "phdthesis":
        return "school"
    return "howpublished"


def _entry_type_for_card(card: SourceCard) -> str:
    text = " ".join(part for part in [card.venue, card.title] if part).casefold()
    if "thesis" in text or "dissertation" in text:
        return "phdthesis"
    conference_tokens = [
        "proceedings",
        "conference",
        "symposium",
        "workshop",
        "congress",
        "chi ",
        "uist",
        "ieee vis",
        "ieee conference",
        "acm ",
    ]
    if card.venue and any(token in text for token in conference_tokens):
        return "inproceedings"
    if card.venue:
        return "article"
    return "misc"


def _entry_from_csl(csl: dict[str, Any]) -> tuple[str, dict[str, str]] | None:
    title = clean_markdown_text(csl.get("title"))
    if not title:
        return None
    entry_type = _csl_entry_type(csl.get("type"))
    fields: dict[str, str] = {"title": title}
    authors = [
        name
        for name in (_csl_person_name(person) for person in csl.get("author") or [])
        if name
    ]
    if authors:
        fields["author"] = " and ".join(authors)
    editors = [
        name
        for name in (_csl_person_name(person) for person in csl.get("editor") or [])
        if name
    ]
    if editors:
        fields["editor"] = " and ".join(editors)
    container_title = clean_markdown_text(csl.get("container-title"))
    if container_title:
        fields[_venue_field_name(entry_type)] = container_title
    if csl.get("publisher"):
        publisher_field = "institution" if entry_type == "techreport" else "publisher"
        fields.setdefault(publisher_field, clean_markdown_text(csl.get("publisher")))
    if csl.get("publisher-place"):
        fields["address"] = clean_markdown_text(csl.get("publisher-place"))
    for csl_key, bib_key in [
        ("volume", "volume"),
        ("issue", "number"),
        ("page", "pages"),
        ("DOI", "doi"),
        ("URL", "url"),
        ("ISBN", "isbn"),
        ("ISSN", "issn"),
        ("abstract", "abstract"),
    ]:
        value = csl.get(csl_key)
        if value:
            fields[bib_key] = clean_markdown_text(value)
    if year := _csl_year(csl):
        fields["year"] = year
    if month := _csl_month(csl):
        fields["month"] = month
    return entry_type, fields


def _load_cached_entry(
    metadata_root: Path | None,
    card: SourceCard,
) -> tuple[str, str, dict[str, str]] | None:
    work_dir = _metadata_dir(metadata_root, card)
    if work_dir is None:
        return None
    bib_path = work_dir / "citation.bib"
    if bib_path.exists():
        parsed = _parse_raw_bibtex(bib_path.read_text(encoding="utf-8"))
        if parsed is not None:
            entry_type, fields = parsed
            return "cached_bibtex", entry_type, fields
    csl_path = work_dir / "citation.csl.json"
    if csl_path.exists():
        try:
            csl = json.loads(csl_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            csl = None
        if isinstance(csl, dict):
            parsed = _entry_from_csl(csl)
            if parsed is not None:
                entry_type, fields = parsed
                return "cached_csl", entry_type, fields
    return None


def _card_fields(card: SourceCard, entry_type: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    if card.title:
        fields["title"] = card.title
    if card.authors:
        fields["author"] = " and ".join(card.authors)
    elif card.authors_preview:
        fields["author"] = card.authors_preview
    if card.venue:
        fields[_venue_field_name(entry_type)] = card.venue
    if card.year:
        fields["year"] = str(card.year)
    if card.doi:
        fields["doi"] = card.doi
    if card.url:
        fields["url"] = card.url
    return fields


def _vault_note(card: SourceCard) -> str | None:
    notes: list[str] = []
    if card.summary and card.summary != "No summary yet.":
        notes.append(f"Summary: {card.summary}")
    if card.why_this_source_matters:
        rationale = "; ".join(
            f"{point.label}: {point.text}" if point.label else point.text
            for point in card.why_this_source_matters
        )
        notes.append(f"Why this source matters: {rationale}")
    return " | ".join(notes) if notes else None


def _augment_fields(
    fields: dict[str, str],
    card: SourceCard,
    *,
    entry_type: str,
    include_vault_note: bool,
) -> dict[str, str]:
    merged = dict(fields)
    for key, value in _card_fields(card, entry_type).items():
        if value and not merged.get(key):
            merged[key] = value
    if card.doi:
        merged["doi"] = normalize_doi(merged.get("doi") or card.doi) or card.doi
    if card.abstract and not merged.get("abstract"):
        merged["abstract"] = card.abstract
    if card.pdf:
        merged["file"] = card.pdf
    if card.keywords:
        existing = [
            token.strip()
            for token in re.split(r"\s*[,;]\s*", merged.get("keywords", ""))
            if token.strip()
        ]
        keywords = []
        seen = set()
        for keyword in [*existing, *card.keywords]:
            key = keyword.casefold()
            if key not in seen:
                seen.add(key)
                keywords.append(keyword)
        if keywords:
            merged["keywords"] = ", ".join(keywords)
    if include_vault_note and (note := _vault_note(card)):
        merged["note"] = note if not merged.get("note") else f"{merged['note']} | {note}"
    return merged


def _format_bibtex(entry_type: str, key: str, fields: dict[str, str]) -> str:
    field_order = set(BIBTEX_FIELD_ORDER)
    ordered_fields = [
        field for field in BIBTEX_FIELD_ORDER if fields.get(field) is not None
    ]
    ordered_fields.extend(sorted(field for field in fields if field not in field_order))
    lines = [f"@{entry_type}{{{key},"]
    rendered = []
    for field_name in ordered_fields:
        value = clean_markdown_text(fields.get(field_name))
        if value:
            rendered.append((field_name, value))
    for index, (field_name, value) in enumerate(rendered):
        suffix = "," if index < len(rendered) - 1 else ""
        lines.append(f"  {field_name} = {{{_escape_bibtex(value)}}}{suffix}")
    lines.append("}")
    return "\n".join(lines)


def render_card_bibtex(
    card: SourceCard,
    *,
    metadata_root: Path | None = None,
    include_vault_note: bool = True,
    require_ready: bool = True,
) -> BibtexRenderResult | None:
    if require_ready and card.citation_status not in BIBTEX_READY_STATUSES:
        return None
    if not card.title:
        return None
    key = card.citekey or card.slug
    cached = _load_cached_entry(metadata_root, card)
    if cached is not None:
        source, entry_type, fields = cached
    else:
        source = "card"
        entry_type = _entry_type_for_card(card)
        fields = _card_fields(card, entry_type)
    fields = _augment_fields(
        fields,
        card,
        entry_type=entry_type,
        include_vault_note=include_vault_note,
    )
    warnings = []
    if card.citation_status not in BIBTEX_READY_STATUSES:
        warnings.append(
            f"citation_status is {card.citation_status}; run enrich or resolve metadata to verify"
        )
    for required in ["author", "year"]:
        if not fields.get(required):
            warnings.append(f"missing {required}")
    return BibtexRenderResult(
        entry=_format_bibtex(entry_type, key, fields),
        source=source,
        warnings=tuple(warnings),
    )


def normalize_bibtex_for_card(card: SourceCard, raw_bibtex: str | None = None) -> str:
    if raw_bibtex:
        normalized = raw_bibtex.strip()
        normalized = rekey_bibtex(normalized, card.citekey or card.slug)
    else:
        normalized = card_to_bibtex(card) or ""
    return normalized.rstrip() + "\n" if normalized else ""


def card_to_bibtex(
    card: SourceCard,
    *,
    metadata_root: Path | None = None,
    include_vault_note: bool = True,
    require_ready: bool = True,
) -> str | None:
    result = render_card_bibtex(
        card,
        metadata_root=metadata_root,
        include_vault_note=include_vault_note,
        require_ready=require_ready,
    )
    return result.entry if result is not None else None


def _split_bibtex_entries(text: str) -> dict[str, str]:
    entries: dict[str, str] = {}
    chunks = re.split(r"\n(?=@)", text.strip())
    for chunk in chunks:
        match = re.match(r"@\s*[^{]+\{\s*([^,\s]+)", chunk.strip())
        if match:
            entries[match.group(1)] = chunk.strip()
    return entries


def write_library_bib(
    cards: list[SourceCard],
    path: Path,
    *,
    metadata_root: Path | None = None,
    include_vault_note: bool = True,
) -> Path:
    existing_entries = (
        _split_bibtex_entries(path.read_text(encoding="utf-8")) if path.exists() else {}
    )
    current_keys = {card.citekey or card.slug for card in cards}
    entries_by_key = {
        key: entry for key, entry in existing_entries.items() if key in current_keys
    }
    for card in cards:
        key = card.citekey or card.slug
        if entry := card_to_bibtex(
            card,
            metadata_root=metadata_root,
            include_vault_note=include_vault_note,
        ):
            entries_by_key[key] = entry
    entries = [entries_by_key[key] for key in sorted(entries_by_key)]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n\n".join(entries).rstrip() + "\n", encoding="utf-8")
    return path
