from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

from .bases import _base_documents, _dump_base_yaml, doctor_bases, rebuild_bases
from .diagnostics import doctor_vault
from .digests import compile_doctor
from .rebuild import rebuild_generated_outputs
from .render import render_vault_agents, render_vault_readme
from .self_improvement import log_operation
from .semantic_lint import lint_wiki
from .sources import VaultPaths, dump_frontmatter, ensure_relative, write_text, write_yaml

FRONTMATTER_BODY_RE = re.compile(r"^---\n(?P<frontmatter>.*?)\n---(?P<body>\n?.*)\Z", re.DOTALL)

SAFE_PAPER_FRONTMATTER_DEFAULTS: dict[str, Any] = {
    "type": "paper",
    "publication_keywords_status": "missing",
    "publication_keywords_source": None,
    "status": "active",
    "pdf_status": "missing",
    "reading_status": "unread",
    "compiled_status": "uncompiled",
    "review_status": "unreviewed",
    "last_read_at": None,
    "last_compiled_at": None,
    "last_reviewed_at": None,
    "evidence_level": "unknown",
    "paper_digest": None,
    "linked_queries": [],
    "linked_query_paths": [],
    "linked_projects": [],
    "doi_status": "missing",
    "doi_source": None,
    "doi_confidence": None,
    "citation_status": "missing",
    "citation_source": None,
    "citation_last_checked": None,
    "citation_enriched_at": None,
    "citation_input_fingerprint": None,
    "citation_retries": 0,
    "citation_skip_reason": None,
    "metadata_lock": False,
    "enrichment_status": "missing",
    "enrichment_missing": [],
    "enrichment_refresh": False,
    "abstract_status": "missing",
    "abstract_source": None,
    "abstract_source_url": None,
    "abstract_confidence": None,
    "abstract_last_checked": None,
    "abstract_enriched_at": None,
    "abstract_input_fingerprint": None,
    "abstract_lock": False,
    "links": [],
}


def _init_config() -> dict[str, Any]:
    return {
        "schema_version": "0.1",
        "name": "scholar-vault",
        "source_kinds": [
            "scholar_labs",
            "pdf_drop",
            "bibtex_import",
            "doi_import",
            "manual",
        ],
    }


def _change(
    action: str,
    path: str,
    *,
    detail: str,
    fields: list[str] | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "action": action,
        "path": path,
        "detail": detail,
    }
    if fields is not None:
        row["fields"] = fields
    return row


def _rel(paths: VaultPaths, path: Path) -> str:
    return ensure_relative(path, paths.vault)


def _planned_directory_changes(paths: VaultPaths) -> list[dict[str, Any]]:
    return [
        _change("create_directory", _rel(paths, path), detail="managed vault folder is missing")
        for path in paths.managed_directories()
        if not path.exists()
    ]


def _starter_file_changes(
    paths: VaultPaths,
    *,
    update_agents: bool,
) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    starters = [
        (paths.vault / "config.yaml", yaml.safe_dump(_init_config(), sort_keys=False)),
        (paths.vault / "README.md", render_vault_readme().rstrip() + "\n"),
    ]
    for path, _content in starters:
        if not path.exists():
            changes.append(
                _change("create_file", _rel(paths, path), detail="starter vault file is missing")
            )
    agents_path = paths.vault / "AGENTS.md"
    agents_content = render_vault_agents().rstrip() + "\n"
    if not agents_path.exists():
        changes.append(
            _change(
                "create_file",
                _rel(paths, agents_path),
                detail="vault agent guide is missing",
            )
        )
    elif update_agents and agents_path.read_text(encoding="utf-8") != agents_content:
        changes.append(
            _change(
                "update_file",
                _rel(paths, agents_path),
                detail="vault agent guide update was explicitly requested",
            )
        )
    return changes


def _read_paper_frontmatter(path: Path) -> tuple[dict[str, Any], str] | None:
    text = path.read_text(encoding="utf-8")
    match = FRONTMATTER_BODY_RE.match(text)
    if not match:
        return {}, text
    frontmatter = yaml.safe_load(match.group("frontmatter")) or {}
    if not isinstance(frontmatter, dict):
        frontmatter = {}
    return frontmatter, match.group("body")


def _paper_frontmatter_changes(paths: VaultPaths) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    if not paths.papers.exists():
        return changes
    for path in sorted(paths.papers.glob("*.md")):
        parsed = _read_paper_frontmatter(path)
        if parsed is None:
            continue
        frontmatter, _body = parsed
        missing = [
            field
            for field in SAFE_PAPER_FRONTMATTER_DEFAULTS
            if field not in frontmatter
        ]
        if missing:
            changes.append(
                _change(
                    "backfill_paper_frontmatter",
                    _rel(paths, path),
                    detail="safe operational paper-card fields are absent",
                    fields=missing,
                )
            )
    return changes


def _apply_starter_files(paths: VaultPaths, *, update_agents: bool) -> None:
    config_path = paths.vault / "config.yaml"
    if not config_path.exists():
        write_yaml(config_path, _init_config())
    readme_path = paths.vault / "README.md"
    if not readme_path.exists():
        write_text(readme_path, render_vault_readme())
    agents_path = paths.vault / "AGENTS.md"
    agents_content = render_vault_agents()
    if not agents_path.exists() or update_agents:
        if not agents_path.exists() or agents_path.read_text(encoding="utf-8") != agents_content:
            write_text(agents_path, agents_content)


