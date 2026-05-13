from __future__ import annotations

from typing import Any

from .models import SourceCard
from .obsidian import _card_id
from .sources import normalize_doi, normalize_title

SEARCH_STOPWORDS = {
    "about",
    "after",
    "also",
    "among",
    "based",
    "between",
    "could",
    "from",
    "have",
    "into",
    "more",
    "paper",
    "papers",
    "research",
    "results",
    "show",
    "shows",
    "study",
    "studies",
    "that",
    "their",
    "these",
    "this",
    "through",
    "using",
    "were",
    "with",
}


def _terms_from_text(text: str | None) -> set[str]:
    normalized = normalize_title(text)
    return {
        token
        for token in normalized.split()
        if len(token) > 3 and token not in SEARCH_STOPWORDS
    }


def _value_map(values: list[str]) -> dict[str, str]:
    mapped: dict[str, str] = {}
    for value in values:
        key = normalize_title(value)
        if key and key not in mapped:
            mapped[key] = value
    return mapped


def _semantic_neighbor_rows(cards: list[SourceCard], *, limit: int = 5) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    features: dict[str, dict[str, Any]] = {}
    for card in cards:
        card_key = _card_id(card)
        features[card_key] = {
            "topics": _value_map(card.topics),
            "keywords": _value_map(card.keywords),
            "runs": set(card.discovered_in),
            "terms": _terms_from_text(f"{card.title} {card.abstract or ''}"),
            "doi": normalize_doi(card.doi),
        }
    for card in cards:
        card_key = _card_id(card)
        neighbors: list[dict[str, Any]] = []
        current = features[card_key]
        for other in cards:
            other_key = _card_id(other)
            if other_key == card_key:
                continue
            candidate = features[other_key]
            reasons: list[str] = []
            score = 0
            shared_topics = sorted(set(current["topics"]) & set(candidate["topics"]))
            for topic_key in shared_topics[:5]:
                reasons.append(f"shared topic: {current['topics'][topic_key]}")
            score += len(shared_topics) * 4
            shared_keywords = sorted(set(current["keywords"]) & set(candidate["keywords"]))
            for keyword_key in shared_keywords[:5]:
                reasons.append(f"shared keyword: {current['keywords'][keyword_key]}")
            score += len(shared_keywords) * 5
            shared_runs = sorted(current["runs"] & candidate["runs"])
            for run in shared_runs[:3]:
                reasons.append(f"same run: {run}")
            score += len(shared_runs) * 3
            shared_terms = sorted(current["terms"] & candidate["terms"])
            if shared_terms:
                reasons.append(
                    "similar title/abstract terms: " + ", ".join(shared_terms[:8])
                )
            score += min(len(shared_terms), 8)
            if current["doi"] and current["doi"] == candidate["doi"]:
                reasons.append(f"same DOI: {current['doi']}")
                score += 10
            if score <= 0:
                continue
            neighbors.append(
                {
                    "citekey": other_key,
                    "paper": f"papers/{other.slug}.md",
                    "title": other.title,
                    "score": score,
                    "reasons": reasons,
                }
            )
        neighbors.sort(key=lambda item: (-int(item["score"]), str(item["citekey"])))
        rows.append(
            {
                "citekey": card_key,
                "paper": f"papers/{card.slug}.md",
                "title": card.title,
                "neighbors": neighbors[:limit],
            }
        )
    return rows


def semantic_neighbors_export(cards: list[SourceCard]) -> dict[str, Any]:
    return {
        "schema_version": "0.1",
        "kind": "deterministic_navigation_neighbors",
        "evidence_warning": (
            "Navigation only. Shared metadata and text overlap are not evidence; read PDFs "
            "before factual synthesis."
        ),
        "method": [
            "shared topics",
            "shared publication keywords",
            "same Scholar Labs run",
            "title/abstract term overlap",
            "matching DOI metadata when present",
        ],
        "papers": _semantic_neighbor_rows(cards),
    }
