from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from .sources import normalize_doi, slugify_text

ProviderName = Literal["openalex", "semantic_scholar"]

OPENALEX_FIELDS = ",".join(
    [
        "id",
        "doi",
        "title",
        "display_name",
        "publication_year",
        "authorships",
        "primary_location",
        "abstract_inverted_index",
        "cited_by_count",
        "referenced_works",
        "related_works",
    ]
)
SEMANTIC_SCHOLAR_FIELDS = ",".join(
    [
        "paperId",
        "title",
        "year",
        "authors",
        "venue",
        "url",
        "externalIds",
        "citationCount",
        "abstract",
    ]
)


class DiscoveryProviderError(RuntimeError):
    """Raised when a discovery provider cannot be queried safely."""


@dataclass(frozen=True)
class DiscoveryPaper:
    source: ProviderName
    source_id: str
    title: str
    authors: tuple[str, ...] = ()
    year: int | None = None
    doi: str | None = None
    url: str | None = None
    venue: str | None = None
    abstract: str | None = None
    cited_by_count: int | None = None
    reason: str = ""


def _cache_stem(value: str, *, max_length: int = 80) -> str:
    return slugify_text(value, max_length=max_length) or "request"


def _json_headers(provider: ProviderName) -> dict[str, str]:
    mailto = os.environ.get("SCHOLAR_VAULT_MAILTO", "scholar-vault@example.invalid")
    headers = {
        "Accept": "application/json",
        "User-Agent": f"scholar-vault/0.2 (mailto:{mailto})",
    }
    if provider == "semantic_scholar":
        api_key = os.environ.get("SEMANTIC_SCHOLAR_API_KEY") or os.environ.get("S2_API_KEY")
        if api_key:
            headers["x-api-key"] = api_key
    return headers


def _http_json(
    url: str,
    cache_path: Path,
    *,
    provider: ProviderName,
    refresh: bool = False,
    min_interval: float = 0.0,
    timeout: int = 20,
) -> dict[str, Any] | None:
    if cache_path.exists() and not refresh:
        return json.loads(cache_path.read_text(encoding="utf-8"))
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers=_json_headers(provider))
    for attempt in range(3):
        if min_interval:
            time.sleep(min_interval)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                text = response.read().decode("utf-8", errors="replace")
                if response.status >= 400:
                    return None
                cache_path.write_text(text, encoding="utf-8")
                return json.loads(text)
        except urllib.error.HTTPError as exc:
            if exc.code in {401, 403}:
                raise DiscoveryProviderError(
                    f"{provider} rejected the request. For Semantic Scholar, set "
                    "SEMANTIC_SCHOLAR_API_KEY or S2_API_KEY if your unauthenticated quota "
                    "is unavailable."
                ) from exc
            if exc.code == 429:
                retry_after = exc.headers.get("Retry-After")
                if retry_after and retry_after.isdigit() and attempt < 2:
                    time.sleep(min(int(retry_after), 30))
                    continue
                raise DiscoveryProviderError(
                    f"{provider} rate limit reached. Retry later, use cached results, or "
                    "configure an API key where the provider supports one."
                ) from exc
            if attempt == 2:
                return None
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            if attempt == 2:
                return None
            time.sleep(2**attempt)
    return None


def _abstract_from_openalex_index(index: object) -> str | None:
    if not isinstance(index, dict):
        return None
    positions: dict[int, str] = {}
    for word, raw_positions in index.items():
        if not isinstance(raw_positions, list):
            continue
        for raw_position in raw_positions:
            if isinstance(raw_position, int):
                positions[raw_position] = str(word)
    if not positions:
        return None
    return " ".join(positions[position] for position in sorted(positions))


def _openalex_short_id(value: str | None) -> str:
    if not value:
        return ""
    return value.rstrip("/").rsplit("/", 1)[-1]


def _openalex_url(params: dict[str, str]) -> str:
    merged = dict(params)
    api_key = os.environ.get("OPENALEX_API_KEY")
    if api_key:
        merged["api_key"] = api_key
    return "https://api.openalex.org/works?" + urllib.parse.urlencode(merged)


def _openalex_venue(row: dict[str, Any]) -> str | None:
    primary = row.get("primary_location") or {}
    if not isinstance(primary, dict):
        return None
    source = primary.get("source") or {}
    if not isinstance(source, dict):
        return None
    venue = source.get("display_name")
    return str(venue) if venue else None


def _parse_openalex_work(row: dict[str, Any], *, reason: str) -> DiscoveryPaper | None:
    title = str(row.get("title") or row.get("display_name") or "").strip()
    if not title:
        return None
    authors = tuple(
        str(item.get("author", {}).get("display_name"))
        for item in (row.get("authorships") or [])[:6]
        if isinstance(item, dict) and item.get("author", {}).get("display_name")
    )
    doi = normalize_doi(str(row.get("doi") or ""))
    openalex_id = _openalex_short_id(str(row.get("id") or ""))
    return DiscoveryPaper(
        source="openalex",
        source_id=openalex_id or slugify_text(title, max_length=80),
        title=title,
        authors=authors,
        year=row.get("publication_year") if isinstance(row.get("publication_year"), int) else None,
        doi=doi,
        url=str(row.get("id") or "") or None,
        venue=_openalex_venue(row),
        abstract=_abstract_from_openalex_index(row.get("abstract_inverted_index")),
        cited_by_count=(
            row.get("cited_by_count") if isinstance(row.get("cited_by_count"), int) else None
        ),
        reason=reason,
    )


