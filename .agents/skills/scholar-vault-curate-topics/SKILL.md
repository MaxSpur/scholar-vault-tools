---
name: scholar-vault-curate-topics
description: Curate Scholar Vault navigation topics. Use when Codex is asked to clean noisy prompt-derived topics, merge duplicate topic labels, improve topic taxonomy, remove generic labels such as Find/Papers/That, or make topic pages and indexes more useful through safe paper-card frontmatter edits plus rebuild.
---

# Scholar Vault Curate Topics

Use this skill to improve the vault's navigation taxonomy while preserving paper-card records and linked PDF evidence.

## CLI Environment

Before any `scholar-vault ...` command, activate the project Conda environment in the same shell:

```fish
conda activate scholar-vault
scholar-vault runs
```

If activation is unavailable or `scholar-vault` is still not on `PATH`, use the explicit fallback:

```fish
/Users/MadMax/miniforge3/condabin/conda run -n scholar-vault scholar-vault runs
```

Do not retry plain `scholar-vault` commands without one of these environment paths.

## Topic Model

- `topics` frontmatter on `papers/*.md` stores prompt/navigation labels inferred from Scholar Labs prompts and rationale.
- `keywords` frontmatter stores publication/provider/PDF keywords. Do not mix keywords into topics unless the user explicitly wants that taxonomy change.
- `topics/*.md` and `_indexes/topics.md` are generated from paper-card frontmatter. Do not edit generated topic pages directly.
- Noisy prompt words such as `Find`, `Papers`, `That`, `Peer Reviewed`, or `Important` may be navigation noise unless the user intentionally wants them.

## Workflow

1. Read `AGENTS.md`, `_indexes/topics.md`, `_indexes/papers.md`, and relevant paper cards.
2. Identify generic labels, near-duplicates, plural/case variants, overly narrow one-off labels, and labels that mix method, task, domain, and evidence type.
3. Prefer `scholar-vault topic-map` for counts and `scholar-vault topic-map --mapping <yaml>` for broad dry-runs.
4. Propose a compact mapping before broad edits when the change affects many cards.
5. Apply agreed or obvious cleanup with `scholar-vault topic-map --mapping <yaml> --apply` when possible. For one-off edits, edit only `topics` frontmatter in `papers/*.md`.
6. Preserve paper order and other frontmatter fields as much as practical.
7. Run `scholar-vault rebuild` after manual edits so `topics/`, `_indexes/`, `_exports/`, and `llms*.txt` reflect the new taxonomy.

## Safe Defaults

Prefer a small stable taxonomy over many single-paper labels. Useful categories usually name:

- Research domain, such as `Urban Mobility`, `Immersive Analytics`, `Origin-Destination Flows`.
- Method family, such as `Trajectory Clustering`, `Flow Aggregation`, `Edge Bundling`.
- Visualization/interaction pattern, such as `Hybrid Map-Network Views`, `Collaborative XR`, `Space-Time Cubes`.
- Evaluation or evidence type, such as `Expert Evaluation`, `User Study`, `Systematic Review`.

Do not delete a specific label if it carries the only useful clue about why the paper matters. Merge it into a clearer label instead.

## Verification

Use:

```fish
conda activate scholar-vault
scholar-vault topic-map
scholar-vault topic-map --mapping <topic-map.yaml>
scholar-vault topic-map --mapping <topic-map.yaml> --apply
scholar-vault rebuild
```

Then inspect `_indexes/topics.md`, a few changed `topics/*.md`, and representative paper cards. Report the number of cards changed, labels removed/renamed, and any labels that still need human judgment.
