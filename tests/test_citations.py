from __future__ import annotations

import json
from pathlib import Path

from scholar_vault.bibtex import render_card_bibtex, write_library_bib
from scholar_vault.citations import (
    CitationCandidate,
    EnrichmentOptions,
    EnrichmentResult,
    _candidate_is_consistent,
    _promote_metadata_from_candidate,
    abstract_fingerprint,
    abstract_looks_truncated,
    card_fingerprint,
    clean_provider_abstract,
    crossref_candidates,
    detect_local_doi,
    enrich_abstract_card,
    enrich_card,
    enrich_cards,
    extract_doi_from_text,
    extract_pdf_abstract,
    extract_pdf_keywords,
    normalize_bibtex_for_card,
    openalex_abstract_candidates,
    reconstruct_openalex_abstract,
    should_skip_abstract_card,
    should_skip_card,
)
from scholar_vault.importer import enrich_citations, initialize_vault
from scholar_vault.models import SourceCard
from scholar_vault.render import render_paper_markdown
from scholar_vault.sources import VaultPaths


def test_extract_doi_from_text() -> None:
    text = "Digital Object Identifier no. 10.1109/TVCG.2020.3030460."

    assert extract_doi_from_text(text) == "10.1109/tvcg.2020.3030460"


def test_detect_local_doi_from_pdf_text(tmp_path: Path, monkeypatch) -> None:
    paths = VaultPaths.from_root(tmp_path / "vault")
    paths.ensure()
    pdf = paths.pdfs / "source.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    card = SourceCard(slug="source", title="Source", pdf="pdfs/source.pdf")
    monkeypatch.setattr("scholar_vault.citations.read_pdf_metadata", lambda _path: {})
    monkeypatch.setattr(
        "scholar_vault.citations.extract_pdf_text_excerpt",
        lambda _path: "Digital Object Identifier 10.1145/3440207",
    )

    doi, source, confidence = detect_local_doi(paths, card)

    assert doi == "10.1145/3440207"
    assert source == "pdf_text"
    assert confidence == 0.95


def test_exact_doi_candidate_promotes_published_metadata_despite_title_change() -> None:
    card = SourceCard(
        slug="mokbel2023towardsmobilitydatasciencevision",
        citekey="mokbel2023towardsmobilitydatasciencevision",
        title="Towards mobility data science (vision paper)",
        authors=["Mohamed F. Mokbel", "Mahmoud Sakr"],
        year=2023,
        venue="arXiv preprint arXiv:2307.05717, 2023",
        doi="10.1145/3652158",
    )
    candidate = CitationCandidate(
        doi="10.1145/3652158",
        title="Mobility Data Science: Perspectives and Challenges",
        authors=["Mohamed F. Mokbel", "Mahmoud Sakr"],
        year=2024,
        venue="ACM Transactions on Spatial Algorithms and Systems",
        source="doi-csl",
        score=41,
    )

    assert _candidate_is_consistent(card, candidate)
    assert _promote_metadata_from_candidate(card, candidate)
    assert card.title == "Mobility Data Science: Perspectives and Challenges"
    assert card.year == 2024
    assert card.venue == "ACM Transactions on Spatial Algorithms and Systems"


def test_exact_doi_candidate_rejects_incompatible_first_author() -> None:
    card = SourceCard(
        slug="source",
        title="Towards mobility data science (vision paper)",
        authors=["Mohamed F. Mokbel"],
        year=2023,
        doi="10.1145/3652158",
    )
    candidate = CitationCandidate(
        doi="10.1145/3652158",
        title="Mobility Data Science: Perspectives and Challenges",
        authors=["Someone Else"],
        year=2024,
        venue="ACM Transactions on Spatial Algorithms and Systems",
        source="doi-csl",
        score=41,
    )

    assert not _candidate_is_consistent(card, candidate)
    assert not _promote_metadata_from_candidate(card, candidate)
    assert card.title == "Towards mobility data science (vision paper)"


def test_enrich_card_extracts_pdf_keywords(tmp_path: Path, monkeypatch) -> None:
    paths = VaultPaths.from_root(tmp_path / "vault")
    paths.ensure()
    pdf = paths.pdfs / "source.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    card = SourceCard(slug="source", title="Source", pdf="pdfs/source.pdf")
    monkeypatch.setattr("scholar_vault.citations.read_pdf_metadata", lambda _path: {})
    monkeypatch.setattr(
        "scholar_vault.citations.extract_pdf_text_excerpt",
        lambda _path: (
            "Keywords: Immersive Analytics · Collaboration · Usability Study\n"
            "1\n\nIntroduction"
        ),
    )

    enrich_card(
        paths,
        card,
        EnrichmentOptions(),
        fetch_json=lambda _url, _cache, _refresh: None,
        fetch_text=lambda _url, _cache, _refresh, _headers: None,
    )

    assert card.keywords == ["Immersive Analytics", "Collaboration", "Usability Study"]


def test_pdf_abstract_extraction_ignores_later_sections() -> None:
    text = """
Title

Abstract
This paper presents a careful system for collaborative analytics. It studies users,
tasks, and visual analysis workflows in enough detail to be a plausible abstract
for a research source card in the vault.

1 Introduction
This should not be included.
"""

    extracted = extract_pdf_abstract(text)

    assert "This paper presents" in extracted
    assert "Introduction" not in extracted


def test_pdf_abstract_extraction_accepts_springer_run_in_heading() -> None:
    text = """
Are We There Yet? Unravelling Usability Challenges

Abstract. In the ever-evolving discipline of high-dimensional scientific
data, collaborative immersive analytics (CIA) offers a promising fron-
tier for domain experts in complex data visualization and interpretation.
This research presents a comprehensive framework for conducting us-
ability studies on an extended reality interface for collaborative analysis.

Keywords: Immersive Analytics

1

Introduction
This should not be included.
"""

    extracted = extract_pdf_abstract(text)

    assert extracted.startswith(
        "In the ever-evolving discipline of high-dimensional scientific data"
    )
    assert "frontier" in extracted
    assert "usability studies" in extracted
    assert "Keywords" not in extracted
    assert "Introduction" not in extracted


