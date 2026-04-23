from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml


def user_config_path() -> Path:
    configured = os.environ.get("SCHOLAR_VAULT_CONFIG")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".config" / "scholar-vault" / "config.yaml"


def load_user_config(path: Path | None = None) -> dict[str, Any]:
    config_path = path or user_config_path()
    if not config_path.exists():
        return {}
    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def save_user_config(config: dict[str, Any], path: Path | None = None) -> Path:
    config_path = path or user_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return config_path


def configured_path(key: str, config: dict[str, Any] | None = None) -> Path | None:
    value = (config or load_user_config()).get(key)
    if not value:
        return None
    return Path(str(value)).expanduser()


def latest_export_json(exports_dir: Path) -> Path:
    candidates = [
        path
        for path in exports_dir.expanduser().iterdir()
        if path.is_file() and path.suffix.casefold() == ".json"
    ]
    if not candidates:
        raise FileNotFoundError(f"No JSON export files found in {exports_dir}")
    return max(candidates, key=lambda path: (path.stat().st_mtime, path.name)).resolve()
