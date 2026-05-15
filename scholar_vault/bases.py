from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .sources import VaultPaths, ensure_relative

BASE_VIEW_NAMES: dict[str, list[str]] = {
    "papers.base": [
        "Needs reading",
        "Needs compile",
        "Missing metadata",
        "Recently changed",
        "By topic",
    ],
    "queries.base": [
        "Active queries",
        "Query outputs",
        "Queries needing Scholar Labs",
        "Queries with unread linked papers",
        "Queries with uncompiled linked papers",
    ],
    "synthesis-workbench.base": [
        "Syntheses without enough source links",
        "Concepts without source links",
        "Open synthesis opportunities",
    ],
    "scholar-labs-workbench.base": [
        "Prompt drafts",
        "Prompts awaiting import",
        "Imported Labs runs needing compile",
    ],
    "self-improvement.base": [
        "Open queue items",
        "Tool-improvement tasks",
        "Feedback needing action",
    ],
}


def _base_documents() -> dict[str, dict[str, Any]]:
    return {
        "papers.base": {
            "filters": {
                "and": [
                    'file.ext == "md"',
                    'file.inFolder("papers")',
                    'type == "paper"',
                ]
            },
            "properties": {
                "file.name": {"displayName": "File"},
                "title": {"displayName": "Title"},
                "reading_status": {"displayName": "Reading"},
                "compiled_status": {"displayName": "Compile"},
                "review_status": {"displayName": "Review"},
                "paper_digest": {"displayName": "Digest"},
                "evidence_level": {"displayName": "Evidence"},
                "last_compiled_at": {"displayName": "Compiled"},
                "last_reviewed_at": {"displayName": "Reviewed"},
                "topics": {"displayName": "Topics"},
                "linked_queries": {"displayName": "Queries"},
                "linked_projects": {"displayName": "Projects"},
                "file.mtime": {"displayName": "Changed"},
            },
            "views": [
                {
                    "type": "table",
                    "name": "Needs reading",
                    "filters": {"and": ['reading_status == "unread"']},
                    "order": [
                        "file.name",
                        "title",
                        "reading_status",
                        "pdf_status",
                        "topics",
                        "linked_queries",
                    ],
                },
                {
                    "type": "table",
                    "name": "Needs compile",
                    "filters": {
                        "and": [
                            (
                                'compiled_status == "uncompiled" || '
                                'compiled_status == "draft" || compiled_status == "stale"'
                            )
                        ]
                    },
                    "order": [
                        "file.name",
                        "title",
                        "compiled_status",
                        "paper_digest",
                        "last_compiled_at",
                        "linked_queries",
                    ],
                },
                {
                    "type": "table",
                    "name": "Missing metadata",
                    "filters": {
                        "and": [
                            (
                                'enrichment_status != "complete" || doi_status == "missing" '
                                '|| citation_status == "ambiguous" '
                                '|| citation_status == "unresolved"'
                            )
                        ]
                    },
                    "order": [
                        "file.name",
                        "title",
                        "enrichment_status",
                        "enrichment_missing",
                        "doi_status",
                        "citation_status",
                    ],
                },
                {
                    "type": "table",
                    "name": "Recently changed",
                    "limit": 50,
                    "filters": {"and": ['file.mtime > now() - "14d"']},
                    "order": [
                        "file.name",
                        "title",
                        "reading_status",
                        "compiled_status",
                        "file.mtime",
                    ],
                },
                {
                    "type": "table",
                    "name": "By topic",
                    "groupBy": {"property": "topics", "direction": "ASC"},
                    "order": [
                        "file.name",
                        "title",
                        "topics",
                        "reading_status",
                        "compiled_status",
                    ],
                },
            ],
        },
        "queries.base": {
            "filters": {"and": ['file.ext == "md"']},
            "properties": {
                "file.name": {"displayName": "File"},
                "question": {"displayName": "Question"},
                "status": {"displayName": "Status"},
                "project": {"displayName": "Project"},
                "priority": {"displayName": "Priority"},
                "review_status": {"displayName": "Review"},
                "linked_runs": {"displayName": "Runs"},
                "linked_papers": {"displayName": "Papers"},
                "linked_syntheses": {"displayName": "Syntheses"},
                "unread_linked_papers": {"displayName": "Unread linked papers"},
                "uncompiled_linked_papers": {"displayName": "Uncompiled linked papers"},
                "file.mtime": {"displayName": "Changed"},
            },
            "views": [
                {
                    "type": "table",
                    "name": "Active queries",
                    "filters": {
                        "and": [
                            'type == "research_query"',
                            'status == "open" || status == "active"',
                        ]
                    },
                    "order": [
                        "file.name",
                        "question",
                        "status",
                        "project",
                        "priority",
                        "linked_papers",
                        "linked_runs",
                    ],
                },
                {
                    "type": "table",
                    "name": "Query outputs",
                    "filters": {
                        "and": [
                            "file.path != this.file.path",
                            (
                                "file.hasLink(this.file) || "
                                "(file.hasProperty(\"linked_queries\") && "
                                "list(linked_queries).contains(this.file.path))"
                            ),
                        ]
                    },
                    "order": [
                        "file.name",
                        "type",
                        "status",
                        "review_status",
                        "linked_queries",
                        "file.mtime",
                    ],
                },
                {
                    "type": "table",
                    "name": "Queries needing Scholar Labs",
                    "filters": {
                        "and": [
                            'type == "research_query"',
                            'status == "open" || status == "active"',
                            '(!file.hasProperty("linked_runs") || linked_runs.isEmpty())',
                            (
                                '(!file.hasProperty("scholar_labs_prompt_pack") || '
                                "scholar_labs_prompt_pack.isEmpty())"
                            ),
                        ]
                    },
                    "order": [
                        "file.name",
                        "question",
                        "project",
                        "priority",
                        "scholar_labs_prompt_pack",
                    ],
                },
                {
                    "type": "table",
                    "name": "Queries with unread linked papers",
                    "filters": {
                        "and": [
                            'type == "research_query"',
                            'file.hasProperty("unread_linked_papers")',
                            "!unread_linked_papers.isEmpty()",
                        ]
                    },
                    "order": [
                        "file.name",
                        "question",
                        "unread_linked_papers",
                        "linked_papers",
                        "review_status",
                    ],
                },
                {
                    "type": "table",
                    "name": "Queries with uncompiled linked papers",
                    "filters": {
                        "and": [
                            'type == "research_query"',
                            'file.hasProperty("uncompiled_linked_papers")',
                            "!uncompiled_linked_papers.isEmpty()",
                        ]
                    },
                    "order": [
                        "file.name",
                        "question",
                        "uncompiled_linked_papers",
                        "linked_papers",
                        "review_status",
                    ],
                },
            ],
        },
        "synthesis-workbench.base": {
            "filters": {"and": ['file.ext == "md"']},
            "properties": {
                "file.name": {"displayName": "File"},
                "title": {"displayName": "Title"},
                "type": {"displayName": "Type"},
                "status": {"displayName": "Status"},
                "sources": {"displayName": "Sources"},
                "linked_papers": {"displayName": "Linked papers"},
                "file.mtime": {"displayName": "Changed"},
            },
            "views": [
                {
                    "type": "table",
                    "name": "Syntheses without enough source links",
                    "filters": {
                        "and": [
                            'type == "synthesis"',
                            '(!file.hasProperty("sources") || list(sources).length < 2)',
                        ]
                    },
                    "order": ["file.name", "title", "sources", "status", "file.mtime"],
                },
                {
                    "type": "table",
                    "name": "Concepts without source links",
                    "filters": {
                        "and": [
                            'type == "concept"',
                            '(!file.hasProperty("sources") || list(sources).isEmpty())',
                        ]
                    },
                    "order": ["file.name", "title", "sources", "status", "file.mtime"],
                },
                {
                    "type": "table",
                    "name": "Open synthesis opportunities",
                    "filters": {
                        "and": [
                            'type == "research_query"',
                            'status == "open" || status == "active"',
                            "file.hasProperty(\"linked_papers\")",
                            "list(linked_papers).length >= 2",
                        ]
                    },
                    "order": [
                        "file.name",
                        "question",
                        "linked_papers",
                        "linked_syntheses",
                        "priority",
                    ],
                },
            ],
        },
        "scholar-labs-workbench.base": {
            "filters": {"and": ['file.ext == "md"']},
            "properties": {
                "file.name": {"displayName": "File"},
                "question": {"displayName": "Question"},
                "prompt": {"displayName": "Prompt"},
                "scholar_labs_prompt_pack": {"displayName": "Prompt pack"},
                "linked_runs": {"displayName": "Linked runs"},
                "selected_count": {"displayName": "Selected"},
                "result_count": {"displayName": "Results"},
                "file.mtime": {"displayName": "Changed"},
            },
            "views": [
                {
                    "type": "table",
                    "name": "Prompt drafts",
                    "filters": {
                        "and": [
                            'type == "research_query"',
                            'file.hasProperty("scholar_labs_prompt_pack")',
                            "!scholar_labs_prompt_pack.isEmpty()",
                        ]
                    },
                    "order": [
                        "file.name",
                        "question",
                        "scholar_labs_prompt_pack",
                        "project",
                    ],
                },
                {
                    "type": "table",
                    "name": "Prompts awaiting import",
                    "filters": {
                        "and": [
                            'type == "research_query"',
                            'file.hasProperty("scholar_labs_prompt_pack")',
                            "!scholar_labs_prompt_pack.isEmpty()",
                            '(!file.hasProperty("linked_runs") || linked_runs.isEmpty())',
                        ]
                    },
                    "order": [
                        "file.name",
                        "question",
                        "scholar_labs_prompt_pack",
                        "priority",
                    ],
                },
                {
                    "type": "table",
                    "name": "Imported Labs runs needing compile",
                    "filters": {
                        "and": [
                            'type == "scholar_labs_run"',
                            "selected_count > 0",
                        ]
                    },
                    "order": [
                        "file.name",
                        "title",
                        "selected_count",
                        "result_count",
                        "file.mtime",
                    ],
                },
            ],
        },
        "self-improvement.base": {
            "filters": {"and": ['file.ext == "md"']},
            "properties": {
                "file.name": {"displayName": "File"},
                "title": {"displayName": "Title"},
                "type": {"displayName": "Type"},
                "status": {"displayName": "Status"},
                "review_status": {"displayName": "Review"},
                "priority": {"displayName": "Priority"},
                "file.mtime": {"displayName": "Changed"},
            },
            "views": [
                {
                    "type": "table",
                    "name": "Open queue items",
                    "filters": {
                        "and": [
                            'file.inFolder("tasks")',
                            'status == "open" || status == "active"',
                        ]
                    },
                    "order": ["file.name", "title", "status", "priority", "file.mtime"],
                },
                {
                    "type": "table",
                    "name": "Tool-improvement tasks",
                    "filters": {
                        "and": [
                            'file.inFolder("tasks")',
                            (
                                'file.hasTag("tool-improvement") || '
                                'file.name.lower().contains("tool")'
                            ),
                        ]
                    },
                    "order": ["file.name", "title", "status", "review_status", "file.mtime"],
                },
                {
                    "type": "table",
                    "name": "Feedback needing action",
                    "filters": {
                        "and": [
                            (
                                'review_status == "needs_fix" || type == "feedback" '
                                '|| file.hasTag("feedback")'
                            ),
                            'status != "archived" && status != "done"',
                        ]
                    },
                    "order": ["file.name", "title", "type", "status", "review_status"],
                },
            ],
        },
    }


