from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from .models import ImportManifest, RunRecord, SourceCard
from .sources import dump_frontmatter, run_display_title, run_note_path, topic_slug

TEMPLATE_ROOT = Path(__file__).resolve().parent.parent / "templates"
ENVIRONMENT = Environment(loader=FileSystemLoader(str(TEMPLATE_ROOT)), autoescape=False)


def run_markdown_path(run: RunRecord) -> str:
    return run_note_path(run.slug, run.date, run.title, run.prompt, run.note_file)


def markdown_link(path: str, label: str) -> str:
    return f"[{label}]({path})"


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
    lines = ["# Missing PDFs", ""]
    if not missing:
        lines.append("No candidate results are currently missing PDFs.")
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
    lines = ["# Unmatched PDFs", ""]
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
        lines.append("No PDFs currently need a match.")
    lines.append("")
    return "\n".join(lines)


def render_vault_readme() -> str:
    return (
        "# scholar-vault research vault\n\n"
        "This vault is a local-first source wiki. Canonical source records live in `papers/`, "
        "Scholar Labs runs live in `runs/`, PDFs live in `pdfs/`, and derived navigation lives in "
        "`_indexes/`, `_exports/`, `llms.txt`, and `llms-full.txt`.\n"
    )


def render_vault_agents() -> str:
    return (
        "# Vault maintenance notes\n\n"
        "- Treat `papers/*.md` as canonical source cards.\n"
        "- Keep raw inputs under `raw/` immutable where practical.\n"
        "- Update topic pages and indexes through `scholar-vault rebuild` after manual edits.\n"
        "- Preserve provenance in `discovered_in` and run pages instead of burying it in notes.\n"
        "- Preserve run-specific Scholar Labs summaries in `summary_sources` on paper cards.\n"
        "- Do not require Obsidian plugins, Zotero, or a database for normal operation.\n"
    )


def render_zotero_migration() -> str:
    return (
        "# Zotero migration\n\n"
        "When you want Zotero copies later, import `_exports/library.bib` into Zotero.\n\n"
        "- The exported BibTeX includes DOI, URL, keywords, PDF file paths when known, "
        "and note text.\n"
        "- Scholar Labs summaries and rationale bullets are folded into the BibTeX `note` field.\n"
        "- `papers/` remains the canonical archive even after a Zotero import.\n"
    )


def render_llms_txt() -> str:
    return (
        "scholar-vault navigation\n"
        "- Canonical sources: papers/\n"
        "- Scholar Labs provenance: runs/\n"
        "- Candidate results missing PDFs: _indexes/missing-pdfs.md\n"
        "- Unmatched PDFs: _indexes/unmatched.md\n"
        "- Topics: topics/\n"
        "- Derived indexes: _indexes/\n"
        "- Exports: _exports/\n"
    )


def render_llms_full(
    cards: list[SourceCard],
    runs: list[RunRecord],
    manifests: list[ImportManifest],
) -> str:
    lines = ["scholar-vault overview", ""]
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
        lines.append(f"  summary: {summary}")
    lines.append("")
    lines.append("Candidate Results:")
    for run in runs:
        for result in run.results:
            if result.status == "selected":
                continue
            lines.append(
                f"- {result.title} | {run_markdown_path(run)} | "
                f"status={result.status} | pdf_status={result.pdf_status}"
            )
    lines.append("")
    lines.append("Unmatched PDFs:")
    for manifest in manifests:
        for entry in manifest.entries:
            if entry.original_path and entry.decision != "accepted":
                lines.append(
                    f"- {entry.original_path} | run={manifest.run_id} | decision={entry.decision}"
                )
    lines.append("")
    return "\n".join(lines)


def group_cards_by_topic(cards: list[SourceCard]) -> dict[str, list[SourceCard]]:
    topic_cards: dict[str, list[SourceCard]] = defaultdict(list)
    for card in cards:
        for topic in card.topics:
            topic_cards[topic].append(card)
    return dict(topic_cards)
