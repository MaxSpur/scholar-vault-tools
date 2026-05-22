from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import yaml

from .models import RunRecord, SourceCard
from .queries import (
    _append_section_item,
    _as_string_list,
    _load_query,
    _query_slug,
    _write_query_preserving_body,
    query_link_run,
)
from .sources import (
    VaultPaths,
    clean_markdown_text,
    dump_frontmatter,
    ensure_relative,
    load_run_records,
    load_source_cards,
    read_frontmatter_markdown,
    slugify_text,
    write_text,
    write_yaml,
)

PROMPT_PACK_STATUSES = {"draft", "ready", "used", "imported", "retired"}
PROMPT_TYPES = (
    "coverage_gap",
    "related_papers_from_seed",
    "method_dataset_relation",
    "contradiction_check",
    "negative_evidence",
    "review_update",
    "benchmark_or_dataset_search",
    "proposal_evidence_gap",
    "synthesis_expansion",
    "failure_modes",
)
SeedProvider = Literal["none", "openalex", "semantic-scholar"]


@dataclass(frozen=True)
class PromptEntry:
    id: str
    prompt_text: str
    prompt_type: str
    intended_use: str
    expected_result_shape: str
    followup_questions: list[str]
    selection_guidance: str
    import_instructions: str


@dataclass(frozen=True)
class SeedCandidate:
    title: str
    year: int | None = None
    authors: tuple[str, ...] = ()
    venue: str | None = None
    doi: str | None = None
    url: str | None = None
    source: str = ""
    citation_count: int | None = None
    reason: str | None = None


def _now_iso() -> str:
    return datetime.now().astimezone().replace(microsecond=0).isoformat()


def _sentence(value: str | None, *, fallback: str, limit: int = 420) -> str:
    cleaned = re.sub(r"\s+", " ", clean_markdown_text(value)).strip()
    if not cleaned:
        return fallback
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3].rstrip(" .,;:") + "..."


def _markdown_quote(value: str) -> str:
    return value.replace("|", r"\|")


def _normalize_status(value: Any) -> str:
    status = str(value or "draft").strip().casefold()
    return status if status in PROMPT_PACK_STATUSES else "draft"


def _prompt_pack_dirs(paths: VaultPaths) -> list[Path]:
    dirs = [paths.tasks / "scholar-labs-prompts"]
    if paths.queries.exists():
        dirs.extend(sorted(paths.queries.glob("*/prompt-packs")))
    return dirs


def _prompt_pack_paths(paths: VaultPaths, *, ensure: bool = True) -> list[Path]:
    if ensure:
        paths.tasks.joinpath("scholar-labs-prompts").mkdir(parents=True, exist_ok=True)
    found: list[Path] = []
    for folder in _prompt_pack_dirs(paths):
        if folder.exists():
            found.extend(sorted(folder.glob("*.md")))
    return sorted(set(found))


def _prompt_pack_ref(paths: VaultPaths, path: Path) -> str:
    return ensure_relative(path, paths.vault)


def _prompt_pack_id_from_path(path: Path) -> str:
    return path.stem


def _load_prompt_pack_path(paths: VaultPaths, path: Path) -> tuple[dict[str, Any], str]:
    frontmatter, body = read_frontmatter_markdown(path)
    if frontmatter.get("type") != "scholar_labs_prompt_pack":
        raise ValueError(f"Not a Scholar Labs prompt pack: {_prompt_pack_ref(paths, path)}")
    frontmatter["status"] = _normalize_status(frontmatter.get("status"))
    for field in (
        "linked_runs",
        "linked_tasks",
        "linked_syntheses",
        "linked_concepts",
        "generated_from",
    ):
        frontmatter[field] = _as_string_list(frontmatter.get(field))
    frontmatter["query"] = str(frontmatter.get("query") or "")
    frontmatter["project"] = str(frontmatter.get("project") or "")
    frontmatter["created_at"] = str(frontmatter.get("created_at") or _now_iso())
    return frontmatter, body


def resolve_prompt_pack(
    paths: VaultPaths,
    prompt_pack_id: str,
) -> tuple[dict[str, Any], Path, str]:
    raw = (prompt_pack_id or "").strip().strip("/")
    if not raw:
        raise ValueError("Prompt-pack id must not be empty.")

    candidate_path: Path | None = None
    candidate = Path(raw)
    if candidate.is_absolute():
        try:
            candidate.relative_to(paths.vault)
        except ValueError as exc:
            raise ValueError("Prompt-pack path must stay inside the vault.") from exc
        candidate_path = candidate
    elif raw.startswith(("queries/", "tasks/")):
        candidate_path = paths.vault / (raw if raw.endswith(".md") else f"{raw}.md")

    if candidate_path is not None:
        if not candidate_path.exists():
            raise ValueError(f"Prompt pack does not exist: {candidate_path}")
        frontmatter, body = _load_prompt_pack_path(paths, candidate_path)
        return frontmatter, candidate_path, body

    matches = []
    for path in _prompt_pack_paths(paths):
        if path.stem == raw:
            matches.append(path)
            continue
        try:
            frontmatter, _ = _load_prompt_pack_path(paths, path)
        except ValueError:
            continue
        if str(frontmatter.get("id") or "") == raw:
            matches.append(path)
    if not matches:
        raise ValueError(f"Prompt pack does not exist: {prompt_pack_id}")
    if len(matches) > 1:
        refs = ", ".join(_prompt_pack_ref(paths, path) for path in matches)
        raise ValueError(f"Prompt-pack id is ambiguous: {prompt_pack_id} ({refs})")
    frontmatter, body = _load_prompt_pack_path(paths, matches[0])
    return frontmatter, matches[0], body


def _write_prompt_pack(path: Path, frontmatter: dict[str, Any], body: str) -> None:
    write_text(path, f"---\n{dump_frontmatter(frontmatter).strip()}\n---\n\n{body.strip()}\n")


def _paper_lookup(cards: list[SourceCard]) -> dict[str, SourceCard]:
    lookup: dict[str, SourceCard] = {}
    for card in cards:
        refs = {card.slug, f"papers/{card.slug}.md"}
        if card.citekey:
            refs.add(card.citekey)
        for ref in refs:
            lookup[ref] = card
    return lookup


def _paper_label(card: SourceCard) -> str:
    bits = [card.title]
    if card.year:
        bits.append(str(card.year))
    if card.authors:
        bits.append(", ".join(card.authors[:2]))
    elif card.authors_preview:
        bits.append(card.authors_preview)
    if card.venue:
        bits.append(card.venue)
    return " - ".join(bits)


