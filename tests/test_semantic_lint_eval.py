from __future__ import annotations

import json
import subprocess
from pathlib import Path

import yaml
from typer.testing import CliRunner

from scholar_vault.bases import init_bases
from scholar_vault.cli import app
from scholar_vault.digests import DIGEST_REQUIRED_FIELDS, DIGEST_TEMPLATE_SECTIONS
from scholar_vault.evals import load_eval_definitions, render_eval_report, run_evals
from scholar_vault.importer import _save_card, initialize_vault
from scholar_vault.models import QueueItem, RunRecord, SourceCard
from scholar_vault.self_improvement import create_queue_item, rate_feedback
from scholar_vault.semantic_lint import lint_wiki
from scholar_vault.sources import dump_frontmatter, write_text, write_yaml


def _write_md(path: Path, frontmatter: dict, body: str) -> None:
    write_text(path, f"---\n{dump_frontmatter(frontmatter).strip()}\n---\n\n{body.strip()}\n")


def _complete_digest_body() -> str:
    return "\n\n".join(f"## {section}\n\nRecorded." for section in DIGEST_TEMPLATE_SECTIONS)


def _digest_frontmatter(citekey: str, paper: str, pdf: str = "pdfs/source.pdf") -> dict:
    return {
        field: None
        for field in DIGEST_REQUIRED_FIELDS
    } | {
        "type": "paper_digest",
        "citekey": citekey,
        "paper": paper,
        "pdf": pdf,
        "status": "compiled",
        "evidence_level": "pdf_grounded",
        "compiled_at": "2020-01-01T00:00:00+00:00",
        "reviewed_at": None,
        "linked_queries": ["queries/empty.md"],
        "linked_projects": [],
        "linked_concepts": [],
        "linked_syntheses": [],
        "source_pages_checked": ["1-2"],
        "figures_checked": [],
        "tables_checked": [],
    }


