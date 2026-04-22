from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from .importer import (
    export_bibtex,
    import_bibtex,
    import_doi,
    import_pdf_dropins,
    import_scholar_labs_run,
    initialize_vault,
    rebuild_vault,
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
StagingArg = Annotated[
    Path,
    typer.Option(..., exists=True, file_okay=False, dir_okay=True, resolve_path=True),
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
) -> None:
    summary = import_scholar_labs_run(vault, export, staging, confirm=_confirm)
    console.print(
        f"Imported run {summary['run']} with {summary['papers']} papers, "
        f"{summary['matched']} matched PDFs, {summary['unmatched']} unmatched PDFs."
    )


@app.command("import")
def import_alias_command(
    vault: VaultArg,
    export: ExportArg,
    staging: StagingArg,
) -> None:
    summary = import_scholar_labs_run(vault, export, staging, confirm=_confirm)
    console.print(
        f"Imported run {summary['run']} with {summary['papers']} papers, "
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


def main() -> None:
    app()