def _read_artifact(paths: VaultPaths, ref: str) -> tuple[dict[str, Any], str, Path] | None:
    raw = (ref or "").strip().strip("/")
    if not raw:
        return None
    path = paths.vault / raw
    if path.suffix != ".md":
        path = path.with_suffix(".md")
    if not path.exists() or not path.is_file():
        return None
    frontmatter, body = read_frontmatter_markdown(path)
    return frontmatter, body, path


def _artifact_title(path: Path, frontmatter: dict[str, Any], body: str) -> str:
    title = str(frontmatter.get("title") or frontmatter.get("question") or "").strip()
    if title:
        return title
    match = re.search(r"^#\s+(.+?)\s*$", body, flags=re.MULTILINE)
    return match.group(1).strip() if match else path.stem.replace("-", " ").title()


def _without_tool_sections(body: str) -> str:
    return re.sub(
        r"(?ms)^##\s+(Workbench|Scholar Labs prompt pack|Linked runs)\s*$.*?(?=^##\s+|\Z)",
        "",
        body,
    )


def _lines_with_terms(body: str, terms: tuple[str, ...], *, limit: int = 6) -> list[str]:
    rows: list[str] = []
    for line in body.splitlines():
        cleaned = re.sub(r"\s+", " ", line.strip(" -*\t"))
        if not cleaned or cleaned.startswith("#"):
            continue
        folded = cleaned.casefold()
        if any(term in folded for term in terms):
            rows.append(cleaned)
        if len(rows) >= limit:
            break
    return rows


def _collect_gap_tasks(
    paths: VaultPaths,
    *,
    query_ref: str = "",
    project_slug: str = "",
) -> list[str]:
    terms = ("gap", "missing", "discover", "scholar labs", "evidence", "contradict")
    rows: list[str] = []
    for path in sorted(paths.tasks.rglob("*.md")) if paths.tasks.exists() else []:
        if "scholar-labs-prompts" in path.parts:
            continue
        frontmatter, body = read_frontmatter_markdown(path)
        text = f"{frontmatter}\n{body}".casefold()
        if query_ref and query_ref.casefold() not in text:
            continue
        if project_slug and project_slug.casefold() not in text:
            continue
        lines = _lines_with_terms(body, terms, limit=3)
        title = _artifact_title(path, frontmatter, body)
        if lines or any(term in text for term in terms):
            rows.append(f"{title}: {'; '.join(lines) if lines else 'gap/discovery task'}")
    for path in sorted(paths.task_queue.glob("*.yaml")) if paths.task_queue.exists() else []:
        try:
            data = json.loads(json.dumps(yaml.safe_load(path.read_text()) or {}))
        except Exception:
            continue
        text = json.dumps(data, ensure_ascii=False).casefold()
        if query_ref and query_ref.casefold() not in text:
            continue
        if project_slug and project_slug.casefold() not in text:
            continue
        if any(term in text for term in terms):
            detail = data.get("notes") or data.get("success_criteria") or data.get("kind")
            rows.append(f"{data.get('title') or path.stem}: {detail}")
    return rows[:8]


def _collect_proposal_gaps(paths: VaultPaths, *, project_slug: str = "") -> list[str]:
    terms = ("gap", "missing", "needs evidence", "weak evidence", "scholar labs")
    rows: list[str] = []
    if not paths.proposals.exists():
        return rows
    for path in sorted(paths.proposals.rglob("*.md")):
        frontmatter, body = read_frontmatter_markdown(path)
        text = f"{frontmatter}\n{body}".casefold()
        if project_slug and project_slug.casefold() not in text:
            continue
        lines = _lines_with_terms(body, terms, limit=4)
        if lines:
            rows.append(f"{_artifact_title(path, frontmatter, body)}: {'; '.join(lines)}")
    return rows[:8]


def _collect_context_for_query(paths: VaultPaths, slug: str) -> dict[str, Any]:
    query, query_path, body = _load_query(paths, slug)
    cards = load_source_cards(paths)
    lookup = _paper_lookup(cards)
    linked_cards = []
    for ref in query.get("linked_papers") or []:
        card = lookup.get(ref) or lookup.get(Path(ref).stem)
        if card:
            linked_cards.append(card)
    syntheses = []
    for ref in query.get("linked_syntheses") or []:
        artifact = _read_artifact(paths, ref)
        if artifact:
            frontmatter, synthesis_body, synthesis_path = artifact
            syntheses.append(
                {
                    "ref": ensure_relative(synthesis_path, paths.vault),
                    "title": _artifact_title(synthesis_path, frontmatter, synthesis_body),
                    "snippet": _sentence(synthesis_body, fallback="", limit=360),
                }
            )
    concept_rows = []
    missing_concepts = []
    for ref in query.get("linked_concepts") or []:
        artifact = _read_artifact(paths, ref if ref.startswith("concepts/") else f"concepts/{ref}")
        if artifact:
            frontmatter, concept_body, concept_path = artifact
            concept_rows.append(
                {
                    "ref": ensure_relative(concept_path, paths.vault),
                    "title": _artifact_title(concept_path, frontmatter, concept_body),
                }
            )
        else:
            missing_concepts.append(ref)
    project_slug = str(query.get("project") or "")
    query_ref = ensure_relative(query_path, paths.vault)
    return {
        "kind": "query",
        "slug": query_path.stem,
        "title": query["question"],
        "query": query,
        "query_ref": query_ref,
        "project": project_slug,
        "body": body,
        "scope": _sentence(
            _without_tool_sections(body),
            fallback="No explicit scope note found.",
            limit=700,
        ),
        "linked_cards": linked_cards,
        "linked_syntheses": syntheses,
        "linked_concepts": concept_rows,
        "missing_concepts": missing_concepts,
        "gap_tasks": _collect_gap_tasks(paths, query_ref=query_ref, project_slug=project_slug),
        "proposal_gaps": _collect_proposal_gaps(paths, project_slug=project_slug),
        "generated_from": [query_ref],
        "linked_tasks": [],
        "linked_syntheses_refs": [row["ref"] for row in syntheses],
        "linked_concepts_refs": [row["ref"] for row in concept_rows],
    }


def _project_path(paths: VaultPaths, slug: str) -> Path:
    normalized = slugify_text(slug, max_length=80)
    return paths.projects / normalized / "index.md"


