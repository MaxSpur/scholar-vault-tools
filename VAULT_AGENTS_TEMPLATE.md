# Scholar Vault Agent Notes

## Scope

These instructions apply inside this research vault. They are for agents working on the vault as an LLM-readable research wiki, not for developing the `scholar-vault-tools` codebase.

## Core Model

- Linked `pdfs/*.pdf` files are the canonical evidence artifacts.
- `papers/*.md` cards are the durable metadata, provenance, index, and notes layer over those PDFs.
- `paper-digests/*.md` files are durable user/agent-authored single-paper
  digests compiled from linked PDFs for reuse in syntheses, concepts, queries,
  projects, and proposals.
- Scholar Labs `runs/` are discovery provenance. They explain why sources were found, but they are not evidence by themselves.
- Scholar Labs prompt packs under `queries/<slug>/prompt-packs/` or
  `tasks/scholar-labs-prompts/` are human-in-the-loop discovery-planning
  artifacts. They help a user run better Google Scholar Labs prompts, but they
  are not evidence and do not create canonical paper cards by themselves.
- Graph-assisted discovery candidates under `tasks/discovery-candidates/` are
  OpenAlex/Semantic Scholar metadata suggestions and Scholar Labs prompt seeds.
  They are not evidence and do not create canonical paper cards by themselves.
- Typed self-improvement state under `tasks/queue/`, `_operations/`, and
  `_feedback/` tracks work, runs, and ratings. It is process context, not
  scientific evidence or a replacement for paper cards, PDFs, concepts, or
  syntheses.
- Autopilot sessions under `_sessions/`, handoffs under `_handoffs/`, and
  session reports under `queries/<slug>/session-report.md` or `_reports/` track
  the user-facing `ask -> intake -> answer` workflow. They are coordination
  state, not evidence.
- Canonical files are `papers/`, `paper-digests/`, `pdfs/`, run
  YAML/manifests under `runs/`, `raw/` inputs, `concepts/`, `syntheses/`,
  `tasks/`, `queries/`, `projects/`, and `proposals/`.
- Derived files are `_indexes/`, `topics/`, `llms.txt`, `llms-full.txt`, and
  `_exports/`. Generated `bases/*.base`, rendered run Markdown under `runs/`, and
  `projects/*/project-map.md` are generated views as well.
- Generated files should not be hand-edited unless the user or a tool-specific
  workflow explicitly allows it. Regenerate them with the appropriate
  `scholar-vault` command instead.
- Durable agent-written work belongs in non-generated folders such as `concepts/`, `syntheses/`, `tasks/`, `queries/`, `projects/`, and `proposals/`.
- Query notes are question-centered workbenches over shared papers, runs, syntheses, and prompt packs. They are not daily notes and do not replace canonical paper cards.
- Paper cards may expose both `linked_queries` and `linked_query_paths`.
  `linked_query_paths` are plain relative paths used by Obsidian Bases path
  filters such as `this.file.path`; do not convert them to wikilinks.
- Projects are lenses over shared papers, runs, concepts, syntheses, tasks, and optional proposals. They link to paper cards instead of duplicating source content.
- Do not create new top-level folders unless the user explicitly instructs you to.
- Proposal workspaces are one workflow, not the primary vault workflow.

## CLI Environment

Before running any `scholar-vault ...` command, activate the Conda environment in the same shell:

```fish
conda activate scholar-vault
```

If activation is unavailable or `scholar-vault` is not on `PATH`, use:

```fish
/Users/MadMax/miniforge3/condabin/conda run -n scholar-vault scholar-vault ...
```

## Skill And AGENTS Synchronization

If you edit or create `.agents/skills/` entries or the vault-local `AGENTS.md`
inside this vault, tell the user to adopt those changes back into the
`scholar-vault-tools` repository before publishing the repository-owned
Scholar Vault skills or the repository vault guide over this vault again. From
the tools repository:

