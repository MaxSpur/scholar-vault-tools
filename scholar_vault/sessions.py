from __future__ import annotations

import subprocess
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from .models import RunRecord, SourceCard
from .sources import (
    VaultPaths,
    ensure_relative,
    load_run_records,
    load_source_cards,
    read_frontmatter_markdown,
    slugify_text,
    write_text,
    write_yaml,
)

SESSION_STATUSES = (
    "asked",
    "prompt_ready",
    "waiting_for_labs_export",
    "imported",
    "improving",
    "answered",
    "blocked",
    "archived",
)
ACTIVE_SESSION_STATUSES = tuple(status for status in SESSION_STATUSES if status != "archived")
HANDOFF_KINDS = ("post-import", "improve", "answer")


def now_iso() -> str:
    return datetime.now().astimezone().replace(microsecond=0).isoformat()


def session_file(paths: VaultPaths, session_id: str) -> Path:
    return paths.sessions / f"{session_id}.yaml"


def current_session_file(paths: VaultPaths) -> Path:
    return paths.sessions / "current.yaml"


def handoff_file(paths: VaultPaths, handoff_id: str) -> Path:
    return paths.handoffs / f"{handoff_id}.md"


def _read_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _session_id(question: str, directory: Path, *, now: str | None = None) -> str:
    timestamp = datetime.fromisoformat(now or now_iso()).strftime("%Y%m%dT%H%M%S")
    base = f"{timestamp}-{slugify_text(question, max_length=54) or 'session'}"
    candidate = base
    suffix = 2
    while (directory / f"{candidate}.yaml").exists():
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate


def _normalize_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def normalize_session(data: dict[str, Any]) -> dict[str, Any]:
    session = dict(data)
    status = str(session.get("status") or "asked")
    if status not in SESSION_STATUSES:
        status = "blocked"
    timestamps = session.get("timestamps") if isinstance(session.get("timestamps"), dict) else {}
    created = str(timestamps.get("created_at") or session.get("created_at") or now_iso())
    updated = str(timestamps.get("updated_at") or session.get("updated_at") or created)
    normalized = {
        "id": str(session.get("id") or ""),
        "status": status,
        "question": str(session.get("question") or ""),
        "project": str(session.get("project") or ""),
        "query_path": str(session.get("query_path") or ""),
        "prompt_pack_path": str(session.get("prompt_pack_path") or ""),
        "run_id": str(session.get("run_id") or ""),
        "synthesis_paths": _normalize_string_list(session.get("synthesis_paths")),
        "blockers": _normalize_string_list(session.get("blockers")),
        "timestamps": {**timestamps, "created_at": created, "updated_at": updated},
    }
    return normalized


def _current_payload(paths: VaultPaths, session: dict[str, Any]) -> dict[str, Any]:
    payload = dict(session)
    payload["session_path"] = ensure_relative(session_file(paths, session["id"]), paths.vault)
    return payload


def write_session(
    paths: VaultPaths,
    session: dict[str, Any],
    *,
    make_current: bool = True,
) -> dict[str, Any]:
    normalized = normalize_session(session)
    if not normalized["id"]:
        raise ValueError("Session id must not be empty.")
    normalized["timestamps"]["updated_at"] = now_iso()
    paths.sessions.mkdir(parents=True, exist_ok=True)
    write_yaml(session_file(paths, normalized["id"]), normalized)
    if make_current:
        write_yaml(current_session_file(paths), _current_payload(paths, normalized))
    return normalized


def load_session(paths: VaultPaths, session_id: str) -> dict[str, Any]:
    normalized = (session_id or "").strip().removesuffix(".yaml")
    path = session_file(paths, normalized)
    if not path.exists():
        raise ValueError(f"Session does not exist: {normalized}")
    return normalize_session(_read_yaml(path))


