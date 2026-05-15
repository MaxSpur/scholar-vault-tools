from __future__ import annotations

from pathlib import Path

import typer

from .cli_common import (
    ApplyArg,
    ArchiveExtraArg,
    BackupArg,
    ExternalSkillsCheckoutArg,
    ExternalSkillSourceNameArg,
    ExternalSkillsRefArg,
    ExternalSkillsRepositoryArg,
    ExternalSkillsSubdirArg,
    ForceArg,
    JsonOutputArg,
    ObsidianSkillsCheckoutArg,
    ObsidianSkillsRefArg,
    ObsidianSkillsRepositoryArg,
    SkillNameArg,
    SkillSourceArg,
    SkillTargetArg,
    UiArg,
    VaultArg,
    _call_root_gui,
    _resolve_vault,
    console,
)
from .skill_sync import (
    OBSIDIAN_SKILLS_DEFAULT_REF,
    OBSIDIAN_SKILLS_REPOSITORY,
    adopt_skill,
    compare_skillsets,
    default_source_agents_path,
    default_source_skills_path,
    format_skillset_summary,
    install_external_skill_source,
    publish_skillset,
    resolve_external_skill_source,
    vault_agents_path,
    vault_skills_path,
)

skills_app = typer.Typer(
    help="Compare, adopt, publish, and install vault-agent Codex skills."
)


def _resolve_skill_paths(
    *,
    source: Path | None,
    target: Path | None,
    vault: Path | None,
) -> tuple[Path, Path]:
    source_path = source.expanduser().resolve() if source else default_source_skills_path()
    if target:
        target_path = target.expanduser().resolve()
    else:
        resolved_vault = _resolve_vault(vault)
        target_path = vault_skills_path(resolved_vault)
    return source_path, target_path


def _resolve_skill_target_path(*, target: Path | None, vault: Path | None) -> Path:
    if target:
        return target.expanduser().resolve()
    return vault_skills_path(_resolve_vault(vault))


def _target_agents_path_from_skills(target: Path) -> Path | None:
    if target.name == "skills" and target.parent.name == ".agents":
        return target.parent.parent / "AGENTS.md"
    return None


def _resolve_skill_sync_paths(
    *,
    source: Path | None,
    target: Path | None,
    vault: Path | None,
) -> tuple[Path, Path, Path | None, Path | None]:
    source_path, target_path = _resolve_skill_paths(source=source, target=target, vault=vault)
    source_agent_guide = default_source_agents_path()
    if target:
        target_agent_guide = _target_agents_path_from_skills(target_path)
    else:
        target_agent_guide = vault_agents_path(_resolve_vault(vault))
    return source_path, target_path, source_agent_guide, target_agent_guide


def _print_skillset_summary(summary: dict[str, object]) -> None:
    console.print(format_skillset_summary(summary), soft_wrap=True)


def _print_skill_action(summary: dict[str, object]) -> None:
    action = summary.get("action")
    if action == "blocked":
        console.print(f"Blocked: {summary.get('reason')}")
        return
    if summary.get("apply"):
        console.print(f"Applied: {action}")
    else:
        console.print(f"Dry-run: would {action}")
    if summary.get("skill"):
        console.print(f"- Skill: {summary['skill']}")
    if summary.get("from"):
        console.print(f"- From: {summary['from']}")
    if summary.get("to"):
        console.print(f"- To: {summary['to']}")
    if summary.get("copied"):
        console.print(f"- Skills to copy: {', '.join(summary['copied'])}")
    agent_guide = summary.get("agent_guide") or {}
    if agent_guide.get("copied"):
        console.print("- Agent guide: VAULT_AGENTS_TEMPLATE.md -> vault AGENTS.md")
    if summary.get("target_only"):
        console.print(f"- Target-only skills: {', '.join(summary['target_only'])}")
    if summary.get("archived"):
        console.print(f"- Archived: {', '.join(summary['archived'])}")
    if summary.get("backup"):
        console.print(f"- Backup: {summary['backup']}")
    if summary.get("backups"):
        console.print(f"- Backups: {', '.join(summary['backups'])}")