def _dump_base_yaml(data: dict[str, Any]) -> str:
    return (
        yaml.safe_dump(
            data,
            sort_keys=False,
            allow_unicode=True,
            default_flow_style=False,
            width=1000,
        ).rstrip()
        + "\n"
    )


def _write_if_changed(path: Path, text: str) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return False
    path.write_text(text, encoding="utf-8")
    return True


def _build_bases(paths: VaultPaths) -> dict[str, Any]:
    try:
        from .queries import refresh_query_derived_fields
    except ImportError:  # pragma: no cover - defensive fallback for partial imports
        refreshed_queries = 0
    else:
        refreshed_queries = refresh_query_derived_fields(paths)

    files: list[dict[str, Any]] = []
    changed = 0
    for filename, data in _base_documents().items():
        path = paths.bases / filename
        did_change = _write_if_changed(path, _dump_base_yaml(data))
        changed += int(did_change)
        files.append(
            {
                "path": ensure_relative(path, paths.vault),
                "changed": did_change,
                "views": [view["name"] for view in data["views"]],
            }
        )
    return {
        "vault": str(paths.vault),
        "files": files,
        "written": len(files),
        "changed": changed,
        "query_notes_refreshed": refreshed_queries,
    }


def init_bases(vault: Path | str) -> dict[str, Any]:
    from .importer import initialize_vault

    paths = initialize_vault(vault, rebuild=False)
    return _build_bases(paths)


