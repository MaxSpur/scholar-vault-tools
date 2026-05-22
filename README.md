# scholar-vault

`scholar-vault` is a local-first research source wiki. The linked PDF is the canonical evidence artifact for a selected source; the Markdown card under `papers/` is the durable metadata, provenance, index, and notes layer over that PDF, not a database row and not a browser export. Scholar Labs is the first ingestion adapter, but direct PDFs, BibTeX, DOI imports, and manual notes all converge on the same paper card format.

The vault is designed for plain files, Obsidian compatibility, and agent readability. A Codex agent should be able to see which sources exist, how they were discovered, where their PDFs live, which runs imported them, and which topic pages synthesize them without walking every PDF in a folder.

## Install

The tool is a Python CLI that you install from this repository into a Conda
environment. It does not require Zotero, Obsidian plugins, or a database.

### Prerequisites

- macOS with a terminal running Fish.
- Miniforge or another Conda distribution installed and initialized for Fish.
- Python 3.12 available through Conda.
- The project folder at `~/Developer/scholar-vault-tools`.
- Optional but recommended: Obsidian installed for browsing the generated vault.

### Create Or Activate The Conda Environment

If the `scholar-vault` environment already exists:

```fish
conda activate scholar-vault
```

If you are setting up a new machine, create it first:

```fish
conda create -n scholar-vault python=3.12
conda activate scholar-vault
```

Confirm that the active Python comes from the Conda environment:

```fish
python --version
which python
```

### Install The CLI From This Repository

Move into the project folder and install in editable mode:

```fish
cd ~/Developer/scholar-vault-tools
python -m pip install --upgrade pip
python -m pip install -e .
```

Editable mode means local code changes take effect without reinstalling the
package from scratch. If dependencies change later, run the editable install
command again:

```fish
python -m pip install -e .
```

Verify that the command is on your `PATH`:

```fish
scholar-vault --help
```

Fish and zsh completions are available for command names, options, and
vault-backed values such as run IDs. For Fish:

```fish
scholar-vault install-fish-completion
exec fish
```

Run the test suite if you are developing the tool:

```fish
python -m pytest
python -m ruff check .
```

If Fish cannot find `scholar-vault`, confirm that `conda activate
scholar-vault` succeeded, then reinstall from the repository folder with
`python -m pip install -e .`.

All examples below assume the `scholar-vault` Conda environment is active in
the current shell before calling `scholar-vault`. In an agent or shell where
activation is unavailable, use the explicit fallback form:

```fish
/Users/MadMax/miniforge3/condabin/conda run -n scholar-vault scholar-vault runs
```

## Configure Default Paths

Store your normal project paths once so routine commands can omit them:

```fish
scholar-vault configure --ui
```

The UI uses native folder pickers and lets you choose whether Scholar Labs JSON
exports live in the same staging folder as PDFs or in a separate exports folder.
The same configuration is also available in the terminal:

```fish
scholar-vault configure \
  --code ~/Developer/scholar-vault-tools \
  --vault ~/Documents/Research/scholar-labs-vault \
  --staging ~/Downloads/scholar-labs-staging \
  --folder-mode shared
```

The defaults are written to `~/.config/scholar-vault/config.yaml`. Run
`scholar-vault configure` without options to inspect the current values.
Explicit command-line paths always override configured defaults.
`--folder-mode shared` means `import-labs` uses the staging folder for both PDFs
and Scholar Labs JSON exports. To keep JSON exports separate, configure:

```fish
scholar-vault configure \
  --staging ~/Downloads/scholar-labs-staging \
  --exports ~/Downloads/scholar-labs-exports \
  --folder-mode separate
```

With defaults configured, commands can be shorter:

```fish
scholar-vault ask "How do collaborative map workbenches support mobility decisions?"
scholar-vault intake
scholar-vault answer "What evidence supports collaborative map workbenches?"
scholar-vault import-pdf
scholar-vault import-pdf --ui
scholar-vault status
```

## Initialize A Vault

```fish
scholar-vault init --vault ~/Documents/Research/scholar-labs-vault
```

This creates the local-first vault structure:

