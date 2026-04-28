# scholar-vault repo notes

## Project Memory

- Read [README.md](/Users/MadMax/Developer/scholar-vault-tools/README.md) first for the user-facing workflow and exact CLI commands.
- Read [ARCHITECTURE.md](/Users/MadMax/Developer/scholar-vault-tools/ARCHITECTURE.md) for the package layout, vault model, and generated file responsibilities.
- Read [TODO.md](/Users/MadMax/Developer/scholar-vault-tools/TODO.md) for the current implementation checklist and verification status.
- Read [LESSONS.md](/Users/MadMax/Developer/scholar-vault-tools/LESSONS.md) before touching importer idempotence, matching thresholds, or generated Markdown.

## Working Rules

- Before running any `scholar-vault ...` CLI command, make sure the `scholar-vault` Conda environment is active in that shell (`conda activate scholar-vault`). If the shell cannot resolve the command, use `/Users/MadMax/miniforge3/condabin/conda run -n scholar-vault scholar-vault ...` instead of retrying plain `scholar-vault`.
- Prefer `scholar-vault status --json`, `scholar-vault pdf-doctor --json`, `scholar-vault notes-missing --heading "PDF reading notes"`, `scholar-vault concept-index`, and dry-run `scholar-vault topic-map --mapping ...` for agent orientation and indexing before manually scanning many generated files.
- Keep linked PDFs as the canonical evidence artifacts. Treat `papers/` cards as the canonical metadata, provenance, index, and notes layer over those PDFs. Treat runs, indexes, and exports as derived views.
- For Scholar Labs imports, keep all candidate results on the run record and create canonical `papers/*.md` cards only for selected results by default.
- In the selected-only Scholar Labs workflow, candidate results without paper cards are discovery context, not maintenance defects. Do not treat `_indexes/missing-pdfs.md` as an action queue unless the user explicitly wants to revisit candidates or there are real, non-duplicate PDFs left in staging.
- Historical unmatched manifest entries are audit records from prior imports. They are actionable only when the referenced PDF still exists in staging and is not already a duplicate of a vault PDF.
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
- `enrich` / `enrich-citations` must process canonical `papers/*.md` cards only. Do not enrich run candidates directly.
- Citation enrichment should preserve Scholar Labs summaries, rationale, provenance, and topics. Respect `metadata_lock: true`, `citation_status: verified`, fingerprints, and retry limits unless the user passes the explicit override flags.
- Treat `enrichment_refresh: true` on a paper card as a user-requested one-card retry. It should bypass normal citation/abstract skip logic, refresh provider caches for that card, and clear after processing.
- Mark generated but incomplete metadata with `enrichment_status: incomplete` and list missing fields in `enrichment_missing`, especially when `venue` is still a Scholar preview string.
- `enrichment_status: missing` is not itself a follow-up issue. It means citation metadata has not been completed/generated for that card, or the field was stale before rebuild. Use `status` issue counts, `enrich --dry-run`, and actionable UI rows rather than treating every `missing` status as a defect.
- For theses, reports, and other non-article PDFs where DOI or journal/conference venue is genuinely absent, use the enrichment UI's metadata resolver or `resolve-citation --lock` instead of inventing fields.
- When a DOI points to a preprint/repository record with incomplete venue metadata, enrichment may promote a strong published-version match if title/author/year checks are strong enough.
- Abstract enrichment is part of `enrich`; `--only missing-abstract` focuses on that queue. Treat abstracts as separate metadata from Scholar Labs summaries.
- Preserve non-empty manual abstracts and `abstract_lock: true` records unless the user explicitly passes `--force`. Use `--refresh-abstracts` for deliberate provider upgrades such as replacing `pdf_extracted` with Crossref.
- Keep raw citation provider responses under `raw/metadata/<citekey>/` and use cached responses before making repeated remote requests.
- Keep generated Markdown Obsidian-safe: YAML frontmatter, plain links, no plugin-only syntax.
- Use `resolve-citation` / `set-metadata`, `set-abstract`, `set-keywords`, `topic-map --apply`, `attach-pdf`, `rerun`, and `clean-staging` instead of hand-editing tool-managed metadata, topic batches, or PDF state.
- Any workflow that refines factual claims, methods, findings, limitations, or source connections should read the linked PDF, not rely only on Scholar Labs summaries or existing card prose.
- For PDF-grounded research work, durable agent-written metacards may live in `concepts/`, `syntheses/`, and `tasks/`. These folders are not generated; keep them concise, linked, and evidence-grounded. Use `concept-index` for concept-only refreshes and `rebuild` after broader edits.
- For proposal workspaces under `proposals/`, use `proposal-sprint scaffold <slug>` to create/update the outline, source matrix, reading log, and raw idea card, set outline `evidence_matrix` when the source matrix lives elsewhere such as `syntheses/`, then use `proposal-audit` before treating outlines or draft claims as evidence-ready.
- Rebuild should rerender existing generated paper cards from the current template, not only indexes. Template-only improvements such as `## Quick access` must apply to existing cards.
- Maintain idempotence for import commands and rebuilds.