def load_current_session(
    paths: VaultPaths,
    *,
    include_archived: bool = False,
) -> dict[str, Any] | None:
    current_path = current_session_file(paths)
    if not current_path.exists():
        return None
    current = normalize_session(_read_yaml(current_path))
    session_id = current.get("id") or current.get("current_session")
    if session_id and session_file(paths, str(session_id)).exists():
        current = load_session(paths, str(session_id))
    if current["status"] == "archived" and not include_archived:
        return None
    return current


def create_or_reuse_session(
    paths: VaultPaths,
    *,
    question: str,
    project: str | None = None,
    query_path: str = "",
    prompt_pack_path: str = "",
    new_session: bool = False,
) -> tuple[dict[str, Any], bool]:
    cleaned_question = " ".join((question or "").split())
    if not cleaned_question:
        raise ValueError("Question text must not be empty.")
    current = load_current_session(paths)
    if (
        current
        and not new_session
        and current["question"] == cleaned_question
        and current["project"] == (project or "")
        and current["status"] in {"asked", "prompt_ready", "waiting_for_labs_export"}
    ):
        if query_path and current.get("query_path") != query_path:
            current["query_path"] = query_path
        if prompt_pack_path and current.get("prompt_pack_path") != prompt_pack_path:
            current["prompt_pack_path"] = prompt_pack_path
        return write_session(paths, current), False

    paths.sessions.mkdir(parents=True, exist_ok=True)
    created = now_iso()
    session = {
        "id": _session_id(cleaned_question, paths.sessions, now=created),
        "status": "asked",
        "question": cleaned_question,
        "project": project or "",
        "query_path": query_path,
        "prompt_pack_path": prompt_pack_path,
        "run_id": "",
        "synthesis_paths": [],
        "blockers": [],
        "timestamps": {
            "created_at": created,
            "updated_at": created,
            "asked_at": created,
        },
    }
    return write_session(paths, session), True


def update_session_status(
    paths: VaultPaths,
    session: dict[str, Any],
    status: str,
    *,
    blockers: list[str] | None = None,
    run_id: str | None = None,
    prompt_pack_path: str | None = None,
    synthesis_paths: list[str] | None = None,
    make_current: bool = True,
) -> dict[str, Any]:
    if status not in SESSION_STATUSES:
        raise ValueError(f"Unsupported session status: {status}")
    updated = normalize_session(session)
    updated["status"] = status
    if blockers is not None:
        updated["blockers"] = blockers
    if run_id is not None:
        updated["run_id"] = run_id
    if prompt_pack_path is not None:
        updated["prompt_pack_path"] = prompt_pack_path
    if synthesis_paths is not None:
        updated["synthesis_paths"] = sorted(set(synthesis_paths), key=str.casefold)
    stamp_name = f"{status}_at"
    updated["timestamps"][stamp_name] = now_iso()
    return write_session(paths, updated, make_current=make_current)


def list_sessions(paths: VaultPaths) -> list[dict[str, Any]]:
    if not paths.sessions.exists():
        return []
    current = load_current_session(paths, include_archived=True)
    current_id = current["id"] if current else ""
    rows: list[dict[str, Any]] = []
    for path in sorted(paths.sessions.glob("*.yaml")):
        if path.name == "current.yaml":
            continue
        session = normalize_session(_read_yaml(path))
        session["path"] = ensure_relative(path, paths.vault)
        session["current"] = session["id"] == current_id
        rows.append(session)
    return sorted(
        rows,
        key=lambda item: (str(item["timestamps"].get("updated_at") or ""), item["id"]),
        reverse=True,
    )


def archive_session(paths: VaultPaths, session_id: str | None = None) -> dict[str, Any]:
    session = load_session(paths, session_id) if session_id else load_current_session(paths)
    if session is None:
        raise ValueError("No current session is active.")
    archived = update_session_status(paths, session, "archived", make_current=True)
    return archived


def _run_lookup(paths: VaultPaths, run_id: str) -> RunRecord | None:
    for run in load_run_records(paths):
        if run.slug == run_id:
            return run
    return None


