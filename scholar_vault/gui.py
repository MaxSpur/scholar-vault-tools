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
            QTextEdit,
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
        "QTextEdit": QTextEdit,
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


def show_import_summary(
    summary: dict[str, Any],
    lines: list[str],
    *,
    title: str = "Scholar Vault Import Summary",
) -> None:
    qt = _load_qt_modules(require_fitz=False)
    app = _application(qt)
    model = _import_summary_model(summary, lines)
    dialog = qt["QDialog"]()
    dialog.setWindowTitle(title)
    dialog.resize(1120, 700)
    dialog.setStyleSheet(
        """
        QDialog { background: #030504; }
        QLabel { color: #baffdc; }
        QPushButton {
            min-width: 92px;
            min-height: 28px;
            padding: 5px 16px;
        }
        """
    )

    shell = qt["QHBoxLayout"](dialog)
    shell.setContentsMargins(0, 0, 0, 0)
    shell.setSpacing(0)

    rail = qt["QFrame"]()
    rail.setFixedWidth(18)
    rail.setStyleSheet("background: #bd0027;")
    shell.addWidget(rail)

    layout = qt["QVBoxLayout"]()
    layout.setContentsMargins(28, 24, 28, 20)
    layout.setSpacing(18)
    shell.addLayout(layout, 1)

    header = qt["QHBoxLayout"]()
    title_block = qt["QVBoxLayout"]()
    kicker = qt["QLabel"]("SCHOLAR VAULT // IMPORT")
    kicker.setFont(_summary_font(qt, 13, mono=True, bold=True))
    kicker.setStyleSheet("color: #69ffad; letter-spacing: 0px;")
    heading = qt["QLabel"]("RUN REPORT")
    heading.setFont(_summary_font(qt, 34, bold=True))
    heading.setStyleSheet("color: #f3fff7;")
    run_label = qt["QLabel"](str(model["run"]))
    run_label.setFont(_summary_font(qt, 12, mono=True))
    run_label.setStyleSheet("color: #68c792;")
    run_label.setWordWrap(True)
    title_block.addWidget(kicker)
    title_block.addWidget(heading)
    title_block.addWidget(run_label)
    header.addLayout(title_block, 1)
    header.addWidget(_summary_status_panel(qt, model), 0)
    layout.addLayout(header)

    metrics = qt["QGridLayout"]()
    metrics.setHorizontalSpacing(12)
    metrics.setVerticalSpacing(12)
    for index, metric in enumerate(model["metrics"]):
        metrics.addWidget(
            _summary_metric_card(qt, metric),
            index // 3,
            index % 3,
        )
    layout.addLayout(metrics)

    middle = qt["QHBoxLayout"]()
    middle.setSpacing(14)
    middle.addWidget(_summary_flow_panel(qt, model), 2)
    middle.addWidget(_summary_breakdown_panel(qt, model), 1)
    layout.addLayout(middle, 1)

    log = qt["QLabel"]("\n".join(model["lines"]))
    log.setWordWrap(True)
    log.setFont(_summary_font(qt, 11, mono=True))
    log.setTextInteractionFlags(qt["Qt"].TextInteractionFlag.TextSelectableByMouse)
    log.setStyleSheet(
        "QLabel { color: #8ce7b8; background: #07100b; "
        "border: 1px solid #26553b; padding: 10px; }"
    )
    layout.addWidget(log)

    buttons = qt["QDialogButtonBox"](qt["QDialogButtonBox"].StandardButton.Ok)
    buttons.accepted.connect(dialog.accept)
    layout.addWidget(buttons)
    qt["QShortcut"](qt["QKeySequence"]("Escape"), dialog).activated.connect(dialog.accept)
    dialog.exec()
    app.processEvents()


def _summary_font(qt: dict[str, Any], size: int, *, mono: bool = False, bold: bool = False):
    if mono:
        family = "Helvetica Neue Condensed Black" if bold else "Helvetica Neue Condensed"
    else:
        family = "Helvetica Neue"
    font = qt["QFont"](family)
    font.setPointSize(size)
    font.setBold(bold)
    return font


