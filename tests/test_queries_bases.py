from __future__ import annotations

import json

import yaml
from typer.testing import CliRunner

from scholar_vault.bases import doctor_bases, init_bases, rebuild_bases
from scholar_vault.cli import app
from scholar_vault.discovery import doctor_discovery
from scholar_vault.importer import initialize_vault
from scholar_vault.labs_prompts import generate_prompt_pack
from scholar_vault.models import RunRecord
from scholar_vault.queries import (
    query_archive,
    query_create,
    query_doctor,
    query_link_paper,
    query_link_run,
    query_link_synthesis,
    query_rename,
    query_status,
)
from scholar_vault.self_improvement import create_queue_item, rate_feedback
from scholar_vault.sources import read_frontmatter_markdown, write_yaml


def test_query_create_writes_note_with_base_embeds(tmp_path) -> None:
    vault = tmp_path / "vault"
    paths = initialize_vault(vault)

    summary = query_create(
        vault,
        "How should query-centered map evidence be compiled?",
        project="map-lens-deformation",
        slug="map-evidence",
    )
    frontmatter, body = read_frontmatter_markdown(paths.queries / "map-evidence.md")

    assert summary["state"] == "created"
    assert summary["query"] == "queries/map-evidence.md"
    assert frontmatter["type"] == "research_query"
    assert frontmatter["status"] == "open"
    assert frontmatter["project"] == "map-lens-deformation"
    assert frontmatter["question"] == "How should query-centered map evidence be compiled?"
    assert frontmatter["linked_runs"] == []
    assert frontmatter["linked_papers"] == []
    assert frontmatter["linked_syntheses"] == []
    assert frontmatter["linked_concepts"] == []
    assert frontmatter["scholar_labs_prompt_pack"] == []
    assert frontmatter["priority"] == "normal"
    assert frontmatter["review_status"] == "unreviewed"
    assert frontmatter["unread_linked_papers"] == []
    assert frontmatter["uncompiled_linked_papers"] == []
    assert "![[bases/queries.base#Query outputs]]" in body
    assert "![[bases/queries.base#Queries with uncompiled linked papers]]" in body
    assert "![[bases/papers.base#Needs reading]]" in body
    assert (paths.bases / "queries.base").exists()


def test_query_linking_is_idempotent_and_updates_paper_frontmatter(tmp_path) -> None:
    vault = tmp_path / "vault"
    paths = initialize_vault(vault)
    paper = paths.papers / "source-paper.md"
    paper_body = "# Source Paper\n\n## Notes\nCustom paper body that should survive linking.\n"
    paper.write_text(
        """---
type: paper
citekey: Source2026
title: Source Paper
reading_status: unread
---

"""
        + paper_body,
        encoding="utf-8",
    )
    query_create(vault, "What does this source answer?", slug="source-query")

    first = query_link_paper(vault, "source-query", "Source2026")
    second = query_link_paper(vault, "source-query", "Source2026")
    query_frontmatter, query_body = read_frontmatter_markdown(
        paths.queries / "source-query.md"
    )
    paper_frontmatter, saved_paper_body = read_frontmatter_markdown(paper)
    status = query_status(vault, "source-query")

    assert first["changed"] is True
    assert second["changed"] is False
    assert query_frontmatter["linked_papers"] == ["papers/source-paper.md"]
    assert query_frontmatter["unread_linked_papers"] == ["papers/source-paper.md"]
    assert query_frontmatter["uncompiled_linked_papers"] == ["papers/source-paper.md"]
    assert query_body.count("- [Source Paper](../papers/source-paper.md)") == 1
    assert paper_frontmatter["linked_queries"] == ["queries/source-query.md"]
    assert paper_frontmatter["linked_query_paths"] == ["queries/source-query.md"]
    assert saved_paper_body.strip() == paper_body.strip()
    assert status["counts"]["linked_papers"] == 1
    assert status["counts"]["unread_linked_papers"] == 1
    assert status["counts"]["uncompiled_linked_papers"] == 1


def test_query_link_run_and_synthesis(tmp_path) -> None:
    vault = tmp_path / "vault"
    paths = initialize_vault(vault)
    run = RunRecord(
        slug="2026-05-01_mobility",
        date="2026-05-01",
        prompt="collaborative mobility maps",
        exported_at="2026-05-01T12:00:00+02:00",
        export_file="/tmp/export.json",
        raw_export_file="raw/scholar-labs/export.json",
        staging_folder="/tmp/staging",
        result_count=0,
    )
    write_yaml(paths.runs / run.slug / "index.yaml", run.model_dump(exclude_none=True))
    (paths.syntheses / "mobility-synthesis.md").write_text(
        "---\ntype: synthesis\ntitle: Mobility Synthesis\n---\n\n# Mobility Synthesis\n",
        encoding="utf-8",
    )
    query_create(vault, "How do collaborative maps support mobility decisions?", slug="mobility")

    linked_run = query_link_run(vault, "mobility", "2026-05-01_mobility")
    linked_synthesis = query_link_synthesis(vault, "mobility", "mobility-synthesis")
    frontmatter, body = read_frontmatter_markdown(paths.queries / "mobility.md")

    assert linked_run["changed"] is True
    assert linked_synthesis["changed"] is True
    assert frontmatter["linked_runs"] == ["2026-05-01_mobility"]
    assert frontmatter["linked_syntheses"] == ["syntheses/mobility-synthesis.md"]
    assert "Run: `2026-05-01_mobility`" in body
    assert "[syntheses/mobility-synthesis.md](../syntheses/mobility-synthesis.md)" in body


