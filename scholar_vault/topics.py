from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from .models import SourceCard
from .obsidian import _card_id, _card_ref
from .render import render_paper_markdown
from .sources import (
    VaultPaths,
    clean_markdown_text,
    load_source_cards,
    normalize_title,
    write_text,
)

PROMPT_BOILERPLATE_TOPICS = (
    "Find",
    "Paper",
    "Papers",
    "Peer",
    "Peer Reviewed",
    "Reviewed",
    "Important",
    "That",
    "Study",
    "Studies",
    "Proposal",
    "Research",
    "Current",
    "Recent",
)
PROMPT_BOILERPLATE_TOPIC_MAP = {topic: None for topic in PROMPT_BOILERPLATE_TOPICS}
NOISY_TOPIC_KEYS = {
    normalize_title(topic)
    for topic in PROMPT_BOILERPLATE_TOPICS
} | {
    "scholar",
    "source",
    "sources",
}


def is_prompt_boilerplate_topic(topic: str) -> bool:
    return normalize_title(topic) in NOISY_TOPIC_KEYS


def _save_card(paths: VaultPaths, card: SourceCard) -> None:
    write_text(paths.papers / f"{card.slug}.md", render_paper_markdown(card))


def _rebuild_indexes(paths: VaultPaths) -> dict[str, int]:
    from .rebuild import _rebuild_indexes as rebuild_indexes

    return rebuild_indexes(paths)


def _topic_report(cards: list[SourceCard], *, limit: int = 30) -> dict[str, Any]:
    counts = Counter(topic for card in cards for topic in card.topics)
    noisy = [
        {"topic": topic, "count": count}
        for topic, count in counts.most_common()
        if is_prompt_boilerplate_topic(topic)
    ]
    return {
        "topic_count": len(counts),
        "top": [
            {"topic": topic, "count": count}
            for topic, count in counts.most_common(limit)
        ],
        "noisy": noisy,
    }


def topic_map_report(
    vault: Path | str,
    *,
    limit: int = 30,
) -> dict[str, Any]:
    paths = VaultPaths.from_root(vault)
    cards = load_source_cards(paths)
    return {"vault": str(paths.vault), **_topic_report(cards, limit=limit)}


def topic_preset_mapping(preset: str) -> dict[str, Any]:
    if preset == "prompt-boilerplate":
        return dict(PROMPT_BOILERPLATE_TOPIC_MAP)
    raise ValueError(f"Unknown topic cleanup preset: {preset}")


def _topic_replacements(value: Any) -> list[str]:
    if value is None or value is False:
        return []
    if isinstance(value, list):
        values = value
    else:
        values = [value]
    cleaned = [clean_markdown_text(str(item)) for item in values]
    return [item for item in cleaned if item]


def apply_topic_map(
    vault: Path | str,
    mapping: dict[str, Any],
    *,
    apply: bool = False,
) -> dict[str, Any]:
    paths = VaultPaths.from_root(vault)
    cards = load_source_cards(paths)
    normalized_mapping = {
        normalize_title(str(source)): _topic_replacements(target)
        for source, target in mapping.items()
        if normalize_title(str(source))
    }
    changed_cards: list[dict[str, Any]] = []
    removed_counter: Counter[str] = Counter()
    added_counter: Counter[str] = Counter()
    for card in cards:
        old_topics = list(card.topics)
        new_topics: list[str] = []
        seen: set[str] = set()
        for topic in old_topics:
            key = normalize_title(topic)
            replacements = normalized_mapping.get(key)
            if replacements is None:
                replacements = [topic]
            else:
                removed_counter[topic] += 1
            for replacement in replacements:
                replacement_key = replacement.casefold()
                if replacement_key in seen:
                    continue
                seen.add(replacement_key)
                new_topics.append(replacement)
                if replacement != topic:
                    added_counter[replacement] += 1
        if new_topics != old_topics:
            changed_cards.append(
                {
                    "citekey": _card_id(card),
                    "paper": _card_ref(card),
                    "title": card.title,
                    "before": old_topics,
                    "after": new_topics,
                }
            )
            if apply:
                card.topics = new_topics
                _save_card(paths, card)
    rebuild_summary = _rebuild_indexes(paths) if apply and changed_cards else None
    return {
        "vault": str(paths.vault),
        "applied": apply,
        "mapping": {
            source: _topic_replacements(target)
            for source, target in mapping.items()
        },
        "changed_cards": len(changed_cards),
        "changes": changed_cards,
        "removed_topics": dict(sorted(removed_counter.items())),
        "added_topics": dict(sorted(added_counter.items())),
        "rebuild": rebuild_summary,
    }
