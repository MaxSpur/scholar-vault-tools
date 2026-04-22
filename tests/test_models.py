from pathlib import Path

from scholar_vault.models import ScholarLabsExport


def test_sample_export_parses() -> None:
    fixture = Path(__file__).parent / "fixtures" / "sample_scholar_labs_export.json"
    export = ScholarLabsExport.model_validate_json(fixture.read_text(encoding="utf-8"))

    assert export.schema_version == "0.2"
    assert export.source == "google_scholar_labs"
    assert export.results[0].scholar_cid == "cid-001"
    assert export.results[1].rationale_points[0].label == "Local-first"
