from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from .models import FeedbackRecord, OperationRecord, QueueItem, ToolImprovementTask
from .obsidian import _markdown_table
from .sources import VaultPaths, ensure_relative, slugify_text, write_text, write_yaml

OPEN_QUEUE_STATUSES = {"open", "planned", "running", "drafted", "blocked"}
ACTION_FEEDBACK_VERDICTS = {"needs_fix", "rejected", "stale"}
STALE_QUEUE_DAYS = 14


def _now_iso() -> str:
    return datetime.now().astimezone().replace(microsecond=0).isoformat()


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _normalize_yaml_loaded_scalars(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, list):
        return [_normalize_yaml_loaded_scalars(item) for item in value]
    if isinstance(value, dict):
        return {key: _normalize_yaml_loaded_scalars(item) for key, item in value.items()}
    return value


def _read_yaml_mapping(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data = _normalize_yaml_loaded_scalars(data)
    if not isinstance(data, dict):
        raise ValueError("YAML record must be a mapping.")
    return data


def _safe_slug(value: str, *, fallback: str, max_length: int = 56) -> str:
    return slugify_text(value or fallback, max_length=max_length)


def _record_id(prefix: str, title: str, directory: Path, *, now: str | None = None) -> str:
    timestamp = _parse_iso(now or _now_iso()) or datetime.now().astimezone()
    stamp = timestamp.strftime("%Y%m%dT%H%M%S")
    base = f"{prefix}-{stamp}-{_safe_slug(title, fallback=prefix)}"
    candidate = base
    suffix = 2
    while (directory / f"{candidate}.yaml").exists():
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate


def _queue_path(paths: VaultPaths, queue_id: str) -> Path:
    return paths.task_queue / f"{queue_id}.yaml"


def _operation_path(paths: VaultPaths, operation_id: str) -> Path:
    return paths.operation_runs / f"{operation_id}.yaml"


def _feedback_path(paths: VaultPaths, feedback_id: str) -> Path:
    return paths.feedback_ratings / f"{feedback_id}.yaml"


def _queue_rows(paths: VaultPaths) -> list[QueueItem]:
    if not paths.task_queue.exists():
        return []
    rows: list[QueueItem] = []
    for path in sorted(paths.task_queue.glob("*.yaml")):
        rows.append(QueueItem.model_validate(_read_yaml_mapping(path)))
    return sorted(rows, key=lambda item: (item.status, item.priority, item.created_at, item.id))


def _operation_rows(paths: VaultPaths) -> list[OperationRecord]:
    if not paths.operation_runs.exists():
        return []
    rows: list[OperationRecord] = []
    for path in sorted(paths.operation_runs.glob("*.yaml")):
        rows.append(OperationRecord.model_validate(_read_yaml_mapping(path)))
    return sorted(rows, key=lambda item: (item.started_at, item.operation_id), reverse=True)


def _feedback_rows(paths: VaultPaths) -> list[FeedbackRecord]:
    if not paths.feedback_ratings.exists():
        return []
    rows: list[FeedbackRecord] = []
    for path in sorted(paths.feedback_ratings.glob("*.yaml")):
        rows.append(FeedbackRecord.model_validate(_read_yaml_mapping(path)))
    return sorted(rows, key=lambda item: (item.created_at, item.id), reverse=True)


def _find_queue_by_stable_key(paths: VaultPaths, stable_key: str) -> QueueItem | None:
    for item in _queue_rows(paths):
        if item.stable_key == stable_key:
            return item
    return None


def _write_queue_item(paths: VaultPaths, item: QueueItem) -> None:
    write_yaml(_queue_path(paths, item.id), item.model_dump(exclude_none=True))


def _write_feedback(paths: VaultPaths, item: FeedbackRecord) -> None:
    write_yaml(_feedback_path(paths, item.id), item.model_dump(exclude_none=True))


def _as_list(values: list[str] | tuple[str, ...] | None) -> list[str]:
    if not values:
        return []
    return [str(value) for value in values if str(value).strip()]


def _record_summary(item: QueueItem) -> dict[str, Any]:
    return item.model_dump(exclude_none=True)


def create_queue_item(
    vault: Path | str,
    *,
    kind: str,
    title: str,
    status: str = "open",
    priority: str = "normal",
    created_by: str = "user",
    project: str | None = None,
    query: str | None = None,
    citekeys: list[str] | None = None,
    runs: list[str] | None = None,
    files: list[str] | None = None,
    required_evidence: str = "none",
    success_criteria: str = "",
    notes: str = "",
    stable_key: str | None = None,
    linked_feedback: list[str] | None = None,
    linked_operations: list[str] | None = None,
    tool_improvement: ToolImprovementTask | dict[str, Any] | None = None,
    refresh_dashboard: bool = True,
) -> dict[str, Any]:
    from .importer import initialize_vault

    cleaned_title = re.sub(r"\s+", " ", title or "").strip()
    if not cleaned_title:
        raise ValueError("Queue title must not be empty.")
    paths = initialize_vault(vault, rebuild=False)
    existing = _find_queue_by_stable_key(paths, stable_key) if stable_key else None
    if existing is not None:
        return {
            "vault": str(paths.vault),
            "queue_item": ensure_relative(_queue_path(paths, existing.id), paths.vault),
            "id": existing.id,
            "created": False,
            "changed": False,
            "item": _record_summary(existing),
        }
    now = _now_iso()
    item_id = _record_id("queue", cleaned_title, paths.task_queue, now=now)
    item = QueueItem(
        id=item_id,
        title=cleaned_title,
        kind=kind,
        status=status,
        priority=priority,
        created_at=now,
        updated_at=now,
        created_by=created_by,
        project=project,
        query=query,
        citekeys=_as_list(citekeys),
        runs=_as_list(runs),
        files=_as_list(files),
        required_evidence=required_evidence,
        success_criteria=success_criteria,
        notes=notes,
        stable_key=stable_key,
        linked_feedback=_as_list(linked_feedback),
        linked_operations=_as_list(linked_operations),
        tool_improvement=tool_improvement,
    )
    _write_queue_item(paths, item)
    if refresh_dashboard:
        write_self_improvement_dashboard(paths.vault)
    return {
        "vault": str(paths.vault),
        "queue_item": ensure_relative(_queue_path(paths, item.id), paths.vault),
        "id": item.id,
        "created": True,
        "changed": True,
        "item": _record_summary(item),
    }


def list_queue_items(vault: Path | str) -> dict[str, Any]:
    paths = VaultPaths.from_root(vault)
    rows = [_record_summary(item) for item in _queue_rows(paths)]
    counts = Counter(row["status"] for row in rows)
    return {"vault": str(paths.vault), "count": len(rows), "counts": dict(counts), "items": rows}


def show_queue_item(vault: Path | str, queue_id: str) -> dict[str, Any]:
    paths = VaultPaths.from_root(vault)
    path = _queue_path(paths, queue_id)
    if not path.exists():
        raise ValueError(f"Queue item does not exist: {queue_id}")
    item = QueueItem.model_validate(_read_yaml_mapping(path))
    return {
        "vault": str(paths.vault),
        "queue_item": ensure_relative(path, paths.vault),
        "item": _record_summary(item),
    }


def _update_queue_status(
    vault: Path | str,
    queue_id: str,
    *,
    status: str,
    notes: str = "",
) -> dict[str, Any]:
    paths = VaultPaths.from_root(vault)
    path = _queue_path(paths, queue_id)
    if not path.exists():
        raise ValueError(f"Queue item does not exist: {queue_id}")
    item = QueueItem.model_validate(_read_yaml_mapping(path))
    item.status = status  # type: ignore[assignment]
    item.updated_at = _now_iso()
    if notes.strip():
        item.notes = f"{item.notes.strip()}\n\n{notes.strip()}".strip()
    _write_queue_item(paths, item)
    write_self_improvement_dashboard(paths.vault)
    return {
        "vault": str(paths.vault),
        "queue_item": ensure_relative(path, paths.vault),
        "changed": True,
        "item": _record_summary(item),
    }


def plan_queue_item(vault: Path | str, queue_id: str) -> dict[str, Any]:
    return _update_queue_status(vault, queue_id, status="planned")


def close_queue_item(
    vault: Path | str,
    queue_id: str,
    *,
    status: str,
    notes: str = "",
) -> dict[str, Any]:
    if status not in {"done", "rejected", "blocked"}:
        raise ValueError("Close status must be done, rejected, or blocked.")
    return _update_queue_status(vault, queue_id, status=status, notes=notes)


def doctor_queue(vault: Path | str) -> dict[str, Any]:
    paths = VaultPaths.from_root(vault)
    rows: list[dict[str, Any]] = []
    issue_counts = {
        "invalid_yaml": 0,
        "invalid_schema": 0,
        "duplicate_ids": 0,
        "duplicate_stable_keys": 0,
    }
    seen_ids: set[str] = set()
    seen_stable: dict[str, str] = {}
    for path in sorted(paths.task_queue.glob("*.yaml")):
        row = {"path": ensure_relative(path, paths.vault), "ok": True, "issues": []}
        try:
            data = _read_yaml_mapping(path)
        except (OSError, yaml.YAMLError, ValueError) as exc:
            row["ok"] = False
            row["issues"].append(f"invalid YAML: {exc}")
            issue_counts["invalid_yaml"] += 1
            rows.append(row)
            continue
        try:
            item = QueueItem.model_validate(data)
        except ValueError as exc:
            row["ok"] = False
            row["issues"].append(f"invalid schema: {exc}")
            issue_counts["invalid_schema"] += 1
            rows.append(row)
            continue
        if item.id in seen_ids:
            row["ok"] = False
            row["issues"].append(f"duplicate id: {item.id}")
            issue_counts["duplicate_ids"] += 1
        seen_ids.add(item.id)
        if item.stable_key:
            previous = seen_stable.get(item.stable_key)
            if previous:
                row["ok"] = False
                row["issues"].append(f"duplicate stable key: {item.stable_key}")
                issue_counts["duplicate_stable_keys"] += 1
            seen_stable[item.stable_key] = item.id
        rows.append(row)
    return {
        "vault": str(paths.vault),
        "ok": not any(issue_counts.values()),
        "issue_counts": issue_counts,
        "records": rows,
    }


def log_operation(
    vault: Path | str,
    *,
    kind: str,
    message: str,
    agent: str | None = None,
    model: str | None = None,
    command: str | None = None,
    inputs: dict[str, Any] | None = None,
    outputs: dict[str, Any] | None = None,
    files_changed: list[str] | None = None,
    evidence_used: list[str] | None = None,
    checks_run: list[str] | None = None,
    result: str = "logged",
    linked_queue_items: list[str] | None = None,
    linked_feedback: list[str] | None = None,
    refresh_dashboard: bool = True,
) -> dict[str, Any]:
    from .importer import initialize_vault

    paths = initialize_vault(vault, rebuild=False)
    now = _now_iso()
    operation_id = _record_id("op", kind, paths.operation_runs, now=now)
    merged_outputs = dict(outputs or {})
    merged_outputs["message"] = message
    record = OperationRecord(
        operation_id=operation_id,
        kind=kind,
        started_at=now,
        finished_at=now,
        agent=agent,
        model=model,
        command=command,
        inputs=inputs or {},
        outputs=merged_outputs,
        files_changed=_as_list(files_changed),
        evidence_used=_as_list(evidence_used),
        checks_run=_as_list(checks_run),
        result=result,
        linked_queue_items=_as_list(linked_queue_items),
        linked_feedback=_as_list(linked_feedback),
    )
    path = _operation_path(paths, operation_id)
    write_yaml(path, record.model_dump(exclude_none=True))
    append_operation_markdown(paths, record)
    if refresh_dashboard:
        write_self_improvement_dashboard(paths.vault)
    return {
        "vault": str(paths.vault),
        "operation": ensure_relative(path, paths.vault),
        "operation_id": operation_id,
        "record": record.model_dump(exclude_none=True),
    }


def append_operation_markdown(paths: VaultPaths, record: OperationRecord) -> None:
    log_path = paths.operations / "log.md"
    if log_path.exists():
        text = log_path.read_text(encoding="utf-8").rstrip()
    else:
        text = "# Operation Log\n\nAppend-only log of vault maintenance and agent work."
    message = str(record.outputs.get("message") or "")
    run_ref = ensure_relative(_operation_path(paths, record.operation_id), paths.vault)
    section = [
        "",
        f"## {record.operation_id} - {record.kind}",
        "",
        f"- Started: {record.started_at}",
        f"- Finished: {record.finished_at or ''}",
        f"- Result: {record.result}",
        f"- Run record: [{run_ref}](../{run_ref})",
    ]
    if record.command:
        section.append(f"- Command: `{record.command}`")
    if message:
        section.extend(["", message])
    write_text(log_path, text + "\n" + "\n".join(section))


def list_operations(vault: Path | str) -> dict[str, Any]:
    paths = VaultPaths.from_root(vault)
    rows = [item.model_dump(exclude_none=True) for item in _operation_rows(paths)]
    counts = Counter(row["kind"] for row in rows)
    return {
        "vault": str(paths.vault),
        "count": len(rows),
        "counts": dict(counts),
        "operations": rows,
    }


def show_operation(vault: Path | str, operation_id: str) -> dict[str, Any]:
    paths = VaultPaths.from_root(vault)
    path = _operation_path(paths, operation_id)
    if not path.exists():
        raise ValueError(f"Operation does not exist: {operation_id}")
    record = OperationRecord.model_validate(_read_yaml_mapping(path))
    return {
        "vault": str(paths.vault),
        "operation": ensure_relative(path, paths.vault),
        "record": record.model_dump(exclude_none=True),
    }


def doctor_operations(vault: Path | str) -> dict[str, Any]:
    paths = VaultPaths.from_root(vault)
    log_text = (paths.operations / "log.md").read_text(encoding="utf-8") if (
        paths.operations / "log.md"
    ).exists() else ""
    rows: list[dict[str, Any]] = []
    issue_counts = {"invalid_yaml": 0, "invalid_schema": 0, "missing_log_entry": 0}
    for path in sorted(paths.operation_runs.glob("*.yaml")):
        row = {"path": ensure_relative(path, paths.vault), "ok": True, "issues": []}
        try:
            record = OperationRecord.model_validate(_read_yaml_mapping(path))
        except (OSError, yaml.YAMLError, ValueError) as exc:
            row["ok"] = False
            row["issues"].append(f"invalid operation record: {exc}")
            issue_counts["invalid_schema"] += 1
            rows.append(row)
            continue
        if record.operation_id not in log_text:
            row["ok"] = False
            row["issues"].append("operation_id is missing from _operations/log.md")
            issue_counts["missing_log_entry"] += 1
        rows.append(row)
    return {
        "vault": str(paths.vault),
        "ok": not any(issue_counts.values()),
        "issue_counts": issue_counts,
        "records": rows,
    }


def rate_feedback(
    vault: Path | str,
    target: str,
    *,
    verdict: str,
    target_type: str,
    notes: str = "",
    linked_operation: str | None = None,
    linked_queue_item: str | None = None,
    refresh_dashboard: bool = True,
) -> dict[str, Any]:
    from .importer import initialize_vault

    paths = initialize_vault(vault, rebuild=False)
    now = _now_iso()
    feedback_id = _record_id("feedback", target, paths.feedback_ratings, now=now)
    record = FeedbackRecord(
        id=feedback_id,
        target=target,
        target_type=target_type,
        verdict=verdict,
        notes=notes,
        created_at=now,
        linked_operation=linked_operation,
        linked_queue_item=linked_queue_item,
    )
    _write_feedback(paths, record)
    if refresh_dashboard:
        write_self_improvement_dashboard(paths.vault)
    return {
        "vault": str(paths.vault),
        "feedback": ensure_relative(_feedback_path(paths, feedback_id), paths.vault),
        "id": feedback_id,
        "record": record.model_dump(exclude_none=True),
    }


def list_feedback(vault: Path | str) -> dict[str, Any]:
    paths = VaultPaths.from_root(vault)
    rows = [item.model_dump(exclude_none=True) for item in _feedback_rows(paths)]
    return {
        "vault": str(paths.vault),
        "count": len(rows),
        "counts": dict(Counter(row["verdict"] for row in rows)),
        "feedback": rows,
    }


def show_feedback(vault: Path | str, feedback_id: str) -> dict[str, Any]:
    paths = VaultPaths.from_root(vault)
    path = _feedback_path(paths, feedback_id)
    if not path.exists():
        raise ValueError(f"Feedback does not exist: {feedback_id}")
    record = FeedbackRecord.model_validate(_read_yaml_mapping(path))
    return {
        "vault": str(paths.vault),
        "feedback": ensure_relative(path, paths.vault),
        "record": record.model_dump(exclude_none=True),
    }


def _feedback_theme(record: FeedbackRecord) -> str:
    text = f"{record.target} {record.notes}".strip()
    tokens = [
        token.casefold()
        for token in re.findall(r"[A-Za-z][A-Za-z0-9-]{2,}", text)
        if token.casefold()
        not in {
            "the",
            "and",
            "for",
            "with",
            "that",
            "this",
            "from",
            "into",
            "needs",
            "fix",
            "tool",
            "behavior",
        }
    ]
    if not tokens:
        return record.target_type
    return f"{record.target_type}: " + " ".join(tokens[:6])


def feedback_report(vault: Path | str) -> dict[str, Any]:
    paths = VaultPaths.from_root(vault)
    rows = _feedback_rows(paths)
    by_verdict = Counter(record.verdict for record in rows)
    by_target_type = Counter(record.target_type for record in rows)
    needing_action = [
        record.model_dump(exclude_none=True)
        for record in rows
        if record.verdict in ACTION_FEEDBACK_VERDICTS
    ]
    theme_groups: dict[str, list[FeedbackRecord]] = defaultdict(list)
    for record in rows:
        if record.verdict in ACTION_FEEDBACK_VERDICTS:
            theme_groups[_feedback_theme(record)].append(record)
    repeated_themes = [
        {
            "theme": theme,
            "count": len(records),
            "feedback": [record.id for record in records],
        }
        for theme, records in sorted(theme_groups.items())
        if len(records) >= 2
    ]
    improvement_candidates = [
        record.model_dump(exclude_none=True)
        for record in rows
        if record.target_type == "tool_behavior" and record.verdict in ACTION_FEEDBACK_VERDICTS
    ]
    return {
        "vault": str(paths.vault),
        "count": len(rows),
        "by_verdict": dict(by_verdict),
        "by_target_type": dict(by_target_type),
        "needing_action": needing_action,
        "repeated_failure_themes": repeated_themes,
        "tool_improvement_candidates": improvement_candidates,
    }


def doctor_feedback(vault: Path | str) -> dict[str, Any]:
    paths = VaultPaths.from_root(vault)
    rows: list[dict[str, Any]] = []
    issue_counts = {"invalid_yaml": 0, "invalid_schema": 0, "missing_links": 0}
    for path in sorted(paths.feedback_ratings.glob("*.yaml")):
        row = {"path": ensure_relative(path, paths.vault), "ok": True, "issues": []}
        try:
            record = FeedbackRecord.model_validate(_read_yaml_mapping(path))
        except (OSError, yaml.YAMLError, ValueError) as exc:
            row["ok"] = False
            row["issues"].append(f"invalid feedback record: {exc}")
            issue_counts["invalid_schema"] += 1
            rows.append(row)
            continue
        if record.linked_operation and not _operation_path(paths, record.linked_operation).exists():
            row["ok"] = False
            row["issues"].append(f"missing linked operation: {record.linked_operation}")
            issue_counts["missing_links"] += 1
        if record.linked_queue_item and not _queue_path(paths, record.linked_queue_item).exists():
            row["ok"] = False
            row["issues"].append(f"missing linked queue item: {record.linked_queue_item}")
            issue_counts["missing_links"] += 1
        rows.append(row)
    return {
        "vault": str(paths.vault),
        "ok": not any(issue_counts.values()),
        "issue_counts": issue_counts,
        "records": rows,
    }


def create_tools_task(
    vault: Path | str,
    *,
    title: str,
    from_feedback: str | None = None,
    problem: str = "",
    reproduction: str = "",
    expected_behavior: str = "",
    actual_behavior: str = "",
    proposed_cli_change: str = "",
    tests_to_add: list[str] | None = None,
) -> dict[str, Any]:
    paths = VaultPaths.from_root(vault)
    linked_feedback: list[str] = []
    feedback_record: FeedbackRecord | None = None
    if from_feedback:
        feedback_summary = show_feedback(paths.vault, from_feedback)
        feedback_record = FeedbackRecord.model_validate(feedback_summary["record"])
        linked_feedback = [from_feedback]
        if not problem:
            problem = feedback_record.notes or f"Feedback on {feedback_record.target}"
        if not actual_behavior:
            actual_behavior = feedback_record.notes
    tool_task = ToolImprovementTask(
        target_repo="scholar-vault-tools",
        problem=problem,
        reproduction=reproduction,
        expected_behavior=expected_behavior,
        actual_behavior=actual_behavior,
        proposed_cli_change=proposed_cli_change,
        tests_to_add=_as_list(tests_to_add),
    )
    summary = create_queue_item(
        paths.vault,
        kind="improve_tool",
        title=title,
        created_by="feedback" if from_feedback else "user",
        required_evidence="none",
        success_criteria=expected_behavior,
        notes=problem,
        stable_key=f"tools-task:{from_feedback}" if from_feedback else None,
        linked_feedback=linked_feedback,
        tool_improvement=tool_task,
        refresh_dashboard=False,
    )
    if feedback_record is not None and not feedback_record.linked_queue_item:
        feedback_record.linked_queue_item = summary["id"]
        _write_feedback(paths, feedback_record)
    write_self_improvement_dashboard(paths.vault)
    return summary


def _is_stale_queue_item(item: QueueItem, now: datetime) -> bool:
    if item.status not in OPEN_QUEUE_STATUSES:
        return False
    updated_at = _parse_iso(item.updated_at)
    if updated_at is None:
        return True
    if updated_at.tzinfo is None and now.tzinfo is not None:
        updated_at = updated_at.replace(tzinfo=now.tzinfo)
    return updated_at <= now - timedelta(days=STALE_QUEUE_DAYS)


def render_self_improvement_dashboard(vault: Path | str, *, now: datetime | None = None) -> str:
    paths = VaultPaths.from_root(vault)
    now_value = now or datetime.now().astimezone()
    queue_items = _queue_rows(paths)
    operations = _operation_rows(paths)
    feedback = _feedback_rows(paths)
    report = feedback_report(paths.vault)
    from .discovery import discovery_counts

    discovery_summary = discovery_counts(paths)
    open_by_kind = Counter(
        item.kind for item in queue_items if item.status in OPEN_QUEUE_STATUSES
    )
    stale_items = [item for item in queue_items if _is_stale_queue_item(item, now_value)]
    feedback_needing_action = [
        record for record in feedback if record.verdict in ACTION_FEEDBACK_VERDICTS
    ]
    tool_tasks = [
        item for item in queue_items if item.kind == "improve_tool" and item.status != "done"
    ]
    lines = [
        "# Self-Improvement Dashboard",
        "",
        "Typed queue, operation, and feedback state for safe vault improvement. These records "
        "coordinate work; they do not authorize automated rewrites of paper cards, concepts, "
        "or syntheses.",
        "",
        "## Open queue items by kind",
        "",
        *_markdown_table(
            ["Kind", "Open items"],
            [[kind, count] for kind, count in sorted(open_by_kind.items())],
            empty="No open queue items.",
        ),
        "",
        "## Discovery candidates",
        "",
        "Graph-assisted discovery candidates are prompt-planning context, not evidence or "
        "canonical paper cards.",
        "",
        *_markdown_table(
            ["Status", "Count"],
            [
                [status, count]
                for status, count in (
                    discovery_summary.get("discovery_candidate_status") or {}
                ).items()
            ],
            empty="No graph-assisted discovery candidates found.",
        ),
        "",
        "## Stale queue items",
        "",
        *_markdown_table(
            ["ID", "Kind", "Status", "Updated", "Title"],
            [
                [item.id, item.kind, item.status, item.updated_at, item.title]
                for item in stale_items[:50]
            ],
            empty=f"No open queue item is older than {STALE_QUEUE_DAYS} days.",
        ),
        "",
        "## Recent operations",
        "",
        *_markdown_table(
            ["Operation", "Kind", "Finished", "Result"],
            [
                [
                    operation.operation_id,
                    operation.kind,
                    operation.finished_at or operation.started_at,
                    operation.result,
                ]
                for operation in operations[:15]
            ],
            empty="No operation records yet.",
        ),
        "",
        "## Feedback needing action",
        "",
        *_markdown_table(
            ["Feedback", "Target type", "Verdict", "Target"],
            [
                [record.id, record.target_type, record.verdict, record.target]
                for record in feedback_needing_action[:50]
            ],
            empty="No feedback records currently need action.",
        ),
        "",
        "## Repeated failure themes",
        "",
        *_markdown_table(
            ["Theme", "Count", "Feedback"],
            [
                [row["theme"], row["count"], ", ".join(row["feedback"])]
                for row in report["repeated_failure_themes"]
            ],
            empty="No repeated failure themes detected.",
        ),
        "",
        "## Tool-improvement tasks",
        "",
        *_markdown_table(
            ["ID", "Status", "Priority", "Title"],
            [[item.id, item.status, item.priority, item.title] for item in tool_tasks[:50]],
            empty="No open tool-improvement tasks.",
        ),
        "",
    ]
    return "\n".join(lines)


def write_self_improvement_dashboard(
    vault: Path | str,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    from .importer import initialize_vault

    paths = initialize_vault(vault, rebuild=False)
    path = paths.indexes / "self-improvement.md"
    text = render_self_improvement_dashboard(paths.vault, now=now)
    before = path.read_text(encoding="utf-8") if path.exists() else None
    write_text(path, text)
    return {
        "vault": str(paths.vault),
        "dashboard": ensure_relative(path, paths.vault),
        "changed": before != text.rstrip() + "\n",
    }
