from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from .dashboards import _artifacts_without_sources, _render_command_block, _topic_opportunities
from .diagnostics import doctor_vault, notes_missing, pdf_doctor
from .models import SourceCard
from .obsidian import _collect_research_artifacts, _markdown_table
from .render import group_cards_by_topic
from .sources import VaultPaths, ensure_relative, load_source_cards, write_text


def _metadata_issue_count(summary: dict[str, Any]) -> int:
    issue_counts = summary.get("issue_counts") or {}
    return sum(int(value or 0) for value in issue_counts.values())


def _report_table(headers: list[str], rows: list[list[object]], *, empty: str) -> list[str]:
    return _markdown_table(headers, rows, empty=empty)


def _render_maintenance_report(
    *,
    report_date: str,
    status_summary: dict[str, Any],
    pdf_summary: dict[str, Any],
    notes_summary: dict[str, Any],
    artifacts: dict[str, list[dict[str, Any]]],
    topic_cards: dict[str, list[SourceCard]],
) -> str:
    counts = status_summary.get("counts") or {}
    topics = status_summary.get("topics") or {}
    staging = pdf_summary.get("staging")
    concepts = artifacts.get("concepts") or []
    syntheses = artifacts.get("syntheses") or []
    tasks = artifacts.get("tasks") or []
    concept_needs = _artifacts_without_sources(concepts)
    synthesis_needs = _artifacts_without_sources(syntheses)
    opportunities = _topic_opportunities(topic_cards, syntheses)
    metadata_issues = status_summary.get("metadata_issues") or {}
    lines = [
        f"# Maintenance Report - {report_date}",
        "",
        "Generated triage report. It writes this report and a task note only; it does not "
        "modify paper cards, PDFs, run records, metadata, topics, or provenance.",
        "",
        "Scholar Labs candidate results without canonical paper cards are discovery context, "
        "not defects in the selected-only workflow.",
        "",
        "## Status / Doctor Summary",
        "",
        *_report_table(
            ["Metric", "Count"],
            [
                ["Paper cards", counts.get("paper_cards", 0)],
                ["Runs", counts.get("runs", 0)],
                ["PDF files", counts.get("pdf_files", 0)],
                ["Attached PDF cards", counts.get("attached_pdf_cards", 0)],
                ["Missing PDF cards", counts.get("missing_pdf_cards", 0)],
                [
                    "Candidate results without cards",
                    counts.get("candidate_results_without_cards", 0),
                ],
                ["Historical unmatched entries", counts.get("historical_unmatched_entries", 0)],
                ["Active staging PDFs", counts.get("active_staging_pdfs") or 0],
                [
                    "Active staging actionable PDFs",
                    counts.get("active_staging_actionable_pdfs") or 0,
                ],
            ],
            empty="No status rows.",
        ),
        "",
        "## PDF Doctor Summary",
        "",
        *_report_table(
            ["Issue", "Count"],
            [
                ["Cards without PDF field", len(pdf_summary.get("cards_without_pdf") or [])],
                ["Missing card PDF files", len(pdf_summary.get("missing_card_pdfs") or [])],
                ["Orphan PDFs", len(pdf_summary.get("orphan_pdfs") or [])],
                [
                    "Duplicate-style filenames",
                    len(pdf_summary.get("duplicate_style_filenames") or []),
                ],
                ["Duplicate PDF hashes", len(pdf_summary.get("duplicate_hashes") or [])],
                [
                    "Repeated unmatched files",
                    len(pdf_summary.get("repeated_unmatched_files") or []),
                ],
            ],
            empty="No PDF issue rows.",
        ),
        "",
        "## Reading Queue",
        "",
        f"- Eligible attached cards: {notes_summary.get('eligible_cards', 0)}",
        f"- Missing `{notes_summary.get('heading')}`: {notes_summary.get('missing', 0)}",
        "",
        *_report_table(
            ["Paper", "Citekey", "PDF"],
            [
                [
                    f"[{row['title']}](../{row['paper']})",
                    row.get("citekey") or "",
                    row.get("pdf") or "",
                ]
                for row in notes_summary.get("missing_cards", [])[:50]
            ],
            empty="No selected attached papers are missing PDF reading notes.",
        ),
        "",
        "## Enrichment Issues",
        "",
        *_report_table(
            ["Issue class", "Count"],
            [
                [key.replace("_", " "), len(rows)]
                for key, rows in sorted(metadata_issues.items())
            ],
            empty="No enrichment issue rows.",
        ),
        "",
        "## Candidate Discovery Backlog",
        "",
        "These rows are optional discovery context unless you choose to fetch/import PDFs.",
        "",
        *_report_table(
            ["Run", "Rank", "Title", "Status"],
            [
                [
                    row.get("run_id"),
                    row.get("rank"),
                    row.get("title"),
                    row.get("status"),
                ]
                for row in status_summary.get("candidate_results_without_cards", [])[:50]
            ],
            empty="No candidate-only Scholar Labs results found.",
        ),
        "",
        "## Historical Unmatched Records",
        "",
        f"- Historical unmatched entries: {pdf_summary.get('historical_unmatched_entries', 0)}",
        "",
        *_report_table(
            ["Filename", "Count", "Runs", "Best score"],
            [
                [row["filename"], row["count"], ", ".join(row["runs"]), row["best_score"]]
                for row in pdf_summary.get("repeated_unmatched_files", [])
            ],
            empty="No repeated historical unmatched records.",
        ),
        "",
        "## Active Staging Issues",
        "",
    ]
    if staging:
        lines.extend(
            [
                f"- Staging folder: {staging.get('path')}",
                f"- PDFs in staging: {staging.get('pdf_count', 0)}",
                f"- Already duplicated in vault: {staging.get('duplicate_count', 0)}",
                f"- Actionable non-duplicate PDFs: {staging.get('actionable_pdf_count', 0)}",
                "",
            ]
        )
    else:
        lines.extend(
            [
                "No staging folder was provided or configured for this report.",
                "",
            ]
        )
    lines.extend(
        [
            "## Topic Noise",
            "",
            *_report_table(
                ["Topic", "Count"],
                [[row["topic"], row["count"]] for row in topics.get("noisy", [])],
                empty="No prompt-boilerplate topic labels detected.",
            ),
            "",
            "## Concepts, Syntheses, And Tasks",
            "",
            *_report_table(
                ["Artifact type", "Count", "Needs source links"],
                [
                    ["Concepts", len(concepts), len(concept_needs)],
                    ["Syntheses", len(syntheses), len(synthesis_needs)],
                    ["Tasks", len(tasks), ""],
                ],
                empty="No research artifacts found.",
            ),
            "",
            "## Missing Synthesis Opportunities",
            "",
            *_report_table(
                ["Topic", "Papers", "Example papers"],
                [
                    [row["topic"], row["papers"], row["example_papers"]]
                    for row in opportunities
                ],
                empty="No multi-paper topic opportunities detected.",
            ),
            "",
        ]
    )
    lines.extend(
        _render_command_block(
            [
                "scholar-vault status --vault /path/to/vault --json",
                "scholar-vault pdf-doctor --vault /path/to/vault --json",
                'scholar-vault notes-missing --vault /path/to/vault --heading "PDF reading notes"',
                "scholar-vault enrich --vault /path/to/vault --ui",
                "scholar-vault topic-map --vault /path/to/vault --preset prompt-boilerplate",
                (
                    "scholar-vault topic-map --vault /path/to/vault "
                    "--preset prompt-boilerplate --apply"
                ),
                "scholar-vault rebuild --vault /path/to/vault",
            ]
        )
    )
    return "\n".join(lines)