def _parse_openalex_results(data: dict[str, Any] | None, *, reason: str) -> list[DiscoveryPaper]:
    if not isinstance(data, dict):
        return []
    papers = []
    for row in data.get("results") or []:
        if isinstance(row, dict):
            paper = _parse_openalex_work(row, reason=reason)
            if paper:
                papers.append(paper)
    return papers


class OpenAlexAdapter:
    provider: ProviderName = "openalex"

    def search(
        self,
        query: str,
        *,
        limit: int,
        cache_dir: Path,
        refresh: bool = False,
    ) -> list[DiscoveryPaper]:
        cache_path = cache_dir / "openalex" / f"search-{_cache_stem(query)}.json"
        url = _openalex_url(
            {
                "search": query,
                "per-page": str(limit),
                "sort": "cited_by_count:desc",
                "select": OPENALEX_FIELDS,
            }
        )
        data = _http_json(url, cache_path, provider=self.provider, refresh=refresh)
        return _parse_openalex_results(data, reason="query result")[:limit]

    def _seed_work(
        self,
        *,
        title: str,
        doi: str | None,
        cache_dir: Path,
        refresh: bool,
    ) -> dict[str, Any] | None:
        if doi:
            doi_url = f"https://doi.org/{normalize_doi(doi)}"
            cache_path = cache_dir / "openalex" / f"seed-doi-{_cache_stem(doi)}.json"
            url = _openalex_url(
                {
                    "filter": f"doi:{doi_url}",
                    "per-page": "1",
                    "select": OPENALEX_FIELDS,
                }
            )
        else:
            cache_path = cache_dir / "openalex" / f"seed-title-{_cache_stem(title)}.json"
            url = _openalex_url(
                {
                    "search": title,
                    "per-page": "1",
                    "select": OPENALEX_FIELDS,
                }
            )
        data = _http_json(url, cache_path, provider=self.provider, refresh=refresh)
        if not isinstance(data, dict):
            return None
        rows = data.get("results") or []
        return rows[0] if rows and isinstance(rows[0], dict) else None

    def _fetch_openalex_ids(
        self,
        ids: list[str],
        *,
        reason: str,
        limit: int,
        cache_dir: Path,
        refresh: bool,
    ) -> list[DiscoveryPaper]:
        clean_ids = [_openalex_short_id(item) for item in ids if _openalex_short_id(item)]
        if not clean_ids:
            return []
        joined = "|".join(clean_ids[: min(len(clean_ids), 25)])
        cache_path = cache_dir / "openalex" / f"{_cache_stem(reason)}-{_cache_stem(joined)}.json"
        url = _openalex_url(
            {
                "filter": f"openalex:{joined}",
                "per-page": str(min(limit, 25)),
                "select": OPENALEX_FIELDS,
            }
        )
        data = _http_json(url, cache_path, provider=self.provider, refresh=refresh)
        return _parse_openalex_results(data, reason=reason)[:limit]

    def neighborhood(
        self,
        *,
        title: str,
        doi: str | None,
        limit: int,
        cache_dir: Path,
        refresh: bool = False,
    ) -> list[DiscoveryPaper]:
        seed = self._seed_work(title=title, doi=doi, cache_dir=cache_dir, refresh=refresh)
        if not seed:
            return self.search(title, limit=limit, cache_dir=cache_dir, refresh=refresh)
        seed_id = _openalex_short_id(str(seed.get("id") or ""))
        references = self._fetch_openalex_ids(
            list(seed.get("referenced_works") or [])[:limit],
            reason="seed reference",
            limit=limit,
            cache_dir=cache_dir,
            refresh=refresh,
        )
        related = self._fetch_openalex_ids(
            list(seed.get("related_works") or [])[:limit],
            reason="related to seed",
            limit=limit,
            cache_dir=cache_dir,
            refresh=refresh,
        )
        citing: list[DiscoveryPaper] = []
        if seed_id:
            cache_path = cache_dir / "openalex" / f"cites-{seed_id}.json"
            url = _openalex_url(
                {
                    "filter": f"cites:{seed_id}",
                    "per-page": str(limit),
                    "sort": "cited_by_count:desc",
                    "select": OPENALEX_FIELDS,
                }
            )
            data = _http_json(url, cache_path, provider=self.provider, refresh=refresh)
            citing = _parse_openalex_results(data, reason="cites seed")
        return [*references, *citing, *related][:limit]


def _semantic_url(path: str, params: dict[str, str]) -> str:
    return (
        "https://api.semanticscholar.org/graph/v1"
        + path
        + ("?" + urllib.parse.urlencode(params) if params else "")
    )


def _semantic_doi(value: dict[str, Any]) -> str | None:
    external = value.get("externalIds") or {}
    if not isinstance(external, dict):
        return None
    return normalize_doi(str(external.get("DOI") or ""))


