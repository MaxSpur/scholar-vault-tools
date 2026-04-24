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
- `import-labs`, `import`, `resume`, and `rerun` should run citation and abstract enrichment for selected papers by default after committed matches. Keep `--no-enrich` available as the fast/offline escape hatch.
- Keep terminal progress feedback for import and enrichment workflows because provider lookups and PDF scans can take noticeable time.
- After successful non-dry-run `import-labs`, move used browser-export JSON files into a sibling `used/` folder without renaming them and update run/manifest `export_file` paths. Do not move export JSON on dry-runs or invalid exports.
- If the exporter changes, verify these browser diagnostics on a live Scholar Labs results page before accepting the change:
  `document.querySelectorAll('div.gs_r[data-cid], div.gs_or[data-cid]').length`
  `document.querySelector('.gs_as_np_tq')?.innerText`
- Prefer updating existing cards over creating parallel records. Match by DOI, Scholar CID, citekey, or normalized title before making a new card.
- Preserve existing summaries and provenance during enrichment imports.
- Preserve run-specific Scholar Labs summaries in `summary_sources` on paper cards. Do not overwrite a paper's primary `Summary` just because a later run produced different Scholar Labs text.
- Generate run Markdown as `runs/<run_id>/<Short Title.md>`, not `index.md`, so Obsidian Graph shows meaningful prompt/run nodes. Keep `runs/<run_id>/index.yaml` as the machine-readable run record.
- Keep run IDs stable for idempotence. Use `note_file`, the run `title` field, `--title`, `rename-run`, or an Obsidian filename rename to change Obsidian-facing run note names.
- User-level path defaults live in `~/.config/scholar-vault/config.yaml` unless `SCHOLAR_VAULT_CONFIG` overrides the location. Commands should use explicit CLI paths when provided and fall back to configured defaults only when options are omitted.
- `import-labs` may omit `--export`; in that case it imports the newest top-level `.json` in the configured exports folder when that folder has one, otherwise the newest top-level `.json` in staging, and ignores files already moved into `used/`.
- `enrich-citations` must process canonical `papers/*.md` cards only. Do not enrich run candidates directly.
- Citation enrichment should preserve Scholar Labs summaries, rationale, provenance, and topics. Respect `metadata_lock: true`, `citation_status: verified`, fingerprints, and retry limits unless the user passes the explicit override flags.
- Treat `enrichment_refresh: true` on a paper card as a user-requested one-card retry. It should bypass normal citation/abstract skip logic, refresh provider caches for that card, and clear after processing.
- Mark generated but incomplete metadata with `enrichment_status: incomplete` and list missing fields in `enrichment_missing`, especially when `venue` is still a Scholar preview string.
- When a DOI points to a preprint/repository record with incomplete venue metadata, enrichment may promote a strong published-version match if title/author/year checks are strong enough.
- Abstract enrichment is part of `enrich-citations` but only runs when `--abstracts`, `--only missing-abstract`, or `--refresh-abstracts` is passed. Treat abstracts as separate metadata from Scholar Labs summaries.
- Preserve non-empty manual abstracts and `abstract_lock: true` records unless the user explicitly passes `--force`. Use `--refresh-abstracts` for deliberate provider upgrades such as replacing `pdf_extracted` with Crossref.
- Keep raw citation provider responses under `raw/metadata/<citekey>/` and use cached responses before making repeated remote requests.
- Keep generated Markdown Obsidian-safe: YAML frontmatter, plain links, no plugin-only syntax.
- Rebuild should rerender existing generated paper cards from the current template, not only indexes. Template-only improvements such as `## Quick access` must apply to existing cards.
- Maintain idempotence for import commands and rebuilds.
