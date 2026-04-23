from __future__ import annotations

import hashlib
import html
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from rapidfuzz import fuzz

from .bibtex import card_to_bibtex
from .matcher import extract_pdf_text_excerpt, read_pdf_metadata, score_title_match
from .models import SourceCard
from .sources import (
    DOI_RE,
    VaultPaths,
    first_author_surname,
    normalize_doi,
    normalize_title,
    parse_people,
    write_text,
)

OnlyMode = Literal["all", "missing-doi", "missing-bibtex", "missing-abstract"]
FetchJson = Callable[[str, Path, bool], dict[str, Any] | list[Any] | None]
FetchText = Callable[[str, Path, bool, dict[str, str]], str | None]
EnrichmentProgress = Callable[[SourceCard, int, int, str], None]

GENERATED_CITATION_STATUSES = {"generated", "verified"}
FAILED_CITATION_STATUSES = {"ambiguous", "unresolved"}
MAX_RETRIES = 3
ABSTRACT_SOURCE_RANK = {
    "pdf_extracted": 1,
    "openalex_reconstructed": 2,
    "datacite": 3,
    "europepmc": 4,
    "crossref": 5,
    "manual": 6,
}


@dataclass(frozen=True)
class EnrichmentOptions:
    only: OnlyMode = "all"
    citekey: str | None = None
    refresh: bool = False
    abstracts: bool = False
    refresh_abstracts: bool = False
    retry_failed: bool = False
    dry_run: bool = False
    force: bool = False


@dataclass(frozen=True)
class CitationCandidate:
    doi: str | None
    title: str
    authors: list[str]
    year: int | None = None
    venue: str | None = None
    url: str | None = None
    source: str = ""
    raw: dict[str, Any] | None = None
    score: int = 0


@dataclass(frozen=True)
class AbstractCandidate:
    text: str
    source: str
    source_url: str | None = None
    confidence: float = 0.0
    metadata: CitationCandidate | None = None


@dataclass(frozen=True)
class EnrichmentResult:
    citekey: str
    status: str
    message: str
    changed: bool = False
    skipped: bool = False
    title: str | None = None
    paper_path: str | None = None
    doi: str | None = None
    source: str | None = None
    missing_fields: tuple[str, ...] = ()


def now_iso() -> str:
    return datetime.now().astimezone().replace(microsecond=0).isoformat()


def _result_with_card_context(result: EnrichmentResult, card: SourceCard) -> EnrichmentResult:
    source = card.abstract_source or card.citation_source or card.doi_source
    return replace(
        result,
        title=card.title,
        paper_path=f"papers/{card.slug}.md",
        doi=card.doi,
        source=source,
        missing_fields=tuple(card.enrichment_missing),
    )


def extract_doi_from_text(text: str | None) -> str | None:
    if not text:
        return None
    match = DOI_RE.search(text)
    return normalize_doi(match.group(1)) if match else None


def card_fingerprint(card: SourceCard) -> str:
    payload = {
        "title": card.title,
        "authors": card.authors,
        "authors_preview": card.authors_preview,
        "year": card.year,
        "venue": card.venue,
        "doi": normalize_doi(card.doi),
        "url": card.url,
        "pdf": card.pdf,
    }
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def abstract_fingerprint(card: SourceCard) -> str:
    payload = {
        "title": card.title,
        "authors": card.authors or None,
        "authors_preview": card.authors_preview,
        "year": card.year,
        "doi": normalize_doi(card.doi),
        "pdf": card.pdf,
    }
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def should_skip_card(card: SourceCard, options: EnrichmentOptions) -> str | None:
    fingerprint = card_fingerprint(card)
    requested_refresh = options.refresh or card.enrichment_refresh
    if options.citekey and card.citekey != options.citekey:
        return "citekey filter"
    if card.metadata_lock and not options.force:
        return "metadata_lock"
    if card.citation_status == "verified" and not requested_refresh:
        return "citation verified"
    if (
        options.only == "missing-doi"
        and card.doi
        and card.doi_status
        in {
            "detected",
            "resolved",
            "verified",
        }
    ):
        return "doi present"
    if options.only == "missing-bibtex" and card.citation_status in GENERATED_CITATION_STATUSES:
        return "citation present"
    if (
        card.citation_status in GENERATED_CITATION_STATUSES
        and card.citation_input_fingerprint == fingerprint
        and not requested_refresh
    ):
        return "fingerprint unchanged"
    if (
        card.citation_status == "unresolved"
        and card.citation_retries >= MAX_RETRIES
        and not options.retry_failed
        and not requested_refresh
    ):
        return "retry limit reached"
    return None


def should_skip_abstract_card(card: SourceCard, options: EnrichmentOptions) -> str | None:
    fingerprint = abstract_fingerprint(card)
    requested_refresh = options.refresh_abstracts or card.enrichment_refresh
    if options.citekey and card.citekey != options.citekey:
        return "citekey filter"
    if card.metadata_lock and not options.force:
        return "metadata_lock"
    if (card.abstract_lock or card.abstract_status == "manual_lock") and not options.force:
        return "abstract_lock"
    if _has_manual_abstract(card) and not options.force:
        return "manual abstract"
    if (
        options.only == "missing-abstract"
        and card.abstract
        and card.abstract_status in {"resolved", "verified"}
        and not requested_refresh
    ):
        return "abstract present"
    if (
        card.abstract_status in {"resolved", "verified"}
        and card.abstract
        and card.abstract_input_fingerprint == fingerprint
        and not requested_refresh
    ):
        return "abstract fingerprint unchanged"
    if (
        card.abstract_status in {"ambiguous", "unresolved"}
        and card.abstract_input_fingerprint == fingerprint
        and not options.retry_failed
        and not requested_refresh
    ):
        return "abstract previously failed"
    return None


