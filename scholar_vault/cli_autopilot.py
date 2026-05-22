from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.table import Table

from .autopilot import (
    answer,
    ask,
    create_handoff,
    improve,
    intake,
    run_handoff,
    session_archive,
    session_current,
    session_list,
    session_show,
    start,
)
from .cli_common import JsonOutputArg, VaultArg, _print_json, _resolve_vault, console
from .sessions import HANDOFF_KINDS

session_app = typer.Typer(help="Autopilot research session state.")
codex_app = typer.Typer(help="Codex handoff helpers.")

QuestionArg = Annotated[str, typer.Argument(help="Research question text.")]
SynthesisQuestionArg = Annotated[str, typer.Argument(help="Focused synthesis question.")]
SessionIdArg = Annotated[str | None, typer.Argument(help="Session id.")]
ProjectArg = Annotated[str, typer.Argument(help="Project slug.")]
ProjectOption = Annotated[str | None, typer.Option("--project", help="Project slug.")]
ProjectTitleOption = Annotated[str | None, typer.Option("--title", help="Project title.")]
SlugOption = Annotated[str | None, typer.Option("--slug", help="Query note slug.")]
SessionOption = Annotated[str | None, typer.Option("--session", help="Session id.")]
CopyOption = Annotated[bool, typer.Option("--copy", help="Copy the selected prompt.")]
OpenScholarOption = Annotated[
    bool,
    typer.Option("--open-scholar", help="Open Google Scholar in the default browser."),
]
NewSessionOption = Annotated[
    bool,
    typer.Option("--new-session", help="Create a new session even if the current one matches."),
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
ExportOption = Annotated[
    Path | None,
    typer.Option("--export", exists=True, file_okay=True, dir_okay=False, resolve_path=True),
]
IntakeQuestionOption = Annotated[
    str | None,
    typer.Option(
        "--question",
        help="Short query/session question when bootstrapping from an export prompt.",
    ),
]
IntakeNewSessionOption = Annotated[
    bool,
    typer.Option(
        "--new-session",
        help="Create a session from the export prompt instead of using the current session.",
    ),
]
PdfOnlyOption = Annotated[
    bool,
    typer.Option("--pdf-only", help="Import PDFs without a Scholar Labs JSON export."),
]
UiOption = Annotated[
    bool,
    typer.Option("--ui", help="Open a desktop UI to resolve staged PDF match blockers."),
]
StagingOption = Annotated[
    Path | None,
    typer.Option("--staging", exists=True, file_okay=False, dir_okay=True, resolve_path=True),
]
DryRunOption = Annotated[bool, typer.Option("--dry-run", help="Plan without agent/import writes.")]
NoAgentOption = Annotated[bool, typer.Option("--no-agent", help="Do not invoke an agent.")]
AgentOption = Annotated[str | None, typer.Option("--agent", help="Agent to run: codex.")]
BudgetPapersOption = Annotated[
    int | None,
    typer.Option("--budget-papers", min=1, help="Maximum session papers to prioritize."),
]
AutoEnrichOption = Annotated[
    bool,
    typer.Option("--enrich/--no-enrich", help="Run enrichment after accepted imports."),
]
UpgradePdfsOption = Annotated[
    bool,
    typer.Option("--upgrade-pdfs/--keep-existing-pdfs", help="Review staged PDF upgrades."),
]
KindOption = Annotated[str, typer.Option("--kind", help="Handoff kind.")]


def _seed_api(value: str) -> str:
    normalized = (value or "none").strip().casefold()
    allowed = {"none", "openalex", "semantic-scholar"}
    if normalized not in allowed:
        raise typer.BadParameter("Seed API must be one of: none, openalex, semantic-scholar.")
    return normalized


def _agent(value: str | None) -> str | None:
    normalized = (value or "").strip().casefold()
    if not normalized:
        return None
    if normalized != "codex":
        raise typer.BadParameter("--agent must be 'codex' when provided.")
    return normalized


def _handoff_kind(value: str) -> str:
    normalized = (value or "").strip().casefold()
    if normalized not in HANDOFF_KINDS:
        raise typer.BadParameter(f"--kind must be one of: {', '.join(HANDOFF_KINDS)}")
    return normalized


def _print_session(summary: dict[str, object]) -> None:
    session = summary.get("session")
    if not session:
        console.print("No current active session.")
        return
    if isinstance(session, dict):
        console.print(f"Session: {session.get('id')}")
        console.print(f"Status: {session.get('status')}")
        console.print(f"Question: {session.get('question')}")
        console.print(f"Query: {session.get('query_path') or '-'}")
        console.print(f"Prompt pack: {session.get('prompt_pack_path') or '-'}")
        console.print(f"Run: {session.get('run_id') or '-'}")
        blockers = session.get("blockers") or []
        if blockers:
            console.print("Blockers: " + "; ".join(str(item) for item in blockers))


def _print_session_list(summary: dict[str, object]) -> None:
    rows = summary.get("sessions") or []
    console.print(f"Sessions: {summary.get('count', 0)}")
    if not rows:
        return
    table = Table(title="Autopilot Sessions", show_lines=False)
    table.add_column("Current")
    table.add_column("ID")
    table.add_column("Status")
    table.add_column("Run")
    table.add_column("Question")
    for row in rows:
        if not isinstance(row, dict):
            continue
        table.add_row(
            "*" if row.get("current") else "",
            str(row.get("id") or ""),
            str(row.get("status") or ""),
            str(row.get("run_id") or "-"),
            str(row.get("question") or ""),
        )
    console.print(table)


def _print_intake(summary: dict[str, object]) -> None:
    session = summary.get("session") or {}
    report = summary.get("report") or {}
    imported = summary.get("import") or {}
    blockers = summary.get("blockers") or []
    console.print(f"Session: {session.get('id') if isinstance(session, dict) else ''}")
    console.print(f"Status: {session.get('status') if isinstance(session, dict) else ''}")
    console.print(f"Run: {imported.get('run') if isinstance(imported, dict) else '-'}")
    if summary.get("pdf_only") and isinstance(imported, dict):
        console.print(
            "Imported: "
            f"pdfs={imported.get('imported', imported.get('pdf_count', 0))}, "
            f"created={imported.get('created', 0)}, "
            f"updated={imported.get('updated_existing', 0)}"
        )
    else:
        console.print(
            "Imported: "
            f"selected={imported.get('selected', 0) if isinstance(imported, dict) else 0}, "
            f"matched={imported.get('matched', 0) if isinstance(imported, dict) else 0}, "
            f"unmatched={imported.get('unmatched', 0) if isinstance(imported, dict) else 0}"
        )
    console.print(f"Report: {report.get('path') if isinstance(report, dict) else '-'}")
    if blockers:
        console.print("Next: Resolve blockers, then rerun `scholar-vault intake`.")
        for blocker in blockers:
            console.print(f"- {blocker}")
    else:
        console.print('Next: Run `scholar-vault answer "synthesis question"`.')


def _print_start(summary: dict[str, object]) -> None:
    mode = summary.get("mode")
    if mode == "ask":
        console.print(str(summary.get("prompt") or ""))
        console.print("")
        console.print(f"Next: {summary.get('next_step')}")
        return
    intake_summary = summary.get("intake") or {}
    if isinstance(intake_summary, dict):
        _print_intake(intake_summary)
    else:
        console.print(f"Next: {summary.get('next_step')}")


def _print_improve(summary: dict[str, object]) -> None:
    session = summary.get("session") or {}
    prioritized = summary.get("prioritized") or {}
    report = summary.get("report") or {}
    handoff = summary.get("handoff") or {}
    console.print(f"Session: {session.get('id') if isinstance(session, dict) else ''}")
    console.print(f"Status: {session.get('status') if isinstance(session, dict) else ''}")
    changed = prioritized.get("changed", 0) if isinstance(prioritized, dict) else 0
    console.print(f"Queue: prioritized={changed}")
    if handoff:
        console.print(f"Handoff: {handoff.get('handoff') if isinstance(handoff, dict) else ''}")
    if report:
        console.print(f"Report: {report.get('path') if isinstance(report, dict) else ''}")


def _print_answer(summary: dict[str, object]) -> None:
    handoff = summary.get("handoff") or {}
    codex = summary.get("codex") or {}
    if codex:
        session = summary.get("session") or {}
        console.print(f"Session: {session.get('id') if isinstance(session, dict) else ''}")
        console.print(f"Status: {session.get('status') if isinstance(session, dict) else ''}")
        console.print(f"Handoff: {handoff.get('handoff') if isinstance(handoff, dict) else ''}")
        return
    command = handoff.get("command") if isinstance(handoff, dict) else ""
    console.print(str(command))


def start_command(
    project: ProjectArg,
    question: QuestionArg,
    vault: VaultArg = None,
    title: ProjectTitleOption = None,
    slug: SlugOption = None,
    export: ExportOption = None,
    staging: StagingOption = None,
    pdf_only: PdfOnlyOption = False,
    seed_api: SeedApiOption = "none",
    refresh_seeds: RefreshSeedsOption = False,
    copy: CopyOption = False,
    open_scholar: OpenScholarOption = False,
    auto_enrich: AutoEnrichOption = True,
    upgrade_pdfs: UpgradePdfsOption = True,
    json_output: JsonOutputArg = False,
) -> None:
    summary = start(
        _resolve_vault(vault),
        project,
        question,
        title=title,
        slug=slug,
        export=export,
        staging=staging,
        pdf_only=pdf_only,
        seed_api=_seed_api(seed_api),
        refresh_seeds=refresh_seeds,
        copy=copy,
        open_scholar=open_scholar,
        auto_enrich=auto_enrich,
        upgrade_pdfs=upgrade_pdfs,
    )
    if json_output:
        _print_json(summary)
    else:
        _print_start(summary)


def ask_command(
    question: QuestionArg,
    vault: VaultArg = None,
    project: ProjectOption = None,
    slug: SlugOption = None,
    seed_api: SeedApiOption = "none",
    refresh_seeds: RefreshSeedsOption = False,
    copy: CopyOption = False,
    open_scholar: OpenScholarOption = False,
    new_session: NewSessionOption = False,
    json_output: JsonOutputArg = False,
) -> None:
    summary = ask(
        _resolve_vault(vault),
        question,
        project=project,
        slug=slug,
        seed_api=_seed_api(seed_api),
        refresh_seeds=refresh_seeds,
        copy=copy,
        open_scholar=open_scholar,
        new_session=new_session,
    )
    if json_output:
        _print_json(summary)
        return
    console.print(summary["prompt"])
    console.print("")
    console.print(f"Next: {summary['next_step']}")


def intake_command(
    vault: VaultArg = None,
    session_id: SessionOption = None,
    export: ExportOption = None,
    staging: StagingOption = None,
    question: IntakeQuestionOption = None,
    project: ProjectOption = None,
    slug: SlugOption = None,
    new_session: IntakeNewSessionOption = False,
    pdf_only: PdfOnlyOption = False,
    ui: UiOption = False,
    dry_run: DryRunOption = False,
    auto_enrich: AutoEnrichOption = True,
    upgrade_pdfs: UpgradePdfsOption = True,
    json_output: JsonOutputArg = False,
) -> None:
    summary = intake(
        _resolve_vault(vault),
        session_id=session_id,
        export=export,
        staging=staging,
        question=question,
        project=project,
        slug=slug,
        new_session=new_session,
        pdf_only=pdf_only,
        ui=ui,
        dry_run=dry_run,
        auto_enrich=auto_enrich,
        upgrade_pdfs=upgrade_pdfs,
    )
    if json_output:
        _print_json(summary)
    else:
        _print_intake(summary)


def improve_command(
    vault: VaultArg = None,
    session_id: SessionOption = None,
    dry_run: DryRunOption = False,
    no_agent: NoAgentOption = False,
    agent: AgentOption = None,
    budget_papers: BudgetPapersOption = None,
    json_output: JsonOutputArg = False,
) -> None:
    summary = improve(
        _resolve_vault(vault),
        session_id=session_id,
        dry_run=dry_run,
        no_agent=no_agent,
        agent=_agent(agent),
        budget_papers=budget_papers,
    )
    if json_output:
        _print_json(summary)
    else:
        _print_improve(summary)


def answer_command(
    synthesis_question: SynthesisQuestionArg,
    vault: VaultArg = None,
    session_id: SessionOption = None,
    agent: AgentOption = None,
    json_output: JsonOutputArg = False,
) -> None:
    summary = answer(
        _resolve_vault(vault),
        synthesis_question,
        session_id=session_id,
        agent=_agent(agent),
    )
    if json_output:
        _print_json(summary)
    else:
        _print_answer(summary)


@session_app.command("current")
def session_current_command(
    vault: VaultArg = None,
    json_output: JsonOutputArg = False,
) -> None:
    summary = session_current(_resolve_vault(vault))
    if json_output:
        _print_json(summary)
    else:
        _print_session(summary)


@session_app.command("list")
def session_list_command(
    vault: VaultArg = None,
    json_output: JsonOutputArg = False,
) -> None:
    summary = session_list(_resolve_vault(vault))
    if json_output:
        _print_json(summary)
    else:
        _print_session_list(summary)


@session_app.command("show")
def session_show_command(
    session_id: SessionIdArg = None,
    vault: VaultArg = None,
    json_output: JsonOutputArg = False,
) -> None:
    summary = session_show(_resolve_vault(vault), session_id=session_id)
    if json_output:
        _print_json(summary)
    else:
        _print_session(summary)


@session_app.command("archive")
def session_archive_command(
    session_id: SessionIdArg = None,
    vault: VaultArg = None,
    json_output: JsonOutputArg = False,
) -> None:
    summary = session_archive(_resolve_vault(vault), session_id=session_id)
    if json_output:
        _print_json(summary)
    else:
        _print_session(summary)


@codex_app.command("handoff")
def codex_handoff_command(
    vault: VaultArg = None,
    kind: KindOption = "post-import",
    session_id: SessionOption = None,
    synthesis_question: Annotated[
        str,
        typer.Option("--question", help="Synthesis question for answer handoffs."),
    ] = "",
    budget_papers: BudgetPapersOption = None,
    json_output: JsonOutputArg = False,
) -> None:
    summary = create_handoff(
        _resolve_vault(vault),
        kind=_handoff_kind(kind),
        session_id=session_id,
        synthesis_question=synthesis_question,
        budget_papers=budget_papers,
    )
    if json_output:
        _print_json(summary)
        return
    handoff = summary["handoff"]
    console.print(f"Handoff: {handoff['handoff']}")
    console.print(handoff["command"])


@codex_app.command("run")
def codex_run_command(
    vault: VaultArg = None,
    kind: KindOption = "post-import",
    session_id: SessionOption = None,
    synthesis_question: Annotated[
        str,
        typer.Option("--question", help="Synthesis question for answer handoffs."),
    ] = "",
    budget_papers: BudgetPapersOption = None,
    json_output: JsonOutputArg = False,
) -> None:
    summary = run_handoff(
        _resolve_vault(vault),
        kind=_handoff_kind(kind),
        session_id=session_id,
        synthesis_question=synthesis_question,
        budget_papers=budget_papers,
    )
    if json_output:
        _print_json(summary)
        return
    handoff = summary["handoff"]
    codex = summary["codex"]
    console.print(f"Handoff: {handoff['handoff']}")
    console.print(f"Codex return code: {codex['returncode']}")


__all__ = [
    "answer_command",
    "ask_command",
    "codex_app",
    "codex_handoff_command",
    "codex_run_command",
    "improve_command",
    "intake_command",
    "session_app",
    "session_archive_command",
    "session_current_command",
    "session_list_command",
    "session_show_command",
]
