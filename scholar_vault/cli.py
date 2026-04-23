from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

from .config import configured_path, latest_export_json, load_user_config, save_user_config
from .importer import (
    attach_pdf,
    clean_staging,
    cleanup_run_selected_only,
    enrich_citations,
    export_bibtex,
    import_bibtex,
    import_doi,
    import_pdf_dropins,
    import_scholar_labs_run,
    initialize_vault,
    latest_run_id,
    list_unmatched,
    rebuild_vault,
    rename_run,
    reset_vault,
    resume_run,
    undo_run,
)
from .models import SourceCard

app = typer.Typer(help="Local-first research source wiki and vault manager.")
console = Console()

VaultArg = Annotated[
    Path | None,
    typer.Option("--vault", exists=True, file_okay=False, dir_okay=True, resolve_path=True),
]
NewVaultArg = Annotated[
    Path,
    typer.Option(..., exists=False, file_okay=False, dir_okay=True, resolve_path=True),
]
ExportArg = Annotated[
    Path,
    typer.Option(..., exists=True, file_okay=True, dir_okay=False, resolve_path=True),
]
OptionalExportArg = Annotated[
    Path | None,
    typer.Option("--export", exists=True, file_okay=True, dir_okay=False, resolve_path=True),
]
PdfArg = Annotated[
    Path,
    typer.Option(..., exists=True, file_okay=True, dir_okay=False, resolve_path=True),
]
StagingArg = Annotated[
    Path | None,
    typer.Option("--staging", exists=True, file_okay=False, dir_okay=True, resolve_path=True),
]
ConfigPathArg = Annotated[
    Path | None,
    typer.Option(exists=True, file_okay=False, dir_okay=True, resolve_path=True),
]
RunIdArg = Annotated[str, typer.Option(..., help="Run id, for example 2026-04-22_example-prompt.")]
OptionalRunIdArg = Annotated[
    str | None,
    typer.Option(
        "--run",
        help="Run id. If omitted for rerun, the most recent run is used.",
    ),
]
TitleArg = Annotated[
    str | None,
    typer.Option("--title", help="Short run title used for Obsidian run-note names."),
]
RequiredTitleArg = Annotated[
    str,
    typer.Option("--title", help="Short run title used for Obsidian run-note names."),
]
DryRunArg = Annotated[
    bool,
    typer.Option("--dry-run", help="Plan matches without copying PDFs or creating cards."),
]
CommitArg = Annotated[
    bool,
    typer.Option(
        "--commit",
        help="Commit high-confidence matches without interactive confirmation.",
    ),
]
IncludeWithoutPdfArg = Annotated[
    bool,
    typer.Option(
        "--include-without-pdf",
        help="Create candidate paper cards for results that do not have matched PDFs.",
    ),
]
AutoEnrichArg = Annotated[
    bool,
    typer.Option(
        "--enrich/--no-enrich",
        help="Run citation and abstract enrichment after accepted Scholar Labs matches.",
    ),
]
ArchiveExportArg = Annotated[
    bool,
    typer.Option(
        "--archive-export/--keep-export",
        help="Move a successfully used Scholar Labs JSON export into a sibling used/ folder.",
    ),
]
SelectedOnlyArg = Annotated[
    bool,
    typer.Option("--selected-only", help="Keep only paper cards that have attached PDFs."),
]
CitekeyArg = Annotated[str, typer.Option(...)]
OptionalCitekeyArg = Annotated[str | None, typer.Option("--citekey")]
OnlyArg = Annotated[
    str,
    typer.Option(
        "--only",
        help="Limit enrichment: all, missing-doi, missing-bibtex, or missing-abstract.",
    ),
]
RefreshArg = Annotated[
    bool,
    typer.Option("--refresh", help="Reprocess generated or verified citation metadata."),
]
AbstractsArg = Annotated[
    bool,
    typer.Option("--abstracts", help="Enrich abstracts instead of the default citation metadata."),
]
RefreshAbstractsArg = Annotated[
    bool,
    typer.Option("--refresh-abstracts", help="Reprocess resolved or verified abstracts."),
]
RetryFailedArg = Annotated[
    bool,
    typer.Option("--retry-failed", help="Retry unresolved records that hit the retry limit."),
]
ForceArg = Annotated[
    bool,
    typer.Option("--force", help="Process locked metadata records."),
]
YesArg = Annotated[
    bool,
    typer.Option("--yes", help="Reset without confirmation."),
]


