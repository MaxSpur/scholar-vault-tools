from __future__ import annotations

import difflib
import json
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .sources import VaultPaths, ensure_relative

OBSIDIAN_DIR = ".obsidian"
GRAPH_SETTINGS = "graph.json"
APP_SETTINGS = "app.json"
BACKUP_DIR = ".scholar-vault-backups"

GRAPH_FILTER_TERMS: tuple[str, ...] = (
    "-path:_indexes/",
    "-path:_exports/",
    "-path:topics/",
    "-path:runs/",
    "-file:project-map",
)

APP_IGNORE_FILTERS: tuple[str, ...] = ("_exports/",)


@dataclass(frozen=True)
class GraphGroup:
    name: str
    query: str
    rgb: int

    def to_obsidian(self) -> dict[str, Any]:
        return {"query": self.query, "color": {"a": 1, "rgb": self.rgb}}


GRAPH_GROUPS: tuple[GraphGroup, ...] = (
    GraphGroup("papers", "path:papers/", 0x4E79A7),
    GraphGroup("paper-digests", "path:paper-digests/", 0x59A14F),
    GraphGroup("concepts", "path:concepts/", 0xF28E2B),
    GraphGroup("syntheses", "path:syntheses/", 0xE15759),
    GraphGroup("queries", "path:queries/", 0x76B7B2),
    GraphGroup("projects", "path:projects/", 0xEDC948),
    GraphGroup("proposals", "path:proposals/", 0xB07AA1),
)