def test_pdf_abstract_extraction_rejects_truncated_snippet() -> None:
    text = """
Title

Abstract
The study of movement is progressing rapidly as a subdiscipline in Geographic
Information Science. At the fulcrum of this new research area are movement
observations. Movem...

1 Introduction
This should not be included.
"""

    assert abstract_looks_truncated(
        "The study of movement is progressing rapidly. Movem..."
    )
    assert extract_pdf_abstract(text) == ""


def test_pdf_keyword_extraction_accepts_springer_keywords() -> None:
    text = """
Abstract. A useful abstract appears here with enough words to pass extraction.

Keywords: Immersive Analytics · Collaboration · Usability Study · Sci-
entific Data Visualization

1

Introduction
This should not be included.
"""

    assert extract_pdf_keywords(text) == [
        "Immersive Analytics",
        "Collaboration",
        "Usability Study",
        "Scientific Data Visualization",
    ]


def test_pdf_keyword_extraction_accepts_index_terms() -> None:
    text = """
TrajGraph: A Graph-Based Visual Analytics Approach

Index Terms--Taxi trajectory data; urban network centrality; visual analytics;
graph-based interaction

1 Introduction
This should not be included.
"""

    assert extract_pdf_keywords(text) == [
        "Taxi trajectory data",
        "urban network centrality",
        "visual analytics",
        "graph-based interaction",
    ]


def test_crossref_abstract_parsing_cleans_jats_markup() -> None:
    raw = "<jats:p>This &amp; that <jats:italic>matters</jats:italic>.</jats:p>"

    assert clean_provider_abstract(raw) == "This & that matters."


def test_openalex_abstract_inverted_index_reconstruction() -> None:
    inverted = {"This": [0], "abstract": [2], "is": [1], "ordered": [3]}

    assert reconstruct_openalex_abstract(inverted) == "This is abstract ordered"


def test_openalex_abstract_candidates_use_reconstructed_source() -> None:
    card = SourceCard(
        slug="smith2024rag",
        citekey="smith2024rag",
        title="Evaluating Retrieval Augmented Generation Systems",
        authors=["Jane Smith"],
        year=2024,
        doi="10.1145/example",
    )
    payload = {
        "results": [
            {
                "title": "Evaluating Retrieval Augmented Generation Systems",
                "doi": "https://doi.org/10.1145/example",
                "publication_year": 2024,
                "abstract_inverted_index": {"A": [0], "useful": [1], "abstract": [2]},
                "authorships": [{"author": {"display_name": "Jane Smith"}}],
            }
        ]
    }

    candidates = openalex_abstract_candidates(payload, card)

    assert candidates[0].source == "openalex_reconstructed"
    assert candidates[0].text == "A useful abstract"


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


def test_skip_logic_for_abstract_lock_and_verified_abstract() -> None:
    verified = SourceCard(
        slug="verified",
        citekey="verified",
        title="Verified Abstract",
        abstract="A verified abstract.",
        abstract_status="verified",
        abstract_source="crossref",
    )
    verified.abstract_input_fingerprint = abstract_fingerprint(verified)
    locked = SourceCard(
        slug="locked",
        citekey="locked",
        title="Locked Abstract",
        abstract="Manual abstract.",
        abstract_lock=True,
    )

    assert (
        should_skip_abstract_card(verified, EnrichmentOptions(abstracts=True))
        == "abstract fingerprint unchanged"
    )
    assert (
        should_skip_abstract_card(locked, EnrichmentOptions(abstracts=True))
        == "abstract_lock"
    )
    assert should_skip_abstract_card(locked, EnrichmentOptions(abstracts=True, force=True)) is None


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
                    "subject": ["Retrieval", "Evaluation"],
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
    assert candidates[0].keywords == ("Retrieval", "Evaluation")
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


def test_bibtex_normalization_converts_raw_provider_unicode_punctuation() -> None:
    card = SourceCard(
        slug="oneil2025maps",
        citekey="oneil2025maps",
        title="Card Title",
        citation_status="generated",
    )
    raw = (
        "@article{wrongkey,\n"
        "  title={O’Neil’s 3–D maps — evidence…},\n"
        "  author={José O’Neil},\n"
        "  year={2025}\n"
        "}\n"
    )

    rendered = normalize_bibtex_for_card(card, raw)

    assert all(ord(char) < 128 for char in rendered)
    assert "@article{oneil2025maps," in rendered
    assert "title = {O'Neil's 3--D maps --- evidence...}" in rendered
    assert r"author = {Jos{\'e} O'Neil}" in rendered


def test_library_bib_uses_paper_keywords_not_navigation_topics(tmp_path: Path) -> None:
    card = SourceCard(
        slug="smith2024rag",
        citekey="smith2024rag",
        title="Evaluating Retrieval Augmented Generation Systems",
        topics=["Evaluation Topic"],
        keywords=["Retrieval", "Benchmarking"],
        citation_status="generated",
    )

    output = write_library_bib([card], tmp_path / "library.bib")
    rendered = output.read_text(encoding="utf-8")

    assert "keywords = {Retrieval, Benchmarking}" in rendered
    assert "Evaluation Topic" not in rendered