```fish
scholar-vault skills diff --vault /path/to/this/vault
scholar-vault skills ui --vault /path/to/this/vault
scholar-vault skills adopt <skill-name> --vault /path/to/this/vault --apply
scholar-vault skills adopt AGENTS.md --vault /path/to/this/vault --apply --force
scholar-vault skills publish --vault /path/to/this/vault --apply
scholar-vault skills install-external obsidian-skills --vault /path/to/this/vault --apply
```

`skills publish` updates repository-owned Scholar Vault skills and vault
`AGENTS.md` from the repository source (`vault-agent-skills/` and
`VAULT_AGENTS_TEMPLATE.md`). `skills adopt AGENTS.md` copies the vault-local
guide back into `VAULT_AGENTS_TEMPLATE.md`; use it only when vault-side guide
edits are intentional.

External skill sources are upstream content, not repository-owned Scholar Vault
skills. Kepano's Obsidian skills are the built-in source
`obsidian-skills` from `https://github.com/kepano/obsidian-skills`. Do not
adopt or paste them into `vault-agent-skills/`. Install or update them with
`scholar-vault skills install-external obsidian-skills --vault /path/to/this/vault
--apply` or `scholar-vault skills update-external obsidian-skills --vault
/path/to/this/vault --apply`. The convenience aliases
`skills install-obsidian` and `skills update-obsidian` do the same thing.

For another external source, use:

```fish
scholar-vault skills install-external <source-name> \
  --repository https://example.com/skills.git \
  --skills-subdir skills \
  --vault /path/to/this/vault \
  --apply
```

External install/update commands clone the upstream repository and mark the
installed vault skills as externally managed so normal `skills diff` /
`publish` does not ask to adopt or archive them.

Do not recommend raw `rsync --delete` for skill or AGENTS synchronization when
either side may contain local changes. `skills publish --archive-extra` archives
vault-only skills into `.sync-backups/` instead of deleting them.

Prefer structured commands for orientation:

```fish
scholar-vault session current --json
scholar-vault session list --json
scholar-vault status --json
scholar-vault migrate --dry-run --json
scholar-vault pdf-doctor --json
scholar-vault git-summary
scholar-vault notes-missing --heading "PDF reading notes"
scholar-vault maintenance-report
scholar-vault maintenance-report --write-queue
scholar-vault lint-wiki --json
scholar-vault lint-wiki --write-queue --write-report
scholar-vault eval list
scholar-vault eval run
scholar-vault eval report
scholar-vault compile status --json
scholar-vault query list --json
scholar-vault query doctor --json
scholar-vault labs-prompts list
scholar-vault labs-prompts doctor --json
scholar-vault discover list
scholar-vault discover doctor --json
scholar-vault obsidian doctor --json
scholar-vault queue list --json
scholar-vault operations list --json
scholar-vault feedback report --json
scholar-vault schema export --json
scholar-vault project list
scholar-vault runs
```

For ordinary user-facing work, prefer the autopilot flow over manual command
chains:

```fish
scholar-vault ask "question"
scholar-vault intake
scholar-vault improve --no-agent
scholar-vault answer "focused synthesis question"
```

For brand-new projects, use `scholar-vault start <project-slug> --title "..."`
only to scaffold a clean project workspace. Keep imports explicit with
`intake`, `ask`, or PDF-only intake after that.

If the user already ran Google Scholar Labs and has a JSON export, `ask` is not
required for provenance. The JSON contains the exact prompt. Prefer
`scholar-vault intake --export <json> --staging <staging-folder> --project <slug>
--slug <query-slug> --question "short query question" --new-session` to create
the session/query from that export, record a used-prompt pack, and link the run
to the project context. For PDFs without a Labs JSON, prefer
`scholar-vault intake --pdf-only --staging <staging-folder> --project <slug>
--slug <query-slug> --question "short query question" --new-session`.
Shared staging folders can contain PDFs and JSON exports from multiple prompts;
explicit `--export` selects the Labs run, and unrelated leftover PDFs are not
blockers unless the importer reports an ambiguous/manual match decision.
For project-wide synthesis across multiple imports, prefer
`scholar-vault answer --project <slug> --budget-papers <N> "question"` so the
handoff covers all linked project papers and runs.

