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
- `templates/`: Markdown body templates for the generated paper, run, and index documents.
- `browser/`: browser-side exporter for visible Google Scholar Labs results.
- `tests/`: regression coverage for naming, parsing, matching, rendering, and idempotence.

## CLI Workflows

- `import-labs`: Scholar Labs convenience flow. It keeps all JSON results on the run record, creates canonical paper cards only for selected results by default, archives matched PDFs out of staging only after the verified vault copy exists, and moves used browser-export JSON unchanged into a sibling `used/` folder after successful non-dry-run imports.
- `configure`: stores user-level defaults for the vault, staging folder, export folder, and code directory in `~/.config/scholar-vault/config.yaml`. Commands use these defaults unless explicit paths are passed.
- `import-labs`: Scholar Labs convenience flow. It keeps all JSON results on the run record, creates canonical paper cards only for selected results by default, archives matched PDFs out of staging only after the verified vault copy exists, and moves used browser-export JSON unchanged into a sibling `used/` folder after successful non-dry-run imports. If `--export` is omitted, it imports the newest top-level `.json` file from the configured exports folder.
- `import-run`: lower-level transactional Scholar Labs import. It uses the same matching and manifest logic but leaves staging untouched unless another command archives files later.
- `import-pdf`, `import-bibtex`, and `import-doi`: non-Scholar-Labs ingestion paths that still converge on canonical `papers/*.md` cards.
- `enrich-citations`: canonical-card-only DOI, citation, and optional abstract metadata enrichment. Default behavior enriches DOI/citation data; `--abstracts`, `--only missing-abstract`, or `--refresh-abstracts` switch to abstract enrichment with separate locks and fingerprints.

## Canonical Data Model

- Canonical source record: `papers/<slug>.md`
- Scholar Labs provenance record: `runs/<run_id>/<Short Title.md>` for Obsidian plus `index.yaml` for machine-readable state.
- Run IDs remain stable and prompt-derived for idempotence. Run note filenames use `note_file` when present, otherwise the `title` field supplied through `--title`, inferred from the prompt, changed with `rename-run`, or edited directly through an Obsidian filename rename.
- Raw inputs: `raw/`
- Raw citation cache: `raw/metadata/<citekey>/`
- Derived indexes and exports: `_indexes/`, `_exports/`, `llms.txt`, `llms-full.txt`

## Merge Strategy

- Match existing cards by DOI first, then Scholar CID, citekey, and exact normalized title.
- Keep the original `source_kind` on an existing card so enrichment imports do not erase provenance.
- Prefer existing citekeys, primary summaries, notes, and discovered runs. Fill missing metadata from new imports.
- Preserve every Scholar Labs run-specific summary in `summary_sources` on the canonical card, keyed by the run note path, so repeated appearances of the same paper do not overwrite earlier summaries.
- Store recovered abstracts separately from Scholar Labs summaries. Abstract enrichment writes `abstract_*` fields and a `## Abstract` section without modifying Scholar Labs summary/rationale provenance.

## Rebuild Strategy

- Rebuild reads canonical paper cards plus run YAML files.
- Rebuild regenerates indexes, topic pages, LLM summaries, and export files.
- Rebuild intentionally does not require Obsidian, Zotero, or a database.
