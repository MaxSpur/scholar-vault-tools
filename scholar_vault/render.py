from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

from .models import ImportManifest, RunRecord, SourceCard
from .sources import dump_frontmatter, run_display_title, run_note_path, topic_slug

TEMPLATE_ROOT = Path(__file__).resolve().parent.parent / "templates"
ENVIRONMENT = Environment(loader=FileSystemLoader(str(TEMPLATE_ROOT)), autoescape=False)
VAULT_AGENTS_TEMPLATE = Path(__file__).resolve().parents[1] / "VAULT_AGENTS_TEMPLATE.md"


def run_markdown_path(run: RunRecord) -> str:
    return run_note_path(run.slug, run.date, run.title, run.prompt, run.note_file)


def markdown_link(path: str, label: str) -> str:
    return f"[{label}]({path})"


def card_for_run_result(result: object, cards_by_slug: dict[str, SourceCard]) -> SourceCard | None:
    paper_card = getattr(result, "paper_card", None)
    if not paper_card:
        return None
    return cards_by_slug.get(Path(paper_card).stem)


def doi_url(doi: str | None) -> str | None:
    if not doi:
        return None
    return f"https://doi.org/{doi}"


def render_paper_markdown(card: SourceCard) -> str:
    template = ENVIRONMENT.get_template("paper.md.j2")
    body = template.render(card=card).strip()
    frontmatter = dump_frontmatter(card.frontmatter()).strip()
    return f"---\n{frontmatter}\n---\n\n{body}\n"


def render_run_markdown(run: RunRecord, cards_by_slug: dict[str, SourceCard]) -> str:
    template = ENVIRONMENT.get_template("run_index.md.j2")
    card_paths = {slug: f"../../papers/{slug}.md" for slug in cards_by_slug}
    prompt_alias = run.prompt[:90].strip()
    title = run_display_title(run.title, run.prompt)
    body = template.render(
        run=run,
        run_title=title,
        cards_by_slug=cards_by_slug,
        card_paths=card_paths,
        card_for_run_result=card_for_run_result,
        doi_url=doi_url,
    ).strip()
    frontmatter = dump_frontmatter(
        {
            "type": "scholar_labs_run",
            "run_id": run.slug,
            "title": title,
            "note_file": run.note_file,
            "date": run.date,
            "prompt": run.prompt,
            "result_count": run.result_count,
            "selected_count": len(
                [result for result in run.results if result.status == "selected"]
            ),
            "tags": ["scholar-vault/run"],
            "aliases": [f"{run.date} Scholar Labs: {title}", f"{run.date} {prompt_alias}"],
        }
    ).strip()
    return f"---\n{frontmatter}\n---\n\n{body}\n"


def render_project_markdown(project: dict[str, Any]) -> str:
    template = ENVIRONMENT.get_template("project.md.j2")
    body = template.render(project=project).strip()
    frontmatter = dump_frontmatter(project).strip()
    return f"---\n{frontmatter}\n---\n\n{body}\n"


def render_project_map_markdown(
    project: dict[str, Any],
    map_data: dict[str, Any],
) -> str:
    template = ENVIRONMENT.get_template("project_map.md.j2")
    body = template.render(project=project, map=map_data).strip()
    frontmatter = dump_frontmatter(
        {
            "type": "project_map",
            "project": map_data.get("project"),
            "project_slug": project.get("slug"),
            "project_updated": project.get("updated"),
            "generated": map_data.get("generated"),
        }
    ).strip()
    return f"---\n{frontmatter}\n---\n\n{body}\n"


def render_prompts_index(runs: list[RunRecord]) -> str:
    template = ENVIRONMENT.get_template("prompts.md.j2")
    return (
        template.render(
            runs=runs,
            run_display_title=run_display_title,
            run_markdown_path=run_markdown_path,
        ).rstrip()
        + "\n"
    )


