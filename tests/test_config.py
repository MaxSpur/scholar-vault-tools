from __future__ import annotations

import json
import os
from pathlib import Path

import yaml
from typer.testing import CliRunner

from scholar_vault.cli import app
from scholar_vault.config import latest_export_json
from scholar_vault.importer import (
    PDF_SCAN_CACHE_FILENAME,
    import_scholar_labs_run,
    initialize_vault,
)


def _write_export(path: Path, *, prompt: str, exported_at: str) -> Path:
    payload = {
        "schema_version": "0.2",
        "source": "google_scholar_labs",
        "exported_at": exported_at,
        "title": prompt.title(),
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
    cache = exports / PDF_SCAN_CACHE_FILENAME
    cache.write_text("{}", encoding="utf-8")
    os.utime(old, (1, 1))
    os.utime(new, (2, 2))
    os.utime(used_newer, (3, 3))
    os.utime(cache, (4, 4))

    assert latest_export_json(exports) == new.resolve()


def test_configure_folder_mode_shared_removes_exports(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_path = tmp_path / "config.yaml"
    monkeypatch.setenv("SCHOLAR_VAULT_CONFIG", str(config_path))
    vault = tmp_path / "vault"
    staging = tmp_path / "staging"
    exports = tmp_path / "exports"
    for folder in (vault, staging, exports):
        folder.mkdir()

    runner = CliRunner()
    separate = runner.invoke(
        app,
        [
            "configure",
            "--vault",
            str(vault),
            "--staging",
            str(staging),
            "--exports",
            str(exports),
        ],
    )
    assert separate.exit_code == 0
    shared = runner.invoke(app, ["configure", "--folder-mode", "shared"])

    assert shared.exit_code == 0
    stored = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert stored["vault"] == str(vault.resolve())
    assert stored["staging"] == str(staging.resolve())
    assert "exports" not in stored
    assert "folder_mode: shared" in shared.output


def test_configure_folder_mode_separate_requires_exports(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("SCHOLAR_VAULT_CONFIG", str(tmp_path / "config.yaml"))

    result = CliRunner().invoke(app, ["configure", "--folder-mode", "separate"])

    assert result.exit_code != 0
    assert "--folder-mode separate requires --exports" in result.output


def test_configure_ui_saves_returned_config(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_path = tmp_path / "config.yaml"
    monkeypatch.setenv("SCHOLAR_VAULT_CONFIG", str(config_path))
    vault = tmp_path / "vault"
    staging = tmp_path / "staging"
    for folder in (vault, staging):
        folder.mkdir()

    seen: list[dict[str, object]] = []

    def fake_configure_ui(config: dict[str, object]) -> dict[str, object]:
        seen.append(dict(config))
        return {
            "vault": str(vault.resolve()),
            "staging": str(staging.resolve()),
        }

    monkeypatch.setattr("scholar_vault.cli._configure_ui", fake_configure_ui)

    result = CliRunner().invoke(app, ["configure", "--ui"])

    assert result.exit_code == 0
    assert seen == [{}]
    stored = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert stored["vault"] == str(vault.resolve())
    assert stored["staging"] == str(staging.resolve())
    assert "exports" not in stored


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


def test_import_labs_uses_staging_for_latest_export_when_exports_unset(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_path = tmp_path / "config.yaml"
    monkeypatch.setenv("SCHOLAR_VAULT_CONFIG", str(config_path))
    vault = tmp_path / "vault"
    staging = tmp_path / "staging"
    staging.mkdir()
    initialize_vault(vault)
    old = _write_export(
        staging / "old.json",
        prompt="old staging prompt",
        exported_at="2026-04-22T10:00:00+02:00",
    )
    new = _write_export(
        staging / "new.json",
        prompt="new staging prompt",
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
        ],
    )
    assert configure.exit_code == 0

    imported = runner.invoke(app, ["import-labs", "--commit"])

    assert imported.exit_code == 0
    stored = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert stored["staging"] == str(staging.resolve())
    assert "exports" not in stored
    assert not new.exists()
    assert (staging / "used" / "new.json").exists()
    run_yaml_paths = list((vault / "runs").glob("*/index.yaml"))
    assert len(run_yaml_paths) == 1
    run_yaml = yaml.safe_load(run_yaml_paths[0].read_text(encoding="utf-8"))
    assert run_yaml["export_file"] == str((staging / "used" / "new.json").resolve())
    assert run_yaml["prompt"] == "new staging prompt"


def test_import_labs_ui_existing_run_confirmation_uses_gui_callback(
    tmp_path: Path,
    monkeypatch,
) -> None:
    vault = tmp_path / "vault"
    staging = tmp_path / "staging"
    staging.mkdir()
    initialize_vault(vault)
    export = _write_export(
        staging / "sample.json",
        prompt="existing run prompt",
        exported_at="2026-04-23T10:00:00+02:00",
    )
    import_scholar_labs_run(vault, export, staging, commit=True, archive_export=False)
    prompts: list[str] = []
    ui_flags: list[bool] = []

    def fake_confirm(prompt: str) -> bool:
        prompts.append(prompt)
        return True

    def fake_confirm_callback(ui: bool):
        ui_flags.append(ui)
        return fake_confirm

    monkeypatch.setattr("scholar_vault.cli._confirm_callback", fake_confirm_callback)
    monkeypatch.setattr("scholar_vault.cli._match_reviewer", lambda _ui: lambda _request: False)
    monkeypatch.setattr("scholar_vault.cli._make_gui_progress", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("scholar_vault.cli._show_import_summary_ui", lambda *_args, **_kwargs: None)

    result = CliRunner().invoke(
        app,
        [
            "import-labs",
            "--vault",
            str(vault),
            "--staging",
            str(staging),
            "--export",
            str(export),
            "--ui",
            "--keep-export",
        ],
    )

    assert result.exit_code == 0
    assert ui_flags == [True]
    assert prompts == [
        "Run 2026-04-23_existing-run-prompt already exists. Resume and update it?"
    ]
    assert "[y/N]" not in result.output


def test_import_labs_existing_run_decline_exits_without_traceback(
    tmp_path: Path,
    monkeypatch,
) -> None:
    vault = tmp_path / "vault"
    staging = tmp_path / "staging"
    staging.mkdir()
    initialize_vault(vault)
    export = _write_export(
        staging / "sample.json",
        prompt="existing run prompt",
        exported_at="2026-04-23T10:00:00+02:00",
    )
    import_scholar_labs_run(vault, export, staging, commit=True, archive_export=False)

    monkeypatch.setattr("scholar_vault.cli._confirm_callback", lambda _ui: lambda _prompt: False)
    monkeypatch.setattr("scholar_vault.cli._match_reviewer", lambda _ui: lambda _request: False)
    monkeypatch.setattr("scholar_vault.cli._make_gui_progress", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("scholar_vault.cli._show_import_summary_ui", lambda *_args, **_kwargs: None)

    result = CliRunner().invoke(
        app,
        [
            "import-labs",
            "--vault",
            str(vault),
            "--staging",
            str(staging),
            "--export",
            str(export),
            "--ui",
            "--keep-export",
        ],
    )

    assert result.exit_code == 0
    assert "Run 2026-04-23_existing-run-prompt already exists. Import canceled." in result.output
    assert "Traceback" not in result.output
