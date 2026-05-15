from __future__ import annotations

import json
from pathlib import Path

import yaml
from pypdf import PdfWriter
from typer.testing import CliRunner

from scholar_vault.cli import app
from scholar_vault.importer import import_scholar_labs_run, initialize_vault
from scholar_vault.labs_prompts import (
    PROMPT_TYPES,
    generate_prompt_pack,
    link_prompt_pack_run,
    mark_prompt_pack_used,
    retire_prompt_pack,
)
from scholar_vault.models import RunRecord
from scholar_vault.queries import query_create, query_link_paper
from scholar_vault.sources import read_frontmatter_markdown, write_yaml


def _write_paper(paths, slug: str, title: str, *, year: int = 2024) -> None:
    (paths.papers / f"{slug}.md").write_text(
        f"""---
type: paper
citekey: {slug}
title: {title}
authors:
  - Jane Smith
year: {year}
venue: Test Venue
topics:
  - Mobility
  - Evidence Mapping
keywords:
  - mixed methods
reading_status: unread
compiled_status: uncompiled
---

# {title}

## Summary
No summary yet.

## Notes
Fixture notes.
""",
        encoding="utf-8",
    )


def _write_export(path: Path, *, prompt: str, result_title: str) -> Path:
    payload = {
        "schema_version": "0.2",
        "source": "google_scholar_labs",
        "exported_at": "2026-05-15T10:00:00+02:00",
        "title": "Prompt Pack Import",
        "prompt": prompt,
        "results": [
            {
                "rank": 1,
                "scholar_cid": "cid-001",
                "title": result_title,
                "authors_preview": "Jane Smith",
                "year": 2024,
                "venue_preview": "Test Venue",
                "summary": "Scholar Labs discovery summary.",
                "rationale_points": [{"label": "Fit", "text": "Matches the prompt."}],
                "links": [{"label": "publication", "url": "https://example.com", "kind": "html"}],
            }
        ],
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def _write_pdf_with_title(path: Path, title: str) -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.add_metadata({"/Title": title})
    with path.open("wb") as handle:
        writer.write(handle)


def test_query_prompt_pack_generation_uses_linked_papers_and_is_idempotent(tmp_path) -> None:
    vault = tmp_path / "vault"
    paths = initialize_vault(vault)
    _write_paper(paths, "source-one", "Collaborative Mobility Evidence Maps")
    _write_paper(paths, "source-two", "Failure Modes in Urban Mobility Dashboards", year=2023)
    query_create(
        vault,
        "How do collaborative maps support urban mobility decisions?",
        slug="mobility",
        project="map-lens",
    )
    query_link_paper(vault, "mobility", "source-one")
    query_link_paper(vault, "mobility", "source-two")

    first = generate_prompt_pack(vault, query="mobility")
    prompt_path = paths.vault / first["prompt_pack"]
    frontmatter, body = read_frontmatter_markdown(prompt_path)
    query_frontmatter, query_body = read_frontmatter_markdown(paths.queries / "mobility.md")
    second = generate_prompt_pack(vault, query="mobility")

    assert first["state"] == "created"
    assert second["state"] == "unchanged"
    assert first["prompt_count"] == len(PROMPT_TYPES)
    assert prompt_path == (
        paths.queries / "mobility" / "prompt-packs" / "query-mobility-scholar-labs-prompts.md"
    )
    assert frontmatter["type"] == "scholar_labs_prompt_pack"
    assert frontmatter["status"] == "draft"
    assert frontmatter["query"] == "queries/mobility.md"
    assert frontmatter["project"] == "map-lens"
    assert "Collaborative Mobility Evidence Maps" in body
    assert "Failure Modes in Urban Mobility Dashboards" in body
    assert "coverage_gap" in body
    assert "contradict" in body.casefold()
    assert "selection_guidance" in body
    assert "Do not scrape Google Scholar" in body
    assert query_frontmatter["scholar_labs_prompt_pack"] == [first["prompt_pack"]]
    assert "[Scholar Labs prompt pack]" in query_body
    assert (paths.indexes / "scholar-labs-prompts.md").exists()


def test_prompt_pack_status_transitions(tmp_path) -> None:
    vault = tmp_path / "vault"
    initialize_vault(vault)
    query_create(vault, "What evidence is missing?", slug="gaps")
    generated = generate_prompt_pack(vault, query="gaps")

    used = mark_prompt_pack_used(vault, generated["id"], notes="Ran prompt in Labs.")
    retired = retire_prompt_pack(vault, generated["id"])
    frontmatter, body = read_frontmatter_markdown(vault / generated["prompt_pack"])

    assert used["previous_status"] == "draft"
    assert used["status"] == "used"
    assert retired["previous_status"] == "used"
    assert frontmatter["status"] == "retired"
    assert "Ran prompt in Labs." in body
    assert "Retired." in body


def test_link_prompt_pack_run_updates_pack_query_and_run_note(tmp_path) -> None:
    vault = tmp_path / "vault"
    paths = initialize_vault(vault)
    query_create(vault, "Which sources update the mobility synthesis?", slug="mobility")
    generated = generate_prompt_pack(vault, query="mobility")
    run = RunRecord(
        slug="2026-05-15_mobility",
        date="2026-05-15",
        prompt="Find mobility evidence",
        exported_at="2026-05-15T10:00:00+02:00",
        export_file="/tmp/export.json",
        raw_export_file="raw/scholar-labs/export.json",
        staging_folder="/tmp/staging",
        result_count=0,
    )
    write_yaml(paths.runs / run.slug / "index.yaml", run.model_dump(exclude_none=True))

    linked = link_prompt_pack_run(vault, generated["id"], run.slug)
    pack_frontmatter, _ = read_frontmatter_markdown(vault / generated["prompt_pack"])
    query_frontmatter, query_body = read_frontmatter_markdown(paths.queries / "mobility.md")
    run_yaml = yaml.safe_load((paths.runs / run.slug / "index.yaml").read_text())
    run_note = (paths.runs / run.slug / "Mobility.md").read_text(encoding="utf-8")

    assert linked["changed"] is True
    assert pack_frontmatter["status"] == "imported"
    assert pack_frontmatter["linked_runs"] == [run.slug]
    assert query_frontmatter["linked_runs"] == [run.slug]
    assert f"Run: `{run.slug}`" in query_body
    assert run_yaml["prompt_pack"] == generated["prompt_pack"]
    assert run_yaml["query"] == "queries/mobility.md"
    assert generated["prompt_pack"] in run_note
    assert "queries/mobility.md" in run_note


def test_import_labs_links_prompt_pack_and_query(tmp_path) -> None:
    vault = tmp_path / "vault"
    staging = tmp_path / "staging"
    exports = tmp_path / "exports"
    staging.mkdir()
    exports.mkdir()
    paths = initialize_vault(vault)
    query_create(vault, "How should imported Labs runs link back?", slug="mobility")
    generated = generate_prompt_pack(vault, query="mobility")
    export = _write_export(
        exports / "labs.json",
        prompt="Find papers on imported Labs run prompt-pack linking.",
        result_title="Prompt Pack Linked Import",
    )
    _write_pdf_with_title(staging / "paper.pdf", "Prompt Pack Linked Import")

    summary = import_scholar_labs_run(
        vault,
        export,
        staging,
        commit=True,
        prompt_pack=generated["prompt_pack"],
        query="mobility",
    )
    run_id = str(summary["run"])
    pack_frontmatter, _ = read_frontmatter_markdown(vault / generated["prompt_pack"])
    query_frontmatter, query_body = read_frontmatter_markdown(paths.queries / "mobility.md")
    run_yaml = yaml.safe_load((paths.runs / run_id / "index.yaml").read_text())

    assert summary["selected"] == 1
    assert pack_frontmatter["status"] == "imported"
    assert pack_frontmatter["linked_runs"] == [run_id]
    assert query_frontmatter["linked_runs"] == [run_id]
    assert f"Run: `{run_id}`" in query_body
    assert run_yaml["prompt_pack"] == generated["prompt_pack"]
    assert run_yaml["query"] == "queries/mobility.md"


def test_prompt_pack_generation_uses_mocked_openalex_seed_without_google(
    tmp_path,
    monkeypatch,
) -> None:
    vault = tmp_path / "vault"
    initialize_vault(vault)
    query_create(vault, "How do benchmarks compare map evidence tools?", slug="benchmarks")
    urls = []

    def fake_http_json(url: str, _cache_path: Path, *, refresh: bool = False):
        urls.append(url)
        assert refresh is False
        return {
            "results": [
                {
                    "title": "Seed Candidate Benchmark Paper",
                    "publication_year": 2025,
                    "doi": "https://doi.org/10.1234/example",
                    "cited_by_count": 12,
                    "authorships": [{"author": {"display_name": "Alex Researcher"}}],
                    "primary_location": {"source": {"display_name": "Benchmark Venue"}},
                }
            ]
        }

    monkeypatch.setattr("scholar_vault.labs_prompts._http_json", fake_http_json)

    summary = generate_prompt_pack(vault, query="benchmarks", seed_api="openalex")
    _, body = read_frontmatter_markdown(vault / summary["prompt_pack"])

    assert urls
    assert all("google" not in url.casefold() for url in urls)
    assert "api.openalex.org" in urls[0]
    assert summary["seed_candidates"][0]["title"] == "Seed Candidate Benchmark Paper"
    assert "Seed Candidate Benchmark Paper" in body


def test_labs_prompts_cli_json_and_doctor(tmp_path) -> None:
    vault = tmp_path / "vault"
    initialize_vault(vault)
    query_create(vault, "How should CLI prompt packs work?", slug="cli-pack")
    runner = CliRunner()

    generated = runner.invoke(
        app,
        [
            "labs-prompts",
            "generate",
            "--vault",
            str(vault),
            "--query",
            "cli-pack",
            "--json",
        ],
    )
    listed = runner.invoke(app, ["labs-prompts", "list", "--vault", str(vault), "--json"])
    doctor = runner.invoke(app, ["labs-prompts", "doctor", "--vault", str(vault), "--json"])

    assert generated.exit_code == 0
    assert listed.exit_code == 0
    assert doctor.exit_code == 0
    generated_json = json.loads(generated.output)
    assert generated_json["prompt_pack"].endswith("query-cli-pack-scholar-labs-prompts.md")
    assert json.loads(listed.output)["count"] == 1
    assert json.loads(doctor.output)["ok"] is True