def _summary_int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _import_summary_model(summary: dict[str, Any], lines: list[str]) -> dict[str, Any]:
    decisions = summary.get("decision_summary") or {}
    citations = summary.get("citation_enrichment") or {}
    abstracts = summary.get("abstract_enrichment") or {}
    selected = _summary_int(summary.get("selected"))
    unselected = _summary_int(summary.get("unselected_results"))
    export_results = _summary_int(decisions.get("export_results")) or selected + unselected
    review_prompts = _summary_int(decisions.get("review_prompts"))
    review_rejected = _summary_int(decisions.get("review_rejected"))
    reused = _summary_int(decisions.get("prior_selected_reused"))
    linked = _summary_int(decisions.get("existing_cards_linked"))
    new_matches = _summary_int(decisions.get("new_staged_pdf_matches"))
    without_candidate = _summary_int(decisions.get("results_without_candidate"))
    citation_changed = _summary_int(citations.get("changed"))
    abstract_changed = _summary_int(abstracts.get("changed"))

    if review_rejected or unselected:
        status = "CHECK"
        status_detail = f"{unselected} unselected"
        status_color = "#ff3b4f"
    elif new_matches:
        status = "UPDATED"
        status_detail = f"{new_matches} new PDFs"
        status_color = "#38ff9b"
    elif reused == selected and selected:
        status = "REUSED"
        status_detail = "manifest complete"
        status_color = "#45ffb0"
    else:
        status = "COMPLETE"
        status_detail = f"{selected} selected"
        status_color = "#8bffd0"

    return {
        "run": summary.get("run") or "unknown run",
        "status": status,
        "status_detail": status_detail,
        "status_color": status_color,
        "notice": _summary_notice(selected, reused, linked, review_prompts),
        "lines": lines,
        "metrics": [
            {
                "label": "EXPORT",
                "value": export_results,
                "detail": "Scholar Labs results",
                "color": "#8bffd0",
            },
            {
                "label": "SELECTED",
                "value": selected,
                "detail": "paper cards active",
                "color": "#45ffb0",
            },
            {
                "label": "UNSELECTED",
                "value": unselected,
                "detail": "need no card yet",
                "color": "#ff3b4f" if unselected else "#426b58",
            },
            {
                "label": "REUSED",
                "value": reused,
                "detail": "from manifest",
                "color": "#41e893",
            },
            {
                "label": "NEW PDFS",
                "value": new_matches,
                "detail": "accepted now",
                "color": "#f3fff7" if new_matches else "#426b58",
            },
            {
                "label": "REVIEWS",
                "value": review_prompts,
                "detail": f"{review_rejected} rejected",
                "color": "#ffb000" if review_prompts else "#426b58",
            },
        ],
        "flow": [
            ("EXPORT", export_results, "#8bffd0"),
            ("SELECTED", selected, "#45ffb0"),
            ("REUSED", reused, "#41e893"),
            ("LINKED", linked, "#69ffad"),
            ("NEW", new_matches, "#f3fff7"),
            ("LEFT", unselected, "#ff3b4f" if unselected else "#426b58"),
        ],
        "breakdown": [
            (
                "No staged candidate",
                without_candidate,
                "#ff3b4f" if without_candidate else "#426b58",
            ),
            ("Rejected in review", review_rejected, "#ff3b4f" if review_rejected else "#426b58"),
            ("Citations changed", citation_changed, "#45ffb0" if citation_changed else "#426b58"),
            ("Abstracts changed", abstract_changed, "#45ffb0" if abstract_changed else "#426b58"),
        ],
    }


def _summary_notice(selected: int, reused: int, linked: int, review_prompts: int) -> str:
    if review_prompts == 0 and selected and reused == selected:
        return "No review prompts: selected results were already recorded in this run."
    if review_prompts == 0 and (reused or linked):
        return "No review needed for reused manifest entries or attached vault PDFs."
    if review_prompts:
        return "Review prompts appeared only where a staged PDF needed a decision."
    return "No selected results required match review."


def _summary_panel(qt: dict[str, Any], border: str = "#2b6748") -> Any:
    frame = qt["QFrame"]()
    frame.setFrameShape(qt["QFrame"].Shape.StyledPanel)
    frame.setStyleSheet(
        f"QFrame {{ background: #07100b; border: 1px solid {border}; }}"
    )
    return frame