def _collect_context_for_project(paths: VaultPaths, slug: str) -> dict[str, Any]:
    project_slug = slugify_text(slug, max_length=80)
    project_path = _project_path(paths, project_slug)
    if not project_path.exists():
        raise ValueError(f"Project does not exist: projects/{project_slug}")
    frontmatter, body = read_frontmatter_markdown(project_path)
    cards = load_source_cards(paths)
    lookup = _paper_lookup(cards)
    linked_cards = []
    for ref in _as_string_list(frontmatter.get("related_papers")):
        card = lookup.get(ref) or lookup.get(Path(ref).stem)
        if card:
            linked_cards.append(card)
    syntheses = []
    for ref in _as_string_list(frontmatter.get("related_syntheses")):
        artifact = _read_artifact(paths, ref)
        if artifact:
            synthesis_frontmatter, synthesis_body, synthesis_path = artifact
            syntheses.append(
                {
                    "ref": ensure_relative(synthesis_path, paths.vault),
                    "title": _artifact_title(synthesis_path, synthesis_frontmatter, synthesis_body),
                    "snippet": _sentence(synthesis_body, fallback="", limit=360),
                }
            )
    concepts = []
    for ref in _as_string_list(frontmatter.get("related_concepts")):
        artifact = _read_artifact(paths, ref)
        if artifact:
            concept_frontmatter, concept_body, concept_path = artifact
            concepts.append(
                {
                    "ref": ensure_relative(concept_path, paths.vault),
                    "title": _artifact_title(concept_path, concept_frontmatter, concept_body),
                }
            )
    map_path = paths.projects / project_slug / "project-map.md"
    map_snippet = ""
    if map_path.exists():
        _, map_body = read_frontmatter_markdown(map_path)
        map_snippet = _sentence(map_body, fallback="", limit=900)
    project_ref = ensure_relative(project_path, paths.vault)
    return {
        "kind": "project",
        "slug": project_slug,
        "title": str(frontmatter.get("title") or project_slug.replace("-", " ").title()),
        "query_ref": "",
        "project": project_slug,
        "body": body,
        "scope": _sentence(
            body,
            fallback=map_snippet or "No explicit project scope found.",
            limit=900,
        ),
        "project_map": map_snippet,
        "linked_cards": linked_cards,
        "linked_syntheses": syntheses,
        "linked_concepts": concepts,
        "missing_concepts": [],
        "gap_tasks": _collect_gap_tasks(paths, project_slug=project_slug),
        "proposal_gaps": _collect_proposal_gaps(paths, project_slug=project_slug),
        "generated_from": [project_ref],
        "linked_tasks": _as_string_list(frontmatter.get("related_tasks")),
        "linked_syntheses_refs": [row["ref"] for row in syntheses],
        "linked_concepts_refs": [row["ref"] for row in concepts],
    }


def _collect_context_from_gaps(paths: VaultPaths) -> dict[str, Any]:
    gap_tasks = _collect_gap_tasks(paths)
    proposal_gaps = _collect_proposal_gaps(paths)
    return {
        "kind": "gaps",
        "slug": "vault-gaps",
        "title": "Vault evidence and discovery gaps",
        "query_ref": "",
        "project": "",
        "body": "",
        "scope": "Open maintenance, gap-scout, and proposal evidence tasks across the vault.",
        "linked_cards": [],
        "linked_syntheses": [],
        "linked_concepts": [],
        "missing_concepts": [],
        "gap_tasks": gap_tasks,
        "proposal_gaps": proposal_gaps,
        "generated_from": [],
        "linked_tasks": [],
        "linked_syntheses_refs": [],
        "linked_concepts_refs": [],
    }


def _context_terms(context: dict[str, Any]) -> str:
    card_terms = []
    for card in context.get("linked_cards") or []:
        card_terms.extend(card.keywords[:5])
        card_terms.extend(card.topics[:5])
    concept_terms = [row["title"] for row in context.get("linked_concepts") or []]
    missing = list(context.get("missing_concepts") or [])
    terms = []
    seen = set()
    for item in [*card_terms, *concept_terms, *missing]:
        cleaned = re.sub(r"\s+", " ", str(item)).strip()
        key = cleaned.casefold()
        if cleaned and key not in seen:
            seen.add(key)
            terms.append(cleaned)
    return ", ".join(terms[:12]) or "the named methods, datasets, assumptions, and evidence gaps"


def _seed_query_text(context: dict[str, Any]) -> str:
    return " ".join(
        item
        for item in [
            str(context.get("title") or ""),
            _context_terms(context),
            " ".join(_paper_label(card) for card in (context.get("linked_cards") or [])[:3]),
        ]
        if item
    )


def _openalex_url(query: str, limit: int) -> str:
    params = {"search": query, "per-page": str(limit)}
    return "https://api.openalex.org/works?" + urllib.parse.urlencode(params)


def _semantic_scholar_url(query: str, limit: int) -> str:
    params = {
        "query": query,
        "limit": str(limit),
        "fields": "title,year,authors,venue,url,externalIds,citationCount",
    }
    return "https://api.semanticscholar.org/graph/v1/paper/search?" + urllib.parse.urlencode(params)


def _http_json(url: str, cache_path: Path, *, refresh: bool = False) -> dict[str, Any] | None:
    if cache_path.exists() and not refresh:
        return json.loads(cache_path.read_text(encoding="utf-8"))
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    mailto = os.environ.get("SCHOLAR_VAULT_MAILTO", "scholar-vault@example.invalid")
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": f"scholar-vault/0.2 (mailto:{mailto})",
        },
    )
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                if response.status >= 400:
                    return None
                text = response.read().decode("utf-8", errors="replace")
                cache_path.write_text(text, encoding="utf-8")
                return json.loads(text)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            if attempt == 2:
                return None
            time.sleep(2**attempt)
    return None


def _parse_openalex_candidates(data: dict[str, Any] | None) -> list[SeedCandidate]:
    if not isinstance(data, dict):
        return []
    candidates: list[SeedCandidate] = []
    for row in data.get("results") or []:
        if not isinstance(row, dict) or not row.get("title"):
            continue
        authorships = row.get("authorships") or []
        authors = tuple(
            str(item.get("author", {}).get("display_name"))
            for item in authorships[:3]
            if isinstance(item, dict) and item.get("author", {}).get("display_name")
        )
        primary = row.get("primary_location") or {}
        source = primary.get("source") if isinstance(primary, dict) else {}
        candidates.append(
            SeedCandidate(
                title=str(row.get("title")),
                year=row.get("publication_year"),
                authors=authors,
                venue=source.get("display_name") if isinstance(source, dict) else None,
                doi=str(row.get("doi") or "").removeprefix("https://doi.org/") or None,
                url=row.get("id"),
                source="openalex",
                citation_count=row.get("cited_by_count"),
            )
        )
    return candidates


