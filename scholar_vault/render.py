from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from textwrap import dedent
from typing import Any

from jinja2 import Environment, FileSystemLoader

from .models import ImportManifest, RunRecord, SourceCard
from .sources import dump_frontmatter, run_display_title, run_note_path, topic_slug

TEMPLATE_ROOT = Path(__file__).resolve().parent.parent / "templates"
ENVIRONMENT = Environment(loader=FileSystemLoader(str(TEMPLATE_ROOT)), autoescape=False)


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
        "agent-written concepts/syntheses/proposals live in their named folders, and "
        "derived navigation lives in "
        "`_indexes/`, `_exports/`, `llms.txt`, and `llms-full.txt`.\n"
    )


def render_vault_agents() -> str:
    return (
        dedent(
            """
            # Scholar Vault Agent Notes

            ## Scope

            These instructions apply inside this research vault. They are for agents working on
            the vault as an LLM-readable research wiki, not for developing the
            `scholar-vault-tools` codebase.

            ## Core Model

            - Linked `pdfs/*.pdf` files are the canonical evidence artifacts.
            - `papers/*.md` cards are the durable metadata, provenance, index, and notes layer
              over those PDFs.
            - Scholar Labs `runs/` are discovery provenance. They explain why sources were
              found, but they are not evidence by themselves.
            - `topics/`, `_indexes/`, `_exports/`, `llms.txt`, and `llms-full.txt` are
              generated or derived views.
            - Durable agent-written work belongs in non-generated folders such as `concepts/`,
              `syntheses/`, `tasks/`, `proposals/`, and `sources/`.

            ## CLI Environment

            Before running any `scholar-vault ...` command, activate the Conda environment in
            the same shell:

            ```fish
            conda activate scholar-vault
            ```

            If activation is unavailable or `scholar-vault` is not on `PATH`, use:

            ```fish
            /Users/MadMax/miniforge3/condabin/conda run -n scholar-vault scholar-vault ...
            ```

            Prefer structured commands for orientation:

            ```fish
            scholar-vault status --json
            scholar-vault pdf-doctor --json
            scholar-vault notes-missing --heading "PDF reading notes"
            scholar-vault runs
            ```

            After editing only `concepts/`, run `scholar-vault concept-index`. After
            editing paper cards, topics, syntheses, tasks, or proposals, run:

            ```fish
            scholar-vault rebuild
            ```

            ## Evidence Rules

            - Read the linked PDF before writing factual claims, methods, findings, limitations,
              definitions, or source connections.
            - For serious reading, inspect the whole paper, including conclusions and
              limitations. Page ranges are only for targeted revisits.
            - Use available Codex PDF reading/rendering for figures, tables, diagrams, maps,
              visual encodings, equations, scanned pages, and appendices.
            - Do not rely on text extraction alone when visual evidence matters.
            - Do not treat Scholar Labs summaries, run rankings, topic pages, `_indexes/`, or
              `llms*.txt` as evidence.
            - Keep provider/manual abstracts separate from Scholar Labs summaries.

            ## Paper Card Edits

            Safe durable card edits:

            - Add PDF-grounded notes under `## Notes`.
            - Add or refine `topics` only when the PDF supports the retrieval label.
            - Use `scholar-vault set-keywords` for explicit PDF/provider keywords.
            - Use `scholar-vault set-abstract` only for the paper's actual abstract.
            - Use `scholar-vault resolve-citation` for safe metadata correction.

            Preserve:

            - `discovered_in`, Scholar Labs provenance, summaries, and `summary_sources`.
            - `raw/` inputs and provider caches.
            - Metadata locks, abstract locks, enrichment fingerprints, and retry state.
            - Generated section structure unless deliberately making a compatible card edit.

            For theses, reports, preprints, and other non-article PDFs with no DOI or
            journal/conference venue, do not invent metadata. Use the enrichment UI metadata
            resolver or:

            ```fish
            scholar-vault resolve-citation --citekey <citekey> \
              --authors "..." \
              --year <year> \
              --url <url> \
              --lock
            ```

            ## Candidate And Staging Semantics

            - Candidate results without paper cards are optional discovery context in the
              selected-only workflow. They are not maintenance defects.
            - `_indexes/missing-pdfs.md` is not an action queue unless explicitly revisiting
              Scholar Labs candidates.
            - Historical unmatched manifest entries are audit records. They matter only when
              non-duplicate PDFs still exist in staging.
            - Use `scholar-vault pdf-doctor --json` before treating PDF/staging issues as
              actionable.

            ## Research Workflow

            For actual vault improvement after import and enrichment:

            1. Use `$scholar-vault-research-loop` for a focused question, concept, method,
               dataset, proposal section, or paper cluster.
            2. Orient from `status --json`, `llms.txt`, relevant cards, runs, topics, and
               existing `concepts/`, `syntheses/`, `tasks/`, and `proposals/`.
            3. Build a reading set from selected paper cards with attached PDFs.
            4. Use `scholar-vault notes-missing --heading "PDF reading notes"` when you need
               the unread selected-card queue.
            5. Read PDFs as primary evidence.
            6. Update only touched paper cards with concise `## Notes`.
            7. Create `concepts/<slug>.md` for reusable concepts, methods, datasets, visual
               encodings, evaluation protocols, or terminology.
            8. Create `syntheses/<slug>.md` for evidence-backed cross-paper answers and
               literature-review prose.
            9. Create `tasks/<date>-research-gaps.md` for unclear evidence, follow-up
               reading, or next Scholar Labs prompts.
            10. Run `scholar-vault concept-index` after concept-only edits, or
                `scholar-vault rebuild` after broader paper/topic/synthesis/task/proposal edits.

            ## Proposal Workflow

            Proposal workspaces live under `proposals/`.

            Start or refresh a workspace with:

            ```fish
            scholar-vault proposal-sprint scaffold <slug>
            ```

            Set `evidence_matrix` in an outline's frontmatter when the proposal should
            audit a shared source matrix, for example:

            ```yaml
            evidence_matrix: syntheses/<matrix>.md
            ```

            Before treating proposal evidence as ready, run:

            ```fish
            scholar-vault proposal-audit proposals/<slug>
            ```

            The audit should pass or be consciously addressed. It checks for:

            - cited papers without `### PDF reading notes`;
            - read papers without `Proposal role: Core`, `Proposal role: Supporting`, or
              `Proposal role: Discarded`;
            - broken source-matrix links, including matrices referenced by `evidence_matrix`;
            - raw idea cards missing `Original User Notes - Verbatim`;
            - draft claims that still cite Scholar Labs summaries instead of PDF-grounded
              evidence.

            ## Skills

            Use these project skills when available:

            - `$scholar-vault-orient`: map current vault state before deeper work.
            - `$scholar-vault-read-pdf`: read linked PDFs and add PDF-grounded notes or
              connections.
            - `$scholar-vault-research-loop`: run a focused PDF-grounded vault improvement
              cycle.
            - `$scholar-vault-synthesize`: write cross-paper syntheses under `syntheses/`.
            - `$scholar-vault-refine-card`: safely improve touched paper cards.
            - `$scholar-vault-curate-topics`: clean topic labels and rebuild generated views.
            - `$scholar-vault-pdf-triage`: inspect active PDF/staging issues.
            - `$scholar-vault-gap-scout`: write follow-up tasks and research gaps.

            Skills do not need to launch subagents by themselves. Subagents may be useful for
            parallel read-only PDF passes or verification when available, but final synthesis
            and file edits should stay coordinated in the main thread.

            ## Reporting

            When reporting work, distinguish:

            - PDF-grounded findings;
            - card metadata/provenance;
            - Scholar Labs discovery context;
            - generated navigation;
            - open uncertainty and follow-up tasks.

            Do not claim a synthesis is evidence-grounded unless the relevant PDFs were read or
            the limitation is stated clearly.
            """
        ).strip()
        + "\n"
    )


