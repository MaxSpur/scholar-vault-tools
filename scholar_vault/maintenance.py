from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from .dashboards import _artifacts_without_sources, _render_command_block, _topic_opportunities
from .diagnostics import doctor_vault, notes_missing, pdf_doctor
from .digests import compile_status_summary
from .discovery import load_discovery_candidates
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
    compile_summary: dict[str, Any],
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
    try:
        discovery_paths = VaultPaths.from_root(status_summary["vault"])
        discovery_candidates = load_discovery_candidates(discovery_paths)
    except (OSError, ValueError, KeyError):
        discovery_candidates = []
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
                ["Discovery candidates", counts.get("discovery_candidates", 0)],
                [
                    "Open discovery candidates",
                    counts.get("open_discovery_candidates", 0),
                ],
                [
                    "Selected discovery candidates",
                    counts.get("selected_discovery_candidates", 0),
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
        "## Compile Queue",
        "",
        *_report_table(
            ["Status", "Count"],
            [[key, value] for key, value in (compile_summary.get("counts") or {}).items()],
            empty="No compile status rows.",
        ),
        "",
        *_report_table(
            ["Paper", "Citekey", "Status", "Digest", "Issues"],
            [
                [
                    row.get("paper"),
                    row.get("citekey"),
                    row.get("effective_status"),
                    row.get("paper_digest"),
                    "; ".join(row.get("issues") or []),
                ]
                for row in (compile_summary.get("papers") or [])
                if row.get("needs_action")
            ][:50],
            empty="No paper digests are currently uncompiled, draft, stale, or invalid.",
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
        "### Graph-assisted candidates",
        "",
        *_report_table(
            ["Candidate", "Status", "Source", "Reason"],
            [
                [
                    candidate.title,
                    candidate.status,
                    candidate.source,
                    candidate.reason,
                ]
                for candidate in discovery_candidates[:50]
            ],
            empty="No graph-assisted discovery candidates found.",
        ),
        "",
        "### Scholar Labs candidates without cards",
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
                "scholar-vault compile status --vault /path/to/vault --json",
                "scholar-vault compile doctor --vault /path/to/vault --json",
                "scholar-vault discover list --vault /path/to/vault",
                "scholar-vault discover doctor --vault /path/to/vault --json",
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
    write_queue: bool = False,
) -> dict[str, Any]:
    paths = VaultPaths.from_root(vault)
    paths.indexes.mkdir(parents=True, exist_ok=True)
    paths.tasks.mkdir(parents=True, exist_ok=True)
    current_date = report_date or datetime.now().astimezone().date().isoformat()
    status_summary = doctor_vault(paths.vault, staging_path=staging_path)
    pdf_summary = status_summary.get("pdfs") or pdf_doctor(paths.vault, staging_path=staging_path)
    notes_summary = notes_missing(paths.vault, heading="PDF reading notes")
    cards = load_source_cards(paths)
    compile_summary = compile_status_summary(paths, cards=cards)
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
            compile_summary=compile_summary,
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
    queue_summary = None
    if write_queue:
        queue_summary = _write_maintenance_queue_items(
            paths=paths,
            notes_summary=notes_summary,
            compile_summary=compile_summary,
            status_summary=status_summary,
            pdf_summary=pdf_summary,
            topics=topics,
            artifacts=artifacts,
        )
    return {
        "vault": str(paths.vault),
        "date": current_date,
        "report": ensure_relative(report_path, paths.vault),
        "task": ensure_relative(task_path, paths.vault),
        "queue": queue_summary,
        "paper_cards_modified": 0,
        "counts": {
            "reading_queue": notes_summary.get("missing", 0),
            "compile_needs_action": compile_summary.get("needs_action", 0),
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


def _write_maintenance_queue_items(
    *,
    paths: VaultPaths,
    notes_summary: dict[str, Any],
    compile_summary: dict[str, Any],
    status_summary: dict[str, Any],
    pdf_summary: dict[str, Any],
    topics: dict[str, Any],
    artifacts: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    from .self_improvement import create_queue_item, write_self_improvement_dashboard

    specs: list[dict[str, Any]] = []
    missing_reading = notes_summary.get("missing_cards") or []
    if missing_reading:
        specs.append(
            {
                "kind": "compile_paper",
                "title": "Read attached PDFs missing PDF reading notes",
                "stable_key": "maintenance:reading-notes",
                "required_evidence": "pdf",
                "success_criteria": "Each linked paper has PDF-grounded reading notes.",
                "notes": f"{len(missing_reading)} attached paper(s) are missing reading notes.",
                "citekeys": [row.get("citekey") for row in missing_reading if row.get("citekey")],
                "files": [row.get("paper") for row in missing_reading if row.get("paper")],
            }
        )
    compile_rows = [
        row for row in (compile_summary.get("papers") or []) if row.get("needs_action")
    ]
    if compile_rows:
        specs.append(
            {
                "kind": "compile_paper",
                "title": "Compile or repair paper digest drafts",
                "stable_key": "maintenance:compile-digests",
                "required_evidence": "pdf",
                "success_criteria": (
                    "Paper digest records are compiled, reviewed, or intentionally deferred."
                ),
                "notes": f"{len(compile_rows)} paper digest row(s) need action.",
                "citekeys": [row.get("citekey") for row in compile_rows if row.get("citekey")],
                "files": [row.get("paper") for row in compile_rows if row.get("paper")],
            }
        )
    metadata_issues = _metadata_issue_count(status_summary)
    if metadata_issues:
        specs.append(
            {
                "kind": "lint_fix",
                "title": "Resolve metadata, citation, abstract, and keyword issues",
                "stable_key": "maintenance:metadata-issues",
                "required_evidence": "metadata",
                "success_criteria": (
                    "Status and enrichment doctors report no unresolved metadata rows."
                ),
                "notes": f"{metadata_issues} metadata issue row(s) were reported.",
            }
        )
    candidate_rows = status_summary.get("candidate_results_without_cards") or []
    if candidate_rows:
        specs.append(
            {
                "kind": "discover_sources",
                "title": "Review candidate-only Scholar Labs results",
                "stable_key": "maintenance:candidate-discovery",
                "required_evidence": "web",
                "success_criteria": (
                    "Candidate-only results are either imported with evidence or "
                    "intentionally ignored."
                ),
                "notes": f"{len(candidate_rows)} candidate result(s) have no canonical paper card.",
                "runs": [row.get("run_id") for row in candidate_rows if row.get("run_id")],
            }
        )
    staging = pdf_summary.get("staging") or {}
    actionable_staging = staging.get("actionable_pdf_count") or 0
    if actionable_staging:
        specs.append(
            {
                "kind": "discover_sources",
                "title": "Triage actionable staging PDFs",
                "stable_key": "maintenance:staging-pdfs",
                "required_evidence": "pdf",
                "success_criteria": (
                    "Actionable staging PDFs are attached, imported, or moved aside."
                ),
                "notes": (
                    f"{actionable_staging} staging PDF(s) are not duplicates already in the vault."
                ),
            }
        )
    noisy_topics = topics.get("noisy") or []
    if noisy_topics:
        specs.append(
            {
                "kind": "lint_fix",
                "title": "Clean prompt-boilerplate topic labels",
                "stable_key": "maintenance:noisy-topics",
                "required_evidence": "metadata",
                "success_criteria": (
                    "Topic-map dry-run no longer reports prompt-boilerplate labels."
                ),
                "notes": ", ".join(row.get("topic", "") for row in noisy_topics[:20]),
            }
        )
    synthesis_needs = _artifacts_without_sources(artifacts.get("syntheses") or [])
    if synthesis_needs:
        specs.append(
            {
                "kind": "update_synthesis",
                "title": "Add source links to syntheses without enough evidence",
                "stable_key": "maintenance:synthesis-source-links",
                "required_evidence": "pdf",
                "success_criteria": "Syntheses have enough linked source records for their claims.",
                "notes": f"{len(synthesis_needs)} synthesis note(s) lack source links.",
                "files": [row.get("path") for row in synthesis_needs if row.get("path")],
            }
        )

    created = 0
    unchanged = 0
    items: list[dict[str, Any]] = []
    for spec in specs:
        summary = create_queue_item(
            paths.vault,
            priority="normal",
            created_by="lint",
            refresh_dashboard=False,
            **spec,
        )
        created += int(bool(summary.get("created")))
        unchanged += int(not summary.get("created"))
        items.append(
            {
                "id": summary["id"],
                "created": summary["created"],
                "queue_item": summary["queue_item"],
                "stable_key": spec.get("stable_key"),
            }
        )
    dashboard = write_self_improvement_dashboard(paths.vault)
    return {
        "requested": True,
        "created": created,
        "unchanged": unchanged,
        "items": items,
        "dashboard": dashboard,
    }
