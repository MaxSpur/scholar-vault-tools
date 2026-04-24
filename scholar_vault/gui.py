from __future__ import annotations

from pathlib import Path
from typing import Any

from .models import MatchReviewAbort, MatchReviewRequest

_ABORT_DIALOG_CODE = 2


class GuiUnavailable(RuntimeError):
    """Raised when desktop GUI dependencies are not installed or usable."""


def _load_qt_modules(*, require_fitz: bool) -> dict[str, Any]:
    try:
        from PySide6.QtCore import Qt, QUrl
        from PySide6.QtGui import QDesktopServices, QFont, QImage, QKeySequence, QPixmap, QShortcut
        from PySide6.QtWidgets import (
            QApplication,
            QComboBox,
            QDialog,
            QDialogButtonBox,
            QFileDialog,
            QFrame,
            QGridLayout,
            QHBoxLayout,
            QLabel,
            QLineEdit,
            QMessageBox,
            QProgressBar,
            QPushButton,
            QRadioButton,
            QScrollArea,
            QTableWidget,
            QTableWidgetItem,
            QVBoxLayout,
            QWidget,
        )
    except ImportError as exc:
        raise GuiUnavailable(
            "install or refresh dependencies with `python -m pip install -e .`"
        ) from exc

    modules: dict[str, Any] = {
        "QApplication": QApplication,
        "QComboBox": QComboBox,
        "QDesktopServices": QDesktopServices,
        "QDialog": QDialog,
        "QDialogButtonBox": QDialogButtonBox,
        "QFileDialog": QFileDialog,
        "QFrame": QFrame,
        "QFont": QFont,
        "QGridLayout": QGridLayout,
        "QHBoxLayout": QHBoxLayout,
        "QImage": QImage,
        "QKeySequence": QKeySequence,
        "QLabel": QLabel,
        "QLineEdit": QLineEdit,
        "QMessageBox": QMessageBox,
        "QPixmap": QPixmap,
        "QProgressBar": QProgressBar,
        "QPushButton": QPushButton,
        "QRadioButton": QRadioButton,
        "QScrollArea": QScrollArea,
        "QShortcut": QShortcut,
        "QTableWidget": QTableWidget,
        "QTableWidgetItem": QTableWidgetItem,
        "QUrl": QUrl,
        "QVBoxLayout": QVBoxLayout,
        "QWidget": QWidget,
        "Qt": Qt,
    }
    if require_fitz:
        try:
            import fitz
        except ImportError as exc:
            raise GuiUnavailable(
                "install or refresh dependencies with `python -m pip install -e .`"
            ) from exc
        modules["fitz"] = fitz
    return modules


def _application(qt: dict[str, Any]):
    app = qt["QApplication"].instance()
    if app is None:
        app = qt["QApplication"]([])
    return app


def _open_path(qt: dict[str, Any], path: str | None) -> None:
    if not path:
        return
    qt["QDesktopServices"].openUrl(qt["QUrl"].fromLocalFile(str(Path(path).expanduser())))


def _render_pdf_image(
    qt: dict[str, Any],
    pdf_path: str,
    *,
    full_page: bool,
):
    fitz = qt["fitz"]
    doc = fitz.open(str(Path(pdf_path).expanduser()))
    try:
        page = doc.load_page(0)
        rect = page.rect
        clip = rect if full_page else fitz.Rect(0, 0, rect.width, rect.height * 0.55)
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), clip=clip, alpha=False)
        image = qt["QImage"](
            pix.samples,
            pix.width,
            pix.height,
            pix.stride,
            qt["QImage"].Format.Format_RGB888,
        )
        return image.copy()
    finally:
        doc.close()


