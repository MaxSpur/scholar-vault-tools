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
scholar-vault import-labs --commit
scholar-vault import-pdf
scholar-vault import-pdf --ui
scholar-vault rerun --commit
scholar-vault status
scholar-vault maintenance-report
scholar-vault rebuild
scholar-vault enrich --ui
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
  pdfs/
  papers/
  paper-digests/
  runs/
  topics/
  concepts/
  syntheses/
  tasks/
    queue/
    scholar-labs-prompts/
  queries/
    <query-slug>/prompt-packs/
  projects/
  proposals/
  _operations/
    log.md
    runs/
  _feedback/
    ratings/
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
  _exports/
    library.bib
    library.json
    library.csl.json
    semantic-neighbors.json
```

`AGENTS.md` is initialized with the vault-specific agent operating rules from
`VAULT_AGENTS_TEMPLATE.md`. Existing vault-level `AGENTS.md` files are preserved
so local project notes are not overwritten by later commands.

`init` does not install Codex skills. The optional vault-agent skills from this
repository's `vault-agent-skills/` folder can be copied into vault
`.agents/skills/` later; see
[Codex Agent Skills](#codex-agent-skills).

## End-To-End Tutorial

The normal workflow is: configure paths once, import a Scholar Labs run, resolve
PDF and metadata follow-up, then use the vault as an agent-readable wiki.

1. Configure your defaults:

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

3. In Google Scholar Labs, run a prompt, download the PDFs you want into the
staging folder, and save the visible results with
`browser/scholar_labs_json_exporter.js`.

4. Import the newest unused Scholar Labs export and review matches in the
desktop UI:

```fish
scholar-vault import-labs --ui
```

For a mostly automatic terminal import, use:

```fish
scholar-vault import-labs --commit
```

The import keeps all Scholar Labs candidates on the run record, creates
canonical `papers/*.md` cards for selected/matched papers by default, copies
verified PDFs into `pdfs/`, archives matched staging PDFs, moves the used JSON
export into `used/`, and runs citation, abstract, and keyword enrichment unless
you pass `--no-enrich`.

Candidate results that you did not download as PDFs remain in the run record as
discovery context. They are not missing canonical sources and do not need action
unless you later decide to fetch those papers.

5. If PDFs remain in staging, triage them against previous runs:

```fish
scholar-vault match-staging --ui
```

In the staging matcher, combine a typed paper title with a chosen PDF path when
automatic scanning is ambiguous, then click `Import PDF` on the matching run
result.

6. Resolve metadata, abstract, and keyword issues:

```fish
scholar-vault enrich --ui
```

Use `set-metadata`, `set-abstract`, or `set-keywords` when a manual correction
is clearer than another provider lookup.

7. Rebuild after manual paper-card edits:

```fish
scholar-vault rebuild
```

8. Open the vault in Obsidian or start a Codex project from the vault folder.
Use `llms.txt`, `llms-full.txt`, `_indexes/`, `papers/`, and `runs/` as the
agent navigation surface. Install the optional Codex skills when you want guided
agent refinement workflows.

## Scholar Labs Prompt Workbench

Use prompt packs when you want to plan a Scholar Labs run before opening
Scholar. Prompt packs are Markdown artifacts with frontmatter status, query or
project links, and structured prompts for coverage gaps, related seed papers,
method/dataset relations, contradiction checks, negative evidence, review
updates, benchmarks, proposal gaps, synthesis expansion, and failure modes.

Generate a query-specific pack:

```fish
scholar-vault labs-prompts generate --query mobility-evidence
```

Generate from a project or from open gap/proposal tasks:

```fish
scholar-vault labs-prompts generate --project map-lens-deformation
scholar-vault labs-prompts generate --from-gaps
```

By default, prompt generation is local and offline. Optional API seed support
can call OpenAlex or Semantic Scholar only to suggest seed titles and query
terms for the prompt text:

```fish
scholar-vault labs-prompts generate --query mobility-evidence --seed-api openalex
```

These API candidates are not paper cards. They become canonical only through
the existing PDF, DOI, BibTeX, or manual import paths.

List, inspect, and track prompt packs:

```fish
scholar-vault labs-prompts list
scholar-vault labs-prompts show query-mobility-evidence-scholar-labs-prompts
scholar-vault labs-prompts mark-used query-mobility-evidence-scholar-labs-prompts --notes "Ran in Labs on 2026-05-15"
scholar-vault labs-prompts link-run query-mobility-evidence-scholar-labs-prompts 2026-05-15_mobility
scholar-vault labs-prompts retire query-mobility-evidence-scholar-labs-prompts
scholar-vault labs-prompts doctor --json
```

When importing a Labs export created from a pack, link the provenance directly:

```fish
scholar-vault import-labs --commit --prompt-pack query-mobility-evidence-scholar-labs-prompts --query mobility-evidence
```

The run note links back to the prompt pack and query, the prompt pack moves to
`imported`, the query note gets the linked run, and
`_indexes/scholar-labs-prompts.md` plus `bases/scholar-labs-workbench.base`
surface active packs and import status.

## Scholar Labs Workflow

1. Run a Google Scholar Labs search.
2. Download selected PDFs into `~/Downloads/scholar-labs-staging`.
3. Run the browser exporter in `browser/scholar_labs_json_exporter.js` on the Scholar Labs page to save a JSON export into the same staging folder. This exporter is intentionally tied to Google Scholar `gs_*` selectors and should not be replaced with generic card scraping logic.
4. Import the run:

```fish
scholar-vault import-labs --vault ~/Documents/Research/scholar-labs-vault --export ~/Downloads/scholar-labs-exports/example.json --staging ~/Downloads/scholar-labs-staging
```

If you configured defaults, the usual command is:

```fish
scholar-vault import-labs --commit
```

When `--export` is omitted, `import-labs` uses the newest top-level `.json`
file in the configured exports folder if that folder has one. Otherwise it
falls back to the staging folder, so PDFs and JSON exports can live together.
It ignores files already moved into the `used/` subfolder. Pass `--export PATH`
when you want to import a specific JSON instead.

The compatibility alias still behaves identically:

```fish
scholar-vault import --vault ~/Documents/Research/scholar-labs-vault --export ~/Downloads/scholar-labs-exports/example.json --staging ~/Downloads/scholar-labs-staging
```

Default Scholar Labs behavior is now selected-only:

- The raw Scholar Labs export is always preserved under `raw/scholar-labs/`.
- The run page stores all candidate results from the export.
- Runs imported with `--prompt-pack` and/or `--query` link back to the prompt
  pack and query note, and linked prompt packs are marked `imported`.
- Canonical `papers/*.md` cards are created only for results with matched PDFs.
- If a later Scholar Labs run returns a paper that already has a canonical card and attached PDF, the run links to the existing card and adds that run's summary to the card instead of creating a duplicate.
- Candidate results stay on the run page unless you explicitly opt in with `--include-without-pdf`.
- `import-labs` copies accepted PDFs into `pdfs/`, verifies them, and then archives the matched originals out of staging into `raw/imported/`, leaving only unmatched PDFs in staging.
- `_indexes/missing-pdfs.md` is an optional candidate discovery backlog, not a maintenance defect list. In the normal workflow it mostly means "Scholar Labs suggested these, but you did not download/import them."
- `_indexes/unmatched.md` is a historical manifest audit of staged PDFs that were not accepted during specific imports. Rows may repeat across runs and are actionable only when the file still exists in staging and is not already a duplicate of a vault PDF.
- After committed matches or direct PDF imports, `import-labs`, `import`,
  `import-pdf`, `resume`, and `rerun` run citation, abstract, and PDF keyword
  enrichment for touched paper cards by default. Use `--no-enrich` when you
  want a faster import that skips provider lookups.
- Paper-provided keywords from BibTeX, provider metadata, and local PDF text are stored separately from prompt-derived `topics`. If a paper has no publication keywords or index terms, the follow-up UI can mark that absence explicitly so the card no longer looks unfinished.
- When a PDF is attached to a canonical card, matching previous run results with the same Scholar CID or exact normalized title are linked to that same card. `rebuild` also repairs missing run/card/PDF links for older stale records.
- After a successful non-dry-run import, `import-labs` moves the used JSON export into a sibling `used/` folder without renaming it, for example `~/Downloads/scholar-labs-staging/used/example.json`. The run metadata is updated so `resume` and `rerun` still know where the export went.
- The final import summary separates reused prior selections, existing vault-card links, newly accepted staged PDFs, review prompts, unresolved results, staged-file cleanup, and enrichment changes, so rerunning an old JSON should make clear why no match-review prompts appeared.
- `import-run` is the lower-level transactional variant. It copies accepted PDFs into `pdfs/` but leaves staging untouched unless you later run `clean-staging`.
- Most commands that accept `--vault`, and commands that accept `--staging`, can use configured defaults when those options are omitted.
- Import and enrichment commands show terminal progress while scanning PDFs, matching results, querying metadata providers, and rebuilding derived files. Enrichment logs include per-pass attempt/result/skip lines for local DOI/PDF scans and provider lookups.
- Staged PDF scan results are cached in `.scholar-vault-pdf-scan-cache` inside the staging folder. Repeated imports reuse cached title, DOI, year, text, and hash data when a PDF's size and modification time are unchanged.
- `match-staging --ui` can import one chosen leftover PDF into one selected run result. Rows already attached to a vault card can also open the card or move the redundant staging copy into `staging/trash/`.

Run notes are written as `runs/<run_id>/<Short Title.md>` instead of
`index.md`. This gives Obsidian Graph and the file sidebar meaningful run/prompt
nodes. Each run note has frontmatter `type: scholar_labs_run`, `title`,
`note_file`, and tag `scholar-vault/run`, so Graph groups can color prompts
separately from paper cards. The Scholar Labs browser exporter asks for this
title before saving JSON and stores it in the export. For older JSON files
without a title, `import-labs` displays the full Scholar Labs prompt and asks
you to confirm or replace the inferred title before importing.

Dry-run the import without creating paper cards or copying PDFs:

```fish
scholar-vault import-labs --vault ~/Documents/Research/scholar-labs-vault --export ~/Downloads/scholar-labs-exports/example.json --staging ~/Downloads/scholar-labs-staging --dry-run
```

Auto-commit only high-confidence matches:

```fish
scholar-vault import-labs --vault ~/Documents/Research/scholar-labs-vault --export ~/Downloads/scholar-labs-exports/example.json --staging ~/Downloads/scholar-labs-staging --commit
```

Skip automatic citation, abstract, and keyword enrichment if you only want to match and archive PDFs:

```fish
scholar-vault import-labs --commit --no-enrich
```

Use the desktop review UI for interactive match confirmation:

```fish
scholar-vault import-labs --ui
```

The UI shows a large Scholar Labs title, a broad scrollable first-page preview,
and large confidence, Yes, and No panels. Keyboard shortcuts are `Return`,
`→`, or `Y` to accept; `←`, `Backspace`, or `N` to reject the current match;
`Esc` or the Abort Import button to stop the import before later steps such as
enrichment; `Space` / `⇧Space` to scroll the preview; and `⌘O` or `O` to open
the PDF.
If the run already exists, the resume/update confirmation is shown in the GUI
rather than as a hidden terminal prompt.
After matching, GUI imports keep a small progress window open for citation,
abstract, and keyword enrichment. The full output stream shows each provider pass and result,
while the compact item stream stays focused on citekeys. If enrichment leaves records incomplete, ambiguous, or
unresolved, a follow-up browser opens with the affected cards and quick actions
to open the paper card or attached PDF.
If GUI dependencies are unavailable in the current environment, the command
falls back to terminal prompts.

You can still override the JSON title during import:

```fish
scholar-vault import-labs --vault ~/Documents/Research/scholar-labs-vault --export ~/Downloads/scholar-labs-exports/example.json --staging ~/Downloads/scholar-labs-staging --commit --title "Immersive Analytics Sources"
```

Also create candidate paper cards for results without matched PDFs:

```fish
scholar-vault import-labs --vault ~/Documents/Research/scholar-labs-vault --export ~/Downloads/scholar-labs-exports/example.json --staging ~/Downloads/scholar-labs-staging --include-without-pdf
```

Keep the original JSON export in place instead of moving it to `used/`:

```fish
scholar-vault import-labs --vault ~/Documents/Research/scholar-labs-vault --export ~/Downloads/scholar-labs-exports/example.json --staging ~/Downloads/scholar-labs-staging --keep-export
```

## Scholar Labs Troubleshooting

If the exporter produces `prompt: "Google Scholar"` and `results: []`, you are either not on a completed Scholar Labs results page or the DOM selectors are broken. Run these in the browser console:

```js
document.querySelectorAll('div.gs_r[data-cid], div.gs_or[data-cid]').length
document.querySelector('.gs_as_np_tq')?.innerText
```

The first command should return a positive number, and the second should return the original Scholar Labs prompt.

## Direct PDF Workflow

Use this when you found or downloaded a paper yourself and do not have a
Scholar Labs JSON export or prompt summary.

For the desktop workflow, run:

```fish
scholar-vault import-pdf --ui
```

The UI accepts multiple PDFs by drag-and-drop or file picker. It copies the
PDFs into `pdfs/`, creates or updates canonical `papers/*.md` cards, runs
citation, abstract, and publication-keyword enrichment by default, then opens a
follow-up editor for unresolved metadata, missing abstracts, or missing
keywords. The original downloaded PDFs stay where they are.

For the terminal workflow, drop PDFs into the configured staging folder or pass
the folder explicitly:

```fish
scholar-vault import-pdf --vault ~/Documents/Research/scholar-labs-vault --staging ~/Downloads/scholar-labs-staging
```

Use `--no-enrich` when you only want to copy PDFs and create cards quickly.
The importer extracts metadata where possible, renames and copies PDFs into
`pdfs/`, creates source cards, and leaves any unresolved citation, abstract, or
keyword fields for `scholar-vault enrich --ui`.

## Other Commands

Import a BibTeX file:

```fish
scholar-vault import-bibtex --vault ~/Documents/Research/scholar-labs-vault --bib ~/Downloads/library.bib
```

Import a DOI stub:

```fish
scholar-vault import-doi --vault ~/Documents/Research/scholar-labs-vault --doi 10.1145/3544548.3580848
```

Rebuild derived indexes and exports from the canonical paper cards:

```fish
scholar-vault rebuild --vault ~/Documents/Research/scholar-labs-vault
```

`rebuild` also rerenders generated paper and run Markdown from the current templates, so existing paper cards get new generated sections such as `## Quick access`. At the end it prints a compact summary with paper-card rewrites, normalized records, refreshed run notes, and regenerated index/export files.

Regenerate the whole-vault BibLaTeX export:

```fish
scholar-vault biblatex --vault ~/Documents/Research/scholar-labs-vault
# Compatibility alias:
scholar-vault bibtex --vault ~/Documents/Research/scholar-labs-vault
```

Generate BibLaTeX for the card you are viewing in Obsidian by copying its
`citekey` and running:

```fish
scholar-vault card-biblatex --vault ~/Documents/Research/scholar-labs-vault smith2024rag
scholar-vault biblatex --vault ~/Documents/Research/scholar-labs-vault --citekey smith2024rag
scholar-vault biblatex --vault ~/Documents/Research/scholar-labs-vault --citekey smith2024rag --output ~/Desktop/smith2024rag.bib
scholar-vault card-biblatex --vault ~/Documents/Research/scholar-labs-vault --clipboard smith2024rag
scholar-vault card-biblatex --vault ~/Documents/Research/scholar-labs-vault --cite --clipboard smith2024rag
```

The `bibtex` and `card-bibtex` command names remain as compatibility aliases.
One-card BibLaTeX uses the best available source in this order: cached provider
BibTeX from `raw/metadata/<citekey>/citation.bib`, cached CSL JSON from
`citation.csl.json`, then a card-derived fallback. It normalizes the entry key
to the vault citekey and adds useful vault-local fields such as `file`,
`abstract`, and publication `keywords` when present. Exported values are
normalized for BibLaTeX/TeX compatibility: smart punctuation becomes ASCII
punctuation, en/em dashes become TeX-style `--` / `---`, remaining Latin
accents become TeX accent macros, and uppercase title tokens such as `LLM`,
`VR`, `3D`, or `GeoAI` are brace-protected. Provider fields are normalized to
BibLaTeX names such as `journaltitle`, `report`, and `thesis` where possible.
Use `--no-local-fields` when you need a portable publication-only entry without
vault-local `abstract`, `file`, `keywords`, or `note` fields. Use
`--with-vault-note` when you also want Scholar Labs summary/rationale text in
the BibLaTeX `note` field.

Validate one-card or library export quality:

```fish
scholar-vault card-biblatex --vault ~/Documents/Research/scholar-labs-vault --validate smith2024rag
scholar-vault biblatex-doctor --vault ~/Documents/Research/scholar-labs-vault
scholar-vault biblatex-doctor --vault ~/Documents/Research/scholar-labs-vault --json
```

Generate formatted APA-style references from the same provider-first metadata:

```fish
scholar-vault reference --vault ~/Documents/Research/scholar-labs-vault smith2024rag
scholar-vault reference --vault ~/Documents/Research/scholar-labs-vault --format rtf --output ~/Desktop/smith2024rag.rtf smith2024rag
scholar-vault reference --vault ~/Documents/Research/scholar-labs-vault --clipboard smith2024rag
scholar-vault references --vault ~/Documents/Research/scholar-labs-vault
scholar-vault references --vault ~/Documents/Research/scholar-labs-vault --format rtf --output ~/Desktop/references.rtf
```

`reference` prints one card's formatted reference. `references` writes the whole
vault bibliography to `_exports/references-apa.md` by default. Supported formats
are `markdown`, `rtf`, and `plain`; the current supported style is `apa`. These
commands are for copy/paste bibliographies and proposal drafts, while `biblatex`
remains the machine-readable citation export.

Inspect vault health for an agent or for manual triage:

```fish
scholar-vault status --vault ~/Documents/Research/scholar-labs-vault
scholar-vault status --vault ~/Documents/Research/scholar-labs-vault --json
scholar-vault doctor --vault ~/Documents/Research/scholar-labs-vault
scholar-vault git-summary --vault ~/Documents/Research/scholar-labs-vault
scholar-vault maintenance-report --vault ~/Documents/Research/scholar-labs-vault
scholar-vault notes-missing --vault ~/Documents/Research/scholar-labs-vault --heading "PDF reading notes"
scholar-vault concept-index --vault ~/Documents/Research/scholar-labs-vault
scholar-vault query create --vault ~/Documents/Research/scholar-labs-vault "How do collaborative map workbenches support mobility decisions?" --project map-lens-deformation --slug collaborative-map-workbenches
scholar-vault query link-paper --vault ~/Documents/Research/scholar-labs-vault collaborative-map-workbenches Schottler2021_GeospatialNetworks
scholar-vault query link-run --vault ~/Documents/Research/scholar-labs-vault collaborative-map-workbenches 2026-05-01_mobility
scholar-vault query status --vault ~/Documents/Research/scholar-labs-vault collaborative-map-workbenches
scholar-vault bases rebuild --vault ~/Documents/Research/scholar-labs-vault
scholar-vault bases doctor --vault ~/Documents/Research/scholar-labs-vault --json
scholar-vault project ui --vault ~/Documents/Research/scholar-labs-vault
scholar-vault project scaffold --vault ~/Documents/Research/scholar-labs-vault map-lens-deformation
scholar-vault project link-paper --vault ~/Documents/Research/scholar-labs-vault map-lens-deformation Schottler2021_GeospatialNetworks
scholar-vault project link-proposal --vault ~/Documents/Research/scholar-labs-vault map-lens-deformation pepr-mobidec
scholar-vault project map --vault ~/Documents/Research/scholar-labs-vault map-lens-deformation
scholar-vault project audit --vault ~/Documents/Research/scholar-labs-vault map-lens-deformation
scholar-vault proposal-sprint scaffold --vault ~/Documents/Research/scholar-labs-vault pepr-mobidec
scholar-vault proposal-audit --vault ~/Documents/Research/scholar-labs-vault proposals/pepr-mobidec
scholar-vault proposal-audit --vault ~/Documents/Research/scholar-labs-vault proposals/pepr-mobidec --json
```

`status` and `doctor` are aliases. They are read-only and report card counts,
run counts, actionable metadata/citation/abstract/keyword issues, optional
candidate discovery counts, historical unmatched manifest entries, active
staging counts, topic noise, orphan PDFs, duplicate PDF hashes, and
duplicate-style filenames. `enrichment_status: missing` is a diagnostic state,
not necessarily a UI follow-up issue; `scholar-vault enrich --ui` shows only
actionable rows such as ambiguous metadata or missing keywords.

`maintenance-report` writes `_indexes/maintenance-report.md` and a dated
`tasks/<date>-maintenance.md` triage note. It composes the existing status,
PDF doctor, reading queue, enrichment, candidate backlog, staging, topic-noise,
concept, and synthesis checks without modifying paper cards or run data.
With `--write-queue`, it also writes typed maintenance queue items under
`tasks/queue/*.yaml` using stable keys so repeated reports do not duplicate the
same work.

`queue`, `operations`, `feedback`, and `tools-task` provide the typed
self-improvement substrate. Queue items live under `tasks/queue/`, operation
records live under `_operations/runs/` with an append-only `_operations/log.md`,
feedback ratings live under `_feedback/ratings/`, and `tools-task create`
creates `improve_tool` queue items for the `scholar-vault-tools` repo without
editing that repo.

`notes-missing` is read-only. It lists active, attached paper cards whose
`## Notes` section does not contain a requested subheading, for example
`### PDF reading notes`. Use it to build a reading queue for selected sources.

`concept-index` regenerates `_indexes/concepts.md` from durable concept cards
and refreshes `llms.txt` / `llms-full.txt` so future agents can find those
metacards without a full rebuild.

`query create` creates a durable `queries/<slug>.md` research-query note with
frontmatter for status, project, question, linked runs, linked papers, linked
syntheses, linked concepts, prompt packs, priority, and review state. Query
notes are not generated-only files; they are the Obsidian place to launch and
track a specific research question. Link sources with `query link-paper`, link
Scholar Labs provenance with `query link-run`, link outputs with
`query link-synthesis`, and inspect the workbench with `query show` or
`query status`.

A new query note starts with Obsidian Bases embeds:

```markdown
---
type: research_query
status: open
project: map-lens-deformation
question: How do collaborative map workbenches support mobility decisions?
linked_runs: []
linked_papers: []
linked_syntheses: []
linked_concepts: []
scholar_labs_prompt_pack: []
priority: normal
review_status: unreviewed
---

# How do collaborative map workbenches support mobility decisions?

## Workbench
![[bases/queries.base#Query outputs]]
![[bases/queries.base#Queries needing Scholar Labs]]
![[bases/papers.base#Needs reading]]
```

Open `queries/collaborative-map-workbenches.md` in Obsidian to work from the
question instead of from a daily note. The `Query outputs` view uses Obsidian
Bases `this.file` behavior when embedded, so files that link to the current
query note or list the current query path in `linked_queries` appear in the
view. If Obsidian changes active-file behavior, the explicit `linked_*`
frontmatter remains the fallback source of truth for CLI status and filtering.

`bases init` and `bases rebuild` write deterministic `.base` files under
`bases/`: `papers.base`, `queries.base`, `synthesis-workbench.base`,
`scholar-labs-workbench.base`, and `self-improvement.base`. `bases doctor`
validates the generated YAML and required view names without requiring Obsidian
to be open. No Dataview dependency is added. Paper-card frontmatter exposes the
workbench fields `reading_status`, `compiled_status`, `review_status`,
`last_read_at`, `last_compiled_at`, `evidence_level`, `linked_queries`, and
`linked_projects` for these views. Bases are a user-facing interface over
existing vault state, not an alternative canonical data model: PDFs and
`papers/*.md` remain canonical evidence records, query notes are durable
workbench notes, and `_indexes/` / `bases/` are deterministic navigation layers.

`project scaffold <slug>` creates `projects/<slug>/index.md`. A project is a
lightweight lens over shared papers, runs, concepts, syntheses, tasks, and
optional proposals. It does not create a separate vault and it should link to
paper cards instead of duplicating source content. Use `project link-paper`,
`project link-concept`, `project link-synthesis`, `project link-run`, and
`project link-task` to maintain the project frontmatter. Use `project
link-proposal` for proposal workspace links. `project map <slug>` writes
`projects/<slug>/project-map.md` with linked paper PDF, metadata, and
reading-note status, linked proposal paths, gaps, and next actions. `project
audit <slug>` is read-only and checks missing linked records, missing PDFs,
missing PDF reading notes, broken links, missing linked proposals, and stale
project maps.

Use `project ui` for a desktop workflow that lists existing projects and linkable
papers, runs, concepts, syntheses, tasks, and proposals with colored status
badges. It scaffolds or updates a project, links the selected resource,
generates the project map, runs the project audit, and opens the project note.
`project scaffold --ui ...` and `project link-paper --ui ...` open the same UI
with the project and target fields prefilled.

Use `projects/` for ongoing research workspaces, implementation planning, and
topic-specific lenses that need to gather shared vault records without copying
them. Use `proposals/` only for proposal-specific outlines, source matrices,
reading logs, raw idea cards, and draft evidence layers that should be audited
with `proposal-audit`.

`proposal-sprint scaffold <slug>` creates or updates
`proposals/<slug>/index.md`, `outline.md`, `source-matrix.md`,
`reading-log.md`, and `raw-idea.md`. New outlines include
`evidence_matrix: source-matrix.md`; you can point that field at a shared matrix
such as `syntheses/<matrix>.md`. The scaffold appends missing required sections
but does not replace existing proposal prose, then rebuilds derived navigation.

`proposal-audit` is read-only. It checks a proposal workspace for cited papers
without `### PDF reading notes`, read papers without `Proposal role: Core`,
`Proposal role: Supporting`, or `Proposal role: Discarded`, broken source-matrix
links, missing `Original User Notes - Verbatim` in the raw idea card, and draft
claims that still cite Scholar Labs summaries instead of PDF-grounded evidence.
In addition to `*matrix*.md` files inside the proposal folder, it follows
`evidence_matrix` / `evidence_matrices` frontmatter on outline files, so a
proposal can audit a shared source matrix under `syntheses/`.

Enrich canonical paper cards with citation metadata, abstracts, and publication keywords:

```fish
scholar-vault enrich --vault ~/Documents/Research/scholar-labs-vault
```

Useful enrichment variants:

```fish
scholar-vault enrich --vault ~/Documents/Research/scholar-labs-vault --citekey smith2024rag
scholar-vault enrich --vault ~/Documents/Research/scholar-labs-vault --only missing-doi
scholar-vault enrich --vault ~/Documents/Research/scholar-labs-vault --only missing-bibtex
scholar-vault enrich --vault ~/Documents/Research/scholar-labs-vault --only missing-abstract
scholar-vault enrich --vault ~/Documents/Research/scholar-labs-vault --only missing-keywords
scholar-vault enrich --vault ~/Documents/Research/scholar-labs-vault --refresh
scholar-vault enrich --vault ~/Documents/Research/scholar-labs-vault --refresh-abstracts
scholar-vault enrich --vault ~/Documents/Research/scholar-labs-vault --retry-failed
scholar-vault enrich --vault ~/Documents/Research/scholar-labs-vault --dry-run
```

`enrich` processes canonical `papers/*.md` cards only. By default it runs citation/DOI, abstract, and publication-keyword passes. Use `--only` as a filter when you want to focus on one queue. The older `enrich-citations` command remains available for citation-only scripts.

For citation metadata, the tool tries local DOI detection first, then cached provider lookups from Crossref, OpenAlex, Europe PMC, DataCite, and DOI content negotiation. Raw provider responses are cached under `raw/metadata/<citekey>/`. When a known DOI resolves to a preprint or repository record with incomplete venue metadata, enrichment may search for a strong published-version match and promote the published DOI and venue instead.

During processing, progress output reports local DOI/PDF scans, provider
attempts, candidate counts, skipped fallback passes, and final write decisions.
After the one-line count summary, the command prints compact grouped details for
generated, verified, incomplete, ambiguous, unresolved, and skipped records. Use
the GUI result browser when you want to filter those groups and open the
associated paper card or PDF:

```fish
scholar-vault enrich --ui
```

The command writes these frontmatter fields: `doi_status`, `doi_source`, `doi_confidence`, `citation_status`, `citation_source`, `citation_last_checked`, `citation_enriched_at`, `citation_input_fingerprint`, `citation_retries`, `citation_skip_reason`, `metadata_lock`, `enrichment_status`, `enrichment_missing`, and `enrichment_refresh`.

For a known manual citation fix, use the safe command path instead of
hand-editing enrichment frontmatter:

```fish
scholar-vault resolve-citation --citekey smith2024rag --doi 10.1145/example --authors "Jane Smith; John Doe" --year 2024 --venue "Example Venue"
scholar-vault resolve-citation --citekey smith2024rag --venue "Example Venue" --lock
```

`resolve-citation` is an alias of `set-metadata`. It updates DOI/citation
status, metadata completeness, fingerprints, and derived files through the same
rebuild path as the GUI manual resolver. For theses, reports, and other
non-article PDFs with no DOI or journal/conference venue, fill the known fields
and use `--lock` so the missing DOI/venue is accepted instead of repeatedly
surfacing as an enrichment issue.

Interpretation:

- `missing`: no DOI or generated citation has been found yet, or an older card
  still carries a stale completeness field before `rebuild` normalizes it. For
  `enrichment_status`, treat this as diagnostic rather than a manual issue by
  itself.
- `detected`: DOI was found locally in frontmatter, URLs, PDF metadata, or PDF text.
- `resolved`: a remote provider or DOI lookup accepted the DOI.
- `generated`: provider BibTeX/CSL metadata was generated but has not been manually verified.
- `verified`: DOI metadata and title/author/year consistency checks were strong.
- `ambiguous`: providers returned plausible but conflicting or weak candidates.
- `unresolved`: no acceptable DOI or citation metadata was found.
- `incomplete`: citation metadata was generated, but canonical fields such as `venue`, `authors`, `year`, or `doi` are still missing or still look like Scholar preview strings.

Set `metadata_lock: true` in a paper card to prevent automatic metadata overwrites. Use `--refresh` to reprocess generated or verified records, `--retry-failed` to retry unresolved records past the retry limit, and `--force` only when you intentionally want to process locked metadata. To mark one card for another normal enrichment attempt from Obsidian, set `enrichment_refresh: true` in that paper card and run `scholar-vault enrich`; the flag is cleared after processing.

Ambiguous citation rows in the GUI can be resolved with **Resolve Metadata**.
The workflow saves manually checked DOI, authors, year, venue, and URL values,
then rebuilds the generated card, indexes, exports, topics, and run notes. For
thesis/report/non-article PDFs, leave genuinely absent DOI or venue fields blank
and enable the metadata lock in the dialog. You can also do the same from the
CLI:

```fish
scholar-vault set-metadata --citekey smith2024rag --doi 10.1145/example --authors "Jane Smith; John Doe" --year 2024 --venue "Proceedings of Example Research"
```

To focus only on abstract enrichment, use `--only missing-abstract`:

```fish
scholar-vault enrich --vault ~/Documents/Research/scholar-labs-vault --only missing-abstract
scholar-vault enrich --vault ~/Documents/Research/scholar-labs-vault --citekey smith2024rag --only missing-abstract
scholar-vault enrich --vault ~/Documents/Research/scholar-labs-vault --refresh-abstracts
scholar-vault enrich --vault ~/Documents/Research/scholar-labs-vault --retry-failed --only missing-abstract
scholar-vault enrich --vault ~/Documents/Research/scholar-labs-vault --dry-run --only missing-abstract
```

The abstract is not the Scholar Labs summary. Scholar Labs summaries explain why the source appeared in a prompt result; abstracts are provider or PDF metadata and are stored in the `## Abstract` section of each paper card. Frontmatter keeps only abstract status, source, confidence, fingerprint, and lock metadata so agents do not read the same long abstract twice.

Abstract provider order is local DOI detection, Crossref REST metadata, OpenAlex reconstructed abstracts, Europe PMC fallback, DataCite descriptions, then local PDF text extraction. Crossref abstracts may include JATS/XML markup, which the tool strips before writing the card. OpenAlex abstracts are reconstructed from `abstract_inverted_index`. The tool never uses LLM summarization or Scholar Labs summaries as abstracts.

Abstract enrichment rejects ellipsis-truncated snippets such as `Movem...` or `…` as incomplete abstracts. Existing resolved/verified cards with truncated abstracts are retried instead of skipped; if no complete provider or PDF abstract can be found, the bad abstract is removed and the card is marked unresolved for manual follow-up.

Abstract enrichment writes the `## Abstract` section plus these frontmatter fields: `abstract_status`, `abstract_source`, `abstract_source_url`, `abstract_confidence`, `abstract_last_checked`, `abstract_enriched_at`, `abstract_input_fingerprint`, and `abstract_lock`.
The `--ui` follow-up window shows only actionable abstract/citation/keyword problems. Skipped rows such as `abstract fingerprint unchanged`, `abstract present`, or `citation verified` are normal non-actions and are not counted as issues.
Paper keywords are written to `keywords` frontmatter and the `## Keywords` section when available. PDF keyword extraction recognizes both `Keywords` and `Index Terms` labels, and accepts common separators such as commas, semicolons, pipes, middle dots, and bullets. To retry attached PDFs that have no captured keywords, run:

```fish
scholar-vault enrich --vault ~/Documents/Research/scholar-labs-vault --only missing-keywords
```

If automatic PDF keyword extraction still finds nothing, GUI follow-up shows a keywords issue row like a missing abstract. You can also set keywords from the CLI:

```fish
scholar-vault set-keywords --citekey smith2024rag --text "Immersive Analytics; Collaboration; Usability Study"
```

When the GUI saves a manually entered abstract or keywords, it shows each
save stage: text cleanup, card write, derived index rebuild, exports, topic
pages, run notes, and follow-up refresh.

Interpretation:

- `missing`: no abstract has been found yet.
- `resolved`: an abstract was accepted from a provider or local PDF extraction.
- `verified`: DOI/title/author/year consistency was strong for the accepted abstract source.
- `ambiguous`: strong sources disagreed or the match was not safe enough to overwrite.
- `unresolved`: no acceptable abstract was found.
- `manual_lock`: the abstract should not be changed automatically.

Set `abstract_lock: true` to protect a manually curated abstract. Previously
unresolved or ambiguous abstracts are tried again on later abstract enrichment
runs instead of being skipped as stale failures. Use `--refresh-abstracts` to
deliberately re-check resolved or verified abstracts, including upgrades from
weak sources such as `pdf_extracted` to stronger sources such as Crossref. Use
`--force` only when you intentionally want to process locked abstract metadata.

To add a manual abstract without editing YAML by hand, put the abstract in a
plain text file and run:

```fish
scholar-vault set-abstract --citekey smith2024rag --file ~/Downloads/abstract.txt --source-url https://doi.org/10.1145/example
```

This writes the `## Abstract` section, marks `abstract_source: manual`, sets
`abstract_status: manual_lock`, and enables `abstract_lock: true` by default.
Use `--no-lock` only if you want later automatic abstract enrichment to be able
to replace it.

In `import-labs --ui` follow-up windows, missing-abstract issues can be resolved
directly: the tool opens the PDF, shows a paste field for text copied from
Preview or another PDF reader, repairs common PDF line breaks and hyphenated
line wraps, then saves the result through the same locked manual-abstract path.

List previous Scholar Labs runs when you need to find a run ID for `resume`,
`rerun`, `rename-run`, or `undo`:

```fish
scholar-vault runs
scholar-vault runs --limit 10
```

`list-runs` is an alias. Once shell completion is installed, `--run` values are
completed from the configured vault, so `scholar-vault rerun --run <tab>` shows
recorded run IDs.

For the desktop workflow, omit `--run` and pass `--ui` to choose from a run
browser with run IDs, titles, full prompts, exported dates, result counts,
selected-paper counts, follow-up issue summaries, and staged-PDF history:

```fish
scholar-vault rerun --ui
```

Resume a previous run using the export and staging folder already recorded in `runs/<run_id>/index.yaml`:

```fish
scholar-vault resume --vault ~/Documents/Research/scholar-labs-vault --run 2026-04-22_example-prompt
```

Rerun the most recent Scholar Labs import after adding more PDFs to the staging folder:

```fish
scholar-vault rerun --vault ~/Documents/Research/scholar-labs-vault --commit
```

Rerun a specific run if needed:

```fish
scholar-vault rerun --vault ~/Documents/Research/scholar-labs-vault --run 2026-04-22_example-prompt --commit
```

If your staging folder has leftover PDFs and you are not sure which Scholar
Labs run requested them, search all previous run results and attach the exact
PDF to the matching result:

```fish
scholar-vault pdf-doctor --vault ~/Documents/Research/scholar-labs-vault --staging ~/Downloads/scholar-labs-staging
scholar-vault pdf-doctor --vault ~/Documents/Research/scholar-labs-vault --staging ~/Downloads/scholar-labs-staging --json
scholar-vault match-staging --vault ~/Documents/Research/scholar-labs-vault --staging ~/Downloads/scholar-labs-staging
scholar-vault match-staging --title "Origin-destination flow data smoothing and mapping"
scholar-vault match-staging --pdf ~/Downloads/scholar-labs-staging/example.pdf --unselected-only
scholar-vault match-staging --ui
```

`pdf-doctor` is read-only. It reports orphan vault PDFs, missing card PDF files,
duplicate PDF hashes, duplicate-style names such as `-2.pdf`, repeated
unmatched files in import manifests, and staged files already present in the
vault by hash. If staging is empty, or every staged PDF is already a vault
duplicate, the historical unmatched entries do not require more matching work.
The `match-staging` terminal form is also read-only. It shows the best
run/result candidates. With `--ui`, the staging matcher opens a desktop search
window where you can scan all staged PDFs, choose a single PDF, type a title,
or combine a typed title with a chosen PDF path. In that combined mode, the
title searches previous Scholar Labs run results and the PDF path is the file
to import. Click `Import PDF` on the correct row to create/update the paper
card, copy the PDF into `pdfs/`, archive the staging original after verifying
the copy, update the run manifest, and run citation, abstract, and keyword
enrichment for the touched card. If a GUI import finishes with PDFs still in
staging, the run report offers the same leftover-PDF search directly. Once a
PDF is accepted for a paper card, other previous runs that mention the same
Scholar CID or normalized title are updated to point at the attached card.

If a selected paper already has a PDF but you later download a better
publisher/full-text version into staging, `import-labs`, `resume`, and `rerun`
check staged PDFs against already attached cards by default. They open the
match-review UI before replacing a canonical attachment; use
`--keep-existing-pdfs` when you only want to attach PDFs for still-unmatched
results.

```fish
scholar-vault rerun --vault ~/Documents/Research/scholar-labs-vault --run 2026-04-22_example-prompt --ui
```

Rename an existing run note for Obsidian Graph:

```fish
scholar-vault rename-run --vault ~/Documents/Research/scholar-labs-vault --run 2026-04-22_example-prompt --title "Immersive Analytics Sources"
```

You can also rename the generated run note directly in Obsidian. On the next
`scholar-vault rebuild`, the tool records that exact filename in
`runs/<run_id>/index.yaml` as `note_file` and updates paper-card links such as
`discovered_in` and `summary_sources`. Editing only the `title:` property also
works, but the filename is what Obsidian Graph and the sidebar display most
prominently.

Undo a run using its import manifest:

```fish
scholar-vault undo --vault ~/Documents/Research/scholar-labs-vault --run 2026-04-22_example-prompt
```

Attach a PDF to an existing citekey:

```fish
scholar-vault attach-pdf --vault ~/Documents/Research/scholar-labs-vault --citekey smith2024rag --pdf ~/Downloads/scholar-labs-staging/example.pdf
```

List PDFs that still need a match:

```fish
scholar-vault unmatched --vault ~/Documents/Research/scholar-labs-vault
```

Archive staging PDFs that already exist in the vault:

```fish
scholar-vault clean-staging --vault ~/Documents/Research/scholar-labs-vault --staging ~/Downloads/scholar-labs-staging
```

Clean up an old run that accidentally created paper cards for every candidate result:

```fish
scholar-vault cleanup-run --vault ~/Documents/Research/scholar-labs-vault --run 2026-04-22_example-prompt --selected-only
```

Inspect or batch-clean topic labels:

```fish
scholar-vault topic-map --vault ~/Documents/Research/scholar-labs-vault
scholar-vault topic-map --vault ~/Documents/Research/scholar-labs-vault --json
scholar-vault topic-map --vault ~/Documents/Research/scholar-labs-vault --preset prompt-boilerplate
scholar-vault topic-map --vault ~/Documents/Research/scholar-labs-vault --preset prompt-boilerplate --apply
scholar-vault topic-map --vault ~/Documents/Research/scholar-labs-vault --mapping ~/Downloads/topic-map.yaml
scholar-vault topic-map --vault ~/Documents/Research/scholar-labs-vault --mapping ~/Downloads/topic-map.yaml --apply
```

The mapping file is YAML. Values can be a replacement string, a list of
replacement labels, or `null` to remove a noisy label:

```yaml
Find: null
Papers: null
That: null
OD Flows: Origin-Destination Flows
Mobility:
  - Urban Mobility
  - Transport Analytics
```

Reset the vault to the same clean state produced by `init`:

```fish
scholar-vault reset --vault ~/Documents/Research/scholar-labs-vault
```

Skip the confirmation prompt:

```fish
scholar-vault reset --vault ~/Documents/Research/scholar-labs-vault --yes
```

`reset` only clears vault-managed state inside the vault itself. It does not touch your external download folders such as `~/Downloads/scholar-labs-staging` or `~/Downloads/scholar-labs-exports`.

## Codex Agent Skills

This repository includes optional repository-owned vault-agent Codex skills
under `vault-agent-skills/` for post-import vault refinement. It also keeps
`VAULT_AGENTS_TEMPLATE.md` as the source for the vault-local `AGENTS.md` guide.
The repository root `AGENTS.md` is for agents working on this tools repo, not
for agents working inside a research vault. Keep those surfaces separate:
`vault-agent-skills/` is published into a vault's `.agents/skills/`, while this
repository's own `.agents/skills/` path is reserved for future tools-repo
development skills.

Kepano's Obsidian skills are useful in Scholar Vaults, but they are external
upstream content from `https://github.com/kepano/obsidian-skills`, not
repository-owned skills. Do not copy that repository into `vault-agent-skills/`
or adopt it back into this repository. Install or update external skill sources
from upstream with the dedicated commands below.

The safer workflow is to compare first, adopt any useful vault-side changes
back into this repository, then publish from the repository into the vault.
In this workflow, **source** means this repository's canonical
`vault-agent-skills/` folder plus `VAULT_AGENTS_TEMPLATE.md`, and **target**
means the vault's installed `.agents/skills/` folder plus vault `AGENTS.md`.
If you changed a skill or the vault guide template in this repository and want
the vault to use it, update the target by publishing source to target. If a
Codex session inside the vault changed a skill or vault `AGENTS.md` and you
want to preserve that change in this repository, adopt target to source.

```fish
scholar-vault skills diff --vault ~/Documents/Research/scholar-labs-vault
scholar-vault skills ui --vault ~/Documents/Research/scholar-labs-vault
```

If a Codex session in the vault created a useful new or changed skill, adopt it
back into the repository source of truth:

```fish
scholar-vault skills adopt scholar-vault-proposal-evidence-sprint \
  --vault ~/Documents/Research/scholar-labs-vault

# Dry-run by default. Add --apply to copy:
scholar-vault skills adopt scholar-vault-proposal-evidence-sprint \
  --vault ~/Documents/Research/scholar-labs-vault \
  --apply
```

To adopt intentional vault-local `AGENTS.md` edits back into
`VAULT_AGENTS_TEMPLATE.md`, use the special item name `AGENTS.md`:

```fish
scholar-vault skills adopt AGENTS.md \
  --vault ~/Documents/Research/scholar-labs-vault \
  --apply \
  --force
```

If the same skill exists on both sides and differs, `adopt` asks for
`--force` before overwriting the repository copy. The overwritten source skill
is backed up under `vault-agent-skills/.sync-backups/`.

Then publish repository skills and the vault AGENTS guide template to the vault:

```fish
scholar-vault skills publish --vault ~/Documents/Research/scholar-labs-vault

# Dry-run by default. Add --apply to copy:
scholar-vault skills publish --vault ~/Documents/Research/scholar-labs-vault --apply
```

Install or update externally managed skills separately. `obsidian-skills` is a
built-in source name for Kepano's repository:

```fish
scholar-vault skills install-external obsidian-skills --vault ~/Documents/Research/scholar-labs-vault

# Dry-run by default. Add --apply to clone from upstream and copy into the vault:
scholar-vault skills install-external obsidian-skills --vault ~/Documents/Research/scholar-labs-vault --apply

# Re-run later to update from the same upstream:
scholar-vault skills update-external obsidian-skills --vault ~/Documents/Research/scholar-labs-vault --apply

# Convenience aliases for the same built-in source:
scholar-vault skills install-obsidian --vault ~/Documents/Research/scholar-labs-vault --apply
scholar-vault skills update-obsidian --vault ~/Documents/Research/scholar-labs-vault --apply
```

Additional external sources use the same command shape:

```fish
scholar-vault skills install-external my-source \
  --repository https://example.com/skills.git \
  --skills-subdir skills \
  --vault ~/Documents/Research/scholar-labs-vault \
  --apply
```

External install/update commands write a small manifest under the vault's
`.agents/skills/.external-sources/` folder. Normal `skills diff` and
`skills publish --archive-extra` ignore externally managed skill names from
those manifests, so they are not mistaken for vault-only skills that should be
adopted into this repository or archived.

`publish` does not remove vault-only skills by default. If you intentionally
want the vault to stop carrying target-only skills, use `--archive-extra`; this
moves them into `.sync-backups/` instead of deleting them.

In the UI, use the single `Skill and AGENTS differences` list. Select the
skills or guide row you want to copy; the buttons decide the direction.
`Update Vault From Repository` copies selected repository-side changes
into the vault, while `Pull Selected Into Repository` copies selected
vault-side changes back into this repo. Deselect all rows to disable both copy
buttons. The same UI also has an `External skill sources` section: use
the `Built-in` menu to select `obsidian-skills` and fill the visible
source and repository fields, or enter another source name with `Repository`,
then preview or install/update that external source into the vault target. Use
the `Advanced...` dialog only when you need a non-default Git ref or skills
subdirectory.
Changed rows show modification-time hints such as repository newer or vault
newer. Treat those as useful guidance, not proof of intent: publishing still
explicitly updates the vault from this repository, while pulling still
explicitly updates this repository from the vault.

For shell-script wrappers, use:

```fish
scripts/skills_diff.sh --vault ~/Documents/Research/scholar-labs-vault
scripts/skills_ui.sh --vault ~/Documents/Research/scholar-labs-vault
scripts/skills_adopt.sh <skill-name> --vault ~/Documents/Research/scholar-labs-vault --apply
scripts/skills_publish.sh --vault ~/Documents/Research/scholar-labs-vault --apply
```

Verify the install:

```fish
find ~/Documents/Research/scholar-labs-vault/.agents/skills -maxdepth 2 -name SKILL.md -print
```

Then open a new Codex session with the vault as the project folder:

```fish
cd ~/Documents/Research/scholar-labs-vault
```

When a vault-side Codex task needs the CLI, first run commands from an active
environment:

```fish
conda activate scholar-vault
scholar-vault runs
```

If that Codex shell does not have Conda activation initialized, use:

```fish
/Users/MadMax/miniforge3/condabin/conda run -n scholar-vault scholar-vault runs
```

If a Codex session was already open on the vault, restart it or open a fresh
session so `.agents/skills/` is scanned.

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

### Post-Import Research Loop

After `import-labs`, `enrich --ui`, and any obvious metadata follow-up, the
normal research workflow is:

1. Use `$scholar-vault-research-loop` with a focused question, concept, method,
   dataset, or paper cluster.
2. Let Codex orient from `llms.txt`, `_indexes/dashboard.md`, relevant
   `projects/`, relevant `concepts/`, relevant `syntheses/`, and then focused
   paper cards.
3. Use `scholar-vault maintenance-report` for a broad triage pass when the
   next work item is unclear.
4. Use `scholar-vault notes-missing --heading "PDF reading notes"` when you
   need a concrete queue of selected cards that have not yet received PDF
   reading notes.
5. Use `scholar-vault compile status --json` or
   `scholar-vault compile queue --project <slug> --json` when you need the
   reusable single-paper digest queue.
6. Read the linked PDFs as primary evidence. Text extraction should cover the
   full paper for serious reading; page ranges are only for targeted revisits.
7. Use Codex's PDF reading/rendering capabilities for figures, tables, maps,
   visualizations, equations, scanned pages, and appendix material. Do not rely
   on text extraction alone for visual evidence.
8. Use `$scholar-vault-compile-paper` when one paper should become a reusable
   `paper-digests/<citekey>.md` artifact for future syntheses, concepts,
   queries, projects, or proposals.
9. Update only touched paper cards with concise `## Notes` that capture claims,
   methods, datasets, evaluation setup, limitations, visual encodings, and
   links to related paper cards.
10. Create `concepts/<slug>.md` for reusable concepts, methods, algorithms,
   datasets, evaluation protocols, terminology, or visual encodings that
   connect multiple papers.
11. Create `syntheses/<slug>.md` for evidence-backed cross-paper answers,
   tensions, and literature-review prose.
12. Create `tasks/<date>-research-gaps.md` for open questions, unclear
   evidence, gaps, follow-up reading, or next Scholar Labs prompts.
13. For question-centered work, use `queries/<slug>.md` as the workbench note
   and link papers, runs, and syntheses with `scholar-vault query link-*`.
14. For ongoing workspaces, use `projects/<slug>/index.md` as a lens over
   shared papers, runs, concepts, syntheses, tasks, and optional proposals.
   Link to the shared records instead of copying paper cards into the project.
15. For proposal workspaces, start with
   `scholar-vault proposal-sprint scaffold <slug>`, then run
   `scholar-vault proposal-audit proposals/<slug>` before treating the draft
   evidence layer as ready. Do not treat proposal workflows as the primary
   workflow for all vault work.
16. Run `scholar-vault concept-index` after concept-only edits, or
   `scholar-vault rebuild` after broader paper, topic, synthesis, task, or
   project/proposal edits, so generated context files include the new durable
   notes and connections.

### Paper Compile Digests

`paper-digests/<citekey>.md` files are durable user/agent-authored artifacts
for reusable single-paper understanding. The CLI scaffolds, tracks, validates,
and indexes them; it does not read PDFs or generate scientific claims.

```fish
scholar-vault compile status --json
scholar-vault compile scaffold --citekey <citekey>
scholar-vault compile scaffold --run <run-id> --selected-only
scholar-vault compile queue --project <slug> --json
scholar-vault compile mark <citekey> --status compiled
scholar-vault compile doctor --json
```

Scaffolding is idempotent and will not overwrite an existing digest unless
`--force` is passed. Mark a digest `stale` when the paper, a linked query, a
linked project, or an interpretation changes and the digest needs review.

## Generated Records

- `pdfs/*.pdf`: canonical evidence artifacts for selected sources.
- `papers/*.md`: canonical source cards for selected papers by default; these store metadata, provenance, links, abstracts, keywords, and notes over the linked PDFs.
- `paper-digests/*.md`: durable PDF-grounded single-paper digests for reuse in
  syntheses, concept pages, query dossiers, project work, and proposal audits.
- `concepts/*.md`: optional agent-written concept/metacards that connect papers by method, dataset, visual encoding, evaluation protocol, or terminology.
- `syntheses/*.md`: optional agent-written cross-paper syntheses grounded in PDFs.
- `tasks/*.md`: optional agent-written follow-up tasks and research gaps.
- `queries/*.md`: durable research-query workbench notes with linked papers, runs, syntheses, concepts, prompt packs, and Obsidian Bases embeds.
- `projects/<slug>/index.md`: optional project lens over shared papers, runs, concepts, syntheses, tasks, and proposals.
- `projects/<slug>/project-map.md`: generated project map summarizing linked record status, gaps, and next actions.
- `proposals/*.md` or `proposals/<slug>/*.md`: optional proposal workspaces, outlines, source matrices, and draft evidence layers.
- `papers/*.md` body sections: human-readable keywords, abstract, and primary Scholar Labs summary. Long prose is not duplicated in frontmatter.
- `runs/<run_id>/<Short Title.md>`: Obsidian-friendly per-run provenance pages that keep all Scholar Labs candidate results.
- `runs/*/index.yaml`: machine-readable run records used by `resume`, `rerun`, and rebuilds.
- `runs/*/import-manifest.yaml`: transactional record of proposed matches, decisions, copied PDFs, and created cards.
- `raw/metadata/<citekey>/`: cached citation provider responses and generated citation artifacts.
- `raw/metadata/<citekey>/citation.bib` and `citation.csl.json`: preferred provider-backed sources for one-card and whole-library BibLaTeX export.
- `topics/*.md`: simple topic pages derived from prompt keywords and rationale labels.
- `_indexes/*.md`: navigation and maintenance views.
- `bases/*.base`: generated Obsidian Bases workbench views over existing vault state.
- `llms.txt` and `llms-full.txt`: short and expanded agent navigation summaries.
- `_exports/library.*`: plain-file exports for Zotero migration or other tools.

## Git workflow for the vault

Rebuilds can produce large but expected diffs. Treat the vault as a mix of
canonical records and generated views:

- Commit canonical changes when they reflect intentional work: `papers/`,
  `paper-digests/`, `pdfs/`, `raw/`, run YAML/manifests under `runs/`, and durable notes under
  `concepts/`, `syntheses/`, `tasks/`, `queries/`, `projects/`, and
  `proposals/`.
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
