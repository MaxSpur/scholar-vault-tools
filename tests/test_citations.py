from __future__ import annotations

from pathlib import Path

from scholar_vault.bibtex import write_library_bib
from scholar_vault.citations import (
    EnrichmentOptions,
    card_fingerprint,
    crossref_candidates,
    enrich_card,
    extract_doi_from_text,
    normalize_bibtex_for_card,
    should_skip_card,
)
from scholar_vault.models import SourceCard
from scholar_vault.sources import VaultPaths


def test_extract_doi_from_text() -> None:
    text = "Digital Object Identifier no. 10.1109/TVCG.2020.3030460."

    assert extract_doi_from_text(text) == "10.1109/tvcg.2020.3030460"


def test_skip_logic_for_verified_and_locked_papers() -> None:
    verified = SourceCard(
        slug="smith2024rag",
        citekey="smith2024rag",
        title="Evaluating Retrieval Augmented Generation Systems",
        citation_status="verified",
    )
    locked = SourceCard(
        slug="locked",
        citekey="locked",
        title="Locked Source",
        metadata_lock=True,
    )

    assert should_skip_card(verified, EnrichmentOptions()) == "citation verified"
    assert should_skip_card(locked, EnrichmentOptions()) == "metadata_lock"
    assert should_skip_card(locked, EnrichmentOptions(force=True)) is None


def test_crossref_candidate_scoring_prefers_title_author_year_match() -> None:
    card = SourceCard(
        slug="smith2024rag",
        citekey="smith2024rag",
        title="Evaluating Retrieval Augmented Generation Systems",
        authors=["Jane Smith", "Omar Lee"],
        year=2024,
    )
    payload = {
        "message": {
            "items": [
                {
                    "DOI": "10.1145/example",
                    "title": ["Evaluating Retrieval Augmented Generation Systems"],
                    "author": [{"given": "Jane", "family": "Smith"}],
                    "published-print": {"date-parts": [[2024]]},
                    "container-title": ["Test Venue"],
                },
                {
                    "DOI": "10.1145/other",
                    "title": ["Unrelated Retrieval Systems"],
                    "author": [{"given": "Alex", "family": "Other"}],
                    "published-print": {"date-parts": [[2018]]},
                },
            ]
        }
    }

    candidates = crossref_candidates(payload, card)

    assert candidates[0].doi == "10.1145/example"
    assert candidates[0].score >= 90
    assert candidates[0].score > candidates[1].score


def test_bibtex_generation_normalizes_key_and_includes_pdf_note_topics() -> None:
    card = SourceCard(
        slug="smith2024rag",
        citekey="smith2024rag",
        title="Evaluating Retrieval Augmented Generation Systems",
        authors=["Jane Smith"],
        year=2024,
        doi="10.1145/example",
        pdf="pdfs/smith2024rag.pdf",
        topics=["Evaluation"],
        summary="Short summary.",
        citation_status="generated",
    )
    raw = "@article{wrongkey,\n  title={Old Title}\n}"

    rendered = normalize_bibtex_for_card(card, raw)

    assert "@article{smith2024rag," in rendered


def test_idempotent_second_run_skips_unchanged_generated_card() -> None:
    card = SourceCard(
        slug="smith2024rag",
        citekey="smith2024rag",
        title="Evaluating Retrieval Augmented Generation Systems",
        citation_status="generated",
    )
    card.citation_input_fingerprint = card_fingerprint(card)

    assert should_skip_card(card, EnrichmentOptions()) == "fingerprint unchanged"


def test_refresh_allows_reprocessing_generated_card() -> None:
    card = SourceCard(
        slug="smith2024rag",
        citekey="smith2024rag",
        title="Evaluating Retrieval Augmented Generation Systems",
        citation_status="generated",
    )
    card.citation_input_fingerprint = card_fingerprint(card)

    assert should_skip_card(card, EnrichmentOptions(refresh=True)) is None


def test_ambiguous_candidate_behavior(tmp_path: Path) -> None:
    paths = VaultPaths.from_root(tmp_path / "vault")
    paths.ensure()
    card = SourceCard(
        slug="ambiguous",
        citekey="ambiguous",
        title="Shared Retrieval Systems",
        authors=["Jane Smith"],
        year=2024,
    )

    def fake_json(url: str, cache_path: Path, refresh: bool) -> dict | None:
        del url, refresh
        if cache_path.name == "crossref.json":
            return {
                "message": {
                    "items": [
                        {
                            "DOI": "10.1000/a",
                            "title": ["Shared Retrieval Systems"],
                            "author": [{"given": "Jane", "family": "Smith"}],
                            "published-print": {"date-parts": [[2024]]},
                        },
                        {
                            "DOI": "10.1000/b",
                            "title": ["Shared Retrieval Systems"],
                            "author": [{"given": "Jane", "family": "Smith"}],
                            "published-print": {"date-parts": [[2024]]},
                        },
                    ]
                }
            }
        return {"results": []}

    result = enrich_card(
        paths,
        card,
        EnrichmentOptions(),
        fetch_json=fake_json,
        fetch_text=lambda *_args: None,
    )

    assert result.status == "ambiguous"
    assert card.citation_status == "ambiguous"
    assert card.doi_status == "ambiguous"


def test_library_bib_exports_only_enriched_papers(tmp_path: Path) -> None:
    enriched = SourceCard(
        slug="enriched",
        citekey="enriched",
        title="Enriched Paper",
        citation_status="generated",
    )
    missing = SourceCard(
        slug="missing",
        citekey="missing",
        title="Missing Paper",
        citation_status="missing",
    )

    output = write_library_bib([enriched, missing], tmp_path / "library.bib")

    text = output.read_text(encoding="utf-8")
    assert "Enriched Paper" in text
    assert "Missing Paper" not in text


def test_library_bib_preserves_existing_entries_for_current_unenriched_papers(
    tmp_path: Path,
) -> None:
    output = tmp_path / "library.bib"
    output.write_text("@misc{missing,\n  title={Existing Missing Paper}\n}\n", encoding="utf-8")
    missing = SourceCard(
        slug="missing",
        citekey="missing",
        title="Missing Paper",
        citation_status="missing",
    )

    write_library_bib([missing], output)

    assert "Existing Missing Paper" in output.read_text(encoding="utf-8")
