---
name: scholar-vault-labs-prompts
description: Create, inspect, and link human-in-the-loop Scholar Labs prompt packs in a Scholar Vault. Use when Codex is asked to draft next Google Scholar Labs prompts for a query, project, synthesis gap, proposal evidence gap, contradiction check, related-paper search, benchmark/dataset search, or failure-mode search.
---

# Scholar Vault Labs Prompts

Use this skill to help a user benefit from Google Scholar Labs without scraping
Scholar and without treating Labs answers as evidence.

Prompt packs are durable Markdown artifacts under
`queries/<slug>/prompt-packs/` or `tasks/scholar-labs-prompts/`. They preserve
the query/project/gap context, structured prompt text, selection guidance, and
run links. A prompt pack is discovery planning only; canonical paper cards still
come from accepted PDFs, DOI imports, BibTeX imports, or explicit manual import.

## CLI Environment

Before any `scholar-vault ...` command, activate the project Conda environment
in the same shell:

```fish
conda activate scholar-vault
scholar-vault labs-prompts list
```

If activation is unavailable or `scholar-vault` is still not on `PATH`, use the
explicit fallback:

```fish
/Users/MadMax/miniforge3/condabin/conda run -n scholar-vault scholar-vault labs-prompts list
```

Do not retry plain `scholar-vault` commands without one of these environment
paths.

## Workflow

1. Read `AGENTS.md`, then orient from `llms.txt`, `_indexes/dashboard.md`,
   `_indexes/queries.md`, `_indexes/scholar-labs-prompts.md`, and the relevant
   query, project, synthesis, task, or proposal files.
2. Prefer existing query/project state over inventing a new prompt context.
   Use `scholar-vault query create ...` or `scholar-vault project scaffold ...`
   only when the user wants that durable workspace.
3. Generate exactly one prompt-pack scope:
   - `scholar-vault labs-prompts generate --query <query-slug>`
   - `scholar-vault labs-prompts generate --project <project-slug>`
   - `scholar-vault labs-prompts generate --from-gaps`
4. When the user wants graph-assisted seed curation first, use
   `scholar-vault discover query --query <query-slug>` or
   `scholar-vault discover seed --citekey <citekey>`, select/reject candidates,
   then run `scholar-vault discover to-labs-prompts --query <query-slug>`.
5. Inspect the pack with `scholar-vault labs-prompts show <prompt-pack-id>` and
   report the strongest prompts and selection guidance to the user.
6. If the user ran a prompt in Labs but has not imported yet, mark it used:
   `scholar-vault labs-prompts mark-used <prompt-pack-id> --notes "..."`
7. When a Scholar Labs export from that pack is imported, link provenance with:
   `scholar-vault import-labs --prompt-pack <prompt-pack-id> --query <query-slug>`
   or after the fact with `scholar-vault labs-prompts link-run <prompt-pack-id> <run-id>`.
8. Run `scholar-vault labs-prompts doctor --json` after prompt-pack edits or
   run-linking work.

## Optional Seed APIs

Default prompt generation is local and does not call external APIs. Optional
seed APIs can improve prompt wording:

```fish
scholar-vault labs-prompts generate --query <query-slug> --seed-api openalex
scholar-vault labs-prompts generate --query <query-slug> --seed-api semantic-scholar
```

Use seed candidates only as suggested titles, citation neighborhoods, and query
terms for Labs prompt construction. Do not create `papers/*.md` cards from seed
API output unless the same source later enters through a normal import path.

Durable graph-assisted discovery uses:

```fish
scholar-vault discover query --query <query-slug> --source openalex,semantic-scholar
scholar-vault discover seed --citekey <citekey> --source openalex,semantic-scholar
scholar-vault discover list
scholar-vault discover select <candidate-id>
scholar-vault discover reject <candidate-id>
scholar-vault discover to-labs-prompts --query <query-slug>
scholar-vault discover doctor --json
```

Those candidates live under `tasks/discovery-candidates/` and raw provider
responses under `raw/discovery/`. They are planning artifacts only.

## Prompt Pack Semantics

- `draft`: generated but not ready or not yet reviewed by the user.
- `ready`: acceptable for the user to run in Scholar Labs.
- `used`: user ran at least one prompt in Scholar Labs, but no run is linked.
- `imported`: a Scholar Labs run is linked back to the pack.
- `retired`: no longer active for discovery.

Good prompt packs ask Labs for specific paper relationships, named methods,
datasets, benchmarks, contradictions, negative evidence, proposal gaps,
failure modes, and follow-up questions. They include inclusion/exclusion
criteria and tell the user which Labs results to select/import.

## Boundaries

- Do not call Google Scholar directly.
- Do not scrape Google Scholar or Scholar Labs.
- Do not treat Labs summaries as PDF-grounded evidence.
- Do not create canonical paper cards from API seed candidates.
- Do not overwrite query/project/synthesis prose when a generated prompt pack
  is enough.
