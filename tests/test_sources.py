from scholar_vault.sources import (
    build_citekey,
    build_pdf_filename,
    infer_run_title,
    load_source_card,
    normalize_copied_abstract,
    parse_people,
    slugify_text,
)


def test_slug_generation_normalizes_text() -> None:
    assert slugify_text("Über Café: Local-First Research!") == "uber-cafe-local-first-research"


def test_citekey_generation_uses_author_year_and_keywords() -> None:
    citekey = build_citekey(
        "Evaluating Retrieval Augmented Generation Systems",
        ["Jane Smith", "Omar Lee"],
        2024,
    )
    assert citekey == "smith2024evaluatingretrievalaugmentedgenerationsystems"


def test_parse_people_handles_comma_and_and() -> None:
    assert parse_people("Jane Smith, Omar Lee and Ken Park") == [
        "Jane Smith",
        "Omar Lee",
        "Ken Park",
    ]


def test_normalize_copied_abstract_repairs_pdf_line_breaks() -> None:
    raw = """Abstract. In the ever-evolving discipline of high-dimensional scientific
data, collaborative immersive analytics (CIA) offers a promising fron-
tier for domain experts in complex data visualization and interpretation.
This research presents a comprehensive framework for conducting us-
ability studies.

Keywords: Immersive Analytics · Collaboration"""

    assert normalize_copied_abstract(raw) == (
        "In the ever-evolving discipline of high-dimensional scientific data, "
        "collaborative immersive analytics (CIA) offers a promising frontier for "
        "domain experts in complex data visualization and interpretation. This "
        "research presents a comprehensive framework for conducting usability studies."
    )


def test_infer_run_title_uses_prompt_topic_phrase() -> None:
    prompt = (
        "Find peer-reviewed papers that would support a postdoctoral research proposal "
        "on collaborative immersive geovisual analytics for multimodal urban mobility data."
    )

    assert infer_run_title(prompt) == "Collaborative Immersive Geovisual Analytics Multimodal Urban"


def test_pdf_filename_uniqueness_keeps_pdf_suffix() -> None:
    name = build_pdf_filename(
        "Evaluating Retrieval Augmented Generation Systems",
        ["Jane Smith"],
        2024,
        existing_names=["smith2024evaluatingretrievalaugmentedgenerationsystems.pdf"],
    )

    assert name == "smith2024evaluatingretrievalaugmentedgenerationsystems-2.pdf"


def test_load_source_card_accepts_yaml_timestamp_scalars(tmp_path) -> None:
    card_path = tmp_path / "timestamped.md"
    card_path.write_text(
        """---
type: paper
title: Timestamped Paper
citation_last_checked: 2026-04-23T12:36:12+02:00
citation_enriched_at: 2026-04-23T12:36:12+02:00
abstract_last_checked: 2026-04-23T16:00:20+02:00
abstract_enriched_at: 2026-04-23T16:00:20+02:00
---

# Timestamped Paper

## Scholar Labs summary
No summary yet.
""",
        encoding="utf-8",
    )

    card = load_source_card(card_path)

    assert card.citation_last_checked == "2026-04-23T12:36:12+02:00"
    assert card.citation_enriched_at == "2026-04-23T12:36:12+02:00"
    assert card.abstract_last_checked == "2026-04-23T16:00:20+02:00"
    assert card.abstract_enriched_at == "2026-04-23T16:00:20+02:00"
