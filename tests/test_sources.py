from scholar_vault.sources import build_citekey, parse_people, slugify_text


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