def _confirm(prompt: str) -> bool:
    return typer.confirm(prompt, default=False)


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


def _resolve_staging(staging: Path | None) -> Path:
    return _require_configured_path(staging, "staging", label="staging folder")


def _resolve_latest_export(export: Path | None) -> Path:
    if export is not None:
        return export.expanduser().resolve()
    exports_dir = _require_configured_path(None, "exports", label="exports folder")
    try:
        return latest_export_json(exports_dir)
    except FileNotFoundError as exc:
        raise typer.BadParameter(str(exc)) from exc


def _print_run_summary(summary: dict[str, int | str]) -> None:
    console.print(
        f"Processed run {summary['run']} with {summary['papers']} paper cards, "
        f"{summary['selected']} selected results, "
        f"{summary['matched']} matched PDFs, {summary['unmatched']} unmatched PDFs, "
        f"and {summary['archived']} matched staging PDFs archived."
    )
    if summary.get("export_archived"):
        console.print(f"Archived used export JSON to {summary['export_archived']}.")
    if summary.get("enriched"):
        console.print(f"Enrichment made {summary['enriched']} selected-paper metadata updates.")


def _with_progress(initial_message: str, action):
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task(initial_message, total=None)

        def report(message: str, current: int | None = None, total: int | None = None) -> None:
            prefix = f"[{current}/{total}] " if current is not None and total else ""
            progress.update(task, description=f"{prefix}{message}")

        result = action(report)
        progress.update(task, description="Complete")
        return result


def _enrichment_progress_reporter(report):
    def progress(card: SourceCard, index: int, total: int, status: str) -> None:
        report(f"{card.citekey or card.slug}: {status}", index, total)

    return progress


@app.command("configure")
def configure_command(
    vault: ConfigPathArg = None,
    staging: ConfigPathArg = None,
    exports: ConfigPathArg = None,
    code: ConfigPathArg = None,
) -> None:
    config = load_user_config()
    if vault is not None:
        config["vault"] = str(vault.expanduser().resolve())
    if staging is not None:
        config["staging"] = str(staging.expanduser().resolve())
    if exports is not None:
        config["exports"] = str(exports.expanduser().resolve())
    if code is not None:
        config["code"] = str(code.expanduser().resolve())

    if any(path is not None for path in (vault, staging, exports, code)):
        config_path = save_user_config(config)
        console.print(f"Wrote scholar-vault defaults to {config_path}.")

    if not config:
        console.print("No scholar-vault defaults configured.")
        return

    console.print("Configured scholar-vault defaults:")
    for key in ("code", "vault", "staging", "exports"):
        value = config.get(key)
        if value:
            console.print(f"- {key}: {value}")


@app.command("init")
def init_command(vault: NewVaultArg) -> None:
    paths = initialize_vault(vault)
    console.print(f"Initialized vault at {paths.vault}")


@app.command("import-run")
def import_run_command(
    export: ExportArg,
    vault: VaultArg = None,
    staging: StagingArg = None,
    dry_run: DryRunArg = False,
    commit: CommitArg = False,
    include_without_pdf: IncludeWithoutPdfArg = False,
    archive_export: ArchiveExportArg = False,
    title: TitleArg = None,
) -> None:
    summary = _with_progress(
        "Importing Scholar Labs run",
        lambda report: import_scholar_labs_run(
            _resolve_vault(vault),
            export,
            _resolve_staging(staging),
            dry_run=dry_run,
            commit=commit,
            include_without_pdf=include_without_pdf,
            archive_matched=False,
            archive_export=archive_export,
            title=title,
            confirm=_confirm,
            progress=report,
        ),
    )
    _print_run_summary(summary)


@app.command("import-labs")
def import_labs_command(
    vault: VaultArg = None,
    export: OptionalExportArg = None,
    staging: StagingArg = None,
    dry_run: DryRunArg = False,
    commit: CommitArg = False,
    include_without_pdf: IncludeWithoutPdfArg = False,
    auto_enrich: AutoEnrichArg = True,
    archive_export: ArchiveExportArg = True,
    title: TitleArg = None,
) -> None:
    summary = _with_progress(
        "Importing Scholar Labs run",
        lambda report: import_scholar_labs_run(
            _resolve_vault(vault),
            _resolve_latest_export(export),
            _resolve_staging(staging),
            dry_run=dry_run,
            commit=commit,
            include_without_pdf=include_without_pdf,
            archive_matched=True,
            archive_export=archive_export,
            auto_enrich=auto_enrich,
            title=title,
            confirm=_confirm,
            progress=report,
        ),
    )
    _print_run_summary(summary)


