from __future__ import annotations

import json
from datetime import datetime

import yaml
from typer.testing import CliRunner

from scholar_vault.cli import app
from scholar_vault.importer import _save_card, initialize_vault
from scholar_vault.maintenance import maintenance_report
from scholar_vault.models import FeedbackRecord, OperationRecord, QueueItem, SourceCard
from scholar_vault.schema import export_schema
from scholar_vault.self_improvement import (
    create_queue_item,
    doctor_feedback,
    doctor_operations,
    doctor_queue,
    feedback_report,
    log_operation,
    rate_feedback,
    write_self_improvement_dashboard,
)


def _yaml(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_self_improvement_records_validate_and_dashboard_is_deterministic(tmp_path) -> None:
    vault = tmp_path / "vault"
    paths = initialize_vault(vault)

    queue = create_queue_item(
        vault,
        kind="compile_paper",
        title="Compile Source2026 digest",
        citekeys=["Source2026"],
        required_evidence="pdf",
        success_criteria="Digest is PDF-grounded and reviewed.",
    )
    operation = log_operation(
        vault,
        kind="queue-test",
        message="Created queue record.",
        linked_queue_items=[queue["id"]],
        checks_run=["pytest tests/test_self_improvement.py"],
    )
    feedback = rate_feedback(
        vault,
        "paper-digests/Source2026.md",
        verdict="needs_fix",
        target_type="paper_digest",
        notes="Digest is missing the evidence notes section.",
        linked_operation=operation["operation_id"],
        linked_queue_item=queue["id"],
    )

    QueueItem.model_validate(_yaml(paths.task_queue / f"{queue['id']}.yaml"))
    OperationRecord.model_validate(
        _yaml(paths.operation_runs / f"{operation['operation_id']}.yaml")
    )
    FeedbackRecord.model_validate(_yaml(paths.feedback_ratings / f"{feedback['id']}.yaml"))

    fixed_now = datetime.fromisoformat("2026-05-15T12:00:00+02:00")
    first = write_self_improvement_dashboard(vault, now=fixed_now)
    snapshot = (paths.indexes / "self-improvement.md").read_text(encoding="utf-8")
    second = write_self_improvement_dashboard(vault, now=fixed_now)

    assert first["dashboard"] == "_indexes/self-improvement.md"
    assert second["changed"] is False
    assert (paths.indexes / "self-improvement.md").read_text(encoding="utf-8") == snapshot
    assert "Open queue items by kind" in snapshot
    assert "Feedback needing action" in snapshot
    assert doctor_queue(vault)["ok"] is True
    assert doctor_operations(vault)["ok"] is True
    assert doctor_feedback(vault)["ok"] is True


def test_queue_operations_feedback_and_tools_task_cli(tmp_path) -> None:
    vault = tmp_path / "vault"
    initialize_vault(vault)
    runner = CliRunner()

    added = runner.invoke(
        app,
        [
            "queue",
            "add",
            "--vault",
            str(vault),
            "--kind",
            "discover_sources",
            "--title",
            "Find source PDFs",
            "--required-evidence",
            "web",
            "--json",
        ],
    )
    assert added.exit_code == 0, added.output
    queue_payload = json.loads(added.output)
    queue_id = queue_payload["id"]

    listed = runner.invoke(app, ["queue", "list", "--vault", str(vault), "--json"])
    shown = runner.invoke(app, ["queue", "show", queue_id, "--vault", str(vault), "--json"])
    closed = runner.invoke(
        app,
        [
            "queue",
            "close",
            queue_id,
            "--vault",
            str(vault),
            "--status",
            "done",
            "--notes",
            "Handled in test.",
            "--json",
        ],
    )
    queue_doctor = runner.invoke(app, ["queue", "doctor", "--vault", str(vault), "--json"])

    assert listed.exit_code == 0, listed.output
    assert shown.exit_code == 0, shown.output
    assert closed.exit_code == 0, closed.output
    assert queue_doctor.exit_code == 0, queue_doctor.output
    assert json.loads(listed.output)["items"][0]["id"] == queue_id
    assert json.loads(shown.output)["item"]["kind"] == "discover_sources"
    assert json.loads(closed.output)["item"]["status"] == "done"
    assert json.loads(queue_doctor.output)["ok"] is True

    op = runner.invoke(
        app,
        [
            "operations",
            "log",
            "--vault",
            str(vault),
            "--kind",
            "test",
            "--message",
            "Logged from CLI.",
            "--queue-item",
            queue_id,
            "--json",
        ],
    )
    assert op.exit_code == 0, op.output
    operation_id = json.loads(op.output)["operation_id"]
    op_list = runner.invoke(app, ["operations", "list", "--vault", str(vault), "--json"])
    op_show = runner.invoke(
        app,
        ["operations", "show", operation_id, "--vault", str(vault), "--json"],
    )
    op_doctor = runner.invoke(app, ["operations", "doctor", "--vault", str(vault), "--json"])

    assert op_list.exit_code == 0, op_list.output
    assert op_show.exit_code == 0, op_show.output
    assert op_doctor.exit_code == 0, op_doctor.output
    assert json.loads(op_show.output)["record"]["outputs"]["message"] == "Logged from CLI."
    assert json.loads(op_doctor.output)["ok"] is True

    rated = runner.invoke(
        app,
        [
            "feedback",
            "rate",
            "scholar-vault queue add",
            "--vault",
            str(vault),
            "--verdict",
            "needs_fix",
            "--target-type",
            "tool_behavior",
            "--notes",
            "The command needs a clearer duplicate warning.",
            "--json",
        ],
    )
    assert rated.exit_code == 0, rated.output
    feedback_id = json.loads(rated.output)["id"]
    feedback_list = runner.invoke(app, ["feedback", "list", "--vault", str(vault), "--json"])
    feedback_report_result = runner.invoke(
        app,
        ["feedback", "report", "--vault", str(vault), "--json"],
    )
    feedback_doctor = runner.invoke(app, ["feedback", "doctor", "--vault", str(vault), "--json"])
    tools_task = runner.invoke(
        app,
        [
            "tools-task",
            "create",
            "--vault",
            str(vault),
            "--title",
            "Improve queue duplicate warning",
            "--from-feedback",
            feedback_id,
            "--expected-behavior",
            "Duplicate queue requests explain the stable key reuse.",
            "--test",
            "CLI duplicate stable-key coverage",
            "--json",
        ],
    )

    assert feedback_list.exit_code == 0, feedback_list.output
    assert feedback_report_result.exit_code == 0, feedback_report_result.output
    assert feedback_doctor.exit_code == 0, feedback_doctor.output
    assert tools_task.exit_code == 0, tools_task.output
    assert json.loads(feedback_report_result.output)["needing_action"][0]["id"] == feedback_id
    assert json.loads(tools_task.output)["item"]["kind"] == "improve_tool"
    assert json.loads(tools_task.output)["item"]["tool_improvement"]["target_repo"] == (
        "scholar-vault-tools"
    )


def test_maintenance_report_write_queue_is_idempotent_and_preserves_papers(tmp_path) -> None:
    vault = tmp_path / "vault"
    paths = initialize_vault(vault)
    (paths.pdfs / "source.pdf").write_bytes(b"%PDF-1.4 source\n")
    _save_card(
        paths,
        SourceCard(
            slug="source",
            citekey="Source2026",
            title="Source Paper",
            pdf="pdfs/source.pdf",
            pdf_status="attached",
        ),
    )
    paper_path = paths.papers / "source.md"
    paper_before = paper_path.read_text(encoding="utf-8")

    first = maintenance_report(vault, write_queue=True, report_date="2026-05-15")
    second = maintenance_report(vault, write_queue=True, report_date="2026-05-15")
    queue_files = sorted(paths.task_queue.glob("*.yaml"))
    stable_keys = [QueueItem.model_validate(_yaml(path)).stable_key for path in queue_files]

    assert first["queue"]["created"] >= 1
    assert second["queue"]["created"] == 0
    assert len(stable_keys) == len(set(stable_keys))
    assert paper_path.read_text(encoding="utf-8") == paper_before
    assert first["paper_cards_modified"] == 0
    assert second["paper_cards_modified"] == 0


def test_queue_and_feedback_report_do_not_modify_paper_cards(tmp_path) -> None:
    vault = tmp_path / "vault"
    paths = initialize_vault(vault)
    _save_card(paths, SourceCard(slug="source", citekey="Source2026", title="Source Paper"))
    paper_path = paths.papers / "source.md"
    paper_before = paper_path.read_text(encoding="utf-8")

    create_queue_item(vault, kind="lint_fix", title="Check generated dashboard")
    rate_feedback(
        vault,
        "tool behavior",
        verdict="needs_fix",
        target_type="tool_behavior",
        notes="The report should be clearer.",
    )
    report = feedback_report(vault)

    assert report["needing_action"]
    assert paper_path.read_text(encoding="utf-8") == paper_before


def test_schema_export_includes_self_improvement_and_workbench_schemas(tmp_path) -> None:
    output = tmp_path / "schemas.json"

    payload = export_schema(output)
    cli_result = CliRunner().invoke(app, ["schema", "export", "--json"])

    assert output.exists()
    assert payload["schemas"]["queue_item"]["title"] == "QueueItem"
    assert "operation_record" in payload["schemas"]
    assert "feedback_record" in payload["schemas"]
    assert "prompt_pack" in payload["schemas"]
    assert "discovery_candidate" in payload["schemas"]
    assert "paper_digest" in payload["schemas"]
    assert "eval_spec" in payload["schemas"]
    assert cli_result.exit_code == 0, cli_result.output
    assert "queue_item" in json.loads(cli_result.output)["schemas"]
