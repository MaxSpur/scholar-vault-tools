from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from .bases import doctor_bases
from .diagnostics import git_summary
from .digests import DIGEST_REQUIRED_FIELDS, DIGEST_TEMPLATE_SECTIONS
from .models import FeedbackRecord, QueueItem, SourceCard
from .obsidian import (
    _as_string_list,
    _card_has_valid_pdf,
    _card_id,
    _card_ref,
    _display_path,
    _extract_note_targets,
    _extract_paper_refs,
    _resolve_note_target,
)
from .semantic import (
    SemanticFinding,
    semantic_finding_id,
    summarize_findings,
    write_finding_queue_items,
    write_findings_report,
)
from .sources import (
    VaultPaths,
    ensure_relative,
    load_run_records,
    load_source_cards,
    read_frontmatter_markdown,
)

SOURCE_FIELDS = (
    "sources",
    "source",
    "source_links",
    "linked_sources",
    "papers",
    "linked_papers",
    "related_papers",
    "paper",
)
CANONICAL_MARKDOWN_ROOTS = (
    "paper-digests",
    "concepts",
    "syntheses",
    "tasks",
    "queries",
    "projects",
    "proposals",
)
ACTION_FEEDBACK_VERDICTS = {"needs_fix", "rejected", "stale"}


def _finding(
    namespace: str,
    *,
    check: str,
    subject: str,
    severity: str,
    action: str,
    title: str,
    message: str,
    files: list[str] | None = None,
    citekeys: list[str] | None = None,
    runs: list[str] | None = None,
    details: dict[str, Any] | None = None,
    queue_kind: str = "lint_fix",
    required_evidence: str = "none",
    success_criteria: str = "",
    queueable: bool = True,
    tool_improvement: dict[str, Any] | None = None,
) -> SemanticFinding:
    return SemanticFinding(
        id=semantic_finding_id(namespace, check, subject),
        check=check,
        severity=severity,
        action=action,
        title=title,
        message=message,
        files=files or [],
        citekeys=citekeys or [],
        runs=runs or [],
        details=details or {},
        queue_kind=queue_kind,
        required_evidence=required_evidence,
        success_criteria=success_criteria,
        queueable=queueable,
        tool_improvement=tool_improvement,
    )


