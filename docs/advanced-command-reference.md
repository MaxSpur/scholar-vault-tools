# Advanced Command Reference

This reference keeps lower-level commands out of the main tutorial. The normal
path is `ask -> intake -> answer`; use this file when you need a specific
internal step, repair workflow, or diagnostic.

## Scholar Labs And Prompt Packs

```fish
scholar-vault labs-prompts generate --query mobility-evidence
scholar-vault labs-prompts generate --project map-lens-deformation
scholar-vault labs-prompts generate --from-gaps
scholar-vault labs-prompts generate --query mobility-evidence --seed-api openalex
scholar-vault labs-prompts list
scholar-vault labs-prompts show query-mobility-evidence-scholar-labs-prompts
scholar-vault labs-prompts mark-used query-mobility-evidence-scholar-labs-prompts
scholar-vault labs-prompts link-run query-mobility-evidence-scholar-labs-prompts 2026-05-15_mobility
scholar-vault labs-prompts retire query-mobility-evidence-scholar-labs-prompts
scholar-vault labs-prompts doctor --json
```

Prompt packs are discovery-planning artifacts. They may use OpenAlex or
Semantic Scholar to improve wording, but those API candidates are not canonical
sources.

For a Scholar Labs search you already ran yourself, prefer `intake` over the
lower-level importer. The JSON export includes the exact top-level `prompt`;
`intake` can use that prompt to create the query/session when you provide
project/query metadata or `--new-session`:

```fish
scholar-vault start budgie-vocoder \
  "Which acoustic evidence supports a budgerigar synthesizer?" \
  --title "Budgerigar Vocoder" \
  --slug budgie-vocoder-scan \
  --export ~/Downloads/scholar-labs-budgerigar.json \
  --staging ~/Downloads/budgie-pdfs

# Equivalent explicit form:
scholar-vault intake \
  --project budgie-vocoder \
  --slug budgie-vocoder-scan \
  --question "Which acoustic evidence supports a budgerigar synthesizer?" \
  --export ~/Downloads/scholar-labs-budgerigar.json \
  --staging ~/Downloads/budgie-pdfs \
  --new-session
```

Here `budgie-vocoder` is the project slug and `budgie-vocoder-scan` is the
query slug for `queries/budgie-vocoder-scan.md`. `intake` records the exact
JSON prompt as a used prompt pack under that query and links it to the imported
run.

Import a specific Labs export directly when bypassing `intake`:

```fish
scholar-vault import-labs --export ~/Downloads/labs.json --staging ~/Downloads/scholar-labs-staging --commit
scholar-vault import-labs --ui
scholar-vault import-labs --commit --prompt-pack query-mobility-evidence-scholar-labs-prompts --query mobility-evidence
scholar-vault import-labs --commit --no-enrich
scholar-vault import-labs --dry-run
scholar-vault import-labs --commit --title "Immersive Analytics Sources"
scholar-vault import-labs --commit --include-without-pdf
scholar-vault import-labs --commit --keep-export
```

The compatibility alias `scholar-vault import` behaves like `import-labs`.
`import-run` is the lower-level transactional variant that copies accepted PDFs
but leaves staging cleanup to later commands.

## Graph-Assisted Discovery

```fish
scholar-vault discover seed --citekey <citekey> --source openalex,semantic-scholar
scholar-vault discover query --query <query-slug> --source openalex,semantic-scholar
scholar-vault discover project --project <project-slug> --source openalex,semantic-scholar
scholar-vault discover list
scholar-vault discover select <candidate-id>
scholar-vault discover reject <candidate-id>
scholar-vault discover to-labs-prompts --query <query-slug>
scholar-vault discover doctor --json
```

Discovery candidates are YAML records under `tasks/discovery-candidates/`.
They deduplicate against canonical cards by DOI and exact normalized title and
become prompt-pack seeds only.

## Direct PDF, BibTeX, And DOI Imports

```fish
scholar-vault import-pdf --ui
scholar-vault import-pdf --staging ~/Downloads/scholar-labs-staging
scholar-vault import-pdf --no-enrich
scholar-vault import-bibtex --bib ~/Downloads/library.bib
scholar-vault import-doi --doi 10.1145/3544548.3580848
```

Direct PDF imports copy PDFs into `pdfs/`, create or update canonical
`papers/*.md` cards, run enrichment by default, and keep the original downloads
where they are.

When the PDFs belong to a query/project and there is no Labs JSON, prefer
PDF-only intake:

```fish
scholar-vault intake --pdf-only --project budgie-vocoder --slug budgie-vocoder-pdf-seed --question "Which acoustic evidence supports a budgerigar synthesizer?" --staging ~/Downloads/budgie-pdfs --new-session
```

This imports PDFs, links imported citekeys to the query/project, and scaffolds
digests. Use lower-level linking only when repairing or curating existing
imports:

```fish
scholar-vault query link-paper budgie-vocoder-pdf-seed <citekey>
scholar-vault project link-paper budgie-vocoder <citekey>
scholar-vault compile scaffold --citekey <citekey>
```

## Sessions And Codex Handoffs

```fish
scholar-vault session current
scholar-vault session list
scholar-vault session show <session-id>
scholar-vault session archive <session-id>
scholar-vault codex handoff --kind post-import
scholar-vault codex handoff --kind improve --budget-papers 5
scholar-vault codex handoff --kind answer --question "What evidence supports this claim?"
scholar-vault codex run --kind improve --budget-papers 5
```

Handoffs are stored under `_handoffs/`. Codex runs use
`--sandbox workspace-write` by default.

## Diagnostics And Maintenance

```fish
scholar-vault status
scholar-vault status --json
scholar-vault doctor
scholar-vault git-summary
scholar-vault maintenance-report
scholar-vault maintenance-report --write-queue
scholar-vault lint-wiki
scholar-vault lint-wiki --json
scholar-vault lint-wiki --write-queue --write-report
scholar-vault eval list
scholar-vault eval run
scholar-vault eval run --kind retrieval
scholar-vault eval run --write-queue
scholar-vault eval report
scholar-vault schema export
```

These commands report or queue structural issues. They do not prove scientific
truth and do not rewrite scientific prose.

## Query, Compile, Bases, And Obsidian

```fish
scholar-vault query create "How do collaborative map workbenches support mobility decisions?" --project map-lens-deformation --slug collaborative-map-workbenches
scholar-vault query list
scholar-vault query show collaborative-map-workbenches
scholar-vault query link-paper collaborative-map-workbenches Schottler2021_GeospatialNetworks
scholar-vault query link-run collaborative-map-workbenches 2026-05-01_mobility
scholar-vault query link-synthesis collaborative-map-workbenches syntheses/mobility-workbenches.md
scholar-vault query status collaborative-map-workbenches
scholar-vault query rename OLD NEW
scholar-vault query archive collaborative-map-workbenches
scholar-vault query doctor --fix
scholar-vault compile status
scholar-vault compile scaffold --run 2026-05-01_mobility --selected-only
scholar-vault compile queue --project map-lens-deformation
scholar-vault compile mark <citekey> --status compiled
scholar-vault compile doctor
scholar-vault bases rebuild
scholar-vault bases doctor --json
scholar-vault obsidian setup --dry-run
scholar-vault obsidian setup --apply
scholar-vault obsidian doctor --json
```

Query notes and Bases are workbench overlays over the same canonical PDFs,
paper cards, runs, syntheses, tasks, and projects.

## Projects And Proposals

```fish
scholar-vault project ui
scholar-vault project scaffold map-lens-deformation
scholar-vault project link-paper map-lens-deformation Schottler2021_GeospatialNetworks
scholar-vault project link-concept map-lens-deformation concepts/flow-maps.md
scholar-vault project link-synthesis map-lens-deformation syntheses/flow-maps.md
scholar-vault project link-run map-lens-deformation 2026-05-01_mobility
scholar-vault project link-task map-lens-deformation tasks/2026-05-22-maintenance.md
scholar-vault project link-proposal map-lens-deformation pepr-mobidec
scholar-vault project map map-lens-deformation
scholar-vault project audit map-lens-deformation
scholar-vault proposal-sprint scaffold pepr-mobidec
scholar-vault proposal-audit proposals/pepr-mobidec
scholar-vault proposal-audit proposals/pepr-mobidec --json
```

Projects are lenses over shared vault records. Proposals are proposal-specific
workspaces with outlines, source matrices, reading logs, and raw idea notes.

## Enrichment And Manual Metadata

