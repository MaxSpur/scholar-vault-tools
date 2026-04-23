# TODO

- [x] Scaffold the package, CLI, browser exporter, templates, and tests.
- [x] Implement local-first vault initialization and generated documentation.
- [x] Implement Scholar Labs, direct PDF, BibTeX, DOI, rebuild, and BibTeX export workflows.
- [x] Add matching, citekey, slug, and Markdown rendering coverage.
- [x] Run verification commands and record any fixes from the first pass.
- [x] Reject invalid Scholar Labs exports and keep failed raw exports for debugging without creating runs or paper cards.
- [x] Switch Scholar Labs imports to selected-only paper creation with run manifests and non-destructive staging handling.
- [x] Split the explicit Scholar Labs workflow into `import-labs`, with matched PDFs archived out of staging after verified copy and unmatched PDFs left in place.
- [x] Move successfully used Scholar Labs JSON exports unchanged into an exports-folder `used/` subfolder while keeping run resume metadata valid.
- [x] Add a `rerun` shortcut for rescanning an existing run after more PDFs are added to staging.
- [x] Make `rerun` default to the latest recorded run when `--run` is omitted.
- [x] Add canonical-card DOI and BibTeX enrichment with cached provider responses, skip rules, fingerprints, and generated-only BibTeX export.
- [x] Promote trusted DOI metadata into canonical paper card fields so venues/authors/titles are not left as Scholar preview strings.
- [x] Add short Obsidian-facing run titles, `--title`, and `rename-run` while keeping stable run IDs.
- [ ] Add review workflow for papers whose citation enrichment state is `ambiguous`.
- [ ] Add an Obsidian-friendly command or workflow for exporting useful BibTeX directly from the vault while working in Obsidian.
