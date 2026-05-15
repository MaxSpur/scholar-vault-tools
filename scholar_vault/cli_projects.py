from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.table import Table

from .cli_common import (
    JsonOutputArg,
    ProjectCitekeyArg,
    ProjectConceptSlugArg,
    ProjectProposalPathArg,
    ProjectRunIdArg,
    ProjectSlugArg,
    ProjectSynthesisSlugArg,
    ProjectTaskPathArg,
    ProjectTitleArg,
    UiArg,
    VaultArg,
    _call_root_gui,
    _complete_citekeys,
    _print_issue_counts,
    _print_json,
    _resolve_vault,
    console,
)
from .projects import (
    project_audit,
    project_link_concept,
    project_link_paper,
    project_link_proposal,
    project_link_run,
    project_link_synthesis,
    project_link_task,
    project_list,
    project_map,
    project_scaffold,
)

project_app = typer.Typer(help="Project workspace helpers.")


def _print_project_list(summary: dict[str, object]) -> None:
    rows = summary.get("projects") or []
    console.print(f"Projects: {summary.get('count', 0)}")
    if not rows:
        return
    table = Table(title="Project Workspaces", show_lines=False)
    table.add_column("Slug")
    table.add_column("Title")
    table.add_column("Status")
    table.add_column("Papers", justify="right")
    table.add_column("Path")
    for row in rows:
        table.add_row(
            str(row.get("slug") or ""),
            str(row.get("title") or ""),
            str(row.get("status") or ""),
            str(row.get("related_papers") or 0),
            str(row.get("path") or ""),
        )
    console.print(table)


def _print_project_scaffold(summary: dict[str, object]) -> None:
    console.print(f"Project scaffold: {summary.get('project')} [{summary.get('state')}]")
    refresh = summary.get("refresh") or summary.get("rebuild") or {}
    if refresh:
        console.print(
            "- Refreshed project navigation: "
            f"{refresh.get('index_files_written')} index, "
            f"{refresh.get('llm_files_written')} LLM files."
        )


def _print_project_link(summary: dict[str, object]) -> None:
    state = "linked" if summary.get("changed") else "already linked"
    console.print(
        f"Project {state}: {summary.get('ref')} -> {summary.get('project')} "
        f"({summary.get('field')})"
    )


def _print_project_map(summary: dict[str, object]) -> None:
    console.print(f"Wrote project map: {summary.get('project_map')}")
    console.print(
        f"Linked papers={summary.get('linked_papers', 0)}, "
        f"gaps={summary.get('gaps', 0)}, "
        f"recommended actions={summary.get('recommended_next_actions', 0)}."
    )


def _print_project_audit(summary: dict[str, object]) -> None:
    status = "OK" if summary.get("ok") else "ISSUES"
    console.print(f"Project audit: {summary.get('project')} [{status}]")
    counts = summary.get("counts") or {}
    console.print(
        "Papers={linked_papers}, concepts={linked_concepts}, syntheses={linked_syntheses}, "
        "tasks={linked_tasks}, runs={linked_runs}.".format(**counts)
    )
    _print_issue_counts("Project Audit Issues", summary.get("issue_counts") or {})
    issues = summary.get("issues") or {}
    for key, rows in issues.items():
        if not rows:
            continue
        table = Table(title=key.replace("_", " ").title(), show_lines=False)
        table.add_column("Target")
        table.add_column("Message")
        for row in rows[:50]:
            table.add_row(
                str(row.get("paper") or row.get("target") or row.get("run") or "-"),
                str(row.get("message") or ""),
            )
        console.print(table)


def _show_project_workspace_ui(
    vault: Path,
    *,
    initial_slug: str | None = None,
    initial_title: str | None = None,
    initial_citekey: str | None = None,
) -> bool:
    cli_module = sys.modules.get("scholar_vault.cli")
    root_helper = getattr(cli_module, "_show_project_workspace_ui", None)
    if root_helper is not None and root_helper is not _show_project_workspace_ui:
        return bool(
            root_helper(
                vault,
                initial_slug=initial_slug,
                initial_title=initial_title,
                initial_citekey=initial_citekey,
            )
        )
    try:
        from .gui import GuiUnavailable, show_project_workspace
    except Exception as exc:  # pragma: no cover - defensive optional import path
        console.print(f"Project UI unavailable ({exc}). Falling back to terminal output.")
        return False
    try:
        _call_root_gui(
            lambda: show_project_workspace(
                vault,
                initial_slug=initial_slug,
                initial_title=initial_title,
                initial_citekey=initial_citekey,
            )
        )
        return True
    except GuiUnavailable as exc:
        console.print(f"Project UI unavailable ({exc}). Falling back to terminal output.")
        return False


