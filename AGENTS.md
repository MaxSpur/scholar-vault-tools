# scholar-vault repo notes

## Project Memory

- Read [README.md](/Users/MadMax/Developer/scholar-vault-tools/README.md) first for the user-facing workflow and exact CLI commands.
- Read [ARCHITECTURE.md](/Users/MadMax/Developer/scholar-vault-tools/ARCHITECTURE.md) for the package layout, vault model, and generated file responsibilities.
- Read [TODO.md](/Users/MadMax/Developer/scholar-vault-tools/TODO.md) for the current implementation checklist and verification status.
- Read [LESSONS.md](/Users/MadMax/Developer/scholar-vault-tools/LESSONS.md) before touching importer idempotence, matching thresholds, or generated Markdown.

## Working Rules

- Keep `papers/` cards as the canonical archive object. Treat runs, indexes, and exports as derived views.
- Preserve raw inputs where practical. Scholar Labs exports copied into vault storage should stay immutable.
- Prefer updating existing cards over creating parallel records. Match by DOI, Scholar CID, citekey, or normalized title before making a new card.
- Preserve existing summaries and provenance during enrichment imports.
- Keep generated Markdown Obsidian-safe: YAML frontmatter, plain links, no plugin-only syntax.
- Maintain idempotence for import commands and rebuilds.
