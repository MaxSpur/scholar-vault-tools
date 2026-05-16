---
name: scholar-vault-compile-paper
description: Compile one Scholar Vault paper into a reusable PDF-grounded digest under paper-digests/. Use when Codex is asked to turn a selected paper and its linked PDF into a durable digest for future syntheses, concept pages, query dossiers, project work, or proposal audits.
---

# Scholar Vault Compile Paper

Use this skill when the goal is to finish one paper's reusable digest. The CLI
can scaffold and track the workflow, but it does not read the PDF or generate
scientific interpretation by itself.

## CLI Environment

Before any `scholar-vault ...` command, activate the project Conda environment
in the same shell:

```fish
conda activate scholar-vault
scholar-vault compile status --json
```

If activation is unavailable or `scholar-vault` is still not on `PATH`, use the
explicit fallback:

```fish
/Users/MadMax/miniforge3/condabin/conda run -n scholar-vault scholar-vault compile status --json
```

Do not retry plain `scholar-vault` commands without one of these environment
paths.

## Workflow

1. Read `AGENTS.md`, then run `scholar-vault compile status --json` or
   `scholar-vault compile queue --project <slug> --json` to find the target.
2. Scaffold the digest if it does not exist:

```fish
scholar-vault compile scaffold --citekey <citekey>
```

For a selected Scholar Labs run:

```fish
scholar-vault compile scaffold --run <run-id> --selected-only
```

3. Open the target `papers/*.md` card and resolve its `pdf` path relative to
   the vault root.
4. Read the actual linked PDF. Extract full text for orientation, then inspect
   rendered pages for important figures, tables, diagrams, maps, equations, or
   scanned material. Do not rely on Scholar Labs summaries as evidence.
5. Fill `paper-digests/<citekey>.md` using the scaffolded sections. Keep claims
   concise and reusable, and cite page, figure, and table locations where
   possible.
6. Update digest frontmatter:
   - `evidence_level: pdf_grounded` when the digest is based on the PDF.
   - `source_pages_checked`, `figures_checked`, and `tables_checked` with the
     inspected evidence locations.
   - `linked_queries`, `linked_projects`, `linked_concepts`, and
     `linked_syntheses` when the digest should feed those workspaces.
7. If useful, add a short `### PDF reading notes - <YYYY-MM-DD>` entry under
   the paper card's `## Notes`, but keep the full reusable digest in
   `paper-digests/`.
8. Mark state explicitly:

```fish
scholar-vault compile mark <citekey> --status compiled
scholar-vault compile mark <citekey> --status reviewed
```

`compile mark` rejects `compiled` and `reviewed` unless the digest is ready:
`evidence_level` is not `metadata_only`, `source_pages_checked` is filled, the
paper has a resolving PDF link, and scaffold/template placeholders are gone.
Use `--force` only when the user explicitly wants the override, then log the
reason with `scholar-vault operations log`.

Use `--status stale` when a paper, query, project, or related interpretation
changes and the digest needs a fresh pass.
9. Run:

```fish
scholar-vault compile doctor --json
scholar-vault rebuild
```

Resolve doctor issues before treating the digest as ready for synthesis or
proposal evidence.

## Digest Content Rules

- The digest is a single-paper reusable knowledge artifact, not a cross-paper
  synthesis.
- Write PDF-grounded content for contribution, problem, method, data,
  evaluation, findings, limitations, definitions, claims to track, figures,
  tables, and open questions.
- Keep "reader-inferred limitations" clearly separate from
  "author-stated limitations".
- Link to paper cards, concepts, syntheses, queries, projects, and proposal
  evidence surfaces when those links will help future agents.
- If a claim matters, include enough page, figure, table, section, or appendix
  detail for another reader to verify it.

## Boundaries

- Do not write claims from Scholar Labs summaries unless the PDF confirms them.
- Do not call a digest `compiled` or `reviewed` if it is still
  `metadata_only`, has no checked source pages, lacks a resolving PDF link, or
  still contains scaffold placeholders.
- Do not use `compile mark --force` unless the user explicitly asks for that
  exception and the reason is recorded.
- Do not overwrite user-authored digest prose with a new scaffold unless the
  user explicitly asks for `--force`.
- Do not hand-edit generated folders. Use `compile mark`, `compile doctor`,
  `bases rebuild`, or `rebuild` to refresh generated views.
