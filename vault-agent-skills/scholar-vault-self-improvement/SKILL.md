---
name: scholar-vault-self-improvement
description: Track typed Scholar Vault improvement work, operation logs, feedback, and scholar-vault-tools improvement requests. Use when Codex is asked to inspect or update tasks/queue records, log vault operations, rate generated artifacts or tool behavior, convert feedback into tool work, or run a maintenance report with typed queue output.
---

# Scholar Vault Self-Improvement

Use this skill when the durable output is process state: a queue item,
operation record, feedback rating, or tool-improvement request. Do not use these
records as scientific evidence, and do not use them as a substitute for reading
PDFs before writing research claims.

## CLI Environment

Before any `scholar-vault ...` command, activate the project Conda environment
in the same shell:

```fish
conda activate scholar-vault
scholar-vault queue list --json
```

If activation is unavailable or `scholar-vault` is still not on `PATH`, use the
explicit fallback:

```fish
/Users/MadMax/miniforge3/condabin/conda run -n scholar-vault scholar-vault queue list --json
```

Do not retry plain `scholar-vault` commands without one of these environment
paths.

## Workflow

1. Read `AGENTS.md`, then orient from `_indexes/self-improvement.md`,
   `scholar-vault queue list --json`, `scholar-vault feedback report --json`,
   and relevant `tasks/`, `queries/`, `projects/`, or paper cards.
2. For broad maintenance triage, prefer
   `scholar-vault maintenance-report --write-queue`; it creates duplicate-safe
   queue items with stable keys.
3. For a new typed task, use `scholar-vault queue add` with the narrowest
   correct `--kind`, `--required-evidence`, and links such as `--citekey`,
   `--run`, `--file`, `--query`, or `--project`.
4. Mark intent with `scholar-vault queue plan <queue-id>`. Close completed or
   rejected items with `scholar-vault queue close <queue-id> --status done
   --notes "..."`.
5. Log meaningful work with `scholar-vault operations log`, especially when an
   agent run changes vault state, closes queue items, or verifies a fix.
6. Record useful or problematic outputs with `scholar-vault feedback rate`.
   Use `feedback report` to find items needing action and repeated failure
   themes.
7. Convert tool behavior problems into a repository-facing task with
   `scholar-vault tools-task create`; it creates an `improve_tool` queue item
   in the vault and does not edit `scholar-vault-tools` directly.
8. Run `scholar-vault queue doctor --json`, `scholar-vault operations doctor
   --json`, and `scholar-vault feedback doctor --json` after manual edits or
   bulk workflow changes.

## Command Patterns

```fish
scholar-vault maintenance-report --write-queue
scholar-vault queue add --kind discover_sources --title "Review candidate-only Labs results" --required-evidence web --run <run-id> --success-criteria "Candidates are imported with evidence or intentionally ignored."
scholar-vault queue add --kind compile_paper --title "Read and compile <citekey>" --required-evidence pdf --citekey <citekey>
scholar-vault queue add --kind update_synthesis --title "Repair source links in <synthesis>" --required-evidence pdf --file syntheses/<slug>.md
scholar-vault operations log --kind research-loop --message "Compiled <citekey> digest." --queue-item <queue-id> --check "scholar-vault compile doctor --json"
scholar-vault feedback rate paper-digests/<citekey>.md --target-type paper_digest --verdict needs_fix --notes "Missing limitations section."
scholar-vault tools-task create --title "Improve queue duplicate warning" --problem "..." --expected-behavior "..." --test "CLI duplicate stable-key coverage"
```

## Boundaries

- Queue records are work-tracking state, not evidence.
- Operation logs are process memory, not proof that research claims are true.
- Feedback is evaluative context; it should guide follow-up work, not rewrite
  paper cards or syntheses by itself.
- Required evidence matters. A queue item requiring `pdf` is not done until the
  relevant linked PDFs have been read or the item is explicitly rejected.
- Do not hand-edit `_indexes/self-improvement.md` or
  `bases/self-improvement.base`; they are generated views.