def metadata_dir(paths: VaultPaths, card: SourceCard) -> Path:
    key = card.citekey or card.slug
    return paths.raw_metadata / key


def _card_pdf_path(paths: VaultPaths, card: SourceCard) -> Path | None:
    if not card.pdf:
        return None
    pdf_path = Path(card.pdf)
    if not pdf_path.is_absolute():
        pdf_path = paths.vault / card.pdf
    return pdf_path if pdf_path.exists() else None


def detect_local_doi(paths: VaultPaths, card: SourceCard) -> tuple[str | None, str | None, float]:
    if card.doi:
        return normalize_doi(card.doi), "frontmatter", 1.0

    candidates: list[tuple[str | None, str, float]] = []
    candidates.append((extract_doi_from_text(card.url), "url", 0.9))
    for link in card.links:
        candidates.append((extract_doi_from_text(link.url), "link", 0.9))

    pdf_path = _card_pdf_path(paths, card)
    if pdf_path:
        metadata = read_pdf_metadata(pdf_path)
        metadata_text = "\n".join(value or "" for value in metadata.values())
        candidates.append((extract_doi_from_text(metadata_text), "pdf_metadata", 0.95))
        text_excerpt = extract_pdf_text_excerpt(pdf_path)
        candidates.append((extract_doi_from_text(text_excerpt), "pdf_text", 0.95))

    for doi, source, confidence in candidates:
        if doi:
            return doi, source, confidence
    return None, None, 0.0


def _has_manual_abstract(card: SourceCard) -> bool:
    if not card.abstract:
        return False
    if card.abstract_lock or card.abstract_status == "manual_lock":
        return True
    return not card.abstract_source


def clean_provider_abstract(value: str | None) -> str:
    if not value:
        return ""
    cleaned = html.unescape(value)
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = re.sub(r"\s+([,.;:])", r"\1", cleaned)
    return cleaned


def reconstruct_openalex_abstract(inverted_index: dict[str, Any] | None) -> str:
    if not inverted_index:
        return ""
    positioned: list[tuple[int, str]] = []
    for token, positions in inverted_index.items():
        if not isinstance(positions, list):
            continue
        for position in positions:
            if isinstance(position, int):
                positioned.append((position, token))
    if not positioned:
        return ""
    words = [token for _, token in sorted(positioned)]
    return clean_provider_abstract(" ".join(words))


def extract_pdf_abstract(text: str | None) -> str:
    if not text:
        return ""
    normalized = text.replace("\r\n", "\n")
    match = re.search(r"(?im)^\s*(abstract|summary)\s*[:—-]?\s*$", normalized)
    if not match:
        match = re.search(r"(?im)\babstract\s*[:—-]\s+", normalized)
    if not match:
        return ""

    start = match.end()
    remaining = normalized[start:]
    stop = re.search(
        r"(?im)^\s*(keywords?|index terms|introduction|1\.?\s+introduction|i\.?\s+introduction|"
        r"\d+\s+[A-Z][A-Za-z ]{2,}|references)\b",
        remaining,
    )
    excerpt = remaining[: stop.start()] if stop else remaining
    cleaned = clean_provider_abstract(excerpt)
    if len(cleaned.split()) < 20:
        return ""
    return cleaned


def _abstract_rank(source: str | None) -> int:
    return ABSTRACT_SOURCE_RANK.get((source or "").casefold(), 0)


def _abstracts_materially_disagree(left: str, right: str) -> bool:
    left_norm = normalize_title(left)
    right_norm = normalize_title(right)
    if len(left_norm) < 80 or len(right_norm) < 80:
        return False
    if left_norm in right_norm or right_norm in left_norm:
        return False
    return fuzz.token_set_ratio(left_norm, right_norm) < 65


def _abstract_metadata_consistent(card: SourceCard, candidate: CitationCandidate | None) -> bool:
    if candidate is None:
        return True
    if card.doi and candidate.doi and normalize_doi(card.doi) != normalize_doi(candidate.doi):
        return False
    if candidate.doi and card.doi and normalize_doi(candidate.doi) == normalize_doi(card.doi):
        return candidate.score >= 70
    return candidate.score >= 88


def _best_abstract_candidate(
    card: SourceCard,
    candidates: list[AbstractCandidate],
) -> tuple[AbstractCandidate | None, bool]:
    consistent = [
        candidate
        for candidate in candidates
        if candidate.text and _abstract_metadata_consistent(card, candidate.metadata)
    ]
    if not consistent:
        return None, False
    ranked = sorted(
        consistent,
        key=lambda candidate: (
            _abstract_rank(candidate.source),
            candidate.confidence,
            len(candidate.text),
        ),
        reverse=True,
    )
    best = ranked[0]
    for other in ranked[1:]:
        if (
            (_abstract_rank(best.source) >= 4 or best.confidence >= 0.94)
            and (_abstract_rank(other.source) >= 4 or other.confidence >= 0.94)
            and _abstracts_materially_disagree(best.text, other.text)
        ):
            return best, True
    return best, False


def _first_author(card: SourceCard) -> str | None:
    authors = card.authors or parse_people(card.authors_preview)
    if not authors:
        return None
    return first_author_surname(authors)


def score_metadata_candidate(card: SourceCard, candidate: CitationCandidate) -> int:
    score = 0
    title_score = score_title_match(card.title, candidate.title)
    score += int(title_score * 0.65)
    expected_author = _first_author(card)
    candidate_author = first_author_surname(candidate.authors) if candidate.authors else None
    if expected_author and candidate_author and expected_author == candidate_author:
        score += 15
    elif expected_author and candidate_author:
        score -= 10
    if card.year and candidate.year:
        delta = abs(card.year - candidate.year)
        if delta == 0:
            score += 12
        elif delta <= 1:
            score += 6
        else:
            score -= min(delta * 2, 12)
    if candidate.doi:
        score += 8
    return max(0, min(score, 100))


