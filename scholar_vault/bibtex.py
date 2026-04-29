from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import bibtexparser
from unidecode import unidecode

from .models import SourceCard
from .sources import clean_markdown_text, normalize_doi

BIBTEX_READY_STATUSES = {"generated", "verified"}
LOCAL_BIBLATEX_FIELDS = {"abstract", "file", "keywords", "note"}
BIBTEX_FIELD_ORDER = [
    "author",
    "editor",
    "title",
    "subtitle",
    "journaltitle",
    "booktitle",
    "series",
    "volume",
    "number",
    "pages",
    "publisher",
    "location",
    "institution",
    "organization",
    "type",
    "year",
    "date",
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
BIBTEX_PUNCTUATION_TRANSLATION = str.maketrans(
    {
        "\u00a0": " ",
        "\u00ad": "",
        "\u2010": "-",
        "\u2011": "-",
        "\u2012": "-",
        "\u2013": "--",
        "\u2014": "---",
        "\u2015": "---",
        "\u2018": "'",
        "\u2019": "'",
        "\u201a": "'",
        "\u201b": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u201e": '"',
        "\u201f": '"',
        "\u2026": "...",
        "\u2032": "'",
        "\u2033": '"',
        "\u2044": "/",
        "\u2212": "-",
    }
)
TEX_SPECIAL_CHARS = {
    "Æ": r"{\AE}",
    "æ": r"{\ae}",
    "Œ": r"{\OE}",
    "œ": r"{\oe}",
    "Ø": r"{\O}",
    "ø": r"{\o}",
    "Å": r"{\AA}",
    "å": r"{\aa}",
    "Ł": r"{\L}",
    "ł": r"{\l}",
    "Đ": r"{\DJ}",
    "đ": r"{\dj}",
    "Þ": r"{\TH}",
    "þ": r"{\th}",
    "ß": r"{\ss}",
}
TEX_COMBINING_ACCENTS = {
    "\u0300": r"\`",
    "\u0301": r"\'",
    "\u0302": r"\^",
    "\u0303": r"\~",
    "\u0304": r"\=",
    "\u0306": r"\u",
    "\u0307": r"\.",
    "\u0308": '\\"',
    "\u030a": r"\r",
    "\u030b": r"\H",
    "\u030c": r"\v",
    "\u0327": r"\c",
    "\u0328": r"\k",
}
PROTECT_TITLE_TOKEN_RE = re.compile(
    r"\b(?:[A-Z]{2,}[A-Za-z0-9]*|[A-Za-z0-9]*[A-Z][a-z0-9]+[A-Z][A-Za-z0-9]*|\d+[A-Z]+)\b"
    r"|(?<=-)[A-Z][A-Za-z0-9]*\b"
)
PROVIDER_TYPE_MAP = {
    "journal-article": "article",
    "article-journal": "article",
    "article-magazine": "article",
    "article-newspaper": "article",
    "article": "article",
    "proceedings-article": "inproceedings",
    "paper-conference": "inproceedings",
    "proceedings": "inproceedings",
    "book-chapter": "incollection",
    "chapter": "incollection",
    "book": "book",
    "edited-book": "book",
    "monograph": "book",
    "report": "report",
    "report-series": "report",
    "dissertation": "thesis",
    "thesis": "thesis",
    "posted-content": "online",
    "preprint": "online",
    "webpage": "online",
    "dataset": "dataset",
}
ENTRY_TYPE_ALIASES = {
    "conference": "inproceedings",
    "techreport": "report",
    "phdthesis": "thesis",
    "mastersthesis": "thesis",
    "www": "online",
}
GENERIC_ENTRY_TYPES = {"misc", "online"}
ENTRY_REQUIRED_FIELDS = {
    "article": (("title",), ("author", "editor"), ("journaltitle",), ("year", "date")),
    "inproceedings": (("title",), ("author", "editor"), ("booktitle",), ("year", "date")),
    "incollection": (("title",), ("author", "editor"), ("booktitle",), ("year", "date")),
    "book": (("title",), ("author", "editor"), ("year", "date")),
    "report": (("title",), ("author", "editor"), ("institution",), ("year", "date")),
    "thesis": (("title",), ("author",), ("institution",), ("type",), ("year", "date")),
    "online": (("title",), ("url", "doi")),
    "dataset": (("title",), ("doi", "url"), ("year", "date")),
}


@dataclass(frozen=True)
class BibtexRenderResult:
    entry: str
    source: str
    entry_type: str = "misc"
    fields: dict[str, str] = field(default_factory=dict)
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


def _char_to_bibtex_ascii(char: str) -> str:
    if ord(char) < 128:
        return char
    if char in TEX_SPECIAL_CHARS:
        return TEX_SPECIAL_CHARS[char]
    decomposed = unicodedata.normalize("NFD", char)
    if not decomposed or decomposed == char:
        return unidecode(char)
    base = decomposed[0]
    accents = [mark for mark in decomposed[1:] if unicodedata.combining(mark)]
    if base and ord(base) < 128 and accents:
        rendered = base
        for accent in accents:
            command = TEX_COMBINING_ACCENTS.get(accent)
            if command is None:
                return unidecode(char)
            rendered = f"{command}{rendered}"
        return f"{{{rendered}}}"
    return unidecode(char)


def _normalize_bibtex_value(value: str) -> str:
    cleaned = re.sub(r"\s+", " ", str(value)).strip()
    translated = cleaned.translate(BIBTEX_PUNCTUATION_TRANSLATION)
    return "".join(_char_to_bibtex_ascii(char) for char in translated)


def _escape_bibtex(value: str) -> str:
    normalized = _normalize_bibtex_value(value)
    if normalized.count("{") == normalized.count("}"):
        return normalized
    return normalized.replace("{", r"\{").replace("}", r"\}")


def _metadata_dir(metadata_root: Path | None, card: SourceCard) -> Path | None:
    if metadata_root is None:
        return None
    return metadata_root / (card.citekey or card.slug)


def _normalize_entry_type(entry_type: str | None) -> str:
    normalized = (entry_type or "misc").strip().lower()
    return ENTRY_TYPE_ALIASES.get(normalized, normalized) or "misc"


def _provider_type_to_entry_type(provider_type: str | None) -> str | None:
    normalized = (provider_type or "").strip().casefold().replace("_", "-")
    if not normalized:
        return None
    return PROVIDER_TYPE_MAP.get(normalized, ENTRY_TYPE_ALIASES.get(normalized))


def _clean_scalar(value: Any) -> str:
    if isinstance(value, list):
        value = value[0] if value else None
    if isinstance(value, dict):
        return ""
    return clean_markdown_text(str(value)) if value is not None else ""


def _first_mapping(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                return item
    return None


def _read_json(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _provider_entry_type(metadata_root: Path | None, card: SourceCard) -> str | None:
    work_dir = _metadata_dir(metadata_root, card)
    if work_dir is None:
        return None

    crossref = _read_json(work_dir / "crossref.json")
    if isinstance(crossref, dict):
        message = crossref.get("message")
        if isinstance(message, dict):
            item = _first_mapping(message.get("items")) or message
            entry_type = _provider_type_to_entry_type(_clean_scalar(item.get("type")))
            if entry_type:
                return entry_type

    openalex = _read_json(work_dir / "openalex.json")
    if isinstance(openalex, dict):
        item = _first_mapping(openalex.get("results")) or openalex
        for key in ("type_crossref", "type"):
            entry_type = _provider_type_to_entry_type(_clean_scalar(item.get(key)))
            if entry_type:
                return entry_type

    datacite = _read_json(work_dir / "datacite.json")
    if isinstance(datacite, dict):
        data = datacite.get("data")
        data_item = _first_mapping(data) if isinstance(data, list) else data
        if isinstance(data_item, dict):
            attributes = data_item.get("attributes")
            if isinstance(attributes, dict):
                types = attributes.get("types")
                if isinstance(types, dict):
                    for key in ("resourceTypeGeneral", "resourceType", "schemaOrg"):
                        entry_type = _provider_type_to_entry_type(
                            _clean_scalar(types.get(key))
                        )
                        if entry_type:
                            return entry_type
                entry_type = _provider_type_to_entry_type(
                    _clean_scalar(attributes.get("resourceType"))
                )
                if entry_type:
                    return entry_type
    return None


def _normalize_field_names(
    entry_type: str,
    fields: dict[str, str],
    *,
    include_local_fields: bool,
) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for raw_key, raw_value in fields.items():
        value = clean_markdown_text(raw_value)
        if not value:
            continue
        key = raw_key.lower()
        if key == "journal":
            key = "journaltitle"
        elif key == "address":
            key = "location"
        elif key == "school":
            key = "institution"
        elif key == "howpublished" and entry_type == "online":
            key = "organization"
        if not include_local_fields and key in LOCAL_BIBLATEX_FIELDS:
            continue
        normalized.setdefault(key, value)
    if entry_type == "thesis" and not normalized.get("type"):
        normalized["type"] = "thesis"
    return normalized


def _parse_raw_bibtex(raw_bibtex: str) -> tuple[str, dict[str, str]] | None:
    try:
        database = bibtexparser.loads(raw_bibtex)
    except Exception:
        return None
    if not database.entries:
        return None
    entry = dict(database.entries[0])
    entry_type = _normalize_entry_type(str(entry.pop("ENTRYTYPE", "misc") or "misc"))
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
    if mapped := _provider_type_to_entry_type(csl_type):
        return mapped
    csl_type = (csl_type or "").casefold()
    if csl_type == "manuscript":
        return "unpublished"
    return "misc"


def _venue_field_name(entry_type: str) -> str:
    if entry_type == "article":
        return "journaltitle"
    if entry_type in {"inproceedings", "incollection"}:
        return "booktitle"
    if entry_type in {"report", "thesis"}:
        return "institution"
    if entry_type == "online":
        return "organization"
    return "howpublished"


def _entry_type_for_card(card: SourceCard) -> str:
    text = " ".join(part for part in [card.venue, card.title] if part).casefold()
    if "thesis" in text or "dissertation" in text:
        return "thesis"
    if "report" in text or "white paper" in text:
        return "report"
    if "preprint" in text or "arxiv" in text:
        return "online"
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
        publisher_field = "institution" if entry_type in {"report", "thesis"} else "publisher"
        fields.setdefault(publisher_field, clean_markdown_text(csl.get("publisher")))
    if csl.get("publisher-place"):
        fields["location"] = clean_markdown_text(csl.get("publisher-place"))
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
    *,
    include_local_fields: bool,
) -> tuple[str, str, dict[str, str]] | None:
    work_dir = _metadata_dir(metadata_root, card)
    if work_dir is None:
        return None
    bib_path = work_dir / "citation.bib"
    if bib_path.exists():
        parsed = _parse_raw_bibtex(bib_path.read_text(encoding="utf-8"))
        if parsed is not None:
            entry_type, fields = parsed
            fields = _normalize_field_names(
                entry_type,
                fields,
                include_local_fields=include_local_fields,
            )
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
                fields = _normalize_field_names(
                    entry_type,
                    fields,
                    include_local_fields=include_local_fields,
                )
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


def _brace_depth_at(text: str, offset: int) -> int:
    depth = 0
    escaped = False
    for char in text[:offset]:
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == "{":
            depth += 1
        elif char == "}" and depth:
            depth -= 1
    return depth


def _protect_title_capitalization(value: str) -> str:
    normalized = _normalize_bibtex_value(value)
    protected: list[str] = []
    last = 0
    for match in PROTECT_TITLE_TOKEN_RE.finditer(normalized):
        start, end = match.span()
        token = match.group(0)
        protected.append(normalized[last:start])
        if _brace_depth_at(normalized, start) > 0:
            protected.append(token)
        elif start >= 2 and normalized[start - 1] == "-" and normalized[start - 2] == "-":
            protected.append(token)
        else:
            protected.append(f"{{{token}}}")
        last = end
    protected.append(normalized[last:])
    rendered = "".join(protected)
    if rendered.count("{") == rendered.count("}"):
        return rendered
    return normalized.replace("{", r"\{").replace("}", r"\}")


def _augment_fields(
    fields: dict[str, str],
    card: SourceCard,
    *,
    entry_type: str,
    include_local_fields: bool,
    include_vault_note: bool,
) -> dict[str, str]:
    merged = _normalize_field_names(
        entry_type,
        fields,
        include_local_fields=include_local_fields,
    )
    for key, value in _card_fields(card, entry_type).items():
        if value and not merged.get(key):
            merged[key] = value
    if card.doi:
        merged["doi"] = normalize_doi(merged.get("doi") or card.doi) or card.doi
    if include_local_fields:
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
    else:
        for key in LOCAL_BIBLATEX_FIELDS:
            merged.pop(key, None)
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
        if field_name == "title":
            value = _protect_title_capitalization(value)
        else:
            value = _escape_bibtex(value)
        lines.append(f"  {field_name} = {{{value}}}{suffix}")
    lines.append("}")
    return "\n".join(lines)


def _has_any_field(fields: dict[str, str], candidates: tuple[str, ...]) -> bool:
    return any(bool(fields.get(candidate)) for candidate in candidates)


def validate_biblatex_entry(
    *,
    entry_type: str,
    key: str,
    fields: dict[str, str],
    entry: str,
) -> tuple[str, ...]:
    warnings: list[str] = []
    if entry.count("{") != entry.count("}"):
        warnings.append("entry has unbalanced braces")
    if not key:
        warnings.append("missing citekey")
    required_groups = ENTRY_REQUIRED_FIELDS.get(entry_type)
    if required_groups is None:
        warnings.append(f"uncommon BibLaTeX entry type: {entry_type}")
    else:
        for group in required_groups:
            if not _has_any_field(fields, group):
                label = "/".join(group)
                warnings.append(f"missing required {label} for @{entry_type}")
    if entry_type == "misc":
        warnings.append("generic @misc entry; provider type was not available")
    return tuple(dict.fromkeys(warnings))


def render_card_bibtex(
    card: SourceCard,
    *,
    metadata_root: Path | None = None,
    include_vault_note: bool = True,
    include_local_fields: bool = True,
    require_ready: bool = True,
) -> BibtexRenderResult | None:
    if require_ready and card.citation_status not in BIBTEX_READY_STATUSES:
        return None
    if not card.title:
        return None
    key = card.citekey or card.slug
    provider_type = _provider_entry_type(metadata_root, card)
    cached = _load_cached_entry(
        metadata_root,
        card,
        include_local_fields=include_local_fields,
    )
    if cached is not None:
        source, entry_type, fields = cached
        if provider_type and entry_type in GENERIC_ENTRY_TYPES:
            entry_type = provider_type
    else:
        source = "card"
        entry_type = provider_type or _entry_type_for_card(card)
        fields = _card_fields(card, entry_type)
    entry_type = _normalize_entry_type(entry_type)
    fields = _augment_fields(
        fields,
        card,
        entry_type=entry_type,
        include_local_fields=include_local_fields,
        include_vault_note=include_vault_note,
    )
    entry = _format_bibtex(entry_type, key, fields)
    warnings = []
    if card.citation_status not in BIBTEX_READY_STATUSES:
        warnings.append(
            f"citation_status is {card.citation_status}; run enrich or resolve metadata to verify"
        )
    warnings.extend(
        validate_biblatex_entry(entry_type=entry_type, key=key, fields=fields, entry=entry)
    )
    return BibtexRenderResult(
        entry=entry,
        source=source,
        entry_type=entry_type,
        fields=fields,
        warnings=tuple(warnings),
    )


def normalize_bibtex_for_card(card: SourceCard, raw_bibtex: str | None = None) -> str:
    if raw_bibtex:
        parsed = _parse_raw_bibtex(raw_bibtex)
        if parsed is not None:
            entry_type, fields = parsed
            fields = _normalize_field_names(
                entry_type,
                fields,
                include_local_fields=True,
            )
            normalized = _format_bibtex(entry_type, card.citekey or card.slug, fields)
        else:
            normalized = rekey_bibtex(raw_bibtex.strip(), card.citekey or card.slug)
    else:
        normalized = card_to_bibtex(card) or ""
    return normalized.rstrip() + "\n" if normalized else ""


def card_to_bibtex(
    card: SourceCard,
    *,
    metadata_root: Path | None = None,
    include_vault_note: bool = True,
    include_local_fields: bool = True,
    require_ready: bool = True,
) -> str | None:
    result = render_card_bibtex(
        card,
        metadata_root=metadata_root,
        include_vault_note=include_vault_note,
        include_local_fields=include_local_fields,
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
    include_local_fields: bool = True,
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
            include_local_fields=include_local_fields,
        ):
            entries_by_key[key] = entry
    entries = [entries_by_key[key] for key in sorted(entries_by_key)]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n\n".join(entries).rstrip() + "\n", encoding="utf-8")
    return path