def _print_external_skill_action(summary: dict[str, object]) -> None:
    if summary.get("apply"):
        console.print(f"Applied: {summary.get('action')}")
    else:
        console.print("Dry-run: would install/update external skills")
    console.print(f"- Source: {summary.get('source')} ({summary.get('repository')})")
    console.print(f"- Ref: {summary.get('ref')}")
    if summary.get("commit"):
        console.print(f"- Commit: {summary['commit']}")
    console.print(f"- Target: {summary.get('target')}")
    if summary.get("skills"):
        console.print(f"- Skills: {', '.join(summary['skills'])}")
    if summary.get("copied"):
        console.print(f"- Copied: {', '.join(summary['copied'])}")
    if summary.get("manifest"):
        console.print(f"- Manifest: {summary['manifest']}")
    if summary.get("backups"):
        console.print(f"- Backups: {', '.join(summary['backups'])}")


def _show_skill_sync_ui(
    source: Path,
    target: Path,
    *,
    source_agent_guide: Path | None = None,
    target_agent_guide: Path | None = None,
) -> None:
    try:
        from .gui import GuiUnavailable, show_skill_sync
    except Exception as exc:  # pragma: no cover - defensive optional import path
        console.print(f"Skill sync UI unavailable ({exc}). Falling back to terminal output.")
        return
    try:
        _call_root_gui(
            lambda: show_skill_sync(
                source,
                target,
                source_agent_guide=source_agent_guide,
                target_agent_guide=target_agent_guide,
            )
        )
    except GuiUnavailable as exc:
        console.print(f"Skill sync UI unavailable ({exc}). Falling back to terminal output.")


