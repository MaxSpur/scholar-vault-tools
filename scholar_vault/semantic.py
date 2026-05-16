from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .obsidian import _markdown_table
from .sources import VaultPaths, ensure_relative, slugify_text, write_text

SEVERITIES = {"info", "warning", "error"}
ACTIONS = {"report_only", "create_queue_item", "needs_user_review", "needs_tool_change"}


def semantic_finding_id(namespace: str, check: str, subject: str) -> str:
    normalized = re.sub(r"\s+", " ", f"{namespace}:{check}:{subject}").strip().casefold()
    digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:12]
    slug = slugify_text(subject or check, max_length=48)
    return f"{namespace}:{check}:{slug}:{digest}"


@dataclass(frozen=True)
class SemanticFinding:
    id: str
    check: str
    severity: str
    action: str
    title: str
    message: str
    files: list[str] = field(default_factory=list)
    citekeys: list[str] = field(default_factory=list)
    runs: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)
    queue_kind: str = "lint_fix"
    required_evidence: str = "none"
    success_criteria: str = ""
    queueable: bool = True
    tool_improvement: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.severity not in SEVERITIES:
            raise ValueError(f"Invalid semantic finding severity: {self.severity}")
        if self.action not in ACTIONS:
            raise ValueError(f"Invalid semantic finding action: {self.action}")

    def to_dict(self) -> dict[str, Any]:
        data = {
            "id": self.id,
            "check": self.check,
            "severity": self.severity,
            "action": self.action,
            "title": self.title,
            "message": self.message,
            "files": list(self.files),
            "citekeys": list(self.citekeys),
            "runs": list(self.runs),
            "details": dict(self.details),
            "queue_kind": self.queue_kind,
            "required_evidence": self.required_evidence,
            "success_criteria": self.success_criteria,
            "queueable": self.queueable,
        }
        if self.tool_improvement is not None:
            data["tool_improvement"] = dict(self.tool_improvement)
        return data


def summarize_findings(findings: list[SemanticFinding]) -> dict[str, Any]:
    by_severity = {severity: 0 for severity in ["info", "warning", "error"]}
    by_action = {action: 0 for action in sorted(ACTIONS)}
    by_check: dict[str, int] = {}
    for finding in findings:
        by_severity[finding.severity] += 1
        by_action[finding.action] += 1
        by_check[finding.check] = by_check.get(finding.check, 0) + 1
    return {
        "ok": not findings,
        "count": len(findings),
        "counts": {
            "by_severity": by_severity,
            "by_action": by_action,
            "by_check": dict(sorted(by_check.items())),
        },
        "findings": [finding.to_dict() for finding in findings],
    }


def _now_iso() -> str:
    return datetime.now().astimezone().replace(microsecond=0).isoformat()


def _markdown_cell(value: object) -> str:
    text = "" if value is None else str(value)
    return text.replace("|", r"\|") or "-"


def _link_for_report(path_ref: str) -> str:
    if not path_ref:
        return ""
    if "://" in path_ref:
        return path_ref
    label = path_ref
    return f"[{label}](../{path_ref})"


def _file_links(files: list[str]) -> str:
    if not files:
        return "-"
    return "<br>".join(_link_for_report(path) for path in files[:5])


def render_findings_report(
    *,
    title: str,
    description: str,
    findings: list[SemanticFinding],
    generated_at: str | None = None,
) -> str:
    summary = summarize_findings(findings)
    counts = summary["counts"]
    lines = [
        f"# {title}",
        "",
        f"Generated: {generated_at or _now_iso()}",
        "",
        description,
        "",
        "Semantic lint and evals are deterministic safety checks. They can surface stale, "
        "ungrounded, incomplete, or weakly linked artifacts; they cannot prove that a "
        "scientific claim is correct.",
        "",
        "## Summary",
        "",
        *_markdown_table(
            ["Metric", "Count"],
            [
                ["Findings", summary["count"]],
                ["Info", counts["by_severity"].get("info", 0)],
                ["Warnings", counts["by_severity"].get("warning", 0)],
                ["Errors", counts["by_severity"].get("error", 0)],
            ],
            empty="No findings.",
        ),
        "",
        "## Findings",
        "",
        *_markdown_table(
            ["Severity", "Action", "Check", "Finding", "Files"],
            [
                [
                    finding.severity,
                    finding.action,
                    finding.check,
                    f"{finding.title}<br>{finding.message}<br>`{finding.id}`",
                    _file_links(finding.files),
                ]
                for finding in findings
            ],
            empty="No findings.",
        ),
        "",
    ]
    return "\n".join(lines)


def write_findings_report(
    paths: VaultPaths,
    *,
    filename: str,
    title: str,
    description: str,
    findings: list[SemanticFinding],
) -> dict[str, Any]:
    path = paths.indexes / filename
    before = path.read_text(encoding="utf-8") if path.exists() else None
    text = render_findings_report(title=title, description=description, findings=findings)
    write_text(path, text)
    return {
        "path": ensure_relative(path, paths.vault),
        "changed": before != path.read_text(encoding="utf-8"),
    }


def write_finding_queue_items(
    paths: VaultPaths,
    findings: list[SemanticFinding],
    *,
    created_by: str,
) -> dict[str, Any]:
    from .self_improvement import create_queue_item, write_self_improvement_dashboard

    created = 0
    unchanged = 0
    skipped = 0
    errors: list[dict[str, str]] = []
    items: list[dict[str, Any]] = []
    queueable = [
        finding
        for finding in findings
        if finding.action != "report_only" and finding.queueable
    ]
    for finding in queueable:
        notes = [
            f"Semantic finding `{finding.id}`.",
            finding.message,
            f"Check: {finding.check}; severity: {finding.severity}; action: {finding.action}.",
        ]
        if finding.details:
            notes.append(
                "Details: "
                + json.dumps(finding.details, ensure_ascii=False, sort_keys=True)
            )
        try:
            summary = create_queue_item(
                paths.vault,
                kind=finding.queue_kind,
                title=finding.title,
                created_by=created_by,
                files=finding.files,
                citekeys=finding.citekeys,
                runs=finding.runs,
                required_evidence=finding.required_evidence,
                success_criteria=finding.success_criteria,
                notes="\n\n".join(notes),
                stable_key=finding.id,
                tool_improvement=finding.tool_improvement,
                refresh_dashboard=False,
            )
        except Exception as exc:  # pragma: no cover - exercised through malformed vault state.
            errors.append({"finding_id": finding.id, "error": str(exc)})
            continue
        created += int(bool(summary.get("created")))
        unchanged += int(not summary.get("created"))
        items.append(
            {
                "id": summary["id"],
                "created": summary["created"],
                "queue_item": summary["queue_item"],
                "stable_key": finding.id,
            }
        )
    skipped = len(findings) - len(queueable)
    dashboard = None
    if items:
        try:
            dashboard = write_self_improvement_dashboard(paths.vault)
        except Exception as exc:  # pragma: no cover - malformed queue state fallback.
            errors.append({"finding_id": "self-improvement-dashboard", "error": str(exc)})
    return {
        "requested": True,
        "created": created,
        "unchanged": unchanged,
        "skipped": skipped,
        "errors": errors,
        "items": items,
        "dashboard": dashboard,
    }
