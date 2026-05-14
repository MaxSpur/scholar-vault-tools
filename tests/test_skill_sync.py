from __future__ import annotations

import json
import os
from pathlib import Path

from scholar_vault.skill_sync import (
    AGENTS_GUIDE_ITEM,
    adopt_skill,
    compare_skillsets,
    default_source_skills_path,
    format_skillset_summary,
    install_obsidian_skills,
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


def _write_external_skill(checkout: Path, name: str, body: str) -> None:
    skill = checkout / "skills" / name
    skill.mkdir(parents=True, exist_ok=True)
    (skill / "SKILL.md").write_text(body, encoding="utf-8")


def test_default_source_skills_path_is_vault_agent_source() -> None:
    source = default_source_skills_path()

    assert source.name == "vault-agent-skills"
    assert ".agents" not in source.parts
    assert (source / "scholar-vault-orient" / "SKILL.md").is_file()


def test_compare_skillsets_ignores_nested_upstream_checkout(tmp_path: Path) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    _write_external_skill(source, "obsidian-markdown", "upstream\n")

    summary = compare_skillsets(source, target)

    assert summary["counts"]["source_only"] == 0
    assert summary["skills"] == []


def test_compare_skillsets_ignores_manifested_external_target_skills(tmp_path: Path) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    _write_skill(target, "obsidian-markdown", "upstream\n")
    manifest = target / ".external-sources" / "obsidian-skills.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps({"skills": ["obsidian-markdown"], "repository": "https://example.test"}),
        encoding="utf-8",
    )

    summary = compare_skillsets(source, target)
    rendered = format_skillset_summary(summary)

    assert summary["counts"]["target_only"] == 0
    assert summary["external_skills"]["target"] == ["obsidian-markdown"]
    assert "External target skills managed upstream" in rendered
    assert "obsidian-markdown: target-only" not in rendered


def test_install_obsidian_skills_from_checkout_writes_target_and_manifest(tmp_path: Path) -> None:
    checkout = tmp_path / "upstream"
    target = tmp_path / "target"
    _write_external_skill(checkout, "obsidian-markdown", "new\n")
    _write_external_skill(checkout, "json-canvas", "canvas\n")
    _write_skill(target, "obsidian-markdown", "old\n")

    dry_run = install_obsidian_skills(target, checkout=checkout)

    assert dry_run["action"] == "install-external"
    assert dry_run["skills"] == ["json-canvas", "obsidian-markdown"]
    assert (target / "obsidian-markdown" / "SKILL.md").read_text(encoding="utf-8") == "old\n"

    applied = install_obsidian_skills(target, checkout=checkout, apply=True)
    manifest = json.loads(
        (target / ".external-sources" / "obsidian-skills.json").read_text(encoding="utf-8")
    )
    summary = compare_skillsets(tmp_path / "empty-source", target)

    assert applied["action"] == "installed-external"
    assert applied["copied"] == ["json-canvas", "obsidian-markdown"]
    assert "sync-backups" in applied["backups"][0]
    assert (target / "obsidian-markdown" / "SKILL.md").read_text(encoding="utf-8") == "new\n"
    assert (target / "json-canvas" / "SKILL.md").read_text(encoding="utf-8") == "canvas\n"
    assert not (target / "skills").exists()
    assert manifest["repository"].endswith("kepano/obsidian-skills.git")
    assert manifest["skills"] == ["json-canvas", "obsidian-markdown"]
    assert summary["counts"]["target_only"] == 0


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


def test_publish_skillset_can_copy_selected_skills_only(tmp_path: Path) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    _write_skill(source, "copy-me", "repo\n")
    _write_skill(source, "skip-me", "repo\n")

    applied = publish_skillset(source, target, apply=True, skills=["copy-me"])

    assert applied["copied"] == ["copy-me"]
    assert (target / "copy-me" / "SKILL.md").exists()
    assert not (target / "skip-me").exists()


def test_publish_skillset_can_archive_target_only_skills(tmp_path: Path) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    _write_skill(source, "repo-skill", "repo\n")
    _write_skill(target, "vault-only", "vault\n")

    applied = publish_skillset(source, target, apply=True, archive_extra=True)

    assert applied["archived"]
    assert not (target / "vault-only").exists()
    assert (target / "repo-skill").exists()


def test_compare_skillsets_can_include_vault_agents_guide(tmp_path: Path) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    _write_skill(source, "shared", "repo\n")
    _write_skill(target, "shared", "repo\n")
    source_agents = tmp_path / "VAULT_AGENTS_TEMPLATE.md"
    target_agents = tmp_path / "vault" / "AGENTS.md"
    source_agents.write_text("repo guide\n", encoding="utf-8")
    target_agents.parent.mkdir(parents=True)
    target_agents.write_text("vault guide\n", encoding="utf-8")

    summary = compare_skillsets(
        source,
        target,
        source_agent_guide=source_agents,
        target_agent_guide=target_agents,
    )
    rendered = format_skillset_summary(summary)

    assert summary["counts"]["identical"] == 1
    assert summary["agent_guide"]["status"] == "changed"
    assert summary["agent_guide"]["skill"] == AGENTS_GUIDE_ITEM
    assert "AGENTS.md: changed" in rendered
    assert "VAULT_AGENTS_TEMPLATE.md" in rendered


def test_publish_skillset_can_copy_vault_agents_guide(tmp_path: Path) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    source_agents = tmp_path / "VAULT_AGENTS_TEMPLATE.md"
    target_agents = tmp_path / "vault" / "AGENTS.md"
    source_agents.write_text("repo guide\n", encoding="utf-8")
    target_agents.parent.mkdir(parents=True)
    target_agents.write_text("vault guide\n", encoding="utf-8")

    dry_run = publish_skillset(
        source,
        target,
        source_agent_guide=source_agents,
        target_agent_guide=target_agents,
    )
    applied = publish_skillset(
        source,
        target,
        apply=True,
        source_agent_guide=source_agents,
        target_agent_guide=target_agents,
    )

    assert dry_run["agent_guide"]["copied"] is True
    assert target_agents.read_text(encoding="utf-8") == "repo guide\n"
    assert applied["agent_guide"]["copied"] is True
    assert applied["backups"]


def test_adopt_skill_can_copy_vault_agents_guide_with_force(tmp_path: Path) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    source_agents = tmp_path / "VAULT_AGENTS_TEMPLATE.md"
    target_agents = tmp_path / "vault" / "AGENTS.md"
    source_agents.write_text("repo guide\n", encoding="utf-8")
    target_agents.parent.mkdir(parents=True)
    target_agents.write_text("vault guide\n", encoding="utf-8")

    blocked = adopt_skill(
        source,
        target,
        AGENTS_GUIDE_ITEM,
        apply=True,
        source_agent_guide=source_agents,
        target_agent_guide=target_agents,
    )
    assert blocked["action"] == "blocked"
    assert source_agents.read_text(encoding="utf-8") == "repo guide\n"

    applied = adopt_skill(
        source,
        target,
        AGENTS_GUIDE_ITEM,
        apply=True,
        force=True,
        source_agent_guide=source_agents,
        target_agent_guide=target_agents,
    )

    assert applied["action"] == "adopted"
    assert source_agents.read_text(encoding="utf-8") == "vault guide\n"
    assert applied["agent_guide"]["copied"] is True
    assert applied["backup"]
