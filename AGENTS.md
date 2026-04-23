# scholar-vault repo notes

## Project Memory

- Read [README.md](/Users/MadMax/Developer/scholar-vault-tools/README.md) first for the user-facing workflow and exact CLI commands.
- Read [ARCHITECTURE.md](/Users/MadMax/Developer/scholar-vault-tools/ARCHITECTURE.md) for the package layout, vault model, and generated file responsibilities.
- Read [TODO.md](/Users/MadMax/Developer/scholar-vault-tools/TODO.md) for the current implementation checklist and verification status.
- Read [LESSONS.md](/Users/MadMax/Developer/scholar-vault-tools/LESSONS.md) before touching importer idempotence, matching thresholds, or generated Markdown.

## Working Rules

- Keep `papers/` cards as the canonical archive object. Treat runs, indexes, and exports as derived views.
- For Scholar Labs imports, keep all candidate results on the run record and create canonical `papers/*.md` cards only for selected results by default.
- Preserve raw inputs where practical. Scholar Labs exports copied into vault storage should stay immutable.
- Keep `browser/scholar_labs_json_exporter.js` Scholar-specific. It depends on Google Scholar `gs_*` selectors and should not be generalized without testing on a real Scholar Labs results page.
- Keep raw failed Scholar Labs exports for debugging, but do not import them into runs or paper cards.
- Keep Scholar Labs PDF handling non-destructive: prefer copy-and-verify into `pdfs/`, leave staging files in place unless the command explicitly archives them, and record decisions in the run manifest.
- `import-labs` is the explicit Scholar Labs convenience flow. It should archive matched PDFs out of staging only after the verified vault copy exists, while unmatched PDFs stay in staging.
- After successful non-dry-run `import-labs`, move used browser-export JSON files into a sibling `used/` folder without renaming them and update run/manifest `export_file` paths. Do not move export JSON on dry-runs or invalid exports.
- If the exporter changes, verify these browser diagnostics on a live Scholar Labs results page before accepting the change:
  `document.querySelectorAll('div.gs_r[data-cid], div.gs_or[data-cid]').length`
  `document.querySelector('.gs_as_np_tq')?.innerText`
- Prefer updating existing cards over creating parallel records. Match by DOI, Scholar CID, citekey, or normalized title before making a new card.
- Preserve existing summaries and provenance during enrichment imports.
- Preserve run-specific Scholar Labs summaries in `summary_sources` on paper cards. Do not overwrite a paper's primary `Summary` just because a later run produced different Scholar Labs text.
- Generate run Markdown as `runs/<run_id>/<Short Title.md>`, not `index.md`, so Obsidian Graph shows meaningful prompt/run nodes. Keep `runs/<run_id>/index.yaml` as the machine-readable run record.
- Keep run IDs stable for idempotence. Use `note_file`, the run `title` field, `--title`, `rename-run`, or an Obsidian filename rename to change Obsidian-facing run note names.
- `enrich-citations` must process canonical `papers/*.md` cards only. Do not enrich run candidates directly.
- Citation enrichment should preserve Scholar Labs summaries, rationale, provenance, and topics. Respect `metadata_lock: true`, `citation_status: verified`, fingerprints, and retry limits unless the user passes the explicit override flags.
- Keep raw citation provider responses under `raw/metadata/<citekey>/` and use cached responses before making repeated remote requests.
- Keep generated Markdown Obsidian-safe: YAML frontmatter, plain links, no plugin-only syntax.
- Maintain idempotence for import commands and rebuilds.
