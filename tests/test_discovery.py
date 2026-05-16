from __future__ import annotations

import json
from pathlib import Path

import yaml
from typer.testing import CliRunner

from scholar_vault.cli import app
from scholar_vault.discovery import (
    discover_query,
    discovery_to_labs_prompts,
    list_discovery_candidates,
    reject_candidate,
    select_candidate,
    update_candidate_status,
)
from scholar_vault.importer import initialize_vault
from scholar_vault.labs_prompts import link_prompt_pack_run
from scholar_vault.models import RunRecord
from scholar_vault.queries import query_create
from scholar_vault.sources import read_frontmatter_markdown, write_yaml


def _write_paper(paths, slug: str, title: str, *, doi: str | None = None) -> None:
    doi_line = f"doi: {doi}\n" if doi else "doi:\n"
    (paths.papers / f"{slug}.md").write_text(
        f"""---
type: paper
citekey: {slug}
title: {title}
authors:
  - Jane Smith
year: 2024
venue: Existing Venue
{doi_line}pdf_status: missing
reading_status: unread
compiled_status: uncompiled
---

# {title}

## Summary
No summary yet.

## Notes
Fixture.
""",
        encoding="utf-8",
    )


def _mock_provider_http(openalex_title: str = "OpenAlex Candidate"):
    def fake_http_json(url: str, cache_path: Path, **_kwargs):
        if "api.openalex.org" in url:
            payload = {
                "results": [
                    {
                        "id": "https://openalex.org/W123",
                        "title": openalex_title,
                        "publication_year": 2025,
                        "doi": "https://doi.org/10.1111/openalex",
                        "cited_by_count": 42,
                        "authorships": [{"author": {"display_name": "Alex Researcher"}}],
                        "primary_location": {"source": {"display_name": "OpenAlex Venue"}},
                        "abstract_inverted_index": {
                            "Graph": [0],
                            "assisted": [1],
                            "discovery": [2],
                        },
                    }
                ]
            }
        elif "api.semanticscholar.org" in url:
            payload = {
                "data": [
                    {
                        "paperId": "S2Paper1",
                        "title": "Semantic Scholar Candidate",
                        "year": 2024,
                        "authors": [{"name": "Sam Semantic"}],
                        "venue": "S2 Venue",
                        "url": "https://www.semanticscholar.org/paper/S2Paper1",
                        "externalIds": {"DOI": "10.2222/s2"},
                        "citationCount": 7,
                        "abstract": "A Semantic Scholar fixture abstract.",
                    }
                ]
            }
        else:
            payload = {}
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(payload), encoding="utf-8")
        return payload

    return fake_http_json


def test_discover_query_creates_openalex_and_semantic_candidates(monkeypatch, tmp_path) -> None:
    vault = tmp_path / "vault"
    paths = initialize_vault(vault)
    query_create(vault, "How do graph methods improve related-paper discovery?", slug="graphs")
    monkeypatch.setattr("scholar_vault.discovery_adapters._http_json", _mock_provider_http())

    summary = discover_query(
        vault,
        query_slug="graphs",
        sources=["openalex", "semantic_scholar"],
        limit=5,
    )
    candidates = list_discovery_candidates(vault)

    assert summary["created"] == 2
    assert summary["skipped_imported"] == 0
    assert candidates["count"] == 2
    assert not list(paths.papers.glob("*.md"))
    assert (paths.raw_discovery / "openalex").exists()
    assert (paths.raw_discovery / "semantic_scholar").exists()
    rows = {row["id"]: row for row in candidates["candidates"]}
    assert rows["openalex-w123"]["source"] == "openalex"
    assert rows["semantic_scholar-s2paper1"]["source"] == "semantic_scholar"
    assert rows["openalex-w123"]["query"] == "queries/graphs.md"


def test_discovery_deduplicates_against_existing_paper_cards(monkeypatch, tmp_path) -> None:
    vault = tmp_path / "vault"
    paths = initialize_vault(vault)
    query_create(vault, "How does DOI dedupe work?", slug="dedupe")
    _write_paper(paths, "existing", "Already Imported Paper", doi="10.1111/openalex")
    monkeypatch.setattr(
        "scholar_vault.discovery_adapters._http_json",
        _mock_provider_http("Already Imported Paper"),
    )

    summary = discover_query(vault, query_slug="dedupe", sources=["openalex"], limit=5)

    assert summary["created"] == 0
    assert summary["skipped_imported"] == 1
    assert list_discovery_candidates(vault)["count"] == 0