def render_zotero_migration() -> str:
    return (
        "# Zotero migration\n\n"
        "When you want Zotero copies later, import `_exports/library.bib` into Zotero.\n\n"
        "- The exported BibTeX includes DOI, URL, abstracts when known, keywords, PDF file paths, "
        "and note text.\n"
        "- Scholar Labs summaries and rationale bullets are folded into the BibTeX `note` field.\n"
        "- `papers/` remains the canonical archive even after a Zotero import.\n"
    )


def render_llms_txt() -> str:
    return (
        "scholar-vault navigation\n"
        "- Canonical sources: papers/\n"
        "- Concepts and method cards: concepts/ and _indexes/concepts.md\n"
        "- Synthesis notes: syntheses/ and _indexes/syntheses.md\n"
        "- Proposal workspaces: proposals/ and _indexes/proposals.md\n"
        "- Scholar Labs provenance: runs/\n"
        "- Optional candidate discovery backlog: _indexes/missing-pdfs.md\n"
        "- Historical unmatched staging records: _indexes/unmatched.md\n"
        "- Topics: topics/\n"
        "- Derived indexes: _indexes/\n"
        "- Exports: _exports/\n"
    )


def render_llms_full(
    cards: list[SourceCard],
    runs: list[RunRecord],
    manifests: list[ImportManifest],
    artifacts: dict[str, list[dict[str, Any]]] | None = None,
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
