from __future__ import annotations

import os
from pathlib import Path

from scholar_vault.skill_sync import (
    adopt_skill,
    compare_skillsets,
    format_skillset_summary,
    publish_skillset,
)


def _write_skill(root: Path, name: str, body: str) -> None:
    skill = root / name
    (skill / "agents").mkdir(parents=True, exist_ok=True)
    (skill / "SKILL.md").write_text(body, encoding="utf-8")
    (skill / "agents" / "openai.yaml").write_text(
        "interface:\n  display_name: Test\n",
        encoding="utf-8",
    )


def test_compare_skillsets_reports_changed_and_target_only(tmp_path: Path) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    _write_skill(source, "shared", "repo\n")
    _write_skill(target, "shared", "vault\n")
    _write_skill(target, "vault-only", "new\n")
    (target / ".DS_Store").write_text("ignored", encoding="utf-8")
    _write_skill(target / ".sync-backups" / "20260429-120000-000000", "old", "ignored\n")

    summary = compare_skillsets(source, target)

    assert summary["counts"]["changed"] == 1
    assert summary["counts"]["target_only"] == 1
    rendered = format_skillset_summary(summary)
    assert "shared: changed" in rendered
    assert "vault-only: target-only" in rendered
    assert "Repository source" in rendered
    assert "Vault target" in rendered
    assert "publish source -> target" in rendered
    assert ".DS_Store" not in rendered
    assert ".sync-backups" not in rendered


def test_compare_skillsets_reports_newer_side_from_mtime(tmp_path: Path) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    _write_skill(source, "shared", "repo\n")
    _write_skill(target, "shared", "vault\n")
    os.utime(source / "shared" / "SKILL.md", (2000, 2000))
    os.utime(target / "shared" / "SKILL.md", (1000, 1000))

    summary = compare_skillsets(source, target)
    row = next(item for item in summary["skills"] if item["skill"] == "shared")
    rendered = format_skillset_summary(summary)

    assert row["newer"] == "source"
    assert row["recommendation"] == "publish"
    assert "source-newer=1" in rendered
    assert "repository source appears newer" in rendered


def test_adopt_skill_is_dry_run_by_default_and_copies_with_apply(tmp_path: Path) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    _write_skill(target, "vault-only", "new\n")

    dry_run = adopt_skill(source, target, "vault-only")

    assert dry_run["action"] == "adopt"
    assert not (source / "vault-only").exists()

    applied = adopt_skill(source, target, "vault-only", apply=True)

    assert applied["action"] == "adopted"
    assert (source / "vault-only" / "SKILL.md").read_text(encoding="utf-8") == "new\n"


def test_adopt_existing_changed_skill_requires_force(tmp_path: Path) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    _write_skill(source, "shared", "repo\n")
    _write_skill(target, "shared", "vault\n")

    blocked = adopt_skill(source, target, "shared", apply=True)

    assert blocked["action"] == "blocked"
    assert (source / "shared" / "SKILL.md").read_text(encoding="utf-8") == "repo\n"

    applied = adopt_skill(source, target, "shared", apply=True, force=True)

    assert applied["action"] == "adopted"
    assert "sync-backups" in str(applied["backup"])
    assert (source / "shared" / "SKILL.md").read_text(encoding="utf-8") == "vault\n"


def test_publish_skillset_copies_without_archiving_extra_by_default(tmp_path: Path) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    _write_skill(source, "repo-skill", "repo\n")
    _write_skill(target, "vault-only", "vault\n")

    dry_run = publish_skillset(source, target)

    assert dry_run["copied"] == ["repo-skill"]
    assert dry_run["target_only"] == ["vault-only"]
    assert not (target / "repo-skill").exists()

    applied = publish_skillset(source, target, apply=True)

    assert applied["action"] == "published"
    assert (target / "repo-skill" / "SKILL.md").read_text(encoding="utf-8") == "repo\n"
    assert (target / "vault-only").exists()


def test_publish_skillset_can_archive_target_only_skills(tmp_path: Path) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    _write_skill(source, "repo-skill", "repo\n")
    _write_skill(target, "vault-only", "vault\n")

    applied = publish_skillset(source, target, apply=True, archive_extra=True)

    assert applied["archived"]
    assert not (target / "vault-only").exists()
    assert (target / "repo-skill").exists()
