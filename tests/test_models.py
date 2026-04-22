from pathlib import Path

import pytest
from pydantic import ValidationError

from scholar_vault.models import ScholarLabsExport


def test_sample_export_parses() -> None:
    fixture = Path(__file__).parent / "fixtures" / "sample_scholar_labs_export.json"
    export = ScholarLabsExport.model_validate_json(fixture.read_text(encoding="utf-8"))

    assert export.schema_version == "0.2"
    assert export.source == "google_scholar_labs"
    assert len(export.prompt) > 20
    assert len(export.results) > 0
    assert export.results[0].scholar_cid == "cid-001"
    assert export.results[1].rationale_points[0].label == "Local-first"


def test_empty_scholar_labs_export_is_rejected() -> None:
    fixture = Path(__file__).parent / "fixtures" / "failed_empty_scholar_labs_export.json"

    with pytest.raises(ValidationError, match="Google Scholar|no results were found"):
        ScholarLabsExport.model_validate_json(fixture.read_text(encoding="utf-8"))


def test_google_scholar_prompt_is_rejected() -> None:
    payload = {
        "schema_version": "0.2",
        "source": "google_scholar_labs",
        "exported_at": "2026-04-22T15:32:20.865Z",
        "prompt": "Google Scholar",
        "results": [
            {
                "rank": 1,
                "scholar_cid": "cid-100",
                "title": "A valid-looking result with an invalid prompt",
                "authors_preview": "Jane Smith",
                "year": 2024,
                "venue_preview": "Test Venue",
                "publisher_or_host": "ACM",
                "summary": "Short summary.",
                "rationale_points": [],
                "links": [],
            }
        ],
    }

    with pytest.raises(ValidationError, match="prompt is 'Google Scholar'"):
        ScholarLabsExport.model_validate(payload)
