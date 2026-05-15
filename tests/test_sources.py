from pathlib import Path

from scholar_vault.sources import (
    build_card_slug,
    build_citekey,
    build_pdf_filename,
    infer_run_title,
    load_source_card,
    normalize_copied_abstract,
    normalize_keywords,
    parse_people,
    slugify_text,
)
from scholar_vault.titles import clean_paper_title


def test_slug_generation_normalizes_text() -> None:
    assert slugify_text("Über Café: Local-First Research!") == "uber-cafe-local-first-research"


def test_citekey_generation_uses_author_year_and_keywords() -> None:
    citekey = build_citekey(
        "Evaluating Retrieval Augmented Generation Systems",
        ["Jane Smith", "Omar Lee"],
        2024,
    )
    assert citekey == "smith2024evaluatingretrievalaugmentedgenerationsystems"


def test_paper_title_cleaning_strips_scholar_resource_prefixes() -> None:
    assert clean_paper_title("[HTML][HTML] Mapping Digital Solutions") == (
        "Mapping Digital Solutions"
    )
    assert clean_paper_title("[PDF] [PDF] A Survey on Interactive Lenses") == (
        "A Survey on Interactive Lenses"
    )
    assert build_citekey("[PDF][PDF] A Survey on Interactive Lenses", ["Jane Smith"], 2024) == (
        "smith2024surveyinteractivelenses"
    )
    assert build_card_slug(None, "[HTML][HTML] Mapping Digital Solutions", []) == (
        "mapping-digital-solutions"
    )


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


def test_normalize_keywords_splits_and_repairs_pdf_keyword_text() -> None:
    raw = (
        "Index Terms--Immersive Analytics · Collaboration | Mixed Reality; "
        "Sci-\nentific Data Visualization"
    )

    assert normalize_keywords(raw) == [
        "Immersive Analytics",
        "Collaboration",
        "Mixed Reality",
        "Scientific Data Visualization",
    ]


def test_load_source_card_reads_keywords_section(tmp_path: Path) -> None:
    card_path = tmp_path / "example.md"
    card_path.write_text(
        """---
title: Example Paper
---

# Example Paper

## Keywords
- Immersive Analytics
- Collaboration

## Abstract
No abstract yet.
""",
        encoding="utf-8",
    )

    card = load_source_card(card_path)

    assert card.keywords == ["Immersive Analytics", "Collaboration"]


def test_load_source_card_applies_workbench_defaults(tmp_path: Path) -> None:
    card_path = tmp_path / "old-card.md"
    card_path.write_text(
        """---
type: paper
title: Old Card
---

# Old Card

## Scholar Labs summary
No summary yet.
""",
        encoding="utf-8",
    )

    card = load_source_card(card_path)

    assert card.reading_status == "unread"
    assert card.compiled_status == "uncompiled"
    assert card.review_status == "unreviewed"
    assert card.evidence_level == "unknown"
    assert card.last_reviewed_at is None
    assert card.paper_digest is None
    assert card.linked_queries == []
    assert card.linked_projects == []


def test_load_source_card_preserves_workbench_fields(tmp_path: Path) -> None:
    card_path = tmp_path / "workbench-card.md"
    card_path.write_text(
        """---
type: paper
title: Workbench Card
reading_status: skimmed
compiled_status: draft
review_status: needs_fix
last_read_at: 2026-05-01T12:00:00+02:00
last_compiled_at: 2026-05-02T12:00:00+02:00
last_reviewed_at: 2026-05-03T12:00:00+02:00
evidence_level: primary
paper_digest: paper-digests/Workbench2026.md
linked_queries:
  - queries/example-query.md
linked_projects: projects/map-lens/index.md
---

# Workbench Card

## Scholar Labs summary
No summary yet.
""",
        encoding="utf-8",
    )

    card = load_source_card(card_path)

    assert card.reading_status == "skimmed"
    assert card.compiled_status == "draft"
    assert card.review_status == "needs_fix"
    assert card.last_read_at == "2026-05-01T12:00:00+02:00"
    assert card.last_compiled_at == "2026-05-02T12:00:00+02:00"
    assert card.last_reviewed_at == "2026-05-03T12:00:00+02:00"
    assert card.evidence_level == "primary"
    assert card.paper_digest == "paper-digests/Workbench2026.md"
    assert card.linked_queries == ["queries/example-query.md"]
    assert card.linked_projects == ["projects/map-lens/index.md"]


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
last_read_at: 2026-04-24T09:00:00+02:00
last_compiled_at: 2026-04-25T09:00:00+02:00
last_reviewed_at: 2026-04-26T09:00:00+02:00
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
    assert card.last_read_at == "2026-04-24T09:00:00+02:00"
    assert card.last_compiled_at == "2026-04-25T09:00:00+02:00"
    assert card.last_reviewed_at == "2026-04-26T09:00:00+02:00"
