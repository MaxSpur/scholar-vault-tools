from __future__ import annotations

import json
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml
from slugify import slugify
from unidecode import unidecode

from .models import ImportManifest, RationalePoint, RunRecord, SourceCard, SummarySource
from .titles import clean_paper_title

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

RUN_TITLE_STOPWORDS = STOPWORDS | {
    "abstract",
    "about",
    "articles",
    "cited",
    "context",
    "could",
    "evidence",
    "example",
    "examples",
    "find",
    "foundational",
    "google",
    "key",
    "labs",
    "literature",
    "paper",
    "papers",
    "peer",
    "prioritize",
    "proposal",
    "recent",
    "research",
    "reviewed",
    "scholar",
    "search",
    "source",
    "sources",
    "state",
    "still",
    "support",
    "survey",
    "that",
    "used",
    "would",
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
    raw_metadata: Path
    raw_discovery: Path
    pdfs: Path
    papers: Path
    paper_digests: Path
    runs: Path
    topics: Path
    concepts: Path
    syntheses: Path
    tasks: Path
    task_queue: Path
    discovery_candidates: Path
    queries: Path
    evals: Path
    projects: Path
    proposals: Path
    bases: Path
    indexes: Path
    exports: Path
    operations: Path
    operation_runs: Path
    feedback: Path
    feedback_ratings: Path

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
            raw_metadata=raw / "metadata",
            raw_discovery=raw / "discovery",
            pdfs=root / "pdfs",
            papers=root / "papers",
            paper_digests=root / "paper-digests",
            runs=root / "runs",
            topics=root / "topics",
            concepts=root / "concepts",
            syntheses=root / "syntheses",
            tasks=root / "tasks",
            task_queue=root / "tasks" / "queue",
            discovery_candidates=root / "tasks" / "discovery-candidates",
            queries=root / "queries",
            evals=root / "_evals",
            projects=root / "projects",
            proposals=root / "proposals",
            bases=root / "bases",
            indexes=indexes,
            exports=exports,
            operations=root / "_operations",
            operation_runs=root / "_operations" / "runs",
            feedback=root / "_feedback",
            feedback_ratings=root / "_feedback" / "ratings",
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
            self.raw_metadata,
            self.raw_discovery,
            self.pdfs,
            self.papers,
            self.paper_digests,
            self.runs,
            self.topics,
            self.concepts,
            self.syntheses,
            self.tasks,
            self.task_queue,
            self.discovery_candidates,
            self.queries,
            self.evals,
            self.projects,
            self.proposals,
            self.bases,
            self.indexes,
            self.exports,
            self.operations,
            self.operation_runs,
            self.feedback,
            self.feedback_ratings,
        ):
            path.mkdir(parents=True, exist_ok=True)


def clean_markdown_text(text: str | None) -> str:
    if not text:
        return ""
    normalized = text.replace("\r\n", "\n").strip()
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized


def normalize_copied_abstract(text: str | None) -> str:
    if not text:
        return ""
    normalized = (
        text.replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\u00a0", " ")
        .replace("\u00ad", "")
    )
    normalized = re.split(r"(?im)^\s*keywords?\s*[:.]", normalized, maxsplit=1)[0]
    normalized = re.sub(r"(?is)^\s*abstract\s*[\.:;—-]\s*", "", normalized.strip())
    normalized = re.sub(r"([A-Za-z])[-‐‑‒–—]\s*\n\s*([A-Za-z])", r"\1\2", normalized)
    paragraphs = re.split(r"\n\s*\n+", normalized)
    cleaned: list[str] = []
    for paragraph in paragraphs:
        lines = [line.strip() for line in paragraph.splitlines() if line.strip()]
        if not lines:
            continue
        joined = " ".join(lines)
        joined = re.sub(r"\s+", " ", joined)
        joined = re.sub(r"\s+([,.;:?!])", r"\1", joined)
        cleaned.append(joined.strip())
    return "\n\n".join(cleaned)


def normalize_keywords(values: Iterable[str] | str | None) -> list[str]:
    if not values:
        return []
    raw_values = [values] if isinstance(values, str) else list(values)
    normalized_values: list[str] = []
    seen: set[str] = set()
    for raw_value in raw_values:
        if raw_value is None:
            continue
        value = str(raw_value)
        value = (
            value.replace("\r\n", "\n")
            .replace("\r", "\n")
            .replace("\u00a0", " ")
            .replace("\u00ad", "")
        )
        value = re.sub(r"([A-Za-z])[-‐‑‒–—]\s*\n\s*([A-Za-z])", r"\1\2", value)
        value = re.sub(r"(?im)^\s*(keywords?|index terms)\s*[\.:;‐‑‒–—-]\s*", "", value)
        for token in re.split(r"\s*(?:[,;|]|[·•])\s*", value):
            cleaned = re.sub(r"\s+", " ", token).strip(" \t\n\r.:;,-")
            if not cleaned:
                continue
            key = normalize_title(cleaned)
            if (
                not key
                or key in {"keyword", "keywords", "index terms"}
                or len(cleaned) > 100
                or len(cleaned.split()) > 10
                or key in seen
            ):
                continue
            seen.add(key)
            normalized_values.append(cleaned)
    return normalized_values


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