Use the lower-level commands only when repairing blockers, inspecting a
specific subsystem, or following a handoff.

Use `scholar-vault obsidian setup --dry-run` to inspect safe Obsidian graph/app
settings before changing `.obsidian/`. Use `--apply` only after reviewing the
diff. The setup command backs up existing settings, hides generated scaffolding
from the graph by default, and does not install plugins.

For older vaults or after updating `scholar-vault-tools`, run
`scholar-vault migrate --dry-run --json` before hand-creating missing folders or
generated files. Apply with `scholar-vault migrate --apply` only after reviewing
the proposed changes. Migration preserves existing `AGENTS.md` unless
`--update-agents` is explicit, backfills only absent operational paper-card
frontmatter, logs an operation, and runs the standard doctors.

For one-card BibLaTeX while working from Obsidian, copy the card `citekey` and run:

```fish
scholar-vault card-biblatex <citekey>
```

For APA-style Markdown/RTF/plain references, use the formatter instead of hand-formatting:

```fish
scholar-vault reference <citekey>
scholar-vault references
```

After editing only `concepts/`, run `scholar-vault concept-index`. After
editing query notes or Base views, run `scholar-vault bases rebuild`. Use
`scholar-vault query rename`, `scholar-vault query archive`, and
`scholar-vault query doctor --fix` for query lifecycle/path repairs instead of
moving query files or editing query-linked metadata by hand. After editing paper
cards, topics, syntheses, tasks, or proposal evidence surfaces,
run:

```fish
scholar-vault rebuild
```

After editing project links or frontmatter, prefer the focused project commands
below; do not use a full rebuild unless broader vault content changed.

Before committing after a rebuild, run `scholar-vault git-summary`. Large
generated diffs under `_indexes/`, `topics/`, `bases/`, `llms*.txt`, `_exports/`,
rendered run Markdown, and project maps are expected. Review canonical changes in
`papers/`, `paper-digests/`, `pdfs/`, run YAML/manifests, `raw/`, concepts, syntheses, tasks,
queries, projects, and proposals before committing. To check determinism, run rebuild a
second time; it should not introduce additional generated churn.

### Obsidian Skills

When available, use the Obsidian skills explicitly:

- Use `$obsidian-markdown` before substantial edits to paper cards, query notes, project pages, concept cards, syntheses, tasks, proposals, or AGENTS.md so YAML properties, wikilinks, callouts, embeds, and Obsidian Markdown stay valid.
- Use `$json-canvas` only when creating or editing `.canvas` files such as visual project maps.
- Use `$obsidian-bases` only when the user explicitly asks for `.base` views.
- Use `$obsidian-cli` only when Obsidian is open and CLI support is enabled.
- Use `$defuddle` only when the task is to extract clean Markdown from a web page before bringing that text into vault work.

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
- Do not paste full Scholar Labs prompt text into paper cards; link the run note instead.
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

## Paper Digest Status

Before marking a digest `compiled` or `reviewed`, confirm it is no longer a
metadata-only scaffold:

- `evidence_level` is not `metadata_only`;
- `source_pages_checked` is filled with the PDF pages or sections inspected;
- the paper has a linked PDF path that resolves inside the vault;
- scaffold/template placeholders have been removed from the digest body.

`scholar-vault compile mark <citekey> --status compiled|reviewed` enforces
these checks and `scholar-vault lint-wiki --json` reports matching findings.
Use `--force` only when the user explicitly wants to override the guard, and
log the reason with `scholar-vault operations log`.

## Candidate And Staging Semantics

- Candidate results without paper cards are optional discovery context in the selected-only workflow. They are not maintenance defects.
- Discovery candidates under `tasks/discovery-candidates/` are optional
  non-canonical graph/search metadata. Use `scholar-vault discover select` or
  `reject` to curate them, and `scholar-vault discover to-labs-prompts --query
  <query-slug>` to turn active query candidates into a prompt pack.
- `_indexes/missing-pdfs.md` is not an action queue unless explicitly revisiting Scholar Labs candidates.
- `_indexes/scholar-labs-prompts.md` tracks active prompt packs and import
  status. It is a planning/dashboard surface, not a source of evidence.
