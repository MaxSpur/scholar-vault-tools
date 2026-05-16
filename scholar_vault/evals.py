from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from .models import SourceCard
from .obsidian import _as_string_list, _extract_paper_refs
from .proposals import (
    _collect_declared_evidence_matrices,
    _markdown_files,
    _resolve_proposal_path,
)
from .semantic import (
    SemanticFinding,
    semantic_finding_id,
    summarize_findings,
    write_finding_queue_items,
    write_findings_report,
)
from .semantic_lint import _digest_refs_from_note, _paper_refs_from_note
from .sources import (
    VaultPaths,
    ensure_relative,
    load_source_cards,
    read_frontmatter_markdown,
    write_json,
)

EVAL_KINDS = {"retrieval", "grounding", "synthesis", "proposal_audit"}
HISTORY_FILENAME = "eval-history.json"


def _now_iso() -> str:
    return datetime.now().astimezone().replace(microsecond=0).isoformat()


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, dict):
        return [str(key) for key in value if str(key).strip()]
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _eval_paths(paths: VaultPaths) -> list[Path]:
    if not paths.evals.exists():
        return []
    return sorted([*paths.evals.rglob("*.yaml"), *paths.evals.rglob("*.yml")])


def _read_eval_definition(paths: VaultPaths, path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Eval definition must be a YAML mapping: {path}")
    data = dict(data)
    data["id"] = str(data.get("id") or path.stem)
    data["kind"] = str(data.get("kind") or "").strip()
    data["path"] = ensure_relative(path, paths.vault)
    return data


def load_eval_definitions(vault: Path | str) -> dict[str, Any]:
    from .importer import initialize_vault

    paths = initialize_vault(vault, rebuild=False)
    definitions = []
    errors = []
    for path in _eval_paths(paths):
        try:
            definition = _read_eval_definition(paths, path)
        except ValueError as exc:
            errors.append({"path": ensure_relative(path, paths.vault), "error": str(exc)})
            continue
        definitions.append(
            {
                "id": definition["id"],
                "kind": definition["kind"],
                "title": definition.get("title") or definition["id"],
                "path": definition["path"],
            }
        )
    return {
        "vault": str(paths.vault),
        "count": len(definitions),
        "definitions": definitions,
        "errors": errors,
    }


def _finding(
    *,
    check: str,
    subject: str,
    severity: str,
    action: str,
    title: str,
    message: str,
    files: list[str] | None = None,
    citekeys: list[str] | None = None,
    details: dict[str, Any] | None = None,
    queue_kind: str = "lint_fix",
    required_evidence: str = "none",
    success_criteria: str = "",
) -> SemanticFinding:
    return SemanticFinding(
        id=semantic_finding_id("eval", check, subject),
        check=check,
        severity=severity,
        action=action,
        title=title,
        message=message,
        files=files or [],
        citekeys=citekeys or [],
        details=details or {},
        queue_kind=queue_kind,
        required_evidence=required_evidence,
        success_criteria=success_criteria,
    )


def _card_lookup(cards: list[SourceCard]) -> dict[str, SourceCard]:
    lookup: dict[str, SourceCard] = {}
    for card in cards:
        for ref in [card.citekey, card.slug, f"papers/{card.slug}.md"]:
            if ref:
                lookup[ref] = card
    return lookup


def _query_path(paths: VaultPaths, value: str) -> Path:
    raw = (value or "").strip().strip("/")
    if raw.startswith("queries/"):
        return paths.vault / (raw if raw.endswith(".md") else f"{raw}.md")
    return paths.queries / (raw if raw.endswith(".md") else f"{raw}.md")


def _synthesis_path(paths: VaultPaths, value: str) -> Path:
    raw = (value or "").strip().strip("/")
    if raw.startswith("syntheses/"):
        return paths.vault / (raw if raw.endswith(".md") else f"{raw}.md")
    return paths.syntheses / (raw if raw.endswith(".md") else f"{raw}.md")


def _paper_refs_for_definition(paths: VaultPaths, path: Path) -> tuple[list[str], list[str]]:
    frontmatter, body = read_frontmatter_markdown(path)
    paper_refs = _paper_refs_from_note(frontmatter, body)
    digest_refs = _digest_refs_from_note(frontmatter, body)
    return paper_refs, digest_refs


def _run_retrieval_eval(
    paths: VaultPaths,
    definition: dict[str, Any],
    cards_by_ref: dict[str, SourceCard],
) -> list[SemanticFinding]:
    query_value = str(definition.get("query") or definition.get("target") or "")
    query_path = _query_path(paths, query_value or definition["id"])
    expected = _as_list(definition.get("expected_citekeys"))
    if not query_path.exists():
        return [
            _finding(
                check="eval-retrieval-query-missing",
                subject=definition["id"],
                severity="error",
                action="create_queue_item",
                title="Repair retrieval eval query target",
                message=f"Eval {definition['id']} targets a missing query note.",
                files=[definition["path"]],
                details={"query": query_value},
            )
        ]
    frontmatter, _ = read_frontmatter_markdown(query_path)
    actual_refs = _as_string_list(frontmatter.get("linked_papers"))
    actual_citekeys = {
        cards_by_ref[ref].citekey or cards_by_ref[ref].slug
        for ref in actual_refs
        if ref in cards_by_ref
    }
    missing = [citekey for citekey in expected if citekey not in actual_citekeys]
    if not missing:
        return []
    return [
        _finding(
            check="eval-retrieval-expected-citekeys",
            subject=definition["id"],
            severity="warning",
            action="create_queue_item",
            title="Repair query retrieval coverage",
            message=f"Eval {definition['id']} expected citekeys missing from the query.",
            files=[definition["path"], ensure_relative(query_path, paths.vault)],
            citekeys=missing,
            details={"missing_citekeys": missing, "actual_citekeys": sorted(actual_citekeys)},
            queue_kind="discover_sources",
            required_evidence="web",
            success_criteria=(
                "The query links the expected canonical papers or the eval expectation is "
                "updated."
            ),
        )
    ]


def _run_grounding_or_synthesis_eval(
    paths: VaultPaths,
    definition: dict[str, Any],
) -> list[SemanticFinding]:
    synthesis_value = str(definition.get("synthesis") or definition.get("target") or "")
    synthesis_path = _synthesis_path(paths, synthesis_value or definition["id"])
    if not synthesis_path.exists():
        return [
            _finding(
                check=f"eval-{definition['kind']}-target-missing",
                subject=definition["id"],
                severity="error",
                action="create_queue_item",
                title="Repair eval synthesis target",
                message=f"Eval {definition['id']} targets a missing synthesis note.",
                files=[definition["path"]],
                details={"synthesis": synthesis_value},
            )
        ]
    expected_sources = _as_list(
        definition.get("required_sources") or definition.get("required_source_links")
    )
    paper_refs, digest_refs = _paper_refs_for_definition(paths, synthesis_path)
    actual_sources = {*paper_refs, *digest_refs}
    findings: list[SemanticFinding] = []
    missing_sources = [source for source in expected_sources if source not in actual_sources]
    if missing_sources:
        findings.append(
            _finding(
                check=f"eval-{definition['kind']}-required-source-links",
                subject=definition["id"],
                severity="warning",
                action="create_queue_item",
                title="Repair required source links",
                message=f"Eval {definition['id']} required source links that were not found.",
                files=[
                    definition["path"],
                    ensure_relative(synthesis_path, paths.vault),
                    *missing_sources,
                ],
                details={"missing_sources": missing_sources},
                queue_kind="update_synthesis",
                required_evidence="pdf",
                success_criteria=(
                    "The synthesis links every required source or the eval expectation is "
                    "updated."
                ),
            )
        )
    forbid_labs = bool(definition.get("forbidden_source_only_scholar_labs_citations"))
    if forbid_labs:
        _, body = read_frontmatter_markdown(synthesis_path)
        bad_lines = []
        for line_number, line in enumerate(body.splitlines(), start=1):
            lowered = line.casefold()
            if "scholar labs" in lowered and "summar" in lowered:
                if not _extract_paper_refs(line):
                    bad_lines.append(line_number)
        if bad_lines:
            findings.append(
                _finding(
                    check="eval-grounding-forbidden-scholar-labs-only",
                    subject=definition["id"],
                    severity="error",
                    action="create_queue_item",
                    title="Replace source-only Scholar Labs citations",
                    message=(
                        f"Eval {definition['id']} found Scholar Labs summary citations "
                        "without paper links."
                    ),
                    files=[definition["path"], ensure_relative(synthesis_path, paths.vault)],
                    details={"lines": bad_lines},
                    queue_kind="update_synthesis",
                    required_evidence="pdf",
                    success_criteria=(
                        "The synthesis cites PDF-grounded paper or digest evidence instead "
                        "of Scholar Labs summaries."
                    ),
                )
            )
    return findings


def _proposal_source_matrix_files(paths: VaultPaths, proposal_path: Path) -> list[Path]:
    files = _markdown_files(proposal_path)
    outline_files = [path for path in files if "outline" in path.name.casefold()]
    declared, _broken = _collect_declared_evidence_matrices(paths, outline_files)
    local = [path for path in files if "matrix" in path.name.casefold()]
    return sorted({*local, *declared}, key=lambda path: ensure_relative(path, paths.vault))


def _run_proposal_audit_eval(
    paths: VaultPaths,
    definition: dict[str, Any],
) -> list[SemanticFinding]:
    proposal_value = str(definition.get("proposal") or definition.get("target") or "")
    try:
        proposal_path = _resolve_proposal_path(paths, proposal_value or definition["id"])
    except ValueError:
        proposal_path = paths.proposals / (proposal_value or definition["id"])
    expected = _as_list(
        definition.get("expected_source_matrix_coverage")
        or definition.get("expected_sources")
        or definition.get("expected_source_matrix")
    )
    if not proposal_path.exists():
        return [
            _finding(
                check="eval-proposal-target-missing",
                subject=definition["id"],
                severity="error",
                action="create_queue_item",
                title="Repair proposal eval target",
                message=f"Eval {definition['id']} targets a missing proposal workspace.",
                files=[definition["path"]],
                details={"proposal": proposal_value},
            )
        ]
    matrix_files = _proposal_source_matrix_files(paths, proposal_path)
    matrix_text = "\n".join(path.read_text(encoding="utf-8") for path in matrix_files)
    missing = [source for source in expected if source not in matrix_text]
    if not missing:
        return []
    return [
        _finding(
            check="eval-proposal-source-matrix-coverage",
            subject=definition["id"],
            severity="warning",
            action="create_queue_item",
            title="Repair proposal source-matrix coverage",
            message=f"Eval {definition['id']} expected proposal sources missing from matrices.",
            files=[
                definition["path"],
                *[ensure_relative(path, paths.vault) for path in matrix_files],
                *missing,
            ],
            details={"missing_sources": missing},
            queue_kind="lint_fix",
            required_evidence="pdf",
            success_criteria=(
                "The proposal source matrix covers the expected sources or the eval "
                "expectation is updated."
            ),
        )
    ]


def _run_definition(
    paths: VaultPaths,
    definition: dict[str, Any],
    cards_by_ref: dict[str, SourceCard],
) -> dict[str, Any]:
    kind = definition["kind"]
    if kind not in EVAL_KINDS:
        findings = [
            _finding(
                check="eval-definition-invalid-kind",
                subject=definition["id"],
                severity="error",
                action="needs_user_review",
                title="Repair eval definition kind",
                message=f"Eval {definition['id']} has unsupported kind: {kind or 'missing'}.",
                files=[definition["path"]],
                details={"kind": kind, "allowed": sorted(EVAL_KINDS)},
            )
        ]
    elif kind == "retrieval":
        findings = _run_retrieval_eval(paths, definition, cards_by_ref)
    elif kind in {"grounding", "synthesis"}:
        findings = _run_grounding_or_synthesis_eval(paths, definition)
    else:
        findings = _run_proposal_audit_eval(paths, definition)
    return {
        "id": definition["id"],
        "kind": kind,
        "title": definition.get("title") or definition["id"],
        "path": definition["path"],
        "status": "pass" if not findings else "fail",
        "finding_count": len(findings),
        "findings": [finding.to_dict() for finding in findings],
    }


def _history_path(paths: VaultPaths) -> Path:
    return paths.exports / HISTORY_FILENAME


def _read_history(paths: VaultPaths) -> dict[str, Any]:
    path = _history_path(paths)
    if not path.exists():
        return {"schema_version": "0.1", "runs": []}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return {"schema_version": "0.1", "runs": []}
    runs = data.get("runs")
    if not isinstance(runs, list):
        data["runs"] = []
    return data


def _write_history(paths: VaultPaths, run_record: dict[str, Any]) -> dict[str, Any]:
    history = _read_history(paths)
    history.setdefault("schema_version", "0.1")
    history.setdefault("runs", [])
    history["runs"].append(run_record)
    write_json(_history_path(paths), history)
    return {
        "path": ensure_relative(_history_path(paths), paths.vault),
        "runs": len(history["runs"]),
    }


def run_evals(
    vault: Path | str,
    *,
    kind: str | None = None,
    write_queue: bool = False,
) -> dict[str, Any]:
    from .importer import initialize_vault

    paths = initialize_vault(vault, rebuild=False)
    if kind and kind not in EVAL_KINDS:
        raise ValueError(f"Unsupported eval kind: {kind}")
    definitions = [_read_eval_definition(paths, path) for path in _eval_paths(paths)]
    if kind:
        definitions = [definition for definition in definitions if definition["kind"] == kind]
    cards_by_ref = _card_lookup(load_source_cards(paths))
    results = [_run_definition(paths, definition, cards_by_ref) for definition in definitions]
    findings = [
        SemanticFinding(**finding)
        for result in results
        for finding in result["findings"]
    ]
    started_at = _now_iso()
    run_record = {
        "run_id": f"eval-{started_at.replace(':', '').replace('+', '-')}",
        "started_at": started_at,
        "kind": kind or "all",
        "counts": {
            "definitions": len(results),
            "passed": len([result for result in results if result["status"] == "pass"]),
            "failed": len([result for result in results if result["status"] == "fail"]),
            "findings": len(findings),
        },
        "results": results,
    }
    history = _write_history(paths, run_record)
    summary = summarize_findings(findings)
    summary.update(
        {
            "vault": str(paths.vault),
            "kind": kind or "all",
            "definitions": len(results),
            "results": results,
            "history": history,
        }
    )
    if write_queue:
        summary["queue"] = write_finding_queue_items(paths, findings, created_by="eval")
    return summary


def render_eval_report(vault: VaultPaths | Path | str) -> dict[str, Any]:
    if isinstance(vault, VaultPaths):
        paths = vault
    else:
        from .importer import initialize_vault

        paths = initialize_vault(vault, rebuild=False)
    history = _read_history(paths)
    runs = history.get("runs") or []
    latest = runs[-1] if runs else None
    findings = []
    if latest:
        findings = [
            SemanticFinding(**finding)
            for result in latest.get("results", [])
            for finding in result.get("findings", [])
        ]
    report = write_findings_report(
        paths,
        filename="eval-report.md",
        title="Eval Report",
        description=(
            "This report summarizes the most recent deterministic vault eval run. "
            "Eval failures create review targets; they do not rewrite vault prose."
        ),
        findings=findings,
    )
    return {
        "vault": str(paths.vault),
        "history": ensure_relative(_history_path(paths), paths.vault),
        "run_count": len(runs),
        "latest": latest,
        "report": report,
        "ok": not findings,
    }
