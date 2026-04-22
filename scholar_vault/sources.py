from __future__ import annotations

import json
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

import yaml
from slugify import slugify
from unidecode import unidecode

from .models import RationalePoint, RunRecord, SourceCard

STOPWORDS = {
    "a",
    "an",
    "and",
    "at",
    "by",
    "for",
    "from",
    "in",
    "into",
    "of",
    "on",
    "or",
    "the",
    "to",
    "toward",
    "with",
}

FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n?(.*)$", re.DOTALL)
SECTION_RE = re.compile(r"^##\s+(.+?)\n", re.MULTILINE)
DOI_RE = re.compile(r"\b(10\.\d{4,9}/[-._;()/:A-Z0-9]+)\b", re.IGNORECASE)
YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")


class FrontmatterDumper(yaml.SafeDumper):
    pass


def _represent_none(dumper: yaml.SafeDumper, _: object) -> yaml.nodes.Node:
    return dumper.represent_scalar("tag:yaml.org,2002:null", "")


FrontmatterDumper.add_representer(type(None), _represent_none)


@dataclass(frozen=True)
class VaultPaths:
    vault: Path
    raw: Path
    raw_scholar_labs: Path
    raw_inbox: Path
    raw_staging: Path
    raw_unmatched: Path
    raw_imported: Path
    pdfs: Path
    papers: Path
    runs: Path
    topics: Path
    indexes: Path
    exports: Path

    @classmethod
    def from_root(cls, vault: Path | str) -> VaultPaths:
        root = Path(vault).expanduser().resolve()
        raw = root / "raw"
        indexes = root / "_indexes"
        exports = root / "_exports"
        return cls(
            vault=root,
            raw=raw,
            raw_scholar_labs=raw / "scholar-labs",
            raw_inbox=raw / "inbox",
            raw_staging=raw / "staging",
            raw_unmatched=raw / "unmatched",
            raw_imported=raw / "imported",
            pdfs=root / "pdfs",
            papers=root / "papers",
            runs=root / "runs",
            topics=root / "topics",
            indexes=indexes,
            exports=exports,
        )

    def ensure(self) -> None:
        for path in (
            self.vault,
            self.raw,
            self.raw_scholar_labs,
            self.raw_inbox,
            self.raw_staging,
            self.raw_unmatched,
            self.raw_imported,
            self.pdfs,
            self.papers,
            self.runs,
            self.topics,
            self.indexes,
            self.exports,
        ):
            path.mkdir(parents=True, exist_ok=True)


def clean_markdown_text(text: str | None) -> str:
    if not text:
        return ""
    normalized = text.replace("\r\n", "\n").strip()
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized


def parse_people(text: str | None) -> list[str]:
    if not text:
        return []
    cleaned = re.sub(r"\bet al\.?$", "", text, flags=re.IGNORECASE).strip(" ,;")
    if not cleaned:
        return []
    parts = re.split(r"\s+and\s+|,|;|\s*&\s*", cleaned)
    return [part.strip() for part in parts if part.strip()]


def slugify_text(text: str, *, max_length: int = 80) -> str:
    candidate = slugify(text or "untitled", lowercase=True, separator="-", max_length=max_length)
    return candidate or "untitled"


def normalize_title(text: str | None) -> str:
    ascii_text = unidecode((text or "").casefold())
    return re.sub(r"[^a-z0-9]+", " ", ascii_text).strip()


def normalize_doi(doi: str | None) -> str | None:
    if not doi:
        return None
    match = DOI_RE.search(doi.strip())
    return match.group(1).lower() if match else doi.strip().lower()