- Historical unmatched manifest entries are audit records. They matter only when non-duplicate PDFs still exist in staging.
- Use `scholar-vault pdf-doctor --json` before treating PDF/staging issues as actionable.
- For one-off leftover PDFs, use `scholar-vault match-staging --ui`: enter the likely title, choose the PDF path, inspect candidate run summaries, then click `Import PDF` for the matching run result instead of rerunning the whole run.

## Scholar Labs Prompt Workbench

Use prompt packs for systematic Scholar Labs follow-up instead of hand-writing
long prompt drafts into task notes. Prompt packs should be specific to a query,
project, or known evidence gap and should remain discovery context until the
user downloads PDFs and imports selected sources.

Useful commands:

```fish
scholar-vault labs-prompts generate --query <query-slug>
scholar-vault labs-prompts generate --project <project-slug>
scholar-vault labs-prompts generate --from-gaps
scholar-vault labs-prompts list
scholar-vault labs-prompts show <prompt-pack-id>
scholar-vault labs-prompts mark-used <prompt-pack-id> --notes "..."
scholar-vault labs-prompts link-run <prompt-pack-id> <run-id>
scholar-vault labs-prompts doctor --json
scholar-vault discover query --query <query-slug> --source openalex,semantic-scholar
scholar-vault discover seed --citekey <citekey> --source openalex,semantic-scholar
scholar-vault discover to-labs-prompts --query <query-slug>
```

Default prompt generation is local and offline. Optional `--seed-api openalex`
or `--seed-api semantic-scholar` may suggest seed titles and terms for prompt
wording only. Do not treat those API candidates as canonical papers unless they
later enter the vault through the PDF, DOI, BibTeX, or manual import path.
For durable seed curation, prefer `scholar-vault discover ...`; it caches raw
provider responses under `raw/discovery/`, stores candidate status under
`tasks/discovery-candidates/`, and feeds selected candidates into prompt packs.

When importing a Google Scholar Labs export that came from a prompt pack, keep
the provenance linked:

```fish
scholar-vault import-labs --commit --prompt-pack <prompt-pack-id> --query <query-slug>
```

This records the prompt pack and query on the run, marks the prompt pack
`imported`, and links the run back to the query note. It does not change the
selected-only import rule: paper cards are still canonical only after an
accepted PDF, DOI, BibTeX, or manual import path.

## Self-Improvement Queue And Feedback

Use typed self-improvement records when the durable artifact is work tracking,
workflow memory, feedback, or a tool-improvement request rather than a research
claim. These records are useful for future agents, but they do not make a
paper, synthesis, concept, or proposal evidence-grounded.

Useful commands:

```fish
scholar-vault maintenance-report --write-queue
scholar-vault queue list --json
scholar-vault queue add --kind <kind> --title "..." --required-evidence <pdf|metadata|web|none>
scholar-vault queue show <queue-id> --json
scholar-vault queue plan <queue-id>
scholar-vault queue close <queue-id> --status done --notes "..."
scholar-vault queue doctor --json
scholar-vault operations log --kind <kind> --message "..." --check "..."
scholar-vault operations list --json
scholar-vault operations doctor --json
scholar-vault feedback rate <target> --target-type <target-type> --verdict <verdict> --notes "..."
scholar-vault feedback report --json
scholar-vault feedback doctor --json
scholar-vault schema export --json
scholar-vault tools-task create --title "..." --problem "..." --test "..."
```

Supported queue kinds include `compile_paper`, `update_synthesis`,
`check_contradiction`, `discover_sources`, `scholar_labs_prompt`,
`improve_tool`, `review_feedback`, and `lint_fix`. Required evidence should
match the next action: use `pdf` for paper reading or synthesis claims,
`metadata` for citation/abstract/keyword cleanup, `web` for discovery planning,
and `none` only for process or tool tasks.