def _read_yaml_mapping(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("YAML record must be a mapping.")
    return data


def _markdown_paths(paths: VaultPaths, root_name: str) -> list[Path]:
    root = paths.vault / root_name
    if not root.exists():
        return []
    if root_name == "queries":
        return sorted(path for path in root.glob("*.md") if not path.name.startswith("."))
    if root_name == "projects":
        return sorted(root.glob("*/index.md"))
    return sorted(
        path
        for path in root.rglob("*.md")
        if not any(part.startswith(".") for part in path.relative_to(root).parts)
    )


def _note_source_targets(frontmatter: dict[str, Any], body: str) -> list[str]:
    targets: list[str] = []
    targets.extend(_frontmatter_source_targets(frontmatter))
    targets.extend(_extract_note_targets(body))
    seen: set[str] = set()
    unique: list[str] = []
    for target in targets:
        clean = target.strip()
        if clean and clean not in seen:
            seen.add(clean)
            unique.append(clean)
    return unique


def _frontmatter_source_targets(frontmatter: dict[str, Any]) -> list[str]:
    targets: list[str] = []
    for field in SOURCE_FIELDS:
        targets.extend(_as_string_list(frontmatter.get(field)))
    return targets


def _paper_refs_from_note(frontmatter: dict[str, Any], body: str) -> list[str]:
    refs = set(_extract_paper_refs(body))
    for target in _note_source_targets(frontmatter, body):
        clean = target.strip().strip("<>")
        if "[[" in clean:
            clean = clean.strip("[]")
        clean = clean.split("|", 1)[0].split("#", 1)[0]
        if "papers/" in clean:
            ref = clean[clean.index("papers/") :]
            if not ref.endswith(".md"):
                ref = f"{ref}.md"
            refs.add(ref)
    return sorted(refs)


def _digest_refs_from_note(frontmatter: dict[str, Any], body: str) -> list[str]:
    refs = set()
    for target in _note_source_targets(frontmatter, body):
        clean = target.strip().strip("<>")
        if "paper-digests/" not in clean:
            continue
        ref = clean[clean.index("paper-digests/") :].split("#", 1)[0].split("|", 1)[0]
        if not ref.endswith(".md"):
            ref = f"{ref}.md"
        refs.add(ref)
    for match in re.finditer(r"paper-digests/[^\]\)\s#|]+(?:\.md)?", body):
        ref = match.group(0)
        refs.add(ref if ref.endswith(".md") else f"{ref}.md")
    return sorted(refs)


def _paper_lookup(cards: list[SourceCard]) -> dict[str, SourceCard]:
    lookup: dict[str, SourceCard] = {}
    for card in cards:
        refs = {_card_ref(card), card.slug}
        if card.citekey:
            refs.add(card.citekey)
        for ref in refs:
            lookup[ref] = card
    return lookup


def _digest_ref_for_card(paths: VaultPaths, card: SourceCard) -> str | None:
    if card.paper_digest and (paths.vault / card.paper_digest).exists():
        return card.paper_digest
    citekey = _card_id(card)
    candidate = paths.paper_digests / f"{citekey}.md"
    if candidate.exists():
        return ensure_relative(candidate, paths.vault)
    for digest_path in sorted(paths.paper_digests.glob("*.md")):
        frontmatter, _ = read_frontmatter_markdown(digest_path)
        if frontmatter.get("paper") == _card_ref(card) or frontmatter.get("citekey") == citekey:
            return ensure_relative(digest_path, paths.vault)
    return None


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _mtime(path: Path) -> datetime:
    return datetime.fromtimestamp(path.stat().st_mtime).astimezone()


def _lint_syntheses_and_concepts(
    paths: VaultPaths,
    cards: list[SourceCard],
) -> list[SemanticFinding]:
    findings: list[SemanticFinding] = []
    cards_by_ref = _paper_lookup(cards)
    for folder in ("syntheses", "concepts"):
        for path in _markdown_paths(paths, folder):
            frontmatter, body = read_frontmatter_markdown(path)
            rel = ensure_relative(path, paths.vault)
            declared_sources = _frontmatter_source_targets(frontmatter)
            paper_refs = _paper_refs_from_note(frontmatter, body)
            digest_refs = _digest_refs_from_note(frontmatter, body)
            if not declared_sources and not paper_refs and not digest_refs:
                is_synthesis = folder == "syntheses"
                singular = "synthesis" if is_synthesis else "concept"
                findings.append(
                    _finding(
                        "lint",
                        check=f"{singular}-no-source-links",
                        subject=rel,
                        severity="warning",
                        action="create_queue_item",
                        title=(
                            "Add source links to synthesis"
                            if is_synthesis
                            else "Add source links to concept"
                        ),
                        message=f"{rel} has no detectable source links.",
                        files=[rel],
                        queue_kind="update_synthesis" if is_synthesis else "lint_fix",
                        required_evidence="pdf",
                        success_criteria=(
                            "The note links to the paper, digest, or run records that "
                            "support it."
                        ),
                    )
                )
            if folder == "concepts" and (declared_sources or paper_refs or digest_refs):
                has_supporting_digest = bool(digest_refs)
                for ref in paper_refs:
                    card = cards_by_ref.get(ref)
                    if card and _digest_ref_for_card(paths, card):
                        has_supporting_digest = True
                        break
                if not has_supporting_digest:
                    findings.append(
                        _finding(
                            "lint",
                            check="concept-sources-no-digests",
                            subject=rel,
                            severity="warning",
                            action="create_queue_item",
                            title="Link concept sources to paper digests",
                            message=(
                                f"{rel} links sources but no supporting paper digest was "
                                "found."
                            ),
                            files=[rel],
                            citekeys=[
                                _card_id(cards_by_ref[ref])
                                for ref in paper_refs
                                if ref in cards_by_ref
                            ],
                            queue_kind="lint_fix",
                            required_evidence="pdf",
                            success_criteria=(
                                "The concept links to at least one PDF-grounded paper digest "
                                "or supported paper source."
                            ),
                        )
                    )
            if folder != "syntheses":
                continue
            for ref in paper_refs:
                card = cards_by_ref.get(ref)
                if card is None:
                    continue
                citekey = _card_id(card)
                if not _card_has_valid_pdf(paths, card):
                    findings.append(
                        _finding(
                            "lint",
                            check="synthesis-paper-missing-pdf",
                            subject=f"{rel}:{ref}",
                            severity="error",
                            action="create_queue_item",
                            title=f"Attach PDF for synthesis source {citekey}",
                            message=f"{rel} cites {ref}, but that paper has no valid linked PDF.",
                            files=[rel, ref],
                            citekeys=[citekey],
                            queue_kind="discover_sources",
                            required_evidence="pdf",
                            success_criteria=(
                                "The cited paper has a verified linked PDF, or the synthesis "
                                "stops relying on it."
                            ),
                        )
                    )
                if not _digest_ref_for_card(paths, card):
                    findings.append(
                        _finding(
                            "lint",
                            check="synthesis-paper-missing-digest",
                            subject=f"{rel}:{ref}",
                            severity="warning",
                            action="create_queue_item",
                            title=f"Compile digest for synthesis source {citekey}",
                            message=(
                                f"{rel} cites {ref}, but no paper digest was found for that "
                                "source."
                            ),
                            files=[rel, ref],
                            citekeys=[citekey],
                            queue_kind="compile_paper",
                            required_evidence="pdf",
                            success_criteria="The cited paper has a reusable PDF-grounded digest.",
                        )
                    )
    return findings


def _lint_digests(paths: VaultPaths, cards: list[SourceCard]) -> list[SemanticFinding]:
    findings: list[SemanticFinding] = []
    cards_by_ref = _paper_lookup(cards)
    for path in sorted(paths.paper_digests.glob("*.md")):
        frontmatter, body = read_frontmatter_markdown(path)
        rel = ensure_relative(path, paths.vault)
        missing_fields = [field for field in DIGEST_REQUIRED_FIELDS if field not in frontmatter]
        if missing_fields:
            findings.append(
                _finding(
                    "lint",
                    check="paper-digest-missing-required-fields",
                    subject=rel,
                    severity="warning",
                    action="create_queue_item",
                    title="Repair paper digest frontmatter",
                    message=f"{rel} is missing required frontmatter fields.",
                    files=[rel],
                    details={"missing_fields": missing_fields},
                    queue_kind="compile_paper",
                    required_evidence="pdf",
                    success_criteria=(
                        "The digest contains the required compile-workflow frontmatter."
                    ),
                )
            )
        missing_sections = [
            section for section in DIGEST_TEMPLATE_SECTIONS if f"## {section}" not in body
        ]
        if missing_sections:
            findings.append(
                _finding(
                    "lint",
                    check="paper-digest-missing-required-sections",
                    subject=rel,
                    severity="warning",
                    action="create_queue_item",
                    title="Repair missing paper digest sections",
                    message=f"{rel} is missing required digest sections.",
                    files=[rel],
                    details={"missing_sections": missing_sections},
                    queue_kind="compile_paper",
                    required_evidence="pdf",
                    success_criteria="The digest contains every required section heading.",
                )
            )
        status = str(frontmatter.get("status") or "")
        if status == "stale":
            continue
        paper_ref = str(frontmatter.get("paper") or "")
        digest_time = _parse_datetime(str(frontmatter.get("reviewed_at") or ""))
        digest_time = digest_time or _parse_datetime(str(frontmatter.get("compiled_at") or ""))
        digest_time = digest_time or _mtime(path)
        changed_sources: list[str] = []
        paper_path = paths.vault / paper_ref if paper_ref else None
        if paper_path and paper_path.exists() and _mtime(paper_path) > digest_time:
            changed_sources.append(paper_ref)
        card = cards_by_ref.get(paper_ref)
        query_refs = set(_as_string_list(frontmatter.get("linked_queries")))
        if card:
            query_refs.update(card.linked_queries)
        for query_ref in sorted(query_refs):
            query_path = paths.vault / query_ref
            if query_path.exists() and _mtime(query_path) > digest_time:
                changed_sources.append(query_ref)
        if changed_sources:
            citekey = str(frontmatter.get("citekey") or (card and _card_id(card)) or path.stem)
            findings.append(
                _finding(
                    "lint",
                    check="paper-digest-stale",
                    subject=rel,
                    severity="warning",
                    action="create_queue_item",
                    title=f"Review stale digest {citekey}",
                    message=f"{rel} is older than its linked paper card or query context.",
                    files=[rel, *changed_sources],
                    citekeys=[citekey],
                    details={"changed_sources": changed_sources},
                    queue_kind="compile_paper",
                    required_evidence="pdf",
                    success_criteria=(
                        "The digest is reviewed against the changed linked records and "
                        "marked current or stale intentionally."
                    ),
                )
            )
    return findings


def _lint_queries(paths: VaultPaths) -> list[SemanticFinding]:
    findings: list[SemanticFinding] = []
    for path in _markdown_paths(paths, "queries"):
        frontmatter, _ = read_frontmatter_markdown(path)
        rel = ensure_relative(path, paths.vault)
        linked_runs = _as_string_list(frontmatter.get("linked_runs"))
        linked_papers = _as_string_list(frontmatter.get("linked_papers"))
        prompt_packs = _as_string_list(frontmatter.get("scholar_labs_prompt_pack"))
        outputs = [
            *_as_string_list(frontmatter.get("linked_syntheses")),
            *_as_string_list(frontmatter.get("linked_concepts")),
            *_as_string_list(frontmatter.get("outputs")),
            *_as_string_list(frontmatter.get("linked_outputs")),
        ]
        if not linked_runs and not linked_papers and not prompt_packs and not outputs:
            findings.append(
                _finding(
                    "lint",
                    check="query-no-linked-work",
                    subject=rel,
                    severity="info",
                    action="create_queue_item",
                    title="Connect empty research query workbench",
                    message=f"{rel} has no linked runs, papers, prompt packs, or outputs.",
                    files=[rel],
                    queue_kind="discover_sources",
                    required_evidence="web",
                    success_criteria=(
                        "The query is linked to relevant runs, papers, prompt packs, "
                        "syntheses, or concepts."
                    ),
                )
            )
    return findings


def _lint_prompt_packs_and_runs(paths: VaultPaths) -> list[SemanticFinding]:
    findings: list[SemanticFinding] = []
    prompt_dirs = [paths.tasks / "scholar-labs-prompts"]
    if paths.queries.exists():
        prompt_dirs.extend(sorted(paths.queries.glob("*/prompt-packs")))
    prompt_paths = sorted(
        {path for folder in prompt_dirs if folder.exists() for path in folder.glob("*.md")}
    )
    for path in prompt_paths:
        frontmatter, _ = read_frontmatter_markdown(path)
        rel = ensure_relative(path, paths.vault)
        status = str(frontmatter.get("status") or "")
        linked_runs = _as_string_list(frontmatter.get("linked_runs"))
        if status in {"used", "imported"} and not linked_runs:
            findings.append(
                _finding(
                    "lint",
                    check="prompt-pack-used-without-run",
                    subject=rel,
                    severity="warning",
                    action="create_queue_item",
                    title="Link used Scholar Labs prompt pack to its run",
                    message=f"{rel} is marked {status} but has no linked runs.",
                    files=[rel],
                    queue_kind="scholar_labs_prompt",
                    required_evidence="metadata",
                    success_criteria=(
                        "The prompt pack links the import run that used it, or the status is "
                        "corrected."
                    ),
                )
            )
    for run in load_run_records(paths):
        missing = []
        if not run.query:
            missing.append("query")
        if not run.prompt_pack:
            missing.append("prompt_pack")
        if missing:
            run_file = paths.runs / run.slug / "index.yaml"
            findings.append(
                _finding(
                    "lint",
                    check="run-missing-query-or-prompt-pack",
                    subject=run.slug,
                    severity="warning",
                    action="create_queue_item",
                    title="Link imported run to query and prompt pack",
                    message=f"Run {run.slug} is missing {', '.join(missing)} provenance.",
                    files=[ensure_relative(run_file, paths.vault)],
                    runs=[run.slug],
                    details={"missing": missing},
                    queue_kind="scholar_labs_prompt",
                    required_evidence="metadata",
                    success_criteria=(
                        "The run records the query and Scholar Labs prompt pack that "
                        "produced it, or the missing provenance is documented."
                    ),
                )
            )
    return findings


def _lint_queue_feedback_and_tools(paths: VaultPaths) -> list[SemanticFinding]:
    findings: list[SemanticFinding] = []
    if paths.task_queue.exists():
        for path in sorted(paths.task_queue.glob("*.yaml")):
            rel = ensure_relative(path, paths.vault)
            try:
                data = _read_yaml_mapping(path)
                item = QueueItem.model_validate(data)
            except (ValueError, ValidationError) as exc:
                findings.append(
                    _finding(
                        "lint",
                        check="queue-item-invalid",
                        subject=rel,
                        severity="error",
                        action="needs_user_review",
                        title="Repair invalid queue item",
                        message=f"{rel} is not a valid queue item: {exc}",
                        files=[rel],
                        queueable=False,
                        success_criteria="The queue YAML validates against the queue item schema.",
                    )
                )
                continue
            if item.tool_improvement is not None:
                missing = []
                if not item.tool_improvement.reproduction.strip():
                    missing.append("reproduction")
                if not item.tool_improvement.tests_to_add:
                    missing.append("tests_to_add")
                if missing:
                    findings.append(
                        _finding(
                            "lint",
                            check="tool-improvement-missing-repro-or-tests",
                            subject=rel,
                            severity="warning",
                            action="needs_tool_change",
                            title="Add reproduction and tests to tool-improvement task",
                            message=f"{rel} is an improve_tool task missing {', '.join(missing)}.",
                            files=[rel],
                            details={"missing": missing},
                            queue_kind="improve_tool",
                            required_evidence="none",
                            success_criteria=(
                                "The tool-improvement task records reproduction steps and "
                                "tests to add."
                            ),
                        )
                    )
    queue_ids = (
        {path.stem for path in paths.task_queue.glob("*.yaml")}
        if paths.task_queue.exists()
        else set()
    )
    if paths.feedback_ratings.exists():
        for path in sorted(paths.feedback_ratings.glob("*.yaml")):
            rel = ensure_relative(path, paths.vault)
            try:
                record = FeedbackRecord.model_validate(_read_yaml_mapping(path))
            except (ValueError, ValidationError):
                continue
            if (
                record.verdict in ACTION_FEEDBACK_VERDICTS
                and (not record.linked_queue_item or record.linked_queue_item not in queue_ids)
            ):
                findings.append(
                    _finding(
                        "lint",
                        check="feedback-missing-follow-up-queue",
                        subject=rel,
                        severity="warning",
                        action="create_queue_item",
                        title="Create follow-up queue item for feedback",
                        message=(
                            f"{rel} records actionable feedback but is not linked to an "
                            "open queue item."
                        ),
                        files=[rel],
                        details={"target": record.target, "verdict": record.verdict},
                        queue_kind="review_feedback",
                        required_evidence="none",
                        success_criteria=(
                            "The feedback is linked to a follow-up queue item or explicitly "
                            "closed."
                        ),
                    )
                )
    return findings


def _lint_bases(paths: VaultPaths) -> list[SemanticFinding]:
    findings: list[SemanticFinding] = []
    summary = doctor_bases(paths.vault)
    for row in summary.get("bases") or []:
        issues = row.get("issues") or []
        if not issues:
            continue
        path_ref = str(row.get("path") or "")
        findings.append(
            _finding(
                "lint",
                check="generated-base-invalid-or-missing",
                subject=path_ref,
                severity="warning",
                action="needs_user_review",
                title="Regenerate or repair generated Obsidian Base",
                message=f"{path_ref} has Base validation issues: {'; '.join(issues)}.",
                files=[path_ref],
                details={"issues": issues},
                queue_kind="lint_fix",
                required_evidence="none",
                success_criteria=(
                    "`scholar-vault bases doctor --json` reports no generated Base issues."
                ),
            )
        )
    return findings


def _lint_dead_links(paths: VaultPaths) -> list[SemanticFinding]:
    findings: list[SemanticFinding] = []
    for root_name in CANONICAL_MARKDOWN_ROOTS:
        for path in _markdown_paths(paths, root_name):
            frontmatter, body = read_frontmatter_markdown(path)
            source_text = "\n".join(
                str(value)
                for field in SOURCE_FIELDS
                for value in _as_string_list(frontmatter.get(field))
            )
            text = body + "\n" + source_text
            rel = ensure_relative(path, paths.vault)
            for target in _extract_note_targets(text):
                resolved = _resolve_note_target(paths, path, target)
                if resolved is None:
                    continue
                try:
                    resolved.relative_to(paths.vault)
                except ValueError:
                    continue
                if not resolved.exists():
                    findings.append(
                        _finding(
                            "lint",
                            check="dead-wikilink",
                            subject=f"{rel}:{target}",
                            severity="warning",
                            action="needs_user_review",
                            title="Repair dead vault link",
                            message=f"{rel} links to {target}, which does not resolve.",
                            files=[rel],
                            details={
                                "target": target,
                                "resolved": _display_path(resolved, paths.vault),
                            },
                            queue_kind="lint_fix",
                            required_evidence="metadata",
                            success_criteria=(
                                "The link resolves to an existing vault artifact or is "
                                "removed."
                            ),
                        )
                    )
    return findings


def _lint_generated_git_changes(paths: VaultPaths) -> list[SemanticFinding]:
    try:
        summary = git_summary(paths.vault)
    except ValueError:
        return []
    findings = []
    for row in summary.get("files") or []:
        if row.get("classification") != "generated":
            continue
        if str(row.get("status") or "").strip() == "??":
            continue
        path_ref = str(row.get("path") or "")
        findings.append(
            _finding(
                "lint",
                check="generated-file-modified",
                subject=path_ref,
                severity="info",
                action="needs_user_review",
                title="Review modified generated file",
                message=f"{path_ref} is generated output but has tracked Git changes.",
                files=[path_ref],
                details={"git_status": row.get("status")},
                queue_kind="lint_fix",
                required_evidence="none",
                success_criteria=(
                    "Generated changes are regenerated intentionally or reverted before "
                    "commit."
                ),
            )
        )
    return findings


def lint_wiki(
    vault: Path | str,
    *,
    write_queue: bool = False,
    write_report: bool = False,
) -> dict[str, Any]:
    from .importer import initialize_vault

    paths = initialize_vault(vault, rebuild=False)
    cards = load_source_cards(paths)
    findings: list[SemanticFinding] = []
    findings.extend(_lint_syntheses_and_concepts(paths, cards))
    findings.extend(_lint_digests(paths, cards))
    findings.extend(_lint_queries(paths))
    findings.extend(_lint_prompt_packs_and_runs(paths))
    findings.extend(_lint_queue_feedback_and_tools(paths))
    findings.extend(_lint_bases(paths))
    findings.extend(_lint_dead_links(paths))
    findings.extend(_lint_generated_git_changes(paths))
    findings = sorted(findings, key=lambda item: (item.severity, item.check, item.id))
    summary = summarize_findings(findings)
    summary["vault"] = str(paths.vault)
    if write_queue:
        summary["queue"] = write_finding_queue_items(paths, findings, created_by="lint")
    if write_report:
        summary["report"] = write_findings_report(
            paths,
            filename="lint-wiki-report.md",
            title="Semantic Wiki Lint Report",
            description=(
                "This report is a safety layer over the vault's source wiki. It creates "
                "work items and review targets; it does not rewrite scientific content."
            ),
            findings=findings,
        )
    return summary
