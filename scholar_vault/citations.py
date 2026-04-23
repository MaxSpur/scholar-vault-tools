from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from .bibtex import card_to_bibtex
from .matcher import extract_pdf_text_excerpt, read_pdf_metadata, score_title_match
from .models import SourceCard
from .sources import (
    DOI_RE,
    VaultPaths,
    first_author_surname,
    normalize_doi,
    parse_people,
    write_text,
)

OnlyMode = Literal["all", "missing-doi", "missing-bibtex"]
FetchJson = Callable[[str, Path, bool], dict[str, Any] | list[Any] | None]
FetchText = Callable[[str, Path, bool, dict[str, str]], str | None]

GENERATED_CITATION_STATUSES = {"generated", "verified"}
FAILED_CITATION_STATUSES = {"ambiguous", "unresolved"}
MAX_RETRIES = 3


@dataclass(frozen=True)
class EnrichmentOptions:
    only: OnlyMode = "all"
    citekey: str | None = None
    refresh: bool = False
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
class EnrichmentResult:
    citekey: str
    status: str
    message: str
    changed: bool = False
    skipped: bool = False


def now_iso() -> str:
    return datetime.now().astimezone().replace(microsecond=0).isoformat()


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


def should_skip_card(card: SourceCard, options: EnrichmentOptions) -> str | None:
    fingerprint = card_fingerprint(card)
    if options.citekey and card.citekey != options.citekey:
        return "citekey filter"
    if card.metadata_lock and not options.force:
        return "metadata_lock"
    if card.citation_status == "verified" and not options.refresh:
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
        and not options.refresh
    ):
        return "fingerprint unchanged"
    if (
        card.citation_status == "unresolved"
        and card.citation_retries >= MAX_RETRIES
        and not options.retry_failed
        and not options.refresh
    ):
        return "retry limit reached"
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


def enrich_card(
    paths: VaultPaths,
    card: SourceCard,
    options: EnrichmentOptions,
    *,
    fetch_json: FetchJson = _http_json,
    fetch_text: FetchText = _http_text,
) -> EnrichmentResult:
    skip_reason = should_skip_card(card, options)
    if skip_reason:
        card.citation_skip_reason = skip_reason
        return EnrichmentResult(card.citekey or card.slug, "skipped", skip_reason, skipped=True)

    fingerprint = card_fingerprint(card)
    cache_refresh = (
        options.refresh or options.retry_failed or card.citation_input_fingerprint != fingerprint
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
            doi = best.doi
        elif best and ambiguous:
            card.doi_status = "ambiguous"
            card.citation_status = "ambiguous"
            card.citation_last_checked = checked_at
            card.citation_input_fingerprint = fingerprint
            card.citation_skip_reason = f"ambiguous {best.source} candidate score={best.score}"
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
                if csl.get("title") and not card.url:
                    card.url = csl.get("URL")
                csl_candidate = _csl_candidate(csl, card)
                if csl_candidate:
                    candidates.append(csl_candidate)
            except json.JSONDecodeError:
                pass
        if raw_bibtex or card.title:
            if card.doi_status in {"missing", "detected"}:
                card.doi_status = "resolved"
            card.citation_status = (
                "verified" if _strong_consistency(card, candidates) else "generated"
            )
            card.citation_source = "doi"
            card.citation_enriched_at = checked_at
            card.citation_last_checked = checked_at
            card.citation_input_fingerprint = fingerprint
            card.citation_skip_reason = None
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
                card.doi_status = "resolved"
                card.doi_source = card.doi_source or "datacite"
                card.citation_status = "generated"
                card.citation_source = "datacite"
                card.citation_enriched_at = checked_at
                card.citation_last_checked = checked_at
                card.citation_input_fingerprint = fingerprint
                card.citation_skip_reason = None
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


def _openalex_url(card: SourceCard) -> str:
    query = " ".join(value for value in [card.title, _first_author(card)] if value)
    params = {"search": query, "per-page": "5"}
    if card.year:
        params["filter"] = (
            f"from_publication_date:{card.year - 1}-01-01,to_publication_date:{card.year + 1}-12-31"
        )
    return "https://api.openalex.org/works?" + urllib.parse.urlencode(params)


def _europepmc_url(card: SourceCard) -> str:
    query = f'TITLE:"{card.title}"'
    if _first_author(card):
        query += f" AND AUTH:{_first_author(card)}"
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
) -> list[EnrichmentResult]:
    results: list[EnrichmentResult] = []
    for card in cards:
        result = enrich_card(
            paths,
            card,
            options,
            fetch_json=fetch_json,
            fetch_text=fetch_text,
        )
        results.append(result)
    return results