def _summary_status_panel(qt: dict[str, Any], model: dict[str, Any]) -> Any:
    panel = _summary_panel(qt, str(model["status_color"]))
    panel.setFixedWidth(250)
    layout = qt["QVBoxLayout"](panel)
    layout.setContentsMargins(16, 14, 16, 14)
    label = qt["QLabel"]("STATUS")
    label.setFont(_summary_font(qt, 11, mono=True, bold=True))
    label.setStyleSheet("color: #8ce7b8; border: none;")
    value = qt["QLabel"](str(model["status"]))
    value.setFont(_summary_font(qt, 30, mono=True, bold=True))
    value.setStyleSheet(f"color: {model['status_color']}; border: none;")
    detail = qt["QLabel"](str(model["status_detail"]))
    detail.setFont(_summary_font(qt, 12, mono=True))
    detail.setStyleSheet("color: #baffdc; border: none;")
    layout.addWidget(label)
    layout.addWidget(value)
    layout.addWidget(detail)
    return panel


def _summary_metric_card(qt: dict[str, Any], metric: dict[str, Any]) -> Any:
    panel = _summary_panel(qt, str(metric["color"]))
    panel.setMinimumHeight(112)
    layout = qt["QVBoxLayout"](panel)
    layout.setContentsMargins(14, 12, 14, 12)
    label = qt["QLabel"](str(metric["label"]))
    label.setFont(_summary_font(qt, 11, mono=True, bold=True))
    label.setStyleSheet("color: #8ce7b8; border: none;")
    value = qt["QLabel"](str(metric["value"]))
    value.setFont(_summary_font(qt, 34, mono=True, bold=True))
    value.setStyleSheet(f"color: {metric['color']}; border: none;")
    detail = qt["QLabel"](str(metric["detail"]))
    detail.setFont(_summary_font(qt, 11, mono=True))
    detail.setStyleSheet("color: #9bdcb9; border: none;")
    layout.addWidget(label)
    layout.addWidget(value)
    layout.addWidget(detail)
    return panel


def _summary_flow_panel(qt: dict[str, Any], model: dict[str, Any]) -> Any:
    panel = _summary_panel(qt)
    layout = qt["QVBoxLayout"](panel)
    layout.setContentsMargins(14, 12, 14, 12)
    title = qt["QLabel"]("DECISION FLOW")
    title.setFont(_summary_font(qt, 12, mono=True, bold=True))
    title.setStyleSheet("color: #8ce7b8; border: none;")
    layout.addWidget(title)
    row = qt["QHBoxLayout"]()
    row.setSpacing(7)
    for index, (label, value, color) in enumerate(model["flow"]):
        row.addWidget(_summary_flow_node(qt, label, value, color), 1)
        if index < len(model["flow"]) - 1:
            connector = qt["QLabel"](">")
            connector.setFont(_summary_font(qt, 18, mono=True, bold=True))
            connector.setStyleSheet("color: #bd0027; border: none;")
            row.addWidget(connector, 0)
    layout.addLayout(row)
    notice = qt["QLabel"](str(model["notice"]))
    notice.setWordWrap(True)
    notice.setFont(_summary_font(qt, 12, mono=True))
    notice.setStyleSheet("color: #f3fff7; border: none; padding-top: 8px;")
    layout.addWidget(notice)
    return panel


def _summary_flow_node(qt: dict[str, Any], label: str, value: int, color: str) -> Any:
    node = qt["QFrame"]()
    node.setStyleSheet(f"QFrame {{ background: #020403; border: 1px solid {color}; }}")
    layout = qt["QVBoxLayout"](node)
    layout.setContentsMargins(8, 8, 8, 8)
    value_label = qt["QLabel"](str(value))
    value_label.setAlignment(qt["Qt"].AlignmentFlag.AlignCenter)
    value_label.setFont(_summary_font(qt, 22, mono=True, bold=True))
    value_label.setStyleSheet(f"color: {color}; border: none;")
    name_label = qt["QLabel"](label)
    name_label.setAlignment(qt["Qt"].AlignmentFlag.AlignCenter)
    name_label.setFont(_summary_font(qt, 10, mono=True, bold=True))
    name_label.setStyleSheet("color: #8ce7b8; border: none;")
    layout.addWidget(value_label)
    layout.addWidget(name_label)
    return node


