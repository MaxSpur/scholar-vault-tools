from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from scholar_vault.cli import app
from scholar_vault.digests import (
    DIGEST_TEMPLATE_SECTIONS,
    compile_doctor,
    compile_mark,
    compile_queue,
    compile_scaffold,
    compile_status,
)
from scholar_vault.importer import _save_card, initialize_vault
from scholar_vault.models import RunRecord, RunResultRecord, SourceCard
from scholar_vault.rebuild import rebuild_vault
from scholar_vault.sources import (
    dump_frontmatter,
    read_frontmatter_markdown,
    write_text,
    write_yaml,
)


def _write_digest_frontmatter(path, frontmatter, body) -> None:
    write_text(path, f"---\n{dump_frontmatter(frontmatter).strip()}\n---\n\n{body.strip()}\n")


def _complete_digest_body() -> str:
    return "\n\n".join(
        f"## {section}\n\nRecorded with page evidence." for section in DIGEST_TEMPLATE_SECTIONS
    )


def test_compile_scaffold_creates_stable_digest_and_updates_card(tmp_path) -> None:
    vault = tmp_path / "vault"
    paths = initialize_vault(vault)
    (paths.pdfs / "source.pdf").write_bytes(b"%PDF-1.4 source\n")
    _save_card(
        paths,
        SourceCard(
            slug="source",
            citekey="Source2026",
            title="Source Paper",
            pdf="pdfs/source.pdf",
            pdf_status="attached",
            reading_status="read",
        ),
    )

    first = compile_scaffold(vault, citekey="Source2026")
    digest_path = paths.paper_digests / "Source2026.md"
    digest_snapshot = digest_path.read_text(encoding="utf-8")
    second = compile_scaffold(vault, citekey="Source2026")
    status = compile_status(vault)
    doctor = compile_doctor(vault)
    frontmatter, body = read_frontmatter_markdown(digest_path)
    card_frontmatter, _ = read_frontmatter_markdown(paths.papers / "source.md")

    assert first["changed"] == 1
    assert second["changed"] == 0
    assert digest_path.read_text(encoding="utf-8") == digest_snapshot
    assert frontmatter["type"] == "paper_digest"
    assert frontmatter["citekey"] == "Source2026"
    assert frontmatter["paper"] == "papers/source.md"
    assert frontmatter["pdf"] == "pdfs/source.pdf"
    assert frontmatter["status"] == "draft"
    assert frontmatter["evidence_level"] == "metadata_only"
    for heading in [
        "Core contribution",
        "Problem addressed",
        "Method/model/apparatus",
        "Evidence notes",
    ]:
        assert f"## {heading}" in body
    assert card_frontmatter["paper_digest"] == "paper-digests/Source2026.md"
    assert card_frontmatter["compiled_status"] == "draft"
    assert status["counts"]["draft"] == 1
    assert doctor["ok"] is True
    assert (paths.indexes / "compile-dashboard.md").exists()


def test_compile_mark_transitions_status_and_timestamps(tmp_path) -> None:
    vault = tmp_path / "vault"
    paths = initialize_vault(vault)
    (paths.pdfs / "source.pdf").write_bytes(b"%PDF-1.4 source\n")
    _save_card(
        paths,
        SourceCard(
            slug="source",
            citekey="Source2026",
            title="Source Paper",
            pdf="pdfs/source.pdf",
            pdf_status="attached",
        ),
    )
    compile_scaffold(vault, citekey="Source2026")
    digest_path = paths.paper_digests / "Source2026.md"
    frontmatter, body = read_frontmatter_markdown(digest_path)
    frontmatter["evidence_level"] = "pdf_grounded"
    frontmatter["source_pages_checked"] = ["1-12"]
    _write_digest_frontmatter(digest_path, frontmatter, _complete_digest_body())

    compiled = compile_mark(vault, "Source2026", status="compiled")
    reviewed = compile_mark(vault, "Source2026", status="reviewed")
    digest_frontmatter, _ = read_frontmatter_markdown(digest_path)
    card_frontmatter, _ = read_frontmatter_markdown(paths.papers / "source.md")

    assert compiled["changed"] is True
    assert reviewed["changed"] is True
    assert digest_frontmatter["status"] == "reviewed"
    assert digest_frontmatter["compiled_at"]
    assert digest_frontmatter["reviewed_at"]
    assert card_frontmatter["compiled_status"] == "reviewed"
    assert card_frontmatter["review_status"] == "reviewed"
    assert card_frontmatter["last_compiled_at"]
    assert card_frontmatter["last_reviewed_at"]
    assert card_frontmatter["evidence_level"] == "pdf_grounded"
    assert compile_doctor(vault)["ok"] is True


