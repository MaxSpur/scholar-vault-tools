from __future__ import annotations

from typing import Annotated

import typer
from rich.table import Table

from .cli_common import JsonOutputArg, VaultArg, _print_json, _resolve_vault, console
from .discovery import (
    discover_project,
    discover_query,
    discover_seed,
    discovery_to_labs_prompts,
    doctor_discovery,
    list_discovery_candidates,
    reject_candidate,
    select_candidate,
)
from .discovery_adapters import ProviderName

discovery_app = typer.Typer(help="Graph-assisted related-paper discovery helpers.")

CandidateIdArg = Annotated[str, typer.Argument(help="Discovery candidate id.")]
CitekeyOption = Annotated[str, typer.Option("--citekey", help="Seed paper citekey or slug.")]
QueryOption = Annotated[str, typer.Option("--query", help="Research query slug.")]
ProjectOption = Annotated[str, typer.Option("--project", help="Project slug.")]
SourceOption = Annotated[
    str,
    typer.Option(
        "--source",
        help="Comma-separated providers: openalex, semantic-scholar.",
    ),
]
LimitOption = Annotated[int, typer.Option("--limit", min=1, max=50, help="Maximum API rows.")]
RefreshOption = Annotated[
    bool,
    typer.Option("--refresh", help="Refresh cached provider responses."),
]


def _sources(value: str) -> list[ProviderName]:
    aliases = {
        "openalex": "openalex",
        "semantic-scholar": "semantic_scholar",
        "semantic_scholar": "semantic_scholar",
    }
    providers: list[ProviderName] = []
    for raw_item in (value or "").split(","):
        raw = raw_item.strip().casefold()
        if not raw:
            continue
        provider = aliases.get(raw)
        if provider is None:
            raise typer.BadParameter("Source must be openalex or semantic-scholar.")
        if provider not in providers:
            providers.append(provider)  # type: ignore[arg-type]
    if not providers:
        raise typer.BadParameter("At least one discovery source is required.")
    return providers


def _print_discovery_summary(summary: dict[str, object]) -> None:
    console.print(
        "Discovery {mode}: created={created}, updated={updated}, "
        "skipped-imported={skipped_imported}, skipped-duplicate={skipped_duplicate}".format(
            **summary
        )
    )
    errors = summary.get("errors") or []
    for error in errors:
        if isinstance(error, dict):
            console.print(f"[red]{error.get('source')}[/red]: {error.get('error')}")
    rows = summary.get("candidates") or []
    if rows:
        _print_candidate_table(rows)


def _print_candidate_table(rows: object) -> None:
    table = Table(title="Discovery Candidates", show_lines=False)
    table.add_column("ID")
    table.add_column("Status")
    table.add_column("Source")
    table.add_column("Year", justify="right")
    table.add_column("Title")
    table.add_column("Reason")
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        table.add_row(
            str(row.get("id") or ""),
            str(row.get("status") or ""),
            str(row.get("source") or ""),
            str(row.get("year") or ""),
            str(row.get("title") or ""),
            str(row.get("reason") or ""),
        )
    console.print(table)


def _print_list(summary: dict[str, object]) -> None:
    console.print(f"Discovery candidates: {summary.get('count', 0)}")
    _print_candidate_table(summary.get("candidates") or [])


def _print_status(summary: dict[str, object]) -> None:
    console.print(
        f"Candidate {summary.get('id')}: {summary.get('previous_status')} -> "
        f"{summary.get('status')} ({summary.get('candidate')})"
    )


def _print_prompt_summary(summary: dict[str, object]) -> None:
    console.print(
        f"Prompt pack {summary.get('state')}: {summary.get('prompt_pack')} "
        f"({summary.get('candidate_count')} discovery candidates)."
    )


