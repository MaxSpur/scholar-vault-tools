# Lessons

- Keep the paper card body sections parseable and stable. Rebuild depends on section headings, so cosmetic heading changes need matching parser updates.
- Preserve existing Scholar Labs summaries and provenance when merging later BibTeX or DOI enrichment.
- Idempotence is easiest when run slugs depend on export metadata and when merges happen before any new card slug is allocated.
- This shell may not expose `python` directly. Use `conda run -n scholar-vault ...` for reliable verification in this repo.
- The Scholar Labs browser exporter is DOM-specific. Treat `prompt == "Google Scholar"` or `results == []` as a broken export, not as an empty but valid import.
- For Scholar Labs, the run is the place to keep all candidate results. `papers/` should default to selected/attached sources only, otherwise Obsidian and LLM navigation get noisy fast.
- If a workflow is meant to empty matched PDFs out of staging, make that explicit in the command name. The lower-level importer should stay safe by default, and the user-facing Labs convenience command can opt into verified copy-then-archive behavior.
