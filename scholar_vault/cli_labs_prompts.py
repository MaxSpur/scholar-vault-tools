from __future__ import annotations

from typing import Annotated

import typer
from rich.table import Table

from .cli_common import (
    JsonOutputArg,
    VaultArg,
    _print_issue_counts,
    _print_json,
    _resolve_vault,
    console,
)
from .labs_prompts import (
    PROMPT_TYPES,
    doctor_prompt_packs,
    generate_prompt_pack,
    link_prompt_pack_run,
    list_prompt_packs,
    mark_prompt_pack_used,
    retire_prompt_pack,
    show_prompt_pack,
)

labs_prompts_app = typer.Typer(help="Scholar Labs prompt-pack workbench helpers.")

PromptPackIdArg = Annotated[str, typer.Argument(help="Prompt-pack id or vault-relative path.")]
RunIdArg = Annotated[str, typer.Argument(help="Scholar Labs run id.")]
QueryOption = Annotated[str | None, typer.Option("--query", help="Research query slug.")]
ProjectOption = Annotated[str | None, typer.Option("--project", help="Project slug.")]
FromGapsOption = Annotated[
    bool,
    typer.Option("--from-gaps", help="Generate from open gap, maintenance, and proposal tasks."),
]
SeedApiOption = Annotated[
    str,
    typer.Option(
        "--seed-api",
        help="Optional seed provider for prompt wording only: none, openalex, semantic-scholar.",
    ),
]
RefreshSeedsOption = Annotated[
    bool,
    typer.Option("--refresh-seeds", help="Refresh cached optional API seed results."),
]
NotesOption = Annotated[str, typer.Option("--notes", help="Usage notes to append.")]


def _seed_api(value: str) -> str:
    normalized = (value or "none").strip().casefold()
    allowed = {"none", "openalex", "semantic-scholar"}
    if normalized not in allowed:
        raise typer.BadParameter("Seed API must be one of: none, openalex, semantic-scholar.")
    return normalized


def _print_prompt_pack_list(summary: dict[str, object]) -> None:
    rows = summary.get("prompt_packs") or []
    console.print(f"Scholar Labs prompt packs: {summary.get('count', 0)}")
    if not rows:
        return
    table = Table(title="Scholar Labs Prompt Packs", show_lines=False)
    table.add_column("ID")
    table.add_column("Status")
    table.add_column("Query")
    table.add_column("Project")
    table.add_column("Runs", justify="right")
    table.add_column("Path")
    for row in rows:
        table.add_row(
            str(row.get("id") or ""),
            str(row.get("status") or ""),
            str(row.get("query") or "-"),
            str(row.get("project") or "-"),
            str(row.get("linked_runs") or 0),
            str(row.get("path") or ""),
        )
    console.print(table)


def _print_generate(summary: dict[str, object]) -> None:
    console.print(
        f"Prompt pack {summary.get('state')}: {summary.get('prompt_pack')} "
        f"({summary.get('prompt_count')} prompts, status={summary.get('status')})."
    )
    if summary.get("seed_provider") != "none":
        console.print(
            f"Seed provider: {summary.get('seed_provider')} "
            f"({len(summary.get('seed_candidates') or [])} candidates)."
        )


def _print_show(summary: dict[str, object]) -> None:
    frontmatter = summary.get("frontmatter") or {}
    console.print(f"Prompt pack: {summary.get('prompt_pack')}")
    console.print(f"Status: {frontmatter.get('status')}")
    console.print(f"Query: {frontmatter.get('query') or '-'}")
    console.print(f"Project: {frontmatter.get('project') or '-'}")
    console.print("")
    console.print(summary.get("body") or "")


def _print_status_change(summary: dict[str, object]) -> None:
    console.print(
        f"Prompt pack {summary.get('id')}: {summary.get('previous_status', 'updated')} "
        f"-> {summary.get('status')} ({summary.get('prompt_pack')})."
    )


