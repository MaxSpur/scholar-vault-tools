from __future__ import annotations

from pathlib import Path
from typing import Any

from .gui_common import (
    _application,
    _dark_dialog_stylesheet,
    _load_qt_modules,
    _style_button,
    _style_message_box,
    _summary_font,
)


def choose_pdf_import_files(
    vault: Path | str,
    staging: Path | str | None = None,
    *,
    auto_enrich: bool = True,
) -> dict[str, Any] | None:
    qt = _load_qt_modules(require_fitz=False)
    app = _application(qt)
    dialog = qt["QDialog"]()
    dialog.setWindowTitle("Scholar Vault PDF Import")
    dialog.resize(900, 680)
    dialog.setStyleSheet(_dark_dialog_stylesheet())

    selected: list[Path] = []
    result: dict[str, Any] | None = None

    layout = qt["QVBoxLayout"](dialog)
    layout.setContentsMargins(28, 24, 28, 22)
    layout.setSpacing(14)

    kicker = qt["QLabel"]("SCHOLAR VAULT // PDF IMPORT")
    kicker.setFont(_summary_font(qt, 12, mono=True, bold=True))
    kicker.setStyleSheet("color: #69ffad;")
    layout.addWidget(kicker)

    heading = qt["QLabel"]("DROP PAPERS")
    heading.setFont(_summary_font(qt, 30, bold=True))
    heading.setStyleSheet("color: #f3fff7;")
    layout.addWidget(heading)

    vault_label = qt["QLabel"](f"Vault: {Path(vault).expanduser().resolve()}")
    vault_label.setWordWrap(True)
    vault_label.setFont(_summary_font(qt, 11, mono=True))
    vault_label.setStyleSheet("color: #8ce7b8;")
    layout.addWidget(vault_label)

    class PdfDropFrame(qt["QFrame"]):
        def dragEnterEvent(self, event) -> None:  # noqa: N802 - Qt API
            if _event_pdf_paths(event):
                event.acceptProposedAction()
            else:
                event.ignore()

        def dropEvent(self, event) -> None:  # noqa: N802 - Qt API
            paths = _event_pdf_paths(event)
            if paths:
                add_paths(paths)
                event.acceptProposedAction()
            else:
                event.ignore()

    drop = PdfDropFrame()
    drop.setAcceptDrops(True)
    drop.setMinimumHeight(150)
    drop.setStyleSheet(
        "QFrame { background: #07100b; border: 2px dashed #45ffb0; }"
        "QLabel { border: none; }"
    )
    drop_layout = qt["QVBoxLayout"](drop)
    drop_layout.setContentsMargins(18, 18, 18, 18)
    drop_label = qt["QLabel"]("Drop one or more PDF files here")
    drop_label.setAlignment(qt["Qt"].AlignmentFlag.AlignCenter)
    drop_label.setFont(_summary_font(qt, 20, bold=True))
    drop_label.setStyleSheet("color: #f3fff7;")
    drop_layout.addWidget(drop_label, 1)
    drop_hint = qt["QLabel"]("The originals stay where they are; vault copies are created.")
    drop_hint.setAlignment(qt["Qt"].AlignmentFlag.AlignCenter)
    drop_hint.setFont(_summary_font(qt, 11))
    drop_hint.setStyleSheet("color: #8ce7b8;")
    drop_layout.addWidget(drop_hint)
    layout.addWidget(drop)

    selected_label = qt["QLabel"]("SELECTED PDFS")
    selected_label.setFont(_summary_font(qt, 10, mono=True, bold=True))
    selected_label.setStyleSheet("color: #69ffad;")
    layout.addWidget(selected_label)

    selected_list = qt["QTextEdit"]()
    selected_list.setReadOnly(True)
    selected_list.setMinimumHeight(150)
    selected_list.setFont(_summary_font(qt, 10, mono=True))
    selected_list.setStyleSheet(
        "QTextEdit { color: #d7ffe8; background: #00120b; border: 1px solid #006b45; "
        "padding: 10px; }"
    )
    layout.addWidget(selected_list, 1)

    option_row = qt["QHBoxLayout"]()
    enrich_box = qt["QCheckBox"]("Run automatic citation, abstract, and keyword enrichment")
    enrich_box.setChecked(auto_enrich)
    enrich_box.setFont(_summary_font(qt, 11))
    option_row.addWidget(enrich_box, 1)
    followup_box = qt["QCheckBox"]("Open follow-up editor for unresolved fields")
    followup_box.setChecked(True)
    followup_box.setFont(_summary_font(qt, 11))
    option_row.addWidget(followup_box, 1)
    layout.addLayout(option_row)

    action_row = qt["QHBoxLayout"]()
    add_button = qt["QPushButton"]("Choose PDFs")
    staging_button = qt["QPushButton"]("Add Staging PDFs")
    clear_button = qt["QPushButton"]("Clear")
    for button, tone in [
        (add_button, "primary"),
        (staging_button, "neutral"),
        (clear_button, "muted"),
    ]:
        _style_button(button, tone)
        action_row.addWidget(button)
    action_row.addStretch(1)
    layout.addLayout(action_row)

    buttons = qt["QDialogButtonBox"](
        qt["QDialogButtonBox"].StandardButton.Ok
        | qt["QDialogButtonBox"].StandardButton.Cancel
    )
    ok_button = buttons.button(qt["QDialogButtonBox"].StandardButton.Ok)
    if ok_button is not None:
        ok_button.setText("Import & Enrich" if enrich_box.isChecked() else "Import PDFs")
        _style_button(ok_button, "success")
        ok_button.setEnabled(False)
    cancel_button = buttons.button(qt["QDialogButtonBox"].StandardButton.Cancel)
    if cancel_button is not None:
        _style_button(cancel_button, "muted")
    layout.addWidget(buttons)

    staging_path = Path(staging).expanduser().resolve() if staging else None
    staging_button.setEnabled(bool(staging_path and staging_path.is_dir()))

    def _event_pdf_paths(event) -> list[Path]:
        mime = event.mimeData()
        if not mime.hasUrls():
            return []
        paths: list[Path] = []
        for url in mime.urls():
            if url.isLocalFile():
                path = Path(url.toLocalFile()).expanduser().resolve()
                if path.is_file() and path.suffix.casefold() == ".pdf":
                    paths.append(path)
        return paths

    def render_selected() -> None:
        if not selected:
            selected_list.setPlainText("No PDFs selected yet.")
            drop_label.setText("Drop one or more PDF files here")
        else:
            selected_list.setPlainText(
                "\n".join(f"{index:02d}. {path}" for index, path in enumerate(selected, 1))
            )
            noun = "PDF" if len(selected) == 1 else "PDFs"
            drop_label.setText(f"{len(selected)} {noun} ready to import")
        if ok_button is not None:
            ok_button.setEnabled(bool(selected))

    def add_paths(paths: list[Path]) -> None:
        existing = {path for path in selected}
        for path in paths:
            if path not in existing:
                selected.append(path)
                existing.add(path)
        selected.sort(key=lambda path: path.name.casefold())
        render_selected()

    def choose_files() -> None:
        start_dir = str(staging_path or Path.home())
        files, _selected_filter = qt["QFileDialog"].getOpenFileNames(
            dialog,
            "Choose PDF Files",
            start_dir,
            "PDF files (*.pdf)",
        )
        add_paths([Path(file).expanduser().resolve() for file in files])

    def add_staging() -> None:
        if staging_path and staging_path.is_dir():
            add_paths(sorted(staging_path.glob("*.pdf")))

    def clear() -> None:
        selected.clear()
        render_selected()

    def accept() -> None:
        nonlocal result
        if not selected:
            box = qt["QMessageBox"](dialog)
            box.setWindowTitle("No PDFs Selected")
            box.setText("Drop or choose at least one PDF before importing.")
            box.setStandardButtons(qt["QMessageBox"].StandardButton.Ok)
            _style_message_box(qt, box)
            box.exec()
            return
        result = {
            "pdfs": [str(path) for path in selected],
            "auto_enrich": enrich_box.isChecked(),
            "open_followup": followup_box.isChecked(),
        }
        dialog.accept()

    def update_ok_label() -> None:
        if ok_button is not None:
            ok_button.setText("Import & Enrich" if enrich_box.isChecked() else "Import PDFs")

    add_button.clicked.connect(choose_files)
    staging_button.clicked.connect(add_staging)
    clear_button.clicked.connect(clear)
    enrich_box.toggled.connect(update_ok_label)
    buttons.accepted.connect(accept)
    buttons.rejected.connect(dialog.reject)
    qt["QShortcut"](qt["QKeySequence"]("Escape"), dialog).activated.connect(dialog.reject)
    render_selected()
    dialog.exec()
    app.processEvents()
    return result