def _preview_viewport_height(pixmap_height: int) -> int:
    return min(640, max(430, pixmap_height // 3))


def _confidence_color(score: int) -> str:
    if score >= 100:
        return "#0067d8"
    if score >= 85:
        return "#238200"
    if score >= 80:
        return "#a46f00"
    if score >= 73:
        return "#c86a00"
    return "#b00020"


def _scroll_preview(qt: dict[str, Any], scroll: Any, *, direction: int = 1) -> None:
    bar = scroll.verticalScrollBar()
    step = max(120, scroll.viewport().height() // 2)
    target = bar.value() + (step * direction)
    bar.setValue(max(bar.minimum(), min(bar.maximum(), target)))


class _MatchReviewer:
    def __init__(self, qt: dict[str, Any]) -> None:
        self._qt = qt
        self._app = _application(qt)

    def __call__(self, request: MatchReviewRequest) -> bool:
        dialog = _build_match_dialog(self._qt, request)
        return _match_dialog_result(self._qt, dialog.exec())


def make_match_reviewer():
    return _MatchReviewer(_load_qt_modules(require_fitz=True))


class _Confirmer:
    def __init__(self, qt: dict[str, Any], title: str) -> None:
        self._qt = qt
        self._app = _application(qt)
        self._title = title

    def __call__(self, prompt: str) -> bool:
        box = self._qt["QMessageBox"]()
        box.setWindowTitle(self._title)
        box.setIcon(self._qt["QMessageBox"].Icon.Question)
        box.setText(prompt)
        box.setStandardButtons(
            self._qt["QMessageBox"].StandardButton.Yes
            | self._qt["QMessageBox"].StandardButton.No
        )
        box.setDefaultButton(self._qt["QMessageBox"].StandardButton.No)
        box.setEscapeButton(self._qt["QMessageBox"].StandardButton.No)
        result = box.exec()
        self._app.processEvents()
        return result == self._qt["QMessageBox"].StandardButton.Yes


def make_confirmer(title: str = "Scholar Vault") -> _Confirmer:
    return _Confirmer(_load_qt_modules(require_fitz=False), title)


def edit_configuration(config: dict[str, Any]) -> dict[str, Any] | None:
    qt = _load_qt_modules(require_fitz=False)
    app = _application(qt)
    dialog = qt["QDialog"]()
    dialog.setWindowTitle("Scholar Vault Configuration")
    dialog.resize(860, 430)

    layout = qt["QVBoxLayout"](dialog)
    layout.setSpacing(14)

    intro = qt["QLabel"](
        "Choose default folders for Scholar Vault. Commands still accept explicit paths "
        "that override these defaults."
    )
    intro.setWordWrap(True)
    layout.addWidget(intro)

    mode_row = qt["QVBoxLayout"]()
    shared_mode = qt["QRadioButton"](
        "Use one staging folder for PDFs and Scholar Labs JSON exports"
    )
    separate_mode = qt["QRadioButton"]("Use separate folders for PDF staging and JSON exports")
    separate_mode.setChecked(bool(config.get("exports")))
    shared_mode.setChecked(not bool(config.get("exports")))
    mode_row.addWidget(shared_mode)
    mode_row.addWidget(separate_mode)
    layout.addLayout(mode_row)

    form = qt["QGridLayout"]()
    form.setHorizontalSpacing(10)
    form.setVerticalSpacing(10)
    layout.addLayout(form, 1)

    edits: dict[str, Any] = {}
    browse_buttons: dict[str, Any] = {}

    def add_folder_row(row: int, key: str, label: str) -> None:
        field_label = qt["QLabel"](label)
        edit = qt["QLineEdit"](str(config.get(key) or ""))
        edit.setMinimumWidth(580)
        browse = qt["QPushButton"]("Choose...")

        def choose_folder() -> None:
            start = edit.text().strip() or str(Path.home())
            selected = qt["QFileDialog"].getExistingDirectory(dialog, f"Choose {label}", start)
            if selected:
                edit.setText(selected)

        browse.clicked.connect(choose_folder)
        form.addWidget(field_label, row, 0)
        form.addWidget(edit, row, 1)
        form.addWidget(browse, row, 2)
        edits[key] = edit
        browse_buttons[key] = browse

    add_folder_row(0, "vault", "Vault")
    add_folder_row(1, "staging", "Staging")
    add_folder_row(2, "exports", "Exports")
    add_folder_row(3, "code", "Code")
    edits["exports"].setPlaceholderText("Only used in separate-folder mode")

    result: dict[str, Any] | None = None

    def set_exports_enabled() -> None:
        enabled = separate_mode.isChecked()
        edits["exports"].setEnabled(enabled)
        browse_buttons["exports"].setEnabled(enabled)

    def show_warning(message: str) -> None:
        box = qt["QMessageBox"](dialog)
        box.setWindowTitle("Scholar Vault Configuration")
        box.setIcon(qt["QMessageBox"].Icon.Warning)
        box.setText(message)
        box.exec()

    def normalized_folder(key: str) -> str:
        raw = edits[key].text().strip()
        if not raw:
            return ""
        path = Path(raw).expanduser()
        if not path.is_dir():
            raise ValueError(f"{key} is not an existing folder:\n{path}")
        return str(path.resolve())

    def save() -> None:
        nonlocal result
        keys = ["vault", "staging", "code"]
        if separate_mode.isChecked():
            keys.append("exports")
        try:
            normalized = {key: normalized_folder(key) for key in keys}
        except ValueError as exc:
            show_warning(str(exc))
            return
        if shared_mode.isChecked() and not normalized["staging"]:
            show_warning("Choose a staging folder for shared-folder mode.")
            return
        if separate_mode.isChecked() and not normalized.get("exports"):
            show_warning("Choose an exports folder for separate-folder mode.")
            return

        updated = dict(config)
        for key in ("vault", "staging", "code"):
            if normalized[key]:
                updated[key] = normalized[key]
            else:
                updated.pop(key, None)
        if separate_mode.isChecked():
            updated["exports"] = normalized["exports"]
        else:
            updated.pop("exports", None)
        result = updated
        dialog.accept()

    shared_mode.toggled.connect(set_exports_enabled)
    separate_mode.toggled.connect(set_exports_enabled)
    set_exports_enabled()

    buttons = qt["QDialogButtonBox"](
        qt["QDialogButtonBox"].StandardButton.Save
        | qt["QDialogButtonBox"].StandardButton.Cancel
    )
    buttons.accepted.connect(save)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)

    dialog.exec()
    app.processEvents()
    return result


def _match_dialog_result(qt: dict[str, Any], result: int) -> bool:
    if result == _ABORT_DIALOG_CODE:
        raise MatchReviewAbort("Import aborted from match review.")
    return result == qt["QDialog"].DialogCode.Accepted


def _metadata_line(request: MatchReviewRequest) -> str:
    parts = [f"rank {request.rank}", f"score {request.score}"]
    if request.authors_preview:
        parts.append(request.authors_preview)
    if request.year:
        parts.append(str(request.year))
    if request.venue:
        parts.append(request.venue)
    return " | ".join(parts)


def _build_match_dialog(qt: dict[str, Any], request: MatchReviewRequest):
    class MatchDialog(qt["QDialog"]):
        def keyPressEvent(self, event):  # noqa: N802 - Qt override name
            if event.key() == qt["Qt"].Key.Key_Escape:
                self.done(_ABORT_DIALOG_CODE)
                return
            super().keyPressEvent(event)

        def closeEvent(self, event):  # noqa: N802 - Qt override name
            event.ignore()
            self.done(_ABORT_DIALOG_CODE)

    dialog = MatchDialog()
    dialog.setWindowTitle("Scholar Vault Match Review")
    dialog.resize(1560, 960)

    layout = qt["QVBoxLayout"](dialog)
    layout.setContentsMargins(38, 28, 38, 28)
    layout.setSpacing(18)

    body = qt["QHBoxLayout"]()
    body.setSpacing(34)
    layout.addLayout(body, 1)

    document_column = qt["QWidget"]()
    document_layout = qt["QVBoxLayout"](document_column)
    document_layout.setContentsMargins(0, 0, 0, 0)
    document_layout.setSpacing(16)

    title = qt["QLabel"](request.result_title)
    title.setWordWrap(True)
    title.setAlignment(qt["Qt"].AlignmentFlag.AlignCenter)
    title_font = qt["QFont"]()
    title_font.setPointSize(30)
    title_font.setBold(True)
    title.setFont(title_font)
    document_layout.addWidget(title)

    metadata = qt["QLabel"](_metadata_line(request))
    metadata.setWordWrap(True)
    metadata.setAlignment(qt["Qt"].AlignmentFlag.AlignCenter)
    metadata_font = qt["QFont"]()
    metadata_font.setPointSize(15)
    metadata.setFont(metadata_font)
    document_layout.addWidget(metadata)

    preview = qt["QLabel"]()
    preview.setAlignment(qt["Qt"].AlignmentFlag.AlignTop | qt["Qt"].AlignmentFlag.AlignHCenter)
    preview.setWordWrap(True)

    scroll = qt["QScrollArea"]()
    scroll.setWidgetResizable(True)
    scroll.setWidget(preview)
    scroll.setHorizontalScrollBarPolicy(qt["Qt"].ScrollBarPolicy.ScrollBarAsNeeded)
    scroll.setVerticalScrollBarPolicy(qt["Qt"].ScrollBarPolicy.ScrollBarAlwaysOn)
    document_layout.addWidget(scroll, 0, qt["Qt"].AlignmentFlag.AlignTop)
    document_layout.addStretch(1)
    body.addWidget(document_column, 1, qt["Qt"].AlignmentFlag.AlignTop)

    side = _build_match_side_panel(qt, request, dialog, scroll)
    body.addWidget(side, 0, qt["Qt"].AlignmentFlag.AlignTop)

    def refresh_preview() -> None:
        try:
            image = _render_pdf_image(qt, request.pdf_path, full_page=True)
            pixmap = qt["QPixmap"].fromImage(image)
            scaled = pixmap.scaledToWidth(
                1100,
                qt["Qt"].TransformationMode.SmoothTransformation,
            )
            preview.setPixmap(scaled)
            preview.setMinimumSize(scaled.size())
            scroll.setFixedHeight(_preview_viewport_height(scaled.height()))
            scroll.verticalScrollBar().setValue(0)
            preview.setText("")
        except Exception as exc:
            preview.setPixmap(qt["QPixmap"]())
            scroll.setFixedHeight(560)
            preview.setText(
                "PDF preview unavailable.\n\n"
                f"{exc}\n\n"
                f"{(request.text_excerpt or '').strip()[:2500]}"
            )

    hint = qt["QLabel"](
        "Shortcuts: Return / Right / Y accept, Left / Backspace / N reject, "
        "Esc aborts import, Space scrolls preview, O opens PDF."
    )
    hint.setAlignment(qt["Qt"].AlignmentFlag.AlignCenter)
    layout.addWidget(hint)

    qt["QShortcut"](qt["QKeySequence"]("Y"), dialog).activated.connect(dialog.accept)
    qt["QShortcut"](qt["QKeySequence"]("Return"), dialog).activated.connect(dialog.accept)
    qt["QShortcut"](qt["QKeySequence"]("Enter"), dialog).activated.connect(dialog.accept)
    qt["QShortcut"](qt["QKeySequence"]("Right"), dialog).activated.connect(dialog.accept)
    qt["QShortcut"](qt["QKeySequence"]("N"), dialog).activated.connect(dialog.reject)
    qt["QShortcut"](qt["QKeySequence"]("Escape"), dialog).activated.connect(
        lambda: dialog.done(_ABORT_DIALOG_CODE)
    )
    qt["QShortcut"](qt["QKeySequence"]("Left"), dialog).activated.connect(dialog.reject)
    qt["QShortcut"](qt["QKeySequence"]("Backspace"), dialog).activated.connect(dialog.reject)
    qt["QShortcut"](qt["QKeySequence"]("Space"), dialog).activated.connect(
        lambda: _scroll_preview(qt, scroll, direction=1)
    )
    qt["QShortcut"](qt["QKeySequence"]("Shift+Space"), dialog).activated.connect(
        lambda: _scroll_preview(qt, scroll, direction=-1)
    )
    qt["QShortcut"](qt["QKeySequence"]("O"), dialog).activated.connect(
        lambda: _open_path(qt, request.pdf_path)
    )
    qt["QShortcut"](qt["QKeySequence"]("Meta+O"), dialog).activated.connect(
        lambda: _open_path(qt, request.pdf_path)
    )
    qt["QShortcut"](qt["QKeySequence"]("Ctrl+O"), dialog).activated.connect(
        lambda: _open_path(qt, request.pdf_path)
    )
    refresh_preview()
    return dialog


def _build_match_side_panel(
    qt: dict[str, Any],
    request: MatchReviewRequest,
    dialog: Any,
    scroll: Any,
) -> Any:
    side = qt["QWidget"]()
    side.setFixedWidth(340)
    side_layout = qt["QVBoxLayout"](side)
    side_layout.setContentsMargins(0, 0, 0, 0)
    side_layout.setSpacing(24)

    confidence = qt["QFrame"]()
    confidence.setFrameShape(qt["QFrame"].Shape.StyledPanel)
    confidence.setMinimumHeight(145)
    confidence_layout = qt["QVBoxLayout"](confidence)
    confidence_label = qt["QLabel"]("Confidence")
    confidence_label.setAlignment(qt["Qt"].AlignmentFlag.AlignCenter)
    confidence_label_font = qt["QFont"]()
    confidence_label_font.setPointSize(18)
    confidence_label_font.setBold(True)
    confidence_label.setFont(confidence_label_font)
    confidence_value = qt["QLabel"](f"{request.score}%")
    confidence_value.setAlignment(qt["Qt"].AlignmentFlag.AlignCenter)
    confidence_value_font = qt["QFont"]("Menlo")
    confidence_value_font.setStyleHint(qt["QFont"].StyleHint.Monospace)
    confidence_value_font.setPointSize(43)
    confidence_value_font.setBold(True)
    confidence_value.setFont(confidence_value_font)
    confidence_value.setStyleSheet(f"color: {_confidence_color(request.score)};")
    confidence_layout.addWidget(confidence_label)
    confidence_layout.addWidget(confidence_value)
    side_layout.addWidget(confidence)

    accept = qt["QPushButton"]("YES")
    accept.setMinimumHeight(185)
    accept.setFocusPolicy(qt["Qt"].FocusPolicy.NoFocus)
    accept_font = qt["QFont"]()
    accept_font.setPointSize(40)
    accept_font.setBold(True)
    accept.setFont(accept_font)
    accept.clicked.connect(dialog.accept)
    side_layout.addWidget(accept)

    reject = qt["QPushButton"]("NO")
    reject.setMinimumHeight(185)
    reject.setFocusPolicy(qt["Qt"].FocusPolicy.NoFocus)
    reject.setFont(accept_font)
    reject.clicked.connect(dialog.reject)
    side_layout.addWidget(reject)

    abort = qt["QPushButton"]("Abort Import")
    abort.setMinimumHeight(52)
    abort.setFocusPolicy(qt["Qt"].FocusPolicy.NoFocus)
    abort.clicked.connect(lambda: dialog.done(_ABORT_DIALOG_CODE))
    side_layout.addWidget(abort)

    open_pdf = qt["QPushButton"]("Open PDF")
    open_pdf.setMinimumHeight(44)
    open_pdf.setFocusPolicy(qt["Qt"].FocusPolicy.NoFocus)
    open_pdf.clicked.connect(lambda: _open_path(qt, request.pdf_path))
    side_layout.addWidget(open_pdf)

    scroll_down = qt["QPushButton"]("Scroll Preview")
    scroll_down.setMinimumHeight(44)
    scroll_down.setFocusPolicy(qt["Qt"].FocusPolicy.NoFocus)
    scroll_down.clicked.connect(lambda: _scroll_preview(qt, scroll, direction=1))
    side_layout.addWidget(scroll_down)

    side_layout.addStretch(1)
    return side


class _ProgressReporter:
    def __init__(self, qt: dict[str, Any], title: str) -> None:
        self._qt = qt
        self._app = _application(qt)
        self._cancelled = False
        self._dialog = qt["QDialog"]()
        self._dialog.setWindowTitle(title)
        self._dialog.resize(620, 150)

        layout = qt["QVBoxLayout"](self._dialog)
        self._label = qt["QLabel"]("Starting...")
        self._label.setWordWrap(True)
        layout.addWidget(self._label)

        self._bar = qt["QProgressBar"]()
        self._bar.setRange(0, 0)
        layout.addWidget(self._bar)

        buttons = qt["QHBoxLayout"]()
        buttons.addStretch(1)
        self._cancel = qt["QPushButton"]("Cancel Import")
        self._cancel.clicked.connect(self._request_cancel)
        buttons.addWidget(self._cancel)
        layout.addLayout(buttons)

        self._dialog.show()
        self._app.processEvents()

    def _request_cancel(self) -> None:
        self._cancelled = True
        self._label.setText("Canceling after the current step...")
        self._app.processEvents()

    def __call__(
        self,
        message: str,
        current: int | None = None,
        total: int | None = None,
    ) -> None:
        if self._cancelled:
            raise MatchReviewAbort("Import canceled from progress window.")
        if current is not None and total:
            self._bar.setRange(0, total)
            self._bar.setValue(current)
            self._label.setText(f"[{current}/{total}] {message}")
        else:
            self._bar.setRange(0, 0)
            self._label.setText(message)
        self._app.processEvents()
        if self._cancelled:
            raise MatchReviewAbort("Import canceled from progress window.")

    def close(self) -> None:
        self._dialog.accept()
        self._app.processEvents()


def make_progress_reporter(title: str):
    return _ProgressReporter(_load_qt_modules(require_fitz=False), title)


def show_import_summary(lines: list[str], *, title: str = "Scholar Vault Import Summary") -> None:
    qt = _load_qt_modules(require_fitz=False)
    app = _application(qt)
    dialog = qt["QDialog"]()
    dialog.setWindowTitle(title)
    dialog.resize(760, 360)

    layout = qt["QVBoxLayout"](dialog)
    heading = qt["QLabel"]("Import Summary")
    heading_font = qt["QFont"]()
    heading_font.setPointSize(18)
    heading_font.setBold(True)
    heading.setFont(heading_font)
    layout.addWidget(heading)

    body = qt["QLabel"]("\n".join(lines))
    body.setWordWrap(True)
    body.setTextInteractionFlags(qt["Qt"].TextInteractionFlag.TextSelectableByMouse)
    layout.addWidget(body, 1)

    buttons = qt["QDialogButtonBox"](qt["QDialogButtonBox"].StandardButton.Ok)
    buttons.accepted.connect(dialog.accept)
    layout.addWidget(buttons)
    qt["QShortcut"](qt["QKeySequence"]("Escape"), dialog).activated.connect(dialog.accept)
    dialog.exec()
    app.processEvents()


def show_enrichment_results(
    details: list[dict[str, Any]],
    *,
    abstracts: bool = False,
    title: str | None = None,
) -> None:
    qt = _load_qt_modules(require_fitz=False)
    app = _application(qt)
    dialog = qt["QDialog"]()
    window_title = title or (
        "Scholar Vault Abstract Results" if abstracts else "Scholar Vault Citation Results"
    )
    dialog.setWindowTitle(window_title)
    dialog.resize(1180, 680)

    layout = qt["QVBoxLayout"](dialog)
    filter_row = qt["QHBoxLayout"]()
    category_filter = qt["QComboBox"]()
    ordered = [
        "all",
        "generated",
        "resolved",
        "verified",
        "incomplete",
        "ambiguous",
        "unresolved",
        "skipped",
    ]
    categories = [
        category
        for category in ordered
        if category == "all" or _has_category(details, category)
    ]
    category_filter.addItems([category.title() for category in categories])
    filter_row.addWidget(qt["QLabel"]("Status"))
    filter_row.addWidget(category_filter)
    filter_row.addStretch(1)
    layout.addLayout(filter_row)

    table = qt["QTableWidget"]()
    table.setColumnCount(8)
    table.setHorizontalHeaderLabels(
        ["Type", "Status", "Citekey", "Title", "DOI", "Source", "Missing", "Message"]
    )
    table.setSelectionBehavior(table.SelectionBehavior.SelectRows)
    table.setEditTriggers(table.EditTrigger.NoEditTriggers)
    layout.addWidget(table, 1)

    visible: list[dict[str, Any]] = []

    def refresh_table() -> None:
        selected_category = categories[category_filter.currentIndex()]
        visible.clear()
        visible.extend(
            row
            for row in details
            if selected_category == "all" or row.get("category") == selected_category
        )
        table.setRowCount(len(visible))
        for row_index, row in enumerate(visible):
            values = [
                row.get("kind"),
                row.get("category"),
                row.get("citekey"),
                row.get("title"),
                row.get("doi"),
                row.get("source"),
                ", ".join(row.get("missing_fields") or []),
                row.get("message"),
            ]
            for column, value in enumerate(values):
                table.setItem(row_index, column, qt["QTableWidgetItem"](str(value or "")))
        table.resizeColumnsToContents()

    def selected_detail() -> dict[str, Any] | None:
        row = table.currentRow()
        if row < 0 or row >= len(visible):
            return None
        return visible[row]

    buttons = qt["QHBoxLayout"]()
    open_card = qt["QPushButton"]("Open Card")
    open_pdf = qt["QPushButton"]("Open PDF")
    copy_citekey = qt["QPushButton"]("Copy Citekey")
    copy_doi = qt["QPushButton"]("Copy DOI")
    close = qt["QPushButton"]("Close")
    buttons.addWidget(open_card)
    buttons.addWidget(open_pdf)
    buttons.addWidget(copy_citekey)
    buttons.addWidget(copy_doi)
    buttons.addStretch(1)
    buttons.addWidget(close)
    layout.addLayout(buttons)

    open_card.clicked.connect(
        lambda: _open_path(qt, str((selected_detail() or {}).get("paper_file") or ""))
    )
    open_pdf.clicked.connect(
        lambda: _open_path(qt, str((selected_detail() or {}).get("pdf_file") or ""))
    )
    copy_citekey.clicked.connect(lambda: _copy_detail(qt, selected_detail(), "citekey"))
    copy_doi.clicked.connect(lambda: _copy_detail(qt, selected_detail(), "doi"))
    close.clicked.connect(dialog.accept)
    category_filter.currentIndexChanged.connect(refresh_table)
    qt["QShortcut"](qt["QKeySequence"]("Escape"), dialog).activated.connect(dialog.accept)

    refresh_table()
    dialog.exec()
    app.processEvents()


def _copy_detail(qt: dict[str, Any], detail: dict[str, Any] | None, key: str) -> None:
    if not detail:
        return
    value = detail.get(key)
    if value:
        qt["QApplication"].clipboard().setText(str(value))


def _has_category(details: list[dict[str, Any]], category: str) -> bool:
    return any(row.get("category") == category for row in details)
