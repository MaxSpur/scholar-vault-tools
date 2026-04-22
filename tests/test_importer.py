from pathlib import Path

from pypdf import PdfWriter

from scholar_vault.importer import import_pdf_dropins, import_scholar_labs_run, initialize_vault
from scholar_vault.sources import load_source_cards


def _write_fixture_copy(target: Path) -> Path:
    fixture = Path(__file__).parent / "fixtures" / "sample_scholar_labs_export.json"
    target.write_text(fixture.read_text(encoding="utf-8"), encoding="utf-8")
    return target


def test_import_run_is_idempotent(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    staging = tmp_path / "staging"
    exports = tmp_path / "exports"
    staging.mkdir()
    exports.mkdir()
    export_path = _write_fixture_copy(exports / "sample.json")

    initialize_vault(vault)
    first = import_scholar_labs_run(vault, export_path, staging)
    second = import_scholar_labs_run(vault, export_path, staging)

    cards = load_source_cards(initialize_vault(vault))

    assert first["papers"] == 2
    assert second["papers"] == 2
    assert len(cards) == 2
    assert len(list((vault / "runs").glob("*"))) == 1
    expected_run = "runs/2026-04-22_retrieval-augmented-generation-evaluation/index.md"
    assert cards[0].discovered_in.count(expected_run) == 1


def test_import_pdf_creates_stub_card_and_moves_pdf(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    staging = tmp_path / "staging"
    staging.mkdir()
    initialize_vault(vault)

    pdf_path = staging / "local-rag.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.add_metadata({"/Title": "Local Retrieval Augmented Generation"})
    with pdf_path.open("wb") as handle:
        writer.write(handle)

    summary = import_pdf_dropins(vault, staging)
    cards = load_source_cards(initialize_vault(vault))

    assert summary["imported"] == 1
    assert len(cards) == 1
    assert cards[0].source_kind == "pdf_drop"
    assert cards[0].pdf_status == "attached"
    assert cards[0].pdf is not None
    assert (vault / cards[0].pdf).exists()
