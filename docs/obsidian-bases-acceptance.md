# Obsidian Bases Acceptance

Use this checklist after `scholar-vault bases rebuild` or any change to query,
paper, prompt-pack, or compile metadata.

## Command Checks

- Run `scholar-vault bases rebuild --vault /path/to/vault`.
- Run `scholar-vault bases doctor --vault /path/to/vault --json` and confirm
  `"ok": true`.
- Open the generated files under `bases/` and confirm Obsidian does not report
  YAML or Bases syntax errors.

## Obsidian Manual Checks

- Open `bases/papers.base`.
  - Confirm `Needs reading`, `Needs compile`, `Missing metadata`, `Recently
    changed`, and `By topic` render.
  - Confirm `linked_queries` and `linked_query_paths` show query path values
    for papers linked from query workbenches.
- Open `bases/queries.base`.
  - Confirm `Active queries`, `Query outputs`, `Queries needing Scholar Labs`,
    `Queries with unread linked papers`, and `Queries with uncompiled linked
    papers` render.
  - From a query note, confirm embedded views like
    `![[bases/queries.base#Query outputs]]` render inside the note.
- Open `bases/scholar-labs-workbench.base`.
  - Confirm query-local prompt packs under `queries/<slug>/prompt-packs/` appear
    in prompt-pack views.
- Open `bases/self-improvement.base`.
  - Confirm queue YAML, feedback YAML, and tool-improvement tasks appear in the
    expected views.

## Path Semantics To Verify

- `this.file.path` is used for query-scoped views. The current query note must
  be open when validating embedded `Query outputs`.
- Paper cards should expose both:
  - `linked_queries`: the Obsidian-visible query references already used by the
    vault.
  - `linked_query_paths`: explicit relative paths such as
    `queries/mobility.md`, used as a path-stable fallback for Bases filters.
- Frontmatter should use plain relative paths, not wikilinks, for generated
  fields that Bases filters compare with `this.file.path`.
  - Good: `queries/mobility.md`
  - Risky for path filters: `[[mobility]]` or `[[queries/mobility]]`
- Markdown body links can remain normal Markdown or wikilinks. The path-sensitive
  behavior is in frontmatter comparisons.

## Rename/Archive Regression Checks

- After `scholar-vault query rename OLD NEW --vault /path/to/vault`, rerun
  `scholar-vault query doctor --vault /path/to/vault --fix --json`.
- Confirm paper cards no longer expose `queries/OLD.md` in `linked_queries` or
  `linked_query_paths`.
- Confirm prompt packs moved from `queries/OLD/prompt-packs/` to
  `queries/NEW/prompt-packs/` and still appear in `scholar-labs-workbench.base`.
- After `scholar-vault query archive SLUG --vault /path/to/vault`, confirm the
  query leaves `Active queries` but the file remains at `queries/SLUG.md`.