def _summary_breakdown_panel(qt: dict[str, Any], model: dict[str, Any]) -> Any:
    panel = _summary_panel(qt)
    layout = qt["QVBoxLayout"](panel)
    layout.setContentsMargins(14, 12, 14, 12)
    title = qt["QLabel"]("SIGNALS")
    title.setFont(_summary_font(qt, 12, mono=True, bold=True))
    title.setStyleSheet("color: #8ce7b8; border: none;")
    layout.addWidget(title)
    for label, value, color in model["breakdown"]:
        row = qt["QHBoxLayout"]()
        name = qt["QLabel"](label)
        name.setFont(_summary_font(qt, 11, mono=True))
        name.setStyleSheet("color: #baffdc; border: none;")
        count = qt["QLabel"](str(value))
        count.setAlignment(qt["Qt"].AlignmentFlag.AlignRight)
        count.setFont(_summary_font(qt, 16, mono=True, bold=True))
        count.setStyleSheet(f"color: {color}; border: none;")
        row.addWidget(name, 1)
        row.addWidget(count, 0)
        layout.addLayout(row)
    layout.addStretch(1)
    return panel


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
    dialog.resize(1180, 760)
    dialog.setStyleSheet(
        """
        QDialog { background: #030504; }
        QLabel { color: #baffdc; }
        QPushButton { min-height: 26px; padding: 5px 12px; }
        QComboBox { min-height: 26px; }
        """
    )

    layout = qt["QVBoxLayout"](dialog)
    layout.setContentsMargins(28, 24, 28, 20)
    layout.setSpacing(16)

    header = qt["QHBoxLayout"]()
    title_block = qt["QVBoxLayout"]()
    kicker = qt["QLabel"]("SCHOLAR VAULT // FOLLOW-UP")
    kicker.setFont(_summary_font(qt, 13, mono=True, bold=True))
    kicker.setStyleSheet("color: #69ffad;")
    heading = qt["QLabel"]("ISSUES TO RESOLVE")
    heading.setFont(_summary_font(qt, 32, bold=True))
    heading.setStyleSheet("color: #f3fff7;")
    subheading = qt["QLabel"]("Click an issue action to open the paper context and resolve it.")
    subheading.setFont(_summary_font(qt, 12))
    subheading.setStyleSheet("color: #8ce7b8;")
    title_block.addWidget(kicker)
    title_block.addWidget(heading)
    title_block.addWidget(subheading)
    header.addLayout(title_block, 1)
    count_panel = _summary_panel(qt, "#ff3b4f" if details else "#45ffb0")
    count_panel.setFixedWidth(180)
    count_layout = qt["QVBoxLayout"](count_panel)
    count_label = qt["QLabel"]("ISSUES")
    count_label.setFont(_summary_font(qt, 11, mono=True, bold=True))
    count_label.setStyleSheet("color: #8ce7b8; border: none;")
    count_value = qt["QLabel"](str(len(details)))
    count_value.setFont(_summary_font(qt, 34, mono=True, bold=True))
    count_value.setStyleSheet("color: #ff3b4f; border: none;")
    count_layout.addWidget(count_label)
    count_layout.addWidget(count_value)
    header.addWidget(count_panel)
    layout.addLayout(header)

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
    status_label = qt["QLabel"]("FILTER")
    status_label.setFont(_summary_font(qt, 11, mono=True, bold=True))
    filter_row.addWidget(status_label)
    filter_row.addWidget(category_filter)
    filter_row.addStretch(1)
    layout.addLayout(filter_row)

    scroll = qt["QScrollArea"]()
    scroll.setWidgetResizable(True)
    scroll.setStyleSheet("QScrollArea { border: 1px solid #26553b; background: #030504; }")
    list_widget = qt["QWidget"]()
    list_layout = qt["QVBoxLayout"](list_widget)
    list_layout.setContentsMargins(12, 12, 12, 12)
    list_layout.setSpacing(12)
    scroll.setWidget(list_widget)
    layout.addWidget(scroll, 1)
    visible: list[dict[str, Any]] = []

    def clear_list() -> None:
        while list_layout.count():
            item = list_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def refresh_list() -> None:
        selected_category = categories[category_filter.currentIndex()]
        visible.clear()
        visible.extend(
            row
            for row in details
            if selected_category == "all" or row.get("category") == selected_category
        )
        clear_list()
        if not visible:
            empty = qt["QLabel"]("No issues in this filter.")
            empty.setFont(_summary_font(qt, 18, bold=True))
            empty.setStyleSheet("color: #45ffb0; padding: 20px;")
            list_layout.addWidget(empty)
        for row in visible:
            list_layout.addWidget(_issue_card(qt, row, refresh_list))
        list_layout.addStretch(1)

    buttons = qt["QHBoxLayout"]()
    close = qt["QPushButton"]("Close")
    buttons.addStretch(1)
    buttons.addWidget(close)
    layout.addLayout(buttons)

    close.clicked.connect(dialog.accept)
    category_filter.currentIndexChanged.connect(refresh_list)
    qt["QShortcut"](qt["QKeySequence"]("Escape"), dialog).activated.connect(dialog.accept)

    refresh_list()
    dialog.exec()
    app.processEvents()


