from scholar_vault.matcher import best_pdf_match, match_candidate_to_cards, score_title_match
from scholar_vault.models import PdfCandidate, SourceCard


def test_score_title_match_prefers_near_exact_titles() -> None:
    score = score_title_match(
        "Evaluating Retrieval Augmented Generation Systems",
        "Evaluating Retrieval-Augmented Generation Systems",
    )
    assert score >= 95


def test_best_pdf_match_autoselects_high_scores() -> None:
    candidate = PdfCandidate(
        path="/tmp/example.pdf",
        title="Grounded Generation from Local Knowledge Stores",
    )
    decision = best_pdf_match("Grounded Generation from Local Knowledge Stores", [candidate])
    assert decision.decision == "auto"
    assert decision.score == 100


def test_match_candidate_to_existing_card_by_title() -> None:
    candidate = PdfCandidate(
        path="/tmp/example.pdf",
        title="Grounded Generation from Local Knowledge Stores",
    )
    cards = [
        SourceCard(
            slug="grounded",
            title="Grounded Generation from Local Knowledge Stores",
            source_kind="manual",
        )
    ]
    card, score = match_candidate_to_cards(candidate, cards)
    assert card is not None
    assert card.slug == "grounded"
    assert score == 100