def render_papers_index(cards: list[SourceCard]) -> str:
    template = ENVIRONMENT.get_template("papers.md.j2")
    return template.render(cards=cards).rstrip() + "\n"


def render_topics_index(topic_cards: dict[str, list[SourceCard]]) -> str:
    template = ENVIRONMENT.get_template("topics.md.j2")
    sorted_topics = sorted(topic_cards.items(), key=lambda item: item[0].casefold())
    return template.render(topic_cards=sorted_topics, topic_slug=topic_slug).rstrip() + "\n"


def render_topic_page(topic: str, cards: list[SourceCard]) -> str:
    lines = [f"# {topic}", "", "## Papers", ""]
    for card in cards:
        lines.append(f"- [{card.title}](../papers/{card.slug}.md)")
    lines.append("")
    return "\n".join(lines)


def render_missing_pdfs(runs: list[RunRecord]) -> str:
    missing = [
        (run, result) for run in runs for result in run.results if result.pdf_status != "attached"
    ]
    lines = [
        "# Candidate Results Without Cards",
        "",
        "These are Scholar Labs results that were not selected/imported into canonical paper "
        "cards. In the selected-only workflow this is expected: download PDFs only for sources "
        "you want to keep, then import those staged PDFs. Treat this page as optional discovery "
        "context, not a maintenance defect, unless you intentionally want to revisit a candidate.",
        "",
    ]
    if not missing:
        lines.append("No candidate results are currently outside the canonical paper set.")
        lines.append("")
        return "\n".join(lines)
    for run, result in missing:
        run_link = f"../{run_markdown_path(run)}"
        if result.paper_card:
            lines.append(
                f"- [{result.title}](<{run_link}>) "
                f"(`status={result.status}`, `paper_card={result.paper_card}`)"
            )
        else:
            lines.append(
                f"- [{result.title}](<{run_link}>) (`status={result.status}`, `paper_card=none`)"
            )
    lines.append("")
    return "\n".join(lines)


def render_unmatched_index(manifests: list[ImportManifest]) -> str:
    lines = [
        "# Historical Unmatched Staging PDFs",
        "",
        "These rows come from import manifests where a staged PDF was not accepted for that "
        "specific run. They are historical audit records and may repeat across runs. They are "
        "actionable only when the referenced file is still present in staging and is not already "
        "a duplicate of a vault PDF.",
        "",
    ]
    rows = [
        (manifest.run_id, entry)
        for manifest in manifests
        for entry in manifest.entries
        if entry.original_path and entry.decision != "accepted"
    ]
    if rows:
        for run_id, entry in rows:
            proposed = entry.proposed_match or "none"
            score = entry.score if entry.score is not None else "n/a"
            lines.append(
                f"- `{entry.original_path}` "
                f"(`run={run_id}`, `decision={entry.decision}`, `score={score}`, "
                f"`proposed={proposed}`)"
            )
    else:
        lines.append("No historical unmatched staged PDFs are recorded.")
    lines.append("")
    return "\n".join(lines)


def render_artifact_index(
    title: str,
    artifacts: list[dict[str, Any]],
    *,
    empty_message: str,
) -> str:
    lines = [f"# {title}", ""]
    if not artifacts:
        lines.extend([empty_message, ""])
        return "\n".join(lines)
    for artifact in artifacts:
        label = artifact.get("title") or artifact.get("path")
        path = artifact.get("path")
        type_value = artifact.get("type")
        created = artifact.get("created")
        detail = []
        if type_value:
            detail.append(f"type={type_value}")
        if created:
            detail.append(f"created={created}")
        suffix = f" ({', '.join(detail)})" if detail else ""
        lines.append(f"- [{label}](../{path}){suffix}")
        sources = artifact.get("sources") or []
        if sources:
            lines.append(f"  - Sources: {', '.join(str(source) for source in sources[:8])}")
    lines.append("")
    return "\n".join(lines)