def test_bases_rebuild_is_deterministic_and_doctor_passes(tmp_path) -> None:
    vault = tmp_path / "vault"
    paths = initialize_vault(vault)

    first = init_bases(vault)
    snapshot = {
        path.name: path.read_text(encoding="utf-8") for path in sorted(paths.bases.glob("*.base"))
    }
    second = rebuild_bases(vault)
    second_snapshot = {
        path.name: path.read_text(encoding="utf-8") for path in sorted(paths.bases.glob("*.base"))
    }
    doctor = doctor_bases(vault)
    queries_base = yaml.safe_load((paths.bases / "queries.base").read_text(encoding="utf-8"))

    assert first["written"] == 5
    assert second["changed"] == 0
    assert snapshot == second_snapshot
    assert doctor["ok"] is True
    assert "Query outputs" in [view["name"] for view in queries_base["views"]]
    assert "Queries with uncompiled linked papers" in [
        view["name"] for view in queries_base["views"]
    ]
    assert "this.file" in str(queries_base)


def test_query_and_bases_cli_json(tmp_path) -> None:
    vault = tmp_path / "vault"
    initialize_vault(vault)
    runner = CliRunner()

    created = runner.invoke(
        app,
        [
            "query",
            "create",
            "How should Obsidian Bases support query workbenches?",
            "--vault",
            str(vault),
            "--slug",
            "bases-workbench",
            "--json",
        ],
    )
    listed = runner.invoke(app, ["query", "list", "--vault", str(vault), "--json"])
    doctor = runner.invoke(app, ["bases", "doctor", "--vault", str(vault), "--json"])

    assert created.exit_code == 0
    assert listed.exit_code == 0
    assert doctor.exit_code == 0
    assert json.loads(created.output)["query"] == "queries/bases-workbench.md"
    assert json.loads(listed.output)["queries"][0]["slug"] == "bases-workbench"
    assert json.loads(doctor.output)["ok"] is True


def test_query_rename_updates_linked_records_and_archive_status(tmp_path) -> None:
    vault = tmp_path / "vault"
    paths = initialize_vault(vault)
    paper = paths.papers / "source-paper.md"
    paper.write_text(
        """---
type: paper
citekey: Source2026
title: Source Paper
reading_status: unread
---

# Source Paper
""",
        encoding="utf-8",
    )
    query_create(vault, "What does this source answer?", slug="source-query")
    query_link_paper(vault, "source-query", "Source2026")
    prompt_pack = generate_prompt_pack(vault, query="source-query")["prompt_pack"]
    run = RunRecord(
        slug="run-source-query",
        date="2026-05-16",
        prompt="source query prompt",
        exported_at="2026-05-16T10:00:00+02:00",
        export_file="/tmp/export.json",
        raw_export_file="raw/scholar-labs/export.json",
        result_count=0,
        query="queries/source-query.md",
        prompt_pack=prompt_pack,
    )
    write_yaml(paths.runs / run.slug / "index.yaml", run.model_dump(exclude_none=True))
    write_yaml(
        paths.discovery_candidates / "candidate.yaml",
        {
            "id": "candidate",
            "source": "openalex",
            "title": "Candidate Paper",
            "status": "candidate",
            "query": "queries/source-query.md",
            "linked_prompt_pack": prompt_pack,
        },
    )
    queue = create_queue_item(
        vault,
        kind="discover_sources",
        title="Query rename queue",
        query="source-query",
        refresh_dashboard=False,
    )
    feedback = rate_feedback(
        vault,
        "source-query",
        target_type="query",
        verdict="needs_fix",
        refresh_dashboard=False,
    )

    renamed = query_rename(vault, "source-query", "renamed-query")
    archived = query_archive(vault, "renamed-query", notes="No longer active.")
    doctor = query_doctor(vault, fix=True)
    new_prompt_pack = prompt_pack.replace("queries/source-query/", "queries/renamed-query/")
    new_prompt_pack = new_prompt_pack.replace("query-source-query-", "query-renamed-query-")
    query_frontmatter, query_body = read_frontmatter_markdown(paths.queries / "renamed-query.md")
    paper_frontmatter, _ = read_frontmatter_markdown(paper)
    run_yaml = yaml.safe_load((paths.runs / run.slug / "index.yaml").read_text())
    candidate_yaml = yaml.safe_load((paths.discovery_candidates / "candidate.yaml").read_text())
    queue_yaml = yaml.safe_load((paths.task_queue / f"{queue['id']}.yaml").read_text())
    feedback_yaml = yaml.safe_load((paths.feedback_ratings / f"{feedback['id']}.yaml").read_text())

    assert renamed["query"] == "queries/renamed-query.md"
    assert archived["status"] == "archived"
    assert not (paths.queries / "source-query.md").exists()
    assert (vault / new_prompt_pack).exists()
    assert query_frontmatter["status"] == "archived"
    assert query_frontmatter["scholar_labs_prompt_pack"] == [new_prompt_pack]
    assert "No longer active." in query_body
    assert paper_frontmatter["linked_queries"] == ["queries/renamed-query.md"]
    assert paper_frontmatter["linked_query_paths"] == ["queries/renamed-query.md"]
    assert run_yaml["query"] == "queries/renamed-query.md"
    assert run_yaml["prompt_pack"] == new_prompt_pack
    assert candidate_yaml["query"] == "queries/renamed-query.md"
    assert candidate_yaml["linked_prompt_pack"] == new_prompt_pack
    assert queue_yaml["query"] == "queries/renamed-query.md"
    assert feedback_yaml["target"] == "queries/renamed-query.md"
    assert doctor["ok"] is True
    assert doctor_discovery(vault)["ok"] is True