def _cards_by_ref(paths: VaultPaths) -> dict[str, SourceCard]:
    lookup: dict[str, SourceCard] = {}
    for card in load_source_cards(paths):
        refs = {card.slug, f"papers/{card.slug}.md"}
        if card.citekey:
            refs.add(card.citekey)
        for ref in refs:
            lookup[ref] = card
    return lookup


def _digest_status(paths: VaultPaths, card: SourceCard) -> tuple[str, str]:
    digest_ref = card.paper_digest or ""
    if digest_ref and (paths.vault / digest_ref).exists():
        frontmatter, _ = read_frontmatter_markdown(paths.vault / digest_ref)
        return str(frontmatter.get("status") or card.compiled_status), digest_ref
    return card.compiled_status, digest_ref


def session_report_path(paths: VaultPaths, session: dict[str, Any]) -> Path:
    query_path = str(session.get("query_path") or "")
    if query_path.startswith("queries/") and query_path.endswith(".md"):
        return paths.queries / Path(query_path).stem / "session-report.md"
    return paths.reports / "latest.md"


def write_session_report(
    paths: VaultPaths,
    session: dict[str, Any],
    *,
    checks: dict[str, Any] | None = None,
    next_user_action: str = "",
    handoff_path: str = "",
) -> dict[str, Any]:
    session = normalize_session(session)
    run = _run_lookup(paths, session.get("run_id") or "")
    cards = _cards_by_ref(paths)
    imported: list[dict[str, str]] = []
    pdfs: list[str] = []
    digest_rows: list[dict[str, str]] = []
    if run:
        for result in run.results:
            if result.status != "selected" or not result.paper_card:
                continue
            card = cards.get(result.paper_card) or cards.get(Path(result.paper_card).stem)
            title = card.title if card else result.title
            pdf = card.pdf if card and card.pdf else ""
            status, digest_ref = _digest_status(paths, card) if card else ("missing", "")
            imported.append(
                {
                    "paper": result.paper_card,
                    "title": title,
                    "pdf": pdf,
                }
            )
            if pdf:
                pdfs.append(pdf)
            digest_rows.append(
                {
                    "paper": result.paper_card,
                    "digest": digest_ref or "(not scaffolded)",
                    "status": status,
                }
            )

    path = session_report_path(paths, session)
    prompt_pack = session.get("prompt_pack_path") or "(none)"
    run_id = session.get("run_id") or "(none)"
    next_action = next_user_action or _default_next_action(session)
    lines = [
        f"# Session Report: {session['question']}",
        "",
        f"- Session: `{session['id']}`",
        f"- Status: `{session['status']}`",
        f"- Project: `{session['project'] or '-'}`",
        f"- Query: `{session['query_path'] or '-'}`",
        f"- Prompt pack: `{prompt_pack}`",
        f"- Run: `{run_id}`",
    ]
    if handoff_path:
        lines.append(f"- Handoff: `{handoff_path}`")
    lines.extend(["", "## Imported papers"])
    if imported:
        for row in imported:
            pdf = f"; PDF: `{row['pdf']}`" if row["pdf"] else ""
            lines.append(f"- `{row['paper']}` - {row['title']}{pdf}")
    else:
        lines.append("No imported papers linked yet.")
    lines.extend(["", "## PDFs"])
    if pdfs:
        lines.extend(f"- `{pdf}`" for pdf in sorted(set(pdfs), key=str.casefold))
    else:
        lines.append("No linked PDFs yet.")
    lines.extend(["", "## Blockers"])
    if session["blockers"]:
        lines.extend(f"- {blocker}" for blocker in session["blockers"])
    else:
        lines.append("No active blockers recorded.")
    lines.extend(["", "## Digest status"])
    if digest_rows:
        for row in digest_rows:
            lines.append(f"- `{row['paper']}` -> `{row['status']}` ({row['digest']})")
    else:
        lines.append("No digest status available yet.")
    lines.extend(["", "## Syntheses"])
    if session["synthesis_paths"]:
        lines.extend(f"- `{path}`" for path in session["synthesis_paths"])
    else:
        lines.append("No linked syntheses yet.")
    if checks:
        lines.extend(["", "## Checks"])
        for name, summary in checks.items():
            if isinstance(summary, dict):
                ok = summary.get("ok")
                count = summary.get("count")
                counts = summary.get("counts")
                detail = []
                if ok is not None:
                    detail.append(f"ok={ok}")
                if count is not None:
                    detail.append(f"count={count}")
                if counts:
                    detail.append(f"counts={counts}")
                lines.append(f"- {name}: {', '.join(detail) if detail else 'completed'}")
            else:
                lines.append(f"- {name}: {summary}")
    lines.extend(["", "## Next user action", next_action, ""])
    write_text(path, "\n".join(lines))
    return {
        "path": ensure_relative(path, paths.vault),
        "imported_papers": len(imported),
        "pdfs": len(set(pdfs)),
        "digest_rows": len(digest_rows),
    }