def render_vault_readme() -> str:
    return (
        "# scholar-vault research vault\n\n"
        "This vault is a local-first source wiki. Paper card records live in `papers/`, "
        "canonical evidence PDFs live in `pdfs/`, Scholar Labs runs live in `runs/`, durable "
        "agent-written concepts/syntheses/tasks/queries/projects/proposals live in their "
        "named folders, and derived navigation lives in "
        "`bases/`, `_indexes/`, `_exports/`, `llms.txt`, and `llms-full.txt`.\n"
    )


def render_vault_agents() -> str:
    if not VAULT_AGENTS_TEMPLATE.exists():
        raise FileNotFoundError(f"Vault AGENTS template is missing: {VAULT_AGENTS_TEMPLATE}")
    return VAULT_AGENTS_TEMPLATE.read_text(encoding="utf-8").rstrip() + "\n"


def render_zotero_migration() -> str:
    return (
        "# Zotero migration\n\n"
        "When you want Zotero copies later, import `_exports/library.bib` into Zotero.\n\n"
        "- The exported BibLaTeX prefers cached provider BibTeX/CSL metadata, then falls back "
        "to card metadata.\n"
        "- The exported entries include DOI, URL, abstracts when known, keywords, PDF file "
        "paths, and note text.\n"
        "- Scholar Labs summaries and rationale bullets are folded into the BibLaTeX `note` "
        "field.\n"
        "- For one-card export while working in Obsidian, copy a card's `citekey` and run "
        "`scholar-vault card-biblatex <citekey>`.\n"
        "- For formatted APA-style bibliography text, use `scholar-vault reference <citekey>` "
        "or `scholar-vault references`.\n"
        "- `papers/` remains the canonical archive even after a Zotero import.\n"
    )


def render_llms_txt() -> str:
    return (
        "scholar-vault navigation\n"
        "- Canonical sources: papers/\n"
        "- Dashboard hub: _indexes/dashboard.md\n"
        "- Maintenance triage: scholar-vault maintenance-report --vault /path/to/vault\n"
        "- Concepts and method cards: concepts/ and _indexes/concepts.md\n"
        "- Synthesis notes: syntheses/ and _indexes/syntheses.md\n"
        "- Open questions and research gaps: tasks/ and _indexes/tasks.md\n"
        "- Query workbench notes: queries/ and _indexes/queries.md\n"
        "- Project workspaces: projects/ and _indexes/projects.md\n"
        "- Proposal workspaces: proposals/ and _indexes/proposals.md\n"
        "- Obsidian Bases workbenches: bases/\n"
        "- Scholar Labs provenance: runs/\n"
        "- Optional candidate discovery backlog: _indexes/missing-pdfs.md\n"
        "- Historical unmatched staging records: _indexes/unmatched.md\n"
        "- Paper reading queue: _indexes/reading-queue.md\n"
        "- Metadata/PDF issue dashboards: _indexes/metadata-issues.md and _indexes/pdf-issues.md\n"
        "- Search surface: _indexes/search-index.md\n"
        "- Semantic-neighbor navigation export: _exports/semantic-neighbors.json\n"
        "- Topics: topics/\n"
        "- Derived indexes: _indexes/\n"
        "- Exports: _exports/\n"
        "- Evidence rule: Scholar Labs summaries and generated indexes are navigation only; "
        "read PDFs before factual synthesis.\n"
    )


