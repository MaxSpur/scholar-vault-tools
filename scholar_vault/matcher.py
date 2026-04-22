from __future__ import annotations

import hashlib
from pathlib import Path

from pdfminer.high_level import extract_text
from pypdf import PdfReader
from rapidfuzz import fuzz

from .models import MatchDecision, PdfCandidate, SourceCard
from .sources import DOI_RE, YEAR_RE, infer_year, normalize_doi, normalize_title


def extract_pdf_text_excerpt(path: Path, *, max_pages: int = 3) -> str:
    try:
        return (extract_text(str(path), page_numbers=range(max_pages)) or "").strip()
    except Exception:
        return ""


def read_pdf_metadata(path: Path) -> dict[str, str | None]:
    try:
        reader = PdfReader(str(path))
    except Exception:
        return {}
    metadata = reader.metadata or {}
    normalized: dict[str, str | None] = {}
    for key, value in metadata.items():
        cleaned_key = str(key).lstrip("/")
        normalized[cleaned_key.lower()] = str(value) if value is not None else None
    return normalized


def infer_pdf_title(path: Path, metadata: dict[str, str | None], text_excerpt: str) -> str | None:
    meta_title = (metadata.get("title") or "").strip()
    if meta_title and meta_title.lower() != "untitled":
        return meta_title
    for line in text_excerpt.splitlines():
        candidate = line.strip()
        if len(candidate) < 12:
            continue
        if candidate.isupper() and len(candidate.split()) <= 2:
            continue
        return candidate
    cleaned_stem = path.stem.replace("_", " ").replace("-", " ").strip()
    return cleaned_stem or None


def infer_pdf_doi(metadata: dict[str, str | None], text_excerpt: str) -> str | None:
    for source in (metadata.get("subject"), metadata.get("keywords"), text_excerpt):
        if not source:
            continue
        match = DOI_RE.search(source)
        if match:
            return normalize_doi(match.group(1))
    return None


def infer_pdf_year(metadata: dict[str, str | None], text_excerpt: str) -> int | None:
    for source in (metadata.get("creationdate"), metadata.get("moddate"), text_excerpt):
        if not source:
            continue
        year = infer_year(source)
        if year:
            return year
        match = YEAR_RE.search(source)
        if match:
            return int(match.group(0))
    return None


def build_pdf_candidate(path: Path) -> PdfCandidate:
    metadata = read_pdf_metadata(path)
    text_excerpt = extract_pdf_text_excerpt(path)
    title = infer_pdf_title(path, metadata, text_excerpt)
    doi = infer_pdf_doi(metadata, text_excerpt)
    year = infer_pdf_year(metadata, text_excerpt)
    sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    size = path.stat().st_size
    return PdfCandidate(
        path=str(path),
        title=title,
        doi=doi,
        year=year,
        text_excerpt=text_excerpt[:4000],
        metadata=metadata,
        sha256=sha256,
        size=size,
    )


def score_title_match(left: str | None, right: str | None) -> int:
    normalized_left = normalize_title(left)
    normalized_right = normalize_title(right)
    if not normalized_left or not normalized_right:
        return 0
    exact = 100 if normalized_left == normalized_right else 0
    token_set = fuzz.token_set_ratio(normalized_left, normalized_right)
    partial = fuzz.partial_ratio(normalized_left, normalized_right)
    return int(round(max(exact, token_set, partial)))


def decide_pdf_match(
    expected_title: str,
    candidate: PdfCandidate,
    *,
    expected_doi: str | None = None,
) -> MatchDecision:
    if (
        expected_doi
        and candidate.doi
        and normalize_doi(expected_doi) == normalize_doi(candidate.doi)
    ):
        return MatchDecision(candidate=candidate, score=100, decision="auto", reason="doi")
    score = score_title_match(expected_title, candidate.title)
    if score >= 90:
        return MatchDecision(candidate=candidate, score=score, decision="auto", reason="title")
    if score >= 70:
        return MatchDecision(candidate=candidate, score=score, decision="review", reason="title")
    return MatchDecision(candidate=candidate, score=score, decision="skip", reason="title")


def best_pdf_match(
    expected_title: str,
    candidates: list[PdfCandidate],
    *,
    expected_doi: str | None = None,
) -> MatchDecision:
    best = MatchDecision()
    for candidate in candidates:
        decision = decide_pdf_match(expected_title, candidate, expected_doi=expected_doi)
        if decision.score > best.score:
            best = decision
    return best


def match_candidate_to_cards(
    candidate: PdfCandidate,
    cards: list[SourceCard],
) -> tuple[SourceCard | None, int]:
    if candidate.doi:
        normalized = normalize_doi(candidate.doi)
        for card in cards:
            if normalize_doi(card.doi) == normalized:
                return card, 100
    best_score = 0
    best_card: SourceCard | None = None
    for card in cards:
        score = score_title_match(candidate.title, card.title)
        if score > best_score:
            best_card = card
            best_score = score
    return best_card, best_score