def _print_link(summary: dict[str, object]) -> None:
    state = "linked" if summary.get("changed") else "already linked"
    console.print(
        f"Prompt pack {state}: {summary.get('prompt_pack')} -> run {summary.get('run')} "
        f"(status={summary.get('status')})."
    )


def _print_doctor(summary: dict[str, object]) -> None:
    status = "OK" if summary.get("ok") else "ISSUES"
    console.print(f"Scholar Labs prompt-pack doctor: {status}")
    _print_issue_counts("Prompt Pack Issues", summary.get("issue_counts") or {})


@labs_prompts_app.command("generate")
def labs_prompts_generate_command(
    vault: VaultArg = None,
    query: QueryOption = None,
    project: ProjectOption = None,
    from_gaps: FromGapsOption = False,
    seed_api: SeedApiOption = "none",
    refresh_seeds: RefreshSeedsOption = False,
    json_output: JsonOutputArg = False,
) -> None:
    summary = generate_prompt_pack(
        _resolve_vault(vault),
        query=query,
        project=project,
        from_gaps=from_gaps,
        seed_api=_seed_api(seed_api),
        refresh_seeds=refresh_seeds,
    )
    if json_output:
        _print_json(summary)
    else:
        _print_generate(summary)


@labs_prompts_app.command("list")
def labs_prompts_list_command(
    vault: VaultArg = None,
    json_output: JsonOutputArg = False,
) -> None:
    summary = list_prompt_packs(_resolve_vault(vault))
    if json_output:
        _print_json(summary)
    else:
        _print_prompt_pack_list(summary)


@labs_prompts_app.command("show")
def labs_prompts_show_command(
    prompt_pack_id: PromptPackIdArg,
    vault: VaultArg = None,
    json_output: JsonOutputArg = False,
) -> None:
    summary = show_prompt_pack(_resolve_vault(vault), prompt_pack_id)
    if json_output:
        _print_json(summary)
    else:
        _print_show(summary)


@labs_prompts_app.command("mark-used")
def labs_prompts_mark_used_command(
    prompt_pack_id: PromptPackIdArg,
    notes: NotesOption = "",
    vault: VaultArg = None,
    json_output: JsonOutputArg = False,
) -> None:
    summary = mark_prompt_pack_used(_resolve_vault(vault), prompt_pack_id, notes=notes)
    if json_output:
        _print_json(summary)
    else:
        _print_status_change(summary)


@labs_prompts_app.command("link-run")
def labs_prompts_link_run_command(
    prompt_pack_id: PromptPackIdArg,
    run_id: RunIdArg,
    vault: VaultArg = None,
    json_output: JsonOutputArg = False,
) -> None:
    summary = link_prompt_pack_run(_resolve_vault(vault), prompt_pack_id, run_id)
    if json_output:
        _print_json(summary)
    else:
        _print_link(summary)


@labs_prompts_app.command("retire")
def labs_prompts_retire_command(
    prompt_pack_id: PromptPackIdArg,
    vault: VaultArg = None,
    json_output: JsonOutputArg = False,
) -> None:
    summary = retire_prompt_pack(_resolve_vault(vault), prompt_pack_id)
    if json_output:
        _print_json(summary)
    else:
        _print_status_change(summary)


@labs_prompts_app.command("doctor")
def labs_prompts_doctor_command(
    vault: VaultArg = None,
    json_output: JsonOutputArg = False,
) -> None:
    summary = doctor_prompt_packs(_resolve_vault(vault))
    if json_output:
        _print_json(summary)
    else:
        _print_doctor(summary)


__all__ = [
    "PROMPT_TYPES",
    "labs_prompts_app",
    "labs_prompts_doctor_command",
    "labs_prompts_generate_command",
    "labs_prompts_link_run_command",
    "labs_prompts_list_command",
    "labs_prompts_mark_used_command",
    "labs_prompts_retire_command",
    "labs_prompts_show_command",
]
