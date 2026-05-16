from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from .cli_common import JsonOutputArg, _print_json, console
from .schema import export_schema

schema_app = typer.Typer(help="Machine-readable schema helpers.")

SchemaOutputOption = Annotated[
    Path | None,
    typer.Option("--output", help="Write the schema bundle to a JSON file."),
]


@schema_app.command("export")
def schema_export_command(
    output: SchemaOutputOption = None,
    json_output: JsonOutputArg = False,
) -> None:
    summary = export_schema(output)
    if json_output or output is None:
        _print_json(summary)
    else:
        console.print(f"Schema exported: {summary.get('output')}")
