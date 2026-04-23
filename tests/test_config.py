from __future__ import annotations

import json
import os
from pathlib import Path

import yaml
from typer.testing import CliRunner

from scholar_vault.cli import app
from scholar_vault.config import latest_export_json
from scholar_vault.importer import initialize_vault


def _write_export(path: Path, *, prompt: str, exported_at: str) -> Path:
    payload = {
        "schema_version": "0.2",
        "source": "google_scholar_labs",
        "exported_at": exported_at,
        "prompt": prompt,
        "results": [
            {
                "rank": 1,
                "scholar_cid": "cid-001",
                "title": "Result Paper 1",
                "authors_preview": "Jane Smith",
                "year": 2024,
                "venue_preview": "Test Venue",
                "summary": "A visible Scholar Labs summary.",
                "rationale_points": [{"label": "Test", "text": "Useful result."}],
                "links": [{"label": "publication", "url": "https://example.com", "kind": "html"}],
            }
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_latest_export_json_ignores_used_subfolder(tmp_path: Path) -> None:
    exports = tmp_path / "exports"
    used = exports / "used"
    used.mkdir(parents=True)
    old = _write_export(
        exports / "old.json",
        prompt="old prompt about local archives",
        exported_at="2026-04-22T10:00:00+02:00",
    )
    new = _write_export(
        exports / "new.json",
        prompt="new prompt about immersive analytics",
        exported_at="2026-04-23T10:00:00+02:00",
    )
    used_newer = _write_export(
        used / "used-newer.json",
        prompt="used prompt that should be ignored",
        exported_at="2026-04-24T10:00:00+02:00",
    )
    os.utime(old, (1, 1))
    os.utime(new, (2, 2))
    os.utime(used_newer, (3, 3))

    assert latest_export_json(exports) == new.resolve()


def test_import_labs_uses_configured_paths_and_latest_export(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_path = tmp_path / "config.yaml"
    monkeypatch.setenv("SCHOLAR_VAULT_CONFIG", str(config_path))
    vault = tmp_path / "vault"
    staging = tmp_path / "staging"
    exports = tmp_path / "exports"
    code = tmp_path / "code"
    staging.mkdir()
    exports.mkdir()
    code.mkdir()
    initialize_vault(vault)
    old = _write_export(
        exports / "old.json",
        prompt="old prompt about local archives",
        exported_at="2026-04-22T10:00:00+02:00",
    )
    new = _write_export(
        exports / "new.json",
        prompt="new prompt about immersive analytics",
        exported_at="2026-04-23T10:00:00+02:00",
    )
    os.utime(old, (1, 1))
    os.utime(new, (2, 2))

    runner = CliRunner()
    configure = runner.invoke(
        app,
        [
            "configure",
            "--vault",
            str(vault),
            "--staging",
            str(staging),
            "--exports",
            str(exports),
            "--code",
            str(code),
        ],
    )
    assert configure.exit_code == 0

    imported = runner.invoke(app, ["import-labs", "--commit", "--keep-export"])

    assert imported.exit_code == 0
    assert config_path.exists()
    stored = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert stored["vault"] == str(vault.resolve())
    run_yaml_paths = list((vault / "runs").glob("*/index.yaml"))
    assert len(run_yaml_paths) == 1
    run_yaml = yaml.safe_load(run_yaml_paths[0].read_text(encoding="utf-8"))
    assert run_yaml["export_file"] == str(new.resolve())
    assert run_yaml["prompt"] == "new prompt about immersive analytics"