def _parse_semantic_scholar_candidates(data: dict[str, Any] | None) -> list[SeedCandidate]:
    if not isinstance(data, dict):
        return []
    candidates: list[SeedCandidate] = []
    for row in data.get("data") or []:
        if not isinstance(row, dict) or not row.get("title"):
            continue
        external = row.get("externalIds") or {}
        authors = tuple(
            str(item.get("name"))
            for item in (row.get("authors") or [])[:3]
            if isinstance(item, dict) and item.get("name")
        )
        candidates.append(
            SeedCandidate(
                title=str(row.get("title")),
                year=row.get("year"),
                authors=authors,
                venue=row.get("venue"),
                doi=external.get("DOI") if isinstance(external, dict) else None,
                url=row.get("url"),
                source="semantic-scholar",
                citation_count=row.get("citationCount"),
            )
        )
    return candidates


def fetch_seed_candidates(
    paths: VaultPaths,
    context: dict[str, Any],
    *,
    provider: SeedProvider = "none",
    limit: int = 5,
    refresh: bool = False,
) -> list[SeedCandidate]:
    if provider == "none":
        return []
    query = _seed_query_text(context)
    cache_dir = paths.raw_metadata / "scholar-labs-prompts"
    cache_path = cache_dir / f"{provider}-{slugify_text(query, max_length=70)}.json"
    if provider == "openalex":
        data = _http_json(_openalex_url(query, limit), cache_path, refresh=refresh)
        return _parse_openalex_candidates(data)[:limit]
    if provider == "semantic-scholar":
        data = _http_json(_semantic_scholar_url(query, limit), cache_path, refresh=refresh)
        return _parse_semantic_scholar_candidates(data)[:limit]
    raise ValueError(f"Unsupported seed provider: {provider}")


def _seed_lines(seeds: list[SeedCandidate]) -> list[str]:
    lines = []
    for seed in seeds:
        detail = []
        if seed.year:
            detail.append(str(seed.year))
        if seed.authors:
            detail.append(", ".join(seed.authors[:2]))
        if seed.venue:
            detail.append(seed.venue)
        if seed.doi:
            detail.append(f"doi:{seed.doi}")
        lines.append(f"- {seed.title}" + (f" ({'; '.join(detail)})" if detail else ""))
    return lines


def _context_summary(context: dict[str, Any], seeds: list[SeedCandidate]) -> str:
    cards = context.get("linked_cards") or []
    syntheses = context.get("linked_syntheses") or []
    concepts = context.get("linked_concepts") or []
    lines = [
        f"- Focus: {context.get('title')}",
        f"- Scope: {context.get('scope')}",
    ]
    if cards:
        lines.append("- Linked papers:")
        lines.extend(f"  - {_paper_label(card)}" for card in cards[:10])
    if syntheses:
        lines.append("- Linked syntheses:")
        lines.extend(
            f"  - {row['title']}: {row.get('snippet') or row['ref']}"
            for row in syntheses[:6]
        )
    if concepts:
        lines.append("- Linked concepts:")
        lines.extend(f"  - {row['title']}" for row in concepts[:10])
    if context.get("missing_concepts"):
        lines.append("- Missing concept links:")
        lines.extend(f"  - {item}" for item in context["missing_concepts"][:10])
    if context.get("gap_tasks"):
        lines.append("- Gap-scout tasks:")
        lines.extend(f"  - {item}" for item in context["gap_tasks"][:8])
    if context.get("proposal_gaps"):
        lines.append("- Proposal evidence gaps:")
        lines.extend(f"  - {item}" for item in context["proposal_gaps"][:8])
    if seeds:
        lines.append("- Optional API seed candidates for prompt wording only:")
        lines.extend(f"  {line}" for line in _seed_lines(seeds))
    return "\n".join(lines)


def _named_papers(context: dict[str, Any], seeds: list[SeedCandidate]) -> str:
    cards = context.get("linked_cards") or []
    if cards:
        names = "; ".join(_paper_label(card) for card in cards[:5])
        if seeds:
            seed_titles = "; ".join(seed.title for seed in seeds[:3])
            return (
                f"Seed from these vault papers: {names}. "
                f"Optional API wording seeds: {seed_titles}."
            )
        return f"Seed from these vault papers: {names}."
    if seeds:
        return "Seed from these API candidate titles for wording only: " + "; ".join(
            seed.title for seed in seeds[:5]
        )
    return "No seed papers are canonical yet; ask for candidate papers directly tied to the focus."


def _has_discovery_seeds(seeds: list[SeedCandidate]) -> bool:
    return any(seed.source == "discovery" for seed in seeds)


def _prompt_text_for_type(
    prompt_type: str,
    context: dict[str, Any],
    seeds: list[SeedCandidate],
) -> str:
    focus = str(context.get("title") or "this research question")
    terms = _context_terms(context)
    seed_clause = _named_papers(context, seeds)
    discovery_prefix = ""
    if _has_discovery_seeds(seeds):
        discovery_prefix = (
            "Starting from these candidate papers/terms, find papers that directly address "
            f"the following relationship: {focus}. Treat the candidates as non-canonical "
            "seed material only, and verify useful results through DOI/PDF/manual import. "
        )
    common = (
        "Use Google Scholar Labs as a discovery assistant only. Return scholarly papers, not "
        "general web pages. For each paper, explain the specific relationship it addresses, "
        "why it is relevant, and what follow-up search question it suggests. Include DOI or "
        "publisher links when visible. Separate recent work from older foundational work. "
        "Exclude papers that only share broad keywords without addressing the named relationship."
    )
    templates = {
        "coverage_gap": (
            f"{discovery_prefix}For the research focus '{focus}', find papers that cover "
            f"evidence gaps around "
            f"{terms}. {seed_clause} Prioritize papers that directly connect two or more of "
            f"these concepts and identify what the current vault appears to be missing. {common}"
        ),
        "related_papers_from_seed": (
            f"{discovery_prefix}Starting from the seed context for '{focus}', find closely "
            f"related papers that extend, compare against, or are cited alongside the seed "
            f"papers. {seed_clause} "
            f"Include both recent follow-ups and foundational papers. {common}"
        ),
        "method_dataset_relation": (
            f"{discovery_prefix}Find papers for '{focus}' where the method, evaluation "
            f"protocol, or dataset is comparable to {terms}. Prefer papers that name datasets, "
            f"benchmarks, instruments, user-study conditions, or reproducible evaluation "
            f"settings. {common}"
        ),
        "contradiction_check": (
            f"{discovery_prefix}Find papers that contradict, limit, or complicate the "
            f"assumptions behind '{focus}'. Look for negative results, boundary conditions, "
            f"failed replications, weak effects, or critiques involving {terms}. {common}"
        ),
        "negative_evidence": (
            f"{discovery_prefix}Find papers that report null, mixed, harmful, or "
            f"non-generalizing outcomes relevant to '{focus}'. Prioritize empirical evidence "
            f"where the expected benefit did not hold, and state what condition made it fail. "
            f"{common}"
        ),
        "review_update": (
            f"{discovery_prefix}Find recent review, survey, meta-analysis, or position "
            f"papers that update the literature around '{focus}' and {terms}. Also identify "
            f"older reviews that are still used as foundations. {common}"
        ),
        "benchmark_or_dataset_search": (
            f"{discovery_prefix}Find papers introducing, comparing, or reusing benchmarks, "
            f"datasets, corpora, protocols, or shared tasks relevant to '{focus}'. Extract "
            f"dataset names and what relationship each benchmark can test. {common}"
        ),
        "proposal_evidence_gap": (
            f"{discovery_prefix}Find papers that would strengthen a proposal evidence gap "
            f"for '{focus}'. Prefer sources that can support need, novelty, feasibility, "
            "risk, or expected impact. "
            "Identify which proposal claim each paper could support and where it remains weak. "
            f"{common}"
        ),
        "synthesis_expansion": (
            f"{discovery_prefix}Find papers that would expand a synthesis for '{focus}' by "
            "adding missing methods, contrasting populations/settings, or adjacent "
            "theoretical frames. Group results by which synthesis section they would improve. "
            f"{common}"
        ),
        "failure_modes": (
            f"{discovery_prefix}Find papers documenting failure modes, threats to validity, "
            f"implementation barriers, or evaluation pitfalls for '{focus}' and {terms}. "
            f"Prefer papers with concrete failure conditions and mitigation strategies. {common}"
        ),
    }
    return templates[prompt_type]