Use `tools-task create` for problems in `scholar-vault-tools` itself. It creates
an `improve_tool` queue item in the vault; it does not edit the tools
repository. Use `operations log` for meaningful agent/tool runs that changed
vault state or closed work, and link queue items or feedback when applicable.

The generated dashboard `_indexes/self-improvement.md` and
`bases/self-improvement.base` summarize this state. Do not hand-edit those
generated views; regenerate them with the commands above or `scholar-vault
rebuild`.

For a full maintenance pass, follow `docs/manual-self-improvement-runbook.md`
from the `scholar-vault-tools` repository. Manual self-improvement runs are
currently preferred over scheduled automations: they surface deterministic
signals and queue items without autonomously rewriting scientific content.

## Semantic Lint And Evals

Use `scholar-vault lint-wiki` as a deterministic safety layer before treating
wiki structure as healthy. It can flag missing source links, syntheses relying
on papers without PDFs or digests, stale or incomplete digests, empty query
workbenches, unlinked prompt packs/runs, malformed queue or feedback records,
invalid generated Bases, detectable dead links, and tracked generated-file
changes. It also reports digests that are marked ready while still
metadata-only, missing checked source pages, missing PDF links, or retaining
template placeholders.

```fish
scholar-vault lint-wiki --json
scholar-vault lint-wiki --write-queue --write-report
```

Semantic lint is not an oracle. It does not prove a claim is true, complete, or
well interpreted, and it must not replace PDF reading. It writes reports and
typed queue items only when requested; it must not silently rewrite paper
cards, concepts, syntheses, or digests.

Use `_evals/*.yaml` for deterministic non-LLM eval definitions, then run:

```fish
scholar-vault eval list
scholar-vault eval run
scholar-vault eval run --kind retrieval
scholar-vault eval report
```

Initial eval kinds are `retrieval`, `grounding`, `synthesis`, and
`proposal_audit`. Eval history lives in `_exports/eval-history.json`; reports
live in `_indexes/eval-report.md`. Eval failures may create queue items with
`eval run --write-queue`.

## Research Workflow

For actual vault improvement after import and enrichment:

1. Use `$scholar-vault-research-loop` for a focused question, concept, method, dataset, proposal section, or paper cluster.
2. Start general work from `llms.txt`, `_indexes/dashboard.md`, relevant `queries/`, relevant `projects/`, relevant `concepts/`, relevant `syntheses/`, and then focused paper cards.
3. Use `scholar-vault maintenance-report` when you need a broad triage pass.
4. Orient from `status --json`, relevant cards, runs, topics, and existing `concepts/`, `syntheses/`, `tasks/`, `queries/`, `projects/`, and `proposals/`.
5. Build a reading set from selected paper cards with attached PDFs.
6. Use `scholar-vault notes-missing --heading "PDF reading notes"` when you need the unread selected-card queue.
7. Use `scholar-vault compile status --json` or `scholar-vault compile queue --project <slug> --json` when you need the reusable digest queue.
8. Read PDFs as primary evidence.
9. Use `$scholar-vault-compile-paper` to fill `paper-digests/<citekey>.md` when one paper should become reusable for future synthesis, query, project, or proposal work.
10. Update only touched paper cards with concise `## Notes`.
11. Create `concepts/<slug>.md` for reusable concepts, methods, algorithms, datasets, visual encodings, evaluation protocols, or terminology.
12. Create `syntheses/<slug>.md` for evidence-backed cross-paper answers and literature-review prose.
13. Create `tasks/<date>-research-gaps.md` for narrative open questions, unclear evidence, gaps, or follow-up reading. Use `$scholar-vault-self-improvement` / `scholar-vault queue ...` for durable typed work items, and use `$scholar-vault-labs-prompts` / `scholar-vault labs-prompts generate ...` for next Scholar Labs prompt packs.
14. Use `queries/<slug>.md` for focused research questions and link papers, runs, and syntheses with `scholar-vault query link-*`. Use `scholar-vault query rename`, `query archive`, and `query doctor --fix` for lifecycle changes so prompt packs, runs, queue items, discovery candidates, paper links, and Bases-visible fields stay aligned.
15. Run `scholar-vault concept-index` after concept-only edits, `scholar-vault bases rebuild` after query/Base edits, or `scholar-vault rebuild` after broader paper/topic/synthesis/task/project/proposal edits.