@app.command("import")
def import_alias_command(
    vault: VaultArg = None,
    export: OptionalExportArg = None,
    staging: StagingArg = None,
    dry_run: DryRunArg = False,
    commit: CommitArg = False,
    include_without_pdf: IncludeWithoutPdfArg = False,
    auto_enrich: AutoEnrichArg = True,
    archive_export: ArchiveExportArg = True,
    title: TitleArg = None,
) -> None:
    summary = _with_progress(
        "Importing Scholar Labs run",
        lambda report: import_scholar_labs_run(
            _resolve_vault(vault),
            _resolve_latest_export(export),
            _resolve_staging(staging),
            dry_run=dry_run,
            commit=commit,
            include_without_pdf=include_without_pdf,
            archive_matched=True,
            archive_export=archive_export,
            auto_enrich=auto_enrich,
            title=title,
            confirm=_confirm,
            progress=report,
        ),
    )
    _print_run_summary(summary)


@app.command("import-pdf")
def import_pdf_command(
    vault: VaultArg = None,
    staging: StagingArg = None,
) -> None:
    summary = import_pdf_dropins(_resolve_vault(vault), _resolve_staging(staging), confirm=_confirm)
    console.print(f"Imported {summary['imported']} PDF files.")


@app.command("import-bibtex")
def import_bibtex_command(
    bib: ExportArg,
    vault: VaultArg = None,
) -> None:
    summary = import_bibtex(_resolve_vault(vault), bib)
    console.print(f"Imported {summary['imported']} BibTeX entries.")


@app.command("import-doi")
def import_doi_command(
    doi: str = typer.Option(...),
    vault: VaultArg = None,
) -> None:
    summary = import_doi(_resolve_vault(vault), doi)
    console.print(f"Imported {summary['imported']} DOI stubs.")


@app.command("rebuild")
def rebuild_command(vault: VaultArg = None) -> None:
    resolved_vault = _resolve_vault(vault)
    rebuild_vault(resolved_vault)
    console.print(f"Rebuilt derived files for {resolved_vault}")


@app.command("bibtex")
def bibtex_command(vault: VaultArg = None) -> None:
    output = export_bibtex(_resolve_vault(vault))
    console.print(f"Wrote {output}")


@app.command("enrich-citations")
def enrich_citations_command(
    vault: VaultArg = None,
    citekey: OptionalCitekeyArg = None,
    only: OnlyArg = "all",
    refresh: RefreshArg = False,
    abstracts: AbstractsArg = False,
    refresh_abstracts: RefreshAbstractsArg = False,
    retry_failed: RetryFailedArg = False,
    dry_run: DryRunArg = False,
    force: ForceArg = False,
) -> None:
    summary = _with_progress(
        "Enriching paper cards",
        lambda report: enrich_citations(
            _resolve_vault(vault),
            citekey=citekey,
            only=only,
            refresh=refresh,
            abstracts=abstracts,
            refresh_abstracts=refresh_abstracts,
            retry_failed=retry_failed,
            dry_run=dry_run,
            force=force,
            progress=_enrichment_progress_reporter(report),
        ),
    )
    if abstracts or refresh_abstracts or only == "missing-abstract":
        console.print(
            f"Enriched abstracts: processed={summary['processed']}, changed={summary['changed']}, "
            f"skipped={summary['skipped']}, resolved={summary['resolved']}, "
            f"verified={summary['verified']}, ambiguous={summary['ambiguous']}, "
            f"unresolved={summary['unresolved']}."
        )
    else:
        console.print(
            f"Enriched citations: processed={summary['processed']}, changed={summary['changed']}, "
            f"skipped={summary['skipped']}, generated={summary['generated']}, "
            f"verified={summary['verified']}, ambiguous={summary['ambiguous']}, "
            f"unresolved={summary['unresolved']}."
        )


@app.command("reset")
def reset_command(vault: VaultArg = None, yes: YesArg = False) -> None:
    resolved = _resolve_vault(vault)
    if not yes and not _confirm(
        f"Reset vault at {resolved}? This removes imported papers, runs, PDFs, "
        "raw copies inside the vault, derived indexes, and exports."
    ):
        raise typer.Exit(code=1)

    summary = reset_vault(resolved)
    console.print(f"Reset vault at {resolved}. Removed {summary['removed']} vault-managed items.")


