from __future__ import annotations

from typing import Annotated

import typer

from .cli_common import (
    JsonOutputArg,
    VaultArg,
    _print_issue_counts,
    _print_json,
    _resolve_vault,
    console,
)
from .obsidian_setup import doctor_obsidian, setup_obsidian

obsidian_app = typer.Typer(help="Safe Obsidian configuration helpers for Scholar Vaults.")

DryRunArg = Annotated[
    bool,
    typer.Option("--dry-run", help="Preview the Obsidian settings diff without writing files."),
]
GraphGroupsArg = Annotated[
    bool,
    typer.Option("--groups/--no-groups", help="Create optional saved graph color groups."),
]


def _print_obsidian_setup(summary: dict[str, object]) -> None:
    verb = "Applied" if summary.get("apply") else "Dry-run"
    console.print(
        f"{verb} Obsidian setup: changed={summary.get('changed', 0)}, "
        f"blocked={summary.get('blocked', 0)}."
    )
    if summary.get("plugins_installed") == []:
        console.print("Plugins: unchanged.")
    for row in summary.get("files") or []:
        if not isinstance(row, dict):
            continue
        console.print(f"- {row.get('path')}: {row.get('action')}")
        if row.get("backup"):
            console.print(f"  backup: {row['backup']}")
        for issue in row.get("issues") or []:
            console.print(f"  issue: {issue}")
        diff = row.get("diff")
        if diff and not summary.get("apply"):
            console.print(str(diff), soft_wrap=True)
    if not summary.get("apply") and summary.get("changed"):
        console.print("Use --apply to write these settings after reviewing the diff.")


def _print_obsidian_doctor(summary: dict[str, object]) -> None:
    console.print(f"Obsidian doctor: {'OK' if summary.get('ok') else 'ISSUES'}")
    _print_issue_counts("Obsidian Doctor Issues", summary.get("issue_counts") or {})
    warnings = summary.get("warning_counts") or {}
    if any(warnings.values()):
        _print_issue_counts("Obsidian Doctor Warnings", warnings)
    for row in summary.get("files") or []:
        if not isinstance(row, dict):
            continue
        messages = list(row.get("issues") or []) + list(row.get("warnings") or [])
        if messages:
            joined = "; ".join(str(message) for message in messages)
            console.print(f"- {row.get('path')}: {joined}")


@obsidian_app.command("setup")
def obsidian_setup_command(
    vault: VaultArg = None,
    dry_run: DryRunArg = False,
    apply: bool = typer.Option(False, "--apply", help="Write the planned Obsidian settings."),
    groups: GraphGroupsArg = True,
    json_output: JsonOutputArg = False,
) -> None:
    if dry_run and apply:
        raise typer.BadParameter("Use either --dry-run or --apply, not both.")
    summary = setup_obsidian(_resolve_vault(vault), apply=apply, include_groups=groups)
    if json_output:
        _print_json(summary)
    else:
        _print_obsidian_setup(summary)


@obsidian_app.command("doctor")
def obsidian_doctor_command(
    vault: VaultArg = None,
    json_output: JsonOutputArg = False,
) -> None:
    summary = doctor_obsidian(_resolve_vault(vault))
    if json_output:
        _print_json(summary)
    else:
        _print_obsidian_doctor(summary)
