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
from .importer import import_scholar_labs_run, initialize_vault
from .labs_prompts import generate_prompt_pack, resolve_prompt_pack
from .maintenance import maintenance_report
from .obsidian_setup import doctor_obsidian
from .queries import query_create
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


def _current_or_named_session(paths: VaultPaths, session_id: str | None = None) -> dict[str, Any]:
    if session_id:
        return load_session(paths, session_id)
    session = load_current_session(paths)
    if session is None:
        raise ValueError("No current session is active. Run `scholar-vault ask \"...\"` first.")
    return session


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


def intake(
    vault: Path | str,
    *,
    session_id: str | None = None,
    export: Path | None = None,
    staging: Path | None = None,
    dry_run: bool = False,
    auto_enrich: bool = True,
    upgrade_pdfs: bool = True,
) -> dict[str, Any]:
    paths = initialize_vault(vault, rebuild=False)
    session = _current_or_named_session(paths, session_id)
    staging_path = _resolve_staging(staging)
    export_path = _resolve_export(export, staging=staging_path)
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
        },
        outputs={
            "run": run_id,
            "import": import_summary,
            "scaffold": scaffold_summary,
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
        "scaffold": scaffold_summary,
        "checks": checks,
        "report": report,
        "blockers": blockers,
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