def _format_title_token(token: str) -> str:
    normalized = token.strip("-_ ")
    if not normalized:
        return ""
    if normalized.isupper() and len(normalized) <= 4:
        return normalized
    if normalized.casefold() in {"ar", "vr", "xr", "od", "gps", "llm"}:
        return normalized.upper()
    return normalized.replace("-", " ").title()


def _topic_phrase_from_prompt(prompt: str) -> str:
    cleaned = re.sub(r"\s+", " ", prompt or "").strip()
    patterns = [
        r"\b(?:proposal|project|research)\s+on\s+(.+?)(?:\.|;|:|\bprioritize\b|$)",
        r"\bpapers?\s+on\s+(.+?)(?:\.|;|:|\bprioritize\b|$)",
        r"\bsources?\s+on\s+(.+?)(?:\.|;|:|\bprioritize\b|$)",
        r"\babout\s+(.+?)(?:\.|;|:|\bprioritize\b|$)",
    ]
    for pattern in patterns:
        match = re.search(pattern, cleaned, flags=re.IGNORECASE)
        if match:
            return match.group(1)
    return cleaned


def infer_run_title(prompt: str, *, max_words: int = 6) -> str:
    phrase = _topic_phrase_from_prompt(prompt)
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9-]*", phrase)
    selected: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        key = token.casefold()
        if key in RUN_TITLE_STOPWORDS or len(key) <= 2:
            continue
        if key not in seen:
            seen.add(key)
            selected.append(token)
        if len(selected) >= max_words:
            break
    if not selected:
        selected = [token for token in tokens[:max_words] if len(token) > 2]
    title = " ".join(_format_title_token(token) for token in selected).strip()
    return title or "Scholar Labs Run"


def run_display_title(title: str | None, prompt: str) -> str:
    cleaned = clean_markdown_text(title)
    return cleaned if cleaned else infer_run_title(prompt)


def run_note_stem(date: str, title: str | None, prompt: str) -> str:
    display_title = run_display_title(title, prompt)
    return sanitize_filename(display_title, max_length=80)


def sanitize_filename(value: str, *, max_length: int = 120) -> str:
    cleaned = re.sub(r"[\x00-\x1f/\\:]+", " - ", value or "").strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = cleaned.strip(". ")
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length].rstrip(" .-_")
    return cleaned or "Untitled"


def run_note_filename(
    date: str,
    title: str | None,
    prompt: str,
    note_file: str | None = None,
) -> str:
    if note_file:
        cleaned = sanitize_filename(Path(note_file).name)
        return cleaned if cleaned.endswith(".md") else f"{cleaned}.md"
    return f"{run_note_stem(date, title, prompt)}.md"


def run_note_path(
    run_slug: str,
    date: str,
    title: str | None,
    prompt: str,
    note_file: str | None = None,
) -> str:
    return f"runs/{run_slug}/{run_note_filename(date, title, prompt, note_file)}"


def humanize_run_note_stem(stem: str, date: str | None = None) -> str:
    cleaned = stem
    if date and cleaned.startswith(date):
        cleaned = cleaned[len(date) :].lstrip("-_ ")
    if " " in cleaned:
        return cleaned.strip()
    return " ".join(_format_title_token(token) for token in re.split(r"[-_]+", cleaned) if token)


def normalize_title(text: str | None) -> str:
    ascii_text = unidecode(clean_paper_title(text).casefold())
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
    words = re.findall(r"[A-Za-z0-9]+", unidecode(clean_paper_title(title)))
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
    preferred = slugify_text(citekey or clean_paper_title(title))
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
    used = {item for item in existing_names if item}
    if name not in used:
        return name
    counter = 2
    while f"{safe_stem}-{counter}.pdf" in used:
        counter += 1
    return f"{safe_stem}-{counter}.pdf"


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
    frontmatter = _normalize_yaml_loaded_scalars(yaml.safe_load(match.group(1)) or {})
    body = match.group(2)
    return frontmatter, body


def _normalize_yaml_loaded_scalars(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, list):
        return [_normalize_yaml_loaded_scalars(item) for item in value]
    if isinstance(value, dict):
        return {key: _normalize_yaml_loaded_scalars(item) for key, item in value.items()}
    return value


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
    abstract_section = sections.get("Abstract", "").strip()
    if abstract_section and abstract_section != "No abstract yet.":
        frontmatter["abstract"] = abstract_section
    keywords_section = sections.get("Keywords", "").strip()
    no_publication_keywords = "No publication keywords listed in the source."
    if keywords_section == no_publication_keywords:
        frontmatter.setdefault("publication_keywords_status", "absent")
    elif keywords_section and not frontmatter.get("keywords"):
        frontmatter["keywords"] = normalize_keywords(
            line.removeprefix("- ").strip()
            for line in keywords_section.splitlines()
            if line.strip()
            and line.strip() not in {"No keywords captured yet.", no_publication_keywords}
        )
    summary_section = (
        sections.get("Scholar Labs summary", "")
        or sections.get("Scholar Labs Summary", "")
        or sections.get("Summary", "")
    )
    summary_section = re.split(r"(?m)^###\s+", summary_section, maxsplit=1)[0]
    card = SourceCard(
        slug=path.stem,
        summary=summary_section.strip() or "No summary yet.",
        why_this_source_matters=parse_rationale_points(sections.get("Why this source matters", "")),
        notes=sections.get("Notes", "").strip(),
        **frontmatter,
    )
    if not card.authors and card.authors_preview:
        card.authors = parse_people(card.authors_preview)
    if card.doi:
        card.doi = normalize_doi(card.doi)
    return card


