from __future__ import annotations

from typing import Annotated

import typer
from rich.table import Table

from .cli_common import JsonOutputArg, VaultArg, _print_json, _resolve_vault, console
from .evals import EVAL_KINDS, load_eval_definitions, render_eval_report, run_evals
from .semantic_lint import lint_wiki

eval_app = typer.Typer(help="Deterministic vault eval workflows.")


def _print_findings_summary(label: str, summary: dict[str, object]) -> None:
    counts = (summary.get("counts") or {}).get("by_severity", {})  # type: ignore[union-attr]
    console.print(
        f"{label}: {summary.get('count', 0)} finding(s) "
        f"(info={counts.get('info', 0)}, warning={counts.get('warning', 0)}, "
        f"error={counts.get('error', 0)})."
    )
    findings = summary.get("findings") or []
    if not findings:
        return
    table = Table(title=label, show_lines=False)
    table.add_column("Severity")
    table.add_column("Action")
    table.add_column("Check")
    table.add_column("Finding")
    for finding in findings[:25]:
        table.add_row(
            str(finding.get("severity") or ""),
            str(finding.get("action") or ""),
            str(finding.get("check") or ""),
            str(finding.get("title") or ""),
        )
    console.print(table)
    if len(findings) > 25:
        console.print(f"... {len(findings) - 25} more finding(s).")


@eval_app.command("list")
def eval_list_command(
    vault: VaultArg = None,
    json_output: JsonOutputArg = False,
) -> None:
    summary = load_eval_definitions(_resolve_vault(vault))
    if json_output:
        _print_json(summary)
        return
    console.print(f"Eval definitions: {summary.get('count', 0)}")
    table = Table(show_lines=False)
    table.add_column("ID")
    table.add_column("Kind")
    table.add_column("Path")
    for row in summary.get("definitions") or []:
        table.add_row(str(row.get("id")), str(row.get("kind")), str(row.get("path")))
    console.print(table)


@eval_app.command("run")
def eval_run_command(
    vault: VaultArg = None,
    kind: Annotated[
        str | None,
        typer.Option("--kind", help="Only run one eval kind."),
    ] = None,
    write_queue: Annotated[
        bool,
        typer.Option("--write-queue", help="Create duplicate-resistant queue items for failures."),
    ] = False,
    json_output: JsonOutputArg = False,
) -> None:
    if kind and kind not in EVAL_KINDS:
        raise typer.BadParameter(f"--kind must be one of: {', '.join(sorted(EVAL_KINDS))}")
    summary = run_evals(_resolve_vault(vault), kind=kind, write_queue=write_queue)
    if json_output:
        _print_json(summary)
    else:
        _print_findings_summary("Eval run", summary)


@eval_app.command("report")
def eval_report_command(
    vault: VaultArg = None,
    json_output: JsonOutputArg = False,
) -> None:
    summary = render_eval_report(_resolve_vault(vault))
    if json_output:
        _print_json(summary)
    else:
        latest = summary.get("latest") or {}
        counts = latest.get("counts") or {}
        console.print(
            f"Eval report: {summary['report']['path']} "
            f"(runs={summary.get('run_count', 0)}, findings={counts.get('findings', 0)})."
        )


def lint_wiki_command(
    vault: VaultArg = None,
    write_queue: Annotated[
        bool,
        typer.Option("--write-queue", help="Create duplicate-resistant queue items."),
    ] = False,
    write_report: Annotated[
        bool,
        typer.Option("--write-report", help="Write _indexes/lint-wiki-report.md."),
    ] = False,
    json_output: JsonOutputArg = False,
) -> None:
    summary = lint_wiki(
        _resolve_vault(vault),
        write_queue=write_queue,
        write_report=write_report,
    )
    if json_output:
        _print_json(summary)
    else:
        _print_findings_summary("Wiki lint", summary)
        if summary.get("report"):
            console.print(f"Report: {summary['report']['path']}")
