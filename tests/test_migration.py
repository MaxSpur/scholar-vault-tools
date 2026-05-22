from __future__ import annotations

import json
import re
from pathlib import Path

from typer.testing import CliRunner

from scholar_vault.cli import app
from scholar_vault.sources import dump_frontmatter, read_frontmatter_markdown

BODY_RE = re.compile(r"^---\n.*?\n---(?P<body>\n?.*)\Z", re.DOTALL)


def _older_vault_fixture(tmp_path: Path) -> tuple[Path, Path, str, dict[str, bytes]]:
    vault = tmp_path / "legacy-vault"
    papers = vault / "papers"
    pdfs = vault / "pdfs"
    papers.mkdir(parents=True)
    pdfs.mkdir()
    (vault / "AGENTS.md").write_text(
        "# Custom Vault Guide\n\nKeep this local note.\n",
        encoding="utf-8",
    )
    (pdfs / "legacy.pdf").write_bytes(b"%PDF-1.4 legacy\n")
    paper = papers / "legacy-source.md"
    frontmatter = {
        "citekey": "Legacy2024",
        "title": "Legacy Source",
        "pdf": "pdfs/legacy.pdf",
        "reading_status": "skimmed",
    }
    body = (
        "\n"
        "# Legacy Source\n\n"
        "## Scholar Labs summary\n\n"
        "Canonical scientific prose that must remain byte-for-byte stable.\n\n"
        "## Notes\n\n"
        "- User-written interpretation stays here.\n"
    )
    paper.write_text(f"---\n{dump_frontmatter(frontmatter).strip()}\n---{body}", encoding="utf-8")
    return vault, paper, body, _snapshot(vault)


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _raw_body(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    match = BODY_RE.match(text)
    assert match is not None
    return match.group("body")


def test_migrate_dry_run_reports_all_planned_changes_without_writing(tmp_path: Path) -> None:
    vault, _paper, _body, before = _older_vault_fixture(tmp_path)

    result = CliRunner().invoke(
        app,
        ["migrate", "--vault", str(vault), "--dry-run", "--json"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["applied"] is False
    assert payload["changed"] > 0
    actions = payload["changes_by_action"]
    assert actions["create_directory"] > 0
    assert actions["backfill_paper_frontmatter"] == 1
    assert actions["refresh_generated_output"] > 0
    assert actions["refresh_base"] == 5
    assert actions["log_operation"] == 1
    assert _snapshot(vault) == before

    json_only = CliRunner().invoke(app, ["migrate", "--vault", str(vault), "--json"])

    assert json_only.exit_code == 0, json_only.output
    json_only_payload = json.loads(json_only.output)
    assert json_only_payload["applied"] is False
    assert json_only_payload["changes_by_action"] == actions
    assert _snapshot(vault) == before


def test_migrate_apply_is_idempotent_and_preserves_canonical_prose(tmp_path: Path) -> None:
    vault, paper, original_body, _before = _older_vault_fixture(tmp_path)

    first = CliRunner().invoke(
        app,
        ["migrate", "--vault", str(vault), "--apply", "--json"],
    )

    assert first.exit_code == 0, first.output
    first_payload = json.loads(first.output)
    assert first_payload["applied"] is True
    assert first_payload["changed"] > 0
    assert first_payload["changes_by_action"]["backfill_paper_frontmatter"] == 1
    assert first_payload["changes_by_action"]["refresh_base"] == 5
    assert (
        first_payload["changes_by_action"]["refresh_generated_output"]
        == first_payload["generated"]["changed"]
    )
    assert first_payload["changes_by_action"]["log_operation"] == 1
    assert first_payload["operation"]["record"]["kind"] == "vault_migration"
    assert first_payload["checks"]["compile_doctor"]["ok"] is True
    assert first_payload["checks"]["bases_doctor"]["ok"] is True
    assert first_payload["checks"]["lint_wiki"]["ok"] is True
    assert (vault / "paper-digests").is_dir()
    assert (vault / "_indexes" / "dashboard.md").exists()
    assert (vault / "bases" / "papers.base").exists()
    assert (vault / "_operations" / "log.md").exists()
    assert (vault / "AGENTS.md").read_text(encoding="utf-8") == (
        "# Custom Vault Guide\n\nKeep this local note.\n"
    )

    frontmatter, body = read_frontmatter_markdown(paper)
    assert _raw_body(paper) == original_body
    assert body == original_body.lstrip("\n")
    assert frontmatter["reading_status"] == "skimmed"
    assert frontmatter["compiled_status"] == "uncompiled"
    assert frontmatter["review_status"] == "unreviewed"
    assert frontmatter["linked_queries"] == []
    assert frontmatter["enrichment_refresh"] is False

    snapshot_after_first = _snapshot(vault)
    second = CliRunner().invoke(
        app,
        ["migrate", "--vault", str(vault), "--apply", "--json"],
    )

    assert second.exit_code == 0, second.output
    second_payload = json.loads(second.output)
    assert second_payload["changed"] == 0
    assert second_payload["changes_by_action"] == {}
    assert _snapshot(vault) == snapshot_after_first
    assert second_payload["checks"]["bases_doctor"]["ok"] is True
