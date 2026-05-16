from __future__ import annotations

import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from .models import RunRecord, SourceCard
from .obsidian import _as_string_list, _card_has_valid_pdf, _card_id, _card_ref
from .render import render_paper_markdown
from .sources import (
    VaultPaths,
    dump_frontmatter,
    ensure_relative,
    load_run_records,
    load_source_cards,
    read_frontmatter_markdown,
    write_text,
)

DIGEST_STATUSES = ("uncompiled", "draft", "compiled", "stale", "reviewed")
MARKABLE_DIGEST_STATUSES = ("draft", "compiled", "stale", "reviewed")
DIGEST_EVIDENCE_LEVELS = ("pdf_grounded", "metadata_only", "mixed")
DIGEST_REQUIRED_FIELDS = (
    "type",
    "citekey",
    "paper",
    "pdf",
    "status",
    "evidence_level",
    "compiled_at",
    "reviewed_at",
    "linked_queries",
    "linked_projects",
    "linked_concepts",
    "linked_syntheses",
    "source_pages_checked",
    "figures_checked",
    "tables_checked",
)
DIGEST_TEMPLATE_SECTIONS = (
    "Core contribution",
    "Problem addressed",
    "Method/model/apparatus",
    "Dataset/corpus/materials",
    "Evaluation design",
    "Main findings",
    "Author-stated limitations",
    "Reader-inferred limitations",
    "Reusable definitions",
    "Claims worth tracking",
    "Figures/tables worth revisiting",
    "Links to update",
    "Open questions",
    "Evidence notes",
)
NEEDS_ACTION_STATUSES = {"uncompiled", "draft", "stale"}
DIGEST_COMPLETION_STATUSES = {"compiled", "reviewed"}
DIGEST_TEMPLATE_PLACEHOLDER_RE = re.compile(
    r"To be filled by an agent or reviewer after reading the PDF",
    re.IGNORECASE,
)


def _now_iso() -> str:
    return datetime.now().astimezone().replace(microsecond=0).isoformat()


def _initialize_vault(vault: Path | str) -> VaultPaths:
    from .importer import initialize_vault

    return initialize_vault(vault, rebuild=False)


def _refresh_outputs(vault: Path | str) -> dict[str, Any]:
    from .bases import rebuild_bases
    from .rebuild import rebuild_vault

    rebuild_summary = rebuild_vault(vault)
    bases_summary = rebuild_bases(vault)
    return {"rebuild": rebuild_summary, "bases": bases_summary}


def _safe_digest_stem(value: str) -> str:
    raw = (value or "").strip().strip("/")
    if raw.endswith(".md"):
        raw = raw[: -len(".md")]
    candidate = Path(raw)
    if (
        candidate.is_absolute()
        or len(candidate.parts) != 1
        or any(part in {"", ".", ".."} for part in candidate.parts)
    ):
        raise ValueError("Digest citekey must stay inside paper-digests/.")
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", raw).strip("._-")
    if not safe:
        raise ValueError("Digest citekey must produce a non-empty safe filename.")
    if safe in {".", ".."} or "/" in safe:
        raise ValueError("Digest citekey must stay inside paper-digests/.")
    return safe


def digest_path_for_card(paths: VaultPaths, card: SourceCard) -> Path:
    return paths.paper_digests / f"{_safe_digest_stem(_card_id(card))}.md"


def digest_ref_for_card(paths: VaultPaths, card: SourceCard) -> str:
    return ensure_relative(digest_path_for_card(paths, card), paths.vault)


def _resolve_card(paths: VaultPaths, citekey: str) -> SourceCard:
    normalized = (citekey or "").strip().strip("/")
    stem = Path(normalized).stem
    for card in load_source_cards(paths):
        candidates = {card.slug, _card_ref(card), f"papers/{card.slug}.md"}
        if card.citekey:
            candidates.add(card.citekey)
        if normalized in candidates or stem == card.slug:
            return card
    raise ValueError(f"No paper card found for citekey or slug: {citekey}")


