from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from .models import RunRecord, SourceCard
from .sources import dump_frontmatter, topic_slug

TEMPLATE_ROOT = Path(__file__).resolve().parent.parent / "templates"
ENVIRONMENT = Environment(loader=FileSystemLoader(str(TEMPLATE_ROOT)), autoescape=False)


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
    return (
        template.render(run=run, cards_by_slug=cards_by_slug, card_paths=card_paths).rstrip() + "\n"
    )


def render_prompts_index(runs: list[RunRecord]) -> str:
    template = ENVIRONMENT.get_template("prompts.md.j2")
    return template.render(runs=runs).rstrip() + "\n"


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


def render_missing_pdfs(cards: list[SourceCard]) -> str:
    missing = [card for card in cards if card.pdf_status != "attached" or not card.pdf]
    lines = ["# Missing PDFs", ""]
    if not missing:
        lines.append("No papers are currently missing PDFs.")
        lines.append("")
        return "\n".join(lines)
    for card in missing:
        lines.append(f"- [{card.title}](../papers/{card.slug}.md)")
    lines.append("")
    return "\n".join(lines)


def render_unmatched_index(cards: list[SourceCard], raw_unmatched: list[str]) -> str:
    needs_review = [
        card
        for card in cards
        if card.citation_status == "partial" or card.pdf_status != "attached" or not card.title
    ]
    lines = ["# Unmatched And Incomplete", ""]
    lines.append("## Source cards needing review")
    lines.append("")
    if needs_review:
        for card in needs_review:
            lines.append(
                f"- [{card.title or card.slug}](../papers/{card.slug}.md) "
                f"(`citation_status={card.citation_status}`, `pdf_status={card.pdf_status}`)"
            )
    else:
        lines.append("No source cards currently need review.")
    lines.append("")
    lines.append("## Raw unmatched files")
    lines.append("")
    if raw_unmatched:
        for item in raw_unmatched:
            lines.append(f"- `{item}`")
    else:
        lines.append("No unmatched raw files.")
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
        "- Topics: topics/\n"
        "- Derived indexes: _indexes/\n"
        "- Exports: _exports/\n"
    )


def render_llms_full(cards: list[SourceCard], runs: list[RunRecord]) -> str:
    lines = ["scholar-vault overview", ""]
    lines.append("Runs:")
    for run in runs:
        lines.append(f"- {run.date} | {run.prompt} | runs/{run.slug}/index.md")
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
    return "\n".join(lines)


def group_cards_by_topic(cards: list[SourceCard]) -> dict[str, list[SourceCard]]:
    topic_cards: dict[str, list[SourceCard]] = defaultdict(list)
    for card in cards:
        for topic in card.topics:
            topic_cards[topic].append(card)
    return dict(topic_cards)
