#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from pdfminer.high_level import extract_text


def parse_pages(value: str | None, max_pages: int | None) -> list[int] | None:
    if value:
        pages: set[int] = set()
        for part in value.split(","):
            item = part.strip()
            if not item:
                continue
            if "-" in item:
                start, end = item.split("-", 1)
                pages.update(range(int(start) - 1, int(end)))
            else:
                pages.add(int(item) - 1)
        return sorted(page for page in pages if page >= 0)
    if max_pages:
        return list(range(max_pages))
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract text from a Scholar Vault PDF.")
    parser.add_argument("pdf", type=Path, help="PDF path to read.")
    parser.add_argument("--pages", help="1-based page list/ranges, e.g. 1-3,8,12.")
    parser.add_argument("--max-pages", type=int, help="Extract the first N pages.")
    parser.add_argument("--head-chars", type=int, help="Print only the first N characters.")
    parser.add_argument("--output", type=Path, help="Write text to this file instead of stdout.")
    args = parser.parse_args()

    page_numbers = parse_pages(args.pages, args.max_pages)
    text = extract_text(str(args.pdf.expanduser()), page_numbers=page_numbers)
    if args.head_chars:
        text = text[: args.head_chars]
    if args.output:
        args.output.expanduser().write_text(text, encoding="utf-8")
    else:
        print(text, end="" if text.endswith("\n") else "\n")


if __name__ == "__main__":
    main()
