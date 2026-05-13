from __future__ import annotations

from pathlib import Path
from typing import Any

from .bibtex import render_card_bibtex, write_library_bib
from .obsidian import _card_ref
from .references import REFERENCE_FORMATS, REFERENCE_STYLES, render_card_reference
from .sources import load_source_cards


def initialize_vault(vault: Path | str, *, rebuild: bool = True):
    from .importer import initialize_vault as initialize

    return initialize(vault, rebuild=rebuild)


def export_bibtex(
    vault: Path | str,
    *,
    include_local_fields: bool = True,
) -> Path:
    paths = initialize_vault(vault, rebuild=False)
    cards = load_source_cards(paths)
    return write_library_bib(
        cards,
        paths.exports / "library.bib",
        metadata_root=paths.raw_metadata,
        include_local_fields=include_local_fields,
    )


def export_card_bibtex(
    vault: Path | str,
    citekey: str,
    *,
    output: Path | str | None = None,
    include_vault_note: bool = False,
    include_local_fields: bool = True,
    cite: bool = False,
) -> dict[str, Any]:
    paths = initialize_vault(vault, rebuild=False)
    cards = load_source_cards(paths)
    card = next(
        (
            candidate
            for candidate in cards
            if citekey in {candidate.citekey, candidate.slug}
        ),
        None,
    )
    if card is None:
        raise ValueError(f"No paper card found for citekey: {citekey}")
    if cite:
        citekey_value = card.citekey or card.slug
        content = f"\\cite{{{citekey_value}}}\n"
        rendered = None
    else:
        rendered = render_card_bibtex(
            card,
            metadata_root=paths.raw_metadata,
            include_vault_note=include_vault_note,
            include_local_fields=include_local_fields,
            require_ready=False,
        )
        if rendered is None:
            raise ValueError(f"Cannot render BibLaTeX for {citekey}: missing title")
        content = rendered.entry.rstrip() + "\n"
    output_path = Path(output).expanduser().resolve() if output is not None else None
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(content, encoding="utf-8")
    return {
        "vault": str(paths.vault),
        "citekey": card.citekey or card.slug,
        "paper": _card_ref(card),
        "source": "cite" if cite else rendered.source,
        "entry_type": None if cite else rendered.entry_type,
        "warnings": [] if cite else list(rendered.warnings),
        "output": str(output_path) if output_path else None,
        "bibtex": content,
        "content": content,
        "content_kind": "cite" if cite else "biblatex",
    }


def bibtex_doctor(vault: Path | str) -> dict[str, Any]:
    paths = initialize_vault(vault, rebuild=False)
    cards = load_source_cards(paths)
    rows: list[dict[str, Any]] = []
    rendered_count = 0
    for card in cards:
        rendered = render_card_bibtex(
            card,
            metadata_root=paths.raw_metadata,
            include_vault_note=False,
            include_local_fields=True,
            require_ready=False,
        )
        if rendered is None:
            rows.append(
                {
                    "citekey": card.citekey or card.slug,
                    "paper": _card_ref(card),
                    "title": card.title,
                    "entry_type": None,
                    "source": None,
                    "warnings": ["cannot render BibLaTeX: missing title"],
                }
            )
            continue
        rendered_count += 1
        if rendered.warnings:
            rows.append(
                {
                    "citekey": card.citekey or card.slug,
                    "paper": _card_ref(card),
                    "title": card.title,
                    "entry_type": rendered.entry_type,
                    "source": rendered.source,
                    "warnings": list(rendered.warnings),
                }
            )
    return {
        "vault": str(paths.vault),
        "cards": len(cards),
        "rendered": rendered_count,
        "issues": len(rows),
        "rows": rows,
    }


def export_card_reference(
    vault: Path | str,
    citekey: str,
    *,
    output: Path | str | None = None,
    style: str = "apa",
    output_format: str = "markdown",
) -> dict[str, Any]:
    paths = initialize_vault(vault, rebuild=False)
    cards = load_source_cards(paths)
    card = next(
        (
            candidate
            for candidate in cards
            if citekey in {candidate.citekey, candidate.slug}
        ),
        None,
    )
    if card is None:
        raise ValueError(f"No paper card found for citekey: {citekey}")
    rendered = render_card_reference(
        card,
        metadata_root=paths.raw_metadata,
        style=style,
        output_format=output_format,
    )
    if rendered is None:
        raise ValueError(f"Cannot render reference for {citekey}: missing title")
    output_path = Path(output).expanduser().resolve() if output is not None else None
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered.content, encoding="utf-8")
    return {
        "vault": str(paths.vault),
        "citekey": card.citekey or card.slug,
        "paper": _card_ref(card),
        "source": rendered.source,
        "style": rendered.style,
        "format": rendered.output_format,
        "warnings": list(rendered.warnings),
        "output": str(output_path) if output_path else None,
        "content": rendered.content,
    }


def export_references(
    vault: Path | str,
    *,
    output: Path | str | None = None,
    style: str = "apa",
    output_format: str = "markdown",
) -> dict[str, Any]:
    style = style.casefold()
    output_format = output_format.casefold()
    if style not in REFERENCE_STYLES:
        raise ValueError(f"Unsupported reference style: {style}")
    if output_format not in REFERENCE_FORMATS:
        raise ValueError(f"Unsupported reference format: {output_format}")
    paths = initialize_vault(vault, rebuild=False)
    cards = load_source_cards(paths)
    rendered_entries = []
    rows: list[dict[str, Any]] = []
    for card in sorted(cards, key=lambda item: (item.authors[0] if item.authors else item.title)):
        rendered = render_card_reference(
            card,
            metadata_root=paths.raw_metadata,
            style=style,
            output_format=output_format,
            wrap_rtf=False,
        )
        if rendered is None:
            rows.append(
                {
                    "citekey": card.citekey or card.slug,
                    "paper": _card_ref(card),
                    "warnings": ["cannot render reference: missing title"],
                }
            )
            continue
        rendered_entries.append(rendered.content.rstrip())
        if rendered.warnings:
            rows.append(
                {
                    "citekey": card.citekey or card.slug,
                    "paper": _card_ref(card),
                    "warnings": list(rendered.warnings),
                }
            )
    extension = {"markdown": "md", "plain": "txt", "rtf": "rtf"}[output_format]
    output_path = (
        Path(output).expanduser().resolve()
        if output is not None
        else paths.exports / f"references-{style}.{extension}"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_format == "rtf":
        content = r"{\rtf1\ansi " + "\n".join(rendered_entries).rstrip() + "\n}\n"
    else:
        content = "\n\n".join(rendered_entries).rstrip() + "\n"
    output_path.write_text(content, encoding="utf-8")
    return {
        "vault": str(paths.vault),
        "style": style,
        "format": output_format,
        "output": str(output_path),
        "references": len(rendered_entries),
        "warnings": rows,
    }
