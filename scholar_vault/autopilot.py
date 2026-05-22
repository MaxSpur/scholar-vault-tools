from __future__ import annotations

import re
import shutil
import subprocess
import webbrowser
from pathlib import Path
from typing import Any

import yaml

from .bases import doctor_bases, rebuild_bases
from .config import configured_path, latest_export_json
from .digests import compile_doctor, compile_scaffold, compile_status
from .evals import render_eval_report, run_evals
from .importer import (
    find_staged_run_matches,
    import_pdf_dropins,
    import_scholar_labs_run,
    import_staged_pdf_match,
    initialize_vault,
)
from .labs_prompts import generate_prompt_pack, record_used_prompt_pack, resolve_prompt_pack
from .maintenance import maintenance_report
from .models import ScholarLabsExport
from .obsidian_setup import doctor_obsidian
from .projects import project_link_paper, project_scaffold
from .queries import _query_slug, query_create, query_link_paper
from .rebuild import rebuild_vault
from .self_improvement import log_operation, write_self_improvement_dashboard
from .semantic_lint import lint_wiki
from .sessions import (
    CodexRunner,
    archive_session,
    create_or_reuse_session,
    list_sessions,
    load_current_session,
    load_session,
    now_iso,
    run_codex_handoff,
    update_session_status,
    write_handoff,
    write_session,
    write_session_report,
)
from .sources import (
    VaultPaths,
    dump_frontmatter,
    ensure_relative,
    load_run_records,
    read_frontmatter_markdown,
    write_text,
    write_yaml,
)

NEXT_AFTER_ASK = (
    "Run this prompt manually in Scholar Labs, download the PDFs and JSON export, "
    "then run `scholar-vault intake`."
)
SCHOLAR_URL = "https://scholar.google.com/"


def _copy_to_clipboard(text: str) -> str:
    pbcopy = shutil.which("pbcopy")
    if pbcopy:
        subprocess.run([pbcopy], input=text, text=True, check=True)
        return "pbcopy"
    wl_copy = shutil.which("wl-copy")
    if wl_copy:
        subprocess.run([wl_copy], input=text, text=True, check=True)
        return "wl-copy"
    xclip = shutil.which("xclip")
    if xclip:
        subprocess.run([xclip, "-selection", "clipboard"], input=text, text=True, check=True)
        return "xclip"
    raise RuntimeError("No clipboard command found. Install pbcopy, wl-copy, or xclip.")


def _open_scholar() -> bool:
    return bool(webbrowser.open(SCHOLAR_URL))


def _resolve_staging(staging: Path | None) -> Path:
    path = staging or configured_path("staging")
    if path is None:
        raise ValueError(
            "No staging folder was provided and no default is configured. "
            "Run `scholar-vault configure` first."
        )
    resolved = path.expanduser().resolve()
    if not resolved.is_dir():
        raise ValueError(f"Staging folder is not a directory: {resolved}")
    return resolved


def _resolve_export(export: Path | None, *, staging: Path) -> Path:
    if export is not None:
        return export.expanduser().resolve()
    exports_dir = configured_path("exports")
    if exports_dir is not None:
        resolved_exports = exports_dir.expanduser().resolve()
        if not resolved_exports.is_dir():
            raise ValueError(f"Configured exports folder is not a directory: {resolved_exports}")
        try:
            return latest_export_json(resolved_exports)
        except FileNotFoundError:
            pass
    return latest_export_json(staging)


def _extract_prompt(body: str, *, preferred_type: str = "coverage_gap") -> dict[str, str]:
    prompt_blocks: list[dict[str, str]] = []
    pattern = re.compile(
        r"^###\s+(?P<id>.+?)\s*$.*?^- prompt_type:\s+`?(?P<type>[^`\n]+)`?.*?"
        r"```text\n(?P<prompt>.*?)\n```",
        flags=re.MULTILINE | re.DOTALL,
    )
    for match in pattern.finditer(body):
        prompt_blocks.append(
            {
                "id": match.group("id").strip(),
                "type": match.group("type").strip(),
                "prompt": match.group("prompt").strip(),
            }
        )
    if not prompt_blocks:
        raise ValueError("Prompt pack does not contain any fenced Scholar Labs prompts.")
    for block in prompt_blocks:
        if block["type"] == preferred_type:
            return block
    return prompt_blocks[0]


def _mark_prompt_pack_ready(paths: VaultPaths, prompt_pack_ref: str) -> None:
    _, path, _ = resolve_prompt_pack(paths, prompt_pack_ref)
    frontmatter, body = read_frontmatter_markdown(path)
    if frontmatter.get("status") != "ready":
        frontmatter["status"] = "ready"
        write_text(path, f"---\n{dump_frontmatter(frontmatter).strip()}\n---\n\n{body.strip()}\n")