def _skills_install_external(
    *,
    source_name: str,
    vault: Path | None,
    target: Path | None,
    repository: str | None,
    ref: str | None,
    skills_subdir: str | None,
    checkout: Path | None,
    apply: bool,
    backup: bool,
    json_output: bool,
) -> None:
    target_path = _resolve_skill_target_path(target=target, vault=vault)
    try:
        source = resolve_external_skill_source(
            source_name,
            repository=repository,
            ref=ref,
            skills_subdir=skills_subdir,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    summary = install_external_skill_source(
        target_path,
        source,
        apply=apply,
        backup=backup,
        checkout=checkout,
    )
    if json_output:
        console.print_json(data=summary)
        return
    _print_external_skill_action(summary)
    if not apply:
        console.print("Use --apply to install or update these external skills in the vault.")


@skills_app.command("install-external")
def skills_install_external_command(
    source_name: ExternalSkillSourceNameArg,
    vault: VaultArg = None,
    target: SkillTargetArg = None,
    repository: ExternalSkillsRepositoryArg = None,
    ref: ExternalSkillsRefArg = None,
    skills_subdir: ExternalSkillsSubdirArg = None,
    checkout: ExternalSkillsCheckoutArg = None,
    apply: ApplyArg = False,
    backup: BackupArg = True,
    json_output: JsonOutputArg = False,
) -> None:
    _skills_install_external(
        source_name=source_name,
        vault=vault,
        target=target,
        repository=repository,
        ref=ref,
        skills_subdir=skills_subdir,
        checkout=checkout,
        apply=apply,
        backup=backup,
        json_output=json_output,
    )


@skills_app.command("update-external")
def skills_update_external_command(
    source_name: ExternalSkillSourceNameArg,
    vault: VaultArg = None,
    target: SkillTargetArg = None,
    repository: ExternalSkillsRepositoryArg = None,
    ref: ExternalSkillsRefArg = None,
    skills_subdir: ExternalSkillsSubdirArg = None,
    checkout: ExternalSkillsCheckoutArg = None,
    apply: ApplyArg = False,
    backup: BackupArg = True,
    json_output: JsonOutputArg = False,
) -> None:
    _skills_install_external(
        source_name=source_name,
        vault=vault,
        target=target,
        repository=repository,
        ref=ref,
        skills_subdir=skills_subdir,
        checkout=checkout,
        apply=apply,
        backup=backup,
        json_output=json_output,
    )


@skills_app.command("install-obsidian")
def skills_install_obsidian_command(
    vault: VaultArg = None,
    target: SkillTargetArg = None,
    repository: ObsidianSkillsRepositoryArg = OBSIDIAN_SKILLS_REPOSITORY,
    ref: ObsidianSkillsRefArg = OBSIDIAN_SKILLS_DEFAULT_REF,
    checkout: ObsidianSkillsCheckoutArg = None,
    apply: ApplyArg = False,
    backup: BackupArg = True,
    json_output: JsonOutputArg = False,
) -> None:
    _skills_install_external(
        source_name="obsidian-skills",
        vault=vault,
        target=target,
        repository=repository,
        ref=ref,
        skills_subdir=None,
        checkout=checkout,
        apply=apply,
        backup=backup,
        json_output=json_output,
    )


@skills_app.command("update-obsidian")
def skills_update_obsidian_command(
    vault: VaultArg = None,
    target: SkillTargetArg = None,
    repository: ObsidianSkillsRepositoryArg = OBSIDIAN_SKILLS_REPOSITORY,
    ref: ObsidianSkillsRefArg = OBSIDIAN_SKILLS_DEFAULT_REF,
    checkout: ObsidianSkillsCheckoutArg = None,
    apply: ApplyArg = False,
    backup: BackupArg = True,
    json_output: JsonOutputArg = False,
) -> None:
    _skills_install_external(
        source_name="obsidian-skills",
        vault=vault,
        target=target,
        repository=repository,
        ref=ref,
        skills_subdir=None,
        checkout=checkout,
        apply=apply,
        backup=backup,
        json_output=json_output,
    )


@skills_app.command("diff")
def skills_diff_command(
    vault: VaultArg = None,
    source: SkillSourceArg = None,
    target: SkillTargetArg = None,
    json_output: JsonOutputArg = False,
    ui: UiArg = False,
) -> None:
    source_path, target_path, source_agent_guide, target_agent_guide = _resolve_skill_sync_paths(
        source=source, target=target, vault=vault
    )
    if ui:
        _show_skill_sync_ui(
            source_path,
            target_path,
            source_agent_guide=source_agent_guide,
            target_agent_guide=target_agent_guide,
        )
        return
    summary = compare_skillsets(
        source_path,
        target_path,
        source_agent_guide=source_agent_guide,
        target_agent_guide=target_agent_guide,
    )
    if json_output:
        console.print_json(data=summary)
        return
    _print_skillset_summary(summary)


@skills_app.command("adopt")
def skills_adopt_command(
    skill: SkillNameArg,
    vault: VaultArg = None,
    source: SkillSourceArg = None,
    target: SkillTargetArg = None,
    apply: ApplyArg = False,
    force: ForceArg = False,
    backup: BackupArg = True,
    json_output: JsonOutputArg = False,
) -> None:
    source_path, target_path, source_agent_guide, target_agent_guide = _resolve_skill_sync_paths(
        source=source, target=target, vault=vault
    )
    summary = adopt_skill(
        source_path,
        target_path,
        skill,
        apply=apply,
        force=force,
        backup=backup,
        source_agent_guide=source_agent_guide,
        target_agent_guide=target_agent_guide,
    )
    if json_output:
        console.print_json(data=summary)
        return
    _print_skill_action(summary)
    if not apply and summary.get("action") != "blocked":
        console.print("Use --apply to copy the vault target skill into the repository source.")


@skills_app.command("publish")
def skills_publish_command(
    vault: VaultArg = None,
    source: SkillSourceArg = None,
    target: SkillTargetArg = None,
    apply: ApplyArg = False,
    archive_extra: ArchiveExtraArg = False,
    backup: BackupArg = True,
    json_output: JsonOutputArg = False,
) -> None:
    source_path, target_path, source_agent_guide, target_agent_guide = _resolve_skill_sync_paths(
        source=source, target=target, vault=vault
    )
    summary = publish_skillset(
        source_path,
        target_path,
        apply=apply,
        archive_extra=archive_extra,
        backup=backup,
        source_agent_guide=source_agent_guide,
        target_agent_guide=target_agent_guide,
    )
    if json_output:
        console.print_json(data=summary)
        return
    _print_skill_action(summary)
    if not apply:
        console.print("Use --apply to update the vault target from the repository source.")


@skills_app.command("ui")
def skills_ui_command(
    vault: VaultArg = None,
    source: SkillSourceArg = None,
    target: SkillTargetArg = None,
) -> None:
    source_path, target_path, source_agent_guide, target_agent_guide = _resolve_skill_sync_paths(
        source=source, target=target, vault=vault
    )
    _show_skill_sync_ui(
        source_path,
        target_path,
        source_agent_guide=source_agent_guide,
        target_agent_guide=target_agent_guide,
    )