def test_compile_mark_rejects_unready_digest_without_force(tmp_path) -> None:
    vault = tmp_path / "vault"
    paths = initialize_vault(vault)
    _save_card(paths, SourceCard(slug="source", citekey="Source2026", title="Source Paper"))
    compile_scaffold(vault, citekey="Source2026")

    with pytest.raises(ValueError, match="digest readiness issues"):
        compile_mark(vault, "Source2026", status="compiled")

    forced = compile_mark(vault, "Source2026", status="compiled", force=True)
    doctor = compile_doctor(vault)

    assert forced["forced"] is True
    assert {issue["check"] for issue in forced["transition_issues"]} >= {
        "paper-digest-ready-metadata-only",
        "paper-digest-ready-missing-source-pages",
        "paper-digest-ready-missing-pdf-link",
        "paper-digest-ready-template-placeholders",
    }
    assert "compiled/reviewed digest still marked metadata_only" in doctor["issue_counts"]


def test_compile_run_scaffold_project_queue_and_rebuild(tmp_path) -> None:
    vault = tmp_path / "vault"
    paths = initialize_vault(vault)
    _save_card(paths, SourceCard(slug="source", citekey="Source2026", title="Source Paper"))
    run = RunRecord(
        slug="2026-05-01_sources",
        date="2026-05-01",
        prompt="source papers",
        exported_at="2026-05-01T12:00:00+02:00",
        export_file="/tmp/export.json",
        raw_export_file="raw/scholar-labs/export.json",
        staging_folder="/tmp/staging",
        result_count=2,
        results=[
            RunResultRecord(
                rank=1,
                title="Source Paper",
                status="selected",
                pdf_status="attached",
                paper_card="papers/source.md",
            ),
            RunResultRecord(rank=2, title="Candidate Paper", status="candidate"),
        ],
    )
    write_yaml(paths.runs / run.slug / "index.yaml", run.model_dump(exclude_none=True))
    project_dir = paths.projects / "map-project"
    project_dir.mkdir(parents=True)
    write_text(
        project_dir / "index.md",
        """---
type: project
title: Map Project
slug: map-project
related_papers:
  - papers/source.md
---

# Map Project
""",
    )

    summary = compile_scaffold(vault, run_id=run.slug, selected_only=True)
    queue = compile_queue(vault, project="map-project")
    rebuild = rebuild_vault(vault)

    assert summary["count"] == 1
    assert summary["skipped"] == []
    assert queue["queue_count"] == 1
    assert queue["queue"][0]["paper"] == "papers/source.md"
    assert rebuild["index_files_written"] >= 1


def test_compile_cli_json(tmp_path) -> None:
    vault = tmp_path / "vault"
    paths = initialize_vault(vault)
    _save_card(paths, SourceCard(slug="source", citekey="Source2026", title="Source Paper"))
    runner = CliRunner()

    scaffold = runner.invoke(
        app,
        ["compile", "scaffold", "--vault", str(vault), "--citekey", "Source2026", "--json"],
    )
    status = runner.invoke(app, ["compile", "status", "--vault", str(vault), "--json"])
    doctor = runner.invoke(app, ["compile", "doctor", "--vault", str(vault), "--json"])

    assert scaffold.exit_code == 0
    assert status.exit_code == 0
    assert doctor.exit_code == 0
    assert json.loads(scaffold.output)["digests"][0]["digest"] == "paper-digests/Source2026.md"
    assert json.loads(status.output)["counts"]["draft"] == 1
    assert json.loads(doctor.output)["ok"] is True