def _cards_by_ref(paths: VaultPaths) -> dict[str, SourceCard]:
    lookup: dict[str, SourceCard] = {}
    for card in load_source_cards(paths):
        lookup[_card_ref(card)] = card
        lookup[card.slug] = card
        if card.citekey:
            lookup[card.citekey] = card
        digest_ref = card.paper_digest
        if digest_ref:
            lookup[digest_ref] = card
    return lookup


def _save_card(paths: VaultPaths, card: SourceCard) -> None:
    write_text(paths.papers / f"{card.slug}.md", render_paper_markdown(card))


def _digest_frontmatter(paths: VaultPaths, card: SourceCard, *, status: str) -> dict[str, Any]:
    return {
        "type": "paper_digest",
        "citekey": _card_id(card),
        "paper": _card_ref(card),
        "pdf": card.pdf,
        "status": status,
        "evidence_level": "metadata_only",
        "compiled_at": None,
        "reviewed_at": None,
        "linked_queries": list(card.linked_queries),
        "linked_projects": list(card.linked_projects),
        "linked_concepts": [],
        "linked_syntheses": [],
        "source_pages_checked": [],
        "figures_checked": [],
        "tables_checked": [],
    }


def normalize_digest_frontmatter(
    frontmatter: dict[str, Any],
    *,
    card: SourceCard | None = None,
    paths: VaultPaths | None = None,
) -> dict[str, Any]:
    digest = dict(frontmatter)
    if card is not None and paths is not None:
        defaults = _digest_frontmatter(paths, card, status=str(digest.get("status") or "draft"))
        defaults.update(digest)
        digest = defaults
    digest["type"] = "paper_digest"
    digest["status"] = str(digest.get("status") or "draft")
    digest["evidence_level"] = str(digest.get("evidence_level") or "metadata_only")
    for field in (
        "linked_queries",
        "linked_projects",
        "linked_concepts",
        "linked_syntheses",
        "source_pages_checked",
        "figures_checked",
        "tables_checked",
    ):
        digest[field] = _as_string_list(digest.get(field))
    for field in ("compiled_at", "reviewed_at", "citekey", "paper", "pdf"):
        value = digest.get(field)
        digest[field] = str(value) if value not in {None, ""} else None
    return digest