def crossref_candidates(payload: dict[str, Any], card: SourceCard) -> list[CitationCandidate]:
    items = (payload.get("message") or {}).get("items") or []
    candidates: list[CitationCandidate] = []
    for item in items:
        titles = item.get("title") or []
        title = str(titles[0]) if titles else ""
        if not title:
            continue
        authors = []
        for author in item.get("author") or []:
            name = " ".join(
                part for part in [author.get("given"), author.get("family")] if part
            ).strip()
            if name:
                authors.append(name)
        year = _date_parts_year(item.get("published-print") or item.get("published-online"))
        candidate = CitationCandidate(
            doi=normalize_doi(item.get("DOI")),
            title=title,
            authors=authors,
            year=year,
            venue=(item.get("container-title") or [None])[0],
            url=item.get("URL"),
            source="crossref",
            raw=item,
        )
        candidates.append(
            candidate.__class__(
                **{**candidate.__dict__, "score": score_metadata_candidate(card, candidate)}
            )
        )
    return sorted(candidates, key=lambda item: item.score, reverse=True)


def openalex_candidates(payload: dict[str, Any], card: SourceCard) -> list[CitationCandidate]:
    results = payload.get("results") or []
    candidates: list[CitationCandidate] = []
    for item in results:
        title = item.get("title") or item.get("display_name") or ""
        authors = [
            authorship.get("author", {}).get("display_name", "")
            for authorship in item.get("authorships") or []
        ]
        authors = [author for author in authors if author]
        primary_location = item.get("primary_location") or {}
        source = primary_location.get("source") or {}
        candidate = CitationCandidate(
            doi=normalize_doi(item.get("doi")),
            title=title,
            authors=authors,
            year=item.get("publication_year"),
            venue=source.get("display_name"),
            url=primary_location.get("landing_page_url") or item.get("id"),
            source="openalex",
            raw=item,
        )
        candidates.append(
            candidate.__class__(
                **{**candidate.__dict__, "score": score_metadata_candidate(card, candidate)}
            )
        )
    return sorted(candidates, key=lambda item: item.score, reverse=True)


def datacite_candidate(payload: dict[str, Any], card: SourceCard) -> CitationCandidate | None:
    data = payload.get("data") or {}
    attributes = data.get("attributes") or {}
    titles = attributes.get("titles") or []
    title = (titles[0] or {}).get("title") if titles else None
    if not title:
        return None
    authors = [
        creator.get("name", "")
        for creator in attributes.get("creators") or []
        if creator.get("name")
    ]
    candidate = CitationCandidate(
        doi=normalize_doi(attributes.get("doi")),
        title=title,
        authors=authors,
        year=_safe_int(attributes.get("publicationYear")),
        venue=attributes.get("publisher"),
        url=attributes.get("url"),
        source="datacite",
        raw=data,
    )
    return candidate.__class__(
        **{**candidate.__dict__, "score": score_metadata_candidate(card, candidate)}
    )


def europepmc_candidates(payload: dict[str, Any], card: SourceCard) -> list[CitationCandidate]:
    results = ((payload.get("resultList") or {}).get("result")) or []
    candidates: list[CitationCandidate] = []
    for item in results:
        candidate = CitationCandidate(
            doi=normalize_doi(item.get("doi")),
            title=item.get("title") or "",
            authors=[item.get("authorString", "")] if item.get("authorString") else [],
            year=_safe_int(item.get("pubYear")),
            venue=item.get("journalTitle"),
            url=item.get("fullTextUrlList", {}).get("fullTextUrl", [{}])[0].get("url")
            if item.get("fullTextUrlList")
            else None,
            source="europepmc",
            raw=item,
        )
        if candidate.title:
            candidates.append(
                candidate.__class__(
                    **{**candidate.__dict__, "score": score_metadata_candidate(card, candidate)}
                )
            )
    return sorted(candidates, key=lambda item: item.score, reverse=True)


def _crossref_item_candidate(item: dict[str, Any], card: SourceCard) -> CitationCandidate | None:
    titles = item.get("title") or []
    title = str(titles[0]) if titles else ""
    if not title:
        return None
    authors = []
    for author in item.get("author") or []:
        name = " ".join(
            part for part in [author.get("given"), author.get("family")] if part
        ).strip()
        if name:
            authors.append(name)
    year = _date_parts_year(
        item.get("published-print")
        or item.get("published-online")
        or item.get("published")
        or item.get("issued")
    )
    candidate = CitationCandidate(
        doi=normalize_doi(item.get("DOI")),
        title=title,
        authors=authors,
        year=year,
        venue=(item.get("container-title") or [None])[0],
        url=item.get("URL"),
        source="crossref",
        raw=item,
    )
    return candidate.__class__(
        **{**candidate.__dict__, "score": score_metadata_candidate(card, candidate)}
    )


def crossref_abstract_candidates(
    payload: dict[str, Any],
    card: SourceCard,
) -> list[AbstractCandidate]:
    message = payload.get("message") or {}
    items = message.get("items") if isinstance(message, dict) else None
    raw_items = items if isinstance(items, list) else [message]
    candidates: list[AbstractCandidate] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        abstract = clean_provider_abstract(item.get("abstract"))
        if not abstract:
            continue
        metadata = _crossref_item_candidate(item, card)
        if metadata is None:
            continue
        candidates.append(
            AbstractCandidate(
                text=abstract,
                source="crossref",
                source_url=item.get("URL"),
                confidence=min(1.0, max(metadata.score / 100, 0.9 if card.doi else 0.0)),
                metadata=metadata,
            )
        )
    return candidates