## Project Workflow

Project workspaces live under `projects/<slug>/index.md`.
Projects are lenses over the shared vault. Do not create separate vaults per project, and do not duplicate paper cards inside project folders.

When working on a project, read:

1. `llms.txt`
2. `projects/<slug>/index.md`
3. `projects/<slug>/project-map.md` if present
4. linked syntheses
5. linked concepts
6. linked paper cards and PDFs as needed

Start or refresh a workspace with:

```fish
scholar-vault project ui
scholar-vault project scaffold <slug>
scholar-vault project map <slug>
scholar-vault project audit <slug>
```

Use `scholar-vault project link-* <slug> ...` commands to connect existing
papers, runs, concepts, syntheses, tasks, or proposals. Project scaffold and
link commands refresh project navigation only; they should not normalize paper
cards, repair PDFs, or rewrite unrelated run links.

Use `scholar-vault project ui` when a desktop picker is faster for scaffolding
or updating a project, selecting and linking papers, runs, concepts, syntheses,
tasks, or proposals, generating the project map, or running the project audit.

Project notes may contain goals, plans, and work-specific synthesis, but factual claims should link to paper cards or syntheses.

## Proposal Workflow

Proposal workspaces live under `proposals/`.
Do not treat proposal workflows as the primary workflow for all vault work.

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
- read papers without `Proposal role: Core`, `Proposal role: Supporting`, or `Proposal role: Discarded`;
- broken source-matrix links, including matrices referenced by `evidence_matrix`;
- raw idea cards missing `Original User Notes - Verbatim`;
- draft claims that still cite Scholar Labs summaries instead of PDF-grounded evidence.

## Skills

Use project skills deliberately. Name the skill in the prompt when the task
matches one of these workflows:

- Start non-trivial orientation with `$scholar-vault-orient` to map current vault state, relevant runs, indexes, staging issues, and candidate source context.
- Use `$scholar-vault-read-pdf` when the work requires factual claims, methods, findings, limitations, definitions, or source connections from linked PDFs.
- Use `$scholar-vault-compile-paper` when one paper needs a reusable PDF-grounded digest under `paper-digests/`.
- Use `$scholar-vault-research-loop` for a focused post-import improvement cycle that reads PDFs, refines cards, creates metacards, and rebuilds generated views.
- Use `$scholar-vault-synthesize` when writing cross-paper synthesis notes under `syntheses/`.
- Use `$scholar-vault-refine-card` when safely improving touched `papers/*.md` cards.
- Use `$scholar-vault-curate-topics` when cleaning topic labels or prompt-boilerplate topic noise.
- Use `$scholar-vault-pdf-triage` for active PDF/staging issues before moving or attaching files.
- Use `$scholar-vault-gap-scout` to write follow-up tasks and research gaps.
- Use `$scholar-vault-self-improvement` when recording, planning, closing, or
  reporting typed queue items, operation logs, feedback ratings, or
  `scholar-vault-tools` improvement requests.
- Use `$scholar-vault-labs-prompts` when creating, inspecting, marking,
  retiring, or linking Scholar Labs prompt packs.
- Use `$scholar-vault-pepr-docx` only for PEPR proposal DOCX rendering, references, and pagination checks.
- Use the Obsidian skills from the earlier section for Obsidian syntax and file-format correctness; they complement the Scholar Vault skills but are installed from Kepano's upstream repository, not authored here.

Skills do not need to launch subagents by themselves. Subagents may be useful for parallel read-only PDF passes or verification when available, but final synthesis and file edits should stay coordinated in the main thread.

## Reporting

When reporting work, distinguish:

- PDF-grounded findings;
- card metadata/provenance;
- Scholar Labs discovery context;
- generated navigation;
- open uncertainty and follow-up tasks.

Do not claim a synthesis is evidence-grounded unless the relevant PDFs were read or the limitation is stated clearly.
