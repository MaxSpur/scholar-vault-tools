from scholar_vault.models import Link, RationalePoint, RunRecord, ScholarLabsResult, SourceCard
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
        discovered_in=["runs/2026-04-22_rag/index.md"],
        summary="Short summary.",
        why_this_source_matters=[
            RationalePoint(label="Evaluation", text="Useful evaluation framing.")
        ],
        links=[Link(label="publication", url="https://example.com", kind="html")],
    )

    rendered = render_paper_markdown(card)

    assert "## Summary" in rendered
    assert "## Why this source matters" in rendered
    assert "[pdfs/smith2024rag.pdf](../pdfs/smith2024rag.pdf)" in rendered
    assert "[runs/2026-04-22_rag/index.md](../runs/2026-04-22_rag/index.md)" in rendered


def test_render_run_markdown_links_canonical_card() -> None:
    result = ScholarLabsResult(
        rank=1,
        title="Evaluating Retrieval Augmented Generation Systems",
        authors_preview="Jane Smith",
        summary="Short summary.",
        rationale_points=[RationalePoint(label="Evaluation", text="Useful evaluation framing.")],
    )
    run = RunRecord(
        slug="2026-04-22_rag",
        date="2026-04-22",
        prompt="retrieval augmented generation",
        exported_at="2026-04-22T10:00:00+02:00",
        export_file="/tmp/export.json",
        raw_export_file="raw/scholar-labs/run.json",
        result_count=1,
        results=[result],
        paper_slugs=["smith2024rag"],
    )
    card = SourceCard(
        slug="smith2024rag",
        title=result.title,
        source_kind="scholar_labs",
        pdf="pdfs/smith2024rag.pdf",
    )

    rendered = render_run_markdown(run, {"smith2024rag": card})

    assert (
        "[Evaluating Retrieval Augmented Generation Systems](../../papers/smith2024rag.md)"
        in rendered
    )
    assert "`papers/smith2024rag.md`" in rendered
