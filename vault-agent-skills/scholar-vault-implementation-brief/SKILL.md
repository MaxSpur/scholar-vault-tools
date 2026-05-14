---
name: scholar-vault-implementation-brief
description: Create standalone, handoff-ready implementation briefs from Scholar Vault PDFs. Use when a user asks whether papers contain enough technical detail to implement a system, wants formulas/algorithms/pseudocode extracted from papers, wants a coding-project handoff, or complains that a synthesis mixes literature review, implementation details, and follow-up prompts.
---

# Scholar Vault Implementation Brief

Use this skill when the output must let another coding project build from the vault evidence without rereading PDFs.

## Workflow

1. Use `$scholar-vault-read-pdf` for formulas, algorithms, figures, tables, methods, implementation details, and limitations. Do not rely on Scholar Labs summaries for technical claims.
2. Separate artifact types. Do not mix a source synthesis, implementation brief, and follow-up prompts in one note.
3. Put the handoff in `syntheses/<slug>-implementation-brief.md` or another durable non-generated folder if the user specifies one.
4. Put literature/source comparison in a separate `syntheses/<slug>-source-synthesis.md`.
5. Put missing-paper prompts and research gaps in `tasks/<date>-<slug>-follow-up-prompts.md`.
6. Run `scholar-vault rebuild` after editing paper cards, syntheses, or tasks.

## Required Brief Structure

A standalone implementation brief must include:

- Goal and non-goals.
- Source list and evidence status.
- Coordinate system and assumptions.
- Exact formulas from the PDF where available.
- Engineering translations marked as translations or recommendations.
- Data structures and runtime state.
- Pseudocode or shader-style code for the core algorithm.
- Integration plan for the target stack.
- Validation checks and known failure modes.
- Missing information that needs another search or experiment.

If a paper does not provide enough formula detail, say so plainly. If you add an implementation approximation, label it as an engineering approximation rather than PDF evidence.

## Quality Bar

The brief should be useful when copied into a different Codex project by itself. Links to paper cards are for provenance and later checking, not required reading for implementation.
