from __future__ import annotations

from typing import Annotated, Any

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
from .self_improvement import (
    close_queue_item,
    create_queue_item,
    create_tools_task,
    doctor_feedback,
    doctor_operations,
    doctor_queue,
    feedback_report,
    list_feedback,
    list_operations,
    list_queue_items,
    log_operation,
    plan_queue_item,
    rate_feedback,
    show_operation,
    show_queue_item,
)

queue_app = typer.Typer(help="Typed vault improvement queue.")
operations_app = typer.Typer(help="Append-only vault operation log.")
feedback_app = typer.Typer(help="Vault feedback records and reports.")
tools_task_app = typer.Typer(help="Tool-improvement task bridge.")

QueueIdArg = Annotated[str, typer.Argument(help="Queue item id.")]
OperationIdArg = Annotated[str, typer.Argument(help="Operation id.")]
FeedbackIdArg = Annotated[str, typer.Argument(help="Feedback id.")]
FeedbackTargetArg = Annotated[str, typer.Argument(help="Feedback target path, id, or query.")]

KindOption = Annotated[str, typer.Option("--kind", help="Queue or operation kind.")]
TitleOption = Annotated[str, typer.Option("--title", help="Short task title.")]
RequiredTitleOption = Annotated[str, typer.Option(..., "--title", help="Short task title.")]
StatusOption = Annotated[str, typer.Option("--status", help="Queue close status.")]
PriorityOption = Annotated[str, typer.Option("--priority", help="Queue priority.")]
CreatedByOption = Annotated[str, typer.Option("--created-by", help="Queue origin.")]
ProjectOption = Annotated[str | None, typer.Option("--project", help="Project slug.")]
QueryOption = Annotated[str | None, typer.Option("--query", help="Related query slug or path.")]
RequiredEvidenceOption = Annotated[
    str,
    typer.Option("--required-evidence", help="Required evidence: pdf, metadata, web, or none."),
]
SuccessCriteriaOption = Annotated[
    str,
    typer.Option("--success-criteria", help="How to tell this task is complete."),
]
NotesOption = Annotated[str, typer.Option("--notes", help="Freeform notes.")]
StableKeyOption = Annotated[
    str | None,
    typer.Option("--stable-key", help="Stable duplicate-prevention key."),
]
MessageOption = Annotated[str, typer.Option("--message", help="Operation log message.")]
RequiredMessageOption = Annotated[
    str,
    typer.Option(..., "--message", help="Operation log message."),
]
AgentOption = Annotated[str | None, typer.Option("--agent", help="Agent or automation name.")]
ModelOption = Annotated[str | None, typer.Option("--model", help="Model used.")]
CommandOption = Annotated[str | None, typer.Option("--command", help="Command that ran.")]
ResultOption = Annotated[str, typer.Option("--result", help="Operation result label.")]
TargetTypeOption = Annotated[
    str,
    typer.Option("--target-type", help="Feedback target type."),
]
VerdictOption = Annotated[str, typer.Option("--verdict", help="Feedback verdict.")]
FromFeedbackOption = Annotated[
    str | None,
    typer.Option("--from-feedback", help="Feedback id to convert into a tools task."),
]
ProblemOption = Annotated[str, typer.Option("--problem", help="Problem statement.")]
ReproductionOption = Annotated[str, typer.Option("--reproduction", help="Reproduction steps.")]
ExpectedOption = Annotated[
    str,
    typer.Option("--expected-behavior", help="Expected behavior."),
]
ActualOption = Annotated[str, typer.Option("--actual-behavior", help="Actual behavior.")]
CliChangeOption = Annotated[
    str,
    typer.Option("--proposed-cli-change", help="Proposed CLI or tool change."),
]