def _render_maintenance_task(
    *,
    report_date: str,
    report_path: str,
    status_summary: dict[str, Any],
    notes_summary: dict[str, Any],
) -> str:
    counts = status_summary.get("counts") or {}
    issue_total = _metadata_issue_count(status_summary)
    lines = [
        f"# {report_date} maintenance",
        "",
        f"Report: [{report_path}](../{report_path})",
        "",
        "## Checklist",
        "",
        f"- [ ] Review reading queue ({notes_summary.get('missing', 0)} papers).",
        f"- [ ] Resolve enrichment issues ({issue_total} issue rows).",
        f"- [ ] Check active staging PDFs ({counts.get('active_staging_actionable_pdfs') or 0}).",
        "- [ ] Run topic cleanup dry-run before applying prompt-boilerplate changes.",
        "- [ ] Add/update concepts or syntheses only after reading PDFs as evidence.",
        "",
        "## Commands",
        "",
        "```fish",
        "scholar-vault maintenance-report --vault /path/to/vault",
        "scholar-vault enrich --vault /path/to/vault --ui",
        "scholar-vault rebuild --vault /path/to/vault",
        "```",
        "",
    ]
    return "\n".join(lines)


def maintenance_report(
    vault: Path | str,
    *,
    staging_path: Path | str | None = None,
    report_date: str | None = None,
) -> dict[str, Any]:
    paths = VaultPaths.from_root(vault)
    paths.indexes.mkdir(parents=True, exist_ok=True)
    paths.tasks.mkdir(parents=True, exist_ok=True)
    current_date = report_date or datetime.now().astimezone().date().isoformat()
    status_summary = doctor_vault(paths.vault, staging_path=staging_path)
    pdf_summary = status_summary.get("pdfs") or pdf_doctor(paths.vault, staging_path=staging_path)
    notes_summary = notes_missing(paths.vault, heading="PDF reading notes")
    cards = load_source_cards(paths)
    topic_cards = group_cards_by_topic(cards)
    artifacts = _collect_research_artifacts(paths)
    report_path = paths.indexes / "maintenance-report.md"
    task_path = paths.tasks / f"{current_date}-maintenance.md"
    write_text(
        report_path,
        _render_maintenance_report(
            report_date=current_date,
            status_summary=status_summary,
            pdf_summary=pdf_summary,
            notes_summary=notes_summary,
            artifacts=artifacts,
            topic_cards=topic_cards,
        ),
    )
    write_text(
        task_path,
        _render_maintenance_task(
            report_date=current_date,
            report_path=ensure_relative(report_path, paths.vault),
            status_summary=status_summary,
            notes_summary=notes_summary,
        ),
    )
    topics = status_summary.get("topics") or {}
    return {
        "vault": str(paths.vault),
        "date": current_date,
        "report": ensure_relative(report_path, paths.vault),
        "task": ensure_relative(task_path, paths.vault),
        "paper_cards_modified": 0,
        "counts": {
            "reading_queue": notes_summary.get("missing", 0),
            "metadata_issue_rows": _metadata_issue_count(status_summary),
            "candidate_results_without_cards": len(
                status_summary.get("candidate_results_without_cards", [])
            ),
            "historical_unmatched_entries": pdf_summary.get("historical_unmatched_entries", 0),
            "active_staging_actionable_pdfs": (
                (pdf_summary.get("staging") or {}).get("actionable_pdf_count") or 0
            ),
            "noisy_topics": len(topics.get("noisy", [])),
            "concepts_without_sources": len(
                _artifacts_without_sources(artifacts.get("concepts") or [])
            ),
            "syntheses_without_sources": len(
                _artifacts_without_sources(artifacts.get("syntheses") or [])
            ),
        },
    }