def _issue_color(detail: dict[str, Any]) -> str:
    category = str(detail.get("category") or "")
    message = str(detail.get("message") or "")
    if category in {"unresolved", "ambiguous"} or "failed" in message:
        return "#ff3b4f"
    if category == "incomplete":
        return "#ffb000"
    return "#69ffad"


def _issue_card(qt: dict[str, Any], detail: dict[str, Any], refresh) -> Any:
    color = _issue_color(detail)
    panel = _summary_panel(qt, color)
    layout = qt["QVBoxLayout"](panel)
    layout.setContentsMargins(16, 14, 16, 14)
    layout.setSpacing(10)

    top = qt["QHBoxLayout"]()
    badge = qt["QLabel"](str(detail.get("category") or "issue").upper())
    badge.setFont(_summary_font(qt, 11, mono=True, bold=True))
    badge.setStyleSheet(f"color: {color}; border: none;")
    top.addWidget(badge, 0)
    kind = qt["QLabel"](str(detail.get("kind") or "").upper())
    kind.setFont(_summary_font(qt, 11, mono=True, bold=True))
    kind.setStyleSheet("color: #8ce7b8; border: none;")
    top.addWidget(kind, 0)
    top.addStretch(1)
    citekey = qt["QLabel"](str(detail.get("citekey") or ""))
    citekey.setFont(_summary_font(qt, 11, mono=True))
    citekey.setStyleSheet("color: #8ce7b8; border: none;")
    top.addWidget(citekey, 0)
    layout.addLayout(top)

    message_text = str(detail.get("message") or detail.get("status") or "Follow-up needed")
    if _can_resolve_missing_abstract(detail):
        message = qt["QPushButton"](message_text)
        message.clicked.connect(lambda: _resolve_missing_abstract(qt, detail, refresh))
        message.setStyleSheet(
            f"QPushButton {{ color: {color}; background: #020403; "
            f"border: 1px solid {color}; text-align: left; padding: 10px; }}"
        )
    else:
        message = qt["QLabel"](message_text)
        message.setStyleSheet(f"color: {color}; border: none;")
    message.setFont(_summary_font(qt, 20, bold=True))
    layout.addWidget(message)

    title = qt["QLabel"](str(detail.get("title") or "Untitled paper"))
    title.setWordWrap(True)
    title.setFont(_summary_font(qt, 15, bold=True))
    title.setStyleSheet("color: #f3fff7; border: none;")
    layout.addWidget(title)

    meta_parts = [
        f"DOI {detail.get('doi')}" if detail.get("doi") else "",
        f"missing {', '.join(detail.get('missing_fields') or [])}"
        if detail.get("missing_fields")
        else "",
        f"source {detail.get('source')}" if detail.get("source") else "",
    ]
    meta = qt["QLabel"](" // ".join(part for part in meta_parts if part))
    meta.setWordWrap(True)
    meta.setFont(_summary_font(qt, 11))
    meta.setStyleSheet("color: #8ce7b8; border: none;")
    layout.addWidget(meta)

    actions = qt["QHBoxLayout"]()
    if _can_resolve_missing_abstract(detail):
        resolve = qt["QPushButton"]("Resolve Abstract")
        resolve.clicked.connect(lambda: _resolve_missing_abstract(qt, detail, refresh))
        actions.addWidget(resolve)
    open_card = qt["QPushButton"]("Open Card")
    open_pdf = qt["QPushButton"]("Open PDF")
    copy_citekey = qt["QPushButton"]("Copy Citekey")
    copy_doi = qt["QPushButton"]("Copy DOI")
    open_card.clicked.connect(lambda: _open_path(qt, str(detail.get("paper_file") or "")))
    open_pdf.clicked.connect(lambda: _open_path(qt, str(detail.get("pdf_file") or "")))
    copy_citekey.clicked.connect(lambda: _copy_detail(qt, detail, "citekey"))
    copy_doi.clicked.connect(lambda: _copy_detail(qt, detail, "doi"))
    actions.addWidget(open_card)
    actions.addWidget(open_pdf)
    actions.addWidget(copy_citekey)
    actions.addWidget(copy_doi)
    actions.addStretch(1)
    layout.addLayout(actions)
    return panel