def _print_queue_list(summary: dict[str, Any]) -> None:
    console.print(f"Queue items: {summary.get('count', 0)}")
    rows = summary.get("items") or []
    if not rows:
        return
    table = Table(title="Queue", show_lines=False)
    table.add_column("ID")
    table.add_column("Kind")
    table.add_column("Status")
    table.add_column("Priority")
    table.add_column("Title")
    for row in rows:
        table.add_row(
            str(row.get("id") or ""),
            str(row.get("kind") or ""),
            str(row.get("status") or ""),
            str(row.get("priority") or ""),
            str(row.get("title") or ""),
        )
    console.print(table)


def _print_queue_change(summary: dict[str, Any]) -> None:
    state = "created" if summary.get("created", summary.get("changed")) else "unchanged"
    item = summary.get("item") or {}
    console.print(f"Queue {state}: {item.get('id')} ({item.get('status')}) {item.get('title')}")


def _print_queue_show(summary: dict[str, Any]) -> None:
    item = summary.get("item") or {}
    console.print(f"Queue item: {item.get('id')}")
    console.print(f"Title: {item.get('title')}")
    console.print(
        "Kind/status/priority: "
        f"{item.get('kind')} / {item.get('status')} / {item.get('priority')}"
    )
    if item.get("success_criteria"):
        console.print(f"Success criteria: {item.get('success_criteria')}")
    if item.get("notes"):
        console.print(f"Notes: {item.get('notes')}")


def _print_doctor(title: str, summary: dict[str, Any]) -> None:
    console.print(f"{title}: {'OK' if summary.get('ok') else 'ISSUES'}")
    _print_issue_counts(f"{title} Issues", summary.get("issue_counts") or {})
    for row in summary.get("records") or []:
        if row.get("issues"):
            console.print(f"- {row.get('path')}: {'; '.join(row.get('issues') or [])}")


def _print_operation_list(summary: dict[str, Any]) -> None:
    console.print(f"Operations: {summary.get('count', 0)}")
    rows = summary.get("operations") or []
    if not rows:
        return
    table = Table(title="Operations", show_lines=False)
    table.add_column("ID")
    table.add_column("Kind")
    table.add_column("Finished")
    table.add_column("Result")
    for row in rows:
        table.add_row(
            str(row.get("operation_id") or ""),
            str(row.get("kind") or ""),
            str(row.get("finished_at") or row.get("started_at") or ""),
            str(row.get("result") or ""),
        )
    console.print(table)


def _print_operation(summary: dict[str, Any]) -> None:
    record = summary.get("record") or {}
    console.print(f"Operation: {record.get('operation_id')}")
    console.print(f"Kind: {record.get('kind')}")
    console.print(f"Result: {record.get('result')}")
    outputs = record.get("outputs") or {}
    if outputs.get("message"):
        console.print(str(outputs.get("message")))


def _print_feedback_list(summary: dict[str, Any]) -> None:
    console.print(f"Feedback records: {summary.get('count', 0)}")
    rows = summary.get("feedback") or []
    if not rows:
        return
    table = Table(title="Feedback", show_lines=False)
    table.add_column("ID")
    table.add_column("Verdict")
    table.add_column("Target type")
    table.add_column("Target")
    for row in rows:
        table.add_row(
            str(row.get("id") or ""),
            str(row.get("verdict") or ""),
            str(row.get("target_type") or ""),
            str(row.get("target") or ""),
        )
    console.print(table)


def _print_feedback_report(summary: dict[str, Any]) -> None:
    console.print(f"Feedback report: {summary.get('count', 0)} record(s)")
    _print_issue_counts("Feedback by verdict", summary.get("by_verdict") or {})
    needing_action = summary.get("needing_action") or []
    repeated = summary.get("repeated_failure_themes") or []
    console.print(
        f"Needs action: {len(needing_action)}; repeated failure themes: {len(repeated)}; "
        f"tool candidates: {len(summary.get('tool_improvement_candidates') or [])}."
    )


@queue_app.command("list")
def queue_list_command(
    vault: VaultArg = None,
    json_output: JsonOutputArg = False,
) -> None:
    summary = list_queue_items(_resolve_vault(vault))
    if json_output:
        _print_json(summary)
    else:
        _print_queue_list(summary)


