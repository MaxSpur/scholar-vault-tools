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
from .queries import (
    query_create,
    query_link_paper,
    query_link_run,
    query_link_synthesis,
    query_list,
    query_show,
    query_status,
)

query_app = typer.Typer(help="Research query workspace helpers.")

QuerySlugArg = Annotated[str, typer.Argument(help="Research query slug.")]
QuestionArg = Annotated[str, typer.Argument(help="Research question text.")]
RunIdArg = Annotated[
    str,
    typer.Argument(autocompletion=_complete_run_ids, help="Scholar Labs run id."),
]
CitekeyArg = Annotated[
    str,
    typer.Argument(
        autocompletion=_complete_citekeys,
        help="Paper citekey, card slug, or papers/<slug>.md path.",
    ),
]
SynthesisArg = Annotated[str, typer.Argument(help="Synthesis slug or syntheses/<slug>.md path.")]
ProjectOption = Annotated[str | None, typer.Option("--project", help="Project slug.")]
SlugOption = Annotated[str | None, typer.Option("--slug", help="Query note slug.")]
PriorityOption = Annotated[str, typer.Option("--priority", help="Query priority label.")]


def _print_query_list(summary: dict[str, object]) -> None:
    rows = summary.get("queries") or []
    console.print(f"Research queries: {summary.get('count', 0)}")
    if not rows:
        return
    table = Table(title="Research Queries", show_lines=False)
    table.add_column("Slug")
    table.add_column("Status")
    table.add_column("Project")
    table.add_column("Papers", justify="right")
    table.add_column("Question")
    for row in rows:
        table.add_row(
            str(row.get("slug") or ""),
            str(row.get("status") or ""),
            str(row.get("project") or ""),
            str(row.get("linked_papers") or 0),
            str(row.get("question") or ""),
        )
    console.print(table)


def _print_query_create(summary: dict[str, object]) -> None:
    bases = summary.get("bases") or {}
    console.print(
        f"Query {summary.get('state')}: {summary.get('query')} "
        f"(bases changed={bases.get('changed', 0)})."
    )


def _print_query_link(summary: dict[str, object]) -> None:
    state = "linked" if summary.get("changed") else "already linked"
    console.print(
        f"Query {state}: {summary.get('ref')} -> {summary.get('query')} "
        f"({summary.get('field')})"
    )


def _print_query_show(summary: dict[str, object]) -> None:
    frontmatter = summary.get("frontmatter") or {}
    console.print(f"Query: {summary.get('query')}")
    console.print(f"Status: {frontmatter.get('status')}")
    console.print(f"Project: {frontmatter.get('project') or '-'}")
    console.print(f"Question: {frontmatter.get('question')}")
    console.print(
        "Linked: "
        f"papers={len(frontmatter.get('linked_papers') or [])}, "
        f"runs={len(frontmatter.get('linked_runs') or [])}, "
        f"syntheses={len(frontmatter.get('linked_syntheses') or [])}"
    )


def _print_query_status(summary: dict[str, object]) -> None:
    status = "OK" if summary.get("ok") else "ISSUES"
    console.print(f"Query status: {summary.get('query')} [{status}]")
    counts = summary.get("counts") or {}
    console.print(
        "Linked papers={linked_papers}, runs={linked_runs}, syntheses={linked_syntheses}, "
        "unread papers={unread_linked_papers}.".format(**counts)
    )
    _print_issue_counts("Query Status Issues", summary.get("issue_counts") or {})


@query_app.command("create")
def query_create_command(
    question: QuestionArg,
    vault: VaultArg = None,
    project: ProjectOption = None,
    slug: SlugOption = None,
    priority: PriorityOption = "normal",
    json_output: JsonOutputArg = False,
) -> None:
    summary = query_create(
        _resolve_vault(vault),
        question,
        project=project,
        slug=slug,
        priority=priority,
    )
    if json_output:
        _print_json(summary)
    else:
        _print_query_create(summary)


@query_app.command("list")
def query_list_command(
    vault: VaultArg = None,
    json_output: JsonOutputArg = False,
) -> None:
    summary = query_list(_resolve_vault(vault))
    if json_output:
        _print_json(summary)
    else:
        _print_query_list(summary)


@query_app.command("show")
def query_show_command(
    slug: QuerySlugArg,
    vault: VaultArg = None,
    json_output: JsonOutputArg = False,
) -> None:
    summary = query_show(_resolve_vault(vault), slug)
    if json_output:
        _print_json(summary)
    else:
        _print_query_show(summary)


@query_app.command("link-run")
def query_link_run_command(
    slug: QuerySlugArg,
    run_id: RunIdArg,
    vault: VaultArg = None,
    json_output: JsonOutputArg = False,
) -> None:
    summary = query_link_run(_resolve_vault(vault), slug, run_id)
    if json_output:
        _print_json(summary)
    else:
        _print_query_link(summary)


@query_app.command("link-paper")
def query_link_paper_command(
    slug: QuerySlugArg,
    citekey: CitekeyArg,
    vault: VaultArg = None,
    json_output: JsonOutputArg = False,
) -> None:
    summary = query_link_paper(_resolve_vault(vault), slug, citekey)
    if json_output:
        _print_json(summary)
    else:
        _print_query_link(summary)


@query_app.command("link-synthesis")
def query_link_synthesis_command(
    slug: QuerySlugArg,
    path_or_slug: SynthesisArg,
    vault: VaultArg = None,
    json_output: JsonOutputArg = False,
) -> None:
    summary = query_link_synthesis(_resolve_vault(vault), slug, path_or_slug)
    if json_output:
        _print_json(summary)
    else:
        _print_query_link(summary)


@query_app.command("status")
def query_status_command(
    slug: QuerySlugArg,
    vault: VaultArg = None,
    json_output: JsonOutputArg = False,
) -> None:
    summary = query_status(_resolve_vault(vault), slug)
    if json_output:
        _print_json(summary)
    else:
        _print_query_status(summary)