@app.command("resume")
def resume_command(
    run: RunIdArg,
    vault: VaultArg = None,
    dry_run: DryRunArg = False,
    commit: CommitArg = False,
    auto_enrich: AutoEnrichArg = True,
) -> None:
    summary = _with_progress(
        f"Resuming run {run}",
        lambda report: resume_run(
            _resolve_vault(vault),
            run,
            dry_run=dry_run,
            commit=commit,
            auto_enrich=auto_enrich,
            confirm=_confirm,
            progress=report,
        ),
    )
    _print_run_summary(summary)


@app.command("rerun")
def rerun_command(
    vault: VaultArg = None,
    run: OptionalRunIdArg = None,
    dry_run: DryRunArg = False,
    commit: CommitArg = False,
    auto_enrich: AutoEnrichArg = True,
) -> None:
    resolved_vault = _resolve_vault(vault)
    run_id = run or latest_run_id(resolved_vault)
    summary = _with_progress(
        f"Rerunning {run_id}",
        lambda report: resume_run(
            resolved_vault,
            run_id,
            dry_run=dry_run,
            commit=commit,
            auto_enrich=auto_enrich,
            confirm=_confirm,
            progress=report,
        ),
    )
    _print_run_summary(summary)


@app.command("re-run")
def re_run_command(
    vault: VaultArg = None,
    run: OptionalRunIdArg = None,
    dry_run: DryRunArg = False,
    commit: CommitArg = False,
    auto_enrich: AutoEnrichArg = True,
) -> None:
    resolved_vault = _resolve_vault(vault)
    run_id = run or latest_run_id(resolved_vault)
    summary = _with_progress(
        f"Rerunning {run_id}",
        lambda report: resume_run(
            resolved_vault,
            run_id,
            dry_run=dry_run,
            commit=commit,
            auto_enrich=auto_enrich,
            confirm=_confirm,
            progress=report,
        ),
    )
    _print_run_summary(summary)


@app.command("rename-run")
def rename_run_command(
    run: RunIdArg,
    title: RequiredTitleArg,
    vault: VaultArg = None,
) -> None:
    summary = rename_run(_resolve_vault(vault), run, title)
    console.print(
        f"Renamed run {summary['run']} to {summary['title']}. "
        f"Run note: {summary['new_ref']}."
    )


@app.command("undo")
def undo_command(run: RunIdArg, vault: VaultArg = None) -> None:
    summary = undo_run(_resolve_vault(vault), run)
    console.print(
        f"Undid run {run}. Archived {summary['archived_cards']} cards, "
        f"restored {summary['restored_cards']} cards, archived {summary['archived_pdfs']} PDFs, "
        f"and restored {summary['restored_originals']} staging originals."
    )


@app.command("attach-pdf")
def attach_pdf_command(
    citekey: CitekeyArg,
    pdf: PdfArg,
    vault: VaultArg = None,
) -> None:
    summary = attach_pdf(_resolve_vault(vault), citekey, pdf)
    console.print(
        f"Attached {summary['pdf']} to {citekey} "
        f"(copied={summary['copied']}, verified={summary['verified']})."
    )


@app.command("unmatched")
def unmatched_command(vault: VaultArg = None) -> None:
    rows = list_unmatched(_resolve_vault(vault))
    if not rows:
        console.print("No unmatched PDFs.")
        return
    for row in rows:
        console.print(
            f"{row['run_id']}: {row['original_path']} "
            f"(decision={row['decision']}, score={row['score']}, proposed={row['proposed_match']})"
        )


@app.command("clean-staging")
def clean_staging_command(vault: VaultArg = None, staging: StagingArg = None) -> None:
    summary = clean_staging(_resolve_vault(vault), _resolve_staging(staging))
    console.print(
        f"Cleaned staging. Moved {summary['moved']} files into vault archive "
        f"and kept {summary['kept']} files."
    )


@app.command("cleanup-run")
def cleanup_run_command(
    run: RunIdArg,
    vault: VaultArg = None,
    selected_only: SelectedOnlyArg = False,
) -> None:
    if not selected_only:
        raise typer.BadParameter("Only --selected-only is currently supported.")
    summary = cleanup_run_selected_only(_resolve_vault(vault), run)
    console.print(
        f"Cleaned run {run}. Archived {summary['archived']} candidate-only cards "
        f"and kept {summary['kept']} cards."
    )


def main() -> None:
    app()
