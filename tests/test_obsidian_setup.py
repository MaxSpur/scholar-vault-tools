from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from scholar_vault.cli import app
from scholar_vault.importer import initialize_vault


def _write_json(path: Path, data: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_obsidian_setup_dry_run_shows_diff_without_writing(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    initialize_vault(vault)

    result = CliRunner().invoke(
        app,
        ["obsidian", "setup", "--vault", str(vault), "--dry-run", "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["applied"] is False
    assert payload["changed"] == 2
    assert payload["blocked"] == 0
    assert "-path:_indexes/" in payload["files"][0]["diff"]
    assert payload["plugins_installed"] == []
    assert not (vault / ".obsidian").exists()


def test_obsidian_setup_apply_preserves_user_settings_and_writes_backups(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    initialize_vault(vault)
    obsidian = vault / ".obsidian"
    original_graph = {
        "search": "tag:#keep",
        "showTags": True,
        "colorGroups": [{"query": "tag:#manual", "color": {"a": 1, "rgb": 123}}],
    }
    original_app = {
        "alwaysUpdateLinks": True,
        "showUnsupportedFiles": True,
        "userIgnoreFilters": ["templates/"],
    }
    _write_json(obsidian / "graph.json", original_graph)
    _write_json(obsidian / "app.json", original_app)

    result = CliRunner().invoke(
        app,
        ["obsidian", "setup", "--vault", str(vault), "--apply", "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["applied"] is True
    assert payload["changed"] == 2
    assert len(payload["backups"]) == 2

    graph = _read_json(obsidian / "graph.json")
    assert graph["showTags"] is True
    assert graph["search"].startswith("tag:#keep")
    assert "-path:_indexes/" in graph["search"]
    assert "-path:_exports/" in graph["search"]
    assert "-path:topics/" in graph["search"]
    assert "-path:runs/" in graph["search"]
    assert "-file:project-map" in graph["search"]
    graph_queries = [group["query"] for group in graph["colorGroups"]]
    assert "tag:#manual" in graph_queries
    assert "path:papers/" in graph_queries
    assert "path:paper-digests/" in graph_queries
    assert "path:proposals/" in graph_queries

    app_settings = _read_json(obsidian / "app.json")
    assert app_settings["alwaysUpdateLinks"] is True
    assert app_settings["showUnsupportedFiles"] is True
    assert app_settings["userIgnoreFilters"] == ["templates/", "_exports/"]

    backups = [vault / backup for backup in payload["backups"]]
    backup_names = {backup.name for backup in backups}
    assert backup_names == {"graph.json", "app.json"}
    graph_backup = next(backup for backup in backups if backup.name == "graph.json")
    app_backup = next(backup for backup in backups if backup.name == "app.json")
    assert _read_json(graph_backup) == original_graph
    assert _read_json(app_backup) == original_app


def test_obsidian_setup_is_idempotent_after_apply(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    initialize_vault(vault)

    first = CliRunner().invoke(
        app,
        ["obsidian", "setup", "--vault", str(vault), "--apply", "--json"],
    )
    second = CliRunner().invoke(
        app,
        ["obsidian", "setup", "--vault", str(vault), "--apply", "--json"],
    )

    assert first.exit_code == 0
    assert second.exit_code == 0
    assert json.loads(first.output)["changed"] == 2
    payload = json.loads(second.output)
    assert payload["changed"] == 0
    assert payload["backups"] == []


def test_obsidian_doctor_json_reports_ok_after_setup(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    initialize_vault(vault)
    setup = CliRunner().invoke(
        app,
        ["obsidian", "setup", "--vault", str(vault), "--apply", "--json"],
    )
    assert setup.exit_code == 0

    result = CliRunner().invoke(
        app,
        ["obsidian", "doctor", "--vault", str(vault), "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["issue_counts"]["missing_graph_filters"] == 0
    assert payload["warning_counts"]["missing_graph_groups"] == 0
    assert payload["warning_counts"]["missing_app_ignore_filters"] == 0


def test_obsidian_setup_blocks_invalid_existing_settings(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    initialize_vault(vault)
    graph = vault / ".obsidian" / "graph.json"
    graph.parent.mkdir(parents=True)
    graph.write_text("{not valid json\n", encoding="utf-8")

    result = CliRunner().invoke(
        app,
        ["obsidian", "setup", "--vault", str(vault), "--apply", "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["blocked"] == 1
    assert payload["files"][0]["action"] == "blocked"
    assert "invalid JSON" in payload["files"][0]["issues"][0]
    assert graph.read_text(encoding="utf-8") == "{not valid json\n"