def test_doi_csl_promotes_canonical_venue_and_metadata(tmp_path: Path) -> None:
    paths = VaultPaths.from_root(tmp_path / "vault")
    paths.ensure()
    card = SourceCard(
        slug="jackson2024workspaceguardianinvestigatingawarenesspersonal",
        citekey="jackson2024workspaceguardianinvestigatingawarenesspersonal",
        title=(
            "Workspace guardian: Investigating awareness of personal workspace between "
            "co-located augmented reality users"
        ),
        authors=["B Jackson", "L Lor", "BC Heggeseth"],
        year=2024,
        venue="IEEE Transactions on …, 2024",
        doi="10.1109/tvcg.2024.3372073",
        url="https://scholar.googleusercontent.com/scholar.bib?q=info:o_l28irQlOwJ:scholar.google.com/&output=citation",
        citation_status="verified",
    )
    csl = {
        "title": (
            "Workspace Guardian: Investigating Awareness of Personal Workspace Between "
            "Co-Located Augmented Reality Users"
        ),
        "container-title": "IEEE Transactions on Visualization and Computer Graphics",
        "issued": {"date-parts": [[2024, 5]]},
        "DOI": "10.1109/tvcg.2024.3372073",
        "URL": "http://dx.doi.org/10.1109/tvcg.2024.3372073",
        "author": [
            {"given": "Bret", "family": "Jackson"},
            {"given": "Linda", "family": "Lor"},
            {"given": "Brianna C.", "family": "Heggeseth"},
        ],
    }

    def fake_text(url: str, cache_path: Path, refresh: bool, headers: dict[str, str]) -> str | None:
        del url, refresh
        accept = headers.get("Accept")
        if accept == "application/vnd.citationstyles.csl+json":
            cache_path.write_text(json.dumps(csl), encoding="utf-8")
            return json.dumps(csl)
        if accept == "application/x-bibtex":
            return "@article{Jackson_2024, title={Workspace Guardian}}"
        return None

    result = enrich_card(
        paths,
        card,
        EnrichmentOptions(refresh=True),
        fetch_json=lambda *_args: None,
        fetch_text=fake_text,
    )

    assert result.status == "verified"
    assert card.title == csl["title"]
    assert card.authors == ["Bret Jackson", "Linda Lor", "Brianna C. Heggeseth"]
    assert card.venue == "IEEE Transactions on Visualization and Computer Graphics"
    assert card.url == "http://dx.doi.org/10.1109/tvcg.2024.3372073"
    assert card.citation_input_fingerprint == card_fingerprint(card)


def test_preprint_doi_can_upgrade_to_published_version_with_venue(tmp_path: Path) -> None:
    paths = VaultPaths.from_root(tmp_path / "vault")
    paths.ensure()
    card = SourceCard(
        slug="saffo2023unravelingdesignspaceimmersiveanalytics",
        citekey="saffo2023unravelingdesignspaceimmersiveanalytics",
        title="Unraveling the Design Space of Immersive Analytics: A Systematic Review",
        authors=["David Saffo", "Sara Di Bartolomeo"],
        year=2023,
        venue="… on Visualization and …, 2023",
        doi="10.31219/osf.io/2e9x4",
        citation_status="verified",
    )
    osf_csl = {
        "title": card.title,
        "DOI": "10.31219/osf.io/2e9x4",
        "issued": {"date-parts": [[2023, 8, 7]]},
        "author": [{"given": "David", "family": "Saffo"}],
    }
    ieee_csl = {
        "title": card.title,
        "DOI": "10.1109/tvcg.2023.3327368",
        "container-title": "IEEE Transactions on Visualization and Computer Graphics",
        "issued": {"date-parts": [[2024, 1]]},
        "URL": "https://doi.org/10.1109/tvcg.2023.3327368",
        "author": [
            {"given": "David", "family": "Saffo"},
            {"given": "Sara", "family": "Di Bartolomeo"},
        ],
    }
    crossref_search = {
        "message": {
            "items": [
                {
                    "DOI": "10.31219/osf.io/2e9x4",
                    "title": [card.title],
                    "author": [{"given": "David", "family": "Saffo"}],
                    "published-print": {"date-parts": [[2023]]},
                    "type": "posted-content",
                },
                {
                    "DOI": "10.1109/tvcg.2023.3327368",
                    "title": [card.title],
                    "author": [
                        {"given": "David", "family": "Saffo"},
                        {"given": "Sara", "family": "Di Bartolomeo"},
                    ],
                    "published-print": {"date-parts": [[2024]]},
                    "container-title": [
                        "IEEE Transactions on Visualization and Computer Graphics"
                    ],
                    "type": "journal-article",
                    "URL": "https://doi.org/10.1109/tvcg.2023.3327368",
                },
            ]
        }
    }

    def fake_json(url: str, cache_path: Path, refresh: bool) -> dict | None:
        del url, refresh
        if cache_path.name == "crossref-search.json":
            return crossref_search
        return None

    def fake_text(url: str, cache_path: Path, refresh: bool, headers: dict[str, str]) -> str | None:
        del cache_path, refresh
        if headers.get("Accept") == "application/x-bibtex":
            return "@article{saffo2023, title={Unraveling the Design Space}}"
        if headers.get("Accept") == "application/vnd.citationstyles.csl+json":
            return json.dumps(ieee_csl if "10.1109" in url else osf_csl)
        return None

    result = enrich_card(
        paths,
        card,
        EnrichmentOptions(refresh=True),
        fetch_json=fake_json,
        fetch_text=fake_text,
    )

    assert result.status == "verified"
    assert card.doi == "10.1109/tvcg.2023.3327368"
    assert card.venue == "IEEE Transactions on Visualization and Computer Graphics"
    assert card.enrichment_status == "complete"
    assert card.enrichment_missing == []


def test_incomplete_enrichment_marks_preview_venue() -> None:
    card = SourceCard(
        slug="preview",
        citekey="preview",
        title="Preview Venue Paper",
        authors=["Jane Smith"],
        year=2024,
        venue="IEEE Transactions on …, 2024",
        doi="10.1145/example",
        citation_status="generated",
    )

    def fake_text(url: str, cache_path: Path, refresh: bool, headers: dict[str, str]) -> str | None:
        del url, cache_path, refresh
        if headers.get("Accept") == "application/vnd.citationstyles.csl+json":
            return json.dumps(
                {
                    "title": card.title,
                    "DOI": card.doi,
                    "issued": {"date-parts": [[2024]]},
                    "author": [{"given": "Jane", "family": "Smith"}],
                }
            )
        return "@misc{preview, title={Preview Venue Paper}}"

    result = enrich_card(
        VaultPaths.from_root(Path("/tmp/nonexistent-vault")),
        card,
        EnrichmentOptions(refresh=True),
        fetch_json=lambda *_args: None,
        fetch_text=fake_text,
    )

    assert result.changed is True
    assert card.enrichment_status == "incomplete"
    assert card.enrichment_missing == ["venue"]
    assert card.citation_skip_reason == "incomplete metadata: venue"