@queue_app.command("add")
def queue_add_command(
    vault: VaultArg = None,
    kind: KindOption = "compile_paper",
    title: RequiredTitleOption = ...,
    priority: PriorityOption = "normal",
    created_by: CreatedByOption = "user",
    project: ProjectOption = None,
    query: QueryOption = None,
    citekeys: Annotated[
        list[str] | None,
        typer.Option("--citekey", help="Related citekey."),
    ] = None,
    runs: Annotated[list[str] | None, typer.Option("--run", help="Related run id.")] = None,
    files: Annotated[list[str] | None, typer.Option("--file", help="Related file path.")] = None,
    required_evidence: RequiredEvidenceOption = "none",
    success_criteria: SuccessCriteriaOption = "",
    notes: NotesOption = "",
    stable_key: StableKeyOption = None,
    json_output: JsonOutputArg = False,
) -> None:
    summary = create_queue_item(
        _resolve_vault(vault),
        kind=kind,
        title=title,
        priority=priority,
        created_by=created_by,
        project=project,
        query=query,
        citekeys=citekeys,
        runs=runs,
        files=files,
        required_evidence=required_evidence,
        success_criteria=success_criteria,
        notes=notes,
        stable_key=stable_key,
    )
    if json_output:
        _print_json(summary)
    else:
        _print_queue_change(summary)


@queue_app.command("show")
def queue_show_command(
    queue_id: QueueIdArg,
    vault: VaultArg = None,
    json_output: JsonOutputArg = False,
) -> None:
    summary = show_queue_item(_resolve_vault(vault), queue_id)
    if json_output:
        _print_json(summary)
    else:
        _print_queue_show(summary)


@queue_app.command("plan")
def queue_plan_command(
    queue_id: QueueIdArg,
    vault: VaultArg = None,
    json_output: JsonOutputArg = False,
) -> None:
    summary = plan_queue_item(_resolve_vault(vault), queue_id)
    if json_output:
        _print_json(summary)
    else:
        _print_queue_change(summary)


@queue_app.command("close")
def queue_close_command(
    queue_id: QueueIdArg,
    vault: VaultArg = None,
    status: StatusOption = "done",
    notes: NotesOption = "",
    json_output: JsonOutputArg = False,
) -> None:
    summary = close_queue_item(_resolve_vault(vault), queue_id, status=status, notes=notes)
    if json_output:
        _print_json(summary)
    else:
        _print_queue_change(summary)


@queue_app.command("doctor")
def queue_doctor_command(
    vault: VaultArg = None,
    json_output: JsonOutputArg = False,
) -> None:
    summary = doctor_queue(_resolve_vault(vault))
    if json_output:
        _print_json(summary)
    else:
        _print_doctor("Queue doctor", summary)


@operations_app.command("log")
def operations_log_command(
    vault: VaultArg = None,
    kind: KindOption = "manual",
    message: RequiredMessageOption = ...,
    agent: AgentOption = None,
    model: ModelOption = None,
    command: CommandOption = None,
    files_changed: Annotated[list[str] | None, typer.Option("--file", help="Changed file.")] = None,
    evidence_used: Annotated[
        list[str] | None,
        typer.Option("--evidence", help="Evidence used."),
    ] = None,
    checks_run: Annotated[list[str] | None, typer.Option("--check", help="Check run.")] = None,
    linked_queue_items: Annotated[
        list[str] | None,
        typer.Option("--queue-item", help="Linked queue item id."),
    ] = None,
    linked_feedback: Annotated[
        list[str] | None,
        typer.Option("--feedback", help="Linked feedback id."),
    ] = None,
    result: ResultOption = "logged",
    json_output: JsonOutputArg = False,
) -> None:
    summary = log_operation(
        _resolve_vault(vault),
        kind=kind,
        message=message,
        agent=agent,
        model=model,
        command=command,
        files_changed=files_changed,
        evidence_used=evidence_used,
        checks_run=checks_run,
        linked_queue_items=linked_queue_items,
        linked_feedback=linked_feedback,
        result=result,
    )
    if json_output:
        _print_json(summary)
    else:
        _print_operation(summary)


