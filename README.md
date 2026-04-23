# scholar-vault

`scholar-vault` is a local-first research source wiki. The canonical record for a source is a Markdown card under `papers/`, not a database row and not a browser export. Scholar Labs is the first ingestion adapter, but direct PDFs, BibTeX, DOI imports, and manual notes all converge on the same paper card format.

The vault is designed for plain files, Obsidian compatibility, and agent readability. A Codex agent should be able to see which sources exist, how they were discovered, where their PDFs live, which runs imported them, and which topic pages synthesize them without walking every PDF in a folder.

## Install

Use the exact macOS / Fish / Conda workflow below:

```fish
conda activate scholar-vault
python -m pip install -e .
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
3. Run the browser exporter in `browser/scholar_labs_json_exporter.js` on the Scholar Labs page to save a JSON export. This exporter is intentionally tied to Google Scholar `gs_*` selectors and should not be replaced with generic card scraping logic.
4. Import the run:

```fish
scholar-vault import-labs --vault ~/Documents/Research/scholar-labs-vault --export ~/Downloads/scholar-labs-exports/example.json --staging ~/Downloads/scholar-labs-staging
```

The compatibility alias still behaves identically:

```fish
scholar-vault import --vault ~/Documents/Research/scholar-labs-vault --export ~/Downloads/scholar-labs-exports/example.json --staging ~/Downloads/scholar-labs-staging
```

Default Scholar Labs behavior is now selected-only:

- The raw Scholar Labs export is always preserved under `raw/scholar-labs/`.
- The run page stores all candidate results from the export.
- Canonical `papers/*.md` cards are created only for results with matched PDFs.
- Candidate results stay on the run page unless you explicitly opt in with `--include-without-pdf`.
- `import-labs` copies accepted PDFs into `pdfs/`, verifies them, and then archives the matched originals out of staging into `raw/imported/`, leaving only unmatched PDFs in staging.
- After a successful non-dry-run import, `import-labs` moves the used JSON export into a sibling `used/` folder, for example `~/Downloads/scholar-labs-exports/used/<run-id>__example.json`. The run metadata is updated so `resume` still knows where the export went.
- `import-run` is the lower-level transactional variant. It copies accepted PDFs into `pdfs/` but leaves staging untouched unless you later run `clean-staging`.

Dry-run the import without creating paper cards or copying PDFs:

```fish
scholar-vault import-labs --vault ~/Documents/Research/scholar-labs-vault --export ~/Downloads/scholar-labs-exports/example.json --staging ~/Downloads/scholar-labs-staging --dry-run
```

Auto-commit only high-confidence matches:

```fish
scholar-vault import-labs --vault ~/Documents/Research/scholar-labs-vault --export ~/Downloads/scholar-labs-exports/example.json --staging ~/Downloads/scholar-labs-staging --commit
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

Regenerate BibTeX only:

```fish
scholar-vault bibtex --vault ~/Documents/Research/scholar-labs-vault
```

Resume a previous run using the export and staging folder already recorded in `runs/<run_id>/index.yaml`:

```fish
scholar-vault resume --vault ~/Documents/Research/scholar-labs-vault --run 2026-04-22_example-prompt
```

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
- `runs/*/index.md`: per-run provenance pages that keep all Scholar Labs candidate results.
- `runs/*/import-manifest.yaml`: transactional record of proposed matches, decisions, copied PDFs, and created cards.
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
