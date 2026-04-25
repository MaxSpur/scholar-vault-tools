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


def test_best_pdf_match_uses_filename_when_pdf_title_is_journal_header() -> None:
    candidate = PdfCandidate(
        path="/tmp/Personal_Augmented_Reality_for_Informati.pdf",
        title="IEEE TRANSACTIONS ON VISUALIZATION AND COMPUTER GRAPHICS",
        text_excerpt="PersonalAugmentedRealityforInformationVisualizationonLargeInteractiveDisplays",
    )

    decision = best_pdf_match(
        "Personal augmented reality for information visualization on large interactive displays",
        [candidate],
    )

    assert decision.decision == "auto"
    assert decision.score >= 90
    assert decision.reason in {"filename", "text"}


def test_best_pdf_match_rejects_single_token_text_overlap_false_positive() -> None:
    candidate = PdfCandidate(
        path="/tmp/3440207.pdf",
        title="CSUR5402-39",
        doi="10.1145/3440207",
        text_excerpt=(
            "A Survey on Trajectory Data Management, Analytics, and Learning\n"
            "Recent advances in sensor and mobile devices have enabled urban trajectory data."
        ),
    )

    decision = best_pdf_match(
        "Navigating the Sky Together: Investigating Collaboration Dynamics through "
        "Annotation in an Immersive Learning Environment",
        [candidate],
    )

    assert decision.decision == "skip"
    assert decision.score < 70


def test_best_pdf_match_rejects_unconfirmed_partial_filename_match() -> None:
    candidate = PdfCandidate(
        path=(
            "/tmp/3D bivariate visualizations in immersive virtual reality  IVR   "
            "the impact of map literacy and visualization method on user performance.pdf"
        ),
        title=(
            "3D bivariate visualizations in immersive virtual reality (IVR): "
            "the impact of map literacy and visua"
        ),
        text_excerpt=(
            "Cartography and Geographic Information Science\n"
            "3D bivariate visualizations in immersive virtual\n"
            "reality (IVR): the impact of map literacy and\n"
            "visualization method on user performance\n"
        ),
    )

    decision = best_pdf_match("Visualization in virtual reality: a systematic review", [candidate])

    assert decision.decision == "skip"
    assert decision.score < 70


def test_best_pdf_match_rejects_short_first_page_text_overlap_false_positive() -> None:
    candidate = PdfCandidate(
        path="/tmp/luo2026association_authorversion.pdf",
        title=(
            "Beyond Links: Exploring Visual Representations of Multi-View "
            "Relations in Mixed Reality"
        ),
        doi="10.1145/3772318.3791398",
        text_excerpt=(
            "Beyond Links: Exploring Visual Representations of Multi-View\n"
            "Relations in Mixed Reality\n"
            "Abstract\n"
            "This paper investigates associations, explicit representations of "
            "relations between multiple views in Mixed Reality."
        ),
    )

    decision = best_pdf_match(
        "A systematic literature review on extended reality: virtual, augmented "
        "and mixed reality in working life",
        [candidate],
    )

    assert decision.decision == "skip"
    assert decision.score < 70


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
