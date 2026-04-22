from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from .importer import (
    attach_pdf,
    clean_staging,
    cleanup_run_selected_only,
    export_bibtex,
    import_bibtex,
    import_doi,
    import_pdf_dropins,
    import_scholar_labs_run,
    initialize_vault,
    list_unmatched,
    rebuild_vault,
    reset_vault,
    resume_run,
    undo_run,
)

app = typer.Typer(help="Local-first research source wiki and vault manager.")
console = Console()

VaultArg = Annotated[
    Path,
    typer.Option(..., exists=True, file_okay=False, dir_okay=True, resolve_path=True),
]
NewVaultArg = Annotated[
    Path,
    typer.Option(..., exists=False, file_okay=False, dir_okay=True, resolve_path=True),
]
ExportArg = Annotated[
    Path,
    typer.Option(..., exists=True, file_okay=True, dir_okay=False, resolve_path=True),
]
PdfArg = Annotated[
    Path,
    typer.Option(..., exists=True, file_okay=True, dir_okay=False, resolve_path=True),
]
StagingArg = Annotated[
    Path,
    typer.Option(..., exists=True, file_okay=False, dir_okay=True, resolve_path=True),
]
RunIdArg = Annotated[str, typer.Option(..., help="Run id, for example 2026-04-22_example-prompt.")]
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
SelectedOnlyArg = Annotated[
    bool,
    typer.Option("--selected-only", help="Keep only paper cards that have attached PDFs."),
]
CitekeyArg = Annotated[str, typer.Option(...)]
YesArg = Annotated[
    bool,
    typer.Option("--yes", help="Reset without confirmation."),
]


def _confirm(prompt: str) -> bool:
    return typer.confirm(prompt, default=False)


@app.command("init")
def init_command(vault: NewVaultArg) -> None:
    paths = initialize_vault(vault)
    console.print(f"Initialized vault at {paths.vault}")


@app.command("import-run")
def import_run_command(
    vault: VaultArg,
    export: ExportArg,
    staging: StagingArg,
    dry_run: DryRunArg = False,
    commit: CommitArg = False,
    include_without_pdf: IncludeWithoutPdfArg = False,
) -> None:
    summary = import_scholar_labs_run(
        vault,
        export,
        staging,
        dry_run=dry_run,
        commit=commit,
        include_without_pdf=include_without_pdf,
        confirm=_confirm,
    )
    console.print(
        f"Processed run {summary['run']} with {summary['papers']} paper cards, "
        f"{summary['selected']} selected results, "
        f"{summary['matched']} matched PDFs, {summary['unmatched']} unmatched PDFs."
    )


@app.command("import")
def import_alias_command(
    vault: VaultArg,
    export: ExportArg,
    staging: StagingArg,
    dry_run: DryRunArg = False,
    commit: CommitArg = False,
    include_without_pdf: IncludeWithoutPdfArg = False,
) -> None:
    summary = import_scholar_labs_run(
        vault,
        export,
        staging,
        dry_run=dry_run,
        commit=commit,
        include_without_pdf=include_without_pdf,
        confirm=_confirm,
    )
    console.print(
        f"Processed run {summary['run']} with {summary['papers']} paper cards, "
        f"{summary['selected']} selected results, "
        f"{summary['matched']} matched PDFs, {summary['unmatched']} unmatched PDFs."
    )


@app.command("import-pdf")
def import_pdf_command(
    vault: VaultArg,
    staging: StagingArg,
) -> None:
    summary = import_pdf_dropins(vault, staging, confirm=_confirm)
    console.print(f"Imported {summary['imported']} PDF files.")


@app.command("import-bibtex")
def import_bibtex_command(
    vault: VaultArg,
    bib: ExportArg,
) -> None:
    summary = import_bibtex(vault, bib)
    console.print(f"Imported {summary['imported']} BibTeX entries.")


@app.command("import-doi")
def import_doi_command(
    vault: VaultArg,
    doi: str = typer.Option(...),
) -> None:
    summary = import_doi(vault, doi)
    console.print(f"Imported {summary['imported']} DOI stubs.")


@app.command("rebuild")
def rebuild_command(vault: VaultArg) -> None:
    rebuild_vault(vault)
    console.print(f"Rebuilt derived files for {Path(vault).expanduser().resolve()}")


@app.command("bibtex")
def bibtex_command(vault: VaultArg) -> None:
    output = export_bibtex(vault)
    console.print(f"Wrote {output}")


@app.command("reset")
def reset_command(vault: VaultArg, yes: YesArg = False) -> None:
    resolved = Path(vault).expanduser().resolve()
    if not yes and not _confirm(
        f"Reset vault at {resolved}? This removes imported papers, runs, PDFs, "
        "raw copies inside the vault, derived indexes, and exports."
    ):
        raise typer.Exit(code=1)

    summary = reset_vault(vault)
    console.print(f"Reset vault at {resolved}. Removed {summary['removed']} vault-managed items.")


@app.command("resume")
def resume_command(
    vault: VaultArg,
    run: RunIdArg,
    dry_run: DryRunArg = False,
    commit: CommitArg = False,
) -> None:
    summary = resume_run(vault, run, dry_run=dry_run, commit=commit, confirm=_confirm)
    console.print(
        f"Resumed run {summary['run']} with {summary['papers']} paper cards, "
        f"{summary['selected']} selected results, "
        f"{summary['matched']} matched PDFs, {summary['unmatched']} unmatched PDFs."
    )


@app.command("undo")
def undo_command(vault: VaultArg, run: RunIdArg) -> None:
    summary = undo_run(vault, run)
    console.print(
        f"Undid run {run}. Archived {summary['archived_cards']} cards, "
        f"restored {summary['restored_cards']} cards, and archived {summary['archived_pdfs']} PDFs."
    )


@app.command("attach-pdf")
def attach_pdf_command(
    vault: VaultArg,
    citekey: CitekeyArg,
    pdf: PdfArg,
) -> None:
    summary = attach_pdf(vault, citekey, pdf)
    console.print(
        f"Attached {summary['pdf']} to {citekey} "
        f"(copied={summary['copied']}, verified={summary['verified']})."
    )


@app.command("unmatched")
def unmatched_command(vault: VaultArg) -> None:
    rows = list_unmatched(vault)
    if not rows:
        console.print("No unmatched PDFs.")
        return
    for row in rows:
        console.print(
            f"{row['run_id']}: {row['original_path']} "
            f"(decision={row['decision']}, score={row['score']}, proposed={row['proposed_match']})"
        )


@app.command("clean-staging")
def clean_staging_command(vault: VaultArg, staging: StagingArg) -> None:
    summary = clean_staging(vault, staging)
    console.print(
        f"Cleaned staging. Moved {summary['moved']} files into vault archive "
        f"and kept {summary['kept']} files."
    )


@app.command("cleanup-run")
def cleanup_run_command(
    vault: VaultArg,
    run: RunIdArg,
    selected_only: SelectedOnlyArg = False,
) -> None:
    if not selected_only:
        raise typer.BadParameter("Only --selected-only is currently supported.")
    summary = cleanup_run_selected_only(vault, run)
    console.print(
        f"Cleaned run {run}. Archived {summary['archived']} candidate-only cards "
        f"and kept {summary['kept']} cards."
    )


def main() -> None:
    app()
