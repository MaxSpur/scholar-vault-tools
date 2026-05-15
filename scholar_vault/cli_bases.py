from __future__ import annotations

import typer
from rich.table import Table

from .bases import doctor_bases, init_bases, rebuild_bases
from .cli_common import (
    JsonOutputArg,
    VaultArg,
    _print_issue_counts,
    _print_json,
    _resolve_vault,
    console,
)

bases_app = typer.Typer(help="Generated Obsidian Bases workbench helpers.")


def _print_bases_summary(summary: dict[str, object], *, action: str) -> None:
    console.print(
        f"Bases {action}: wrote={summary.get('written', 0)}, "
        f"changed={summary.get('changed', 0)}, "
        f"query notes refreshed={summary.get('query_notes_refreshed', 0)}."
    )
    files = summary.get("files") or []
    if not files:
        return
    table = Table(title="Obsidian Bases", show_lines=False)
    table.add_column("Path")
    table.add_column("Changed")
    table.add_column("Views", justify="right")
    for row in files:
        table.add_row(
            str(row.get("path") or ""),
            "yes" if row.get("changed") else "no",
            str(len(row.get("views") or [])),
        )
    console.print(table)


def _print_bases_doctor(summary: dict[str, object]) -> None:
    console.print(f"Bases doctor: {'OK' if summary.get('ok') else 'ISSUES'}")
    _print_issue_counts("Bases Doctor Issues", summary.get("issue_counts") or {})
    for row in summary.get("bases") or []:
        if not row.get("issues"):
            continue
        console.print(f"- {row.get('path')}: {'; '.join(row.get('issues') or [])}")


@bases_app.command("init")
def bases_init_command(
    vault: VaultArg = None,
    json_output: JsonOutputArg = False,
) -> None:
    summary = init_bases(_resolve_vault(vault))
    if json_output:
        _print_json(summary)
    else:
        _print_bases_summary(summary, action="initialized")


@bases_app.command("rebuild")
def bases_rebuild_command(
    vault: VaultArg = None,
    json_output: JsonOutputArg = False,
) -> None:
    summary = rebuild_bases(_resolve_vault(vault))
    if json_output:
        _print_json(summary)
    else:
        _print_bases_summary(summary, action="rebuilt")


@bases_app.command("doctor")
def bases_doctor_command(
    vault: VaultArg = None,
    json_output: JsonOutputArg = False,
) -> None:
    summary = doctor_bases(_resolve_vault(vault))
    if json_output:
        _print_json(summary)
    else:
        _print_bases_doctor(summary)
