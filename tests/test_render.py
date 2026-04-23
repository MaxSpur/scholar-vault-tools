from scholar_vault.models import (
    Link,
    RationalePoint,
    RunRecord,
    RunResultRecord,
    SourceCard,
    SummarySource,
)
from scholar_vault.render import render_paper_markdown, render_run_markdown


def test_render_paper_markdown_contains_required_sections() -> None:
    card = SourceCard(
        slug="smith2024rag",
        citekey="smith2024rag",
        title="Evaluating Retrieval Augmented Generation Systems",
        authors_preview="Jane Smith, Omar Lee",
        authors=["Jane Smith", "Omar Lee"],
        year=2024,
        pdf="pdfs/smith2024rag.pdf",
        source_kind="scholar_labs",
        discovered_in=["runs/2026-04-22_rag/2026-04-22_rag.md"],
        summary="Short summary.",
        summary_sources=[
            SummarySource(
                run="runs/2026-04-22_rag/2026-04-22_rag.md",
                prompt="retrieval augmented generation",
                rank=1,
                summary="Run-specific summary.",
            )
        ],
        why_this_source_matters=[
            RationalePoint(label="Evaluation", text="Useful evaluation framing.")
        ],
        links=[Link(label="publication", url="https://example.com", kind="html")],
    )

    rendered = render_paper_markdown(card)

    assert "## Summary" in rendered
    assert "## Scholar Labs Summaries" in rendered
    assert "Run-specific summary." in rendered
    assert "## Why this source matters" in rendered
    assert "[pdfs/smith2024rag.pdf](../pdfs/smith2024rag.pdf)" in rendered
    assert (
        "[runs/2026-04-22_rag/2026-04-22_rag.md]"
        "(../runs/2026-04-22_rag/2026-04-22_rag.md)" in rendered
    )


def test_render_run_markdown_separates_selected_and_candidate_results() -> None:
    selected = RunResultRecord(
        rank=1,
        title="Evaluating Retrieval Augmented Generation Systems",
        authors_preview="Jane Smith",
        summary="Short summary.",
        rationale_points=[RationalePoint(label="Evaluation", text="Useful evaluation framing.")],
        status="selected",
        pdf_status="attached",
        paper_card="papers/smith2024rag.md",
    )
    candidate = RunResultRecord(
        rank=2,
        title="Grounded Generation from Local Knowledge Stores",
        authors_preview="Omar Lee",
        status="candidate",
        pdf_status="missing",
    )
    run = RunRecord(
        slug="2026-04-22_rag",
        date="2026-04-22",
        prompt="retrieval augmented generation",
        exported_at="2026-04-22T10:00:00+02:00",
        export_file="/tmp/export.json",
        raw_export_file="raw/scholar-labs/run.json",
        staging_folder="/tmp/staging",
        result_count=2,
        results=[selected, candidate],
    )
    card = SourceCard(
        slug="smith2024rag",
        title=selected.title,
        source_kind="scholar_labs",
        pdf="pdfs/smith2024rag.pdf",
    )

    rendered = render_run_markdown(run, {"smith2024rag": card})

    assert "type: scholar_labs_run" in rendered
    assert "title: Retrieval Augmented Generation" in rendered
    assert "# Scholar Labs Run: Retrieval Augmented Generation" in rendered
    assert "## Selected Papers" in rendered
    assert "## Candidate And Unmatched Results" in rendered
    assert (
        "[Evaluating Retrieval Augmented Generation Systems](../../papers/smith2024rag.md)"
        in rendered
    )
    assert "Grounded Generation from Local Knowledge Stores" in rendered