def _prefer_summary(text: str | None) -> bool:
    cleaned = clean_markdown_text(text)
    return bool(cleaned and cleaned != "No summary yet." and cleaned != "No summary provided.")


def _summary_source_from_run_result(run: RunRecord, result: object) -> SummarySource | None:
    summary = clean_markdown_text(getattr(result, "summary", None))
    if not _prefer_summary(summary):
        return None
    return SummarySource(
        run=run_note_path(run.slug, run.date, run.title, run.prompt, run.note_file),
        prompt=run.prompt,
        rank=getattr(result, "rank", None),
        summary=summary,
        rationale_points=list(getattr(result, "rationale_points", []) or []),
    )


def _merge_summary_sources(
    existing: list[SummarySource],
    incoming: list[SummarySource],
) -> list[SummarySource]:
    merged: list[SummarySource] = []
    by_run: dict[str, int] = {}
    seen_without_run: set[str] = set()
    for source in [*existing, *incoming]:
        source = source.model_copy(deep=True)
        source.summary = clean_markdown_text(source.summary)
        if not _prefer_summary(source.summary):
            continue
        if source.run:
            if source.run in by_run:
                merged[by_run[source.run]] = source
            else:
                by_run[source.run] = len(merged)
                merged.append(source)
            continue
        key = normalize_title(source.summary)
        if key not in seen_without_run:
            seen_without_run.add(key)
            merged.append(source)
    return merged


def _apply_run_summary_sources(paths: VaultPaths, cards: list[SourceCard]) -> None:
    cards_by_slug = {card.slug: card for card in cards}
    incoming_by_slug: dict[str, list[SummarySource]] = {card.slug: [] for card in cards}
    for run in load_run_records(paths):
        for result in run.results:
            if not result.paper_card:
                continue
            card = cards_by_slug.get(Path(result.paper_card).stem)
            if card is None:
                continue
            source = _summary_source_from_run_result(run, result)
            if source is not None:
                incoming_by_slug[card.slug].append(source)
    for card in cards:
        merged_sources = _merge_summary_sources(
            card.summary_sources,
            incoming_by_slug.get(card.slug, []),
        )
        if not merged_sources and _prefer_summary(card.summary):
            merged_sources = [
                SummarySource(
                    run=run_ref,
                    summary=card.summary,
                    rationale_points=card.why_this_source_matters,
                )
                for run_ref in card.discovered_in
            ]
        card.summary_sources = merged_sources


def load_source_cards(paths: VaultPaths) -> list[SourceCard]:
    cards: list[SourceCard] = []
    for path in sorted(paths.papers.glob("*.md")):
        cards.append(load_source_card(path))
    _apply_run_summary_sources(paths, cards)
    return cards


def _apply_run_markdown_title(run: RunRecord, run_dir: Path) -> RunRecord:
    markdown_files = sorted(path for path in run_dir.glob("*.md") if path.name != "index.md")
    if not markdown_files:
        return run

    generated_slug_style = re.compile(r"^\d{4}-\d{2}-\d{2}_[a-z0-9-]+$")
    matching_note: Path | None = None
    for note in markdown_files:
        frontmatter, _ = read_frontmatter_markdown(note)
        if frontmatter.get("type") == "scholar_labs_run" and frontmatter.get("run_id") == run.slug:
            matching_note = note
            manually_named = note.stem != run.slug and not generated_slug_style.match(note.stem)
            if manually_named:
                run.title = humanize_run_note_stem(note.stem, run.date)
                run.note_file = note.name
            elif isinstance(frontmatter.get("title"), str) and frontmatter["title"].strip():
                run.title = frontmatter["title"].strip()
            return run
    if matching_note is None and len(markdown_files) == 1:
        note = markdown_files[0]
        if note.stem != run.slug:
            run.title = humanize_run_note_stem(note.stem, run.date)
            if not generated_slug_style.match(note.stem):
                run.note_file = note.name
    return run


def load_run_records(paths: VaultPaths) -> list[RunRecord]:
    runs: list[RunRecord] = []
    for path in sorted(paths.runs.glob("*/index.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        runs.append(_apply_run_markdown_title(RunRecord.model_validate(data), path.parent))
    return runs


def load_import_manifests(paths: VaultPaths) -> list[ImportManifest]:
    manifests: list[ImportManifest] = []
    for path in sorted(paths.runs.glob("*/import-manifest.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        manifests.append(ImportManifest.model_validate(data))
    return manifests