def _dump_json(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def _load_json_object(path: Path) -> tuple[dict[str, Any] | None, str | None, list[str]]:
    if not path.exists():
        return {}, None, []
    text = path.read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, text, [f"invalid JSON: {exc}"]
    if not isinstance(data, dict):
        return None, text, ["settings JSON must be an object"]
    return data, text, []


def _merge_graph_search(existing: Any) -> tuple[str | None, list[str]]:
    if existing is None:
        query = ""
    elif isinstance(existing, str):
        query = " ".join(existing.split())
    else:
        return None, ["graph search setting must be a string"]
    tokens = query.split()
    for term in GRAPH_FILTER_TERMS:
        if term not in tokens:
            tokens.append(term)
    return " ".join(tokens), []


def _merge_graph_settings(
    data: dict[str, Any],
    *,
    include_groups: bool,
) -> tuple[dict[str, Any] | None, list[str]]:
    merged = dict(data)
    search, issues = _merge_graph_search(merged.get("search"))
    if issues or search is None:
        return None, issues
    merged["search"] = search

    if "showAttachments" not in merged:
        merged["showAttachments"] = False
    if "hideUnresolved" not in merged:
        merged["hideUnresolved"] = True

    if include_groups:
        color_groups = merged.get("colorGroups")
        if color_groups is None:
            color_groups = []
        if not isinstance(color_groups, list):
            return None, ["graph colorGroups setting must be a list"]
        existing_queries = {
            str(group.get("query")).strip()
            for group in color_groups
            if isinstance(group, dict) and group.get("query")
        }
        merged_groups = list(color_groups)
        for group in GRAPH_GROUPS:
            if group.query not in existing_queries:
                merged_groups.append(group.to_obsidian())
        merged["colorGroups"] = merged_groups

    return merged, []


def _merge_app_settings(data: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
    merged = dict(data)
    ignore_filters = merged.get("userIgnoreFilters")
    if ignore_filters is None:
        ignore_filters = []
    if not isinstance(ignore_filters, list) or not all(
        isinstance(item, str) for item in ignore_filters
    ):
        return None, ["app userIgnoreFilters setting must be a list of strings"]
    merged_filters = list(ignore_filters)
    for pattern in APP_IGNORE_FILTERS:
        if pattern not in merged_filters:
            merged_filters.append(pattern)
    merged["userIgnoreFilters"] = merged_filters
    if "showUnsupportedFiles" not in merged:
        merged["showUnsupportedFiles"] = False
    return merged, []


def _diff_text(path: str, original: str | None, planned: str) -> str:
    from_lines = [] if original is None else original.splitlines()
    to_lines = planned.splitlines()
    fromfile = "/dev/null" if original is None else f"a/{path}"
    tofile = f"b/{path}"
    diff_lines = list(
        difflib.unified_diff(
            from_lines,
            to_lines,
            fromfile=fromfile,
            tofile=tofile,
            lineterm="",
        )
    )
    return "\n".join(diff_lines) + ("\n" if diff_lines else "")


def _timestamp() -> str:
    return datetime.now().astimezone().strftime("%Y%m%d-%H%M%S-%f")


def _plan_file(
    paths: VaultPaths,
    path: Path,
    planned_data: dict[str, Any] | None,
    original_text: str | None,
    issues: list[str],
) -> dict[str, Any]:
    relative = ensure_relative(path, paths.vault)
    if issues or planned_data is None:
        return {
            "path": relative,
            "action": "blocked",
            "changed": False,
            "backup": None,
            "issues": issues,
            "diff": "",
        }
    planned_text = _dump_json(planned_data)
    changed = original_text != planned_text
    if original_text is None:
        action = "create"
    elif changed:
        action = "update"
    else:
        action = "unchanged"
    return {
        "path": relative,
        "action": action,
        "changed": changed,
        "backup": None,
        "issues": [],
        "diff": _diff_text(relative, original_text, planned_text) if changed else "",
        "_planned_text": planned_text,
    }


def _backup_existing(path: Path, backup_root: Path) -> Path:
    destination = backup_root / path.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, destination)
    return destination


def setup_obsidian(
    vault: Path | str,
    *,
    apply: bool = False,
    include_groups: bool = True,
) -> dict[str, Any]:
    paths = VaultPaths.from_root(vault)
    obsidian_dir = paths.vault / OBSIDIAN_DIR
    graph_path = obsidian_dir / GRAPH_SETTINGS
    app_path = obsidian_dir / APP_SETTINGS

    graph_data, graph_original, graph_issues = _load_json_object(graph_path)
    planned_graph, graph_merge_issues = (
        (None, [])
        if graph_data is None
        else _merge_graph_settings(graph_data, include_groups=include_groups)
    )
    app_data, app_original, app_issues = _load_json_object(app_path)
    planned_app, app_merge_issues = (
        (None, []) if app_data is None else _merge_app_settings(app_data)
    )

    files = [
        _plan_file(
            paths,
            graph_path,
            planned_graph,
            graph_original,
            graph_issues + graph_merge_issues,
        ),
        _plan_file(paths, app_path, planned_app, app_original, app_issues + app_merge_issues),
    ]

    backup_root: Path | None = None
    if apply:
        for row in files:
            if not row["changed"] or row["action"] == "blocked":
                continue
            target = paths.vault / row["path"]
            if target.exists():
                if backup_root is None:
                    backup_root = obsidian_dir / BACKUP_DIR / _timestamp()
                backup_path = _backup_existing(target, backup_root)
                row["backup"] = ensure_relative(backup_path, paths.vault)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(str(row.pop("_planned_text")), encoding="utf-8")
        for row in files:
            row.pop("_planned_text", None)
    else:
        for row in files:
            row.pop("_planned_text", None)

    changed = sum(1 for row in files if row["changed"])
    blocked = sum(1 for row in files if row["action"] == "blocked")
    backups = [row["backup"] for row in files if row.get("backup")]
    return {
        "vault": str(paths.vault),
        "apply": apply,
        "applied": apply,
        "changed": changed,
        "blocked": blocked,
        "backups": backups,
        "files": files,
        "graph_filters": list(GRAPH_FILTER_TERMS),
        "graph_groups": [{"name": group.name, "query": group.query} for group in GRAPH_GROUPS],
        "app_ignore_filters": list(APP_IGNORE_FILTERS),
        "plugins_installed": [],
    }


def _read_doctor_json(path: Path) -> tuple[dict[str, Any] | None, list[str]]:
    data, _text, issues = _load_json_object(path)
    return data, issues


def doctor_obsidian(vault: Path | str) -> dict[str, Any]:
    paths = VaultPaths.from_root(vault)
    obsidian_dir = paths.vault / OBSIDIAN_DIR
    graph_path = obsidian_dir / GRAPH_SETTINGS
    app_path = obsidian_dir / APP_SETTINGS
    issue_counts = {
        "missing_obsidian_dir": 0,
        "missing_graph": 0,
        "invalid_json": 0,
        "invalid_graph_search": 0,
        "missing_graph_filters": 0,
    }
    warning_counts = {
        "missing_graph_groups": 0,
        "missing_app": 0,
        "missing_app_ignore_filters": 0,
    }
    files: list[dict[str, Any]] = []

    if not obsidian_dir.exists():
        issue_counts["missing_obsidian_dir"] = 1

    graph_row: dict[str, Any] = {
        "path": ensure_relative(graph_path, paths.vault),
        "exists": graph_path.exists(),
        "ok": True,
        "issues": [],
        "warnings": [],
        "missing_filters": [],
        "missing_groups": [],
    }
    if not graph_path.exists():
        graph_row["ok"] = False
        graph_row["issues"].append("missing graph settings")
        issue_counts["missing_graph"] += 1
    else:
        graph_data, graph_issues = _read_doctor_json(graph_path)
        if graph_issues or graph_data is None:
            graph_row["ok"] = False
            graph_row["issues"].extend(graph_issues)
            issue_counts["invalid_json"] += 1
        else:
            search = graph_data.get("search")
            if not isinstance(search, str):
                graph_row["ok"] = False
                graph_row["issues"].append("graph search setting must be a string")
                issue_counts["invalid_graph_search"] += 1
            else:
                tokens = search.split()
                missing_filters = [term for term in GRAPH_FILTER_TERMS if term not in tokens]
                graph_row["missing_filters"] = missing_filters
                if missing_filters:
                    graph_row["ok"] = False
                    graph_row["issues"].append(
                        f"missing graph filters: {', '.join(missing_filters)}"
                    )
                    issue_counts["missing_graph_filters"] += len(missing_filters)
            color_groups = graph_data.get("colorGroups", [])
            if isinstance(color_groups, list):
                group_queries = {
                    str(group.get("query")).strip()
                    for group in color_groups
                    if isinstance(group, dict) and group.get("query")
                }
                missing_groups = [
                    {"name": group.name, "query": group.query}
                    for group in GRAPH_GROUPS
                    if group.query not in group_queries
                ]
                graph_row["missing_groups"] = missing_groups
                if missing_groups:
                    graph_row["warnings"].append(
                        "missing optional graph groups: "
                        + ", ".join(group["name"] for group in missing_groups)
                    )
                    warning_counts["missing_graph_groups"] += len(missing_groups)
            else:
                graph_row["warnings"].append("graph colorGroups setting is not a list")
                warning_counts["missing_graph_groups"] += len(GRAPH_GROUPS)
    files.append(graph_row)

    app_row: dict[str, Any] = {
        "path": ensure_relative(app_path, paths.vault),
        "exists": app_path.exists(),
        "ok": True,
        "issues": [],
        "warnings": [],
        "missing_ignore_filters": [],
    }
    if not app_path.exists():
        app_row["warnings"].append("missing app settings")
        warning_counts["missing_app"] += 1
    else:
        app_data, app_issues = _read_doctor_json(app_path)
        if app_issues or app_data is None:
            app_row["ok"] = False
            app_row["issues"].extend(app_issues)
            issue_counts["invalid_json"] += 1
        else:
            ignore_filters = app_data.get("userIgnoreFilters")
            if isinstance(ignore_filters, list):
                missing = [
                    pattern for pattern in APP_IGNORE_FILTERS if pattern not in ignore_filters
                ]
                app_row["missing_ignore_filters"] = missing
                if missing:
                    app_row["warnings"].append(
                        f"missing app ignore filters: {', '.join(missing)}"
                    )
                    warning_counts["missing_app_ignore_filters"] += len(missing)
            else:
                app_row["warnings"].append("app userIgnoreFilters setting is not a list")
                warning_counts["missing_app_ignore_filters"] += len(APP_IGNORE_FILTERS)
    files.append(app_row)

    return {
        "vault": str(paths.vault),
        "ok": not any(issue_counts.values()) and all(row["ok"] for row in files),
        "issue_counts": issue_counts,
        "warning_counts": warning_counts,
        "files": files,
        "graph_filters": list(GRAPH_FILTER_TERMS),
        "graph_groups": [{"name": group.name, "query": group.query} for group in GRAPH_GROUPS],
        "app_ignore_filters": list(APP_IGNORE_FILTERS),
    }