@project_app.command("scaffold")
def project_scaffold_command(
    slug: ProjectSlugArg,
    vault: VaultArg = None,
    title: ProjectTitleArg = None,
    json_output: JsonOutputArg = False,
    ui: UiArg = False,
) -> None:
    resolved_vault = _resolve_vault(vault)
    if ui and _show_project_workspace_ui(
        resolved_vault,
        initial_slug=slug,
        initial_title=title,
    ):
        return
    summary = project_scaffold(resolved_vault, slug, title=title)
    if json_output:
        _print_json(summary)
    else:
        _print_project_scaffold(summary)


@project_app.command("list")
def project_list_command(
    vault: VaultArg = None,
    json_output: JsonOutputArg = False,
) -> None:
    summary = project_list(_resolve_vault(vault))
    if json_output:
        _print_json(summary)
    else:
        _print_project_list(summary)


@project_app.command("map")
def project_map_command(
    slug: ProjectSlugArg,
    vault: VaultArg = None,
    json_output: JsonOutputArg = False,
) -> None:
    summary = project_map(_resolve_vault(vault), slug)
    if json_output:
        _print_json(summary)
    else:
        _print_project_map(summary)


@project_app.command("link-paper")
def project_link_paper_command(
    slug: ProjectSlugArg,
    citekey: ProjectCitekeyArg,
    vault: VaultArg = None,
    json_output: JsonOutputArg = False,
    ui: UiArg = False,
) -> None:
    resolved_vault = _resolve_vault(vault)
    if ui and _show_project_workspace_ui(
        resolved_vault,
        initial_slug=slug,
        initial_citekey=citekey,
    ):
        return
    summary = project_link_paper(resolved_vault, slug, citekey)
    if json_output:
        _print_json(summary)
    else:
        _print_project_link(summary)


@project_app.command("link-concept")
def project_link_concept_command(
    slug: ProjectSlugArg,
    concept_slug: ProjectConceptSlugArg,
    vault: VaultArg = None,
    json_output: JsonOutputArg = False,
) -> None:
    summary = project_link_concept(_resolve_vault(vault), slug, concept_slug)
    if json_output:
        _print_json(summary)
    else:
        _print_project_link(summary)


@project_app.command("link-synthesis")
def project_link_synthesis_command(
    slug: ProjectSlugArg,
    synthesis_slug: ProjectSynthesisSlugArg,
    vault: VaultArg = None,
    json_output: JsonOutputArg = False,
) -> None:
    summary = project_link_synthesis(_resolve_vault(vault), slug, synthesis_slug)
    if json_output:
        _print_json(summary)
    else:
        _print_project_link(summary)


@project_app.command("link-run")
def project_link_run_command(
    slug: ProjectSlugArg,
    run_id: ProjectRunIdArg,
    vault: VaultArg = None,
    json_output: JsonOutputArg = False,
) -> None:
    summary = project_link_run(_resolve_vault(vault), slug, run_id)
    if json_output:
        _print_json(summary)
    else:
        _print_project_link(summary)


@project_app.command("link-task")
def project_link_task_command(
    slug: ProjectSlugArg,
    task_path: ProjectTaskPathArg,
    vault: VaultArg = None,
    json_output: JsonOutputArg = False,
) -> None:
    summary = project_link_task(_resolve_vault(vault), slug, task_path)
    if json_output:
        _print_json(summary)
    else:
        _print_project_link(summary)


@project_app.command("link-proposal")
def project_link_proposal_command(
    slug: ProjectSlugArg,
    proposal_path: ProjectProposalPathArg,
    vault: VaultArg = None,
    json_output: JsonOutputArg = False,
) -> None:
    summary = project_link_proposal(_resolve_vault(vault), slug, proposal_path)
    if json_output:
        _print_json(summary)
    else:
        _print_project_link(summary)


@project_app.command("audit")
def project_audit_command(
    slug: ProjectSlugArg,
    vault: VaultArg = None,
    json_output: JsonOutputArg = False,
) -> None:
    summary = project_audit(_resolve_vault(vault), slug)
    if json_output:
        _print_json(summary)
    else:
        _print_project_audit(summary)


@project_app.command("ui")
def project_ui_command(
    vault: VaultArg = None,
    slug: Annotated[
        str | None,
        typer.Option(
            "--slug",
            "--project",
            help="Project slug to preselect or scaffold.",
        ),
    ] = None,
    title: ProjectTitleArg = None,
    citekey: Annotated[
        str | None,
        typer.Option(
            "--citekey",
            autocompletion=_complete_citekeys,
            help="Paper citekey or card slug to preselect.",
        ),
    ] = None,
) -> None:
    if not _show_project_workspace_ui(
        _resolve_vault(vault),
        initial_slug=slug,
        initial_title=title,
        initial_citekey=citekey,
    ):
        console.print("Project UI unavailable.")