def _digest_body(card: SourceCard) -> str:
    paper_link = f"../{_card_ref(card)}"
    pdf_link = f"../{card.pdf}" if card.pdf else ""
    lines = [
        f"# {_card_id(card)} digest",
        "",
        "This scaffold is a place for PDF-grounded interpretation. The CLI created the "
        "structure only; an agent or reviewer must fill it from the linked PDF.",
        "",
    ]
    for section in DIGEST_TEMPLATE_SECTIONS:
        lines.extend([f"## {section}", ""])
        if section == "Evidence notes":
            lines.extend(
                [
                    f"- Paper card: [{_card_ref(card)}]({paper_link})",
                    f"- PDF: [{card.pdf}]({pdf_link})" if card.pdf else "- PDF: Missing",
                    "- Record page, figure, and table locations in frontmatter and bullets above "
                    "when possible.",
                    "- Do not promote Scholar Labs summaries into claims unless the PDF "
                    "confirms them.",
                ]
            )
        else:
            lines.append(
                "_To be filled by an agent or reviewer after reading the PDF. Include page, "
                "figure, or table evidence where possible._"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_digest_markdown(paths: VaultPaths, card: SourceCard, *, status: str = "draft") -> str:
    frontmatter = dump_frontmatter(_digest_frontmatter(paths, card, status=status)).strip()
    return f"---\n{frontmatter}\n---\n\n{_digest_body(card)}"


def _write_digest(path: Path, frontmatter: dict[str, Any], body: str) -> None:
    write_text(path, f"---\n{dump_frontmatter(frontmatter).strip()}\n---\n\n{body.strip()}\n")


def _template_placeholder_sections(body: str) -> list[str]:
    sections: list[str] = []
    matches = list(re.finditer(r"^##\s+(.+?)\s*$", body, flags=re.MULTILINE))
    for index, match in enumerate(matches):
        section = match.group(1).strip()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        if DIGEST_TEMPLATE_PLACEHOLDER_RE.search(body[start:end]):
            sections.append(section)
    if not sections and DIGEST_TEMPLATE_PLACEHOLDER_RE.search(body):
        sections.append("body")
    return sections


def digest_completion_issues(
    paths: VaultPaths,
    digest_path: Path,
    digest_frontmatter: dict[str, Any],
    body: str,
    *,
    card: SourceCard | None = None,
    target_status: str | None = None,
) -> list[dict[str, Any]]:
    status = str(target_status or digest_frontmatter.get("status") or "")
    if status not in DIGEST_COMPLETION_STATUSES:
        return []

    digest_ref = ensure_relative(digest_path, paths.vault)
    citekey = str(
        digest_frontmatter.get("citekey") or (card and _card_id(card)) or digest_path.stem
    )
    issues: list[dict[str, Any]] = []
    evidence_level = str(digest_frontmatter.get("evidence_level") or "")
    if evidence_level == "metadata_only":
        issues.append(
            {
                "kind": "compiled/reviewed digest still marked metadata_only",
                "check": "paper-digest-ready-metadata-only",
                "field": "evidence_level",
                "message": (
                    f"{digest_ref} is being marked {status} while evidence_level is "
                    "metadata_only."
                ),
                "citekey": citekey,
            }
        )
    if not _as_string_list(digest_frontmatter.get("source_pages_checked")):
        issues.append(
            {
                "kind": "compiled/reviewed digest has no source_pages_checked",
                "check": "paper-digest-ready-missing-source-pages",
                "field": "source_pages_checked",
                "message": (
                    f"{digest_ref} is being marked {status} without source_pages_checked."
                ),
                "citekey": citekey,
            }
        )

    pdf_ref = str(digest_frontmatter.get("pdf") or "").strip()
    if not pdf_ref:
        issues.append(
            {
                "kind": "compiled/reviewed digest has no linked PDF",
                "check": "paper-digest-ready-missing-pdf-link",
                "field": "pdf",
                "message": f"{digest_ref} is being marked {status} without a linked PDF.",
                "citekey": citekey,
            }
        )
    elif not (paths.vault / pdf_ref).exists():
        issues.append(
            {
                "kind": "compiled/reviewed digest PDF link is missing",
                "check": "paper-digest-ready-missing-pdf-link",
                "field": "pdf",
                "message": f"{digest_ref} links missing PDF {pdf_ref}.",
                "citekey": citekey,
                "pdf": pdf_ref,
            }
        )
    elif card is not None and not _card_has_valid_pdf(paths, card):
        issues.append(
            {
                "kind": "compiled/reviewed digest paper card has no valid PDF",
                "check": "paper-digest-ready-missing-pdf-link",
                "field": "pdf",
                "message": f"{digest_ref} links a paper card without a valid PDF.",
                "citekey": citekey,
                "pdf": pdf_ref,
            }
        )

    placeholder_sections = _template_placeholder_sections(body)
    if placeholder_sections:
        issues.append(
            {
                "kind": "compiled/reviewed digest still has template placeholders",
                "check": "paper-digest-ready-template-placeholders",
                "field": "body",
                "message": f"{digest_ref} still has unfilled digest template placeholders.",
                "citekey": citekey,
                "sections": placeholder_sections,
            }
        )
    return issues


def _sync_card_to_digest(
    paths: VaultPaths,
    card: SourceCard,
    *,
    status: str,
    digest_ref: str,
    digest_frontmatter: dict[str, Any] | None = None,
) -> bool:
    changed = False
    if card.paper_digest != digest_ref:
        card.paper_digest = digest_ref
        changed = True
    if card.compiled_status != status:
        card.compiled_status = status
        changed = True
    if digest_frontmatter:
        evidence_level = digest_frontmatter.get("evidence_level")
        if evidence_level and card.evidence_level != evidence_level:
            card.evidence_level = str(evidence_level)
            changed = True
    return changed


def _scaffold_card(paths: VaultPaths, card: SourceCard, *, force: bool = False) -> dict[str, Any]:
    digest_path = digest_path_for_card(paths, card)
    digest_ref = ensure_relative(digest_path, paths.vault)
    state = "unchanged"
    digest_changed = False
    existed_before = digest_path.exists()
    if existed_before and not force:
        frontmatter, _ = read_frontmatter_markdown(digest_path)
        digest_frontmatter = normalize_digest_frontmatter(frontmatter, card=card, paths=paths)
        status = str(digest_frontmatter.get("status") or "draft")
    else:
        content = render_digest_markdown(paths, card, status="draft")
        write_text(digest_path, content)
        digest_frontmatter = _digest_frontmatter(paths, card, status="draft")
        status = "draft"
        state = "overwritten" if existed_before and force else "created"
        digest_changed = True
    card_changed = _sync_card_to_digest(
        paths,
        card,
        status=status,
        digest_ref=digest_ref,
        digest_frontmatter=digest_frontmatter,
    )
    if card_changed:
        _save_card(paths, card)
    return {
        "citekey": _card_id(card),
        "paper": _card_ref(card),
        "digest": digest_ref,
        "status": status,
        "state": state,
        "changed": digest_changed or card_changed,
        "card_changed": card_changed,
        "digest_changed": digest_changed,
    }


def _run_by_id(paths: VaultPaths, run_id: str) -> RunRecord:
    normalized = (run_id or "").strip()
    for run in load_run_records(paths):
        if run.slug == normalized:
            return run
    raise ValueError(f"No run found for run id: {run_id}")


def compile_scaffold(
    vault: Path | str,
    *,
    citekey: str | None = None,
    run_id: str | None = None,
    selected_only: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    if bool(citekey) == bool(run_id):
        raise ValueError("Provide exactly one of --citekey or --run.")
    paths = _initialize_vault(vault)
    rows: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    if citekey:
        cards = [_resolve_card(paths, citekey)]
    else:
        run = _run_by_id(paths, str(run_id))
        cards_by_ref = _cards_by_ref(paths)
        cards = []
        for result in run.results:
            if selected_only and result.status != "selected":
                continue
            if not result.paper_card:
                skipped.append(
                    {
                        "run_id": run.slug,
                        "rank": result.rank,
                        "title": result.title,
                        "reason": "result has no canonical paper card",
                    }
                )
                continue
            card = cards_by_ref.get(result.paper_card) or cards_by_ref.get(
                Path(result.paper_card).stem
            )
            if card is None:
                skipped.append(
                    {
                        "run_id": run.slug,
                        "rank": result.rank,
                        "title": result.title,
                        "paper_card": result.paper_card,
                        "reason": "paper card is missing",
                    }
                )
                continue
            cards.append(card)
    seen: set[str] = set()
    for card in cards:
        if card.slug in seen:
            continue
        seen.add(card.slug)
        rows.append(_scaffold_card(paths, card, force=force))
    changed = any(row["changed"] for row in rows)
    refresh = _refresh_outputs(paths.vault) if changed else None
    return {
        "vault": str(paths.vault),
        "count": len(rows),
        "changed": sum(1 for row in rows if row["changed"]),
        "digests": rows,
        "skipped": skipped,
        "refresh": refresh,
        "rebuild": refresh,
    }


def _digest_status_for_card(
    paths: VaultPaths,
    card: SourceCard,
) -> tuple[str, Path, dict[str, Any] | None]:
    digest_path = digest_path_for_card(paths, card)
    if card.paper_digest:
        candidate = paths.vault / card.paper_digest
        if candidate.exists():
            digest_path = candidate
    if not digest_path.exists():
        return "uncompiled", digest_path, None
    frontmatter, _ = read_frontmatter_markdown(digest_path)
    digest = normalize_digest_frontmatter(frontmatter, card=card, paths=paths)
    status = str(digest.get("status") or "draft")
    if status not in MARKABLE_DIGEST_STATUSES:
        status = card.compiled_status if card.compiled_status in DIGEST_STATUSES else "draft"
    return status, digest_path, digest


def _compile_row(paths: VaultPaths, card: SourceCard) -> dict[str, Any]:
    status, digest_path, digest = _digest_status_for_card(paths, card)
    digest_exists = digest_path.exists()
    digest_ref = ensure_relative(digest_path, paths.vault)
    issues: list[str] = []
    if not digest_exists and card.reading_status == "read":
        issues.append("needs compile")
    if not digest_exists and card.compiled_status not in {"", "uncompiled"}:
        issues.append("compiled status set but digest is missing")
    if digest and digest.get("paper") != _card_ref(card):
        issues.append("digest paper link differs from card")
    if digest and digest.get("pdf") != card.pdf:
        issues.append("digest pdf link differs from card")
    if digest and digest.get("status") != card.compiled_status:
        issues.append("digest status differs from paper card")
    if digest and digest_exists:
        _, body = read_frontmatter_markdown(digest_path)
        issues.extend(
            issue["kind"]
            for issue in digest_completion_issues(
                paths,
                digest_path,
                digest,
                body,
                card=card,
                target_status=status,
            )
        )
    return {
        "citekey": _card_id(card),
        "paper": _card_ref(card),
        "title": card.title,
        "pdf": card.pdf,
        "pdf_exists": _card_has_valid_pdf(paths, card),
        "reading_status": card.reading_status,
        "compiled_status": card.compiled_status,
        "review_status": card.review_status,
        "last_compiled_at": card.last_compiled_at,
        "last_reviewed_at": card.last_reviewed_at,
        "linked_queries": list(card.linked_queries),
        "linked_projects": list(card.linked_projects),
        "paper_digest": card.paper_digest or digest_ref,
        "digest_exists": digest_exists,
        "digest_status": digest.get("status") if digest else None,
        "evidence_level": (digest.get("evidence_level") if digest else card.evidence_level),
        "effective_status": status,
        "needs_action": status in NEEDS_ACTION_STATUSES or bool(issues),
        "issues": issues,
    }


def compile_status_summary(
    vault_or_paths: Path | str | VaultPaths,
    *,
    cards: list[SourceCard] | None = None,
) -> dict[str, Any]:
    paths = (
        vault_or_paths
        if isinstance(vault_or_paths, VaultPaths)
        else VaultPaths.from_root(vault_or_paths)
    )
    cards = cards if cards is not None else load_source_cards(paths)
    rows = [_compile_row(paths, card) for card in cards]
    counts = Counter(row["effective_status"] for row in rows)
    issue_counts = Counter(issue for row in rows for issue in row["issues"])
    return {
        "vault": str(paths.vault),
        "counts": {status: counts.get(status, 0) for status in DIGEST_STATUSES},
        "needs_action": sum(1 for row in rows if row["needs_action"]),
        "issue_counts": dict(sorted(issue_counts.items())),
        "papers": rows,
        "digests": (
            len(list(paths.paper_digests.glob("*.md"))) if paths.paper_digests.exists() else 0
        ),
        "ok": not issue_counts,
    }


def compile_status(vault: Path | str) -> dict[str, Any]:
    return compile_status_summary(_initialize_vault(vault))


def _project_slug(value: str) -> str:
    raw = (value or "").strip().strip("/")
    if raw.startswith("projects/"):
        raw = raw.removeprefix("projects/").strip("/")
    if raw.endswith("/index.md"):
        raw = raw[: -len("/index.md")]
    candidate = Path(raw)
    if (
        not raw
        or candidate.is_absolute()
        or len(candidate.parts) != 1
        or any(part in {"", ".", ".."} for part in candidate.parts)
    ):
        raise ValueError("Project slug must be a single safe path segment.")
    return raw


def compile_queue(vault: Path | str, *, project: str) -> dict[str, Any]:
    paths = _initialize_vault(vault)
    slug = _project_slug(project)
    project_path = paths.projects / slug / "index.md"
    if not project_path.exists():
        raise ValueError(f"Project does not exist: projects/{slug}")
    frontmatter, _ = read_frontmatter_markdown(project_path)
    related = set(_as_string_list(frontmatter.get("related_papers")))
    project_ref = ensure_relative(project_path, paths.vault)
    rows = []
    for row in compile_status_summary(paths)["papers"]:
        if row["paper"] in related or project_ref in _as_string_list(row.get("linked_projects")):
            rows.append(row)
    queue_rows = [row for row in rows if row["needs_action"]]
    counts = Counter(row["effective_status"] for row in rows)
    return {
        "vault": str(paths.vault),
        "project": project_ref,
        "count": len(rows),
        "queue_count": len(queue_rows),
        "counts": {status: counts.get(status, 0) for status in DIGEST_STATUSES},
        "papers": rows,
        "queue": queue_rows,
    }


def compile_mark(
    vault: Path | str,
    citekey: str,
    *,
    status: str,
    force: bool = False,
) -> dict[str, Any]:
    if status not in MARKABLE_DIGEST_STATUSES:
        raise ValueError(f"Unsupported compile status: {status}")
    paths = _initialize_vault(vault)
    card = _resolve_card(paths, citekey)
    digest_path = digest_path_for_card(paths, card)
    if card.paper_digest and (paths.vault / card.paper_digest).exists():
        digest_path = paths.vault / card.paper_digest
    if not digest_path.exists():
        raise ValueError(f"Digest does not exist for {_card_id(card)}. Run compile scaffold first.")
    frontmatter, body = read_frontmatter_markdown(digest_path)
    digest = normalize_digest_frontmatter(frontmatter, card=card, paths=paths)
    transition_issues = digest_completion_issues(
        paths,
        digest_path,
        digest,
        body,
        card=card,
        target_status=status,
    )
    if transition_issues and not force:
        details = "\n".join(f"- {issue['message']}" for issue in transition_issues)
        raise ValueError(
            f"Cannot mark {_card_id(card)} as {status} until digest readiness issues are "
            f"fixed:\n{details}\nUse --force to override this guard."
        )
    before_digest = dump_frontmatter(digest)
    now = _now_iso()
    digest["status"] = status
    if status in {"compiled", "reviewed"}:
        digest["compiled_at"] = now
    if status == "reviewed":
        digest["reviewed_at"] = now
    digest_changed = before_digest != dump_frontmatter(digest)
    if digest_changed:
        _write_digest(digest_path, digest, body)

    card_changed = False
    digest_ref = ensure_relative(digest_path, paths.vault)
    if _sync_card_to_digest(
        paths,
        card,
        status=status,
        digest_ref=digest_ref,
        digest_frontmatter=digest,
    ):
        card_changed = True
    if status in {"compiled", "reviewed"} and card.last_compiled_at != digest["compiled_at"]:
        card.last_compiled_at = str(digest["compiled_at"])
        card_changed = True
    if status == "reviewed":
        if card.review_status != "reviewed":
            card.review_status = "reviewed"
            card_changed = True
        if card.last_reviewed_at != digest["reviewed_at"]:
            card.last_reviewed_at = str(digest["reviewed_at"])
            card_changed = True
    if card_changed:
        _save_card(paths, card)
    changed = digest_changed or card_changed
    refresh = _refresh_outputs(paths.vault) if changed else None
    return {
        "vault": str(paths.vault),
        "citekey": _card_id(card),
        "paper": _card_ref(card),
        "digest": digest_ref,
        "status": status,
        "changed": changed,
        "digest_changed": digest_changed,
        "card_changed": card_changed,
        "forced": bool(force and transition_issues),
        "transition_issues": transition_issues,
        "refresh": refresh,
        "rebuild": refresh,
    }


def compile_doctor(vault: Path | str) -> dict[str, Any]:
    paths = _initialize_vault(vault)
    status_summary = compile_status_summary(paths)
    issues: list[dict[str, Any]] = []
    for row in status_summary["papers"]:
        for issue in row["issues"]:
            issues.append(
                {
                    "kind": issue,
                    "citekey": row["citekey"],
                    "paper": row["paper"],
                    "digest": row["paper_digest"],
                }
            )
    cards_by_paper = {_card_ref(card): card for card in load_source_cards(paths)}
    cards_by_citekey = {_card_id(card): card for card in load_source_cards(paths)}
    if paths.paper_digests.exists():
        for digest_path in sorted(paths.paper_digests.glob("*.md")):
            frontmatter, body = read_frontmatter_markdown(digest_path)
            digest = normalize_digest_frontmatter(frontmatter)
            for field in DIGEST_REQUIRED_FIELDS:
                if field not in frontmatter:
                    issues.append(
                        {
                            "kind": "missing digest frontmatter field",
                            "field": field,
                            "digest": ensure_relative(digest_path, paths.vault),
                        }
                    )
            if digest.get("status") not in MARKABLE_DIGEST_STATUSES:
                issues.append(
                    {
                        "kind": "invalid digest status",
                        "status": digest.get("status"),
                        "digest": ensure_relative(digest_path, paths.vault),
                    }
                )
            if digest.get("evidence_level") not in DIGEST_EVIDENCE_LEVELS:
                issues.append(
                    {
                        "kind": "invalid digest evidence level",
                        "evidence_level": digest.get("evidence_level"),
                        "digest": ensure_relative(digest_path, paths.vault),
                    }
                )
            paper = digest.get("paper")
            citekey = digest.get("citekey")
            if paper and paper not in cards_by_paper:
                issues.append(
                    {
                        "kind": "digest paper link is missing",
                        "paper": paper,
                        "digest": ensure_relative(digest_path, paths.vault),
                    }
                )
            if citekey and citekey not in cards_by_citekey:
                issues.append(
                    {
                        "kind": "digest citekey has no paper card",
                        "citekey": citekey,
                        "digest": ensure_relative(digest_path, paths.vault),
                    }
                )
            missing_sections = [
                section for section in DIGEST_TEMPLATE_SECTIONS if f"## {section}" not in body
            ]
            for section in missing_sections:
                issues.append(
                    {
                        "kind": "missing digest section",
                        "section": section,
                        "digest": ensure_relative(digest_path, paths.vault),
                    }
                )
            card = cards_by_paper.get(str(digest.get("paper") or ""))
            for transition_issue in digest_completion_issues(
                paths,
                digest_path,
                digest,
                body,
                card=card,
            ):
                issues.append(
                    {
                        "kind": transition_issue["kind"],
                        "check": transition_issue["check"],
                        "citekey": transition_issue.get("citekey"),
                        "digest": ensure_relative(digest_path, paths.vault),
                        "field": transition_issue.get("field"),
                    }
                )
    issue_counts = Counter(str(issue["kind"]) for issue in issues)
    return {
        "vault": str(paths.vault),
        "ok": not issues,
        "counts": status_summary["counts"],
        "issue_counts": dict(sorted(issue_counts.items())),
        "issues": issues,
        "status": status_summary,
    }