def render_llms_full(
    cards: list[SourceCard],
    runs: list[RunRecord],
    manifests: list[ImportManifest],
    artifacts: dict[str, list[dict[str, Any]]] | None = None,
) -> str:
    lines = ["scholar-vault overview", ""]
    lines.extend(
        [
            "Agent Navigation:",
            "- Start with llms.txt, _indexes/dashboard.md, and relevant projects, "
            "concepts, and syntheses.",
            "- Use `scholar-vault maintenance-report --vault /path/to/vault` for broad triage.",
            "- Use concepts/ for reusable methods, algorithms, visual encodings, datasets, "
            "evaluation protocols, and terminology.",
            "- Use syntheses/ for evidence-backed cross-paper answers and literature-review prose.",
            "- Use tasks/ for open questions, gaps, and next searches.",
            "- Use queries/ for active research questions with linked papers, runs, syntheses, "
            "and Obsidian Bases workbench embeds.",
            "- Use projects/ as lenses over shared papers, runs, concepts, syntheses, tasks, "
            "and optional proposals.",
            "- Do not treat Scholar Labs summaries, generated indexes, or semantic-neighbor "
            "links as evidence.",
            "- Read linked PDFs before writing factual synthesis.",
            "",
            "Generated Navigation:",
            "- _indexes/dashboard.md",
            "- _indexes/paper-status.md",
            "- _indexes/reading-queue.md",
            "- _indexes/metadata-issues.md",
            "- _indexes/pdf-issues.md",
            "- _indexes/synthesis-dashboard.md",
            "- _indexes/search-index.md",
            "- _indexes/queries.md",
            "- _indexes/projects.md",
            "- bases/",
            "- _exports/semantic-neighbors.json",
            "",
        ]
    )
    lines.append("Runs:")
    for run in runs:
        selected = len([result for result in run.results if result.status == "selected"])
        candidates = len([result for result in run.results if result.status != "selected"])
        lines.append(
            f"- {run.date} | {run_display_title(run.title, run.prompt)} | "
            f"{run_markdown_path(run)} | "
            f"selected={selected} candidate={candidates}"
        )
    lines.append("")
    lines.append("Papers:")
    for card in cards:
        summary = (
            card.summary
            if card.summary and card.summary != "No summary yet."
            else "No summary yet."
        )
        pdf = card.pdf or "missing"
        topics = ", ".join(card.topics) if card.topics else "none"
        lines.append(f"- {card.title} | papers/{card.slug}.md | topics: {topics} | pdf: {pdf}")
        lines.append(
            f"  enrichment: status={card.enrichment_status}"
            + (
                f" missing={', '.join(card.enrichment_missing)}"
                if card.enrichment_missing
                else ""
            )
        )
        lines.append(
            f"  abstract: status={card.abstract_status}"
            + (f" source={card.abstract_source}" if card.abstract_source else "")
        )
        lines.append(f"  summary: {summary}")
    lines.append("")
    lines.append("Candidate Results Without Canonical Cards:")
    for run in runs:
        for result in run.results:
            if result.status == "selected":
                continue
            lines.append(
                f"- {result.title} | {run_markdown_path(run)} | "
                f"status={result.status} | pdf_status={result.pdf_status}"
            )
    lines.append("")
    lines.append("Historical Unmatched Staging PDFs:")
    for manifest in manifests:
        for entry in manifest.entries:
            if entry.original_path and entry.decision != "accepted":
                lines.append(
                    f"- {entry.original_path} | run={manifest.run_id} | decision={entry.decision}"
                )
    lines.append("")
    if artifacts:
        for folder, title in [
            ("concepts", "Concepts"),
            ("syntheses", "Syntheses"),
            ("tasks", "Tasks"),
            ("queries", "Research Queries"),
            ("projects", "Projects"),
            ("proposals", "Proposals"),
        ]:
            rows = artifacts.get(folder) or []
            lines.append(f"{title}:")
            if rows:
                for artifact in rows:
                    lines.append(
                        f"- {artifact.get('title') or artifact.get('path')} | "
                        f"{artifact.get('path')}"
                    )
            else:
                lines.append("- none")
            lines.append("")
    return "\n".join(lines)


def group_cards_by_topic(cards: list[SourceCard]) -> dict[str, list[SourceCard]]:
    topic_cards: dict[str, list[SourceCard]] = defaultdict(list)
    for card in cards:
        for topic in card.topics:
            topic_cards[topic].append(card)
    return dict(topic_cards)