```text
scholar-labs-vault/
  AGENTS.md
  README.md
  llms.txt
  llms-full.txt
  config.yaml
  raw/
    scholar-labs/
    inbox/
    staging/
    unmatched/
    imported/
    metadata/
    discovery/
  pdfs/
  papers/
  paper-digests/
  runs/
  topics/
  concepts/
  syntheses/
  tasks/
    queue/
    discovery-candidates/
    scholar-labs-prompts/
  queries/
    <query-slug>/prompt-packs/
  projects/
  proposals/
  _evals/
  _operations/
    log.md
    runs/
  _feedback/
    ratings/
  _sessions/
    current.yaml
    <session-id>.yaml
  _handoffs/
  _reports/
  bases/
    papers.base
    queries.base
    synthesis-workbench.base
    scholar-labs-workbench.base
    self-improvement.base
  _indexes/
    prompts.md
    scholar-labs-prompts.md
    papers.md
    topics.md
    missing-pdfs.md
    unmatched.md
    zotero-migration.md
    dashboard.md
    paper-status.md
    reading-queue.md
    compile-dashboard.md
    metadata-issues.md
    pdf-issues.md
    synthesis-dashboard.md
    search-index.md
    paper-digests.md
    concepts.md
    syntheses.md
    tasks.md
    queries.md
    projects.md
    proposals.md
    self-improvement.md
    lint-wiki-report.md
    eval-report.md
  _exports/
    library.bib
    library.json
    library.csl.json
    semantic-neighbors.json
    eval-history.json
```

## Upgrade An Existing Vault

Use `migrate` for vaults created by older versions of this tool:

```fish
scholar-vault migrate --vault ~/Documents/Research/scholar-labs-vault --dry-run
scholar-vault migrate --vault ~/Documents/Research/scholar-labs-vault --json
scholar-vault migrate --vault ~/Documents/Research/scholar-labs-vault --apply
```

Dry-run mode reports every proposed directory, starter file, generated output,
Base, paper-frontmatter backfill, and operation-log change without writing. Apply
mode creates missing managed folders, refreshes generated dashboards and Bases,
adds only absent safe operational paper-card frontmatter fields, logs an
operation, then runs `doctor`, `compile doctor`, `bases doctor`, and `lint-wiki`.
Existing `AGENTS.md` files are preserved unless `--update-agents` is passed.

`AGENTS.md` is initialized with the vault-specific agent operating rules from
`VAULT_AGENTS_TEMPLATE.md`. Existing vault-level `AGENTS.md` files are preserved
so local project notes are not overwritten by later commands.

