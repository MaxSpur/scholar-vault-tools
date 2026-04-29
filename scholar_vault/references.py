from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .bibtex import BIBTEX_READY_STATUSES, render_card_bibtex
from .models import SourceCard
from .sources import clean_markdown_text, normalize_doi

REFERENCE_FORMATS = {"markdown", "plain", "rtf"}
REFERENCE_STYLES = {"apa"}
DOI_URL_RE = re.compile(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", flags=re.IGNORECASE)
TEX_ACCENT_REPLACEMENTS = {
    r"\"": {
        "A": "Ae",
        "a": "ae",
        "E": "E",
        "e": "e",
        "I": "I",
        "i": "i",
        "O": "Oe",
        "o": "oe",
        "U": "Ue",
        "u": "ue",
        "Y": "Y",
        "y": "y",
    },
    r"\'": {
        "A": "A",
        "a": "a",
        "E": "E",
        "e": "e",
        "I": "I",
        "i": "i",
        "O": "O",
        "o": "o",
        "U": "U",
        "u": "u",
        "Y": "Y",
        "y": "y",
    },
    r"\`": {
        "A": "A",
        "a": "a",
        "E": "E",
        "e": "e",
        "I": "I",
        "i": "i",
        "O": "O",
        "o": "o",
        "U": "U",
        "u": "u",
    },
    r"\~": {"N": "N", "n": "n", "A": "A", "a": "a", "O": "O", "o": "o"},
}


@dataclass(frozen=True)
class ReferenceRenderResult:
    content: str
    source: str
    style: str
    output_format: str
    warnings: tuple[str, ...] = ()


def _strip_tex_markup(value: str) -> str:
    text = clean_markdown_text(value)
    for command, letters in TEX_ACCENT_REPLACEMENTS.items():
        for letter, replacement in letters.items():
            escaped = re.escape(command)
            text = re.sub(rf"\{{{escaped}\s*\{{?{letter}\}}?\}}", replacement, text)
            text = re.sub(rf"{escaped}\s*\{{?{letter}\}}?", replacement, text)
    text = re.sub(r"\\[A-Za-z]+\*?(?:\[[^\]]*\])?(?:\{([^{}]*)\})?", r"\1", text)
    text = text.replace("{", "").replace("}", "")
    text = text.replace("--", "-")
    return re.sub(r"\s+", " ", text).strip()


def _markdown_escape(value: str) -> str:
    return re.sub(r"([\\*_`\[\]])", r"\\\1", value)


def _rtf_escape(value: str) -> str:
    escaped = []
    for char in value:
        codepoint = ord(char)
        if char in {"\\", "{", "}"}:
            escaped.append("\\" + char)
        elif char == "\n":
            escaped.append(r"\line ")
        elif codepoint > 127:
            if codepoint > 32767:
                codepoint -= 65536
            escaped.append(rf"\u{codepoint}?")
        else:
            escaped.append(char)
    return "".join(escaped)


def _text(value: str, output_format: str) -> str:
    value = _strip_tex_markup(value)
    if output_format == "markdown":
        return _markdown_escape(value)
    if output_format == "rtf":
        return _rtf_escape(value)
    return value


def _italic(value: str, output_format: str) -> str:
    value = _strip_tex_markup(value)
    if output_format == "markdown":
        return f"*{_markdown_escape(value)}*"
    if output_format == "rtf":
        return r"{\i " + _rtf_escape(value) + "}"
    return value


def _ensure_sentence(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    return value if value[-1] in ".!?" else f"{value}."


def _split_people(value: str | None) -> list[str]:
    if not value:
        return []
    return [person.strip() for person in value.split(" and ") if person.strip()]


def _initials(given: str) -> str:
    parts = [part for part in re.split(r"[\s-]+", given.strip()) if part]
    return " ".join(f"{part[0].upper()}." for part in parts if part[0].isalpha())


def _format_person(person: str) -> str:
    person = _strip_tex_markup(person)
    if not person:
        return ""
    if "," in person:
        family, given = [part.strip() for part in person.split(",", 1)]
        initials = _initials(given)
        return f"{family}, {initials}".strip().rstrip(",")
    parts = person.split()
    if len(parts) <= 1:
        return person
    family = parts[-1]
    given = " ".join(parts[:-1])
    initials = _initials(given)
    return f"{family}, {initials}".strip().rstrip(",")


def _format_people(value: str | None) -> str:
    people = [_format_person(person) for person in _split_people(value)]
    people = [person for person in people if person]
    if not people:
        return ""
    if len(people) == 1:
        return people[0]
    if len(people) == 2:
        return f"{people[0]}, & {people[1]}"
    return f"{', '.join(people[:-1])}, & {people[-1]}"


def _year(fields: dict[str, str]) -> str:
    if fields.get("year"):
        return _strip_tex_markup(fields["year"])
    date = _strip_tex_markup(fields.get("date", ""))
    match = re.search(r"\b\d{4}\b", date)
    return match.group(0) if match else "n.d."


def _doi_or_url(fields: dict[str, str], output_format: str) -> str:
    doi = normalize_doi(_strip_tex_markup(fields.get("doi", "")))
    if doi:
        return _text(f"https://doi.org/{doi}", output_format)
    url = _strip_tex_markup(fields.get("url", ""))
    if not url:
        return ""
    url = DOI_URL_RE.sub("https://doi.org/", url)
    return _text(url, output_format)


def _pages(fields: dict[str, str], output_format: str) -> str:
    pages = _strip_tex_markup(fields.get("pages", ""))
    return _text(pages, output_format) if pages else ""


def _volume_issue(fields: dict[str, str], output_format: str) -> str:
    volume = _strip_tex_markup(fields.get("volume", ""))
    issue = _strip_tex_markup(fields.get("number", ""))
    if not volume:
        return ""
    rendered = _italic(volume, output_format)
    if issue:
        rendered += f"({_text(issue, output_format)})"
    return rendered


def _join_nonempty(parts: list[str], separator: str = " ") -> str:
    return separator.join(part for part in parts if part)


def _reference_source(fields: dict[str, str], entry_type: str, output_format: str) -> str:
    doi_url = _doi_or_url(fields, output_format)
    pages = _pages(fields, output_format)
    if entry_type == "article":
        journal = _strip_tex_markup(fields.get("journaltitle", ""))
        source_parts = []
        if journal:
            source_parts.append(_italic(journal, output_format))
        if volume_issue := _volume_issue(fields, output_format):
            source_parts.append(volume_issue)
        if pages:
            source_parts.append(pages)
        source = ", ".join(source_parts)
        return _join_nonempty([_ensure_sentence(source), doi_url])
    if entry_type in {"inproceedings", "incollection"}:
        container = _strip_tex_markup(fields.get("booktitle", ""))
        source = f"In {_italic(container, output_format)}" if container else ""
        if pages:
            rendered_pages = _text(pages, output_format)
            source = (
                f"{source} (pp. {rendered_pages})" if source else f"pp. {rendered_pages}"
            )
        return _join_nonempty([_ensure_sentence(source), doi_url])
    if entry_type in {"book", "report", "thesis"}:
        details = []
        if entry_type in {"report", "thesis"} and fields.get("type"):
            details.append(f"[{_text(fields['type'], output_format)}]")
        publisher = fields.get("publisher") or fields.get("institution")
        if publisher:
            details.append(_text(publisher, output_format))
        return _join_nonempty([_ensure_sentence(" ".join(details)), doi_url])
    publisher = fields.get("publisher") or fields.get("organization") or fields.get("institution")
    return _join_nonempty([_ensure_sentence(_text(publisher, output_format)), doi_url])


def _format_apa(fields: dict[str, str], entry_type: str, output_format: str) -> str:
    authors = _format_people(fields.get("author")) or _format_people(fields.get("editor"))
    title = _strip_tex_markup(fields.get("title", ""))
    title_rendered = (
        _italic(title, output_format)
        if entry_type in {"book", "report", "thesis"}
        else _text(title, output_format)
    )
    year = _text(_year(fields), output_format)
    source = _reference_source(fields, entry_type, output_format)
    if authors:
        body = _join_nonempty(
            [_text(authors, output_format), f"({year}).", _ensure_sentence(title_rendered), source]
        )
    else:
        body = _join_nonempty([_ensure_sentence(title_rendered), f"({year}).", source])
    return body


def render_card_reference(
    card: SourceCard,
    *,
    metadata_root: Path | None = None,
    style: str = "apa",
    output_format: str = "markdown",
    wrap_rtf: bool = True,
) -> ReferenceRenderResult | None:
    style = style.casefold()
    output_format = output_format.casefold()
    if style not in REFERENCE_STYLES:
        raise ValueError(f"Unsupported reference style: {style}")
    if output_format not in REFERENCE_FORMATS:
        raise ValueError(f"Unsupported reference format: {output_format}")
    rendered = render_card_bibtex(
        card,
        metadata_root=metadata_root,
        include_vault_note=False,
        include_local_fields=False,
        require_ready=False,
    )
    if rendered is None:
        return None
    if style == "apa":
        body = _format_apa(rendered.fields, rendered.entry_type, output_format)
    warnings = list(rendered.warnings)
    if card.citation_status not in BIBTEX_READY_STATUSES:
        warnings.append("reference is based on unverified citation metadata")
    if output_format == "rtf" and wrap_rtf:
        body = r"{\rtf1\ansi " + body + r"\par}" + "\n"
    elif output_format == "rtf":
        body = body.rstrip() + r"\par" + "\n"
    else:
        body = body.rstrip() + "\n"
    return ReferenceRenderResult(
        content=body,
        source=rendered.source,
        style=style,
        output_format=output_format,
        warnings=tuple(dict.fromkeys(warnings)),
    )
