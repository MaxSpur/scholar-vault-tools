from __future__ import annotations

from typing import Annotated

import typer
from rich.table import Table

from .cli_common import (
    JsonOutputArg,
    VaultArg,
    _complete_citekeys,
    _complete_run_ids,
    _print_issue_counts,
    _print_json,
    _resolve_vault,
    console,
)
from .digests import (
    MARKABLE_DIGEST_STATUSES,
    compile_doctor,
    compile_mark,
    compile_queue,
    compile_scaffold,
    compile_status,
)

compile_app = typer.Typer(help="Paper digest compile workflow helpers.")

CitekeyOption = Annotated[
    str | None,
    typer.Option(
        "--citekey",
        autocompletion=_complete_citekeys,
        help="Paper citekey, card slug, or papers/<slug>.md path.",
    ),
]
RunOption = Annotated[
    str | None,
    typer.Option("--run", autocompletion=_complete_run_ids, help="Scholar Labs run id."),
]
SelectedOnlyOption = Annotated[
    bool,
    typer.Option(
        "--selected-only",
        help="When scaffolding a run, use selected results with canonical paper cards only.",
    ),
]
ScaffoldForceOption = Annotated[
    bool,
    typer.Option("--force", help="Overwrite an existing digest scaffold."),
]
MarkForceOption = Annotated[
    bool,
    typer.Option("--force", help="Allow compiled/reviewed marks despite readiness issues."),
]
ProjectOption = Annotated[str, typer.Option("--project", help="Project workspace slug.")]
CitekeyArg = Annotated[
    str,
    typer.Argument(
        autocompletion=_complete_citekeys,
        help="Paper citekey, card slug, or papers/<slug>.md path.",
    ),
]
CompileStatusOption = Annotated[
    str,
    typer.Option("--status", help="Compile status: draft, compiled, stale, or reviewed."),
]


def _print_status(summary: dict[str, object]) -> None:
    console.print(f"Paper digest status: {summary.get('needs_action', 0)} need action.")
    _print_issue_counts("Compile Status Counts", summary.get("counts") or {})
    rows = [
        row
        for row in summary.get("papers") or []
        if row.get("needs_action")
    ]
    if not rows:
        return
    table = Table(title="Compile Queue", show_lines=False)
    table.add_column("Citekey")
    table.add_column("Status")
    table.add_column("Reading")
    table.add_column("Digest")
    table.add_column("Issues")
    for row in rows[:50]:
        table.add_row(
            str(row.get("citekey") or ""),
            str(row.get("effective_status") or ""),
            str(row.get("reading_status") or ""),
            str(row.get("paper_digest") or ""),
            "; ".join(str(issue) for issue in row.get("issues") or []),
        )
    console.print(table)


def _print_scaffold(summary: dict[str, object]) -> None:
    console.print(
        f"Digest scaffolds: {summary.get('changed', 0)} changed, "
        f"{summary.get('count', 0)} considered."
    )
    skipped = summary.get("skipped") or []
    if skipped:
        console.print(f"Skipped {len(skipped)} run result(s) without scaffoldable paper cards.")


def _print_queue(summary: dict[str, object]) -> None:
    console.print(
        f"Compile queue for {summary.get('project')}: "
        f"{summary.get('queue_count', 0)} of {summary.get('count', 0)} paper(s)."
    )
    rows = summary.get("queue") or []
    if not rows:
        return
    table = Table(title="Project Compile Queue", show_lines=False)
    table.add_column("Citekey")
    table.add_column("Status")
    table.add_column("Digest")
    table.add_column("Title")
    for row in rows:
        table.add_row(
            str(row.get("citekey") or ""),
            str(row.get("effective_status") or ""),
            str(row.get("paper_digest") or ""),
            str(row.get("title") or ""),
        )
    console.print(table)


def _print_mark(summary: dict[str, object]) -> None:
    state = "updated" if summary.get("changed") else "unchanged"
    console.print(
        f"Digest {state}: {summary.get('citekey')} -> {summary.get('status')} "
        f"({summary.get('digest')})"
    )


def _print_doctor(summary: dict[str, object]) -> None:
    status = "OK" if summary.get("ok") else "ISSUES"
    console.print(f"Compile doctor: {status}")
    _print_issue_counts("Compile Doctor Issues", summary.get("issue_counts") or {})


@compile_app.command("status")
def compile_status_command(
    vault: VaultArg = None,
    json_output: JsonOutputArg = False,
) -> None:
    summary = compile_status(_resolve_vault(vault))
    if json_output:
        _print_json(summary)
    else:
        _print_status(summary)


@compile_app.command("scaffold")
def compile_scaffold_command(
    vault: VaultArg = None,
    citekey: CitekeyOption = None,
    run_id: RunOption = None,
    selected_only: SelectedOnlyOption = False,
    force: ScaffoldForceOption = False,
    json_output: JsonOutputArg = False,
) -> None:
    summary = compile_scaffold(
        _resolve_vault(vault),
        citekey=citekey,
        run_id=run_id,
        selected_only=selected_only,
        force=force,
    )
    if json_output:
        _print_json(summary)
    else:
        _print_scaffold(summary)


@compile_app.command("queue")
def compile_queue_command(
    project: ProjectOption,
    vault: VaultArg = None,
    json_output: JsonOutputArg = False,
) -> None:
    summary = compile_queue(_resolve_vault(vault), project=project)
    if json_output:
        _print_json(summary)
    else:
        _print_queue(summary)


@compile_app.command("mark")
def compile_mark_command(
    citekey: CitekeyArg,
    status: CompileStatusOption,
    vault: VaultArg = None,
    force: MarkForceOption = False,
    json_output: JsonOutputArg = False,
) -> None:
    if status not in MARKABLE_DIGEST_STATUSES:
        raise typer.BadParameter(
            f"--status must be one of: {', '.join(MARKABLE_DIGEST_STATUSES)}"
        )
    summary = compile_mark(_resolve_vault(vault), citekey, status=status, force=force)
    if json_output:
        _print_json(summary)
    else:
        _print_mark(summary)


@compile_app.command("doctor")
def compile_doctor_command(
    vault: VaultArg = None,
    json_output: JsonOutputArg = False,
) -> None:
    summary = compile_doctor(_resolve_vault(vault))
    if json_output:
        _print_json(summary)
    else:
        _print_doctor(summary)