def test_enrichment_refresh_flag_overrides_verified_skip() -> None:
    card = SourceCard(
        slug="refresh",
        citekey="refresh",
        title="Refresh Paper",
        citation_status="verified",
        enrichment_refresh=True,
    )

    assert should_skip_card(card, EnrichmentOptions()) is None


def test_enrichment_refresh_flag_forces_provider_cache_refresh(tmp_path: Path) -> None:
    paths = VaultPaths.from_root(tmp_path / "vault")
    paths.ensure()
    card = SourceCard(
        slug="refresh",
        citekey="refresh",
        title="Refresh Paper",
        authors=["Jane Smith"],
        year=2024,
        doi="10.1145/example",
        citation_status="verified",
        enrichment_refresh=True,
    )
    refresh_values: list[bool] = []

    def fake_text(url: str, cache_path: Path, refresh: bool, headers: dict[str, str]) -> str | None:
        del url, cache_path
        refresh_values.append(refresh)
        if headers.get("Accept") == "application/vnd.citationstyles.csl+json":
            return json.dumps(
                {
                    "title": "Refresh Paper",
                    "DOI": "10.1145/example",
                    "issued": {"date-parts": [[2024]]},
                    "author": [{"given": "Jane", "family": "Smith"}],
                    "container-title": "Journal of Refresh Testing",
                }
            )
        return "@article{refresh, title={Refresh Paper}}"

    result = enrich_card(
        paths,
        card,
        EnrichmentOptions(),
        fetch_json=lambda *_args: None,
        fetch_text=fake_text,
    )

    assert result.status == "verified"
    assert refresh_values and all(refresh_values)
    assert card.enrichment_refresh is False


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


def test_citation_enrichment_progress_reports_provider_passes(tmp_path: Path) -> None:
    paths = VaultPaths.from_root(tmp_path / "vault")
    paths.ensure()
    card = SourceCard(
        slug="smith2024rag",
        citekey="smith2024rag",
        title="Evaluating Retrieval Augmented Generation Systems",
        authors=["Jane Smith"],
        year=2024,
    )
    crossref_payload = {
        "message": {
            "items": [
                {
                    "DOI": "10.1145/example",
                    "title": ["Evaluating Retrieval Augmented Generation Systems"],
                    "author": [{"given": "Jane", "family": "Smith"}],
                    "published-print": {"date-parts": [[2024]]},
                    "container-title": ["Journal of Retrieval Testing"],
                    "URL": "https://doi.org/10.1145/example",
                }
            ]
        }
    }
    csl_payload = {
        "title": "Evaluating Retrieval Augmented Generation Systems",
        "DOI": "10.1145/example",
        "issued": {"date-parts": [[2024]]},
        "container-title": "Journal of Retrieval Testing",
        "author": [{"given": "Jane", "family": "Smith"}],
    }
    events: list[str] = []

    def fake_json(url: str, cache_path: Path, refresh: bool) -> dict:
        del url, refresh
        if cache_path.name == "crossref.json":
            return crossref_payload
        return {"results": []}

    def fake_text(url: str, cache_path: Path, refresh: bool, headers: dict[str, str]) -> str:
        del url, cache_path, refresh
        if headers.get("Accept") == "application/vnd.citationstyles.csl+json":
            return json.dumps(csl_payload)
        return "@article{smith2024rag, title={Evaluating Retrieval Augmented Generation Systems}}"

    results = enrich_cards(
        paths,
        [card],
        EnrichmentOptions(refresh=True),
        fetch_json=fake_json,
        fetch_text=fake_text,
        progress=lambda _card, _index, _total, status: events.append(status),
    )

    assert results[0].status == "verified"
    assert "checking" in events
    assert any(event.startswith("attempt:crossref metadata search") for event in events)
    assert any(
        event.startswith("result:crossref metadata search -> 1 metadata candidate")
        for event in events
    )
    assert any(event.startswith("skip-pass:europepmc metadata search") for event in events)
    assert any(event.startswith("attempt:DOI CSL fetch") for event in events)
    assert any(event.startswith("skip-pass:datacite metadata lookup") for event in events)
    assert any(event.startswith("result:citation write -> verified") for event in events)


def test_keyword_enrichment_mode_extracts_pdf_index_terms(tmp_path: Path, monkeypatch) -> None:
    paths = VaultPaths.from_root(tmp_path / "vault")
    paths.ensure()
    pdf = paths.pdfs / "source.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    card = SourceCard(
        slug="source",
        citekey="source",
        title="Source",
        pdf="pdfs/source.pdf",
    )
    events: list[str] = []
    monkeypatch.setattr(
        "scholar_vault.citations.extract_pdf_text_excerpt",
        lambda _path: "Index Terms--Taxi trajectory data; visual analytics\n\n1 Introduction",
    )

    results = enrich_cards(
        paths,
        [card],
        EnrichmentOptions(only="missing-keywords"),
        progress=lambda _card, _index, _total, status: events.append(status),
    )

    assert results[0].status == "resolved"
    assert results[0].source == "pdf_extracted"
    assert card.keywords == ["Taxi trajectory data", "visual analytics"]
    assert any(event.startswith("attempt:PDF keyword extraction") for event in events)
    assert any(
        event.startswith("result:PDF keyword extraction -> added 2 keywords")
        for event in events
    )


def test_keyword_enrichment_mode_reports_missing_keywords(tmp_path: Path, monkeypatch) -> None:
    paths = VaultPaths.from_root(tmp_path / "vault")
    paths.ensure()
    pdf = paths.pdfs / "source.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    card = SourceCard(
        slug="source",
        citekey="source",
        title="Source",
        pdf="pdfs/source.pdf",
    )
    monkeypatch.setattr(
        "scholar_vault.citations.extract_pdf_text_excerpt",
        lambda _path: "Title\n\nAbstract\nNo keyword block appears in this excerpt.",
    )

    results = enrich_cards(paths, [card], EnrichmentOptions(only="missing-keywords"))

    assert results[0].status == "unresolved"
    assert results[0].missing_fields == ("keywords",)
    assert results[0].message == "no keywords found in attached PDF"


