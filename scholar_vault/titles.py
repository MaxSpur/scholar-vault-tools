from __future__ import annotations

import re

SCHOLAR_RESOURCE_PREFIX_RE = re.compile(r"^(?:\[(?:HTML|PDF)\]\s*)+", re.IGNORECASE)


def clean_paper_title(title: str | None) -> str:
    if not title:
        return ""
    normalized = (
        str(title)
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\u00a0", " ")
        .strip()
    )
    normalized = re.sub(r"\s+", " ", normalized)
    stripped = SCHOLAR_RESOURCE_PREFIX_RE.sub("", normalized).strip()
    return stripped or normalized