def infer_year(value: str | int | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    match = YEAR_RE.search(value)
    return int(match.group(0)) if match else None


def first_author_surname(authors: Sequence[str], authors_preview: str | None = None) -> str:
    pool = list(authors) or parse_people(authors_preview)
    if not pool:
        return "source"
    first = pool[0].replace(".", " ").strip()
    tokens = [token for token in re.split(r"\s+", first) if token]
    return unidecode(tokens[-1]).lower() if tokens else "source"


def title_keywords(title: str, *, minimum: int = 2, maximum: int = 5) -> list[str]:
    words = re.findall(r"[A-Za-z0-9]+", unidecode(title))
    filtered = [word.lower() for word in words if word.lower() not in STOPWORDS and len(word) > 2]
    if len(filtered) < minimum:
        filtered = [word.lower() for word in words if len(word) > 2]
    return filtered[:maximum] or ["source"]


def ensure_unique(value: str, existing: Iterable[str]) -> str:
    used = {item for item in existing if item}
    if value not in used:
        return value
    counter = 2
    while f"{value}-{counter}" in used:
        counter += 1
    return f"{value}-{counter}"


def build_citekey(
    title: str,
    authors: Sequence[str],
    year: int | None,
    *,
    authors_preview: str | None = None,
    existing: str | None = None,
    existing_keys: Iterable[str] = (),
) -> str:
    if existing:
        return existing
    surname = first_author_surname(authors, authors_preview)
    year_part = str(year) if year else "nd"
    keyword_part = "".join(title_keywords(title))
    base = f"{surname}{year_part}{keyword_part}"
    return ensure_unique(base, existing_keys)


def build_card_slug(citekey: str | None, title: str, existing_slugs: Iterable[str]) -> str:
    preferred = slugify_text(citekey or title)
    return ensure_unique(preferred, existing_slugs)


def build_pdf_filename(
    title: str,
    authors: Sequence[str],
    year: int | None,
    *,
    authors_preview: str | None = None,
    existing_names: Iterable[str] = (),
) -> str:
    stem = build_citekey(
        title,
        authors,
        year,
        authors_preview=authors_preview,
        existing_keys=(),
    )
    safe_stem = slugify_text(stem, max_length=100)
    name = f"{safe_stem}.pdf"
    return ensure_unique(name, existing_names)


def infer_topics(prompt: str, rationale_points: Sequence[RationalePoint]) -> list[str]:
    topics: list[str] = []
    seen: set[str] = set()
    for point in rationale_points:
        label = clean_markdown_text(point.label)
        if label:
            normalized = label.title()
            key = normalized.casefold()
            if key not in seen:
                seen.add(key)
                topics.append(normalized)
    prompt_words = [
        token.lower()
        for token in re.findall(r"[A-Za-z][A-Za-z0-9-]+", prompt)
        if token.lower() not in STOPWORDS and len(token) > 3
    ]
    for token in prompt_words[:3]:
        normalized = token.replace("-", " ").title()
        key = normalized.casefold()
        if key not in seen:
            seen.add(key)
            topics.append(normalized)
    return topics


def topic_slug(topic: str) -> str:
    return slugify_text(topic)


def ensure_relative(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def dump_frontmatter(data: dict) -> str:
    return yaml.dump(
        data,
        Dumper=FrontmatterDumper,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
        width=1000,
    )


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def write_yaml(path: Path, data: dict) -> None:
    write_text(path, yaml.safe_dump(data, sort_keys=False, allow_unicode=True))


def write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_frontmatter_markdown(path: Path) -> tuple[dict, str]:
    text = path.read_text(encoding="utf-8")
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    frontmatter = yaml.safe_load(match.group(1)) or {}
    body = match.group(2)
    return frontmatter, body


def parse_sections(body: str) -> dict[str, str]:
    matches = list(SECTION_RE.finditer(body))
    if not matches:
        return {}
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        title = match.group(1).strip()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        sections[title] = body[start:end].strip()
    return sections


def parse_rationale_points(section_text: str) -> list[RationalePoint]:
    points: list[RationalePoint] = []
    for line in section_text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("- "):
            continue
        item = stripped[2:].strip()
        labeled = re.match(r"\*\*(.+?)\*\*:\s*(.+)$", item)
        if labeled:
            points.append(
                RationalePoint(
                    label=labeled.group(1).strip(),
                    text=labeled.group(2).strip(),
                )
            )
            continue
        points.append(RationalePoint(text=item))
    return points


def load_source_card(path: Path) -> SourceCard:
    frontmatter, body = read_frontmatter_markdown(path)
    sections = parse_sections(body)
    card = SourceCard(
        slug=path.stem,
        summary=sections.get("Summary", "").strip() or "No summary yet.",
        why_this_source_matters=parse_rationale_points(sections.get("Why this source matters", "")),
        notes=sections.get("Notes", "").strip(),
        **frontmatter,
    )
    if not card.authors and card.authors_preview:
        card.authors = parse_people(card.authors_preview)
    if card.doi:
        card.doi = normalize_doi(card.doi)
    return card


def load_source_cards(paths: VaultPaths) -> list[SourceCard]:
    cards: list[SourceCard] = []
    for path in sorted(paths.papers.glob("*.md")):
        cards.append(load_source_card(path))
    return cards


def load_run_records(paths: VaultPaths) -> list[RunRecord]:
    runs: list[RunRecord] = []
    for path in sorted(paths.runs.glob("*/index.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        runs.append(RunRecord.model_validate(data))
    return runs
