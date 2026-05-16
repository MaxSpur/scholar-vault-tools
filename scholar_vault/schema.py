from __future__ import annotations

from pathlib import Path
from typing import Any

from .digests import DIGEST_EVIDENCE_LEVELS, DIGEST_REQUIRED_FIELDS, DIGEST_STATUSES
from .evals import EVAL_KINDS
from .labs_prompts import PROMPT_PACK_STATUSES, PROMPT_TYPES
from .models import (
    DiscoveryCandidate,
    FeedbackRecord,
    OperationRecord,
    QueueItem,
)
from .sources import write_json


def _string_array() -> dict[str, Any]:
    return {"type": "array", "items": {"type": "string"}, "default": []}


def _frontmatter_schema(
    *,
    title: str,
    required: list[str],
    properties: dict[str, Any],
) -> dict[str, Any]:
    return {
        "type": "object",
        "title": title,
        "required": required,
        "properties": properties,
        "additionalProperties": True,
    }


def _prompt_pack_schema() -> dict[str, Any]:
    return _frontmatter_schema(
        title="Scholar Labs prompt pack frontmatter",
        required=["type", "status", "created_at"],
        properties={
            "type": {"const": "scholar_labs_prompt_pack"},
            "status": {"enum": sorted(PROMPT_PACK_STATUSES)},
            "query": {"type": "string"},
            "project": {"type": "string"},
            "created_at": {"type": "string", "format": "date-time"},
            "generated_from": _string_array(),
            "linked_runs": _string_array(),
            "linked_tasks": _string_array(),
            "linked_syntheses": _string_array(),
            "linked_concepts": _string_array(),
            "linked_discovery_candidates": _string_array(),
            "prompt_types": {
                "type": "array",
                "items": {"enum": list(PROMPT_TYPES)},
            },
        },
    )


def _digest_schema() -> dict[str, Any]:
    return _frontmatter_schema(
        title="Paper digest frontmatter",
        required=list(DIGEST_REQUIRED_FIELDS),
        properties={
            "type": {"const": "paper_digest"},
            "citekey": {"type": "string"},
            "paper": {"type": "string"},
            "pdf": {"type": ["string", "null"]},
            "status": {"enum": list(DIGEST_STATUSES)},
            "evidence_level": {"enum": list(DIGEST_EVIDENCE_LEVELS)},
            "compiled_at": {"type": ["string", "null"], "format": "date-time"},
            "reviewed_at": {"type": ["string", "null"], "format": "date-time"},
            "linked_queries": _string_array(),
            "linked_projects": _string_array(),
            "linked_concepts": _string_array(),
            "linked_syntheses": _string_array(),
            "source_pages_checked": _string_array(),
            "figures_checked": _string_array(),
            "tables_checked": _string_array(),
        },
    )


def _eval_spec_schema() -> dict[str, Any]:
    return _frontmatter_schema(
        title="Deterministic eval spec",
        required=["id", "kind"],
        properties={
            "id": {"type": "string"},
            "kind": {"enum": sorted(EVAL_KINDS)},
            "title": {"type": "string"},
            "target": {"type": "string"},
            "query": {"type": "string"},
            "synthesis": {"type": "string"},
            "proposal": {"type": "string"},
            "expected_citekeys": _string_array(),
            "required_sources": _string_array(),
            "required_source_links": _string_array(),
            "forbidden_source_only_scholar_labs_citations": {"type": "boolean"},
            "expected_source_matrix_coverage": _string_array(),
        },
    )


def schema_export_payload() -> dict[str, Any]:
    return {
        "schema_version": "0.1",
        "schemas": {
            "queue_item": QueueItem.model_json_schema(),
            "operation_record": OperationRecord.model_json_schema(),
            "feedback_record": FeedbackRecord.model_json_schema(),
            "prompt_pack": _prompt_pack_schema(),
            "discovery_candidate": DiscoveryCandidate.model_json_schema(),
            "paper_digest": _digest_schema(),
            "eval_spec": _eval_spec_schema(),
        },
    }


def export_schema(output: Path | str | None = None) -> dict[str, Any]:
    payload = schema_export_payload()
    if output is None:
        return payload
    output_path = Path(output)
    write_json(output_path, payload)
    return {**payload, "output": str(output_path)}