def rebuild_bases(vault: Path | str) -> dict[str, Any]:
    from .importer import initialize_vault

    paths = initialize_vault(vault, rebuild=False)
    return _build_bases(paths)


def _validate_filter(value: Any) -> list[str]:
    if isinstance(value, str):
        return []
    if not isinstance(value, dict):
        return ["filter must be a string or object"]
    keys = set(value)
    if not keys <= {"and", "or", "not"}:
        return [f"filter object has unsupported keys: {', '.join(sorted(keys))}"]
    issues: list[str] = []
    for items in value.values():
        if not isinstance(items, list):
            issues.append("filter group must be a list")
            continue
        for item in items:
            issues.extend(_validate_filter(item))
    return issues


def doctor_bases(vault: Path | str) -> dict[str, Any]:
    paths = VaultPaths.from_root(vault)
    rows: list[dict[str, Any]] = []
    issue_counts = {
        "missing": 0,
        "invalid_yaml": 0,
        "missing_views": 0,
        "invalid_filters": 0,
    }
    for filename, required_views in BASE_VIEW_NAMES.items():
        path = paths.bases / filename
        row: dict[str, Any] = {
            "path": ensure_relative(path, paths.vault),
            "ok": True,
            "views": [],
            "issues": [],
        }
        if not path.exists():
            row["ok"] = False
            row["issues"].append("missing base file")
            issue_counts["missing"] += 1
            rows.append(row)
            continue
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            row["ok"] = False
            row["issues"].append(f"invalid YAML: {exc}")
            issue_counts["invalid_yaml"] += 1
            rows.append(row)
            continue
        if not isinstance(data, dict):
            row["ok"] = False
            row["issues"].append("base YAML must be a mapping")
            issue_counts["invalid_yaml"] += 1
            rows.append(row)
            continue
        views = data.get("views")
        if not isinstance(views, list):
            row["ok"] = False
            row["issues"].append("views must be a list")
            issue_counts["invalid_yaml"] += 1
            rows.append(row)
            continue
        view_names = [str(view.get("name")) for view in views if isinstance(view, dict)]
        row["views"] = view_names
        missing_views = [name for name in required_views if name not in view_names]
        if missing_views:
            row["ok"] = False
            row["issues"].append(f"missing views: {', '.join(missing_views)}")
            issue_counts["missing_views"] += len(missing_views)
        filter_issues = _validate_filter(data.get("filters", ""))
        for view in views:
            if isinstance(view, dict) and "filters" in view:
                filter_issues.extend(_validate_filter(view["filters"]))
        if filter_issues:
            row["ok"] = False
            row["issues"].extend(filter_issues)
            issue_counts["invalid_filters"] += len(filter_issues)
        rows.append(row)
    return {
        "vault": str(paths.vault),
        "ok": not any(issue_counts.values()),
        "issue_counts": issue_counts,
        "bases": rows,
    }