def ask(
    vault: Path | str,
    question: str,
    *,
    project: str | None = None,
    slug: str | None = None,
    seed_api: str = "none",
    refresh_seeds: bool = False,
    copy: bool = False,
    open_scholar: bool = False,
    new_session: bool = False,
) -> dict[str, Any]:
    paths = initialize_vault(vault, rebuild=False)
    query_summary = query_create(paths.vault, question, project=project, slug=slug)
    query_slug = str(query_summary["slug"])
    query_path = str(query_summary["query"])
    session, created = create_or_reuse_session(
        paths,
        question=question,
        project=project,
        query_path=query_path,
        new_session=new_session,
    )
    prompt_summary = generate_prompt_pack(
        paths.vault,
        query=query_slug,
        seed_api=seed_api,  # type: ignore[arg-type]
        refresh_seeds=refresh_seeds,
    )
    prompt_pack_ref = str(prompt_summary["prompt_pack"])
    _mark_prompt_pack_ready(paths, prompt_pack_ref)
    _, prompt_path, prompt_body = resolve_prompt_pack(paths, prompt_pack_ref)
    selected_prompt = _extract_prompt(prompt_body)
    session["prompt_pack_path"] = ensure_relative(prompt_path, paths.vault)
    session = update_session_status(
        paths,
        session,
        "waiting_for_labs_export",
        prompt_pack_path=session["prompt_pack_path"],
    )
    copy_status = ""
    open_status = ""
    if copy:
        try:
            copy_status = _copy_to_clipboard(selected_prompt["prompt"])
        except Exception as exc:
            copy_status = f"unsupported: {exc}"
    if open_scholar:
        try:
            open_status = "opened" if _open_scholar() else "unsupported"
        except Exception as exc:
            open_status = f"unsupported: {exc}"
    log_operation(
        paths.vault,
        kind="autopilot_ask",
        message=f"Prepared Scholar Labs prompt for session `{session['id']}`.",
        command="scholar-vault ask",
        inputs={
            "question": question,
            "project": project,
            "seed_api": seed_api,
            "copy": copy,
            "open_scholar": open_scholar,
        },
        outputs={
            "session": session["id"],
            "session_created": created,
            "query": query_path,
            "prompt_pack": prompt_pack_ref,
            "prompt_id": selected_prompt["id"],
            "copy_status": copy_status,
            "open_status": open_status,
        },
        result="ready",
    )
    write_session_report(paths, session, next_user_action=NEXT_AFTER_ASK)
    return {
        "vault": str(paths.vault),
        "session": session,
        "session_created": created,
        "query": query_path,
        "prompt_pack": prompt_pack_ref,
        "prompt_id": selected_prompt["id"],
        "prompt_type": selected_prompt["type"],
        "prompt": selected_prompt["prompt"],
        "next_step": NEXT_AFTER_ASK,
        "copy_status": copy_status,
        "open_status": open_status,
    }


def start(
    vault: Path | str,
    project: str,
    question: str,
    *,
    title: str | None = None,
    slug: str | None = None,
    export: Path | None = None,
    staging: Path | None = None,
    pdf_only: bool = False,
    seed_api: str = "none",
    refresh_seeds: bool = False,
    copy: bool = False,
    open_scholar: bool = False,
    auto_enrich: bool = True,
    upgrade_pdfs: bool = True,
) -> dict[str, Any]:
    if export is not None and pdf_only:
        raise ValueError("Use either --export for Scholar Labs JSON or --pdf-only, not both.")
    paths = initialize_vault(vault, rebuild=False)
    project_summary = project_scaffold(paths.vault, project, title=title)
    if export is not None or pdf_only:
        intake_summary = intake(
            paths.vault,
            export=export,
            staging=staging,
            question=question,
            project=project,
            slug=slug,
            new_session=True,
            pdf_only=pdf_only,
            auto_enrich=auto_enrich,
            upgrade_pdfs=upgrade_pdfs,
        )
        return {
            "vault": str(paths.vault),
            "mode": "pdf-only" if pdf_only else "intake",
            "project": project_summary,
            "intake": intake_summary,
            "session": intake_summary["session"],
            "next_step": (
                "Run `scholar-vault answer \"synthesis question\"` when ready."
                if not intake_summary.get("blockers")
                else "Resolve the listed blocker(s), then rerun intake."
            ),
        }

    ask_summary = ask(
        paths.vault,
        question,
        project=project,
        slug=slug,
        seed_api=seed_api,
        refresh_seeds=refresh_seeds,
        copy=copy,
        open_scholar=open_scholar,
        new_session=True,
    )
    return {
        "vault": str(paths.vault),
        "mode": "ask",
        "project": project_summary,
        "ask": ask_summary,
        "session": ask_summary["session"],
        "prompt": ask_summary["prompt"],
        "next_step": ask_summary["next_step"],
    }


def _current_or_named_session(paths: VaultPaths, session_id: str | None = None) -> dict[str, Any]:
    if session_id:
        return load_session(paths, session_id)
    session = load_current_session(paths)
    if session is None:
        raise ValueError("No current session is active. Run `scholar-vault ask \"...\"` first.")
    return session