def test_abstract_enrichment_upgrades_pdf_source_to_crossref_on_refresh(tmp_path: Path) -> None:
    paths = VaultPaths.from_root(tmp_path / "vault")
    paths.ensure()
    card = SourceCard(
        slug="smith2024rag",
        citekey="smith2024rag",
        title="Evaluating Retrieval Augmented Generation Systems",
        authors=["Jane Smith"],
        year=2024,
        doi="10.1145/example",
        abstract="PDF fallback abstract.",
        abstract_status="resolved",
        abstract_source="pdf_extracted",
    )
    payload = {
        "message": {
            "DOI": "10.1145/example",
            "title": ["Evaluating Retrieval Augmented Generation Systems"],
            "author": [{"given": "Jane", "family": "Smith"}],
            "published-print": {"date-parts": [[2024]]},
            "abstract": "<jats:p>Provider abstract with substantially better provenance.</jats:p>",
            "URL": "https://doi.org/10.1145/example",
        }
    }

    result = enrich_abstract_card(
        paths,
        card,
        EnrichmentOptions(abstracts=True, refresh_abstracts=True),
        fetch_json=lambda *_args: payload,
    )

    assert result.status == "verified"
    assert card.abstract == "Provider abstract with substantially better provenance."
    assert card.abstract_source == "crossref"


def test_abstract_enrichment_progress_reports_provider_passes(tmp_path: Path) -> None:
    paths = VaultPaths.from_root(tmp_path / "vault")
    paths.ensure()
    card = SourceCard(
        slug="smith2024rag",
        citekey="smith2024rag",
        title="Evaluating Retrieval Augmented Generation Systems",
        authors=["Jane Smith"],
        year=2024,
        doi="10.1145/example",
    )
    crossref_payload = {
        "message": {
            "DOI": "10.1145/example",
            "title": ["Evaluating Retrieval Augmented Generation Systems"],
            "author": [{"given": "Jane", "family": "Smith"}],
            "published-print": {"date-parts": [[2024]]},
            "abstract": "<jats:p>Provider abstract with enough detail to accept.</jats:p>",
            "URL": "https://doi.org/10.1145/example",
        }
    }
    events: list[str] = []

    def fake_json(url: str, cache_path: Path, refresh: bool) -> dict:
        del url, refresh
        if cache_path.name == "crossref.json":
            return crossref_payload
        return {"results": []}

    results = enrich_cards(
        paths,
        [card],
        EnrichmentOptions(abstracts=True, refresh_abstracts=True),
        fetch_json=fake_json,
        progress=lambda _card, _index, _total, status: events.append(status),
    )

    assert results[0].status == "verified"
    assert "checking" in events
    assert any(event.startswith("attempt:crossref DOI abstract lookup") for event in events)
    assert any(
        event.startswith("result:crossref DOI abstract lookup -> 1 abstract candidate")
        for event in events
    )
    assert any(event.startswith("attempt:openalex abstract lookup") for event in events)
    assert any(event.startswith("skip-pass:europepmc abstract lookup") for event in events)
    assert any(
        event.startswith("result:abstract write -> verified from crossref") for event in events
    )


def test_abstract_ambiguity_does_not_overwrite_existing_good_abstract(tmp_path: Path) -> None:
    paths = VaultPaths.from_root(tmp_path / "vault")
    paths.ensure()
    existing = "Existing curated abstract about retrieval systems and evaluation workflows."
    card = SourceCard(
        slug="smith2024rag",
        citekey="smith2024rag",
        title="Evaluating Retrieval Augmented Generation Systems",
        authors=["Jane Smith"],
        year=2024,
        doi="10.1145/example",
        abstract=existing,
        abstract_status="resolved",
        abstract_source="crossref",
    )
    crossref_payload = {
        "message": {
            "DOI": "10.1145/example",
            "title": ["Evaluating Retrieval Augmented Generation Systems"],
            "author": [{"given": "Jane", "family": "Smith"}],
            "published-print": {"date-parts": [[2024]]},
            "abstract": (
                "This abstract discusses retrieval systems, evaluation protocols, "
                "benchmarks, and analyst workflows in digital libraries."
            ),
            "URL": "https://doi.org/10.1145/example",
        }
    }
    openalex_payload = {
        "results": [
            {
                "title": "Evaluating Retrieval Augmented Generation Systems",
                "doi": "https://doi.org/10.1145/example",
                "publication_year": 2024,
                "authorships": [{"author": {"display_name": "Jane Smith"}}],
                "abstract_inverted_index": {
                    "This": [0],
                    "paper": [1],
                    "is": [2],
                    "about": [3],
                    "marine": [4],
                    "biology": [5],
                    "and": [6],
                    "coral": [7],
                    "reef": [8],
                    "fieldwork": [9],
                    "covering": [10],
                    "habitat": [11],
                    "temperature": [12],
                    "salinity": [13],
                    "plankton": [14],
                    "measurements": [15],
                    "with": [16],
                    "long": [17],
                    "observations": [18],
                    "from": [19],
                    "boats": [20],
                    "divers": [21],
                    "currents": [22],
                    "plus": [23],
                    "ecological": [24],
                    "survey": [25],
                    "methods": [26],
                },
            }
        ]
    }

    def fake_json(url: str, cache_path: Path, refresh: bool) -> dict:
        del url, refresh
        return openalex_payload if cache_path.name == "openalex.json" else crossref_payload

    result = enrich_abstract_card(
        paths,
        card,
        EnrichmentOptions(abstracts=True, refresh_abstracts=True),
        fetch_json=fake_json,
    )

    assert result.status == "ambiguous"
    assert card.abstract_status == "ambiguous"
    assert card.abstract == existing