def _can_resolve_missing_abstract(detail: dict[str, Any]) -> bool:
    message = str(detail.get("message") or "")
    return (
        detail.get("kind") == "abstract"
        and bool(detail.get("paper_file"))
        and bool(detail.get("citekey"))
        and (
            message in {"abstract previously failed", "no acceptable abstract found"}
            or detail.get("category") == "unresolved"
        )
    )


def _vault_from_detail(detail: dict[str, Any]) -> Path:
    paper_file = detail.get("paper_file")
    if not paper_file:
        raise ValueError("Issue does not include a paper file path.")
    return Path(str(paper_file)).expanduser().resolve().parent.parent


def _resolve_missing_abstract(qt: dict[str, Any], detail: dict[str, Any], refresh) -> None:
    pdf_file = str(detail.get("pdf_file") or "")
    if pdf_file:
        _open_path(qt, pdf_file)

    dialog = qt["QDialog"]()
    dialog.setWindowTitle("Resolve Missing Abstract")
    dialog.resize(880, 620)
    dialog.setStyleSheet(
        "QDialog { background: #030504; } QLabel { color: #baffdc; } "
        "QTextEdit { background: #f7f7f7; color: #111; }"
    )
    layout = qt["QVBoxLayout"](dialog)
    title = qt["QLabel"](str(detail.get("title") or "Untitled paper"))
    title.setWordWrap(True)
    title.setFont(_summary_font(qt, 20, bold=True))
    title.setStyleSheet("color: #f3fff7;")
    layout.addWidget(title)

    prompt = qt["QLabel"](
        "Paste the abstract copied from the PDF. Line breaks and word hyphenation from PDF "
        "copying will be cleaned before saving."
    )
    prompt.setWordWrap(True)
    prompt.setFont(_summary_font(qt, 12))
    layout.addWidget(prompt)

    editor = qt["QTextEdit"]()
    editor.setAcceptRichText(False)
    editor.setFont(_summary_font(qt, 13))
    layout.addWidget(editor, 1)

    buttons = qt["QDialogButtonBox"](
        qt["QDialogButtonBox"].StandardButton.Save
        | qt["QDialogButtonBox"].StandardButton.Cancel
    )
    layout.addWidget(buttons)

    def save() -> None:
        try:
            from .importer import set_manual_abstract

            result = set_manual_abstract(
                _vault_from_detail(detail),
                str(detail.get("citekey")),
                editor.toPlainText(),
                source_url=str(detail.get("pdf") or detail.get("pdf_file") or ""),
            )
        except Exception as exc:  # pragma: no cover - defensive UI error handling
            box = qt["QMessageBox"](dialog)
            box.setWindowTitle("Abstract Not Saved")
            box.setIcon(qt["QMessageBox"].Icon.Warning)
            box.setText(str(exc))
            box.exec()
            return
        detail["category"] = "resolved"
        detail["status"] = "manual_lock"
        detail["source"] = "manual"
        detail["message"] = "manual abstract saved"
        detail["paper_path"] = result.get("paper") or detail.get("paper_path")
        refresh()
        dialog.accept()

    buttons.accepted.connect(save)
    buttons.rejected.connect(dialog.reject)
    dialog.exec()


def _copy_detail(qt: dict[str, Any], detail: dict[str, Any] | None, key: str) -> None:
    if not detail:
        return
    value = detail.get(key)
    if value:
        qt["QApplication"].clipboard().setText(str(value))


def _has_category(details: list[dict[str, Any]], category: str) -> bool:
    return any(row.get("category") == category for row in details)
