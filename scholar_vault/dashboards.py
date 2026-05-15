from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .citations import refresh_metadata_completeness
from .diagnostics import _repeated_unmatched_files, _unmatched_rows_from_manifests
from .models import ImportManifest, RunRecord, SourceCard
from .obsidian import (
    _artifact_link,
    _card_has_valid_pdf,
    _card_id,
    _display_path,
    _markdown_heading_re,
    _markdown_table,
    _paper_link,
    _status_counts,
)
from .sources import VaultPaths, ensure_relative, normalize_title, topic_slug, write_text
from .topics import _topic_report


def _reading_queue_rows(
    paths: VaultPaths,
    cards: list[SourceCard],
    *,
    heading: str = "PDF reading notes",
) -> list[dict[str, Any]]:
    heading_re = _markdown_heading_re(heading)
    rows: list[dict[str, Any]] = []
    for card in cards:
        if card.status != "active" or not (card.pdf_status == "attached" or card.pdf):
            continue
        if heading_re.search(card.notes or ""):
            continue
        rows.append(
            {
                "paper": f"papers/{card.slug}.md",
                "paper_link": _paper_link(card),
                "citekey": _card_id(card),
                "year": card.year,
                "pdf": card.pdf or "missing",
                "pdf_exists": _card_has_valid_pdf(paths, card),
            }
        )
    return rows


def _metadata_issue_label(card: SourceCard) -> list[str]:
    issue_states = {"incomplete", "ambiguous", "unresolved"}
    issues: list[str] = []
    if card.enrichment_refresh:
        issues.append("metadata refresh requested")
    if card.enrichment_status in issue_states or card.enrichment_missing:
        missing = ", ".join(card.enrichment_missing)
        label = f"metadata {card.enrichment_status}"
        issues.append(f"{label} ({missing})" if missing else label)
    if card.citation_status in {"ambiguous", "unresolved"}:
        issues.append(f"citation {card.citation_status}")
    if card.doi_status in {"ambiguous", "unresolved"}:
        issues.append(f"DOI {card.doi_status}")
    if card.abstract_status in {"missing", "ambiguous", "unresolved"}:
        issues.append(f"abstract {card.abstract_status}")
    if card.pdf and not card.keywords and card.publication_keywords_status != "absent":
        issues.append("missing publication keywords")
    return issues


