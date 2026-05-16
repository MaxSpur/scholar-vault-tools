# Manual Self-Improvement Runbook

This manual sequence is currently preferred over scheduled automations. It
surfaces deterministic maintenance signals, records what happened, and keeps
scientific records under explicit human or agent control.

Set the vault once:

```sh
VAULT=/path/to/vault
```

Run the maintenance pass:

```sh
scholar-vault maintenance-report --vault "$VAULT" --write-queue --json
scholar-vault lint-wiki --vault "$VAULT" --write-report --write-queue --json
scholar-vault eval list --vault "$VAULT" --json
scholar-vault eval run --vault "$VAULT" --write-queue --json
scholar-vault eval report --vault "$VAULT" --json
```

Review compile state before changing digest status:

```sh
scholar-vault compile status --vault "$VAULT" --json
scholar-vault compile doctor --vault "$VAULT" --json
scholar-vault compile mark CITEKEY --vault "$VAULT" --status compiled --json
scholar-vault compile mark CITEKEY --vault "$VAULT" --status reviewed --json
```

Use `--force` on `compile mark` only when the readiness guard is intentionally
overridden and the operation is logged.

Review self-improvement state:

```sh
scholar-vault queue list --vault "$VAULT" --json
scholar-vault feedback report --vault "$VAULT" --json
```

Refresh prompt and Bases workbenches:

```sh
scholar-vault labs-prompts generate --vault "$VAULT" --query QUERY_SLUG --json
scholar-vault labs-prompts doctor --vault "$VAULT" --json
scholar-vault bases rebuild --vault "$VAULT" --json
scholar-vault bases doctor --vault "$VAULT" --json
```

Record the maintenance operation:

```sh
scholar-vault operations log \
  --vault "$VAULT" \
  --kind manual-self-improvement \
  --message "Ran maintenance-report, lint-wiki, eval, compile status, queue, feedback, labs-prompts, and bases checks." \
  --command "docs/manual-self-improvement-runbook.md" \
  --check "scholar-vault lint-wiki --write-report --write-queue --json" \
  --check "scholar-vault eval run --write-queue --json" \
  --check "scholar-vault bases doctor --json" \
  --json
```

Do not use this workflow to scrape Google Scholar or to autonomously rewrite
digests, concepts, syntheses, paper cards, or proposals. Queue items and reports
are coordination records; evidence-bearing prose still needs an explicit
PDF-grounded edit.