def _prompt_entry(
    prompt_type: str,
    context: dict[str, Any],
    seeds: list[SeedCandidate],
) -> PromptEntry:
    expected_shapes = {
        "coverage_gap": "Grouped papers by missing relationship or concept gap.",
        "related_papers_from_seed": (
            "Papers adjacent to named seeds, with relationship to each seed."
        ),
        "method_dataset_relation": (
            "Methods, datasets, protocols, and comparable evaluation settings."
        ),
        "contradiction_check": (
            "Contradictory or limiting evidence with the challenged assumption named."
        ),
        "negative_evidence": (
            "Null, mixed, or adverse findings and the conditions where they occur."
        ),
        "review_update": "Recent and foundational reviews, surveys, and meta-analyses.",
        "benchmark_or_dataset_search": "Benchmark or dataset papers with reuse/comparison context.",
        "proposal_evidence_gap": (
            "Papers mapped to proposal need, novelty, feasibility, risk, or impact claims."
        ),
        "synthesis_expansion": (
            "Papers grouped by the synthesis section or concept they would expand."
        ),
        "failure_modes": "Failure modes, threats to validity, and mitigation evidence.",
    }
    guidance = {
        "coverage_gap": (
            "Select papers that fill a named missing relationship, not broad background matches."
        ),
        "related_papers_from_seed": (
            "Select papers that cite, extend, compare with, or clearly neighbor a seed."
        ),
        "method_dataset_relation": (
            "Select papers with concrete reusable methods, datasets, or protocols."
        ),
        "contradiction_check": (
            "Select papers that would change a claim, assumption, or scope boundary."
        ),
        "negative_evidence": (
            "Select papers with explicit null, mixed, adverse, or non-generalizing results."
        ),
        "review_update": "Select reviews that reorganize the field or reveal a new search trail.",
        "benchmark_or_dataset_search": (
            "Select benchmark/dataset papers that can drive follow-up searches."
        ),
        "proposal_evidence_gap": "Select papers that support or weaken a specific proposal claim.",
        "synthesis_expansion": "Select papers that add a missing axis to an existing synthesis.",
        "failure_modes": (
            "Select papers with concrete pitfalls that should constrain future claims."
        ),
    }
    return PromptEntry(
        id=f"{context['slug']}-{prompt_type}",
        prompt_type=prompt_type,
        prompt_text=_prompt_text_for_type(prompt_type, context, seeds),
        intended_use=f"Use this when the vault needs {prompt_type.replace('_', ' ')} discovery.",
        expected_result_shape=expected_shapes[prompt_type],
        followup_questions=[
            "Which result should become the next seed prompt?",
            "Which result contradicts or narrows the current assumption?",
            "Which selected PDF should be imported first for PDF-grounded review?",
        ],
        selection_guidance=guidance[prompt_type],
        import_instructions=(
            "Run this prompt manually in Google Scholar Labs, download only PDFs worth keeping, "
            "export the visible Labs results, then run import-labs with --prompt-pack and --query "
            "or link the run afterwards. Treat Labs summaries as discovery context only."
        ),
    )


def _render_prompt_pack(
    frontmatter: dict[str, Any],
    context: dict[str, Any],
    prompts: list[PromptEntry],
    seeds: list[SeedCandidate],
) -> str:
    lines = [
        f"# Scholar Labs Prompt Pack: {context.get('title')}",
        "",
        "## Boundaries",
        "- Run these prompts manually in Google Scholar Labs.",
        "- Do not scrape Google Scholar and do not treat Labs summaries as PDF-grounded evidence.",
        "- Canonical paper cards should be created only through the existing PDF, DOI, "
        "BibTeX, or manual import paths.",
        "",
        "## Source Context",
        _context_summary(context, seeds),
        "",
        "## API Seed Support",
        "API seed candidates are optional prompt-writing aids. They are not canonical "
        "vault papers.",
    ]
    if seeds:
        lines.extend(_seed_lines(seeds))
    else:
        lines.append("No API seed candidates were requested for this pack.")
    lines.extend(["", "## Prompts", ""])
    for prompt in prompts:
        lines.extend(
            [
                f"### {prompt.id}",
                f"- id: `{prompt.id}`",
                f"- prompt_type: `{prompt.prompt_type}`",
                f"- intended_use: {_markdown_quote(prompt.intended_use)}",
                f"- expected_result_shape: {_markdown_quote(prompt.expected_result_shape)}",
                "- followup_questions:",
                *[f"  - {_markdown_quote(question)}" for question in prompt.followup_questions],
                f"- selection_guidance: {_markdown_quote(prompt.selection_guidance)}",
                f"- import_instructions: {_markdown_quote(prompt.import_instructions)}",
                "",
                "```text",
                prompt.prompt_text,
                "```",
                "",
            ]
        )
    lines.extend(
        [
            "## Usage Notes",
            "No usage notes yet.",
            "",
            "## Linked Runs",
            "No linked Scholar Labs runs yet.",
            "",
        ]
    )
    return "\n".join(lines)