def _parse_semantic_paper(row: dict[str, Any], *, reason: str) -> DiscoveryPaper | None:
    title = str(row.get("title") or "").strip()
    if not title:
        return None
    authors = tuple(
        str(item.get("name"))
        for item in (row.get("authors") or [])[:6]
        if isinstance(item, dict) and item.get("name")
    )
    return DiscoveryPaper(
        source="semantic_scholar",
        source_id=str(row.get("paperId") or slugify_text(title, max_length=80)),
        title=title,
        authors=authors,
        year=row.get("year") if isinstance(row.get("year"), int) else None,
        doi=_semantic_doi(row),
        url=str(row.get("url") or "") or None,
        venue=str(row.get("venue") or "") or None,
        abstract=str(row.get("abstract") or "") or None,
        cited_by_count=(
            row.get("citationCount") if isinstance(row.get("citationCount"), int) else None
        ),
        reason=reason,
    )


def _parse_semantic_rows(
    data: dict[str, Any] | None,
    *,
    reason: str,
    nested_key: str | None = None,
) -> list[DiscoveryPaper]:
    if not isinstance(data, dict):
        return []
    papers = []
    for raw_row in data.get("data") or []:
        row = raw_row
        if nested_key and isinstance(raw_row, dict):
            row = raw_row.get(nested_key)
        if isinstance(row, dict):
            paper = _parse_semantic_paper(row, reason=reason)
            if paper:
                papers.append(paper)
    return papers


class SemanticScholarAdapter:
    provider: ProviderName = "semantic_scholar"

    def search(
        self,
        query: str,
        *,
        limit: int,
        cache_dir: Path,
        refresh: bool = False,
    ) -> list[DiscoveryPaper]:
        cache_path = cache_dir / "semantic_scholar" / f"search-{_cache_stem(query)}.json"
        url = _semantic_url(
            "/paper/search",
            {
                "query": query,
                "limit": str(limit),
                "fields": SEMANTIC_SCHOLAR_FIELDS,
            },
        )
        data = _http_json(
            url,
            cache_path,
            provider=self.provider,
            refresh=refresh,
            min_interval=0.25,
        )
        return _parse_semantic_rows(data, reason="query result")[:limit]

    def _seed_paper(
        self,
        *,
        title: str,
        doi: str | None,
        limit: int,
        cache_dir: Path,
        refresh: bool,
    ) -> DiscoveryPaper | None:
        if doi:
            paper_id = urllib.parse.quote(f"DOI:{normalize_doi(doi)}", safe=":")
            cache_path = cache_dir / "semantic_scholar" / f"seed-doi-{_cache_stem(doi)}.json"
            url = _semantic_url(f"/paper/{paper_id}", {"fields": SEMANTIC_SCHOLAR_FIELDS})
            data = _http_json(
                url,
                cache_path,
                provider=self.provider,
                refresh=refresh,
                min_interval=0.25,
            )
            if isinstance(data, dict):
                return _parse_semantic_paper(data, reason="seed paper")
        rows = self.search(title, limit=max(1, limit), cache_dir=cache_dir, refresh=refresh)
        return rows[0] if rows else None

    def neighborhood(
        self,
        *,
        title: str,
        doi: str | None,
        limit: int,
        cache_dir: Path,
        refresh: bool = False,
    ) -> list[DiscoveryPaper]:
        seed = self._seed_paper(
            title=title,
            doi=doi,
            limit=1,
            cache_dir=cache_dir,
            refresh=refresh,
        )
        if seed is None:
            return []
        paper_id = urllib.parse.quote(seed.source_id, safe="")
        references_path = (
            cache_dir / "semantic_scholar" / f"references-{_cache_stem(paper_id)}.json"
        )
        references_url = _semantic_url(
            f"/paper/{paper_id}/references",
            {
                "limit": str(limit),
                "fields": SEMANTIC_SCHOLAR_FIELDS,
            },
        )
        citations_path = cache_dir / "semantic_scholar" / f"citations-{_cache_stem(paper_id)}.json"
        citations_url = _semantic_url(
            f"/paper/{paper_id}/citations",
            {
                "limit": str(limit),
                "fields": SEMANTIC_SCHOLAR_FIELDS,
            },
        )
        references = _parse_semantic_rows(
            _http_json(
                references_url,
                references_path,
                provider=self.provider,
                refresh=refresh,
                min_interval=0.25,
            ),
            reason="seed reference",
            nested_key="citedPaper",
        )
        citations = _parse_semantic_rows(
            _http_json(
                citations_url,
                citations_path,
                provider=self.provider,
                refresh=refresh,
                min_interval=0.25,
            ),
            reason="cites seed",
            nested_key="citingPaper",
        )
        return [*references, *citations][:limit]


def get_adapter(provider: ProviderName) -> OpenAlexAdapter | SemanticScholarAdapter:
    if provider == "openalex":
        return OpenAlexAdapter()
    if provider == "semantic_scholar":
        return SemanticScholarAdapter()
    raise ValueError(f"Unsupported discovery provider: {provider}")