def _metadata_issue_rows(cards: list[SourceCard]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for card in cards:
        refresh_metadata_completeness(card)
        issues = _metadata_issue_label(card)
        if not issues:
            continue
        rows.append(
            {
                "paper": f"papers/{card.slug}.md",
                "paper_link": _paper_link(card),
                "citekey": _card_id(card),
                "issues": issues,
                "doi": card.doi or "",
                "venue": card.venue or "",
            }
        )
    return rows


def _metadata_not_enriched_rows(cards: list[SourceCard]) -> list[dict[str, Any]]:
    return [
        {
            "paper": f"papers/{card.slug}.md",
            "paper_link": _paper_link(card),
            "citekey": _card_id(card),
            "title": card.title,
        }
        for card in cards
        if card.enrichment_status == "missing"
    ]


def _pdf_issue_summary(
    paths: VaultPaths,
    cards: list[SourceCard],
    manifests: list[ImportManifest],
) -> dict[str, Any]:
    referenced_pdf_paths: set[Path] = set()
    cards_without_pdf: list[dict[str, Any]] = []
    missing_card_pdfs: list[dict[str, Any]] = []
    for card in cards:
        if not card.pdf:
            cards_without_pdf.append(
                {
                    "paper": f"papers/{card.slug}.md",
                    "paper_link": _paper_link(card),
                    "citekey": _card_id(card),
                    "title": card.title,
                }
            )
            continue
        pdf_path = Path(card.pdf)
        if not pdf_path.is_absolute():
            pdf_path = paths.vault / pdf_path
        if pdf_path.exists():
            referenced_pdf_paths.add(pdf_path.resolve())
        else:
            missing_card_pdfs.append(
                {
                    "paper": f"papers/{card.slug}.md",
                    "paper_link": _paper_link(card),
                    "citekey": _card_id(card),
                    "pdf": card.pdf,
                }
            )
    pdf_files = sorted(paths.pdfs.glob("*.pdf"))
    orphan_pdfs = [
        _display_path(path, paths.vault)
        for path in pdf_files
        if path.resolve() not in referenced_pdf_paths
    ]
    duplicate_style = [
        _display_path(path, paths.vault)
        for path in pdf_files
        if re.search(r"-\d+\.pdf$", path.name, flags=re.IGNORECASE)
    ]
    unmatched_rows = _unmatched_rows_from_manifests(manifests)
    return {
        "cards_without_pdf": cards_without_pdf,
        "missing_card_pdfs": missing_card_pdfs,
        "orphan_pdfs": orphan_pdfs,
        "duplicate_style_filenames": duplicate_style,
        "historical_unmatched_entries": len(unmatched_rows),
        "repeated_unmatched_files": _repeated_unmatched_files(unmatched_rows),
    }


def _stale_topic_pages(paths: VaultPaths, topic_cards: dict[str, list[SourceCard]]) -> list[str]:
    active_slugs = {topic_slug(topic) for topic in topic_cards}
    return [
        ensure_relative(path, paths.vault)
        for path in sorted(paths.topics.glob("*.md"))
        if path.stem not in active_slugs
    ]


def _artifacts_without_sources(artifacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [artifact for artifact in artifacts if not artifact.get("sources")]


def _topic_opportunities(
    topic_cards: dict[str, list[SourceCard]],
    syntheses: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    synthesis_text = normalize_title(" ".join(str(item.get("title") or "") for item in syntheses))
    rows = []
    for topic, cards in sorted(topic_cards.items(), key=lambda item: (-len(item[1]), item[0])):
        if len(cards) < 2:
            continue
        topic_key = normalize_title(topic)
        if topic_key and topic_key in synthesis_text:
            continue
        rows.append(
            {
                "topic": topic,
                "papers": len(cards),
                "example_papers": ", ".join(card.title for card in cards[:3]),
            }
        )
    return rows[:20]


def _render_command_block(commands: list[str]) -> list[str]:
    lines = ["## Useful CLI commands", ""]
    for command in commands:
        lines.extend(["```fish", command, "```", ""])
    return lines


def _render_dashboard_index(
    paths: VaultPaths,
    cards: list[SourceCard],
    runs: list[RunRecord],
    manifests: list[ImportManifest],
    artifacts: dict[str, list[dict[str, Any]]],
    topic_cards: dict[str, list[SourceCard]],
) -> str:
    reading_rows = _reading_queue_rows(paths, cards)
    metadata_rows = _metadata_issue_rows(cards)
    pdf_summary = _pdf_issue_summary(paths, cards, manifests)
    topic_report = _topic_report(cards, limit=12)
    stale_topics = _stale_topic_pages(paths, topic_cards)
    concepts = artifacts.get("concepts") or []
    syntheses = artifacts.get("syntheses") or []
    tasks = artifacts.get("tasks") or []
    queries = artifacts.get("queries") or []
    projects = artifacts.get("projects") or []
    issue_counts = {
        "Reading queue": len(reading_rows),
        "Metadata issues": len(metadata_rows),
        "Orphan PDFs": len(pdf_summary["orphan_pdfs"]),
        "Missing card PDFs": len(pdf_summary["missing_card_pdfs"]),
        "Historical unmatched records": pdf_summary["historical_unmatched_entries"],
        "Noisy topics": len(topic_report["noisy"]),
        "Stale topic pages": len(stale_topics),
        "Concepts": len(concepts),
        "Syntheses": len(syntheses),
        "Tasks": len(tasks),
        "Queries": len(queries),
        "Projects": len(projects),
    }
    lines = [
        "# Scholar Vault Dashboard",
        "",
        "Plain Markdown dashboard for Obsidian and CLI-oriented maintenance. No Obsidian "
        "plugin is required for these views.",
        "",
        "Scholar Labs summaries, generated indexes, and topic pages are navigation aids, not "
        "evidence. Read linked PDFs before factual synthesis.",
        "",
        "## Views",
        "",
        "- [Paper status](paper-status.md)",
        "- [Reading queue](reading-queue.md)",
        "- [Metadata issues](metadata-issues.md)",
        "- [PDF issues](pdf-issues.md)",
        "- [Synthesis dashboard](synthesis-dashboard.md)",
        "- [Search index](search-index.md)",
        "- [Research queries](queries.md)",
        "- [Projects](projects.md)",
        "",
        "## Open queues",
        "",
        *_markdown_table(
            ["Queue", "Count"],
            [[key, value] for key, value in issue_counts.items()],
        ),
        "",
        "## Reading queue preview",
        "",
        *_markdown_table(
            ["Paper", "Citekey", "PDF"],
            [
                [row["paper_link"], row["citekey"], row["pdf"]]
                for row in reading_rows[:10]
            ],
            empty="No selected attached papers are missing PDF reading notes.",
        ),
        "",
        "## Metadata issue preview",
        "",
        *_markdown_table(
            ["Paper", "Citekey", "Issues"],
            [
                [row["paper_link"], row["citekey"], "; ".join(row["issues"])]
                for row in metadata_rows[:10]
            ],
            empty="No actionable metadata, citation, abstract, or keyword issues found.",
        ),
        "",
        "## Topic noise preview",
        "",
        *_markdown_table(
            ["Topic", "Count"],
            [[row["topic"], row["count"]] for row in topic_report["noisy"][:12]],
            empty="No prompt-boilerplate topic labels detected.",
        ),
        "",
    ]
    lines.extend(
        _render_command_block(
            [
                "scholar-vault maintenance-report --vault /path/to/vault",
                'scholar-vault notes-missing --vault /path/to/vault --heading "PDF reading notes"',
                "scholar-vault enrich --vault /path/to/vault --ui",
                "scholar-vault pdf-doctor --vault /path/to/vault --json",
                "scholar-vault topic-map --vault /path/to/vault --preset prompt-boilerplate",
            ]
        )
    )
    return "\n".join(lines)


def _render_paper_status_index(
    paths: VaultPaths,
    cards: list[SourceCard],
    reading_rows: list[dict[str, Any]],
    metadata_rows: list[dict[str, Any]],
) -> str:
    attached = sum(1 for card in cards if _card_has_valid_pdf(paths, card))
    counts = [
        ["Paper cards", len(cards)],
        ["Attached PDF cards", attached],
        ["Missing PDF cards", len(cards) - attached],
        ["Reading queue", len(reading_rows)],
        ["Metadata issue cards", len(metadata_rows)],
    ]
    status_fields = [
        ("PDF status", _status_counts(cards, "pdf_status")),
        ("Enrichment status", _status_counts(cards, "enrichment_status")),
        ("Citation status", _status_counts(cards, "citation_status")),
        ("Abstract status", _status_counts(cards, "abstract_status")),
        ("Publication keyword status", _status_counts(cards, "publication_keywords_status")),
    ]
    lines = [
        "# Paper Status",
        "",
        *_markdown_table(["Metric", "Count"], counts),
        "",
    ]
    for title, status_counts in status_fields:
        lines.extend(
            [
                f"## {title}",
                "",
                *_markdown_table(
                    ["Status", "Count"],
                    [[key, value] for key, value in status_counts.items()],
                ),
                "",
            ]
        )
    lines.extend(
        _render_command_block(
            [
                "scholar-vault status --vault /path/to/vault --json",
                "scholar-vault rebuild --vault /path/to/vault",
            ]
        )
    )
    return "\n".join(lines)


def _render_reading_queue_index(reading_rows: list[dict[str, Any]]) -> str:
    lines = [
        "# Reading Queue",
        "",
        "Selected or attached paper cards missing a `PDF reading notes` heading under "
        "`## Notes`.",
        "",
        *_markdown_table(
            ["Paper", "Citekey", "Year", "PDF", "PDF exists"],
            [
                [
                    row["paper_link"],
                    row["citekey"],
                    row["year"] or "",
                    row["pdf"],
                    row["pdf_exists"],
                ]
                for row in reading_rows
            ],
            empty="No selected attached papers are missing PDF reading notes.",
        ),
        "",
    ]
    lines.extend(
        _render_command_block(
            [
                'scholar-vault notes-missing --vault /path/to/vault --heading "PDF reading notes"',
                "scholar-vault rebuild --vault /path/to/vault",
            ]
        )
    )
    return "\n".join(lines)


def _render_metadata_issues_index(
    metadata_rows: list[dict[str, Any]],
    diagnostic_rows: list[dict[str, Any]],
) -> str:
    lines = [
        "# Metadata Issues",
        "",
        "Actionable citation, DOI, enrichment, abstract, and publication-keyword follow-up.",
        "",
        "## Actionable issues",
        "",
        *_markdown_table(
            ["Paper", "Citekey", "Issues", "DOI", "Venue"],
            [
                [
                    row["paper_link"],
                    row["citekey"],
                    "; ".join(row["issues"]),
                    row["doi"],
                    row["venue"],
                ]
                for row in metadata_rows
            ],
            empty="No actionable metadata issues found.",
        ),
        "",
        "## Not-yet-enriched diagnostics",
        "",
        "These rows are diagnostics, not defects by themselves.",
        "",
        *_markdown_table(
            ["Paper", "Citekey"],
            [[row["paper_link"], row["citekey"]] for row in diagnostic_rows[:100]],
            empty="No papers are marked with untouched metadata enrichment.",
        ),
        "",
    ]
    lines.extend(
        _render_command_block(
            [
                "scholar-vault enrich --vault /path/to/vault --ui",
                "scholar-vault resolve-citation --vault /path/to/vault --citekey <citekey>",
                "scholar-vault set-abstract --vault /path/to/vault --citekey <citekey>",
                "scholar-vault set-keywords --vault /path/to/vault --citekey <citekey>",
            ]
        )
    )
    return "\n".join(lines)


def _render_pdf_issues_index(pdf_summary: dict[str, Any]) -> str:
    lines = [
        "# PDF Issues",
        "",
        "Vault PDF inventory view. Candidate results without cards are discovery context, not "
        "missing canonical sources.",
        "",
        "## Cards without a PDF field",
        "",
        *_markdown_table(
            ["Paper", "Citekey"],
            [
                [row["paper_link"], row["citekey"]]
                for row in pdf_summary["cards_without_pdf"]
            ],
            empty="No cards are missing a PDF field.",
        ),
        "",
        "## Card PDF files missing on disk",
        "",
        *_markdown_table(
            ["Paper", "Citekey", "PDF"],
            [
                [row["paper_link"], row["citekey"], row["pdf"]]
                for row in pdf_summary["missing_card_pdfs"]
            ],
            empty="No card PDF links point at missing files.",
        ),
        "",
        "## Orphan vault PDFs",
        "",
        *_markdown_table(
            ["PDF"],
            [[path] for path in pdf_summary["orphan_pdfs"]],
            empty="No orphan vault PDFs found.",
        ),
        "",
        "## Duplicate-style filenames",
        "",
        *_markdown_table(
            ["PDF"],
            [[path] for path in pdf_summary["duplicate_style_filenames"]],
            empty="No duplicate-style PDF filenames found.",
        ),
        "",
        "## Historical unmatched records",
        "",
        f"- Historical unmatched entries: {pdf_summary['historical_unmatched_entries']}",
        "",
        *_markdown_table(
            ["Filename", "Count", "Runs", "Best score"],
            [
                [
                    row["filename"],
                    row["count"],
                    ", ".join(row["runs"]),
                    row["best_score"],
                ]
                for row in pdf_summary["repeated_unmatched_files"]
            ],
            empty="No repeated historical unmatched files found.",
        ),
        "",
    ]
    lines.extend(
        _render_command_block(
            [
                "scholar-vault pdf-doctor --vault /path/to/vault --json",
                "scholar-vault match-staging --vault /path/to/vault --ui",
            ]
        )
    )
    return "\n".join(lines)


def _render_synthesis_dashboard(
    artifacts: dict[str, list[dict[str, Any]]],
    topic_cards: dict[str, list[SourceCard]],
    stale_topics: list[str],
    topic_report: dict[str, Any],
) -> str:
    concepts = artifacts.get("concepts") or []
    syntheses = artifacts.get("syntheses") or []
    tasks = artifacts.get("tasks") or []
    concept_needs = _artifacts_without_sources(concepts)
    synthesis_needs = _artifacts_without_sources(syntheses)
    opportunities = _topic_opportunities(topic_cards, syntheses)
    lines = [
        "# Synthesis Dashboard",
        "",
        "Concepts are reusable methods, algorithms, visual encodings, datasets, evaluation "
        "protocols, and terminology. Syntheses are evidence-backed cross-paper answers. "
        "Tasks are open questions, gaps, and next searches.",
        "",
        "## Research artifacts",
        "",
        *_markdown_table(
            ["Type", "Count"],
            [
                ["Concepts", len(concepts)],
                ["Syntheses", len(syntheses)],
                ["Tasks", len(tasks)],
            ],
        ),
        "",
        "## Concepts without source links",
        "",
        *_markdown_table(
            ["Concept", "Type"],
            [[_artifact_link(row), row.get("type") or "concept"] for row in concept_needs],
            empty="No concept cards are missing source links.",
        ),
        "",
        "## Syntheses without source links",
        "",
        *_markdown_table(
            ["Synthesis", "Type"],
            [[_artifact_link(row), row.get("type") or "synthesis"] for row in synthesis_needs],
            empty="No synthesis notes are missing source links.",
        ),
        "",
        "## Synthesis opportunities by topic",
        "",
        *_markdown_table(
            ["Topic", "Papers", "Example papers"],
            [
                [row["topic"], row["papers"], row["example_papers"]]
                for row in opportunities
            ],
            empty="No multi-paper topic opportunities detected.",
        ),
        "",
        "## Topic cleanup",
        "",
        *_markdown_table(
            ["Noisy topic", "Count"],
            [[row["topic"], row["count"]] for row in topic_report["noisy"]],
            empty="No prompt-boilerplate topic labels detected.",
        ),
        "",
        "## Stale generated topic pages",
        "",
        *_markdown_table(
            ["Topic page"],
            [[path] for path in stale_topics],
            empty="No stale generated topic pages detected.",
        ),
        "",
    ]
    lines.extend(
        _render_command_block(
            [
                "scholar-vault topic-map --vault /path/to/vault --preset prompt-boilerplate",
                (
                    "scholar-vault topic-map --vault /path/to/vault "
                    "--preset prompt-boilerplate --apply"
                ),
                "scholar-vault concept-index --vault /path/to/vault",
                "scholar-vault rebuild --vault /path/to/vault",
            ]
        )
    )
    return "\n".join(lines)


def _write_dashboard_indexes(
    paths: VaultPaths,
    cards: list[SourceCard],
    runs: list[RunRecord],
    manifests: list[ImportManifest],
    artifacts: dict[str, list[dict[str, Any]]],
    topic_cards: dict[str, list[SourceCard]],
) -> int:
    reading_rows = _reading_queue_rows(paths, cards)
    metadata_rows = _metadata_issue_rows(cards)
    diagnostic_rows = _metadata_not_enriched_rows(cards)
    pdf_summary = _pdf_issue_summary(paths, cards, manifests)
    topic_report = _topic_report(cards, limit=30)
    stale_topics = _stale_topic_pages(paths, topic_cards)
    outputs = {
        "dashboard.md": _render_dashboard_index(
            paths,
            cards,
            runs,
            manifests,
            artifacts,
            topic_cards,
        ),
        "paper-status.md": _render_paper_status_index(
            paths,
            cards,
            reading_rows,
            metadata_rows,
        ),
        "reading-queue.md": _render_reading_queue_index(reading_rows),
        "metadata-issues.md": _render_metadata_issues_index(metadata_rows, diagnostic_rows),
        "pdf-issues.md": _render_pdf_issues_index(pdf_summary),
        "synthesis-dashboard.md": _render_synthesis_dashboard(
            artifacts,
            topic_cards,
            stale_topics,
            topic_report,
        ),
    }
    for filename, content in outputs.items():
        write_text(paths.indexes / filename, content)
    return len(outputs)