def _load_export(export_path: Path) -> ScholarLabsExport:
    return ScholarLabsExport.model_validate_json(export_path.read_text(encoding="utf-8"))


def _load_export_prompt(export_path: Path) -> str:
    export = _load_export(export_path)
    prompt = " ".join(export.prompt.split())
    if not prompt:
        raise ValueError(f"Scholar Labs export has no prompt: {export_path}")
    return prompt


def _desired_query_ref(question: str, slug: str | None) -> str:
    return f"queries/{_query_slug(slug or question)}.md"


def _current_session_conflict(
    current: dict[str, Any],
    *,
    question: str | None = None,
    project: str | None = None,
    slug: str | None = None,
) -> str | None:
    if question is not None and current.get("question") != question:
        return (
            f"current session question is `{current.get('question')}`, "
            f"but intake requested `{question}`"
        )
    if project is not None and current.get("project") != project:
        return (
            f"current session project is `{current.get('project') or '-'}`, "
            f"but intake requested `{project}`"
        )
    if slug is not None:
        desired_query = _desired_query_ref(question or current.get("question") or slug, slug)
        if current.get("query_path") != desired_query:
            return (
                f"current session query is `{current.get('query_path') or '-'}`, "
                f"but intake requested `{desired_query}`"
            )
    return None


def _bootstrap_session(
    paths: VaultPaths,
    *,
    question: str,
    project: str | None,
    slug: str | None,
    new_session: bool,
) -> dict[str, Any]:
    if project:
        project_scaffold(paths.vault, project)
    query_summary = query_create(paths.vault, question, project=project, slug=slug)
    session, _created = create_or_reuse_session(
        paths,
        question=question,
        project=project,
        query_path=str(query_summary["query"]),
        new_session=new_session,
    )
    return update_session_status(paths, session, "waiting_for_labs_export")


def _intake_session(
    paths: VaultPaths,
    *,
    session_id: str | None,
    export_path: Path,
    question: str | None,
    project: str | None,
    slug: str | None,
    new_session: bool,
) -> dict[str, Any]:
    if session_id:
        return load_session(paths, session_id)

    explicit_bootstrap = bool(question or project or slug or new_session)
    current = None if new_session else load_current_session(paths)
    if current is not None:
        if not explicit_bootstrap:
            return current
        conflict = _current_session_conflict(
            current,
            question=" ".join(question.split()) if question else None,
            project=project,
            slug=slug,
        )
        if conflict:
            raise ValueError(f"{conflict}. Pass --new-session or --session to disambiguate.")
        return current

    export_prompt = _load_export_prompt(export_path)
    session_question = " ".join((question or export_prompt).split())
    return _bootstrap_session(
        paths,
        question=session_question,
        project=project,
        new_session=new_session,
        slug=slug,
    )


def _pdf_only_session(
    paths: VaultPaths,
    *,
    session_id: str | None,
    question: str | None,
    project: str | None,
    slug: str | None,
    new_session: bool,
) -> dict[str, Any]:
    if session_id:
        return load_session(paths, session_id)

    explicit_bootstrap = bool(question or project or slug or new_session)
    current = None if new_session else load_current_session(paths)
    if current is not None:
        if not explicit_bootstrap:
            return current
        conflict = _current_session_conflict(
            current,
            question=" ".join(question.split()) if question else None,
            project=project,
            slug=slug,
        )
        if conflict:
            raise ValueError(f"{conflict}. Pass --new-session or --session to disambiguate.")
        return current

    session_question = " ".join((question or "").split())
    if not session_question:
        raise ValueError("PDF-only intake needs --question when no current session is active.")
    return _bootstrap_session(
        paths,
        question=session_question,
        project=project,
        slug=slug,
        new_session=new_session,
    )


