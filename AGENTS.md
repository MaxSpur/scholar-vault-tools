# scholar-vault-tools repo notes

## Scope

- This root `AGENTS.md` is for agents developing and maintaining the
  `scholar-vault-tools` repository.
- It is not the vault-local operating guide. Vault-local agents should use the
  `AGENTS.md` generated inside a research vault from `VAULT_AGENTS_TEMPLATE.md`.
- Keep this file short and repo-focused. Put vault operating rules, evidence
  rules, and vault-agent workflows in `VAULT_AGENTS_TEMPLATE.md`.

## Project Memory

- Read [README.md](/Users/MadMax/Developer/scholar-vault-tools/README.md) for
  user-facing workflows and exact CLI commands.
- Read [ARCHITECTURE.md](/Users/MadMax/Developer/scholar-vault-tools/ARCHITECTURE.md)
  for package layout, vault model, generated file responsibilities, and module
  ownership.
- Read [TODO.md](/Users/MadMax/Developer/scholar-vault-tools/TODO.md) for the
  current implementation checklist and verification status.
- Read [LESSONS.md](/Users/MadMax/Developer/scholar-vault-tools/LESSONS.md)
  before changing importer idempotence, matching thresholds, generated
  Markdown, or rebuild behavior.

## Environment

- Before running `scholar-vault ...`, activate the Conda environment in that
  shell: `conda activate scholar-vault`.
- If the shell cannot resolve the command, use
  `/Users/MadMax/miniforge3/condabin/conda run -n scholar-vault scholar-vault ...`.
- For Python validation in this repo, prefer:
  `/Users/MadMax/miniforge3/condabin/conda run -n scholar-vault python -m pytest`
  and
  `/Users/MadMax/miniforge3/condabin/conda run -n scholar-vault python -m ruff check .`.
- Plain `python` may not exist in the default zsh environment. Use the Conda
  command above when in doubt.
- Do not run mutating CLI commands against a real research vault unless the
  user explicitly asks. Use tests and temporary vaults for development checks.

## Repository Invariants

- Preserve command idempotence. Re-running imports, rebuilds, project helpers,
  and sync commands should not create duplicate records or unexpected churn.
- Keep linked PDFs as canonical evidence artifacts and `papers/*.md` cards as
  canonical metadata/provenance/notes records in implementation behavior.
- For Scholar Labs imports, keep all candidate results on the run record and
  create canonical paper cards only for selected results by default.
- Candidate results without paper cards are normal selected-only discovery
  context, not maintenance defects.
- Keep Scholar Labs PDF handling non-destructive: copy into `pdfs/`, archive
  staging files only after verified vault copies, and preserve raw inputs.
- Preserve run-specific Scholar Labs summaries in `summary_sources`. Do not
  overwrite a paper's primary summary just because a later run produced another
  Scholar Labs summary.
- `enrich` / `enrich-citations` must process canonical `papers/*.md` cards only.
  Preserve metadata locks, abstract locks, enrichment fingerprints, retry state,
  provenance, topics, and manual abstracts unless an explicit override flag is
  passed.
- Keep generated Markdown Obsidian-safe: YAML frontmatter, plain Markdown links,
  and no plugin-only syntax.

## Module Ownership

- Do not add new feature families to `scholar_vault/importer.py`. Add focused
  modules and keep compatibility wrappers thin.
- `importer.py` should stay centered on import/rerun/resume flows, run
  manifests, staging PDF behavior, selected-only semantics, and post-import
  enrichment coordination.
- Keep CLI aliases as thin calls into shared helpers. Preserve existing commands
  and aliases unless the user explicitly asks to remove them.
- Project scaffold/link commands must use focused project navigation refreshes
  only. Do not trigger broad rebuild side effects such as paper-card
  normalization, PDF filename repair, or run-link repair unless the user
  explicitly runs `rebuild`.
- Project workspaces are a lens over shared vault content, not separate vaults.
  Link to existing paper, run, concept, synthesis, task, and proposal records
  instead of duplicating source content.
- Rebuild may rerender existing generated paper cards and repair conservative
  run/card/PDF links. Keep those broad effects behind explicit rebuild paths.

## Vault Guide Ownership

- `VAULT_AGENTS_TEMPLATE.md` is the source of truth for vault-local `AGENTS.md`
  files.
- `render_vault_agents()` must read `VAULT_AGENTS_TEMPLATE.md`; do not re-create
  a second embedded copy of the vault guide in Python.
- `scholar-vault skills diff`, `skills adopt`, `skills publish`, and `skills ui`
  synchronize both `vault-agent-skills/` and `VAULT_AGENTS_TEMPLATE.md`/vault
  `AGENTS.md`.
- In sync wording, source means this repository's `vault-agent-skills/` plus
  `VAULT_AGENTS_TEMPLATE.md`; target means the vault's `.agents/skills/` plus
  vault `AGENTS.md`.
- Reserve this repository's `.agents/skills/` path for skills that help agents
  develop `scholar-vault-tools` itself. Do not put vault-agent skills there,
  because Codex sessions opened on this tools repo may auto-load that path.
- Do not use raw `rsync --delete` for skill or AGENTS synchronization. Adopt
  intentional vault-side improvements first, then publish from the repository
  source of truth.
- Modification-time hints are guidance only. Do not treat "source newer" or
  "vault newer" as permission to overwrite without an explicit publish/adopt
  direction.

## Browser Exporter

- Keep `browser/scholar_labs_json_exporter.js` Scholar-specific. It depends on
  Google Scholar `gs_*` selectors and should not be generalized without testing
  on a real Scholar Labs results page.
- If the exporter changes, verify these browser diagnostics on a live Scholar
  Labs results page before accepting the change:
  `document.querySelectorAll('div.gs_r[data-cid], div.gs_or[data-cid]').length`
  and `document.querySelector('.gs_as_np_tq')?.innerText`.

## Verification

- For normal code changes, run:
  `/Users/MadMax/miniforge3/condabin/conda run -n scholar-vault python -m pytest`
- Run:
  `/Users/MadMax/miniforge3/condabin/conda run -n scholar-vault python -m ruff check .`
- After CLI/package wiring changes, run:
  `/Users/MadMax/miniforge3/condabin/conda run -n scholar-vault python -m pip install -e .`
- State clearly which checks were run and any remaining risks.