```fish
scholar-vault enrich
scholar-vault enrich --ui
scholar-vault enrich --citekey smith2024rag
scholar-vault enrich --only missing-doi
scholar-vault enrich --only missing-bibtex
scholar-vault enrich --only missing-abstract
scholar-vault enrich --only missing-keywords
scholar-vault enrich --refresh
scholar-vault enrich --refresh-abstracts
scholar-vault enrich --retry-failed
scholar-vault enrich --dry-run
scholar-vault resolve-citation --citekey smith2024rag --doi 10.1145/example --authors "Jane Smith; John Doe" --year 2024 --venue "Example Venue"
scholar-vault set-metadata --citekey smith2024rag --venue "Example Venue" --lock
scholar-vault set-abstract --citekey smith2024rag --file ~/Downloads/abstract.txt --source-url https://doi.org/10.1145/example
scholar-vault set-keywords --citekey smith2024rag --text "Immersive Analytics; Collaboration; Usability Study"
```

Enrichment processes canonical `papers/*.md` only. Abstracts are provider/PDF
metadata in `## Abstract`; they are not Scholar Labs summaries. Metadata and
abstract locks protect curated fields from automatic overwrites.

## Runs And Staging Repair

```fish
scholar-vault runs
scholar-vault runs --limit 10
scholar-vault resume --run 2026-04-22_example-prompt
scholar-vault rerun --commit
scholar-vault rerun --run 2026-04-22_example-prompt --commit
scholar-vault rerun --ui
scholar-vault pdf-doctor --staging ~/Downloads/scholar-labs-staging
scholar-vault pdf-doctor --staging ~/Downloads/scholar-labs-staging --json
scholar-vault match-staging
scholar-vault match-staging --title "Origin-destination flow data smoothing and mapping"
scholar-vault match-staging --pdf ~/Downloads/scholar-labs-staging/example.pdf --unselected-only
scholar-vault match-staging --ui
scholar-vault rename-run --run 2026-04-22_example-prompt --title "Immersive Analytics Sources"
scholar-vault undo --run 2026-04-22_example-prompt
scholar-vault attach-pdf --citekey smith2024rag --pdf ~/Downloads/example.pdf
scholar-vault unmatched
scholar-vault clean-staging --staging ~/Downloads/scholar-labs-staging
scholar-vault cleanup-run --run 2026-04-22_example-prompt --selected-only
```

`pdf-doctor` and terminal `match-staging` are read-only. The staging UI imports
one chosen PDF into one chosen run result and archives the staging original only
after the vault copy verifies.

## Topics, Bibliographies, And References

```fish
scholar-vault topic-map
scholar-vault topic-map --json
scholar-vault topic-map --preset prompt-boilerplate
scholar-vault topic-map --preset prompt-boilerplate --apply
scholar-vault topic-map --mapping ~/Downloads/topic-map.yaml
scholar-vault biblatex
scholar-vault bibtex
scholar-vault card-biblatex smith2024rag
scholar-vault card-biblatex --clipboard smith2024rag
scholar-vault card-biblatex --cite --clipboard smith2024rag
scholar-vault card-biblatex --validate smith2024rag
scholar-vault biblatex-doctor --json
scholar-vault reference smith2024rag
scholar-vault reference --format rtf --output ~/Desktop/smith2024rag.rtf smith2024rag
scholar-vault references
scholar-vault references --format rtf --output ~/Desktop/references.rtf
```

BibLaTeX export is provider-first but vault-aware. Formatted references are for
copy/paste bibliographies and drafts.

## Skill Synchronization

```fish
scholar-vault skills diff --vault ~/Documents/Research/scholar-labs-vault
scholar-vault skills ui --vault ~/Documents/Research/scholar-labs-vault
scholar-vault skills adopt scholar-vault-proposal-evidence-sprint --vault ~/Documents/Research/scholar-labs-vault --apply
scholar-vault skills adopt AGENTS.md --vault ~/Documents/Research/scholar-labs-vault --apply --force
scholar-vault skills publish --vault ~/Documents/Research/scholar-labs-vault --apply
scholar-vault skills install-external obsidian-skills --vault ~/Documents/Research/scholar-labs-vault --apply
scholar-vault skills update-external obsidian-skills --vault ~/Documents/Research/scholar-labs-vault --apply
```

Repository-owned vault-agent skills live in `vault-agent-skills/` and publish
into a vault's `.agents/skills/`. External skills remain external upstream
content and are tracked with manifests under `.external-sources/`.

## Reset

```fish
scholar-vault reset --vault ~/Documents/Research/scholar-labs-vault
scholar-vault reset --vault ~/Documents/Research/scholar-labs-vault --yes
```

`reset` clears vault-managed state inside the vault only. It does not touch
external download folders.
