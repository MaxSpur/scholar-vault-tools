# Bird Vocoder Autopilot Tutorial

This tutorial covers a project that starts outside the vault: you discussed an
idea elsewhere, ran multiple Google Scholar Labs prompts yourself, downloaded
only the PDFs you want to keep, and now want the vault to turn those files into
a durable project workspace.

The example project is **Bird Vocoder**. Replace paths and names as needed.

## What The Vault Will Treat As Important

- Downloaded PDFs are the evidence candidates that should become canonical
  `papers/*.md` cards.
- Scholar Labs results without downloaded PDFs stay inside the run record. They
  are useful for reruns and manual PDF matching, but they are not promoted to
  paper cards by default.
- Overlapping results across prompts are expected. Imports are idempotent and
  should reuse existing paper cards when metadata/PDF matching finds the same
  source.
- The project page is the durable lens over all imported runs, selected papers,
  digests, and syntheses for this topic.

## 1. Prepare Your Files

Use your normal shared staging folder. It can contain PDFs from several Labs
prompts plus the JSON exports. The importer will match the PDFs that belong to
the export you name and leave unrelated PDFs in staging for later imports.
Leftover staged PDFs are not blockers; only ambiguous/manual match decisions
should block.

Example:

```fish
mkdir -p ~/Downloads/scholar-labs-staging
```

Keep the two Scholar Labs JSON exports in staging or pass their exact paths:

```fish
~/Downloads/scholar-labs-staging/bird-vocoder-prompt-1.json
~/Downloads/scholar-labs-staging/bird-vocoder-prompt-2.json
```

## 2. Create The Project

Use `start` only to create the clean project workspace.

```fish
scholar-vault start bird-vocoder --title "Bird Vocoder"
```

## 3. Import The First Export

Run `intake` for the first export. It creates a query and session, records the
exact JSON prompt as a used prompt pack, imports matched PDFs, links selected
papers and the run to the project, scaffolds digests, runs checks, and writes a
session report.

```fish
scholar-vault intake \
  --project bird-vocoder \
  --slug bird-vocoder-acoustic-mechanisms \
  --question "What research supports modeling psittacine vocal production with analog electronic synthesis or a vocoder-like model?" \
  --export ~/Downloads/scholar-labs-staging/bird-vocoder-prompt-1.json \
  --staging ~/Downloads/scholar-labs-staging \
  --new-session
```

Use a query slug that names the scan, not the whole project. A project can have
multiple query slugs.

## 4. Import The Second Export Into The Same Project

Use `intake --new-session` for each additional Labs prompt/export. Give it a
different query slug so the prompt/run provenance stays clear.

```fish
scholar-vault intake \
  --project bird-vocoder \
  --slug bird-vocoder-speech-imitation \
  --question "Which studies explain psittacine speech imitation and vocal-tract filtering for synthesis?" \
  --export ~/Downloads/scholar-labs-staging/bird-vocoder-prompt-2.json \
  --staging ~/Downloads/scholar-labs-staging \
  --new-session
```

If an import reports staged PDF match blockers, run:

```fish
scholar-vault intake --ui
```

Accept only the matches you trust. Then rerun the explicit `intake` command for
that export if needed.

## 5. Check The Project

```fish
scholar-vault project map bird-vocoder
scholar-vault project audit bird-vocoder
scholar-vault session list
```

The project map should show linked runs and linked papers. Undownloaded Labs
results should not appear as canonical papers.

## 6. Optional Codex Improvement Pass

This is useful when imported cards have unresolved metadata, missing abstracts,
or empty digests. It is not always necessary; if `intake` reports no blockers
and the project map looks clean, you can go directly to synthesis.

```fish
scholar-vault improve --project bird-vocoder --agent codex --budget-papers 6
```

The handoff tells Codex to work in `workspace-write`, read PDFs before claims,
fill digests only when guards pass, and leave explicit blockers for papers it
cannot process.

## 7. Ask For The Dossier

Start with a bounded pass. The agent should read the most relevant project
papers, write durable paper digests/notes, and create or update a synthesis
under `syntheses/`.

```fish
scholar-vault answer \
  --project bird-vocoder \
  --agent codex \
  --budget-papers 8 \
  "Based on the papers in this project, synthesize a detailed dossier on how to model a psittacine bird's vocal tract in a way that could be reproduced with analog electronic synthesis, similar to a vocoder."
```

If one pass is not enough, run another pass with a higher or different paper
budget, or ask the agent to continue from the next-pass task it left:

```fish
scholar-vault answer \
  --project bird-vocoder \
  --agent codex \
  --budget-papers 8 \
  "Continue the Bird Vocoder dossier from the next unread or unresolved project papers."
```

The final durable output should be a Markdown synthesis under `syntheses/`,
linked from the project and any relevant queries. Future Codex sessions should
use the paper digests, project map, and synthesis instead of repeating the same
PDF reading work.

## PDF-Only Variant

If you have PDFs but no Scholar Labs JSON export, use PDF-only intake:

```fish
scholar-vault start bird-vocoder --title "Bird Vocoder"

scholar-vault intake \
  --pdf-only \
  --project bird-vocoder \
  --slug bird-vocoder-pdf-seed \
  --question "What research supports modeling psittacine vocal production with analog electronic synthesis or a vocoder-like model?" \
  --staging ~/Downloads/scholar-labs-staging \
  --new-session
```

This path has weaker Scholar Labs provenance, but it still creates paper cards,
links them to the project/query, scaffolds digests, runs checks, and writes a
session report.