def _append_usage_note(body: str, text: str) -> str:
    note = f"- {_now_iso()}: {text}"
    return _append_section_item(body, "Usage Notes", note)


def _append_run_note(body: str, run_id: str) -> str:
    return _append_section_item(body, "Linked Runs", f"- Run: `{run_id}`")


def _update_query_prompt_pack(paths: VaultPaths, query_slug: str, pack_ref: str) -> bool:
    query, path, body = _load_query(paths, query_slug)
    packs = _as_string_list(query.get("scholar_labs_prompt_pack"))
    changed = False
    if pack_ref not in packs:
        packs.append(pack_ref)
        query["scholar_labs_prompt_pack"] = sorted(packs, key=str.casefold)
        query["updated"] = _now_iso()
        body = _append_section_item(
            body,
            "Scholar Labs prompt pack",
            f"- [Scholar Labs prompt pack](../{pack_ref})",
        )
        changed = True
    if changed:
        _write_query_preserving_body(path, query, body)
    return changed


def _refresh_prompt_navigation(paths: VaultPaths) -> None:
    from .bases import rebuild_bases
    from .rebuild import _rebuild_indexes

    rebuild_bases(paths.vault)
    _rebuild_indexes(paths)


def generate_prompt_pack(
    vault: Path | str,
    *,
    query: str | None = None,
    project: str | None = None,
    from_gaps: bool = False,
    seed_api: SeedProvider = "none",
    refresh_seeds: bool = False,
) -> dict[str, Any]:
    from .importer import initialize_vault

    selected_modes = [bool(query), bool(project), from_gaps]
    if sum(selected_modes) != 1:
        raise ValueError("Choose exactly one of --query, --project, or --from-gaps.")
    paths = initialize_vault(vault, rebuild=False)
    if query:
        context = _collect_context_for_query(paths, _query_slug(query))
        pack_id = f"query-{context['slug']}-scholar-labs-prompts"
        path = paths.queries / context["slug"] / "prompt-packs" / f"{pack_id}.md"
    elif project:
        context = _collect_context_for_project(paths, project)
        pack_id = f"project-{context['slug']}-scholar-labs-prompts"
        path = paths.tasks / "scholar-labs-prompts" / f"{pack_id}.md"
    else:
        context = _collect_context_from_gaps(paths)
        pack_id = "vault-gaps-scholar-labs-prompts"
        path = paths.tasks / "scholar-labs-prompts" / f"{pack_id}.md"

    existing_frontmatter: dict[str, Any] = {}
    if path.exists():
        existing_frontmatter, _ = _load_prompt_pack_path(paths, path)
    seeds = fetch_seed_candidates(paths, context, provider=seed_api, refresh=refresh_seeds)
    prompts = [_prompt_entry(prompt_type, context, seeds) for prompt_type in PROMPT_TYPES]
    now = _now_iso()
    frontmatter = {
        "type": "scholar_labs_prompt_pack",
        "status": _normalize_status(existing_frontmatter.get("status") or "draft"),
        "query": context.get("query_ref") or "",
        "project": context.get("project") or "",
        "created_at": existing_frontmatter.get("created_at") or now,
        "generated_from": sorted(
            set(
                _as_string_list(existing_frontmatter.get("generated_from"))
                + context["generated_from"]
            ),
            key=str.casefold,
        ),
        "linked_runs": sorted(
            set(_as_string_list(existing_frontmatter.get("linked_runs"))), key=str.casefold
        ),
        "linked_tasks": sorted(
            set(
                _as_string_list(existing_frontmatter.get("linked_tasks"))
                + context["linked_tasks"]
            ),
            key=str.casefold,
        ),
        "linked_syntheses": sorted(
            set(
                _as_string_list(existing_frontmatter.get("linked_syntheses"))
                + context["linked_syntheses_refs"]
            ),
            key=str.casefold,
        ),
        "linked_concepts": sorted(
            set(
                _as_string_list(existing_frontmatter.get("linked_concepts"))
                + context["linked_concepts_refs"]
            ),
            key=str.casefold,
        ),
    }
    body = _render_prompt_pack(frontmatter, context, prompts, seeds)
    before = path.read_text(encoding="utf-8") if path.exists() else None
    _write_prompt_pack(path, frontmatter, body)
    pack_ref = _prompt_pack_ref(paths, path)
    state = (
        "unchanged"
        if before == path.read_text(encoding="utf-8")
        else ("updated" if before else "created")
    )
    query_changed = False
    if context.get("query_ref"):
        query_changed = _update_query_prompt_pack(paths, context["slug"], pack_ref)
    _refresh_prompt_navigation(paths)
    return {
        "vault": str(paths.vault),
        "id": pack_id,
        "prompt_pack": pack_ref,
        "status": frontmatter["status"],
        "state": state,
        "prompt_count": len(prompts),
        "prompt_types": list(PROMPT_TYPES),
        "query_updated": query_changed,
        "seed_provider": seed_api,
        "seed_candidates": [seed.__dict__ for seed in seeds],
    }


