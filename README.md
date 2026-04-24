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

Run the test suite if you are developing the tool:

```fish
python -m pytest
python -m ruff check .
```

If Fish cannot find `scholar-vault`, confirm that `conda activate
scholar-vault` succeeded, then reinstall from the repository folder with
`python -m pip install -e .`.

## Configure Default Paths

Store your normal project paths once so routine commands can omit them:

```fish
scholar-vault configure \
  --code ~/Developer/scholar-vault-tools \
  --vault ~/Documents/Research/scholar-labs-vault \
  --staging ~/Downloads/scholar-labs-staging
```

The defaults are written to `~/.config/scholar-vault/config.yaml`. Run
`scholar-vault configure` without options to inspect the current values.
Explicit command-line paths always override configured defaults.
You may also configure a separate `--exports` folder, but it is optional:
`import-labs` can use the staging folder for both PDFs and Scholar Labs JSON
exports.

With defaults configured, commands can be shorter:

```fish
scholar-vault import-labs --commit
scholar-vault import-pdf
scholar-vault rerun --commit
scholar-vault rebuild
scholar-vault enrich-citations --abstracts
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
- After committed matches, `import-labs`, `import`, `resume`, and `rerun` run citation and abstract enrichment for selected paper cards by default. Use `--no-enrich` when you want a faster import that skips provider lookups.
- After a successful non-dry-run import, `import-labs` moves the used JSON export into a sibling `used/` folder without renaming it, for example `~/Downloads/scholar-labs-staging/used/example.json`. The run metadata is updated so `resume` and `rerun` still know where the export went.
- `import-run` is the lower-level transactional variant. It copies accepted PDFs into `pdfs/` but leaves staging untouched unless you later run `clean-staging`.
- Most commands that accept `--vault`, and commands that accept `--staging`, can use configured defaults when those options are omitted.
- Import and enrichment commands show terminal progress while scanning PDFs, matching results, querying metadata providers, and rebuilding derived files.

Run notes are written as `runs/<run_id>/<Short Title.md>` instead of
`index.md`. This gives Obsidian Graph and the file sidebar meaningful run/prompt
nodes. Each run note has frontmatter `type: scholar_labs_run`, `title`,
`note_file`, and tag `scholar-vault/run`, so Graph groups can color prompts
separately from paper cards. If you do not provide a title, `scholar-vault`
infers a short title from the prompt topic.

Dry-run the import without creating paper cards or copying PDFs:

```fish
scholar-vault import-labs --vault ~/Documents/Research/scholar-labs-vault --export ~/Downloads/scholar-labs-exports/example.json --staging ~/Downloads/scholar-labs-staging --dry-run
```

Auto-commit only high-confidence matches:

```fish
scholar-vault import-labs --vault ~/Documents/Research/scholar-labs-vault --export ~/Downloads/scholar-labs-exports/example.json --staging ~/Downloads/scholar-labs-staging --commit
```

Skip automatic citation and abstract enrichment if you only want to match and archive PDFs:

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
After matching, GUI imports keep a small progress window open for citation and
abstract enrichment. If enrichment leaves records incomplete, ambiguous, or
unresolved, a follow-up browser opens with the affected cards and quick actions
to open the paper card or attached PDF.
If GUI dependencies are unavailable in the current environment, the command
falls back to terminal prompts.

Set a short Obsidian run title during import:

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

Enrich canonical paper cards with DOI and citation metadata:

```fish
scholar-vault enrich-citations --vault ~/Documents/Research/scholar-labs-vault
```

Useful enrichment variants:

```fish
scholar-vault enrich-citations --vault ~/Documents/Research/scholar-labs-vault --citekey smith2024rag
scholar-vault enrich-citations --vault ~/Documents/Research/scholar-labs-vault --only missing-doi
scholar-vault enrich-citations --vault ~/Documents/Research/scholar-labs-vault --only missing-bibtex
scholar-vault enrich-citations --vault ~/Documents/Research/scholar-labs-vault --abstracts
scholar-vault enrich-citations --vault ~/Documents/Research/scholar-labs-vault --only missing-abstract
scholar-vault enrich-citations --vault ~/Documents/Research/scholar-labs-vault --refresh
scholar-vault enrich-citations --vault ~/Documents/Research/scholar-labs-vault --refresh-abstracts
scholar-vault enrich-citations --vault ~/Documents/Research/scholar-labs-vault --retry-failed
scholar-vault enrich-citations --vault ~/Documents/Research/scholar-labs-vault --dry-run
```

`enrich-citations` processes canonical `papers/*.md` cards only. It tries local DOI detection first, then cached provider lookups from Crossref, OpenAlex, Europe PMC, DataCite, and DOI content negotiation. Raw provider responses are cached under `raw/metadata/<citekey>/`. When a known DOI resolves to a preprint or repository record with incomplete venue metadata, enrichment may search for a strong published-version match and promote the published DOI and venue instead.

After the one-line count summary, the command prints compact grouped details
for generated, verified, incomplete, ambiguous, unresolved, and skipped records.
Use the GUI result browser when you want to filter those groups and open the
associated paper card or PDF:

```fish
scholar-vault enrich-citations --ui
```

The command writes these frontmatter fields: `doi_status`, `doi_source`, `doi_confidence`, `citation_status`, `citation_source`, `citation_last_checked`, `citation_enriched_at`, `citation_input_fingerprint`, `citation_retries`, `citation_skip_reason`, `metadata_lock`, `enrichment_status`, `enrichment_missing`, and `enrichment_refresh`.

Interpretation:

- `missing`: no DOI or generated citation has been found yet.
- `detected`: DOI was found locally in frontmatter, URLs, PDF metadata, or PDF text.
- `resolved`: a remote provider or DOI lookup accepted the DOI.
- `generated`: BibTeX/CSL metadata was generated but has not been manually verified.
- `verified`: DOI metadata and title/author/year consistency checks were strong.
- `ambiguous`: providers returned plausible but conflicting or weak candidates.
- `unresolved`: no acceptable DOI or citation metadata was found.
- `incomplete`: citation metadata was generated, but canonical fields such as `venue`, `authors`, `year`, or `doi` are still missing or still look like Scholar preview strings.

Set `metadata_lock: true` in a paper card to prevent automatic metadata overwrites. Use `--refresh` to reprocess generated or verified records, `--retry-failed` to retry unresolved records past the retry limit, and `--force` only when you intentionally want to process locked metadata. To mark one card for another normal enrichment attempt from Obsidian, set `enrichment_refresh: true` in that paper card and run `scholar-vault enrich-citations`; the flag is cleared after processing.

Abstract enrichment is opt-in through the same command:

```fish
scholar-vault enrich-citations --vault ~/Documents/Research/scholar-labs-vault --abstracts
scholar-vault enrich-citations --vault ~/Documents/Research/scholar-labs-vault --only missing-abstract
scholar-vault enrich-citations --vault ~/Documents/Research/scholar-labs-vault --citekey smith2024rag --abstracts
scholar-vault enrich-citations --vault ~/Documents/Research/scholar-labs-vault --refresh-abstracts
scholar-vault enrich-citations --vault ~/Documents/Research/scholar-labs-vault --retry-failed --abstracts
scholar-vault enrich-citations --vault ~/Documents/Research/scholar-labs-vault --dry-run --abstracts
```

The abstract is not the Scholar Labs summary. Scholar Labs summaries explain why the source appeared in a prompt result; abstracts are provider or PDF metadata and are stored in the `## Abstract` section of each paper card. Frontmatter keeps only abstract status, source, confidence, fingerprint, and lock metadata so agents do not read the same long abstract twice.

Abstract provider order is local DOI detection, Crossref REST metadata, Europe PMC fallback, OpenAlex reconstructed abstracts, DataCite descriptions, then local PDF text extraction. Crossref abstracts may include JATS/XML markup, which the tool strips before writing the card. OpenAlex abstracts are reconstructed from `abstract_inverted_index`. The tool never uses LLM summarization or Scholar Labs summaries as abstracts.

Abstract enrichment writes the `## Abstract` section plus these frontmatter fields: `abstract_status`, `abstract_source`, `abstract_source_url`, `abstract_confidence`, `abstract_last_checked`, `abstract_enriched_at`, `abstract_input_fingerprint`, and `abstract_lock`.

Interpretation:

- `missing`: no abstract has been found yet.
- `resolved`: an abstract was accepted from a provider or local PDF extraction.
- `verified`: DOI/title/author/year consistency was strong for the accepted abstract source.
- `ambiguous`: strong sources disagreed or the match was not safe enough to overwrite.
- `unresolved`: no acceptable abstract was found.
- `manual_lock`: the abstract should not be changed automatically.

Set `abstract_lock: true` to protect a manually curated abstract. Use `--refresh-abstracts` to deliberately re-check resolved or verified abstracts, including upgrades from weak sources such as `pdf_extracted` to stronger sources such as Crossref. Use `--force` only when you intentionally want to process locked abstract metadata.

To add a manual abstract without editing YAML by hand, put the abstract in a
plain text file and run:

```fish
scholar-vault set-abstract --citekey smith2024rag --file ~/Downloads/abstract.txt --source-url https://doi.org/10.1145/example
```

This writes the `## Abstract` section, marks `abstract_source: manual`, sets
`abstract_status: manual_lock`, and enables `abstract_lock: true` by default.
Use `--no-lock` only if you want later automatic abstract enrichment to be able
to replace it.

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

Reset the vault to the same clean state produced by `init`:

```fish
scholar-vault reset --vault ~/Documents/Research/scholar-labs-vault
```

Skip the confirmation prompt:

```fish
scholar-vault reset --vault ~/Documents/Research/scholar-labs-vault --yes
```

`reset` only clears vault-managed state inside the vault itself. It does not touch your external download folders such as `~/Downloads/scholar-labs-staging` or `~/Downloads/scholar-labs-exports`.

## Generated Records

- `papers/*.md`: canonical source cards for selected papers by default.
- `papers/*.md` body sections: human-readable abstract and primary Scholar Labs summary. Long prose is not duplicated in frontmatter.
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
