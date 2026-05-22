from __future__ import annotations

from typing import Annotated

import typer
from rich.table import Table

from .cli_common import JsonOutputArg, VaultArg, _print_json, _resolve_vault, console
from .migration import migrate_vault


def _print_migration_summary(summary: dict[str, object]) -> None:
    mode = str(summary.get("mode") or "dry-run")
    changed = int(summary.get("changed") or 0)
    if mode == "apply":
        console.print(f"Migration applied: {changed} change(s).")
    else:
        console.print(f"Migration dry-run: {changed} proposed change(s).")
    counts = summary.get("changes_by_action") or {}
    if counts:
        table = Table(title="Migration Changes", show_lines=False)
        table.add_column("Action")
        table.add_column("Count", justify="right")
        for action, count in counts.items():
            table.add_row(str(action).replace("_", " "), str(count))
        console.print(table)
    changes = summary.get("changes") or []
    if changes:
        table = Table(title="Change Details", show_lines=False)
        table.add_column("Action")
        table.add_column("Path")
        table.add_column("Detail")
        for row in changes:
            if not isinstance(row, dict):
                continue
            detail = str(row.get("detail") or "")
            fields = row.get("fields") or []
            if fields:
                detail = f"{detail}: {', '.join(str(field) for field in fields)}"
            table.add_row(
                str(row.get("action") or "").replace("_", " "),
                str(row.get("path") or ""),
                detail,
            )
        console.print(table)
    checks = summary.get("checks") or {}
    if checks:
        doctor = checks.get("doctor") if isinstance(checks, dict) else {}
        compile_doctor = checks.get("compile_doctor") if isinstance(checks, dict) else {}
        bases_doctor = checks.get("bases_doctor") if isinstance(checks, dict) else {}
        lint = checks.get("lint_wiki") if isinstance(checks, dict) else {}
        console.print(
            "Checks: "
            f"doctor cards={((doctor or {}).get('counts') or {}).get('paper_cards', 0)}, "
            f"compile={'OK' if (compile_doctor or {}).get('ok') else 'ISSUES'}, "
            f"bases={'OK' if (bases_doctor or {}).get('ok') else 'ISSUES'}, "
            f"lint findings={len((lint or {}).get('findings') or [])}."
        )


def migrate_command(
    vault: VaultArg = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Report planned migration changes without writing."),
    ] = False,
    apply_changes: Annotated[
        bool,
        typer.Option("--apply", help="Apply the safe migration."),
    ] = False,
    update_agents: Annotated[
        bool,
        typer.Option(
            "--update-agents",
            help="Explicitly update an existing vault AGENTS.md from the current template.",
        ),
    ] = False,
    json_output: JsonOutputArg = False,
) -> None:
    if dry_run and apply_changes:
        raise typer.BadParameter("Choose only one of --dry-run or --apply.")
    summary = migrate_vault(
        _resolve_vault(vault),
        apply=apply_changes,
        update_agents=update_agents,
    )
    if json_output:
        _print_json(summary)
    else:
        _print_migration_summary(summary)
