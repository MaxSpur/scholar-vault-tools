from __future__ import annotations

from pathlib import Path

from pypdf import PdfWriter


def test_gui_module_imports() -> None:
    from scholar_vault import gui

    assert gui.GuiUnavailable is not None


def test_gui_dependency_loader_smoke() -> None:
    from scholar_vault.gui import _load_qt_modules

    modules = _load_qt_modules(require_fitz=True)

    assert "QApplication" in modules
    assert "fitz" in modules


def test_gui_pdf_preview_render_smoke(tmp_path: Path) -> None:
    from scholar_vault.gui import _load_qt_modules, _render_pdf_image

    pdf = tmp_path / "preview.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=300)
    with pdf.open("wb") as handle:
        writer.write(handle)

    modules = _load_qt_modules(require_fitz=True)
    image = _render_pdf_image(modules, str(pdf), full_page=False)

    assert image.width() > 0
    assert image.height() > 0


def test_preview_viewport_height_targets_top_third() -> None:
    from scholar_vault.gui import _preview_viewport_height

    assert _preview_viewport_height(1500) == 500
    assert _preview_viewport_height(900) == 430
    assert _preview_viewport_height(2400) == 640


def test_confidence_color_thresholds() -> None:
    from scholar_vault.gui import _confidence_color

    assert _confidence_color(100) == "#0067d8"
    assert _confidence_color(95) == "#238200"
    assert _confidence_color(82) == "#a46f00"
    assert _confidence_color(76) == "#c86a00"
    assert _confidence_color(70) == "#b00020"


def test_match_dialog_abort_result_raises() -> None:
    from scholar_vault.gui import _ABORT_DIALOG_CODE, _match_dialog_result
    from scholar_vault.models import MatchReviewAbort

    try:
        _match_dialog_result({}, _ABORT_DIALOG_CODE)
    except MatchReviewAbort:
        pass
    else:
        raise AssertionError("Abort dialog result should raise MatchReviewAbort.")