def _print_doctor(summary: dict[str, object]) -> None:
    status = "OK" if summary.get("ok") else "ISSUES"
    counts = summary.get("counts") or {}
    console.print(f"Discovery doctor: {status}")
    console.print(
        "Candidates={discovery_candidates}, open={open_discovery_candidates}, "
        "selected={selected_discovery_candidates}".format(**counts)
    )


@discovery_app.command("seed")
def discovery_seed_command(
    citekey: CitekeyOption,
    vault: VaultArg = None,
    source: SourceOption = "openalex,semantic-scholar",
    limit: LimitOption = 20,
    refresh: RefreshOption = False,
    json_output: JsonOutputArg = False,
) -> None:
    summary = discover_seed(
        _resolve_vault(vault),
        citekey=citekey,
        sources=_sources(source),
        limit=limit,
        refresh=refresh,
    )
    if json_output:
        _print_json(summary)
    else:
        _print_discovery_summary(summary)


@discovery_app.command("query")
def discovery_query_command(
    query: QueryOption,
    vault: VaultArg = None,
    source: SourceOption = "openalex,semantic-scholar",
    limit: LimitOption = 20,
    refresh: RefreshOption = False,
    json_output: JsonOutputArg = False,
) -> None:
    summary = discover_query(
        _resolve_vault(vault),
        query_slug=query,
        sources=_sources(source),
        limit=limit,
        refresh=refresh,
    )
    if json_output:
        _print_json(summary)
    else:
        _print_discovery_summary(summary)


@discovery_app.command("project")
def discovery_project_command(
    project: ProjectOption,
    vault: VaultArg = None,
    source: SourceOption = "openalex,semantic-scholar",
    limit: LimitOption = 20,
    refresh: RefreshOption = False,
    json_output: JsonOutputArg = False,
) -> None:
    summary = discover_project(
        _resolve_vault(vault),
        project=project,
        sources=_sources(source),
        limit=limit,
        refresh=refresh,
    )
    if json_output:
        _print_json(summary)
    else:
        _print_discovery_summary(summary)


@discovery_app.command("list")
def discovery_list_command(
    vault: VaultArg = None,
    json_output: JsonOutputArg = False,
) -> None:
    summary = list_discovery_candidates(_resolve_vault(vault))
    if json_output:
        _print_json(summary)
    else:
        _print_list(summary)


@discovery_app.command("select")
def discovery_select_command(
    candidate_id: CandidateIdArg,
    vault: VaultArg = None,
    json_output: JsonOutputArg = False,
) -> None:
    summary = select_candidate(_resolve_vault(vault), candidate_id)
    if json_output:
        _print_json(summary)
    else:
        _print_status(summary)


@discovery_app.command("reject")
def discovery_reject_command(
    candidate_id: CandidateIdArg,
    vault: VaultArg = None,
    json_output: JsonOutputArg = False,
) -> None:
    summary = reject_candidate(_resolve_vault(vault), candidate_id)
    if json_output:
        _print_json(summary)
    else:
        _print_status(summary)


@discovery_app.command("to-labs-prompts")
def discovery_to_labs_prompts_command(
    query: QueryOption,
    vault: VaultArg = None,
    limit: LimitOption = 12,
    json_output: JsonOutputArg = False,
) -> None:
    summary = discovery_to_labs_prompts(
        _resolve_vault(vault),
        query_slug=query,
        limit=limit,
    )
    if json_output:
        _print_json(summary)
    else:
        _print_prompt_summary(summary)


@discovery_app.command("doctor")
def discovery_doctor_command(
    vault: VaultArg = None,
    json_output: JsonOutputArg = False,
) -> None:
    summary = doctor_discovery(_resolve_vault(vault))
    if json_output:
        _print_json(summary)
    else:
        _print_doctor(summary)


__all__ = [
    "discovery_app",
    "discovery_doctor_command",
    "discovery_list_command",
    "discovery_project_command",
    "discovery_query_command",
    "discovery_reject_command",
    "discovery_seed_command",
    "discovery_select_command",
    "discovery_to_labs_prompts_command",
]