def test_abstract_enrichment_second_run_skips_unchanged_resolved_card() -> None:
    card = SourceCard(
        slug="smith2024rag",
        citekey="smith2024rag",
        title="Evaluating Retrieval Augmented Generation Systems",
        abstract="Resolved abstract.",
        abstract_status="resolved",
        abstract_source="crossref",
    )
    card.abstract_input_fingerprint = abstract_fingerprint(card)

    assert (
        should_skip_abstract_card(card, EnrichmentOptions(abstracts=True))
        == "abstract fingerprint unchanged"
    )


def test_abstract_enrichment_retries_truncated_resolved_card() -> None:
    card = SourceCard(
        slug="dodge2016analysismovementdata",
        citekey="dodge2016analysismovementdata",
        title="Analysis of Movement Data",
        abstract=(
            "The study of movement is progressing rapidly as a subdiscipline in "
            "Geographic Information Science. Movem..."
        ),
        abstract_status="resolved",
        abstract_source="crossref",
    )
    card.abstract_input_fingerprint = abstract_fingerprint(card)

    assert should_skip_abstract_card(card, EnrichmentOptions(abstracts=True)) is None


def test_abstract_enrichment_rejects_truncated_provider_candidate(tmp_path: Path) -> None:
    paths = VaultPaths.from_root(tmp_path / "vault")
    paths.ensure()
    card = SourceCard(
        slug="dodge2016analysismovementdata",
        citekey="dodge2016analysismovementdata",
        title="Analysis of Movement Data",
        authors=["S. Dodge"],
        year=2016,
        doi="10.1145/example",
        abstract=(
            "The study of movement is progressing rapidly as a subdiscipline in "
            "Geographic Information Science. Movem..."
        ),
        abstract_status="resolved",
        abstract_source="crossref",
    )
    card.abstract_input_fingerprint = abstract_fingerprint(card)
    crossref_payload = {
        "message": {
            "DOI": "10.1145/example",
            "title": ["Analysis of Movement Data"],
            "author": [{"given": "S.", "family": "Dodge"}],
            "published-print": {"date-parts": [[2016]]},
            "abstract": (
                "The study of movement is progressing rapidly as a subdiscipline in "
                "Geographic Information Science. Movem..."
            ),
            "URL": "https://doi.org/10.1145/example",
        }
    }

    def fake_json(url: str, cache_path: Path, refresh: bool) -> dict:
        del url, refresh
        if cache_path.name == "crossref.json":
            return crossref_payload
        return {"results": []}

    result = enrich_abstract_card(
        paths,
        card,
        EnrichmentOptions(abstracts=True),
        fetch_json=fake_json,
    )

    assert result.status == "unresolved"
    assert result.message == "truncated abstract rejected"
    assert card.abstract is None
    assert card.abstract_status == "unresolved"


def test_abstract_enrichment_retries_previous_failure_by_default() -> None:
    card = SourceCard(
        slug="smith2024rag",
        citekey="smith2024rag",
        title="Evaluating Retrieval Augmented Generation Systems",
        abstract_status="unresolved",
    )
    card.abstract_input_fingerprint = abstract_fingerprint(card)

    assert should_skip_abstract_card(card, EnrichmentOptions(abstracts=True)) is None


def test_abstract_dry_run_does_not_write_card(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    paths = initialize_vault(vault)
    card = SourceCard(
        slug="smith2024rag",
        citekey="smith2024rag",
        title="Evaluating Retrieval Augmented Generation Systems",
        doi="10.1145/example",
    )
    (paths.papers / "smith2024rag.md").write_text(render_paper_markdown(card), encoding="utf-8")
    cache_dir = paths.raw_metadata / "smith2024rag"
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "crossref.json").write_text(
        json.dumps(
            {
                "message": {
                    "DOI": "10.1145/example",
                    "title": ["Evaluating Retrieval Augmented Generation Systems"],
                    "abstract": "Cached provider abstract with enough detail to accept.",
                }
            }
        ),
        encoding="utf-8",
    )
    (cache_dir / "openalex.json").write_text('{"results": []}', encoding="utf-8")

    summary = enrich_citations(vault, abstracts=True, dry_run=True)

    saved = (paths.papers / "smith2024rag.md").read_text(encoding="utf-8")
    assert summary["changed"] == 1
    assert "abstract_status: resolved" not in saved


def test_enrich_citations_returns_itemized_details(tmp_path: Path, monkeypatch) -> None:
    vault = tmp_path / "vault"
    paths = initialize_vault(vault)
    cards = [
        SourceCard(slug="generated", citekey="generated", title="Generated Paper"),
        SourceCard(slug="incomplete", citekey="incomplete", title="Incomplete Paper"),
        SourceCard(slug="ambiguous", citekey="ambiguous", title="Ambiguous Paper"),
        SourceCard(slug="skipped", citekey="skipped", title="Skipped Paper"),
    ]
    for card in cards:
        (paths.papers / f"{card.slug}.md").write_text(
            render_paper_markdown(card),
            encoding="utf-8",
        )

    def fake_enrich_cards(paths_arg, cards_arg, options, progress=None):
        del paths_arg, options, progress
        by_slug = {card.slug: card for card in cards_arg}
        by_slug["generated"].doi = "10.1000/generated"
        by_slug["generated"].authors = ["Jane Smith"]
        by_slug["generated"].year = 2024
        by_slug["generated"].venue = "Generated Venue"
        by_slug["generated"].citation_status = "generated"
        by_slug["generated"].citation_source = "datacite"
        by_slug["generated"].enrichment_status = "complete"
        by_slug["incomplete"].doi = "10.1000/incomplete"
        by_slug["incomplete"].citation_status = "generated"
        by_slug["incomplete"].citation_source = "crossref"
        by_slug["incomplete"].enrichment_status = "incomplete"
        by_slug["incomplete"].enrichment_missing = ["venue"]
        by_slug["ambiguous"].citation_status = "ambiguous"
        by_slug["ambiguous"].citation_skip_reason = "ambiguous crossref candidate score=88"
        results = {
            "generated": EnrichmentResult(
                "generated",
                "generated",
                "citation generated",
                changed=True,
            ),
            "incomplete": EnrichmentResult(
                "incomplete",
                "generated",
                "incomplete metadata",
                changed=True,
            ),
            "ambiguous": EnrichmentResult(
                "ambiguous",
                "ambiguous",
                "ambiguous crossref",
                changed=True,
            ),
            "skipped": EnrichmentResult(
                "skipped",
                "skipped",
                "citation verified",
                skipped=True,
            ),
        }
        return [results[card.slug] for card in cards_arg]

    monkeypatch.setattr("scholar_vault.importer.enrich_cards", fake_enrich_cards)

    summary = enrich_citations(vault, dry_run=True)
    details = {row["citekey"]: row for row in summary["details"]}

    assert summary["generated"] == 2
    assert summary["ambiguous"] == 1
    assert summary["skipped"] == 1
    assert details["generated"]["category"] == "generated"
    assert details["generated"]["doi"] == "10.1000/generated"
    assert details["incomplete"]["category"] == "incomplete"
    assert details["incomplete"]["missing_fields"] == ["venue"]
    assert details["ambiguous"]["message"] == "ambiguous crossref"
    assert Path(details["generated"]["paper_file"]).name == "generated.md"


