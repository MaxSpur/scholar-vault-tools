from scholar_vault.models import (
    ImportManifest,
    ImportManifestEntry,
    Link,
    RationalePoint,
    RunRecord,
    RunResultRecord,
    SourceCard,
    SummarySource,
)
from scholar_vault.render import (
    render_missing_pdfs,
    render_paper_markdown,
    render_run_markdown,
    render_unmatched_index,
)


def test_render_paper_markdown_contains_required_sections() -> None:
    card = SourceCard(
        slug="smith2024rag",
        citekey="smith2024rag",
        title="Evaluating Retrieval Augmented Generation Systems",
        authors_preview="Jane Smith, Omar Lee",
        authors=["Jane Smith", "Omar Lee"],
        year=2024,
        doi="10.1145/example",
        url="https://doi.org/10.1145/example",
        pdf="pdfs/smith2024rag.pdf",
        source_kind="scholar_labs",
        discovered_in=["runs/2026-04-22_rag/2026-04-22_rag.md"],
        keywords=["Retrieval", "Benchmarking"],
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
        enrichment_status="incomplete",
        enrichment_missing=["venue"],
    )

    rendered = render_paper_markdown(card)

    assert "## Abstract" in rendered
    assert "## Quick access" in rendered
    assert "[Open local PDF](../pdfs/smith2024rag.pdf)" in rendered
    assert "Metadata: `incomplete` (missing venue)" in rendered
    assert "[10.1145/example](https://doi.org/10.1145/example)" in rendered
    assert "## Scholar Labs summary" in rendered
    assert "## Keywords\n- Retrieval\n- Benchmarking" in rendered
    assert "### Run-specific Scholar Labs summaries" in rendered
    assert "Run-specific summary." in rendered
    frontmatter = rendered.split("---", 2)[1]
    assert "reading_status: unread" in frontmatter
    assert "compiled_status: uncompiled" in frontmatter
    assert "review_status: unreviewed" in frontmatter
    assert "evidence_level: unknown" in frontmatter
    assert "linked_queries: []" in frontmatter
    assert "linked_projects: []" in frontmatter
    assert "\nabstract:" not in frontmatter
    assert "\nsummary_sources:" not in frontmatter
    assert "## Why this source matters" in rendered
    assert "[pdfs/smith2024rag.pdf](../pdfs/smith2024rag.pdf)" in rendered
    assert (
        "[runs/2026-04-22_rag/2026-04-22_rag.md]"
        "(<../runs/2026-04-22_rag/2026-04-22_rag.md>)" in rendered
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
        authors=["Jane Smith", "Omar Lee"],
        year=2025,
        venue="Journal of Local Knowledge Stores",
        doi="10.1145/example",
        topics=["Retrieval", "Evaluation"],
        source_kind="scholar_labs",
        pdf="pdfs/smith2024rag.pdf",
        enrichment_status="incomplete",
        enrichment_missing=["venue"],
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
    assert "Authors: Jane Smith, Omar Lee" in rendered
    assert "Year: 2025" in rendered
    assert "Venue: Journal of Local Knowledge Stores" in rendered
    assert "[10.1145/example](https://doi.org/10.1145/example)" in rendered
    assert "Topics: Retrieval, Evaluation" in rendered
    assert "Metadata: `incomplete` (missing venue)" in rendered
    assert "[pdfs/smith2024rag.pdf](../../pdfs/smith2024rag.pdf)" in rendered
    assert "Grounded Generation from Local Knowledge Stores" in rendered


def test_generated_maintenance_indexes_label_optional_and_historical_queues() -> None:
    run = RunRecord(
        slug="2026-04-22_rag",
        date="2026-04-22",
        prompt="retrieval augmented generation",
        exported_at="2026-04-22T10:00:00+02:00",
        export_file="/tmp/export.json",
        raw_export_file="raw/scholar-labs/run.json",
        staging_folder="/tmp/staging",
        result_count=1,
        results=[
            RunResultRecord(
                rank=1,
                title="Grounded Generation from Local Knowledge Stores",
                authors_preview="Omar Lee",
                status="candidate",
                pdf_status="missing",
            )
        ],
    )
    manifest = ImportManifest(
        run_id="2026-04-22_rag",
        export_file="/tmp/export.json",
        staging_folder="/tmp/staging",
        created_at="2026-04-22T10:00:00+02:00",
        entries=[
            ImportManifestEntry(
                original_path="/tmp/staging/example.pdf",
                proposed_match="Grounded Generation from Local Knowledge Stores",
                score=0,
                decision="rejected",
            )
        ],
    )

    missing = render_missing_pdfs([run])
    unmatched = render_unmatched_index([manifest])

    assert "# Candidate Results Without Cards" in missing
    assert "optional discovery context" in missing
    assert "# Historical Unmatched Staging PDFs" in unmatched
    assert "historical audit records" in unmatched