def test_lint_wiki_detects_semantic_checks(tmp_path) -> None:
    vault = tmp_path / "vault"
    paths = initialize_vault(vault)
    init_bases(vault)
    (paths.pdfs / "source.pdf").write_bytes(b"%PDF-1.4 source\n")
    (paths.pdfs / "no-digest.pdf").write_bytes(b"%PDF-1.4 no digest\n")
    _save_card(
        paths,
        SourceCard(
            slug="source",
            citekey="Source2026",
            title="Source Paper",
            pdf="pdfs/source.pdf",
            pdf_status="attached",
            paper_digest="paper-digests/Source2026.md",
        ),
    )
    _save_card(paths, SourceCard(slug="no-pdf", citekey="NoPdf2026", title="No PDF"))
    _save_card(
        paths,
        SourceCard(
            slug="no-digest",
            citekey="NoDigest2026",
            title="No Digest",
            pdf="pdfs/no-digest.pdf",
            pdf_status="attached",
        ),
    )
    _write_md(
        paths.paper_digests / "Source2026.md",
        _digest_frontmatter("Source2026", "papers/source.md"),
        _complete_digest_body(),
    )
    _write_md(
        paths.paper_digests / "Broken2026.md",
        {"type": "paper_digest", "citekey": "Broken2026", "paper": "papers/source.md"},
        "## Core contribution\n\nOnly one section.",
    )
    _write_md(paths.syntheses / "empty.md", {"type": "synthesis"}, "# Empty\n")
    _write_md(
        paths.syntheses / "weak.md",
        {"type": "synthesis", "sources": ["papers/no-pdf.md", "papers/no-digest.md"]},
        "# Weak\n\nUses [No PDF](../papers/no-pdf.md) and [[papers/no-digest]].",
    )
    _write_md(paths.concepts / "empty.md", {"type": "concept"}, "# Empty\n")
    _write_md(
        paths.concepts / "no-digest.md",
        {"type": "concept", "sources": ["papers/no-digest.md"]},
        "# Concept\n\n[[papers/no-digest]]\n",
    )
    _write_md(
        paths.concepts / "dead-link.md",
        {"type": "concept", "sources": ["papers/source.md"]},
        "# Dead\n\n[[syntheses/missing-link]]\n",
    )
    _write_md(paths.queries / "empty.md", {"type": "research_query"}, "# Empty query\n")
    prompt_dir = paths.tasks / "scholar-labs-prompts"
    prompt_dir.mkdir(parents=True, exist_ok=True)
    _write_md(
        prompt_dir / "used-pack.md",
        {"type": "scholar_labs_prompt_pack", "status": "used", "linked_runs": []},
        "# Used pack\n",
    )
    run = RunRecord(
        slug="run-1",
        date="2026-05-16",
        prompt="Find papers",
        exported_at="2026-05-16T10:00:00+02:00",
        export_file="/tmp/export.json",
        raw_export_file="raw/scholar-labs/export.json",
        result_count=0,
    )
    write_yaml(paths.runs / run.slug / "index.yaml", run.model_dump(exclude_none=True))
    create_queue_item(
        vault,
        kind="improve_tool",
        title="Improve tool task",
        tool_improvement={"problem": "Unclear error", "reproduction": "", "tests_to_add": []},
    )
    rate_feedback(
        vault,
        "syntheses/weak.md",
        target_type="synthesis",
        verdict="needs_fix",
        notes="Needs a follow-up.",
    )
    write_yaml(paths.task_queue / "bad.yaml", {"title": "Missing required fields"})
    (paths.bases / "papers.base").write_text("views: not-a-list\n", encoding="utf-8")

    summary = lint_wiki(vault)
    checks = {finding["check"] for finding in summary["findings"]}

    assert {
        "synthesis-no-source-links",
        "synthesis-paper-missing-pdf",
        "synthesis-paper-missing-digest",
        "concept-no-source-links",
        "concept-sources-no-digests",
        "paper-digest-missing-required-fields",
        "paper-digest-missing-required-sections",
        "paper-digest-stale",
        "query-no-linked-work",
        "prompt-pack-used-without-run",
        "run-missing-query-or-prompt-pack",
        "queue-item-invalid",
        "feedback-missing-follow-up-queue",
        "tool-improvement-missing-repro-or-tests",
        "generated-base-invalid-or-missing",
        "dead-wikilink",
    } <= checks


def test_lint_finding_ids_and_queue_creation_are_stable(tmp_path) -> None:
    vault = tmp_path / "vault"
    paths = initialize_vault(vault)
    init_bases(vault)
    _write_md(paths.syntheses / "empty.md", {"type": "synthesis"}, "# Empty\n")

    first = lint_wiki(vault, write_queue=True)
    second = lint_wiki(vault, write_queue=True)
    first_ids = sorted(finding["id"] for finding in first["findings"])
    second_ids = sorted(finding["id"] for finding in second["findings"])
    queue_items = [
        QueueItem.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
        for path in sorted(paths.task_queue.glob("*.yaml"))
    ]

    assert first_ids == second_ids
    assert first["queue"]["created"] == 1
    assert second["queue"]["created"] == 0
    assert [item.stable_key for item in queue_items] == first_ids


def test_lint_wiki_cli_writes_report_json(tmp_path) -> None:
    vault = tmp_path / "vault"
    paths = initialize_vault(vault)
    init_bases(vault)
    _write_md(paths.concepts / "empty.md", {"type": "concept"}, "# Empty\n")

    result = CliRunner().invoke(
        app,
        ["lint-wiki", "--vault", str(vault), "--write-report", "--json"],
    )
    payload = json.loads(result.output)

    assert result.exit_code == 0, result.output
    assert payload["report"]["path"] == "_indexes/lint-wiki-report.md"
    assert (paths.indexes / "lint-wiki-report.md").exists()
    assert payload["findings"][0]["check"] == "concept-no-source-links"


