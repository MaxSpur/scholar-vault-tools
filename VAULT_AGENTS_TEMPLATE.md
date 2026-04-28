# Scholar Vault Agent Notes

## Scope

These instructions apply inside this research vault. They are for agents working on the vault as an LLM-readable research wiki, not for developing the `scholar-vault-tools` codebase.

## Core Model

- Linked `pdfs/*.pdf` files are the canonical evidence artifacts.
- `papers/*.md` cards are the durable metadata, provenance, index, and notes layer over those PDFs.
- Scholar Labs `runs/` are discovery provenance. They explain why sources were found, but they are not evidence by themselves.
- `topics/`, `_indexes/`, `_exports/`, `llms.txt`, and `llms-full.txt` are generated or derived views.
- Durable agent-written work belongs in non-generated folders such as `concepts/`, `syntheses/`, `tasks/`, `proposals/`, and `sources/`.

## CLI Environment

Before running any `scholar-vault ...` command, activate the Conda environment in the same shell:

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

- Read the linked PDF before writing factual claims, methods, findings, limitations, definitions, or source connections.
- For serious reading, inspect the whole paper, including conclusions and limitations. Page ranges are only for targeted revisits.
- Use available Codex PDF reading/rendering for figures, tables, diagrams, maps, visual encodings, equations, scanned pages, and appendices.
- Do not rely on text extraction alone when visual evidence matters.
- Do not treat Scholar Labs summaries, run rankings, topic pages, `_indexes/`, or `llms*.txt` as evidence.
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

For theses, reports, preprints, and other non-article PDFs with no DOI or journal/conference venue, do not invent metadata. Use the enrichment UI metadata resolver or:

```fish
scholar-vault resolve-citation --citekey <citekey> \
  --authors "..." \
  --year <year> \
  --url <url> \
  --lock
```

## Candidate And Staging Semantics

- Candidate results without paper cards are optional discovery context in the selected-only workflow. They are not maintenance defects.
- `_indexes/missing-pdfs.md` is not an action queue unless explicitly revisiting Scholar Labs candidates.
- Historical unmatched manifest entries are audit records. They matter only when non-duplicate PDFs still exist in staging.
- Use `scholar-vault pdf-doctor --json` before treating PDF/staging issues as actionable.

## Research Workflow

For actual vault improvement after import and enrichment:

1. Use `$scholar-vault-research-loop` for a focused question, concept, method, dataset, proposal section, or paper cluster.
2. Orient from `status --json`, `llms.txt`, relevant cards, runs, topics, and existing `concepts/`, `syntheses/`, `tasks/`, and `proposals/`.
3. Build a reading set from selected paper cards with attached PDFs.
4. Use `scholar-vault notes-missing --heading "PDF reading notes"` when you need the unread selected-card queue.
5. Read PDFs as primary evidence.
6. Update only touched paper cards with concise `## Notes`.
7. Create `concepts/<slug>.md` for reusable concepts, methods, datasets, visual encodings, evaluation protocols, or terminology.
8. Create `syntheses/<slug>.md` for evidence-backed cross-paper answers and literature-review prose.
9. Create `tasks/<date>-research-gaps.md` for unclear evidence, follow-up reading, or next Scholar Labs prompts.
10. Run `scholar-vault concept-index` after concept-only edits, or `scholar-vault rebuild` after broader paper/topic/synthesis/task/proposal edits.

## Proposal Workflow

Proposal workspaces live under `proposals/`.

Start or refresh a workspace with:

```fish
scholar-vault proposal-sprint scaffold <slug>
```

Before treating proposal evidence as ready, run:

```fish
scholar-vault proposal-audit proposals/<slug>
```

The audit should pass or be consciously addressed. It checks for:

- cited papers without `### PDF reading notes`;
- read papers without `Proposal role: Core`, `Proposal role: Supporting`, or `Proposal role: Discarded`;
- broken source-matrix links;
- raw idea cards missing `Original User Notes - Verbatim`;
- draft claims that still cite Scholar Labs summaries instead of PDF-grounded evidence.

## Skills

Use these project skills when available:

- `$scholar-vault-orient`: map current vault state before deeper work.
- `$scholar-vault-read-pdf`: read linked PDFs and add PDF-grounded notes or connections.
- `$scholar-vault-research-loop`: run a focused PDF-grounded vault improvement cycle.
- `$scholar-vault-synthesize`: write cross-paper syntheses under `syntheses/`.
- `$scholar-vault-refine-card`: safely improve touched paper cards.
- `$scholar-vault-curate-topics`: clean topic labels and rebuild generated views.
- `$scholar-vault-pdf-triage`: inspect active PDF/staging issues.
- `$scholar-vault-gap-scout`: write follow-up tasks and research gaps.

Skills do not need to launch subagents by themselves. Subagents may be useful for parallel read-only PDF passes or verification when available, but final synthesis and file edits should stay coordinated in the main thread.

## Reporting

When reporting work, distinguish:

- PDF-grounded findings;
- card metadata/provenance;
- Scholar Labs discovery context;
- generated navigation;
- open uncertainty and follow-up tasks.

Do not claim a synthesis is evidence-grounded unless the relevant PDFs were read or the limitation is stated clearly.