@operations_app.command("list")
def operations_list_command(
    vault: VaultArg = None,
    json_output: JsonOutputArg = False,
) -> None:
    summary = list_operations(_resolve_vault(vault))
    if json_output:
        _print_json(summary)
    else:
        _print_operation_list(summary)


@operations_app.command("show")
def operations_show_command(
    operation_id: OperationIdArg,
    vault: VaultArg = None,
    json_output: JsonOutputArg = False,
) -> None:
    summary = show_operation(_resolve_vault(vault), operation_id)
    if json_output:
        _print_json(summary)
    else:
        _print_operation(summary)


@operations_app.command("doctor")
def operations_doctor_command(
    vault: VaultArg = None,
    json_output: JsonOutputArg = False,
) -> None:
    summary = doctor_operations(_resolve_vault(vault))
    if json_output:
        _print_json(summary)
    else:
        _print_doctor("Operations doctor", summary)


@feedback_app.command("rate")
def feedback_rate_command(
    target: FeedbackTargetArg,
    vault: VaultArg = None,
    verdict: VerdictOption = "useful",
    notes: NotesOption = "",
    target_type: TargetTypeOption = "tool_behavior",
    linked_operation: Annotated[
        str | None,
        typer.Option("--operation", help="Linked operation id."),
    ] = None,
    linked_queue_item: Annotated[
        str | None,
        typer.Option("--queue-item", help="Linked queue item id."),
    ] = None,
    json_output: JsonOutputArg = False,
) -> None:
    summary = rate_feedback(
        _resolve_vault(vault),
        target,
        verdict=verdict,
        target_type=target_type,
        notes=notes,
        linked_operation=linked_operation,
        linked_queue_item=linked_queue_item,
    )
    if json_output:
        _print_json(summary)
    else:
        console.print(f"Feedback recorded: {summary.get('id')} ({verdict})")


@feedback_app.command("list")
def feedback_list_command(
    vault: VaultArg = None,
    json_output: JsonOutputArg = False,
) -> None:
    summary = list_feedback(_resolve_vault(vault))
    if json_output:
        _print_json(summary)
    else:
        _print_feedback_list(summary)


@feedback_app.command("report")
def feedback_report_command(
    vault: VaultArg = None,
    json_output: JsonOutputArg = False,
) -> None:
    summary = feedback_report(_resolve_vault(vault))
    if json_output:
        _print_json(summary)
    else:
        _print_feedback_report(summary)


@feedback_app.command("doctor")
def feedback_doctor_command(
    vault: VaultArg = None,
    json_output: JsonOutputArg = False,
) -> None:
    summary = doctor_feedback(_resolve_vault(vault))
    if json_output:
        _print_json(summary)
    else:
        _print_doctor("Feedback doctor", summary)


@tools_task_app.command("create")
def tools_task_create_command(
    vault: VaultArg = None,
    title: RequiredTitleOption = ...,
    from_feedback: FromFeedbackOption = None,
    problem: ProblemOption = "",
    reproduction: ReproductionOption = "",
    expected_behavior: ExpectedOption = "",
    actual_behavior: ActualOption = "",
    proposed_cli_change: CliChangeOption = "",
    tests_to_add: Annotated[
        list[str] | None,
        typer.Option("--test", help="Test to add for the tool improvement."),
    ] = None,
    json_output: JsonOutputArg = False,
) -> None:
    summary = create_tools_task(
        _resolve_vault(vault),
        title=title,
        from_feedback=from_feedback,
        problem=problem,
        reproduction=reproduction,
        expected_behavior=expected_behavior,
        actual_behavior=actual_behavior,
        proposed_cli_change=proposed_cli_change,
        tests_to_add=tests_to_add,
    )
    if json_output:
        _print_json(summary)
    else:
        _print_queue_change(summary)
