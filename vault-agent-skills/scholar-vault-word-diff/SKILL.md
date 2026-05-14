---
name: scholar-vault-word-diff
description: Create readable full-context HTML word diffs between DOCX, Markdown, vault cards, or plain text files in this Scholar Vault, especially when line-level diffs are unreadable after shortening, paragraph merges, Google Docs exports, or proposal/card rewrites.
---

# Scholar Vault Word Diff

Use this skill when the user wants to inspect what changed between two document
drafts and a line-level diff is too noisy.

## Tool

Use the reusable script:

```sh
scripts/word_diff_html.py old-file new-file --output output/doc/<name>_full_word_diff.html
```

The script:

- supports DOCX, Markdown, and plain text inputs;
- auto-detects `.docx` and Markdown-like extensions;
- extracts DOCX text, headings, bullets, reference paragraphs, and table rows;
- extracts Markdown headings, bullets, references, tables, frontmatter, code blocks, and paragraphs;
- aligns changed, merged, or shortened blocks;
- writes one full-context HTML file only;
- marks deleted words in red and inserted words in green;
- keeps unchanged text visible so the user does not lose context.

For plain-text or Markdown files where each line should be compared separately:

```sh
scripts/word_diff_html.py old.md new.md --text-granularity line --output output/doc/<name>.html
```

The older `scripts/docx_word_diff_html.py` command remains as a compatibility
wrapper, but prefer `scripts/word_diff_html.py` for new work.

Do not create Markdown sidecar diffs unless the user explicitly asks for them.

## Verification

After running the script, confirm that the output file exists and report the
clickable HTML path. If the in-app browser cannot navigate to `file://` URLs,
give the file path instead of trying to force browser automation.