def _default_next_action(session: dict[str, Any]) -> str:
    status = session.get("status")
    if status == "waiting_for_labs_export":
        return (
            "Run the prompt in Scholar Labs, download the PDFs and JSON export, then run "
            "`scholar-vault intake`."
        )
    if status == "imported":
        return "Run `scholar-vault answer \"synthesis question\"` or `scholar-vault improve`."
    if status == "blocked":
        return "Resolve the listed blocker, then rerun the last command."
    if status == "answered":
        return "Review the linked synthesis and archive the session when finished."
    return "Continue the session workflow from the current status."


def write_handoff(
    paths: VaultPaths,
    *,
    kind: str,
    session: dict[str, Any],
    prompt: str,
    title: str | None = None,
) -> dict[str, Any]:
    if kind not in HANDOFF_KINDS:
        raise ValueError(f"Handoff kind must be one of: {', '.join(HANDOFF_KINDS)}")
    session = normalize_session(session)
    created = now_iso()
    base = f"{datetime.fromisoformat(created).strftime('%Y%m%dT%H%M%S')}-{kind}-{session['id']}"
    handoff_id = slugify_text(base, max_length=110)
    path = handoff_file(paths, handoff_id)
    suffix = 2
    while path.exists():
        path = handoff_file(paths, f"{handoff_id}-{suffix}")
        suffix += 1
    frontmatter = {
        "type": "codex_handoff",
        "kind": kind,
        "session": session["id"],
        "question": session["question"],
        "query": session["query_path"],
        "run": session["run_id"],
        "created_at": created,
        "status": "ready",
    }
    body_title = title or f"Codex {kind} handoff"
    text = [
        "---",
        yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True).strip(),
        "---",
        "",
        f"# {body_title}",
        "",
        prompt.strip(),
        "",
    ]
    write_text(path, "\n".join(text))
    return {
        "handoff": ensure_relative(path, paths.vault),
        "path": str(path),
        "kind": kind,
        "command": codex_command(paths.vault, path),
    }


def codex_command(vault: Path, handoff_path: Path) -> str:
    return f'codex exec -C "{vault}" --sandbox workspace-write "$(cat "{handoff_path}")"'


CodexRunner = Callable[[list[str], str, Path], subprocess.CompletedProcess[str]]


def run_codex_handoff(
    vault: Path,
    handoff_path: Path,
    *,
    runner: CodexRunner | None = None,
) -> dict[str, Any]:
    prompt = handoff_path.read_text(encoding="utf-8")
    args = ["codex", "exec", "-C", str(vault), "--sandbox", "workspace-write", prompt]
    actual_runner = runner or _default_codex_runner
    completed = actual_runner(args, prompt, vault)
    return {
        "args": args[:-1] + ["<handoff-prompt>"],
        "returncode": completed.returncode,
        "stdout": completed.stdout or "",
        "stderr": completed.stderr or "",
        "ok": completed.returncode == 0,
    }


def _default_codex_runner(
    args: list[str],
    prompt: str,
    cwd: Path,
) -> subprocess.CompletedProcess[str]:
    _ = prompt
    return subprocess.run(args, cwd=cwd, text=True, capture_output=True, check=False)