def test_lint_detects_tracked_generated_file_changes(tmp_path) -> None:
    vault = tmp_path / "vault"
    paths = initialize_vault(vault)
    init_bases(vault)
    subprocess.run(["git", "init"], cwd=vault, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=vault, check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=test@example.com",
            "-c",
            "user.name=Test",
            "commit",
            "-m",
            "initial",
        ],
        cwd=vault,
        check=True,
        capture_output=True,
    )
    with (paths.indexes / "papers.md").open("a", encoding="utf-8") as handle:
        handle.write("\nmanual generated edit\n")

    summary = lint_wiki(vault)

    assert "generated-file-modified" in {finding["check"] for finding in summary["findings"]}


def _write_eval_fixture(vault: Path) -> None:
    paths = initialize_vault(vault)
    init_bases(vault)
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
    _write_md(
        paths.queries / "mobility.md",
        {"type": "research_query", "linked_papers": ["papers/source.md"]},
        "# Mobility\n",
    )
    _write_md(
        paths.syntheses / "mobility.md",
        {"type": "synthesis", "sources": ["papers/source.md"]},
        "# Mobility\n\nThis cites a Scholar Labs summary without a paper link.\n",
    )
    proposal = paths.proposals / "mobility"
    proposal.mkdir(parents=True)
    _write_md(
        proposal / "outline.md",
        {"type": "proposal_outline", "evidence_matrix": "source-matrix.md"},
        "# Outline\n",
    )
    _write_md(
        proposal / "source-matrix.md",
        {"type": "proposal_source_matrix"},
        "# Source matrix\n\nNo expected source yet.\n",
    )
    write_yaml(
        paths.evals / "retrieval.yaml",
        {
            "id": "retrieval-mobility",
            "kind": "retrieval",
            "query": "mobility",
            "expected_citekeys": ["Source2026", "Missing2026"],
        },
    )
    write_yaml(
        paths.evals / "grounding.yaml",
        {
            "id": "grounding-mobility",
            "kind": "grounding",
            "synthesis": "mobility",
            "required_sources": ["papers/source.md", "papers/missing.md"],
            "forbidden_source_only_scholar_labs_citations": True,
        },
    )
    write_yaml(
        paths.evals / "proposal.yaml",
        {
            "id": "proposal-mobility",
            "kind": "proposal_audit",
            "proposal": "proposals/mobility",
            "expected_source_matrix_coverage": ["papers/source.md"],
        },
    )


def test_eval_loading_running_history_report_and_queue(tmp_path) -> None:
    vault = tmp_path / "vault"
    _write_eval_fixture(vault)
    paths = initialize_vault(vault, rebuild=False)

    listed = load_eval_definitions(vault)
    retrieval = run_evals(vault, kind="retrieval")
    first = run_evals(vault, write_queue=True)
    second = run_evals(vault, write_queue=True)
    report = render_eval_report(paths)
    history = json.loads((paths.exports / "eval-history.json").read_text(encoding="utf-8"))

    assert listed["count"] == 3
    assert retrieval["definitions"] == 1
    assert retrieval["findings"][0]["check"] == "eval-retrieval-expected-citekeys"
    assert first["count"] >= 4
    assert first["queue"]["created"] == first["count"]
    assert second["queue"]["created"] == 0
    assert len(history["runs"]) == 3
    assert report["report"]["path"] == "_indexes/eval-report.md"
    assert "papers/source.md" in (paths.indexes / "eval-report.md").read_text(encoding="utf-8")


def test_eval_cli_json(tmp_path) -> None:
    vault = tmp_path / "vault"
    _write_eval_fixture(vault)
    runner = CliRunner()

    listed = runner.invoke(app, ["eval", "list", "--vault", str(vault), "--json"])
    run = runner.invoke(
        app,
        ["eval", "run", "--vault", str(vault), "--kind", "grounding", "--json"],
    )
    report = runner.invoke(app, ["eval", "report", "--vault", str(vault), "--json"])

    assert listed.exit_code == 0, listed.output
    assert run.exit_code == 0, run.output
    assert report.exit_code == 0, report.output
    assert json.loads(listed.output)["count"] == 3
    assert json.loads(run.output)["kind"] == "grounding"
    assert json.loads(report.output)["report"]["path"] == "_indexes/eval-report.md"