def test_paper_template_renders_abstract_section() -> None:
    card = SourceCard(
        slug="smith2024rag",
        citekey="smith2024rag",
        title="Evaluating Retrieval Augmented Generation Systems",
        abstract="A real abstract.",
        summary="Scholar Labs summary.",
    )

    rendered = render_paper_markdown(card)

    assert "## Abstract\nA real abstract." in rendered
    assert "## Scholar Labs summary\nScholar Labs summary." in rendered


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


def test_library_bib_includes_abstract_for_enriched_papers(tmp_path: Path) -> None:
    enriched = SourceCard(
        slug="enriched",
        citekey="enriched",
        title="Enriched Paper",
        abstract="A useful abstract.",
        citation_status="generated",
    )

    output = write_library_bib([enriched], tmp_path / "library.bib")

    assert "abstract = {A useful abstract.}" in output.read_text(encoding="utf-8")


def test_card_bibtex_prefers_cached_provider_bibtex_and_adds_vault_fields(
    tmp_path: Path,
) -> None:
    metadata_root = tmp_path / "metadata"
    cache_dir = metadata_root / "smith2024rag"
    cache_dir.mkdir(parents=True)
    (cache_dir / "citation.bib").write_text(
        (
            "@inproceedings{wrongkey,\n"
            "  title={Provider Title},\n"
            "  author={Jane Smith and John Doe},\n"
            "  booktitle={Proceedings of the Test Conference},\n"
            "  pages={10--20},\n"
            "  year={2024},\n"
            "  doi={10.1145/example}\n"
            "}\n"
        ),
        encoding="utf-8",
    )
    card = SourceCard(
        slug="smith2024rag",
        citekey="smith2024rag",
        title="Card Title",
        doi="10.1145/example",
        pdf="pdfs/smith2024rag.pdf",
        abstract="A useful abstract.",
        keywords=["Retrieval", "Evaluation"],
        citation_status="verified",
    )

    result = render_card_bibtex(card, metadata_root=metadata_root, include_vault_note=False)

    assert result is not None
    assert result.source == "cached_bibtex"
    assert "@inproceedings{smith2024rag," in result.entry
    assert "booktitle = {Proceedings of the Test Conference}" in result.entry
    assert "pages = {10--20}" in result.entry
    assert "abstract = {A useful abstract.}" in result.entry
    assert "keywords = {Retrieval, Evaluation}" in result.entry
    assert "file = {pdfs/smith2024rag.pdf}" in result.entry


def test_card_bibtex_uses_cached_csl_when_provider_bibtex_is_absent(tmp_path: Path) -> None:
    metadata_root = tmp_path / "metadata"
    cache_dir = metadata_root / "lee2025vis"
    cache_dir.mkdir(parents=True)
    (cache_dir / "citation.csl.json").write_text(
        json.dumps(
            {
                "type": "paper-conference",
                "title": "Immersive Visual Analytics",
                "author": [{"given": "Ada", "family": "Lee"}],
                "container-title": "IEEE VIS",
                "issued": {"date-parts": [[2025, 10]]},
                "page": "1-9",
                "DOI": "10.1109/vis.example",
                "URL": "https://doi.org/10.1109/vis.example",
            }
        ),
        encoding="utf-8",
    )
    card = SourceCard(
        slug="lee2025vis",
        citekey="lee2025vis",
        title="Immersive Visual Analytics",
        citation_status="verified",
    )

    result = render_card_bibtex(card, metadata_root=metadata_root, include_vault_note=False)

    assert result is not None
    assert result.source == "cached_csl"
    assert "@inproceedings{lee2025vis," in result.entry
    assert "author = {Ada Lee}" in result.entry
    assert "booktitle = {IEEE VIS}" in result.entry
    assert "month = {10}" in result.entry
    assert "pages = {1-9}" in result.entry


def test_card_bibtex_fallback_infers_conference_venue() -> None:
    card = SourceCard(
        slug="lee2025vis",
        citekey="lee2025vis",
        title="Immersive Visual Analytics",
        authors=["Ada Lee"],
        year=2025,
        venue="Proceedings of IEEE VIS",
        citation_status="verified",
    )

    result = render_card_bibtex(card, include_vault_note=False)

    assert result is not None
    assert result.source == "card"
    assert "@inproceedings{lee2025vis," in result.entry
    assert "booktitle = {Proceedings of IEEE VIS}" in result.entry