def generate_prompt_pack_from_seed_candidates(
    vault: Path | str,
    *,
    query: str,
    seed_candidates: list[SeedCandidate],
    candidate_refs: list[str],
) -> dict[str, Any]:
    from .importer import initialize_vault

    paths = initialize_vault(vault, rebuild=False)
    context = _collect_context_for_query(paths, _query_slug(query))
    pack_id = f"query-{context['slug']}-discovery-candidate-labs-prompts"
    path = paths.queries / context["slug"] / "prompt-packs" / f"{pack_id}.md"
    existing_frontmatter: dict[str, Any] = {}
    if path.exists():
        existing_frontmatter, _ = _load_prompt_pack_path(paths, path)
    prompts = [_prompt_entry(prompt_type, context, seed_candidates) for prompt_type in PROMPT_TYPES]
    now = _now_iso()
    linked_discovery = sorted(
        set(
            _as_string_list(existing_frontmatter.get("linked_discovery_candidates"))
            + list(candidate_refs)
        ),
        key=str.casefold,
    )
    frontmatter = {
        "type": "scholar_labs_prompt_pack",
        "status": _normalize_status(existing_frontmatter.get("status") or "draft"),
        "query": context.get("query_ref") or "",
        "project": context.get("project") or "",
        "created_at": existing_frontmatter.get("created_at") or now,
        "generated_from": sorted(
            set(
                _as_string_list(existing_frontmatter.get("generated_from"))
                + context["generated_from"]
                + linked_discovery
            ),
            key=str.casefold,
        ),
        "linked_runs": sorted(
            set(_as_string_list(existing_frontmatter.get("linked_runs"))), key=str.casefold
        ),
        "linked_tasks": sorted(
            set(
                _as_string_list(existing_frontmatter.get("linked_tasks"))
                + context["linked_tasks"]
            ),
            key=str.casefold,
        ),
        "linked_syntheses": sorted(
            set(
                _as_string_list(existing_frontmatter.get("linked_syntheses"))
                + context["linked_syntheses_refs"]
            ),
            key=str.casefold,
        ),
        "linked_concepts": sorted(
            set(
                _as_string_list(existing_frontmatter.get("linked_concepts"))
                + context["linked_concepts_refs"]
            ),
            key=str.casefold,
        ),
        "linked_discovery_candidates": linked_discovery,
    }
    body = _render_prompt_pack(frontmatter, context, prompts, seed_candidates)
    before = path.read_text(encoding="utf-8") if path.exists() else None
    _write_prompt_pack(path, frontmatter, body)
    pack_ref = _prompt_pack_ref(paths, path)
    state = (
        "unchanged"
        if before == path.read_text(encoding="utf-8")
        else ("updated" if before else "created")
    )
    query_changed = _update_query_prompt_pack(paths, context["slug"], pack_ref)
    _refresh_prompt_navigation(paths)
    return {
        "vault": str(paths.vault),
        "id": pack_id,
        "prompt_pack": pack_ref,
        "status": frontmatter["status"],
        "state": state,
        "prompt_count": len(prompts),
        "prompt_types": list(PROMPT_TYPES),
        "query_updated": query_changed,
        "seed_provider": "discovery",
        "seed_candidates": [seed.__dict__ for seed in seed_candidates],
        "linked_discovery_candidates": linked_discovery,
    }


def list_prompt_packs(vault: Path | str) -> dict[str, Any]:
    from .importer import initialize_vault

    paths = initialize_vault(vault, rebuild=False)
    return _list_prompt_packs_from_paths(paths, ensure=True)


def _list_prompt_packs_from_paths(paths: VaultPaths, *, ensure: bool = False) -> dict[str, Any]:
    rows = []
    for path in _prompt_pack_paths(paths, ensure=ensure):
        try:
            frontmatter, body = _load_prompt_pack_path(paths, path)
        except ValueError:
            continue
        rows.append(
            {
                "id": _prompt_pack_id_from_path(path),
                "path": _prompt_pack_ref(paths, path),
                "status": frontmatter["status"],
                "query": frontmatter.get("query") or "",
                "project": frontmatter.get("project") or "",
                "linked_runs": len(frontmatter.get("linked_runs") or []),
                "prompt_count": len(re.findall(r"^###\s+", body, flags=re.MULTILINE)),
                "created_at": frontmatter.get("created_at"),
            }
        )
    return {"vault": str(paths.vault), "count": len(rows), "prompt_packs": rows}


def show_prompt_pack(vault: Path | str, prompt_pack_id: str) -> dict[str, Any]:
    from .importer import initialize_vault

    paths = initialize_vault(vault, rebuild=False)
    frontmatter, path, body = resolve_prompt_pack(paths, prompt_pack_id)
    return {
        "vault": str(paths.vault),
        "id": _prompt_pack_id_from_path(path),
        "prompt_pack": _prompt_pack_ref(paths, path),
        "frontmatter": frontmatter,
        "body": body.rstrip(),
    }


def mark_prompt_pack_used(
    vault: Path | str,
    prompt_pack_id: str,
    *,
    notes: str = "",
) -> dict[str, Any]:
    from .importer import initialize_vault

    paths = initialize_vault(vault, rebuild=False)
    frontmatter, path, body = resolve_prompt_pack(paths, prompt_pack_id)
    before_status = frontmatter["status"]
    frontmatter["status"] = "used"
    body = _append_usage_note(body, clean_markdown_text(notes) or "Marked used.")
    _write_prompt_pack(path, frontmatter, body)
    _refresh_prompt_navigation(paths)
    return {
        "vault": str(paths.vault),
        "id": _prompt_pack_id_from_path(path),
        "prompt_pack": _prompt_pack_ref(paths, path),
        "previous_status": before_status,
        "status": "used",
    }


def _resolve_run(paths: VaultPaths, run_id: str) -> RunRecord:
    normalized = (run_id or "").strip().strip("/")
    for run in load_run_records(paths):
        if run.slug == normalized:
            return run
    raise ValueError(f"No run found for run id: {run_id}")


def _write_run_prompt_links(
    paths: VaultPaths,
    run: RunRecord,
    *,
    prompt_pack_ref: str,
    query_ref: str,
) -> bool:
    run_dir = paths.runs / run.slug
    yaml_path = run_dir / "index.yaml"
    if not yaml_path.exists():
        return False
    import yaml

    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
    changed = False
    if prompt_pack_ref and data.get("prompt_pack") != prompt_pack_ref:
        data["prompt_pack"] = prompt_pack_ref
        changed = True
    if query_ref and data.get("query") != query_ref:
        data["query"] = query_ref
        changed = True
    if changed:
        write_yaml(yaml_path, data)
        from .importer import _write_run

        refreshed = _resolve_run(paths, run.slug)
        _write_run(paths, refreshed, load_source_cards(paths))
    return changed