def _apply_paper_frontmatter_backfills(paths: VaultPaths) -> None:
    if not paths.papers.exists():
        return
    for path in sorted(paths.papers.glob("*.md")):
        parsed = _read_paper_frontmatter(path)
        if parsed is None:
            continue
        frontmatter, body = parsed
        missing = {
            field: value
            for field, value in SAFE_PAPER_FRONTMATTER_DEFAULTS.items()
            if field not in frontmatter
        }
        if not missing:
            continue
        updated = dict(frontmatter)
        updated.update(missing)
        path.write_text(
            f"---\n{dump_frontmatter(updated).strip()}\n---{body}",
            encoding="utf-8",
        )


def _planned_generated_output_changes(paths: VaultPaths) -> list[dict[str, Any]]:
    summary = rebuild_generated_outputs(paths.vault, apply=False)
    return [
        _change(
            "refresh_generated_output",
            str(row["path"]),
            detail=f"generated output would be {row['operation']}d",
        )
        for row in summary["files"]
        if row["changed"]
    ]


def _planned_base_changes(paths: VaultPaths) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    for filename, data in _base_documents().items():
        path = paths.bases / filename
        text = _dump_base_yaml(data)
        before = path.read_text(encoding="utf-8") if path.exists() else None
        if before == text:
            continue
        operation = "updated" if path.exists() else "created"
        changes.append(
            _change(
                "refresh_base",
                _rel(paths, path),
                detail=f"generated Obsidian Base would be {operation}",
            )
        )
    return changes


def _run_post_migration_checks(paths: VaultPaths) -> dict[str, Any]:
    return {
        "doctor": doctor_vault(paths.vault),
        "compile_doctor": compile_doctor(paths.vault),
        "bases_doctor": doctor_bases(paths.vault),
        "lint_wiki": lint_wiki(paths.vault),
    }


def _changes_by_action(changes: list[dict[str, Any]]) -> dict[str, int]:
    return dict(sorted(Counter(str(change["action"]) for change in changes).items()))


def plan_migration(
    vault: Path | str,
    *,
    update_agents: bool = False,
) -> dict[str, Any]:
    paths = VaultPaths.from_root(vault)
    if not paths.vault.exists():
        raise ValueError(f"Vault does not exist: {paths.vault}")
    changes = [
        *_planned_directory_changes(paths),
        *_starter_file_changes(paths, update_agents=update_agents),
        *_paper_frontmatter_changes(paths),
        *_planned_generated_output_changes(paths),
        *_planned_base_changes(paths),
    ]
    if changes:
        changes.append(
            _change(
                "log_operation",
                "_operations/log.md",
                detail="migration apply would append an operation record",
            )
        )
    return {
        "vault": str(paths.vault),
        "mode": "dry-run",
        "applied": False,
        "changed": len(changes),
        "changes_by_action": _changes_by_action(changes),
        "changes": changes,
        "checks": {},
    }


def migrate_vault(
    vault: Path | str,
    *,
    apply: bool = False,
    update_agents: bool = False,
) -> dict[str, Any]:
    paths = VaultPaths.from_root(vault)
    if not paths.vault.exists():
        raise ValueError(f"Vault does not exist: {paths.vault}")
    if not apply:
        return plan_migration(paths.vault, update_agents=update_agents)

    planned_before_apply = plan_migration(paths.vault, update_agents=update_agents)
    changes: list[dict[str, Any]] = [
        change
        for change in planned_before_apply["changes"]
        if change["action"]
        not in {
            "log_operation",
            "refresh_generated_output",
            "refresh_base",
        }
    ]
    paths.ensure()
    _apply_starter_files(paths, update_agents=update_agents)
    _apply_paper_frontmatter_backfills(paths)

    generated_summary = rebuild_generated_outputs(paths.vault, apply=True)
    for row in generated_summary["files"]:
        if row["changed"]:
            change = _change(
                "refresh_generated_output",
                str(row["path"]),
                detail=f"generated output was {row['operation']}d",
            )
            changes.append(change)

    bases_summary = rebuild_bases(paths.vault)
    for row in bases_summary.get("files") or []:
        if row.get("changed"):
            change = _change(
                "refresh_base",
                str(row["path"]),
                detail="generated Obsidian Base was refreshed",
            )
            changes.append(change)
    if bases_summary.get("query_notes_refreshed"):
        changes.append(
            _change(
                "refresh_query_derived_fields",
                "queries/",
                detail=(
                    f"{bases_summary['query_notes_refreshed']} query note(s) refreshed for Bases"
                ),
            )
        )

    operation_summary = None
    if changes:
        operation_summary = log_operation(
            paths.vault,
            kind="vault_migration",
            message="Applied safe Scholar Vault migration.",
            command="scholar-vault migrate --apply",
            outputs={
                "changed": len(changes),
                "changes_by_action": _changes_by_action(changes),
            },
            files_changed=sorted(
                {
                    str(change["path"])
                    for change in changes
                    if change.get("action")
                    in {
                        "create_file",
                        "update_file",
                        "backfill_paper_frontmatter",
                        "refresh_generated_output",
                        "refresh_base",
                    }
                    and change.get("path")
                }
            ),
            checks_run=[
                "doctor",
                "compile doctor",
                "bases doctor",
                "lint-wiki",
            ],
            result="applied",
        )
        changes.append(
            _change(
                "log_operation",
                str(operation_summary["operation"]),
                detail="migration operation record was written",
            )
        )

    checks = _run_post_migration_checks(paths)
    return {
        "vault": str(paths.vault),
        "mode": "apply",
        "applied": True,
        "changed": len(changes),
        "changes_by_action": _changes_by_action(changes),
        "changes": changes,
        "generated": generated_summary,
        "bases": bases_summary,
        "operation": operation_summary,
        "checks": checks,
    }
