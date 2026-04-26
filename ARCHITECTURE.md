# Architecture

## Repository

- `scholar_vault/cli.py`: Typer CLI entrypoint and command wiring.
- `scholar_vault/config.py`: user-level default path storage and latest Scholar Labs export selection.
- `scholar_vault/models.py`: typed records for exports, paper cards, runs, logs, and PDF candidates.
- `scholar_vault/sources.py`: vault path management, slug and citekey utilities, Markdown parsing, and frontmatter helpers.
- `scholar_vault/matcher.py`: PDF extraction, metadata inference, and fuzzy matching helpers using DOI, extracted title, filename, and compact first-page text evidence.
- `scholar_vault/importer.py`: end-to-end workflows for `init`, import commands, rebuilds, and derived exports.
- `scholar_vault/render.py`: Jinja-backed Markdown rendering for cards, run pages, indexes, topics, and LLM summary files.
- `scholar_vault/bibtex.py`: BibTeX parsing and export helpers.
- `scholar_vault/citations.py`: DOI detection, provider response caching, citation and abstract enrichment, candidate scoring, abstract provenance, and BibTeX normalization.
- `scholar_vault/gui.py`: PySide6/PyMuPDF desktop UI for configuration, Scholar Labs match decisions, import/enrichment progress, import summaries, issue-card follow-up browsing, and missing-abstract manual resolution. GUI imports stay isolated so non-UI commands do not initialize Qt.
- `templates/`: Markdown body templates for the generated paper, run, and index documents.
- `browser/`: browser-side exporter for visible Google Scholar Labs results.
- `tests/`: regression coverage for naming, parsing, matching, rendering, and idempotence.

## CLI Workflows

- `configure`: stores user-level defaults for the vault, staging folder, optional export folder, and code directory in `~/.config/scholar-vault/config.yaml`. `--ui` opens a native folder-picker dialog. `--folder-mode shared` omits `exports` so staging is used for PDFs and Scholar Labs JSON exports; `--folder-mode separate` records an explicit exports folder. Commands use these defaults unless explicit paths are passed.
- `runs` / `list-runs`: lists previous Scholar Labs run records with the run ID, exported date, selected/result counts, unresolved count, and title. Typer shell completion supplies command and option names, while custom completion callbacks fill `--run`, `--citekey`, `--only`, and `--folder-mode` values from the explicit or configured vault.
- `import-labs`: Scholar Labs convenience flow. It keeps all JSON results on the run record, creates canonical paper cards only for selected results by default, archives matched PDFs out of staging only after the verified vault copy exists, enriches selected paper cards by default, and moves used browser-export JSON unchanged into a sibling `used/` folder after successful non-dry-run imports. If `--export` is omitted, it imports the newest top-level `.json` file from the configured exports folder when that folder has one, otherwise from the staging folder.
- Import summaries report decision provenance separately: prior selections reused from an existing manifest, existing vault cards linked, newly accepted staged PDFs, review prompts, unresolved results, staged-file cleanup, and enrichment processing.
- `--upgrade-pdfs` on Scholar Labs import/resume/rerun commands makes staged PDFs eligible to replace already attached PDFs through the normal match-review path. Accepted upgrades repoint the canonical paper card, preserve the previous card state in the import manifest, and mark citation enrichment for refresh so DOI-bearing publisher PDFs can repair preprint metadata.
- `import-run`: lower-level transactional Scholar Labs import. It uses the same matching and manifest logic but leaves staging untouched unless another command archives files later.
- `import-pdf`, `import-bibtex`, and `import-doi`: non-Scholar-Labs ingestion paths that still converge on canonical `papers/*.md` cards.
- `enrich-citations`: canonical-card-only DOI, citation, and optional abstract metadata enrichment. Default behavior enriches DOI/citation data; `--abstracts`, `--only missing-abstract`, or `--refresh-abstracts` switch to abstract enrichment with separate locks and fingerprints.
- `--ui`: desktop review mode on interactive Scholar Labs import/resume/rerun commands and enrichment review. `rerun --ui` opens a run picker when `--run` is omitted, while terminal reruns still default to the latest run for scriptability. After GUI imports, enrichment progress stays visible and unresolved/incomplete follow-up rows open in the result browser. If GUI dependencies are unavailable in the current environment, commands fall back to terminal output and prompts.
- Paper-card frontmatter includes `enrichment_status`, `enrichment_missing`, and `enrichment_refresh` so incomplete canonical metadata is visible and individual cards can request another enrichment attempt from Obsidian.

## Canonical Data Model

- Canonical source record: `papers/<slug>.md`
- Scholar Labs provenance record: `runs/<run_id>/<Short Title.md>` for Obsidian plus `index.yaml` for machine-readable state.
- Run IDs remain stable and prompt-derived for idempotence. Run note filenames use `note_file` when present, otherwise the `title` field from the Scholar Labs JSON, a `--title` override, an import-time prompt for older untitled JSON, `rename-run`, or an Obsidian filename rename.
- Raw inputs: `raw/`
- Staging scan cache: `.scholar-vault-pdf-scan-cache` beside staged PDFs, keyed by filename plus size/mtime and ignored by JSON export discovery.
- Raw citation cache: `raw/metadata/<citekey>/`
- Derived indexes and exports: `_indexes/`, `_exports/`, `llms.txt`, `llms-full.txt`

## Merge Strategy

- Match existing cards by DOI first, then Scholar CID, citekey, and exact normalized title.
- Keep the original `source_kind` on an existing card so enrichment imports do not erase provenance.
- Prefer existing citekeys, primary summaries, notes, discovered runs, and paper keywords. Fill missing metadata from new imports.
- Preserve every Scholar Labs run-specific summary in run records and run notes, and hydrate `summary_sources` in memory from those records so repeated appearances of the same paper do not overwrite earlier summaries.
- Store recovered abstracts separately from Scholar Labs summaries. Abstract enrichment writes the prose to `## Abstract` and keeps only `abstract_*` status/provenance fields in frontmatter, without modifying Scholar Labs summary/rationale provenance.
- Store paper-provided `keywords` separately from prompt-derived `topics`. Keywords come from BibTeX/provider metadata or local PDF keyword blocks and export as BibTeX/CSL keywords.

## Rebuild Strategy

- Rebuild reads canonical paper cards plus run YAML files.
- Rebuild rerenders generated paper/run Markdown from current templates and regenerates indexes, topic pages, LLM summaries, and export files.
- Rebuild intentionally does not require Obsidian, Zotero, or a database.