def link_prompt_pack_run(vault: Path | str, prompt_pack_id: str, run_id: str) -> dict[str, Any]:
    from .importer import initialize_vault

    paths = initialize_vault(vault, rebuild=False)
    frontmatter, path, body = resolve_prompt_pack(paths, prompt_pack_id)
    run = _resolve_run(paths, run_id)
    linked_runs = _as_string_list(frontmatter.get("linked_runs"))
    changed = False
    if run.slug not in linked_runs:
        linked_runs.append(run.slug)
        frontmatter["linked_runs"] = sorted(linked_runs, key=str.casefold)
        changed = True
    if frontmatter.get("status") != "imported":
        frontmatter["status"] = "imported"
        changed = True
    updated_body = _append_run_note(body, run.slug)
    body_changed = updated_body != body
    if changed or body_changed:
        body = updated_body
        _write_prompt_pack(path, frontmatter, body)
    query_ref = str(frontmatter.get("query") or "")
    query_changed = False
    if query_ref:
        query_changed = query_link_run(paths.vault, Path(query_ref).stem, run.slug)["changed"]
    run_changed = _write_run_prompt_links(
        paths,
        run,
        prompt_pack_ref=_prompt_pack_ref(paths, path),
        query_ref=query_ref,
    )
    discovery_candidates_linked = 0
    discovery_refs = _as_string_list(frontmatter.get("linked_discovery_candidates"))
    if discovery_refs:
        from .discovery import mark_candidates_linked_run

        discovery_candidates_linked = mark_candidates_linked_run(
            paths.vault,
            discovery_refs,
            run_id=run.slug,
        )
    _refresh_prompt_navigation(paths)
    return {
        "vault": str(paths.vault),
        "id": _prompt_pack_id_from_path(path),
        "prompt_pack": _prompt_pack_ref(paths, path),
        "run": run.slug,
        "changed": changed
        or body_changed
        or query_changed
        or run_changed
        or bool(discovery_candidates_linked),
        "status": "imported",
        "query_changed": query_changed,
        "run_changed": run_changed,
        "discovery_candidates_linked": discovery_candidates_linked,
    }


def retire_prompt_pack(vault: Path | str, prompt_pack_id: str) -> dict[str, Any]:
    from .importer import initialize_vault

    paths = initialize_vault(vault, rebuild=False)
    frontmatter, path, body = resolve_prompt_pack(paths, prompt_pack_id)
    before_status = frontmatter["status"]
    frontmatter["status"] = "retired"
    body = _append_usage_note(body, "Retired.")
    _write_prompt_pack(path, frontmatter, body)
    _refresh_prompt_navigation(paths)
    return {
        "vault": str(paths.vault),
        "id": _prompt_pack_id_from_path(path),
        "prompt_pack": _prompt_pack_ref(paths, path),
        "previous_status": before_status,
        "status": "retired",
    }


def render_prompt_packs_index(vault: Path | str) -> str:
    paths = VaultPaths.from_root(vault)
    rows = _list_prompt_packs_from_paths(paths, ensure=False)["prompt_packs"]
    active = [row for row in rows if row["status"] not in {"imported", "retired"}]
    lines = [
        "# Scholar Labs Prompt Packs",
        "",
        "Prompt packs are human-in-the-loop discovery aids for Google Scholar Labs. "
        "They do not create canonical paper cards and Labs summaries are not evidence.",
        "",
        "## Active Prompt Packs",
        "",
    ]
    if active:
        lines.extend(
            [
                "| Prompt pack | Status | Query | Project | Runs |",
                "| --- | --- | --- | --- | ---: |",
            ]
        )
        for row in active:
            lines.append(
                "| "
                f"[{row['id']}](../{row['path']}) | "
                f"{row['status']} | "
                f"{row['query'] or '-'} | "
                f"{row['project'] or '-'} | "
                f"{row['linked_runs']} |"
            )
    else:
        lines.append("No active Scholar Labs prompt packs.")
    lines.extend(["", "## All Prompt Packs", ""])
    if rows:
        lines.extend(["| Prompt pack | Status | Created | Runs |", "| --- | --- | --- | ---: |"])
        for row in rows:
            lines.append(
                f"| [{row['id']}](../{row['path']}) | {row['status']} | "
                f"{row.get('created_at') or '-'} | {row['linked_runs']} |"
            )
    else:
        lines.append("No Scholar Labs prompt packs have been generated yet.")
    lines.append("")
    return "\n".join(lines)


def write_prompt_packs_index(vault: Path | str) -> dict[str, Any]:
    paths = VaultPaths.from_root(vault)
    path = paths.indexes / "scholar-labs-prompts.md"
    before = path.read_text(encoding="utf-8") if path.exists() else None
    write_text(path, render_prompt_packs_index(paths.vault))
    return {
        "index": ensure_relative(path, paths.vault),
        "changed": before != path.read_text(encoding="utf-8"),
    }


def doctor_prompt_packs(vault: Path | str) -> dict[str, Any]:
    from .importer import initialize_vault

    paths = initialize_vault(vault, rebuild=False)
    run_ids = {run.slug for run in load_run_records(paths)}
    rows = []
    issue_counts = Counter(
        {
            "invalid_status": 0,
            "missing_query": 0,
            "missing_project": 0,
            "missing_run": 0,
            "missing_query_backlink": 0,
            "missing_prompt_pack_index": 0,
        }
    )
    for path in _prompt_pack_paths(paths):
        try:
            raw_frontmatter, _ = read_frontmatter_markdown(path)
            frontmatter, _ = _load_prompt_pack_path(paths, path)
        except ValueError as exc:
            rows.append(
                {
                    "path": ensure_relative(path, paths.vault),
                    "ok": False,
                    "issues": [str(exc)],
                }
            )
            continue
        issues = []
        raw_status = str(raw_frontmatter.get("status") or "").strip()
        if raw_status not in PROMPT_PACK_STATUSES:
            issues.append(f"invalid status: {raw_status or 'missing'}")
            issue_counts["invalid_status"] += 1
        query_ref = str(frontmatter.get("query") or "")
        if query_ref and not (paths.vault / query_ref).exists():
            issues.append(f"missing query: {query_ref}")
            issue_counts["missing_query"] += 1
        if query_ref and (paths.vault / query_ref).exists():
            query_frontmatter, _ = read_frontmatter_markdown(paths.vault / query_ref)
            prompt_packs = _as_string_list(query_frontmatter.get("scholar_labs_prompt_pack"))
            if ensure_relative(path, paths.vault) not in prompt_packs:
                issues.append("query note does not link this prompt pack")
                issue_counts["missing_query_backlink"] += 1
        project = str(frontmatter.get("project") or "")
        if project and not _project_path(paths, project).exists():
            issues.append(f"missing project: {project}")
            issue_counts["missing_project"] += 1
        for run_id in frontmatter.get("linked_runs") or []:
            if run_id not in run_ids:
                issues.append(f"missing run: {run_id}")
                issue_counts["missing_run"] += 1
        rows.append(
            {
                "id": path.stem,
                "path": ensure_relative(path, paths.vault),
                "ok": not issues,
                "status": frontmatter["status"],
                "issues": issues,
            }
        )
    if not (paths.indexes / "scholar-labs-prompts.md").exists():
        issue_counts["missing_prompt_pack_index"] += 1
    return {
        "vault": str(paths.vault),
        "ok": not any(issue_counts.values()),
        "issue_counts": dict(issue_counts),
        "prompt_packs": rows,
        "google_scholar_network_calls": 0,
    }