def europepmc_abstract_candidates(
    payload: dict[str, Any],
    card: SourceCard,
) -> list[AbstractCandidate]:
    candidates: list[AbstractCandidate] = []
    for metadata in europepmc_candidates(payload, card):
        item = metadata.raw or {}
        abstract = clean_provider_abstract(item.get("abstractText"))
        if not abstract:
            continue
        candidates.append(
            AbstractCandidate(
                text=abstract,
                source="europepmc",
                source_url=metadata.url,
                confidence=metadata.score / 100,
                metadata=metadata,
            )
        )
    return candidates


def openalex_abstract_candidates(
    payload: dict[str, Any],
    card: SourceCard,
) -> list[AbstractCandidate]:
    raw_items = payload.get("results") if isinstance(payload.get("results"), list) else [payload]
    candidates: list[AbstractCandidate] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        abstract = reconstruct_openalex_abstract(item.get("abstract_inverted_index"))
        if not abstract:
            continue
        title = item.get("title") or item.get("display_name") or ""
        authors = [
            authorship.get("author", {}).get("display_name", "")
            for authorship in item.get("authorships") or []
        ]
        authors = [author for author in authors if author]
        primary_location = item.get("primary_location") or {}
        source = primary_location.get("source") or {}
        metadata = CitationCandidate(
            doi=normalize_doi(item.get("doi")),
            title=title,
            authors=authors,
            year=item.get("publication_year"),
            venue=source.get("display_name"),
            url=primary_location.get("landing_page_url") or item.get("id"),
            source="openalex",
            raw=item,
        )
        metadata = metadata.__class__(
            **{**metadata.__dict__, "score": score_metadata_candidate(card, metadata)}
        )
        candidates.append(
            AbstractCandidate(
                text=abstract,
                source="openalex_reconstructed",
                source_url=metadata.url,
                confidence=metadata.score / 100,
                metadata=metadata,
            )
        )
    return candidates


def datacite_abstract_candidates(
    payload: dict[str, Any],
    card: SourceCard,
) -> list[AbstractCandidate]:
    metadata = datacite_candidate(payload, card)
    if metadata is None:
        return []
    data = payload.get("data") or {}
    attributes = data.get("attributes") or {}
    descriptions = attributes.get("descriptions") or []
    chosen = ""
    for description in descriptions:
        if not isinstance(description, dict):
            continue
        value = clean_provider_abstract(description.get("description"))
        if not value:
            continue
        if (description.get("descriptionType") or "").casefold() == "abstract":
            chosen = value
            break
        chosen = chosen or value
    if not chosen:
        return []
    return [
        AbstractCandidate(
            text=chosen,
            source="datacite",
            source_url=attributes.get("url"),
            confidence=metadata.score / 100,
            metadata=metadata,
        )
    ]


