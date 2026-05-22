from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import yaml
from typer.testing import CliRunner

from scholar_vault import autopilot
from scholar_vault.cli import app
from scholar_vault.importer import initialize_vault

runner = CliRunner()


def _session_files(vault: Path) -> list[Path]:
    return sorted(
        path
        for path in (vault / "_sessions").glob("*.yaml")
        if path.name != "current.yaml"
    )


def test_ask_creates_reusable_session_and_prompt_pack_with_copy_open(
    tmp_path: Path,
    monkeypatch,
) -> None:
    vault = tmp_path / "vault"
    initialize_vault(vault)
    copied: list[str] = []
    opened: list[bool] = []

    def fake_copy(text: str) -> str:
        copied.append(text)
        return "test-copy"

    def fake_open() -> bool:
        opened.append(True)
        return True

    monkeypatch.setattr(autopilot, "_copy_to_clipboard", fake_copy)
    monkeypatch.setattr(autopilot, "_open_scholar", fake_open)

    result = runner.invoke(
        app,
        [
            "ask",
            "--vault",
            str(vault),
            "--copy",
            "--open-scholar",
            "How do maps distort movement?",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "For the research focus 'How do maps distort movement?'" in result.output
    assert "Next: Run this prompt manually in Scholar Labs" in result.output
    assert copied and "For the research focus" in copied[0]
    assert opened == [True]
    session_files = _session_files(vault)
    assert len(session_files) == 1
    current = yaml.safe_load((vault / "_sessions" / "current.yaml").read_text())
    assert current["status"] == "waiting_for_labs_export"
    assert current["query_path"] == "queries/how-do-maps-distort-movement.md"
    prompt_pack = vault / current["prompt_pack_path"]
    frontmatter = yaml.safe_load(prompt_pack.read_text().split("---", 2)[1])
    assert frontmatter["status"] == "ready"

    second = runner.invoke(
        app,
        ["ask", "--vault", str(vault), "How do maps distort movement?"],
    )

    assert second.exit_code == 0, second.output
    assert len(_session_files(vault)) == 1
    current_after = yaml.safe_load((vault / "_sessions" / "current.yaml").read_text())
    assert current_after["id"] == current["id"]


def test_session_commands_show_list_and_archive_current(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    initialize_vault(vault)
    result = runner.invoke(app, ["ask", "--vault", str(vault), "What evidence is missing?"])
    assert result.exit_code == 0, result.output

    current = runner.invoke(app, ["session", "current", "--vault", str(vault)])
    assert current.exit_code == 0, current.output
    assert "waiting_for_labs_export" in current.output

    listed = runner.invoke(app, ["session", "list", "--vault", str(vault)])
    assert listed.exit_code == 0, listed.output
    assert "missing?" in listed.output

    archived = runner.invoke(app, ["session", "archive", "--vault", str(vault)])
    assert archived.exit_code == 0, archived.output
    assert "archived" in archived.output

    current_after = runner.invoke(app, ["session", "current", "--vault", str(vault)])
    assert current_after.exit_code == 0, current_after.output
    assert "No current active session." in current_after.output


def test_intake_orchestrates_import_scaffold_checks_and_report(
    tmp_path: Path,
    monkeypatch,
) -> None:
    vault = tmp_path / "vault"
    staging = tmp_path / "staging"
    staging.mkdir()
    export = staging / "labs.json"
    export.write_text("{}", encoding="utf-8")
    initialize_vault(vault)
    ask_summary = autopilot.ask(vault, "How should tactile maps be evaluated?")
    calls: dict[str, object] = {}

    def fake_import(vault_path, export_path, staging_path, **kwargs):
        calls["import"] = {
            "vault": vault_path,
            "export": export_path,
            "staging": staging_path,
            **kwargs,
        }
        return {
            "run": "20260522_tactile-maps",
            "selected": 2,
            "matched": 2,
            "unmatched": 0,
            "decision_summary": {
                "commit_proposals_skipped": 0,
                "export_results": 2,
            },
        }

    def fake_scaffold(vault_path, **kwargs):
        calls["scaffold"] = {"vault": vault_path, **kwargs}
        return {"changed": 2, "count": 2}

    def fake_checks(paths, **kwargs):
        calls["checks"] = {"paths": paths, **kwargs}
        return {"compile_doctor": {"ok": True}, "bases_doctor": {"ok": True}}

    monkeypatch.setattr(autopilot, "import_scholar_labs_run", fake_import)
    monkeypatch.setattr(autopilot, "compile_scaffold", fake_scaffold)
    monkeypatch.setattr(autopilot, "_run_quality_checks", fake_checks)

    summary = autopilot.intake(vault, export=export, staging=staging)

    assert summary["session"]["status"] == "imported"
    assert summary["session"]["run_id"] == "20260522_tactile-maps"
    assert calls["import"]["commit"] is True  # type: ignore[index]
    assert calls["import"]["archive_matched"] is True  # type: ignore[index]
    assert calls["import"]["prompt_pack"] == ask_summary["prompt_pack"]  # type: ignore[index]
    assert calls["import"]["query"] == "how-should-tactile-maps-be-evaluated"  # type: ignore[index]
    assert calls["scaffold"]["run_id"] == "20260522_tactile-maps"  # type: ignore[index]
    assert calls["scaffold"]["selected_only"] is True  # type: ignore[index]
    assert (vault / summary["report"]["path"]).exists()
    assert "20260522_tactile-maps" in (vault / "_sessions" / "current.yaml").read_text()


def test_intake_can_bootstrap_session_from_export_prompt(
    tmp_path: Path,
    monkeypatch,
) -> None:
    vault = tmp_path / "vault"
    staging = tmp_path / "staging"
    staging.mkdir()
    export = staging / "labs.json"
    export.write_text(
        """
{
  "schema_version": "0.2",
  "source": "google_scholar_labs",
  "exported_at": "2026-05-22T12:00:00Z",
  "prompt": "Find papers that measure budgerigar vocal acoustics for synthesis.",
  "results": [
    {
      "rank": 1,
      "title": "Mechanisms of vocal production in budgerigars",
      "authors_preview": "EF Brittan-Powell, RJ Dooling",
      "year": 1997,
      "summary": "Measured contact calls."
    }
  ]
}
""".strip(),
        encoding="utf-8",
    )
    initialize_vault(vault)
    calls: dict[str, object] = {}

    def fake_import(vault_path, export_path, staging_path, **kwargs):
        calls["import"] = {
            "vault": vault_path,
            "export": export_path,
            "staging": staging_path,
            **kwargs,
        }
        return {
            "run": "20260522_budgerigar-vocal-acoustics",
            "selected": 1,
            "matched": 1,
            "unmatched": 0,
            "decision_summary": {"commit_proposals_skipped": 0},
        }

    monkeypatch.setattr(autopilot, "import_scholar_labs_run", fake_import)
    monkeypatch.setattr(autopilot, "compile_scaffold", lambda *args, **kwargs: {})
    monkeypatch.setattr(autopilot, "_run_quality_checks", lambda *args, **kwargs: {})

    summary = autopilot.intake(
        vault,
        export=export,
        staging=staging,
        project="budgie-vocoder",
        slug="budgie-scan",
        question="Which acoustic evidence supports a budgerigar synthesizer?",
    )

    assert summary["session"]["status"] == "imported"
    assert summary["session"]["project"] == "budgie-vocoder"
    assert summary["session"]["query_path"] == "queries/budgie-scan.md"
    assert calls["import"]["query"] == "budgie-scan"  # type: ignore[index]
    prompt_pack = calls["import"]["prompt_pack"]  # type: ignore[index]
    assert isinstance(prompt_pack, str)
    assert prompt_pack.startswith("queries/budgie-scan/prompt-packs/")
    assert "budgie-vocoder" in (vault / "queries" / "budgie-scan.md").read_text()
    assert "Find papers that measure budgerigar vocal acoustics" in (
        vault / prompt_pack
    ).read_text()
    assert len(_session_files(vault)) == 1

    second = autopilot.intake(
        vault,
        export=export,
        staging=staging,
        project="budgie-vocoder",
        slug="budgie-scan",
        question="Which acoustic evidence supports a budgerigar synthesizer?",
    )

    assert second["session"]["id"] == summary["session"]["id"]
    assert len(_session_files(vault)) == 1


def test_intake_pdf_only_imports_links_and_scaffolds(
    tmp_path: Path,
    monkeypatch,
) -> None:
    vault = tmp_path / "vault"
    staging = tmp_path / "staging"
    staging.mkdir()
    initialize_vault(vault)
    calls: dict[str, list[object]] = {
        "query": [],
        "project": [],
        "scaffold": [],
    }

    monkeypatch.setattr(
        autopilot,
        "import_pdf_dropins",
        lambda *args, **kwargs: {
            "imported": 1,
            "created": 1,
            "updated_existing": 0,
            "pdfs": [
                {
                    "citekey": "brittanpowell1997mechanisms",
                    "paper": "papers/brittanpowell1997mechanisms.md",
                    "title": "Mechanisms of vocal production in budgerigars",
                    "pdf": "pdfs/brittanpowell1997mechanisms.pdf",
                }
            ],
        },
    )

    def fake_query_link(vault_path, query_slug, citekey):
        calls["query"].append((vault_path, query_slug, citekey))
        return {"changed": True}

    def fake_project_link(vault_path, project_slug, citekey):
        calls["project"].append((vault_path, project_slug, citekey))
        return {"changed": True}

    def fake_scaffold(vault_path, **kwargs):
        calls["scaffold"].append((vault_path, kwargs))
        return {"changed": 1, "count": 1}

    monkeypatch.setattr(autopilot, "query_link_paper", fake_query_link)
    monkeypatch.setattr(autopilot, "project_link_paper", fake_project_link)
    monkeypatch.setattr(autopilot, "compile_scaffold", fake_scaffold)
    monkeypatch.setattr(autopilot, "_run_quality_checks", lambda *args, **kwargs: {})

    summary = autopilot.intake(
        vault,
        staging=staging,
        question="Which acoustic evidence supports a budgerigar synthesizer?",
        project="budgie-vocoder",
        slug="budgie-pdf-seed",
        pdf_only=True,
    )

    assert summary["pdf_only"] is True
    assert summary["session"]["status"] == "imported"
    assert summary["session"]["query_path"] == "queries/budgie-pdf-seed.md"
    assert calls["query"] == [(vault, "budgie-pdf-seed", "brittanpowell1997mechanisms")]
    assert calls["project"] == [(vault, "budgie-vocoder", "brittanpowell1997mechanisms")]
    assert calls["scaffold"][0][1] == {"citekey": "brittanpowell1997mechanisms"}


def test_labs_intake_links_selected_run_and_papers_to_project(
    tmp_path: Path,
    monkeypatch,
) -> None:
    vault = tmp_path / "vault"
    staging = tmp_path / "staging"
    staging.mkdir()
    export = staging / "labs.json"
    export.write_text(
        """
{
  "schema_version": "0.2",
  "source": "google_scholar_labs",
  "exported_at": "2026-05-22T12:00:00Z",
  "prompt": "Find papers about budgerigar vocal production.",
  "results": [{"rank": 1, "title": "Mechanisms of vocal production in budgerigars"}]
}
""".strip(),
        encoding="utf-8",
    )
    initialize_vault(vault)
    calls: dict[str, list[object]] = {"runs": [], "papers": []}

    monkeypatch.setattr(
        autopilot,
        "import_scholar_labs_run",
        lambda *args, **kwargs: {
            "run": "20260522_budgerigar-vocal-production",
            "selected": 1,
            "matched": 1,
            "unmatched": 0,
            "decision_summary": {"commit_proposals_skipped": 0},
        },
    )
    monkeypatch.setattr(autopilot, "compile_scaffold", lambda *args, **kwargs: {})
    monkeypatch.setattr(autopilot, "_run_quality_checks", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        autopilot,
        "load_run_records",
        lambda paths: [
            SimpleNamespace(
                slug="20260522_budgerigar-vocal-production",
                results=[
                    SimpleNamespace(
                        status="selected",
                        paper_card="papers/brittanpowell1997mechanisms.md",
                    )
                ],
            )
        ],
    )
    monkeypatch.setattr(
        autopilot,
        "load_source_cards",
        lambda paths: [
            SimpleNamespace(
                slug="brittanpowell1997mechanisms",
                citekey="brittanpowell1997mechanisms",
            )
        ],
    )

    def fake_project_link_run(vault_path, project_slug, run_id):
        calls["runs"].append((vault_path, project_slug, run_id))
        return {"changed": True}

    def fake_project_link_paper(vault_path, project_slug, citekey):
        calls["papers"].append((vault_path, project_slug, citekey))
        return {"changed": True}

    monkeypatch.setattr(autopilot, "project_link_run", fake_project_link_run)
    monkeypatch.setattr(autopilot, "project_link_paper", fake_project_link_paper)

    summary = autopilot.intake(
        vault,
        export=export,
        staging=staging,
        project="bird-vocoder",
        slug="bird-vocoder-scan-1",
        question="Which papers support a psittacine vocoder?",
        new_session=True,
    )

    assert summary["project_links"]["linked_run"] is True
    assert summary["project_links"]["linked_papers"] == 1
    assert calls["runs"] == [(vault, "bird-vocoder", "20260522_budgerigar-vocal-production")]
    assert calls["papers"] == [(vault, "bird-vocoder", "brittanpowell1997mechanisms")]


def test_start_scaffolds_clean_project_only(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    initialize_vault(vault)

    summary = autopilot.start(
        vault,
        "budgie-vocoder",
        title="Budgerigar Vocoder",
    )

    assert summary["mode"] == "project"
    assert (vault / "projects" / "budgie-vocoder" / "index.md").exists()
    assert summary["project"]["project"] == "projects/budgie-vocoder/index.md"
    assert summary["project"]["state"] in {"created", "updated", "unchanged"}
    assert "intake" in summary["next_step"]
    assert not (vault / "_sessions" / "current.yaml").exists()


def test_intake_marks_session_blocked_for_manual_pdf_matches(
    tmp_path: Path,
    monkeypatch,
) -> None:
    vault = tmp_path / "vault"
    staging = tmp_path / "staging"
    staging.mkdir()
    export = staging / "labs.json"
    export.write_text("{}", encoding="utf-8")
    initialize_vault(vault)
    autopilot.ask(vault, "Which movement papers are missing?")

    monkeypatch.setattr(
        autopilot,
        "import_scholar_labs_run",
        lambda *args, **kwargs: {
            "run": "20260522_movement",
            "selected": 1,
            "matched": 1,
            "unmatched": 1,
            "decision_summary": {"commit_proposals_skipped": 1},
        },
    )
    monkeypatch.setattr(autopilot, "compile_scaffold", lambda *args, **kwargs: {})
    monkeypatch.setattr(autopilot, "_run_quality_checks", lambda *args, **kwargs: {})

    summary = autopilot.intake(vault, export=export, staging=staging)

    assert summary["session"]["status"] == "blocked"
    assert "manual review" in summary["blockers"][0]


def test_intake_does_not_block_on_leftover_shared_staging_pdfs(
    tmp_path: Path,
    monkeypatch,
) -> None:
    vault = tmp_path / "vault"
    staging = tmp_path / "staging"
    staging.mkdir()
    export = staging / "labs.json"
    export.write_text("{}", encoding="utf-8")
    initialize_vault(vault)
    autopilot.ask(vault, "Which bird papers are useful?")

    monkeypatch.setattr(
        autopilot,
        "import_scholar_labs_run",
        lambda *args, **kwargs: {
            "run": "20260522_bird-vocoder",
            "selected": 1,
            "matched": 1,
            "unmatched": 12,
            "decision_summary": {
                "commit_proposals_skipped": 0,
                "results_without_candidate": 8,
            },
        },
    )
    monkeypatch.setattr(autopilot, "compile_scaffold", lambda *args, **kwargs: {})
    monkeypatch.setattr(autopilot, "_run_quality_checks", lambda *args, **kwargs: {})

    summary = autopilot.intake(vault, export=export, staging=staging)

    assert summary["session"]["status"] == "imported"
    assert summary["blockers"] == []


def test_improve_prioritizes_session_queue_and_writes_report(
    tmp_path: Path,
    monkeypatch,
) -> None:
    vault = tmp_path / "vault"
    initialize_vault(vault)
    session = autopilot.ask(vault, "How should movement maps be synthesized?")["session"]
    session["run_id"] = "20260522_maps"
    autopilot.write_session(initialize_vault(vault, rebuild=False), session)
    queue = vault / "tasks" / "queue" / "queue-session.yaml"
    queue.write_text(
        yaml.safe_dump(
            {
                "id": "queue-session",
                "title": "Compile session papers",
                "kind": "compile_paper",
                "status": "open",
                "priority": "normal",
                "created_at": "2026-05-22T10:00:00+02:00",
                "updated_at": "2026-05-22T10:00:00+02:00",
                "created_by": "lint",
                "query": "queries/how-should-movement-maps-be-synthesized.md",
                "citekeys": [],
                "runs": [],
                "files": [],
                "required_evidence": "pdf",
                "success_criteria": "Digest is filled.",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(autopilot, "_run_quality_checks", lambda *args, **kwargs: {})

    summary = autopilot.improve(vault, no_agent=True, budget_papers=1)

    updated_queue = yaml.safe_load(queue.read_text())
    assert summary["session"]["status"] == "improving"
    assert updated_queue["status"] == "planned"
    assert updated_queue["priority"] == "high"
    assert summary["prioritized"]["changed"] == 1
    assert (vault / summary["report"]["path"]).exists()


def test_answer_writes_handoff_without_agent_and_prints_command(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    initialize_vault(vault)
    autopilot.ask(vault, "What should the synthesis answer?")

    result = runner.invoke(
        app,
        ["answer", "--vault", str(vault), "What evidence supports the synthesis?"],
    )

    assert result.exit_code == 0, result.output
    assert result.output.strip().startswith("codex exec -C")
    handoffs = sorted((vault / "_handoffs").glob("*.md"))
    assert len(handoffs) == 1
    text = handoffs[0].read_text()
    assert "Before making scientific claims, open and read the linked PDFs" in text
    current = yaml.safe_load((vault / "_sessions" / "current.yaml").read_text())
    assert current["status"] == "waiting_for_labs_export"


def test_answer_can_create_project_scoped_handoff(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    initialize_vault(vault)
    result = runner.invoke(
        app,
        [
            "answer",
            "--vault",
            str(vault),
            "--project",
            "bird-vocoder",
            "--budget-papers",
            "3",
            "How should the dossier model psittacine vocal tracts?",
        ],
    )

    assert result.exit_code == 0, result.output
    handoff = next((vault / "_handoffs").glob("*.md"))
    text = handoff.read_text()
    assert "Project: `projects/bird-vocoder/index.md`" in text
    assert "focus on at most 3 paper(s)" in text
    assert "linked project papers and runs" in text


def test_answer_with_mocked_codex_marks_session_answered(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    initialize_vault(vault)
    autopilot.ask(vault, "What should the synthesis answer?")

    def fake_runner(args: list[str], prompt: str, cwd: Path) -> subprocess.CompletedProcess[str]:
        assert args[:4] == ["codex", "exec", "-C", str(vault)]
        assert "--sandbox" in args
        assert "workspace-write" in args
        assert "Answer this synthesis question" in prompt
        assert cwd == vault
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="ok", stderr="")

    summary = autopilot.answer(
        vault,
        "What evidence supports the synthesis?",
        agent="codex",
        codex_runner=fake_runner,
    )

    assert summary["session"]["status"] == "answered"
    assert summary["codex"]["ok"] is True
    assert (vault / summary["handoff"]["handoff"]).exists()


def test_codex_handoff_and_run_helpers_store_prompts_and_call_codex(
    tmp_path: Path,
    monkeypatch,
) -> None:
    vault = tmp_path / "vault"
    initialize_vault(vault)
    autopilot.ask(vault, "What post import work remains?")
    handoff = autopilot.create_handoff(vault, kind="post-import")
    assert (vault / handoff["handoff"]["handoff"]).exists()

    def fake_run(vault_path: Path, handoff_path: Path, *, runner=None):
        assert vault_path == vault
        assert handoff_path.exists()
        return {"ok": True, "returncode": 0, "stdout": "ok", "stderr": ""}

    monkeypatch.setattr(autopilot, "run_codex_handoff", fake_run)
    ran = autopilot.run_handoff(vault, kind="improve", budget_papers=2)
    assert ran["codex"]["ok"] is True
    assert ran["handoff"]["kind"] == "improve"
