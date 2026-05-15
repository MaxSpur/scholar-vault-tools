from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.table import Table

from .config import configured_path
from .sources import VaultPaths, load_run_records, load_source_cards

console = Console()


def _completion_vault_path(ctx) -> Path | None:
    value = None
    if ctx is not None:
        value = ctx.params.get("vault")
    return value or configured_path("vault")


def _complete_run_ids(ctx, args: list[str], incomplete: str) -> list[str]:
    _ = args
    vault = _completion_vault_path(ctx)
    if vault is None:
        return []
    try:
        paths = VaultPaths.from_root(Path(vault).expanduser().resolve())
        run_ids = [run.slug for run in load_run_records(paths)]
    except Exception:
        return []
    needle = incomplete.casefold()
    return [run_id for run_id in run_ids if run_id.casefold().startswith(needle)]


def _complete_citekeys(ctx, args: list[str], incomplete: str) -> list[str]:
    _ = args
    vault = _completion_vault_path(ctx)
    if vault is None:
        return []
    try:
        paths = VaultPaths.from_root(Path(vault).expanduser().resolve())
        citekeys = [card.citekey for card in load_source_cards(paths) if card.citekey]
    except Exception:
        return []
    needle = incomplete.casefold()
    return [citekey for citekey in citekeys if citekey and citekey.casefold().startswith(needle)]


def _require_configured_path(
    explicit: Path | None,
    key: str,
    *,
    label: str,
    must_be_file: bool = False,
    must_be_dir: bool = True,
) -> Path:
    path = explicit or configured_path(key)
    if path is None:
        raise typer.BadParameter(
            f"No {label} was provided and no default is configured. "
            "Run `scholar-vault configure` to store default paths."
        )
    resolved = path.expanduser().resolve()
    if must_be_file and not resolved.is_file():
        raise typer.BadParameter(f"Configured {label} is not a file: {resolved}")
    if must_be_dir and not resolved.is_dir():
        raise typer.BadParameter(f"Configured {label} is not a directory: {resolved}")
    return resolved


def _resolve_vault(vault: Path | None) -> Path:
    return _require_configured_path(vault, "vault", label="vault path")


def _print_json(data: dict[str, Any]) -> None:
    typer.echo(json.dumps(data, ensure_ascii=False, indent=2))


def _print_issue_counts(title: str, counts: dict[str, Any]) -> None:
    table = Table(title=title, show_lines=False)
    table.add_column("Issue")
    table.add_column("Count", justify="right")
    for key, value in counts.items():
        table.add_row(str(key).replace("_", " "), str(value))
    console.print(table)


def _call_root_gui(callback):
    cli_module = sys.modules.get("scholar_vault.cli")
    helper = getattr(cli_module, "_call_gui", None)
    if helper is not None:
        return helper(callback)
    return callback()


VaultArg = Annotated[
    Path | None,
    typer.Option("--vault", exists=True, file_okay=False, dir_okay=True, resolve_path=True),
]
JsonOutputArg = Annotated[
    bool,
    typer.Option("--json", help="Print machine-readable JSON."),
]
UiArg = Annotated[
    bool,
    typer.Option(
        "--ui/--no-ui",
        help="Use the desktop UI when available.",
    ),
]
ApplyArg = Annotated[
    bool,
    typer.Option("--apply", help="Apply the planned changes. Default is dry-run."),
]
ArchiveExtraArg = Annotated[
    bool,
    typer.Option(
        "--archive-extra/--keep-extra",
        help="When publishing, move target-only skills into .sync-backups.",
    ),
]
BackupArg = Annotated[
    bool,
    typer.Option("--backup/--no-backup", help="Back up overwritten skills before copying."),
]
ForceArg = Annotated[
    bool,
    typer.Option("--force", help="Process locked metadata records."),
]
SkillSourceArg = Annotated[
    Path | None,
    typer.Option(
        "--source",
        exists=False,
        file_okay=False,
        dir_okay=True,
        resolve_path=True,
        help="Canonical vault-agent skills folder. Defaults to this repo's vault-agent-skills.",
    ),
]
SkillTargetArg = Annotated[
    Path | None,
    typer.Option(
        "--target",
        exists=False,
        file_okay=False,
        dir_okay=True,
        resolve_path=True,
        help="Installed skills folder. Defaults to <vault>/.agents/skills.",
    ),
]
SkillNameArg = Annotated[str, typer.Argument(help="Skill folder name to adopt, or AGENTS.md.")]
ExternalSkillSourceNameArg = Annotated[
    str,
    typer.Argument(
        help=(
            "External skill source name, for example obsidian-skills. Unknown names require "
            "--repository."
        )
    ),
]
ExternalSkillsRepositoryArg = Annotated[
    str | None,
    typer.Option(
        "--repository",
        help="External skills Git repository URL or local Git path. Required for unknown sources.",
    ),
]
ExternalSkillsRefArg = Annotated[
    str | None,
    typer.Option("--ref", help="Git branch, tag, or ref. Defaults to source default or main."),
]
ExternalSkillsSubdirArg = Annotated[
    str | None,
    typer.Option(
        "--skills-subdir",
        help=(
            "Repository subdirectory containing skill folders. "
            "Defaults to source default or skills."
        ),
    ),
]
ExternalSkillsCheckoutArg = Annotated[
    Path | None,
    typer.Option(
        "--checkout",
        exists=True,
        file_okay=False,
        dir_okay=True,
        resolve_path=True,
        hidden=True,
        help="Use an existing external skills checkout instead of cloning.",
    ),
]
ObsidianSkillsRepositoryArg = Annotated[
    str,
    typer.Option(
        "--repository",
        help="Kepano Obsidian skills Git repository URL or local Git path.",
    ),
]
ObsidianSkillsRefArg = Annotated[
    str,
    typer.Option("--ref", help="Git branch, tag, or ref to clone from the Obsidian skills repo."),
]
ObsidianSkillsCheckoutArg = Annotated[
    Path | None,
    typer.Option(
        "--checkout",
        exists=True,
        file_okay=False,
        dir_okay=True,
        resolve_path=True,
        hidden=True,
        help="Use an existing Obsidian skills checkout instead of cloning.",
    ),
]
ProjectSlugArg = Annotated[
    str,
    typer.Argument(help="Project workspace slug, for example map-lens-deformation."),
]
ProjectTitleArg = Annotated[
    str | None,
    typer.Option("--title", help="Human-readable project title."),
]
ProjectCitekeyArg = Annotated[
    str,
    typer.Argument(
        autocompletion=_complete_citekeys,
        help="Paper citekey or card slug to link into the project.",
    ),
]
ProjectConceptSlugArg = Annotated[
    str,
    typer.Argument(help="Concept slug or concepts/<slug>.md path."),
]
ProjectSynthesisSlugArg = Annotated[
    str,
    typer.Argument(help="Synthesis slug or syntheses/<slug>.md path."),
]
ProjectRunIdArg = Annotated[
    str,
    typer.Argument(autocompletion=_complete_run_ids, help="Scholar Labs run id."),
]
ProjectTaskPathArg = Annotated[
    str,
    typer.Argument(help="Task path, with or without the leading tasks/ folder."),
]
ProjectProposalPathArg = Annotated[
    str,
    typer.Argument(help="Proposal path, with or without the leading proposals/ folder."),
]