def _ensure_used_prompt_pack(
    paths: VaultPaths,
    session: dict[str, Any],
    *,
    export_path: Path,
    dry_run: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if dry_run or session.get("prompt_pack_path") or not session.get("query_path"):
        return {}, session
    export = _load_export(export_path)
    prompt = " ".join(export.prompt.split())
    if not prompt:
        return {}, session
    prompt_pack_summary = record_used_prompt_pack(
        paths.vault,
        query=Path(str(session["query_path"])).stem,
        project=str(session.get("project") or "") or None,
        prompt=prompt,
        export_path=export_path,
        exported_at=export.exported_at,
    )
    session = {**session, "prompt_pack_path": prompt_pack_summary["prompt_pack"]}
    session = write_session(paths, session)
    return prompt_pack_summary, session


def _run_staging_match_ui(paths: VaultPaths, staging_path: Path) -> dict[str, Any]:
    try:
        from .gui import GuiUnavailable
        from .gui_staging_match import choose_staging_match
    except Exception as exc:  # pragma: no cover - optional desktop dependency
        return {"opened": False, "resolved": 0, "error": str(exc)}

    imported: list[dict[str, Any]] = []

    def search_callback(
        query_title: str | None,
        query_pdf: str | None,
        query_min_score: int,
        query_limit: int,
        query_unselected_only: bool,
        progress,
    ) -> dict[str, Any]:
        return find_staged_run_matches(
            paths.vault,
            staging_path,
            title=query_title,
            pdf_path=Path(query_pdf).expanduser().resolve() if query_pdf else None,
            min_score=query_min_score,
            limit=query_limit,
            unselected_only=query_unselected_only,
            progress=progress,
        )

    def import_callback(row: dict[str, Any]) -> None:
        pdf_path = str(row.get("pdf_path") or "")
        run_id = str(row.get("run_id") or "")
        if not pdf_path or not run_id:
            raise ValueError("Choose a staged PDF and matching run result before importing.")
        summary = import_staged_pdf_match(
            paths.vault,
            run_id,
            pdf_path,
            rank=int(row["rank"]) if str(row.get("rank") or "").strip() else None,
            scholar_cid=str(row.get("scholar_cid") or "") or None,
            result_title=str(row.get("result_title") or "") or None,
            score=int(row["score"]) if str(row.get("score") or "").strip() else None,
            match_reason=str(row.get("reason") or "") or None,
            auto_enrich=True,
            archive_matched=True,
        )
        imported.append(summary)

    try:
        selected_run = choose_staging_match(
            str(paths.vault),
            str(staging_path),
            search_callback,
            min_score=60,
            limit=50,
            unselected_only=True,
            import_callback=import_callback,
        )
    except GuiUnavailable as exc:  # pragma: no cover - optional desktop dependency
        return {"opened": False, "resolved": 0, "error": str(exc)}

    return {
        "opened": True,
        "selected_run": selected_run,
        "resolved": len(imported),
        "imports": imported,
    }


def _blockers_from_import(summary: dict[str, Any]) -> list[str]:
    decisions = summary.get("decision_summary") or {}
    blockers: list[str] = []
    skipped = int(decisions.get("commit_proposals_skipped") or 0)
    if skipped:
        blockers.append(
            f"{skipped} staged PDF match(es) need manual review before they can be imported."
        )
    unmatched = int(summary.get("unmatched") or 0)
    selected = int(summary.get("selected") or 0)
    if not selected:
        blockers.append("No selected papers were imported from the Scholar Labs export.")
    elif unmatched and unmatched > selected:
        blockers.append(f"{unmatched} unmatched staged PDF/result entries need review.")
    return blockers


def _run_quality_checks(
    paths: VaultPaths,
    *,
    staging_path: Path | None = None,
    write_queues: bool = False,
    write_reports: bool = True,
    rebuild: bool = True,
) -> dict[str, Any]:
    checks: dict[str, Any] = {}
    checks["maintenance"] = maintenance_report(
        paths.vault,
        staging_path=staging_path,
        write_queue=write_queues,
    )
    checks["lint"] = lint_wiki(
        paths.vault,
        write_queue=write_queues,
        write_report=write_reports,
    )
    checks["eval"] = run_evals(paths.vault, write_queue=write_queues)
    checks["eval_report"] = render_eval_report(paths.vault)
    checks["compile_status"] = compile_status(paths.vault)
    checks["compile_doctor"] = compile_doctor(paths.vault)
    if rebuild:
        checks["rebuild"] = rebuild_vault(paths.vault)
    checks["bases"] = rebuild_bases(paths.vault)
    checks["bases_doctor"] = doctor_bases(paths.vault)
    checks["obsidian_doctor"] = doctor_obsidian(paths.vault)
    if write_queues:
        checks["self_improvement_dashboard"] = write_self_improvement_dashboard(paths.vault)
    return checks


def _link_pdf_imports(
    paths: VaultPaths,
    session: dict[str, Any],
    import_summary: dict[str, Any],
) -> dict[str, Any]:
    query_slug = Path(session["query_path"]).stem if session.get("query_path") else ""
    project_slug = str(session.get("project") or "")
    linked_query = 0
    linked_project = 0
    scaffolded = 0
    rows: list[dict[str, Any]] = []
    for row in import_summary.get("pdfs") or []:
        citekey = str(row.get("citekey") or "").strip()
        if not citekey:
            continue
        item: dict[str, Any] = {"citekey": citekey, "paper": row.get("paper")}
        if query_slug:
            query_summary = query_link_paper(paths.vault, query_slug, citekey)
            item["query_linked"] = query_summary.get("changed")
            linked_query += int(bool(query_summary.get("changed")))
        if project_slug:
            project_summary = project_link_paper(paths.vault, project_slug, citekey)
            item["project_linked"] = project_summary.get("changed")
            linked_project += int(bool(project_summary.get("changed")))
        scaffold_summary = compile_scaffold(paths.vault, citekey=citekey)
        item["digest_scaffold"] = scaffold_summary
        scaffolded += int(scaffold_summary.get("changed") or 0)
        rows.append(item)
    return {
        "count": len(rows),
        "linked_query": linked_query,
        "linked_project": linked_project,
        "digest_scaffolds_changed": scaffolded,
        "items": rows,
    }


def _intake_pdf_only(
    paths: VaultPaths,
    *,
    session_id: str | None,
    staging_path: Path,
    question: str | None,
    project: str | None,
    slug: str | None,
    new_session: bool,
    dry_run: bool,
    auto_enrich: bool,
) -> dict[str, Any]:
    session = _pdf_only_session(
        paths,
        session_id=session_id,
        question=question,
        project=project,
        slug=slug,
        new_session=new_session,
    )
    checks: dict[str, Any] = {}
    link_summary: dict[str, Any] = {}
    blockers: list[str] = []
    if dry_run:
        pdfs = sorted(staging_path.glob("*.pdf"))
        import_summary: dict[str, Any] = {
            "dry_run": True,
            "staging_folder": str(staging_path),
            "pdf_count": len(pdfs),
            "pdfs": [{"source": str(path), "title": path.stem} for path in pdfs],
        }
    else:
        import_summary = import_pdf_dropins(
            paths.vault,
            staging_path,
            auto_enrich=auto_enrich,
        )
        imported = int(import_summary.get("imported") or 0)
        if not imported:
            blockers.append("No PDFs were imported from the staging folder.")
        else:
            link_summary = _link_pdf_imports(paths, session, import_summary)
        session = update_session_status(
            paths,
            session,
            "blocked" if blockers else "imported",
            blockers=blockers,
            run_id="",
        )
        checks = _run_quality_checks(paths, staging_path=staging_path)

    report = write_session_report(
        paths,
        session,
        checks=checks,
        next_user_action=(
            "Resolve the blocker(s), then rerun `scholar-vault intake --pdf-only`."
            if blockers
            else "Run `scholar-vault answer \"synthesis question\"` when ready."
        ),
    )
    log_operation(
        paths.vault,
        kind="autopilot_intake_pdf_only",
        message=f"Imported PDF-only session `{session['id']}`.",
        command="scholar-vault intake --pdf-only",
        inputs={
            "session": session["id"],
            "staging": str(staging_path),
            "dry_run": dry_run,
        },
        outputs={
            "import": import_summary,
            "links": link_summary,
            "report": report,
            "blockers": blockers,
        },
        checks_run=list(checks.keys()),
        result="blocked" if blockers else ("dry-run" if dry_run else "imported"),
    )
    return {
        "vault": str(paths.vault),
        "session": session,
        "export": None,
        "staging": str(staging_path),
        "import": import_summary,
        "links": link_summary,
        "scaffold": link_summary,
        "checks": checks,
        "report": report,
        "blockers": blockers,
        "pdf_only": True,
    }


def intake(
    vault: Path | str,
    *,
    session_id: str | None = None,
    export: Path | None = None,
    staging: Path | None = None,
    question: str | None = None,
    project: str | None = None,
    slug: str | None = None,
    new_session: bool = False,
    pdf_only: bool = False,
    ui: bool = False,
    dry_run: bool = False,
    auto_enrich: bool = True,
    upgrade_pdfs: bool = True,
) -> dict[str, Any]:
    paths = initialize_vault(vault, rebuild=False)
    staging_path = _resolve_staging(staging)
    if pdf_only:
        return _intake_pdf_only(
            paths,
            session_id=session_id,
            staging_path=staging_path,
            question=question,
            project=project,
            slug=slug,
            new_session=new_session,
            dry_run=dry_run,
            auto_enrich=auto_enrich,
        )
    export_path = _resolve_export(export, staging=staging_path)
    session = _intake_session(
        paths,
        session_id=session_id,
        export_path=export_path,
        question=question,
        project=project,
        slug=slug,
        new_session=new_session,
    )
    prompt_pack_summary, session = _ensure_used_prompt_pack(
        paths,
        session,
        export_path=export_path,
        dry_run=dry_run,
    )
    query_slug = Path(session["query_path"]).stem if session.get("query_path") else None
    prompt_pack = session.get("prompt_pack_path") or None
    import_summary = import_scholar_labs_run(
        paths.vault,
        export_path,
        staging_path,
        dry_run=dry_run,
        commit=not dry_run,
        archive_matched=not dry_run,
        archive_export=not dry_run,
        auto_enrich=auto_enrich and not dry_run,
        upgrade_pdfs=upgrade_pdfs,
        prompt_pack=prompt_pack,
        query=query_slug,
    )
    blockers = _blockers_from_import(import_summary) if not dry_run else []
    run_id = str(import_summary.get("run") or "")
    ui_summary: dict[str, Any] = {}
    if blockers and ui and run_id and not dry_run:
        ui_summary = _run_staging_match_ui(paths, staging_path)
        if ui_summary.get("resolved"):
            import_summary = import_scholar_labs_run(
                paths.vault,
                export_path,
                staging_path,
                dry_run=False,
                commit=True,
                archive_matched=True,
                archive_export=True,
                auto_enrich=auto_enrich,
                upgrade_pdfs=upgrade_pdfs,
                prompt_pack=prompt_pack,
                query=query_slug,
            )
            blockers = _blockers_from_import(import_summary)
            run_id = str(import_summary.get("run") or run_id)
    scaffold_summary = {}
    checks: dict[str, Any] = {}
    if not dry_run and run_id:
        scaffold_summary = compile_scaffold(paths.vault, run_id=run_id, selected_only=True)
        status = "blocked" if blockers else "imported"
        session = update_session_status(paths, session, status, blockers=blockers, run_id=run_id)
        checks = _run_quality_checks(paths, staging_path=staging_path)
    report = write_session_report(
        paths,
        session if not dry_run else {**session, "run_id": run_id},
        checks=checks,
        next_user_action=(
            "Resolve the blocker(s), then rerun `scholar-vault intake`."
            if blockers
            else "Run `scholar-vault answer \"synthesis question\"` when ready."
        ),
    )
    log_operation(
        paths.vault,
        kind="autopilot_intake",
        message=f"Imported Scholar Labs export for session `{session['id']}`.",
        command="scholar-vault intake",
        inputs={
            "session": session["id"],
            "export": str(export_path),
            "staging": str(staging_path),
            "dry_run": dry_run,
            "ui": ui,
        },
        outputs={
            "run": run_id,
            "import": import_summary,
            "prompt_pack": prompt_pack_summary,
            "scaffold": scaffold_summary,
            "ui": ui_summary,
            "report": report,
            "blockers": blockers,
        },
        checks_run=list(checks.keys()),
        result="blocked" if blockers else ("dry-run" if dry_run else "imported"),
    )
    return {
        "vault": str(paths.vault),
        "session": session if not dry_run else {**session, "run_id": run_id},
        "export": str(export_path),
        "staging": str(staging_path),
        "import": import_summary,
        "prompt_pack": prompt_pack_summary,
        "scaffold": scaffold_summary,
        "ui": ui_summary,
        "checks": checks,
        "report": report,
        "blockers": blockers,
        "pdf_only": False,
    }


def _session_refs(paths: VaultPaths, session: dict[str, Any]) -> dict[str, set[str]]:
    refs = {
        "queries": {session.get("query_path") or ""},
        "runs": {session.get("run_id") or ""},
        "projects": {session.get("project") or ""},
        "papers": set(),
        "citekeys": set(),
    }
    run_id = session.get("run_id") or ""
    for run in load_run_records(paths):
        if run.slug != run_id:
            continue
        for result in run.results:
            if result.paper_card:
                refs["papers"].add(result.paper_card)
                refs["papers"].add(Path(result.paper_card).stem)
    return {key: {value for value in values if value} for key, values in refs.items()}


def _prioritize_session_queue(
    paths: VaultPaths,
    session: dict[str, Any],
    *,
    budget_papers: int | None = None,
) -> dict[str, Any]:
    refs = _session_refs(paths, session)
    changed = 0
    matched = 0
    prioritized: list[str] = []
    if not paths.task_queue.exists():
        return {"matched": 0, "changed": 0, "items": []}
    paper_budget = budget_papers if budget_papers is not None and budget_papers > 0 else None
    for path in sorted(paths.task_queue.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            continue
        haystack = " ".join(
            [
                str(data.get("query") or ""),
                str(data.get("project") or ""),
                " ".join(str(item) for item in data.get("runs") or []),
                " ".join(str(item) for item in data.get("files") or []),
                " ".join(str(item) for item in data.get("citekeys") or []),
                str(data.get("notes") or ""),
            ]
        )
        if not any(value and value in haystack for values in refs.values() for value in values):
            continue
        if paper_budget is not None and len(prioritized) >= paper_budget:
            continue
        matched += 1
        before = dict(data)
        if data.get("status") == "open":
            data["status"] = "planned"
        if data.get("priority") != "high":
            data["priority"] = "high"
        data["updated_at"] = now_iso()
        if data != before:
            write_yaml(path, data)
            changed += 1
        prioritized.append(ensure_relative(path, paths.vault))
    return {"matched": matched, "changed": changed, "items": prioritized}


def build_handoff_prompt(
    paths: VaultPaths,
    session: dict[str, Any],
    *,
    kind: str,
    synthesis_question: str = "",
    budget_papers: int | None = None,
) -> str:
    question = synthesis_question or session.get("question") or ""
    run_line = f"- Run: `{session.get('run_id')}`" if session.get("run_id") else "- Run: none yet"
    budget_line = (
        f"- Paper budget: focus on at most {budget_papers} paper(s) first."
        if budget_papers
        else "- Paper budget: use judgment; prefer a narrow focused pass."
    )
    vault_arg = f'--vault "{paths.vault}"'
    if kind == "post-import":
        objective = "Finish post-import PDF-grounded cleanup for the session."
    elif kind == "improve":
        objective = "Improve the imported session by clearing deterministic queue items first."
    elif kind == "answer":
        objective = f"Answer this synthesis question: {question}"
    else:
        raise ValueError("Unsupported handoff kind.")
    return "\n".join(
        [
            objective,
            "",
            "Session context:",
            f"- Session: `{session['id']}`",
            f"- User question: {session.get('question')}",
            f"- Query: `{session.get('query_path') or ''}`",
            f"- Prompt pack: `{session.get('prompt_pack_path') or ''}`",
            run_line,
            budget_line,
            "",
            "Operating rules:",
            "- Work in the vault passed with `-C`; do not use danger or full access.",
            (
                "- Before making scientific claims, open and read the linked PDFs, not only "
                "cards, summaries, or Scholar Labs text."
            ),
            (
                "- Scaffold missing paper digests, but fill or mark them compiled/reviewed "
                "only when compile guards pass."
            ),
            "- Keep page, figure, or table evidence in digest notes where possible.",
            (
                "- Draft or update focused syntheses under `syntheses/` and link them back "
                "to the query."
            ),
            (
                "- Run validation after edits: "
                f"`scholar-vault compile doctor {vault_arg}`, "
                f"`scholar-vault lint-wiki {vault_arg} --write-report`, "
                f"`scholar-vault eval run {vault_arg}`, "
                f"`scholar-vault eval report {vault_arg}`, "
                f"`scholar-vault rebuild {vault_arg}`, "
                f"`scholar-vault bases rebuild {vault_arg}`, and "
                f"`scholar-vault obsidian doctor {vault_arg}`."
            ),
            (
                "- Log the operation with `scholar-vault operations log` or the closest "
                "available workflow command."
            ),
            "",
            "Deliverables:",
            "- Updated paper digests or explicit blockers for papers that could not be read.",
            "- One focused synthesis or an update to an existing one.",
            "- Query/session links updated to include any synthesis path.",
            (
                "- A concise final note listing PDFs read, files changed, checks run, and "
                "remaining blockers."
            ),
        ]
    )


def improve(
    vault: Path | str,
    *,
    session_id: str | None = None,
    dry_run: bool = False,
    no_agent: bool = False,
    agent: str | None = None,
    budget_papers: int | None = None,
    codex_runner: CodexRunner | None = None,
) -> dict[str, Any]:
    paths = initialize_vault(vault, rebuild=False)
    session = _current_or_named_session(paths, session_id)
    checks: dict[str, Any] = {}
    prioritized = {"matched": 0, "changed": 0, "items": []}
    if dry_run:
        checks["compile_status"] = compile_status(paths.vault)
        checks["compile_doctor"] = compile_doctor(paths.vault)
        checks["bases_doctor"] = doctor_bases(paths.vault)
        checks["obsidian_doctor"] = doctor_obsidian(paths.vault)
    else:
        session = update_session_status(paths, session, "improving")
        checks = _run_quality_checks(paths, write_queues=True)
        prioritized = _prioritize_session_queue(paths, session, budget_papers=budget_papers)
        write_self_improvement_dashboard(paths.vault)
    handoff = {}
    codex = {}
    should_run_agent = agent == "codex" and not no_agent and not dry_run
    if should_run_agent:
        prompt = build_handoff_prompt(
            paths,
            session,
            kind="improve",
            budget_papers=budget_papers,
        )
        handoff = write_handoff(paths, kind="improve", session=session, prompt=prompt)
        codex = run_codex_handoff(paths.vault, Path(handoff["path"]), runner=codex_runner)
        if not codex.get("ok"):
            session = update_session_status(
                paths,
                session,
                "blocked",
                blockers=[
                    (
                        "Codex improve handoff failed with return code "
                        f"{codex.get('returncode')}."
                    )
                ],
            )
    report = {}
    if not dry_run:
        report = write_session_report(
            paths,
            session,
            checks=checks,
            handoff_path=str(handoff.get("handoff") or ""),
            next_user_action="Run `scholar-vault answer \"synthesis question\"` when ready.",
        )
        log_operation(
            paths.vault,
            kind="autopilot_improve",
            message=f"Improved session `{session['id']}`.",
            command="scholar-vault improve",
            inputs={
                "session": session["id"],
                "agent": agent,
                "budget_papers": budget_papers,
                "dry_run": dry_run,
            },
            outputs={
                "prioritized": prioritized,
                "handoff": handoff,
                "codex": codex,
                "report": report,
            },
            checks_run=list(checks.keys()),
            result="blocked" if session["status"] == "blocked" else "improving",
        )
    return {
        "vault": str(paths.vault),
        "session": session,
        "checks": checks,
        "prioritized": prioritized,
        "handoff": handoff,
        "codex": codex,
        "report": report,
        "dry_run": dry_run,
    }


def _linked_syntheses(paths: VaultPaths, session: dict[str, Any]) -> list[str]:
    query_ref = session.get("query_path") or ""
    if not query_ref:
        return session.get("synthesis_paths") or []
    query_path = paths.vault / query_ref
    if not query_path.exists():
        return session.get("synthesis_paths") or []
    frontmatter, _ = read_frontmatter_markdown(query_path)
    syntheses = frontmatter.get("linked_syntheses") or []
    if isinstance(syntheses, str):
        syntheses = [syntheses]
    return [str(item) for item in syntheses if str(item).strip()]


def answer(
    vault: Path | str,
    synthesis_question: str,
    *,
    session_id: str | None = None,
    agent: str | None = None,
    codex_runner: CodexRunner | None = None,
) -> dict[str, Any]:
    paths = initialize_vault(vault, rebuild=False)
    session = _current_or_named_session(paths, session_id)
    prompt = build_handoff_prompt(
        paths,
        session,
        kind="answer",
        synthesis_question=synthesis_question,
    )
    handoff = write_handoff(
        paths,
        kind="answer",
        session=session,
        prompt=prompt,
        title=f"Answer handoff: {synthesis_question}",
    )
    codex = {}
    if agent == "codex":
        codex = run_codex_handoff(paths.vault, Path(handoff["path"]), runner=codex_runner)
        syntheses = _linked_syntheses(paths, session)
        session = update_session_status(
            paths,
            session,
            "answered" if codex.get("ok") else "blocked",
            blockers=[]
            if codex.get("ok")
            else [f"Codex answer handoff failed with return code {codex.get('returncode')}."],
            synthesis_paths=syntheses,
        )
        report = write_session_report(
            paths,
            session,
            handoff_path=str(handoff.get("handoff") or ""),
            next_user_action="Review the linked synthesis and archive the session when finished.",
        )
        log_operation(
            paths.vault,
            kind="autopilot_answer",
            message=f"Ran answer handoff for session `{session['id']}`.",
            command="scholar-vault answer",
            inputs={
                "session": session["id"],
                "synthesis_question": synthesis_question,
                "agent": agent,
            },
            outputs={"handoff": handoff, "codex": codex, "report": report},
            result=session["status"],
        )
    else:
        report = write_session_report(
            paths,
            session,
            handoff_path=str(handoff.get("handoff") or ""),
            next_user_action=f"Run `{handoff['command']}`.",
        )
        log_operation(
            paths.vault,
            kind="autopilot_answer_handoff",
            message=f"Wrote answer handoff for session `{session['id']}`.",
            command="scholar-vault answer",
            inputs={"session": session["id"], "synthesis_question": synthesis_question},
            outputs={"handoff": handoff, "report": report},
            result="handoff-ready",
        )
    return {
        "vault": str(paths.vault),
        "session": session,
        "handoff": handoff,
        "codex": codex,
        "report": report,
    }


def create_handoff(
    vault: Path | str,
    *,
    kind: str,
    session_id: str | None = None,
    synthesis_question: str = "",
    budget_papers: int | None = None,
) -> dict[str, Any]:
    paths = initialize_vault(vault, rebuild=False)
    session = _current_or_named_session(paths, session_id)
    prompt = build_handoff_prompt(
        paths,
        session,
        kind=kind,
        synthesis_question=synthesis_question,
        budget_papers=budget_papers,
    )
    handoff = write_handoff(paths, kind=kind, session=session, prompt=prompt)
    return {"vault": str(paths.vault), "session": session, "handoff": handoff}


def run_handoff(
    vault: Path | str,
    *,
    kind: str,
    session_id: str | None = None,
    synthesis_question: str = "",
    budget_papers: int | None = None,
    codex_runner: CodexRunner | None = None,
) -> dict[str, Any]:
    paths = initialize_vault(vault, rebuild=False)
    handoff_summary = create_handoff(
        paths.vault,
        kind=kind,
        session_id=session_id,
        synthesis_question=synthesis_question,
        budget_papers=budget_papers,
    )
    handoff = handoff_summary["handoff"]
    codex = run_codex_handoff(paths.vault, Path(handoff["path"]), runner=codex_runner)
    return {**handoff_summary, "codex": codex}


def session_current(vault: Path | str) -> dict[str, Any]:
    paths = initialize_vault(vault, rebuild=False)
    session = load_current_session(paths)
    return {"vault": str(paths.vault), "session": session}


def session_list(vault: Path | str) -> dict[str, Any]:
    paths = initialize_vault(vault, rebuild=False)
    sessions = list_sessions(paths)
    return {"vault": str(paths.vault), "count": len(sessions), "sessions": sessions}


def session_show(vault: Path | str, session_id: str | None = None) -> dict[str, Any]:
    paths = initialize_vault(vault, rebuild=False)
    session = _current_or_named_session(paths, session_id)
    return {"vault": str(paths.vault), "session": session}


def session_archive(vault: Path | str, session_id: str | None = None) -> dict[str, Any]:
    paths = initialize_vault(vault, rebuild=False)
    session = archive_session(paths, session_id=session_id)
    write_session(paths, session, make_current=True)
    log_operation(
        paths.vault,
        kind="autopilot_session_archive",
        message=f"Archived session `{session['id']}`.",
        command="scholar-vault session archive",
        outputs={"session": session["id"]},
        result="archived",
    )
    return {"vault": str(paths.vault), "session": session}
