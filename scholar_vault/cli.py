from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

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
    set_manual_abstract,
    undo_run,
)
from .models import (
    ImportCanceled,
    MatchReviewAbort,
    MatchReviewRequest,
    ScholarLabsExport,
    SourceCard,
)
from .sources import VaultPaths, infer_run_title, load_run_records, load_source_cards

app = typer.Typer(help="Local-first research source wiki and vault manager.")
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


def _complete_only_modes(incomplete: str) -> list[str]:
    values = ["all", "missing-doi", "missing-bibtex", "missing-abstract"]
    return [value for value in values if value.startswith(incomplete)]


def _complete_folder_modes(incomplete: str) -> list[str]:
    values = ["shared", "separate"]
    return [value for value in values if value.startswith(incomplete)]

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
FolderModeArg = Annotated[
    str | None,
    typer.Option(
        "--folder-mode",
        autocompletion=_complete_folder_modes,
        help=(
            "Scholar Labs download layout: 'shared' uses the staging folder for PDFs and "
            "JSON exports; 'separate' uses --exports."
        ),
    ),
]
RunIdArg = Annotated[
    str,
    typer.Option(
        ...,
        autocompletion=_complete_run_ids,
        help="Run id, for example 2026-04-22_example-prompt.",
    ),
]
OptionalRunIdArg = Annotated[
    str | None,
    typer.Option(
        "--run",
        autocompletion=_complete_run_ids,
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
UpgradePdfsArg = Annotated[
    bool,
    typer.Option(
        "--upgrade-pdfs/--keep-existing-pdfs",
        help=(
            "Review staged PDFs as possible replacements for already attached PDFs "
            "when rerunning or re-importing a Scholar Labs export."
        ),
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
CitekeyArg = Annotated[str, typer.Option(..., autocompletion=_complete_citekeys)]
OptionalCitekeyArg = Annotated[
    str | None,
    typer.Option("--citekey", autocompletion=_complete_citekeys),
]
AbstractTextArg = Annotated[
    str | None,
    typer.Option("--text", help="Manual abstract text. Use --file for longer abstracts."),
]
AbstractFileArg = Annotated[
    Path | None,
    typer.Option("--file", exists=True, file_okay=True, dir_okay=False, resolve_path=True),
]
SourceUrlArg = Annotated[
    str | None,
    typer.Option("--source-url", help="URL where the manual abstract was copied from."),
]
AbstractLockArg = Annotated[
    bool,
    typer.Option(
        "--lock/--no-lock",
        help="Protect the manual abstract from future automatic abstract enrichment.",
    ),
]
OnlyArg = Annotated[
    str,
    typer.Option(
        "--only",
        autocompletion=_complete_only_modes,
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
UiArg = Annotated[
    bool,
    typer.Option(
        "--ui/--no-ui",
        help="Use the desktop UI when available.",
    ),
]
YesArg = Annotated[
    bool,
    typer.Option("--yes", help="Reset without confirmation."),
]


def _confirm(prompt: str) -> bool:
    return typer.confirm(prompt, default=False)


def _load_export_for_title(export_path: Path) -> ScholarLabsExport:
    return ScholarLabsExport.model_validate_json(export_path.read_text(encoding="utf-8"))


def _prompt_run_title_cli(default_title: str, prompt: str) -> str:
    console.print("Scholar Labs export does not include a run title.")
    console.print("Prompt:")
    console.print(prompt.strip() or "(empty)", soft_wrap=True)
    selected = typer.prompt("Run title", default=default_title)
    return selected.strip() or default_title


def _prompt_run_title_gui(default_title: str, prompt: str, export_path: Path) -> str | None:
    try:
        from .gui import GuiUnavailable, prompt_run_title
    except Exception as exc:  # pragma: no cover - defensive optional import path
        console.print(f"Title UI unavailable ({exc}). Falling back to terminal prompt.")
        return _prompt_run_title_cli(default_title, prompt)
    try:
        return prompt_run_title(default_title, prompt, str(export_path))
    except GuiUnavailable as exc:
        console.print(f"Title UI unavailable ({exc}). Falling back to terminal prompt.")
        return _prompt_run_title_cli(default_title, prompt)


def _resolve_import_title(title: str | None, export_path: Path, *, ui: bool) -> str | None:
    if title and title.strip():
        return title.strip()
    export = _load_export_for_title(export_path)
    if export.title and export.title.strip():
        return export.title.strip()
    default_title = infer_run_title(export.prompt)
    selected = (
        _prompt_run_title_gui(default_title, export.prompt, export_path)
        if ui
        else _prompt_run_title_cli(default_title, export.prompt)
    )
    if selected is None:
        console.print("Import canceled.")
        raise typer.Exit(code=0)
    return selected.strip() or default_title


def _match_review_prompt(request: MatchReviewRequest) -> str:
    return (
        f"Accept match {request.pdf_filename} -> {request.result_title} "
        f"(score={request.score}, reason={request.match_reason})?"
    )


def _terminal_match_review(request: MatchReviewRequest) -> bool:
    console.print()
    console.print(f"[bold]Scholar Labs title:[/bold] {request.result_title}")
    console.print(
        f"[bold]PDF:[/bold] {request.pdf_filename}  "
        f"[bold]score:[/bold] {request.score}  "
        f"[bold]reason:[/bold] {request.match_reason}"
    )
    if request.inferred_title:
        console.print(f"[bold]Inferred PDF title:[/bold] {request.inferred_title}")
    if request.inferred_doi or request.inferred_year:
        console.print(
            f"[bold]PDF metadata:[/bold] DOI={request.inferred_doi or '-'}  "
            f"year={request.inferred_year or '-'}"
        )
    return typer.confirm(_match_review_prompt(request), default=False)


def _match_reviewer(ui: bool):
    if not ui:
        return _terminal_match_review
    try:
        from .gui import GuiUnavailable, make_match_reviewer
    except Exception as exc:  # pragma: no cover - defensive optional import path
        console.print(f"Review UI unavailable ({exc}). Falling back to terminal prompts.")
        return _terminal_match_review
    try:
        return make_match_reviewer()
    except GuiUnavailable as exc:
        console.print(f"Review UI unavailable ({exc}). Falling back to terminal prompts.")
        return _terminal_match_review


def _confirm_callback(ui: bool):
    if not ui:
        return _confirm
    try:
        from .gui import GuiUnavailable, make_confirmer
    except Exception as exc:  # pragma: no cover - defensive optional import path
        console.print(f"Confirmation UI unavailable ({exc}). Falling back to terminal prompts.")
        return _confirm
    try:
        return make_confirmer("Scholar Vault Import")
    except GuiUnavailable as exc:
        console.print(f"Confirmation UI unavailable ({exc}). Falling back to terminal prompts.")
        return _confirm


def _card_followup_kinds(card: SourceCard) -> list[str]:
    issue_states = {"incomplete", "ambiguous", "unresolved"}
    kinds: list[str] = []
    if card.enrichment_refresh:
        kinds.append("refresh")
    if card.enrichment_status in issue_states or card.enrichment_missing:
        kinds.append("metadata")
    if card.citation_status in issue_states:
        kinds.append("citation")
    if card.abstract_status in issue_states:
        kinds.append("abstract")
    if card.doi_status in {"ambiguous", "unresolved"}:
        kinds.append("doi")
    return kinds


def _followup_issue_label(summary: dict[str, Any] | None) -> str:
    if not summary or not summary.get("count"):
        return "none"
    count = int(summary["count"])
    kind_counts = summary.get("kinds", {})
    if not isinstance(kind_counts, dict) or not kind_counts:
        return f"{count} follow-up"
    order = ["abstract", "citation", "metadata", "doi", "refresh"]
    parts = []
    for kind in order:
        kind_count = int(kind_counts.get(kind, 0))
        if not kind_count:
            continue
        parts.append(f"{kind_count} {kind}" if kind_count > 1 else kind)
    suffix = ", ".join(parts)
    label = "follow-up" if count == 1 else "follow-ups"
    return f"{count} {label}: {suffix}"


def _run_followup_issue_summaries(paths, runs) -> dict[str, dict[str, Any]]:
    cards = {f"papers/{card.slug}.md": card for card in load_source_cards(paths)}
    summaries: dict[str, dict[str, Any]] = {}
    for run in runs:
        seen: set[str] = set()
        issue_count = 0
        kind_counts: Counter[str] = Counter()
        for result in run.results:
            if result.status != "selected" or not result.paper_card:
                continue
            if result.paper_card in seen:
                continue
            seen.add(result.paper_card)
            card = cards.get(result.paper_card)
            if card is None:
                continue
            kinds = _card_followup_kinds(card)
            if not kinds:
                continue
            issue_count += 1
            kind_counts.update(set(kinds))
        if issue_count:
            summaries[run.slug] = {
                "count": issue_count,
                "kinds": dict(kind_counts),
            }
    return summaries


def _select_rerun_run_id(vault: Path, run: str | None, *, ui: bool) -> str:
    if run:
        return run
    if not ui:
        return latest_run_id(vault)

    paths = VaultPaths.from_root(vault)
    runs = load_run_records(paths)
    if not runs:
        raise typer.BadParameter(f"No runs found in vault: {paths.vault}")
    try:
        from .gui import GuiUnavailable, choose_rerun
    except Exception as exc:  # pragma: no cover - defensive optional import path
        console.print(f"Rerun UI unavailable ({exc}). Falling back to latest run.")
        return latest_run_id(vault)
    try:
        selected = choose_rerun(
            runs,
            str(paths.vault),
            issue_summaries=_run_followup_issue_summaries(paths, runs),
        )
    except GuiUnavailable as exc:
        console.print(f"Rerun UI unavailable ({exc}). Falling back to latest run.")
        return latest_run_id(vault)
    if selected is None:
        console.print("Rerun canceled.")
        raise typer.Exit(code=0)
    return selected


def _configure_ui(config: dict[str, Any]) -> dict[str, Any] | None:
    try:
        from .gui import GuiUnavailable, edit_configuration
    except Exception as exc:  # pragma: no cover - defensive optional import path
        console.print(f"Configuration UI unavailable ({exc}). Falling back to terminal output.")
        return None
    try:
        return edit_configuration(config)
    except GuiUnavailable as exc:
        console.print(f"Configuration UI unavailable ({exc}). Falling back to terminal output.")
        return None


def _apply_config_options(
    config: dict[str, Any],
    *,
    vault: Path | None,
    staging: Path | None,
    exports: Path | None,
    code: Path | None,
    folder_mode: str | None,
) -> bool:
    changed = False
    if vault is not None:
        config["vault"] = str(vault.expanduser().resolve())
        changed = True
    if staging is not None:
        config["staging"] = str(staging.expanduser().resolve())
        changed = True
    if code is not None:
        config["code"] = str(code.expanduser().resolve())
        changed = True

    normalized_mode = folder_mode.casefold() if folder_mode else None
    if normalized_mode not in (None, "shared", "separate"):
        raise typer.BadParameter("--folder-mode must be 'shared' or 'separate'.")
    if exports is not None and normalized_mode == "shared":
        raise typer.BadParameter("--exports cannot be used with --folder-mode shared.")
    if exports is not None:
        config["exports"] = str(exports.expanduser().resolve())
        changed = True
    if normalized_mode == "shared":
        if "exports" in config:
            config.pop("exports", None)
            changed = True
    if normalized_mode == "separate":
        if not config.get("exports"):
            raise typer.BadParameter("--folder-mode separate requires --exports.")
        changed = True
    return changed


def _print_config(config: dict[str, Any]) -> None:
    if not config:
        console.print("No scholar-vault defaults configured.")
        return

    console.print("Configured scholar-vault defaults:")
    for key in ("code", "vault", "staging", "exports"):
        value = config.get(key)
        if value:
            console.print(f"- {key}: {value}")
    if config.get("staging") and not config.get("exports"):
        console.print("- folder_mode: shared (staging folder also contains JSON exports)")
    elif config.get("exports"):
        console.print("- folder_mode: separate (staging PDFs and JSON exports are separate)")


def _shorten(value: object, limit: int = 76) -> str:
    text = "" if value is None else str(value)
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _short_run_title(run) -> str:
    title = (run.title or "").strip()
    if title:
        return title
    prompt = " ".join((run.prompt or "").split())
    return _shorten(prompt, 80)


def _short_run_timestamp(run) -> str:
    value = run.exported_at or run.date
    if "T" in value:
        return value[:16].replace("T", " ")
    return value


def _run_table_counts(run) -> tuple[int, int]:
    total = run.result_count or len(run.results)
    selected = sum(1 for result in run.results if result.status == "selected")
    return total, selected


def _print_runs_table(vault: Path, *, limit: int | None = None) -> None:
    paths = VaultPaths.from_root(vault)
    runs = sorted(
        load_run_records(paths),
        key=lambda run: (run.exported_at or run.date, run.slug),
        reverse=True,
    )
    if limit is not None and limit > 0:
        runs = runs[:limit]
    if not runs:
        console.print(f"No runs found in {paths.vault}.")
        return

    issue_summaries = _run_followup_issue_summaries(paths, runs)
    console.print("Scholar Vault Runs")
    console.print(f"Vault: {paths.vault}")
    for run in runs:
        total, selected = _run_table_counts(run)
        console.print(f"\n[cyan]{run.slug}[/cyan]")
        console.print(f"  title: {_short_run_title(run)}")
        console.print(f"  exported: {_short_run_timestamp(run)}")
        console.print(f"  results: {total}  selected: {selected}")
        console.print(f"  follow_up: {_followup_issue_label(issue_summaries.get(run.slug))}")


def _detail_rows(summary: dict[str, Any]) -> list[dict[str, Any]]:
    rows = summary.get("details", [])
    return [row for row in rows if isinstance(row, dict)]


def _print_enrichment_details(summary: dict[str, Any]) -> None:
    rows = _detail_rows(summary)
    if not rows:
        return
    order = [
        "generated",
        "resolved",
        "verified",
        "incomplete",
        "ambiguous",
        "unresolved",
        "skipped",
    ]
    for category in order:
        category_rows = [row for row in rows if row.get("category") == category]
        if not category_rows:
            continue
        table = Table(title=f"{category.title()} ({len(category_rows)})", show_lines=False)
        table.add_column("Type", no_wrap=True)
        table.add_column("Citekey", no_wrap=True)
        table.add_column("Title")
        table.add_column("DOI / Source")
        table.add_column("Missing")
        table.add_column("Message")
        for row in category_rows:
            doi_source = " / ".join(
                part
                for part in [
                    str(row.get("doi") or ""),
                    str(row.get("source") or ""),
                ]
                if part
            )
            missing = ", ".join(row.get("missing_fields") or [])
            table.add_row(
                str(row.get("kind") or ""),
                str(row.get("citekey") or ""),
                _shorten(row.get("title")),
                _shorten(doi_source, 48),
                missing or "-",
                _shorten(row.get("message"), 70),
            )
        console.print(table)


def _show_enrichment_ui(
    summary: dict[str, Any],
    *,
    abstracts: bool,
    title: str | None = None,
    close_label: str | None = None,
) -> bool:
    rows = _detail_rows(summary)
    if not rows:
        return False
    try:
        from .gui import GuiUnavailable, show_enrichment_results
    except Exception as exc:  # pragma: no cover - defensive optional import path
        console.print(f"Review UI unavailable ({exc}). Showing terminal details instead.")
        return False
    try:
        show_enrichment_results(
            rows,
            abstracts=abstracts,
            title=title,
            close_label=close_label,
        )
    except GuiUnavailable as exc:
        console.print(f"Review UI unavailable ({exc}). Showing terminal details instead.")
        return False
    return True


def _make_gui_progress(enabled: bool, title: str):
    if not enabled:
        return None
    try:
        from .gui import GuiUnavailable, make_progress_reporter
    except Exception as exc:  # pragma: no cover - defensive optional import path
        console.print(f"Progress UI unavailable ({exc}). Showing terminal progress instead.")
        return None
    try:
        return make_progress_reporter(title)
    except GuiUnavailable as exc:
        console.print(f"Progress UI unavailable ({exc}). Showing terminal progress instead.")
        return None


def _close_gui_progress(progress_ui) -> None:
    if progress_ui is not None:
        progress_ui.close()


def _show_import_summary_ui(
    summary: dict[str, Any],
    *,
    ui: bool,
    followup_pending: bool = False,
) -> None:
    if not ui:
        return
    try:
        from .gui import GuiUnavailable, show_import_summary
    except Exception as exc:  # pragma: no cover - defensive optional import path
        console.print(f"Summary UI unavailable ({exc}).")
        return
    try:
        show_import_summary(
            summary,
            _import_summary_lines(summary),
            followup_pending=followup_pending,
        )
    except GuiUnavailable as exc:
        console.print(f"Summary UI unavailable ({exc}).")


def _run_enrichment_rows(summary: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for key in ("enrichment_details", "abstract_details"):
        value = summary.get(key, [])
        rows.extend(row for row in value if isinstance(row, dict))
    return rows


def _problem_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    problem_categories = {"incomplete", "ambiguous", "unresolved"}
    problem_skip_messages = {
        "retry limit reached",
        "abstract previously failed",
        "metadata_lock",
    }
    return [
        row
        for row in rows
        if row.get("category") in problem_categories
        or (
            row.get("category") == "skipped"
            and str(row.get("message") or "") in problem_skip_messages
        )
    ]


def _show_import_enrichment_followup(summary: dict[str, Any], *, ui: bool) -> None:
    rows = _run_enrichment_rows(summary)
    problems = _problem_rows(rows)
    if ui:
        if problems:
            shown = _show_enrichment_ui(
                {"details": problems},
                abstracts=False,
                title="Scholar Vault Import Follow-Up",
                close_label="Close Follow-Up and Import Log",
            )
            if not shown:
                console.print("Enrichment follow-up issues:")
                _print_enrichment_details({"details": problems})
        elif rows:
            console.print("No enrichment follow-up issues found.")
        return
    if problems:
        console.print("Enrichment follow-up issues:")
        _print_enrichment_details({"details": problems})


def _has_import_followup(summary: dict[str, Any]) -> bool:
    return bool(_problem_rows(_run_enrichment_rows(summary)))


def _finish_import_workflow(
    summary: dict[str, Any],
    *,
    ui: bool,
    progress_ui=None,
) -> None:
    try:
        _print_run_summary(summary)
        _show_import_summary_ui(
            summary,
            ui=ui,
            followup_pending=_has_import_followup(summary),
        )
        _show_import_enrichment_followup(summary, ui=ui)
    finally:
        _close_gui_progress(progress_ui)


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


def _resolve_latest_export(export: Path | None, *, fallback_dir: Path | None = None) -> Path:
    if export is not None:
        return export.expanduser().resolve()

    exports_dir = configured_path("exports")
    exports_error = ""
    if exports_dir is not None:
        resolved_exports = exports_dir.expanduser().resolve()
        if not resolved_exports.is_dir():
            raise typer.BadParameter(
                f"Configured exports folder is not a directory: {resolved_exports}"
            )
        try:
            return latest_export_json(resolved_exports)
        except FileNotFoundError as exc:
            exports_error = str(exc)

    if fallback_dir is not None:
        try:
            return latest_export_json(fallback_dir)
        except FileNotFoundError as exc:
            fallback_label = f"No JSON export files found in staging folder {fallback_dir}"
            if exports_error:
                raise typer.BadParameter(f"{exports_error}; {fallback_label}") from exc
            raise typer.BadParameter(str(exc)) from exc

    if exports_dir is None:
        raise typer.BadParameter(
            "No export was provided and no exports folder is configured. "
            "Pass --export, configure an exports folder, or configure/use a staging folder "
            "that contains the Scholar Labs JSON export."
        )
    raise typer.BadParameter(exports_error)


def _print_run_summary(summary: dict[str, Any]) -> None:
    for line in _import_summary_lines(summary):
        console.print(line)
    if summary.get("export_archived"):
        console.print(f"Archived used export JSON to {summary['export_archived']}.")


def _import_summary_lines(summary: dict[str, Any]) -> list[str]:
    decisions = summary.get("decision_summary") or {}
    citations = summary.get("citation_enrichment") or {}
    abstracts = summary.get("abstract_enrichment") or {}
    selected = int(summary.get("selected") or 0)
    reused = int(decisions.get("prior_selected_reused") or 0)
    linked = int(decisions.get("existing_cards_linked") or 0)
    new_matches = int(decisions.get("new_staged_pdf_matches") or 0)
    review_prompts = int(decisions.get("review_prompts") or 0)
    review_accepted = int(decisions.get("review_accepted") or 0)
    review_rejected = int(decisions.get("review_rejected") or 0)
    unselected = int(summary.get("unselected_results") or 0)
    export_results = int(decisions.get("export_results") or selected + unselected)
    skipped_commit = int(decisions.get("commit_proposals_skipped") or 0)
    not_committed = int(decisions.get("proposed_not_committed") or 0)
    without_candidate = int(decisions.get("results_without_candidate") or 0)
    pdf_upgrades = int(decisions.get("pdf_upgrades") or 0)
    lines = [
        f"Processed run {summary['run']}.",
        (
            f"- Results: {export_results} in export; "
            f"{selected} selected paper cards; {unselected} left unselected."
        ),
        (
            "- Selection source: "
            f"{reused} reused from previous run manifest, "
            f"{linked} linked to existing vault cards, "
            f"{new_matches} newly accepted staged PDFs."
        ),
        (
            "- Match review: "
            f"{review_prompts} prompts shown "
            f"({review_accepted} accepted, {review_rejected} rejected)."
        ),
        (
            "- Staging: "
            f"{int(decisions.get('staged_pdfs_scanned') or 0)} PDFs scanned; "
            f"{int(summary.get('unmatched') or 0)} unmatched PDFs remain; "
            f"{int(summary.get('archived') or 0)} matched staging PDFs archived."
        ),
    ]
    if unselected:
        lines.append(
            "- Unselected reasons: "
            f"{without_candidate} had no staged PDF candidate above threshold, "
            f"{review_rejected} rejected in review, "
            f"{skipped_commit} skipped by --commit, "
            f"{not_committed} not committed in dry-run."
        )
    citation_processed = int(citations.get("processed") or 0)
    abstract_processed = int(abstracts.get("processed") or 0)
    if citation_processed or abstract_processed:
        citation_changed = int(citations.get("changed") or 0)
        abstract_changed = int(abstracts.get("changed") or 0)
        citation_unchanged = max(citation_processed - citation_changed, 0)
        abstract_unchanged = max(abstract_processed - abstract_changed, 0)
        lines.append(
            "- Enrichment: "
            f"citations checked {citation_processed} cards "
            f"({citation_changed} updated, {citation_unchanged} unchanged); "
            f"abstracts checked {abstract_processed} cards "
            f"({abstract_changed} updated, {abstract_unchanged} unchanged)."
        )
    if pdf_upgrades:
        lines.append(
            f"- PDF upgrades: {pdf_upgrades} existing attachment(s) replaced from staging."
        )
    if review_prompts == 0 and selected:
        if reused == selected:
            lines.append(
                "No match-review prompts appeared because every selected result was already "
                "recorded in the existing run manifest."
            )
        elif reused or linked:
            lines.append(
                "Some results did not need review because they were already selected in this "
                "run or already had attached PDFs in the vault."
            )
    if skipped_commit:
        lines.append(
            f"{skipped_commit} proposed matches were skipped because --commit only accepts "
            "high-confidence auto matches."
        )
    if not_committed:
        lines.append(f"{not_committed} proposed matches were not committed during dry-run.")
    return lines


def _with_progress(
    initial_message: str,
    action,
    *,
    interactive: bool = False,
    gui_progress=None,
):
    if interactive:
        console.print(initial_message)

        def plain_report(
            message: str,
            current: int | None = None,
            total: int | None = None,
        ) -> None:
            if gui_progress is not None:
                gui_progress(message, current, total)
            prefix = f"[{current}/{total}] " if current is not None and total else ""
            console.print(f"{prefix}{message}")

        try:
            result = action(plain_report)
            if gui_progress is not None:
                gui_progress("Complete", None, None)
            return result
        except MatchReviewAbort as exc:
            if gui_progress is not None:
                gui_progress.close()
            console.print(str(exc) or "Import aborted.")
            raise typer.Exit(code=130) from exc
        except ImportCanceled as exc:
            if gui_progress is not None:
                gui_progress.close()
            console.print(str(exc) or "Import canceled.")
            raise typer.Exit(code=0) from exc
        except Exception:
            if gui_progress is not None:
                gui_progress.close()
            raise

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task(initial_message, total=None)

        def report(message: str, current: int | None = None, total: int | None = None) -> None:
            if gui_progress is not None:
                gui_progress(message, current, total)
            prefix = f"[{current}/{total}] " if current is not None and total else ""
            progress.update(task, description=f"{prefix}{message}")

        try:
            result = action(report)
        except MatchReviewAbort as exc:
            progress.stop()
            if gui_progress is not None:
                gui_progress.close()
            console.print(str(exc) or "Import aborted.")
            raise typer.Exit(code=130) from exc
        except ImportCanceled as exc:
            progress.stop()
            if gui_progress is not None:
                gui_progress.close()
            console.print(str(exc) or "Import canceled.")
            raise typer.Exit(code=0) from exc
        except Exception:
            if gui_progress is not None:
                gui_progress.close()
            raise
        if gui_progress is not None:
            gui_progress("Complete", None, None)
        progress.update(task, description="Complete")
        return result


def _enrichment_progress_reporter(report, *, abstracts: bool = False):
    def progress(card: SourceCard, index: int, total: int, status: str) -> None:
        report(_enrichment_progress_message(card, status, abstracts=abstracts), index, total)

    return progress


def _enrichment_progress_message(card: SourceCard, status: str, *, abstracts: bool = False) -> str:
    stage = "abstracts" if abstracts else "citations"
    identifier = card.citekey or card.slug
    title = " ".join((card.title or identifier).split())
    context: list[str] = []
    if abstracts:
        context.append(f"state={card.abstract_status}")
        if card.abstract_source:
            context.append(f"source={card.abstract_source}")
        context.append(f"pdf={'yes' if card.pdf else 'no'}")
        if card.abstract_lock:
            context.append("locked")
    else:
        context.append(f"state={card.citation_status}")
        if card.citation_source:
            context.append(f"source={card.citation_source}")
        if card.enrichment_missing:
            context.append(f"missing={','.join(card.enrichment_missing)}")
        if card.doi:
            context.append(f"doi={card.doi}")
    return f"Enriching {stage} [{status}]: {identifier} // {title} // {'; '.join(context)}"


@app.command("configure")
def configure_command(
    vault: ConfigPathArg = None,
    staging: ConfigPathArg = None,
    exports: ConfigPathArg = None,
    code: ConfigPathArg = None,
    folder_mode: FolderModeArg = None,
    ui: UiArg = False,
) -> None:
    config = load_user_config()
    changed = _apply_config_options(
        config,
        vault=vault,
        staging=staging,
        exports=exports,
        code=code,
        folder_mode=folder_mode,
    )

    if ui:
        updated = _configure_ui(config)
        if updated is None:
            if changed:
                config_path = save_user_config(config)
                console.print(f"Wrote scholar-vault defaults to {config_path}.")
            else:
                console.print("Configuration unchanged.")
            _print_config(config)
            return
        config = updated
        changed = True

    if changed:
        config_path = save_user_config(config)
        console.print(f"Wrote scholar-vault defaults to {config_path}.")

    _print_config(config)


@app.command("init")
def init_command(vault: NewVaultArg) -> None:
    paths = initialize_vault(vault)
    console.print(f"Initialized vault at {paths.vault}")


@app.command("runs")
@app.command("list-runs")
def list_runs_command(
    vault: VaultArg = None,
    limit: int = typer.Option(30, "--limit", "-n", help="Maximum runs to show; 0 shows all."),
) -> None:
    _print_runs_table(_resolve_vault(vault), limit=None if limit == 0 else limit)


@app.command("import-run")
def import_run_command(
    export: ExportArg,
    vault: VaultArg = None,
    staging: StagingArg = None,
    dry_run: DryRunArg = False,
    commit: CommitArg = False,
    include_without_pdf: IncludeWithoutPdfArg = False,
    archive_export: ArchiveExportArg = False,
    upgrade_pdfs: UpgradePdfsArg = True,
    title: TitleArg = None,
    ui: UiArg = False,
) -> None:
    resolved_title = _resolve_import_title(title, export, ui=ui)
    review_match = _match_reviewer(ui) if not dry_run and not commit else None
    confirm = _confirm_callback(ui)
    progress_ui = _make_gui_progress(ui and not dry_run, "Scholar Vault Import")
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
            upgrade_pdfs=upgrade_pdfs,
            title=resolved_title,
            confirm=confirm,
            review_match=review_match,
            progress=report,
        ),
        interactive=review_match is not None,
        gui_progress=progress_ui,
    )
    _finish_import_workflow(summary, ui=ui, progress_ui=progress_ui)


@app.command("import-labs")
def import_labs_command(
    vault: VaultArg = None,
    export: OptionalExportArg = None,
    staging: StagingArg = None,
    dry_run: DryRunArg = False,
    commit: CommitArg = False,
    include_without_pdf: IncludeWithoutPdfArg = False,
    auto_enrich: AutoEnrichArg = True,
    upgrade_pdfs: UpgradePdfsArg = True,
    archive_export: ArchiveExportArg = True,
    title: TitleArg = None,
    ui: UiArg = False,
) -> None:
    review_match = _match_reviewer(ui) if not dry_run and not commit else None
    confirm = _confirm_callback(ui)
    progress_ui = _make_gui_progress(ui and not dry_run, "Scholar Vault Import")
    resolved_vault = _resolve_vault(vault)
    resolved_staging = _resolve_staging(staging)
    resolved_export = _resolve_latest_export(export, fallback_dir=resolved_staging)
    resolved_title = _resolve_import_title(title, resolved_export, ui=ui)
    summary = _with_progress(
        "Importing Scholar Labs run",
        lambda report: import_scholar_labs_run(
            resolved_vault,
            resolved_export,
            resolved_staging,
            dry_run=dry_run,
            commit=commit,
            include_without_pdf=include_without_pdf,
            archive_matched=True,
            archive_export=archive_export,
            auto_enrich=auto_enrich,
            upgrade_pdfs=upgrade_pdfs,
            title=resolved_title,
            confirm=confirm,
            review_match=review_match,
            progress=report,
        ),
        interactive=review_match is not None,
        gui_progress=progress_ui,
    )
    _finish_import_workflow(summary, ui=ui, progress_ui=progress_ui)


@app.command("import")
def import_alias_command(
    vault: VaultArg = None,
    export: OptionalExportArg = None,
    staging: StagingArg = None,
    dry_run: DryRunArg = False,
    commit: CommitArg = False,
    include_without_pdf: IncludeWithoutPdfArg = False,
    auto_enrich: AutoEnrichArg = True,
    upgrade_pdfs: UpgradePdfsArg = True,
    archive_export: ArchiveExportArg = True,
    title: TitleArg = None,
    ui: UiArg = False,
) -> None:
    review_match = _match_reviewer(ui) if not dry_run and not commit else None
    confirm = _confirm_callback(ui)
    progress_ui = _make_gui_progress(ui and not dry_run, "Scholar Vault Import")
    resolved_vault = _resolve_vault(vault)
    resolved_staging = _resolve_staging(staging)
    resolved_export = _resolve_latest_export(export, fallback_dir=resolved_staging)
    resolved_title = _resolve_import_title(title, resolved_export, ui=ui)
    summary = _with_progress(
        "Importing Scholar Labs run",
        lambda report: import_scholar_labs_run(
            resolved_vault,
            resolved_export,
            resolved_staging,
            dry_run=dry_run,
            commit=commit,
            include_without_pdf=include_without_pdf,
            archive_matched=True,
            archive_export=archive_export,
            auto_enrich=auto_enrich,
            upgrade_pdfs=upgrade_pdfs,
            title=resolved_title,
            confirm=confirm,
            review_match=review_match,
            progress=report,
        ),
        interactive=review_match is not None,
        gui_progress=progress_ui,
    )
    _finish_import_workflow(summary, ui=ui, progress_ui=progress_ui)


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
    summary = rebuild_vault(resolved_vault)
    console.print(f"Rebuilt derived files for {resolved_vault}")
    console.print(
        f"- Papers: {summary['papers']} total, "
        f"{summary['paper_cards_written']} card files rewritten, "
        f"{summary['cards_normalized']} normalized."
    )
    console.print(
        f"- Runs: {summary['runs']} run notes refreshed; "
        f"{summary['manifests']} import manifests read."
    )
    console.print(
        f"- Derived outputs: {summary['index_files_written']} indexes, "
        f"{summary['topic_pages_written']} topic pages, "
        f"{summary['llm_files_written']} LLM files, "
        f"{summary['export_files_written']} export files."
    )
    if summary["pdf_filenames_normalized"]:
        console.print(
            f"- Normalized {summary['pdf_filenames_normalized']} attached PDF filename(s)."
        )


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
    ui: UiArg = False,
) -> None:
    progress_ui = _make_gui_progress(ui and not dry_run, "Scholar Vault Enrichment")
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
            progress=_enrichment_progress_reporter(
                report,
                abstracts=abstracts or refresh_abstracts or only == "missing-abstract",
            ),
        ),
        gui_progress=progress_ui,
    )
    if progress_ui is not None:
        progress_ui.close()
    enrich_abstracts = abstracts or refresh_abstracts or only == "missing-abstract"
    if enrich_abstracts:
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
    shown_in_ui = _show_enrichment_ui(summary, abstracts=enrich_abstracts) if ui else False
    if not shown_in_ui:
        _print_enrichment_details(summary)


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
    upgrade_pdfs: UpgradePdfsArg = True,
    ui: UiArg = False,
) -> None:
    review_match = _match_reviewer(ui) if not dry_run and not commit else None
    confirm = _confirm_callback(ui)
    progress_ui = _make_gui_progress(ui and not dry_run, "Scholar Vault Import")
    summary = _with_progress(
        f"Resuming run {run}",
        lambda report: resume_run(
            _resolve_vault(vault),
            run,
            dry_run=dry_run,
            commit=commit,
            auto_enrich=auto_enrich,
            upgrade_pdfs=upgrade_pdfs,
            confirm=confirm,
            review_match=review_match,
            progress=report,
        ),
        interactive=review_match is not None,
        gui_progress=progress_ui,
    )
    _finish_import_workflow(summary, ui=ui, progress_ui=progress_ui)


@app.command("rerun")
def rerun_command(
    vault: VaultArg = None,
    run: OptionalRunIdArg = None,
    dry_run: DryRunArg = False,
    commit: CommitArg = False,
    auto_enrich: AutoEnrichArg = True,
    upgrade_pdfs: UpgradePdfsArg = True,
    ui: UiArg = False,
) -> None:
    resolved_vault = _resolve_vault(vault)
    run_id = _select_rerun_run_id(resolved_vault, run, ui=ui)
    review_match = _match_reviewer(ui) if not dry_run and not commit else None
    confirm = _confirm_callback(ui)
    progress_ui = _make_gui_progress(ui and not dry_run, "Scholar Vault Import")
    summary = _with_progress(
        f"Rerunning {run_id}",
        lambda report: resume_run(
            resolved_vault,
            run_id,
            dry_run=dry_run,
            commit=commit,
            auto_enrich=auto_enrich,
            upgrade_pdfs=upgrade_pdfs,
            confirm=confirm,
            review_match=review_match,
            progress=report,
        ),
        interactive=review_match is not None,
        gui_progress=progress_ui,
    )
    _finish_import_workflow(summary, ui=ui, progress_ui=progress_ui)


@app.command("re-run")
def re_run_command(
    vault: VaultArg = None,
    run: OptionalRunIdArg = None,
    dry_run: DryRunArg = False,
    commit: CommitArg = False,
    auto_enrich: AutoEnrichArg = True,
    upgrade_pdfs: UpgradePdfsArg = True,
    ui: UiArg = False,
) -> None:
    resolved_vault = _resolve_vault(vault)
    run_id = _select_rerun_run_id(resolved_vault, run, ui=ui)
    review_match = _match_reviewer(ui) if not dry_run and not commit else None
    confirm = _confirm_callback(ui)
    progress_ui = _make_gui_progress(ui and not dry_run, "Scholar Vault Import")
    summary = _with_progress(
        f"Rerunning {run_id}",
        lambda report: resume_run(
            resolved_vault,
            run_id,
            dry_run=dry_run,
            commit=commit,
            auto_enrich=auto_enrich,
            upgrade_pdfs=upgrade_pdfs,
            confirm=confirm,
            review_match=review_match,
            progress=report,
        ),
        interactive=review_match is not None,
        gui_progress=progress_ui,
    )
    _finish_import_workflow(summary, ui=ui, progress_ui=progress_ui)


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


@app.command("set-abstract")
def set_abstract_command(
    citekey: CitekeyArg,
    text: AbstractTextArg = None,
    abstract_file: AbstractFileArg = None,
    source_url: SourceUrlArg = None,
    lock: AbstractLockArg = True,
    vault: VaultArg = None,
) -> None:
    if text and abstract_file:
        raise typer.BadParameter("Use either --text or --file, not both.")
    if abstract_file:
        abstract = abstract_file.read_text(encoding="utf-8")
    elif text:
        abstract = text
    else:
        raise typer.BadParameter("Provide a manual abstract with --text or --file.")

    summary = set_manual_abstract(
        _resolve_vault(vault),
        citekey,
        abstract,
        source_url=source_url,
        lock=lock,
    )
    lock_note = "locked" if summary["locked"] else "unlocked"
    console.print(
        f"Set manual abstract for {summary['citekey']} ({lock_note}). "
        f"Updated {summary['paper']}."
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