def _safe_int(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _date_parts_year(value: dict[str, Any] | None) -> int | None:
    parts = (value or {}).get("date-parts") or []
    if parts and parts[0]:
        return _safe_int(parts[0][0])
    return None


def select_candidate(
    candidates: list[CitationCandidate],
) -> tuple[CitationCandidate | None, bool]:
    if not candidates:
        return None, False
    best = candidates[0]
    second = candidates[1] if len(candidates) > 1 else None
    ambiguous = best.score < 88 or (second is not None and best.score - second.score < 8)
    return best, ambiguous


def normalize_bibtex_for_card(card: SourceCard, raw_bibtex: str | None = None) -> str:
    if raw_bibtex:
        normalized = raw_bibtex.strip()
        key = card.citekey or card.slug
        normalized = rekey_bibtex(normalized, key)
    else:
        normalized = card_to_bibtex(card) or ""
    return normalized.rstrip() + "\n" if normalized else ""


def rekey_bibtex(raw_bibtex: str, key: str) -> str:
    return re.sub(r"^@\s*([^{]+)\{[^,]+,", rf"@\1{{{key},", raw_bibtex.strip(), count=1)


def _author_surnames(authors: list[str]) -> list[str]:
    surnames: list[str] = []
    for author in authors:
        surname = first_author_surname([author])
        if surname and surname != "source":
            surnames.append(surname)
    return surnames


def _is_abbreviated_author_list(authors: list[str]) -> bool:
    if not authors:
        return True
    initials = 0
    for author in authors:
        tokens = [token for token in re.split(r"\s+", author.replace(".", " ").strip()) if token]
        if len(tokens) >= 2 and all(len(token) <= 2 for token in tokens[:-1]):
            initials += 1
    return initials >= max(1, len(authors) - 1)


def _is_preview_venue(value: str | None) -> bool:
    if not value:
        return True
    stripped = value.strip()
    return "…" in stripped or "..." in stripped or bool(re.search(r",\s*(19|20)\d{2}$", stripped))


def _is_scholar_citation_url(value: str | None) -> bool:
    if not value:
        return True
    parsed = urllib.parse.urlparse(value)
    host = parsed.netloc.lower()
    return (
        "scholar.google" in host
        and ("scholar.bib" in parsed.path or "output=citation" in parsed.query)
    )


def _metadata_missing_fields(card: SourceCard) -> list[str]:
    missing: list[str] = []
    if not normalize_doi(card.doi):
        missing.append("doi")
    if not card.authors and not parse_people(card.authors_preview):
        missing.append("authors")
    if not card.year:
        missing.append("year")
    if _is_preview_venue(card.venue):
        missing.append("venue")
    return missing


def _update_enrichment_completeness(card: SourceCard) -> None:
    missing = _metadata_missing_fields(card)
    card.enrichment_missing = missing
    if card.metadata_lock:
        card.enrichment_status = "manual_lock"
    elif card.citation_status == "ambiguous" or card.doi_status == "ambiguous":
        card.enrichment_status = "ambiguous"
    elif missing:
        card.enrichment_status = "incomplete"
    elif card.citation_status in GENERATED_CITATION_STATUSES:
        card.enrichment_status = "complete"
    else:
        card.enrichment_status = "missing"


def _candidate_is_consistent(card: SourceCard, candidate: CitationCandidate) -> bool:
    if not candidate.title:
        return False
    if card.doi and candidate.doi and normalize_doi(card.doi) != normalize_doi(candidate.doi):
        return False
    return candidate.score >= 88


def _is_published_metadata_candidate(candidate: CitationCandidate) -> bool:
    work_type = ((candidate.raw or {}).get("type") or "").casefold()
    if work_type in {"posted-content", "preprint"}:
        return False
    if work_type and work_type not in {
        "journal-article",
        "proceedings-article",
        "book-chapter",
        "monograph",
    }:
        return False
    return bool(candidate.doi and candidate.venue and not _is_preview_venue(candidate.venue))


def _published_version_candidate(
    card: SourceCard,
    candidates: list[CitationCandidate],
) -> CitationCandidate | None:
    viable = [
        candidate
        for candidate in candidates
        if _is_published_metadata_candidate(candidate)
        and candidate.score >= 88
        and score_title_match(card.title, candidate.title) >= 95
    ]
    if not viable:
        return None
    current_doi = normalize_doi(card.doi)
    for candidate in viable:
        if current_doi and normalize_doi(candidate.doi) == current_doi:
            return candidate
    return max(viable, key=lambda candidate: (candidate.score, len(candidate.venue or "")))


def _should_search_for_published_version(card: SourceCard) -> bool:
    return bool(card.doi and _is_preview_venue(card.venue))


def _promote_metadata_from_candidate(card: SourceCard, candidate: CitationCandidate) -> bool:
    if not _candidate_is_consistent(card, candidate):
        return False

    changed = False
    if candidate.title and normalize_title(candidate.title) == normalize_title(card.title):
        if candidate.title != card.title:
            card.title = candidate.title
            changed = True

    if candidate.authors:
        current_surnames = _author_surnames(card.authors)
        candidate_surnames = _author_surnames(candidate.authors)
        same_surnames = (
            current_surnames
            and candidate_surnames
            and current_surnames[: len(candidate_surnames)] == candidate_surnames
        )
        if not card.authors or _is_abbreviated_author_list(card.authors) or same_surnames:
            if card.authors != candidate.authors:
                card.authors = candidate.authors
                changed = True

    if candidate.year and not card.year:
        card.year = candidate.year
        changed = True

    if candidate.venue and (
        _is_preview_venue(card.venue)
        or normalize_title(candidate.venue) == normalize_title(card.venue)
        or (card.venue is not None and len(candidate.venue) > len(card.venue))
    ):
        if candidate.venue != card.venue:
            card.venue = candidate.venue
            changed = True

    if candidate.url and _is_scholar_citation_url(card.url):
        if candidate.url != card.url:
            card.url = candidate.url
            changed = True

    return changed


def _finalize_citation_success(
    card: SourceCard,
    *,
    checked_at: str,
    candidates: list[CitationCandidate],
) -> None:
    if card.doi_status in {"missing", "detected"}:
        card.doi_status = "resolved"
    card.citation_status = "verified" if _strong_consistency(card, candidates) else "generated"
    card.citation_source = "doi"
    card.citation_enriched_at = checked_at
    card.citation_last_checked = checked_at
    card.citation_input_fingerprint = card_fingerprint(card)
    _update_enrichment_completeness(card)
    card.citation_skip_reason = (
        f"incomplete metadata: {', '.join(card.enrichment_missing)}"
        if card.enrichment_missing
        else None
    )
    card.enrichment_refresh = False


def _http_json(url: str, cache_path: Path, refresh: bool) -> dict[str, Any] | list[Any] | None:
    if cache_path.exists() and not refresh:
        return json.loads(cache_path.read_text(encoding="utf-8"))
    text = _http_text(url, cache_path, refresh, {"Accept": "application/json"})
    return json.loads(text) if text else None


def _http_text(url: str, cache_path: Path, refresh: bool, headers: dict[str, str]) -> str | None:
    if cache_path.exists() and not refresh:
        return cache_path.read_text(encoding="utf-8")
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    mailto = os.environ.get("SCHOLAR_VAULT_MAILTO", "scholar-vault@example.invalid")
    request_headers = {
        "User-Agent": f"scholar-vault/0.1 (mailto:{mailto})",
        **headers,
    }
    request = urllib.request.Request(url, headers=request_headers)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                if response.status >= 400:
                    return None
                text = response.read().decode("utf-8", errors="replace")
                write_text(cache_path, text)
                return text
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
            if attempt == 2:
                return None
            time.sleep(2**attempt)
    return None


def _record_detected_doi(card: SourceCard, doi: str, source: str | None, confidence: float) -> None:
    if not card.doi:
        card.doi = doi
        card.doi_status = "detected"
        card.doi_source = source
        card.doi_confidence = confidence
    elif card.doi_status == "missing":
        card.doi_status = "detected"
        card.doi_source = source
        card.doi_confidence = confidence


def _record_resolved_doi_from_abstract(card: SourceCard, candidate: AbstractCandidate) -> None:
    metadata = candidate.metadata
    if not metadata or not metadata.doi:
        return
    doi = normalize_doi(metadata.doi)
    if not doi:
        return
    if not card.doi:
        card.doi = doi
    if normalize_doi(card.doi) == doi:
        card.doi_status = "resolved"
        card.doi_source = card.doi_source or candidate.source
        card.doi_confidence = max(card.doi_confidence or 0.0, candidate.confidence)


def _accept_abstract_candidate(
    card: SourceCard,
    candidate: AbstractCandidate,
    *,
    checked_at: str,
) -> None:
    _record_resolved_doi_from_abstract(card, candidate)
    if candidate.metadata:
        _promote_metadata_from_candidate(card, candidate.metadata)
    card.abstract = candidate.text
    card.abstract_status = "verified" if candidate.confidence >= 0.94 else "resolved"
    card.abstract_source = candidate.source
    card.abstract_source_url = candidate.source_url
    card.abstract_confidence = round(candidate.confidence, 3)
    card.abstract_last_checked = checked_at
    card.abstract_enriched_at = checked_at
    card.abstract_input_fingerprint = abstract_fingerprint(card)


def _existing_abstract_blocks_candidate(
    card: SourceCard,
    candidate: AbstractCandidate,
    *,
    refresh: bool,
) -> bool:
    if not card.abstract:
        return False
    if _has_manual_abstract(card):
        return True
    existing_rank = _abstract_rank(card.abstract_source)
    candidate_rank = _abstract_rank(candidate.source)
    if existing_rank >= candidate_rank:
        return not refresh or not _abstracts_materially_disagree(card.abstract, candidate.text)
    return False


def enrich_abstract_card(
    paths: VaultPaths,
    card: SourceCard,
    options: EnrichmentOptions,
    *,
    fetch_json: FetchJson = _http_json,
) -> EnrichmentResult:
    skip_reason = should_skip_abstract_card(card, options)
    if skip_reason:
        return EnrichmentResult(card.citekey or card.slug, "skipped", skip_reason, skipped=True)

    checked_at = now_iso()
    requested_refresh = options.refresh_abstracts or card.enrichment_refresh
    cache_refresh = (
        requested_refresh
        or options.retry_failed
        or card.abstract_input_fingerprint != abstract_fingerprint(card)
    )
    work_dir = metadata_dir(paths, card)
    work_dir.mkdir(parents=True, exist_ok=True)

    doi, doi_source, doi_confidence = detect_local_doi(paths, card)
    if doi:
        _record_detected_doi(card, doi, doi_source, doi_confidence)

    candidates: list[AbstractCandidate] = []
    if card.doi:
        crossref_payload = fetch_json(
            _crossref_work_url(card.doi),
            work_dir / "crossref.json",
            cache_refresh,
        )
        if isinstance(crossref_payload, dict):
            candidates.extend(crossref_abstract_candidates(crossref_payload, card))
    else:
        crossref_payload = fetch_json(
            _crossref_url(card),
            work_dir / "crossref.json",
            cache_refresh,
        )
        if isinstance(crossref_payload, dict):
            candidates.extend(crossref_abstract_candidates(crossref_payload, card))

    # OpenAlex is useful corroboration for DOI records and fallback when Crossref lacks an abstract.
    if card.doi or not candidates:
        openalex_payload = fetch_json(
            _openalex_abstract_url(card),
            work_dir / "openalex.json",
            cache_refresh,
        )
        if isinstance(openalex_payload, dict):
            candidates.extend(openalex_abstract_candidates(openalex_payload, card))

    if not candidates:
        europepmc_payload = fetch_json(
            _europepmc_abstract_url(card),
            work_dir / "europepmc.json",
            cache_refresh,
        )
        if isinstance(europepmc_payload, dict):
            candidates.extend(europepmc_abstract_candidates(europepmc_payload, card))

    if card.doi and not candidates:
        datacite_payload = fetch_json(
            f"https://api.datacite.org/dois/{urllib.parse.quote(card.doi)}",
            work_dir / "datacite.json",
            cache_refresh,
        )
        if isinstance(datacite_payload, dict):
            candidates.extend(datacite_abstract_candidates(datacite_payload, card))

    if not candidates:
        pdf_path = _card_pdf_path(paths, card)
        if pdf_path:
            pdf_abstract = extract_pdf_abstract(extract_pdf_text_excerpt(pdf_path))
            if pdf_abstract:
                candidates.append(
                    AbstractCandidate(
                        text=pdf_abstract,
                        source="pdf_extracted",
                        source_url=card.pdf,
                        confidence=0.6,
                    )
                )

    best, ambiguous = _best_abstract_candidate(card, candidates)
    if ambiguous and best:
        card.abstract_status = "ambiguous"
        card.abstract_last_checked = checked_at
        card.abstract_input_fingerprint = abstract_fingerprint(card)
        card.enrichment_refresh = False
        return EnrichmentResult(
            card.citekey or card.slug,
            "ambiguous",
            f"ambiguous abstract candidates; best source={best.source}",
            changed=True,
        )

    if best:
        if _existing_abstract_blocks_candidate(
            card,
            best,
            refresh=requested_refresh,
        ):
            card.abstract_last_checked = checked_at
            card.abstract_input_fingerprint = abstract_fingerprint(card)
            changed = card.enrichment_refresh
            card.enrichment_refresh = False
            return EnrichmentResult(
                card.citekey or card.slug,
                "skipped",
                "existing abstract has equal or stronger provenance",
                changed=changed,
                skipped=True,
            )
        _accept_abstract_candidate(card, best, checked_at=checked_at)
        card.enrichment_refresh = False
        return EnrichmentResult(
            card.citekey or card.slug,
            card.abstract_status,
            f"abstract {card.abstract_status} from {best.source}",
            changed=True,
        )

    card.abstract_status = "unresolved"
    card.abstract_last_checked = checked_at
    card.abstract_input_fingerprint = abstract_fingerprint(card)
    card.enrichment_refresh = False
    return EnrichmentResult(
        card.citekey or card.slug,
        "unresolved",
        "no acceptable abstract found",
        changed=True,
    )


def enrich_card(
    paths: VaultPaths,
    card: SourceCard,
    options: EnrichmentOptions,
    *,
    fetch_json: FetchJson = _http_json,
    fetch_text: FetchText = _http_text,
) -> EnrichmentResult:
    if options.abstracts:
        return enrich_abstract_card(paths, card, options, fetch_json=fetch_json)

    skip_reason = should_skip_card(card, options)
    if skip_reason:
        card.citation_skip_reason = skip_reason
        return EnrichmentResult(card.citekey or card.slug, "skipped", skip_reason, skipped=True)

    fingerprint = card_fingerprint(card)
    cache_refresh = (
        options.refresh
        or card.enrichment_refresh
        or options.retry_failed
        or card.citation_input_fingerprint != fingerprint
    )
    checked_at = now_iso()
    work_dir = metadata_dir(paths, card)
    work_dir.mkdir(parents=True, exist_ok=True)

    doi, doi_source, doi_confidence = detect_local_doi(paths, card)
    if doi and not card.doi:
        card.doi = doi
        card.doi_status = "detected"
        card.doi_source = doi_source
        card.doi_confidence = doi_confidence
    elif doi and card.doi_status == "missing":
        card.doi_status = "detected"
        card.doi_source = doi_source
        card.doi_confidence = doi_confidence

    candidates: list[CitationCandidate] = []
    if not card.doi:
        crossref_payload = fetch_json(
            _crossref_url(card),
            work_dir / "crossref.json",
            cache_refresh,
        )
        if isinstance(crossref_payload, dict):
            candidates.extend(crossref_candidates(crossref_payload, card))

        openalex_payload = fetch_json(
            _openalex_url(card),
            work_dir / "openalex.json",
            cache_refresh,
        )
        if isinstance(openalex_payload, dict):
            candidates.extend(openalex_candidates(openalex_payload, card))

        if not candidates or max(candidate.score for candidate in candidates) < 70:
            europepmc_payload = fetch_json(
                _europepmc_url(card),
                work_dir / "europepmc.json",
                cache_refresh,
            )
            if isinstance(europepmc_payload, dict):
                candidates.extend(europepmc_candidates(europepmc_payload, card))

        best, ambiguous = select_candidate(
            sorted(candidates, key=lambda item: item.score, reverse=True)
        )
        if best and best.doi and not ambiguous:
            card.doi = best.doi
            card.doi_status = "resolved"
            card.doi_source = best.source
            card.doi_confidence = best.score / 100
            _promote_metadata_from_candidate(card, best)
            doi = best.doi
        elif best and ambiguous:
            card.doi_status = "ambiguous"
            card.citation_status = "ambiguous"
            card.citation_last_checked = checked_at
            card.citation_input_fingerprint = fingerprint
            card.citation_skip_reason = f"ambiguous {best.source} candidate score={best.score}"
            _update_enrichment_completeness(card)
            card.enrichment_refresh = False
            return EnrichmentResult(
                card.citekey or card.slug,
                "ambiguous",
                card.citation_skip_reason,
                changed=True,
            )

    if card.doi:
        raw_bibtex = fetch_text(
            f"https://doi.org/{urllib.parse.quote(card.doi)}",
            work_dir / "citation.bib",
            cache_refresh,
            {"Accept": "application/x-bibtex"},
        )
        csl_json = fetch_text(
            f"https://doi.org/{urllib.parse.quote(card.doi)}",
            work_dir / "citation.csl.json",
            cache_refresh,
            {"Accept": "application/vnd.citationstyles.csl+json"},
        )
        if csl_json:
            try:
                csl = json.loads(csl_json)
                csl_candidate = _csl_candidate(csl, card)
                if csl_candidate:
                    candidates.append(csl_candidate)
                    _promote_metadata_from_candidate(card, csl_candidate)
            except json.JSONDecodeError:
                pass

        if _should_search_for_published_version(card):
            crossref_payload = fetch_json(
                _crossref_url(card),
                work_dir / "crossref-search.json",
                cache_refresh,
            )
            if isinstance(crossref_payload, dict):
                search_candidates = crossref_candidates(crossref_payload, card)
                candidates.extend(search_candidates)
                published = _published_version_candidate(card, search_candidates)
                if published:
                    card.doi = published.doi
                    card.doi_status = "resolved"
                    card.doi_source = f"{published.source}:published-version"
                    card.doi_confidence = max(card.doi_confidence or 0.0, published.score / 100)
                    _promote_metadata_from_candidate(card, published)
                    raw_bibtex = fetch_text(
                        f"https://doi.org/{urllib.parse.quote(card.doi)}",
                        work_dir / "citation.bib",
                        True,
                        {"Accept": "application/x-bibtex"},
                    )
                    refreshed_csl_json = fetch_text(
                        f"https://doi.org/{urllib.parse.quote(card.doi)}",
                        work_dir / "citation.csl.json",
                        True,
                        {"Accept": "application/vnd.citationstyles.csl+json"},
                    )
                    if refreshed_csl_json:
                        try:
                            refreshed_csl = json.loads(refreshed_csl_json)
                            refreshed_candidate = _csl_candidate(refreshed_csl, card)
                            if refreshed_candidate:
                                candidates.append(refreshed_candidate)
                                _promote_metadata_from_candidate(card, refreshed_candidate)
                        except json.JSONDecodeError:
                            pass
        if raw_bibtex or card.title:
            _finalize_citation_success(card, checked_at=checked_at, candidates=candidates)
            return EnrichmentResult(
                card.citekey or card.slug,
                card.citation_status,
                f"citation {card.citation_status}",
                changed=True,
            )

        datacite_payload = fetch_json(
            f"https://api.datacite.org/dois/{urllib.parse.quote(card.doi)}",
            work_dir / "datacite.json",
            cache_refresh,
        )
        if isinstance(datacite_payload, dict):
            datacite = datacite_candidate(datacite_payload, card)
            if datacite and datacite.score >= 88:
                _promote_metadata_from_candidate(card, datacite)
                card.doi_status = "resolved"
                card.doi_source = card.doi_source or "datacite"
                card.citation_status = "generated"
                card.citation_source = "datacite"
                card.citation_enriched_at = checked_at
                card.citation_last_checked = checked_at
                card.citation_input_fingerprint = card_fingerprint(card)
                _update_enrichment_completeness(card)
                card.citation_skip_reason = (
                    f"incomplete metadata: {', '.join(card.enrichment_missing)}"
                    if card.enrichment_missing
                    else None
                )
                card.enrichment_refresh = False
                return EnrichmentResult(
                    card.citekey or card.slug,
                    "generated",
                    "citation generated from datacite",
                    changed=True,
                )

    card.citation_status = "unresolved"
    card.doi_status = card.doi_status if card.doi_status != "missing" else "unresolved"
    card.citation_last_checked = checked_at
    card.citation_input_fingerprint = fingerprint
    card.citation_retries += 1
    card.citation_skip_reason = "no acceptable DOI or citation metadata found"
    _update_enrichment_completeness(card)
    card.enrichment_refresh = False
    return EnrichmentResult(
        card.citekey or card.slug,
        "unresolved",
        card.citation_skip_reason,
        changed=True,
    )


def _strong_consistency(card: SourceCard, candidates: list[CitationCandidate]) -> bool:
    if not card.doi:
        return False
    return any(candidate.doi == card.doi and candidate.score >= 94 for candidate in candidates)


def _csl_candidate(payload: dict[str, Any], card: SourceCard) -> CitationCandidate | None:
    title = payload.get("title")
    if not title:
        return None
    authors = []
    for author in payload.get("author") or []:
        literal = author.get("literal")
        name = literal or " ".join(
            part for part in [author.get("given"), author.get("family")] if part
        )
        if name:
            authors.append(name)
    issued = payload.get("issued") or {}
    year = None
    if issued.get("date-parts") and issued["date-parts"][0]:
        year = _safe_int(issued["date-parts"][0][0])
    candidate = CitationCandidate(
        doi=normalize_doi(payload.get("DOI") or payload.get("doi")) or normalize_doi(card.doi),
        title=title,
        authors=authors,
        year=year,
        venue=payload.get("container-title"),
        url=payload.get("URL"),
        source="doi-csl",
        raw=payload,
    )
    return candidate.__class__(
        **{**candidate.__dict__, "score": score_metadata_candidate(card, candidate)}
    )


def _crossref_url(card: SourceCard) -> str:
    params = {
        "query.bibliographic": " ".join(value for value in [card.title, card.venue] if value),
        "rows": "5",
        "mailto": os.environ.get("SCHOLAR_VAULT_MAILTO", "scholar-vault@example.invalid"),
    }
    author = _first_author(card)
    if author:
        params["query.author"] = author
    if card.year:
        params["filter"] = f"from-pub-date:{card.year - 1},until-pub-date:{card.year + 1}"
    return "https://api.crossref.org/works?" + urllib.parse.urlencode(params)


def _crossref_work_url(doi: str) -> str:
    params = {"mailto": os.environ.get("SCHOLAR_VAULT_MAILTO", "scholar-vault@example.invalid")}
    return (
        f"https://api.crossref.org/works/{urllib.parse.quote(doi)}?"
        + urllib.parse.urlencode(params)
    )


def _openalex_url(card: SourceCard) -> str:
    query = " ".join(value for value in [card.title, _first_author(card)] if value)
    params = {"search": query, "per-page": "5"}
    if card.year:
        params["filter"] = (
            f"from_publication_date:{card.year - 1}-01-01,to_publication_date:{card.year + 1}-12-31"
        )
    return "https://api.openalex.org/works?" + urllib.parse.urlencode(params)


def _openalex_abstract_url(card: SourceCard) -> str:
    if card.doi:
        params = {"filter": f"doi:{normalize_doi(card.doi)}", "per-page": "1"}
        return "https://api.openalex.org/works?" + urllib.parse.urlencode(params)
    return _openalex_url(card)


def _europepmc_url(card: SourceCard) -> str:
    query = f'TITLE:"{card.title}"'
    if _first_author(card):
        query += f" AND AUTH:{_first_author(card)}"
    params = {"query": query, "format": "json", "pageSize": "5"}
    return "https://www.ebi.ac.uk/europepmc/webservices/rest/search?" + urllib.parse.urlencode(
        params
    )


def _europepmc_abstract_url(card: SourceCard) -> str:
    if card.doi:
        query = f'DOI:"{normalize_doi(card.doi)}"'
    else:
        query = f'TITLE:"{card.title}"'
        if _first_author(card):
            query += f" AND AUTH:{_first_author(card)}"
        if card.year:
            query += f" AND PUB_YEAR:{card.year}"
    params = {"query": query, "format": "json", "pageSize": "5"}
    return "https://www.ebi.ac.uk/europepmc/webservices/rest/search?" + urllib.parse.urlencode(
        params
    )


def enrich_cards(
    paths: VaultPaths,
    cards: list[SourceCard],
    options: EnrichmentOptions,
    *,
    fetch_json: FetchJson = _http_json,
    fetch_text: FetchText = _http_text,
    progress: EnrichmentProgress | None = None,
) -> list[EnrichmentResult]:
    results: list[EnrichmentResult] = []
    total = len(cards)
    for index, card in enumerate(cards, start=1):
        if progress:
            progress(card, index, total, "checking")
        result = enrich_card(
            paths,
            card,
            options,
            fetch_json=fetch_json,
            fetch_text=fetch_text,
        )
        if progress:
            progress(card, index, total, result.status)
        results.append(_result_with_card_context(result, card))
    return results