`init` does not install Codex skills. The optional vault-agent skills from this
repository's `vault-agent-skills/` folder can be copied into vault
`.agents/skills/` later; see
[Codex Agent Skills](#codex-agent-skills).

## End-To-End Tutorial

The ordinary workflow is now intentionally short:

```fish
scholar-vault ask "question"
# Run the printed prompt manually in Google Scholar Labs.
# Download the PDFs you want and export the visible Labs results JSON.
scholar-vault intake
scholar-vault answer "focused synthesis question"
```

The detailed commands still exist, but these four steps are the front door for
normal use.

For a brand-new project, `start` only creates the clean project workspace:

```fish
scholar-vault start budgie-vocoder --title "Budgerigar Vocoder"
```

For a concrete multi-prompt project walkthrough, see
[Bird Vocoder Autopilot Tutorial](docs/tutorials/bird-vocoder-autopilot.md).

1. Configure your defaults once:

```fish
conda activate scholar-vault
cd ~/Developer/scholar-vault-tools
scholar-vault configure \
  --code ~/Developer/scholar-vault-tools \
  --vault ~/Documents/Research/scholar-labs-vault \
  --staging ~/Downloads/scholar-labs-staging \
  --folder-mode shared
```

2. Create the vault if needed:

```fish
scholar-vault init --vault ~/Documents/Research/scholar-labs-vault
```

3. Ask a research question:

```fish
scholar-vault ask "How do collaborative map workbenches support mobility decisions?"
```

`ask` creates or reuses a durable `queries/<slug>.md` note, creates a current
session under `_sessions/`, generates a query-linked Scholar Labs prompt pack,
chooses the best first prompt, refreshes the query/Bases views, and logs the
operation. It does not scrape Scholar. The terminal output is just the prompt
and the next step.

Useful variants:

```fish
scholar-vault ask "How do tactile maps affect route decisions?" --project map-lens-deformation
scholar-vault ask "How do tactile maps affect route decisions?" --seed-api openalex
scholar-vault ask "How do tactile maps affect route decisions?" --copy --open-scholar
```

`--seed-api openalex` or `--seed-api semantic-scholar` only improves prompt
wording. API candidates are not canonical paper cards.

4. In Google Scholar Labs, paste the printed prompt, inspect the result, download
only the PDFs you want to keep into the configured staging folder, and save the
visible results with `browser/scholar_labs_json_exporter.js`.

5. Intake the run:

```fish
scholar-vault intake
```

`intake` uses the current session and the newest unused top-level Labs JSON from
the configured exports folder, or from staging when exports are shared. It runs
the existing `import-labs` path with commit mode, query and prompt-pack
provenance, matched-PDF archiving, used-JSON archiving, and enrichment. Then it
scaffolds `paper-digests/` for selected papers, runs deterministic maintenance,
lint, eval, compile, rebuild, Bases, and Obsidian checks, writes a concise
session report, and logs the operation.

The session report is written to `queries/<slug>/session-report.md` when the
session has a query, otherwise `_reports/latest.md`. It lists the question,
status, prompt pack, run, imported papers, PDFs, blockers, digest status,
syntheses, and the next user action.

`intake` only blocks for real follow-up, such as staged PDF matches that need
manual review. If that happens, resolve the blocker with the lower-level repair
commands, or run `scholar-vault intake --ui` to open the staging match UI and
retry the import after targeted matches are accepted.

### If You Already Ran Scholar Labs Yourself

You do not have to run `ask` before `intake` when you already have a Google
Scholar Labs JSON export. The export includes the exact prompt under its
top-level `prompt` field, and the imported run stores that prompt as run
provenance.

For a new project, create the clean project first:

```fish
scholar-vault start budgie-vocoder --title "Budgerigar Vocoder"
```

Then import the already-exported Labs JSON and staged PDFs:

```fish
scholar-vault intake \
  --project budgie-vocoder \
  --slug budgie-vocoder-scan \
  --question "Which acoustic evidence supports a budgerigar synthesizer?" \
  --export ~/Downloads/scholar-labs-staging/scholar-labs-budgerigar.json \
  --staging ~/Downloads/scholar-labs-staging \
  --new-session
```

The staging folder can be the same shared folder you use for all Scholar Labs
downloads. It may contain PDFs and JSON exports from several prompts; the
explicit `--export` path selects which Labs prompt/run to import, and unrelated
PDFs remain in staging for later imports.

`budgie-vocoder` is the project slug. `budgie-vocoder-scan` is the query slug:
the short stable filename for the research-query note at
`queries/budgie-vocoder-scan.md`. A project can have many query slugs over
time, for example one initial broad scan, one methods scan, and one negative
evidence scan.

Use `--new-session` when you are importing a self-run search and an older
current session may still exist. If there is no current session, `intake` can
also bootstrap from the JSON prompt without it.

You can still run `ask` first when you want the vault to generate a prompt pack,
copy/open Scholar for you, or create the query/session before you search. In
the self-run path, `intake` creates the query/session from the JSON prompt,
writes an exact used-prompt artifact under the query's `prompt-packs/` folder,
and links the imported run to that query and prompt artifact.

6. Optional: run a deterministic improvement pass before synthesis:

```fish
scholar-vault improve --no-agent
scholar-vault improve --dry-run
scholar-vault improve --agent codex --budget-papers 5
```

Without an agent, `improve` refreshes reports/checks, prioritizes queue items
linked to the session, writes the session report, and logs the run. With Codex,
it writes a handoff under `_handoffs/` and runs:

```fish
codex exec -C "<vault>" --sandbox workspace-write "$(cat "<handoff>")"
```

It never requests danger/full access by default.

7. Answer the synthesis question:

```fish
scholar-vault answer "What evidence supports collaborative map workbenches for mobility decisions?"
```

Without `--agent`, `answer` writes the handoff file and prints the single Codex
command to run. With `--agent codex`, it invokes Codex with workspace-write
sandboxing. The handoff tells the agent to read PDFs before making scientific
claims, fill or mark digests only when compile guards pass, draft or update
focused syntheses, validate, rebuild, link outputs back to the query/session,
and log the work.

8. Track or archive the session:

```fish
scholar-vault session current
scholar-vault session list
scholar-vault session show
scholar-vault session archive
```

Sessions live under `_sessions/` and carry `id`, `status`, `question`,
`project`, `query_path`, `prompt_pack_path`, `run_id`, `synthesis_paths`,
`blockers`, and timestamps. Status values are `asked`, `prompt_ready`,
`waiting_for_labs_export`, `imported`, `improving`, `answered`, `blocked`, and
`archived`.

## Manual And Advanced Workflows

The detailed commands remain available for direct use and repair work:
`import-labs`, `import-pdf`, `labs-prompts`, `discover`, `query`, `compile`,
`maintenance-report`, `lint-wiki`, `eval`, `bases`, `obsidian`, `project`,
`proposal-audit`, `enrich`, `match-staging`, `rerun`, `resume`, `attach-pdf`,
`topic-map`, bibliography exports, and skill synchronization.

See [Advanced Command Reference](docs/advanced-command-reference.md) for the
command catalog and lower-level workflows.

## Direct PDF Workflow

Use this when you found or downloaded papers yourself and do not have a Scholar
Labs JSON export.

For a new project, create the clean project first:

```fish
scholar-vault start budgie-vocoder --title "Budgerigar Vocoder"
```

Then run PDF-only intake:

```fish
scholar-vault intake \
  --pdf-only \
  --project budgie-vocoder \
  --slug budgie-vocoder-pdf-seed \
  --question "Which acoustic evidence supports a budgerigar synthesizer?" \
  --staging ~/Downloads/scholar-labs-staging \
  --new-session
```

PDF-only intake imports the PDFs, links imported citekeys to the query and
project, scaffolds paper digests, runs the deterministic checks, writes the
session report, and logs the operation. The original downloaded PDFs stay where
they are. In a shared staging folder, PDF-only intake treats every staged PDF as
intentional input for that PDF-only pass, so use it when the folder currently
contains only the PDFs you want to import without Labs provenance.

The lower-level `import-pdf --ui` workflow remains available when you want a
desktop file picker or need to import PDFs outside a session.

Then continue from the session:

```fish
scholar-vault answer "focused synthesis question" --agent codex
```

## Advanced Command Reference

The lower-level command catalog now lives in
[docs/advanced-command-reference.md](docs/advanced-command-reference.md). Use it
when you need to bypass the autopilot flow, repair staging/PDF matches, run
specialized diagnostics, manage projects/proposals, export bibliographies, or
synchronize vault-agent skills.

For routine research intake and synthesis, prefer:

```fish
scholar-vault ask "question"
scholar-vault intake
scholar-vault improve --no-agent
scholar-vault answer "synthesis question"
```

## Codex Agent Skills

This repository includes optional repository-owned vault-agent Codex skills
under `vault-agent-skills/` for post-import vault refinement. It also keeps
`VAULT_AGENTS_TEMPLATE.md` as the source for the vault-local `AGENTS.md` guide.
The repository root `AGENTS.md` is for agents working on this tools repo, not
for agents working inside a research vault. Keep those surfaces separate:
`vault-agent-skills/` is published into a vault's `.agents/skills/`, while this
repository's own `.agents/skills/` path is reserved for future tools-repo
development skills.

Install or update the optional vault-agent skills when you want a Codex session
opened on the vault to follow the same PDF-grounded workflows. The short path is:

```fish
scholar-vault skills diff --vault ~/Documents/Research/scholar-labs-vault
scholar-vault skills publish --vault ~/Documents/Research/scholar-labs-vault --apply
```

Use `skills adopt` when you intentionally want to pull vault-side skill or
`AGENTS.md` edits back into this repository. Install Kepano's Obsidian skills
and other third-party skills with `skills install-external`; keep them external
rather than adopting them into `vault-agent-skills/`. See
[Advanced Command Reference](docs/advanced-command-reference.md#skill-synchronization)
for the full sync command list.

After publishing skills, open a fresh Codex session with the vault as the
project folder. When a vault-side Codex task needs the CLI, activate the Conda
environment first:

```fish
conda activate scholar-vault
scholar-vault runs
```

If activation is not initialized in that shell, use:

```fish
/Users/MadMax/miniforge3/condabin/conda run -n scholar-vault scholar-vault runs
```

Available skills:

- `$scholar-vault-orient`: map relevant canonical papers, runs, topics,
  active staging/PDF issues, optional candidate context, and metadata issues
  before doing deeper work.
- `$scholar-vault-synthesize`: write evidence-linked synthesis notes under
  `syntheses/` from linked PDFs, paper cards, and run provenance.
- `$scholar-vault-refine-card`: safely improve `papers/*.md` notes and safe
  metadata from PDF evidence while preserving generated sections, enrichment
  state, locks, and provenance.
- `$scholar-vault-curate-topics`: clean noisy prompt-derived `topics`
  frontmatter, then rebuild derived topic pages and indexes.
- `$scholar-vault-pdf-triage`: inspect orphan, duplicate, unmatched, and
  staged PDFs, then choose safe CLI repair workflows.
- `$scholar-vault-gap-scout`: write `tasks/<date>-research-gaps.md` with next
  active staging, metadata, import, and synthesis actions.
- `$scholar-vault-labs-prompts`: generate, inspect, mark, retire, or link
  Scholar Labs prompt packs while keeping Labs output discovery-only.
- `$scholar-vault-self-improvement`: inspect or update typed queue items,
  operation logs, feedback ratings, and `scholar-vault-tools` improvement
  requests without treating process state as research evidence.
- `$scholar-vault-read-pdf`: read linked PDFs as the primary evidence and add
  evidence-grounded notes, topics, metadata fixes, syntheses, or metacards.
- `$scholar-vault-compile-paper`: fill a reusable PDF-grounded
  `paper-digests/<citekey>.md` digest and mark its compile/review state.
- `$scholar-vault-research-loop`: run a focused post-import research cycle:
  read PDFs, refine touched cards, create concept/synthesis metacards, and
  rebuild generated views.

Example prompts:

```text
Use $scholar-vault-orient to map the current vault state.
Use $scholar-vault-gap-scout to identify the next import and metadata gaps.
Use $scholar-vault-synthesize to write a synthesis on OD-flow visualization.
Use $scholar-vault-curate-topics to propose a cleanup of noisy topics.
Use $scholar-vault-pdf-triage to inspect current staging PDFs and historical unmatched records.
Use $scholar-vault-self-improvement to review queue and feedback state.
Use $scholar-vault-read-pdf to read selected PDFs and refine their cards.
Use $scholar-vault-compile-paper to compile one paper digest for <citekey>.
Use $scholar-vault-research-loop to work through this question: <question>.
Use $obsidian-markdown before substantial edits to Obsidian Markdown/properties.
Use $json-canvas to create or repair a .canvas project map.
```

The skills do not require subagents and do not launch them by themselves. That
is intentional: they should work in a normal single-agent Codex session and in
environments where subagent tools are unavailable. For large vault refinement
tasks, subagents can still be useful for parallel read-only exploration or
independent verification when the active Codex environment and user instructions
allow them, but final synthesis and file edits should stay coordinated in the
main thread.

### Answer Phase Agent Work

The `answer` command now writes the Codex handoff for this work. It instructs
the agent to orient from the current session/query, read linked PDFs before
scientific claims, scaffold or update paper digests only when evidence guards
pass, draft focused syntheses under `syntheses/`, link outputs back to the
query/session, validate, rebuild, and log the operation.

For manual agent prompting, the older skills are still useful:

```text
Use $scholar-vault-orient to map the current vault state.
Use $scholar-vault-compile-paper to compile one paper digest for <citekey>.
Use $scholar-vault-research-loop to work through this question: <question>.
Use $scholar-vault-synthesize to write a synthesis on OD-flow visualization.
```

Keep final synthesis and file edits coordinated in one session. Subagents can
help with parallel read-only exploration or independent verification when the
active Codex environment and user instructions allow them.

### Paper Compile Digests

`paper-digests/<citekey>.md` files are durable user/agent-authored artifacts
for reusable single-paper understanding. The CLI scaffolds, tracks, validates,
and indexes them; it does not read PDFs or generate scientific claims.

Scaffolding is idempotent and will not overwrite an existing digest unless
`--force` is passed. `compile mark --status compiled` and
`compile mark --status reviewed` reject digests that still have
`evidence_level: metadata_only`, no `source_pages_checked`, missing PDF links,
or unfilled scaffold placeholders unless `--force` is passed. Mark a digest
`stale` when the paper, a linked query, a linked project, or an interpretation
changes and the digest needs review. See the advanced reference for the compile
command list.

## Generated Records

- `pdfs/*.pdf`: canonical evidence artifacts for selected sources.
- `papers/*.md`: canonical source cards for selected papers by default; these store metadata, provenance, links, abstracts, keywords, and notes over the linked PDFs.
- `paper-digests/*.md`: durable PDF-grounded single-paper digests for reuse in
  syntheses, concept pages, query dossiers, project work, and proposal audits.
- `concepts/*.md`: optional agent-written concept/metacards that connect papers by method, dataset, visual encoding, evaluation protocol, or terminology.
- `syntheses/*.md`: optional agent-written cross-paper syntheses grounded in PDFs.
- `tasks/*.md`: optional agent-written follow-up tasks and research gaps.
- `tasks/discovery-candidates/*.yaml`: non-canonical OpenAlex/Semantic Scholar
  candidate records for related-paper discovery and Scholar Labs prompt seeds.
- `queries/*.md`: durable research-query workbench notes with linked papers, runs, syntheses, concepts, prompt packs, and Obsidian Bases embeds.
- `_sessions/*.yaml`: durable ask/intake/improve/answer session state.
- `_handoffs/*.md`: generated Codex handoff prompts.
- `queries/<slug>/session-report.md` and `_reports/latest.md`: concise
  session reports for user-facing autopilot runs.
- `projects/<slug>/index.md`: optional project lens over shared papers, runs, concepts, syntheses, tasks, and proposals.
- `projects/<slug>/project-map.md`: generated project map summarizing linked record status, gaps, and next actions.
- `proposals/*.md` or `proposals/<slug>/*.md`: optional proposal workspaces, outlines, source matrices, and draft evidence layers.
- `_evals/*.yaml`: deterministic eval definitions for retrieval, grounding,
  synthesis, and proposal source-matrix checks.
- `papers/*.md` body sections: human-readable keywords, abstract, and primary Scholar Labs summary. Long prose is not duplicated in frontmatter.
- `runs/<run_id>/<Short Title.md>`: Obsidian-friendly per-run provenance pages that keep all Scholar Labs candidate results.
- `runs/*/index.yaml`: machine-readable run records used by `resume`, `rerun`, and rebuilds.
- `runs/*/import-manifest.yaml`: transactional record of proposed matches, decisions, copied PDFs, and created cards.
- `raw/metadata/<citekey>/`: cached citation provider responses and generated citation artifacts.
- `raw/discovery/`: cached OpenAlex and Semantic Scholar discovery responses.
- `raw/metadata/<citekey>/citation.bib` and `citation.csl.json`: preferred provider-backed sources for one-card and whole-library BibLaTeX export.
- `topics/*.md`: simple topic pages derived from prompt keywords and rationale labels.
- `_indexes/*.md`: navigation and maintenance views.
- `bases/*.base`: generated Obsidian Bases workbench views over existing vault state.
- `llms.txt` and `llms-full.txt`: short and expanded agent navigation summaries.
- `_exports/library.*`: plain-file exports for Zotero migration or other tools.
- `_exports/eval-history.json`: generated eval run history.

## Git workflow for the vault

Rebuilds can produce large but expected diffs. Treat the vault as a mix of
canonical records and generated views:

- Commit canonical changes when they reflect intentional work: `papers/`,
  `paper-digests/`, `pdfs/`, `raw/`, `_evals/`, run YAML/manifests under
  `runs/`, and durable notes under `concepts/`, `syntheses/`, `tasks/`,
  `queries/`, `projects/`, and `proposals/`.
- Treat `_indexes/`, `topics/`, `llms.txt`, `llms-full.txt`, `_exports/`,
  `bases/`, rendered run Markdown under `runs/`, and
  `projects/*/project-map.md` as generated output. Do not hand-edit these
  unless a workflow explicitly says to.
- Paper cards in `papers/` are canonical records, but their generated section
  layout is tool-managed. Use CLI commands for metadata/abstract/keyword fixes
  and keep manual reading notes under `## Notes`.

Use `git-summary` before reviewing or committing a large vault diff:

```fish
scholar-vault git-summary --vault ~/Documents/Research/scholar-labs-vault
scholar-vault git-summary --vault ~/Documents/Research/scholar-labs-vault --json
```

The command groups changed files by top-level path and classifies them as
`canonical`, `generated`, or `other`. Large generated counts after `rebuild` are
normal. Unexpected canonical changes deserve review.

To check rebuild determinism, run `scholar-vault rebuild`, inspect
`git-summary`, then run `scholar-vault rebuild` again. The second rebuild should
not introduce new changed files or churn the generated diff. If the second pass
changes timestamps, ordering, or generated content again, treat that as a
nondeterminism bug before committing.

Optional `.gitattributes` examples for making high-churn generated files less
noisy in GitHub or local diffs:

```gitattributes
_indexes/** -diff
topics/** -diff
_exports/library.* -diff
_exports/semantic-neighbors.json -diff
llms.txt -diff
llms-full.txt -diff
runs/**/*.md -diff
projects/*/project-map.md -diff
```

This repository does not install those rules automatically. Add them to a vault
only if you prefer hiding generated diff bodies while still tracking the files.

## Verification

After implementation or local changes, run:

```fish
python -m pytest
python -m ruff check .
python -m pip install -e .
scholar-vault init --vault ~/Documents/Research/scholar-labs-vault
```
