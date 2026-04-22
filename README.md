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
3. Run the browser exporter in `browser/scholar_labs_json_exporter.js` on the Scholar Labs page to save a JSON export.
4. Import the run:

```fish
scholar-vault import-run --vault ~/Documents/Research/scholar-labs-vault --export ~/Downloads/scholar-labs-exports/example.json --staging ~/Downloads/scholar-labs-staging
```

The convenience alias behaves identically:

```fish
scholar-vault import --vault ~/Documents/Research/scholar-labs-vault --export ~/Downloads/scholar-labs-exports/example.json --staging ~/Downloads/scholar-labs-staging
```

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

## Generated Records

- `papers/*.md`: canonical source cards.
- `runs/*/index.md`: per-run provenance pages for Scholar Labs imports.
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