def test_card_bibtex_normalizes_unicode_punctuation_to_ascii() -> None:
    card = SourceCard(
        slug="oneil2025maps",
        citekey="oneil2025maps",
        title="O’Neil’s 3–D maps — evidence… and limits",
        authors=["José O’Neil"],
        year=2025,
        venue="Proceedings of IEEE VIS",
        abstract="A “smart-quoted” abstract with non‑breaking punctuation.",
        citation_status="verified",
    )

    result = render_card_bibtex(card, include_vault_note=False)

    assert result is not None
    assert all(ord(char) < 128 for char in result.entry)
    assert "title = {O'Neil's 3--D maps --- evidence... and limits}" in result.entry
    assert r"author = {Jos{\'e} O'Neil}" in result.entry
    assert 'abstract = {A "smart-quoted" abstract with non-breaking punctuation.}' in (
        result.entry
    )


def test_card_bibtex_preserves_provider_tex_macros(tmp_path: Path) -> None:
    metadata_root = tmp_path / "metadata"
    cache_dir = metadata_root / "muller2025"
    cache_dir.mkdir(parents=True)
    (cache_dir / "citation.bib").write_text(
        (
            "@article{wrongkey,\n"
            "  title={M{\\\"u}ller's result -- already TeX-safe},\n"
            "  author={M{\\\"u}ller, Anna},\n"
            "  year={2025}\n"
            "}\n"
        ),
        encoding="utf-8",
    )
    card = SourceCard(
        slug="muller2025",
        citekey="muller2025",
        title="Muller Result",
        citation_status="verified",
    )

    result = render_card_bibtex(card, metadata_root=metadata_root, include_vault_note=False)

    assert result is not None
    assert all(ord(char) < 128 for char in result.entry)
    assert r'M{\\"u}ller' not in result.entry
    assert r'M{\"u}ller' in result.entry


def test_card_bibtex_emits_biblatex_journaltitle_from_provider_bibtex(
    tmp_path: Path,
) -> None:
    metadata_root = tmp_path / "metadata"
    cache_dir = metadata_root / "smith2024"
    cache_dir.mkdir(parents=True)
    (cache_dir / "citation.bib").write_text(
        (
            "@article{wrongkey,\n"
            "  title={Provider Article},\n"
            "  author={Jane Smith},\n"
            "  journal={Journal of Test Results},\n"
            "  year={2024}\n"
            "}\n"
        ),
        encoding="utf-8",
    )
    card = SourceCard(
        slug="smith2024",
        citekey="smith2024",
        title="Provider Article",
        citation_status="verified",
    )

    result = render_card_bibtex(card, metadata_root=metadata_root, include_vault_note=False)

    assert result is not None
    assert "@article{smith2024," in result.entry
    assert "journaltitle = {Journal of Test Results}" in result.entry
    assert "\n  journal = " not in result.entry


def test_card_bibtex_can_omit_local_fields(tmp_path: Path) -> None:
    metadata_root = tmp_path / "metadata"
    cache_dir = metadata_root / "smith2024"
    cache_dir.mkdir(parents=True)
    (cache_dir / "citation.bib").write_text(
        (
            "@article{wrongkey,\n"
            "  title={Provider Article},\n"
            "  author={Jane Smith},\n"
            "  journal={Journal of Test Results},\n"
            "  abstract={Provider abstract},\n"
            "  keywords={Provider keyword},\n"
            "  year={2024}\n"
            "}\n"
        ),
        encoding="utf-8",
    )
    card = SourceCard(
        slug="smith2024",
        citekey="smith2024",
        title="Provider Article",
        pdf="pdfs/smith2024.pdf",
        abstract="Vault abstract.",
        keywords=["Vault keyword"],
        summary="Vault summary.",
        citation_status="verified",
    )

    result = render_card_bibtex(
        card,
        metadata_root=metadata_root,
        include_vault_note=True,
        include_local_fields=False,
    )

    assert result is not None
    assert "abstract = " not in result.entry
    assert "keywords = " not in result.entry
    assert "file = " not in result.entry
    assert "note = " not in result.entry


def test_card_bibtex_protects_title_capitalization() -> None:
    card = SourceCard(
        slug="llmwiki2026",
        citekey="llmwiki2026",
        title="LLM-Wiki for VR, 3D OD maps, and GeoAI",
        authors=["Jane Smith"],
        year=2026,
        venue="Journal of Test Results",
        citation_status="verified",
    )

    result = render_card_bibtex(card, include_vault_note=False)

    assert result is not None
    assert "title = {{LLM}-{Wiki} for {VR}, {3D} {OD} maps, and {GeoAI}}" in result.entry


def test_card_bibtex_infers_entry_type_from_cached_crossref_metadata(
    tmp_path: Path,
) -> None:
    metadata_root = tmp_path / "metadata"
    cache_dir = metadata_root / "smith2024"
    cache_dir.mkdir(parents=True)
    (cache_dir / "citation.bib").write_text(
        (
            "@misc{wrongkey,\n"
            "  title={Provider Conference Paper},\n"
            "  author={Jane Smith},\n"
            "  booktitle={Proceedings of TestConf},\n"
            "  year={2024}\n"
            "}\n"
        ),
        encoding="utf-8",
    )
    (cache_dir / "crossref.json").write_text(
        json.dumps({"message": {"type": "proceedings-article"}}),
        encoding="utf-8",
    )
    card = SourceCard(
        slug="smith2024",
        citekey="smith2024",
        title="Provider Conference Paper",
        citation_status="verified",
    )

    result = render_card_bibtex(card, metadata_root=metadata_root, include_vault_note=False)

    assert result is not None
    assert "@inproceedings{smith2024," in result.entry
    assert "booktitle = {Proceedings of TestConf}" in result.entry


def test_card_bibtex_reports_biblatex_validation_warnings() -> None:
    card = SourceCard(
        slug="incomplete",
        citekey="incomplete",
        title="Incomplete Article",
        venue="Journal of Test Results",
        citation_status="missing",
    )

    result = render_card_bibtex(card, include_vault_note=False, require_ready=False)

    assert result is not None
    assert any("citation_status is missing" in warning for warning in result.warnings)
    assert "missing required author/editor for @article" in result.warnings
    assert "missing required year/date for @article" in result.warnings