def test_candidate_selection_rejection_and_imported_status(monkeypatch, tmp_path) -> None:
    vault = tmp_path / "vault"
    initialize_vault(vault)
    query_create(vault, "How should candidate statuses work?", slug="statuses")
    monkeypatch.setattr("scholar_vault.discovery_adapters._http_json", _mock_provider_http())
    discover_query(vault, query_slug="statuses", sources=["openalex"], limit=5)

    selected = select_candidate(vault, "openalex-w123")
    rejected = reject_candidate(vault, "openalex-w123")
    imported = update_candidate_status(
        vault,
        "openalex-w123",
        status="imported",
        linked_run="run-1",
    )
    row = list_discovery_candidates(vault)["candidates"][0]

    assert selected["status"] == "selected"
    assert rejected["previous_status"] == "selected"
    assert imported["status"] == "imported"
    assert row["status"] == "imported"
    assert row["linked_run"] == "run-1"


def test_discovery_candidates_generate_labs_prompt_seed_pack(monkeypatch, tmp_path) -> None:
    vault = tmp_path / "vault"
    paths = initialize_vault(vault)
    query_create(vault, "Which graph signals reveal directly related papers?", slug="prompt-seeds")
    monkeypatch.setattr("scholar_vault.discovery_adapters._http_json", _mock_provider_http())
    discover_query(vault, query_slug="prompt-seeds", sources=["openalex"], limit=5)
    select_candidate(vault, "openalex-w123")

    summary = discovery_to_labs_prompts(vault, query_slug="prompt-seeds")
    frontmatter, body = read_frontmatter_markdown(vault / summary["prompt_pack"])
    query_frontmatter, _ = read_frontmatter_markdown(paths.queries / "prompt-seeds.md")
    candidate_yaml = yaml.safe_load((paths.discovery_candidates / "openalex-w123.yaml").read_text())

    assert summary["seed_provider"] == "discovery"
    assert summary["candidate_count"] == 1
    assert frontmatter["type"] == "scholar_labs_prompt_pack"
    assert frontmatter["linked_discovery_candidates"] == [
        "tasks/discovery-candidates/openalex-w123.yaml"
    ]
    assert "Starting from these candidate papers/terms" in body
    assert "OpenAlex Candidate" in body
    assert summary["prompt_pack"] in query_frontmatter["scholar_labs_prompt_pack"]
    assert candidate_yaml["linked_prompt_pack"] == summary["prompt_pack"]

    run = RunRecord(
        slug="2026-05-15_prompt-seeds",
        date="2026-05-15",
        prompt="Find directly related graph signal papers",
        exported_at="2026-05-15T10:00:00+02:00",
        export_file="/tmp/export.json",
        raw_export_file="raw/scholar-labs/export.json",
        result_count=0,
    )
    write_yaml(paths.runs / run.slug / "index.yaml", run.model_dump(exclude_none=True))
    linked = link_prompt_pack_run(vault, summary["prompt_pack"], run.slug)
    candidate_yaml = yaml.safe_load((paths.discovery_candidates / "openalex-w123.yaml").read_text())

    assert linked["discovery_candidates_linked"] == 1
    assert candidate_yaml["status"] == "imported"
    assert candidate_yaml["linked_run"] == run.slug


def test_discovery_cli_json_and_doctor(monkeypatch, tmp_path) -> None:
    vault = tmp_path / "vault"
    initialize_vault(vault)
    query_create(vault, "How should the discovery CLI work?", slug="cli-discovery")
    monkeypatch.setattr("scholar_vault.discovery_adapters._http_json", _mock_provider_http())
    runner = CliRunner()

    generated = runner.invoke(
        app,
        [
            "discover",
            "query",
            "--vault",
            str(vault),
            "--query",
            "cli-discovery",
            "--source",
            "openalex",
            "--json",
        ],
    )
    listed = runner.invoke(app, ["discover", "list", "--vault", str(vault), "--json"])
    doctor = runner.invoke(app, ["discover", "doctor", "--vault", str(vault), "--json"])

    assert generated.exit_code == 0, generated.output
    assert listed.exit_code == 0, listed.output
    assert doctor.exit_code == 0, doctor.output
    assert json.loads(generated.output)["created"] == 1
    assert json.loads(listed.output)["count"] == 1
    doctor_json = json.loads(doctor.output)
    assert doctor_json["ok"] is True
    assert doctor_json["counts"]["discovery_candidates"] == 1
