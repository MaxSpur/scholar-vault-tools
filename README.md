# scholar-vault

`scholar-vault` is a local-first research source wiki. The canonical record for a source is a Markdown card under `papers/`, not a database row and not a browser export. Scholar Labs is the first ingestion adapter, but direct PDFs, BibTeX, DOI imports, and manual notes all converge on the same paper card format.

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

From Fish, install tab completion for command names, options, and vault-backed
values such as run IDs:

```fish
scholar-vault install-fish-completion
exec fish
```

This writes `~/.config/fish/completions/scholar-vault.fish` directly, avoiding
Typer shell-detection issues. Use `scholar-vault show-fish-completion` if you
want to inspect the generated completion script instead of installing it.

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
scholar-vault rerun --commit
scholar-vault status
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
  runs/
  topics/
  _indexes/
    prompts.md
    papers.md
    topics.md
    missing-pdfs.md
    unmatched.md
    zotero-migration.md
  _exports/
    library.bib
    library.json
    library.csl.json
```

`init` does not install Codex skills. The optional project-local agent skills
from this repository can be copied into `.agents/skills/` later; see
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
scholar-vault rerun --ui
```

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
- Canonical `papers/*.md` cards are created only for results with matched PDFs.
- If a later Scholar Labs run returns a paper that already has a canonical card and attached PDF, the run links to the existing card and adds that run's summary to the card instead of creating a duplicate.
- Candidate results stay on the run page unless you explicitly opt in with `--include-without-pdf`.
- `import-labs` copies accepted PDFs into `pdfs/`, verifies them, and then archives the matched originals out of staging into `raw/imported/`, leaving only unmatched PDFs in staging.
- `_indexes/missing-pdfs.md` is an optional candidate discovery backlog, not a maintenance defect list. In the normal workflow it mostly means "Scholar Labs suggested these, but you did not download/import them."
- `_indexes/unmatched.md` is a historical manifest audit of staged PDFs that were not accepted during specific imports. Rows may repeat across runs and are actionable only when the file still exists in staging and is not already a duplicate of a vault PDF.
- After committed matches, `import-labs`, `import`, `resume`, and `rerun` run citation, abstract, and PDF keyword enrichment for selected paper cards by default. Use `--no-enrich` when you want a faster import that skips provider lookups.
- Paper-provided keywords from BibTeX, provider metadata, and local PDF text are stored separately from prompt-derived `topics`. If a paper has no publication keywords or index terms, the follow-up UI can mark that absence explicitly so the card no longer looks unfinished.
- When a PDF is attached to a canonical card, matching previous run results with the same Scholar CID or exact normalized title are linked to that same card. `rebuild` also repairs missing run/card/PDF links for older stale records.
- After a successful non-dry-run import, `import-labs` moves the used JSON export into a sibling `used/` folder without renaming it, for example `~/Downloads/scholar-labs-staging/used/example.json`. The run metadata is updated so `resume` and `rerun` still know where the export went.
- The final import summary separates reused prior selections, existing vault-card links, newly accepted staged PDFs, review prompts, unresolved results, staged-file cleanup, and enrichment changes, so rerunning an old JSON should make clear why no match-review prompts appeared.
- `import-run` is the lower-level transactional variant. It copies accepted PDFs into `pdfs/` but leaves staging untouched unless you later run `clean-staging`.
- Most commands that accept `--vault`, and commands that accept `--staging`, can use configured defaults when those options are omitted.
- Import and enrichment commands show terminal progress while scanning PDFs, matching results, querying metadata providers, and rebuilding derived files. Enrichment logs include per-pass attempt/result/skip lines for local DOI/PDF scans and provider lookups.
- Staged PDF scan results are cached in `.scholar-vault-pdf-scan-cache` inside the staging folder. Repeated imports reuse cached title, DOI, year, text, and hash data when a PDF's size and modification time are unchanged.
- `match-staging --ui` rows can open the staged PDF directly. Rows already attached to a vault card can also open the card or move the redundant staging copy into `staging/trash/`.

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

1. Drop PDFs into `~/Downloads/scholar-labs-staging`.
2. Run:

```fish
scholar-vault import-pdf --vault ~/Documents/Research/scholar-labs-vault --staging ~/Downloads/scholar-labs-staging
```

The importer extracts metadata where possible, renames and moves PDFs into `pdfs/`, creates source cards, and flags incomplete metadata in `_indexes/unmatched.md`.

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

Regenerate BibTeX only:

```fish
scholar-vault bibtex --vault ~/Documents/Research/scholar-labs-vault
```

Inspect vault health for an agent or for manual triage:

```fish
scholar-vault status --vault ~/Documents/Research/scholar-labs-vault
scholar-vault status --vault ~/Documents/Research/scholar-labs-vault --json
scholar-vault doctor --vault ~/Documents/Research/scholar-labs-vault
```

`status` and `doctor` are aliases. They are read-only and report card counts,
run counts, actionable metadata/citation/abstract/keyword issues, optional
candidate discovery counts, historical unmatched manifest entries, active
staging counts, topic noise, orphan PDFs, duplicate PDF hashes, and
duplicate-style filenames. `enrichment_status: missing` is a diagnostic state,
not necessarily a UI follow-up issue; `scholar-vault enrich --ui` shows only
actionable rows such as ambiguous metadata or missing keywords.

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
rebuild path as the GUI manual resolver.

Interpretation:

- `missing`: no DOI or generated citation has been found yet, or an older card
  still carries a stale completeness field before `rebuild` normalizes it. For
  `enrichment_status`, treat this as diagnostic rather than a manual issue by
  itself.
- `detected`: DOI was found locally in frontmatter, URLs, PDF metadata, or PDF text.
- `resolved`: a remote provider or DOI lookup accepted the DOI.
- `generated`: BibTeX/CSL metadata was generated but has not been manually verified.
- `verified`: DOI metadata and title/author/year consistency checks were strong.
- `ambiguous`: providers returned plausible but conflicting or weak candidates.
- `unresolved`: no acceptable DOI or citation metadata was found.
- `incomplete`: citation metadata was generated, but canonical fields such as `venue`, `authors`, `year`, or `doi` are still missing or still look like Scholar preview strings.

Set `metadata_lock: true` in a paper card to prevent automatic metadata overwrites. Use `--refresh` to reprocess generated or verified records, `--retry-failed` to retry unresolved records past the retry limit, and `--force` only when you intentionally want to process locked metadata. To mark one card for another normal enrichment attempt from Obsidian, set `enrichment_refresh: true` in that paper card and run `scholar-vault enrich`; the flag is cleared after processing.

Ambiguous citation rows in the GUI can be resolved with **Resolve Metadata**.
The workflow saves manually checked DOI, authors, year, venue, and URL values,
then rebuilds the generated card, indexes, exports, topics, and run notes. You
can also do the same from the CLI:

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
Labs run they came from, search all previous run results before choosing a run
to rerun:

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
run/result candidates and the `rerun --run ... --ui` command to use when you
want the normal match-review workflow to import a remaining non-duplicate
staged PDF. With `--ui`, the staging matcher opens a desktop search window
where you can scan all staged PDFs, choose a single PDF, or type a title;
clicking `Rerun` starts the normal reviewed import workflow for that run. If a
GUI import finishes with PDFs still in staging, the run report offers the same
leftover-PDF search directly. Once a PDF is accepted for a paper card, other
previous runs that mention the same Scholar CID or normalized title are updated
to point at the attached card.

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

This repository includes optional Codex skills under `.agents/skills/` for
post-import vault refinement. They are not part of the generated vault by
default; copy them into the vault when you want to start a Codex project there.

```fish
set src ~/Developer/scholar-vault-tools/.agents/skills
set vault ~/Documents/Research/scholar-labs-vault

mkdir -p $vault/.agents/skills
rsync -a $src/ $vault/.agents/skills/
```

Rerunning the same `rsync -a $src/ $vault/.agents/skills/` command updates and
overwrites files with the same names and adds new skill files. It does not
remove old files that no longer exist in the source. Use `rsync -a --delete
$src/ $vault/.agents/skills/` only if the vault skill folder contains no
vault-local skills you want to keep.

Verify the install:

```fish
find $vault/.agents/skills -maxdepth 2 -name SKILL.md -print
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
  `syntheses/` from canonical paper cards and run provenance.
- `$scholar-vault-refine-card`: safely improve `papers/*.md` notes and safe
  metadata while preserving generated sections, enrichment state, locks, and
  provenance.
- `$scholar-vault-curate-topics`: clean noisy prompt-derived `topics`
  frontmatter, then rebuild derived topic pages and indexes.
- `$scholar-vault-pdf-triage`: inspect orphan, duplicate, unmatched, and
  staged PDFs, then choose safe CLI repair workflows.
- `$scholar-vault-gap-scout`: write `tasks/<date>-research-gaps.md` with next
  active staging, metadata, import, and synthesis actions.

Example prompts:

```text
Use $scholar-vault-orient to map the current vault state.
Use $scholar-vault-gap-scout to identify the next import and metadata gaps.
Use $scholar-vault-synthesize to write a synthesis on OD-flow visualization.
Use $scholar-vault-curate-topics to propose a cleanup of noisy topics.
Use $scholar-vault-pdf-triage to inspect current staging PDFs and historical unmatched records.
```

The skills do not require subagents and do not launch them by themselves. That
is intentional: they should work in a normal single-agent Codex session and in
environments where subagent tools are unavailable. For large vault refinement
tasks, subagents can still be useful for parallel read-only exploration or
independent verification when the active Codex environment and user instructions
allow them, but final synthesis and file edits should stay coordinated in the
main thread.

## Generated Records

- `papers/*.md`: canonical source cards for selected papers by default.
- `papers/*.md` body sections: human-readable keywords, abstract, and primary Scholar Labs summary. Long prose is not duplicated in frontmatter.
- `runs/<run_id>/<Short Title.md>`: Obsidian-friendly per-run provenance pages that keep all Scholar Labs candidate results.
- `runs/*/index.yaml`: machine-readable run records used by `resume`, `rerun`, and rebuilds.
- `runs/*/import-manifest.yaml`: transactional record of proposed matches, decisions, copied PDFs, and created cards.
- `raw/metadata/<citekey>/`: cached citation provider responses and generated citation artifacts.
- `topics/*.md`: simple topic pages derived from prompt keywords and rationale labels.
- `_indexes/*.md`: navigation and maintenance views.
- `llms.txt` and `llms-full.txt`: short and expanded agent navigation summaries.
- `_exports/library.*`: plain-file exports for Zotero migration or other tools.

## Verification

After implementation or local changes, run:

```fish
python -m pytest
python -m ruff check .
python -m pip install -e .
scholar-vault init --vault ~/Documents/Research/scholar-labs-vault
```
