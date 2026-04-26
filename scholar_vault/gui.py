from __future__ import annotations

import html
import re
from pathlib import Path
from typing import Any

from .models import MatchReviewAbort, MatchReviewRequest

_ABORT_DIALOG_CODE = 2


class GuiUnavailable(RuntimeError):
    """Raised when desktop GUI dependencies are not installed or usable."""


def _load_qt_modules(*, require_fitz: bool) -> dict[str, Any]:
    try:
        from PySide6.QtCore import QEventLoop, Qt, QTimer, QUrl
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
        "QEventLoop": QEventLoop,
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
        "QTextEdit": QTextEdit,
        "QTimer": QTimer,
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


def _exec_modeless_dialog(qt: dict[str, Any], app: Any, dialog: Any) -> None:
    dialog.setModal(False)
    dialog.setWindowModality(qt["Qt"].WindowModality.NonModal)
    loop = qt["QEventLoop"]()
    dialog.finished.connect(lambda _code: loop.quit())
    dialog.show()
    dialog.raise_()
    dialog.activateWindow()
    loop.exec()
    app.processEvents()


def _dark_dialog_stylesheet() -> str:
    return """
        QDialog, QMessageBox { background: #030504; }
        QLabel, QRadioButton { color: #baffdc; }
        QLineEdit, QTextEdit, QComboBox {
            background: #07100b;
            color: #f3fff7;
            border: 1px solid #26553b;
            padding: 6px;
            selection-background-color: #1d6f4b;
        }
        QScrollArea {
            background: #030504;
            border: 1px solid #26553b;
        }
        QScrollBar:vertical {
            background: #030504;
            width: 12px;
            margin: 0;
        }
        QScrollBar::handle:vertical {
            background: #2c7b55;
            min-height: 28px;
        }
        QProgressBar {
            background: #07100b;
            color: #baffdc;
            border: 1px solid #26553b;
            min-height: 14px;
            text-align: center;
        }
        QProgressBar::chunk { background: #45ffb0; }
    """


def _match_review_stylesheet() -> str:
    return """
        QDialog { background: #ffffff; }
        QLabel { color: #111111; }
        QScrollArea {
            background: #ffffff;
            border: 1px solid #bfc7c2;
        }
        QScrollArea > QWidget > QWidget { background: #ffffff; }
        QScrollBar:vertical {
            background: #f4f6f5;
            width: 10px;
            margin: 0;
        }
        QScrollBar::handle:vertical {
            background: #91a79b;
            min-height: 28px;
        }
        QScrollBar::add-line:vertical,
        QScrollBar::sub-line:vertical {
            height: 0;
            background: transparent;
        }
        QScrollBar::add-page:vertical,
        QScrollBar::sub-page:vertical {
            background: transparent;
        }
    """


def _button_stylesheet(tone: str = "neutral") -> str:
    tones = {
        "primary": ("#69ffad", "#f3fff7", "#0b2417"),
        "danger": ("#ff3b4f", "#ffd4d9", "#22050a"),
        "success": ("#45ffb0", "#f3fff7", "#082116"),
        "muted": ("#2b6748", "#baffdc", "#07100b"),
        "neutral": ("#8ce7b8", "#f3fff7", "#07100b"),
    }
    border, text, background = tones.get(tone, tones["neutral"])
    return f"""
        QPushButton {{
            background: {background};
            color: {text};
            border: 1px solid {border};
            padding: 7px 14px;
            min-height: 28px;
            font-family: "Helvetica Neue";
        }}
        QPushButton:hover {{ background: #102719; }}
        QPushButton:pressed {{ background: #17452f; }}
        QPushButton:disabled {{
            color: #426b58;
            border-color: #1d3328;
            background: #050805;
        }}
    """


def _light_button_stylesheet(tone: str = "neutral", *, large: bool = False) -> str:
    tones = {
        "success": ("#087a4b", "#f2fff8", "#087a4b", "#e6fff2"),
        "danger": ("#b00020", "#fff4f6", "#b00020", "#ffe9ee"),
        "neutral": ("#14563d", "#ffffff", "#14563d", "#eef8f2"),
        "muted": ("#5f6f68", "#ffffff", "#1f2a25", "#f2f4f3"),
    }
    border, background, text, hover = tones.get(tone, tones["neutral"])
    size = "font-size: 34px; font-weight: 800;" if large else "font-size: 15px;"
    return f"""
        QPushButton {{
            background: {background};
            color: {text};
            border: 2px solid {border};
            padding: 8px 16px;
            min-height: 34px;
            font-family: "Helvetica Neue";
            {size}
        }}
        QPushButton:hover {{ background: {hover}; }}
        QPushButton:pressed {{ background: #ddeee5; }}
        QPushButton:disabled {{
            color: #9aa8a1;
            border-color: #c7d4cd;
            background: #f4f6f5;
        }}
    """


def _style_button(button: Any, tone: str = "neutral") -> None:
    button.setStyleSheet(_button_stylesheet(tone))


def _style_light_button(button: Any, tone: str = "neutral", *, large: bool = False) -> None:
    button.setStyleSheet(_light_button_stylesheet(tone, large=large))


def _style_dialog_buttons(button_box: Any, tone: str = "neutral") -> None:
    for button in button_box.buttons():
        _style_button(button, tone)


def _style_standard_dialog_button(button_box: Any, standard_button: Any, tone: str) -> None:
    button = button_box.button(standard_button)
    if button is not None:
        _style_button(button, tone)


def _style_message_box(qt: dict[str, Any], box: Any) -> None:
    box.setStyleSheet(_dark_dialog_stylesheet() + _button_stylesheet("neutral"))
    for button in box.buttons():
        _style_button(button, "primary")


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
        dialog = _build_confirmation_dialog(self._qt, self._title, prompt)
        result = dialog.exec()
        self._app.processEvents()
        return result == self._qt["QDialog"].DialogCode.Accepted


def make_confirmer(title: str = "Scholar Vault") -> _Confirmer:
    return _Confirmer(_load_qt_modules(require_fitz=False), title)


def _confirmation_model(prompt: str) -> dict[str, str]:
    normalized = " ".join(prompt.strip().split())
    run_match = re.fullmatch(r"Run (.+) already exists\. Resume and update it\?", normalized)
    if run_match:
        return {
            "kicker": "SCHOLAR VAULT // CONFIRM",
            "heading": "Resume Existing Run?",
            "body": (
                "This Scholar Labs run already exists. Resume it to reuse recorded decisions "
                "and update the manifest, cards, indexes, and follow-up report."
            ),
            "detail_label": "RUN",
            "detail": run_match.group(1),
            "accept": "Resume",
            "reject": "Cancel",
        }

    pdf_match = re.fullmatch(r"Use existing attached PDF for (.+)\?", normalized)
    if pdf_match:
        return {
            "kicker": "SCHOLAR VAULT // CONFIRM",
            "heading": "Use Existing PDF?",
            "body": "A vault card already has an attached PDF for this Scholar Labs result.",
            "detail_label": "RESULT",
            "detail": pdf_match.group(1),
            "accept": "Use PDF",
            "reject": "Skip",
        }

    return {
        "kicker": "SCHOLAR VAULT // CONFIRM",
        "heading": "Confirm Action",
        "body": normalized,
        "detail_label": "",
        "detail": "",
        "accept": "Yes",
        "reject": "No",
    }


def _build_confirmation_dialog(qt: dict[str, Any], title: str, prompt: str) -> Any:
    model = _confirmation_model(prompt)
    dialog = qt["QDialog"]()
    dialog.setWindowTitle(title)
    dialog.resize(720, 320)
    dialog.setMinimumWidth(640)
    dialog.setStyleSheet(_dark_dialog_stylesheet())

    layout = qt["QVBoxLayout"](dialog)
    layout.setContentsMargins(30, 26, 30, 24)
    layout.setSpacing(14)

    kicker = qt["QLabel"](model["kicker"])
    kicker.setFont(_summary_font(qt, 11, mono=True, bold=True))
    kicker.setStyleSheet("color: #69ffad;")
    layout.addWidget(kicker)

    heading = qt["QLabel"](model["heading"])
    heading.setFont(_summary_font(qt, 25, bold=True))
    heading.setStyleSheet("color: #f3fff7;")
    heading.setWordWrap(True)
    layout.addWidget(heading)

    body = qt["QLabel"](model["body"])
    body.setFont(_summary_font(qt, 13))
    body.setStyleSheet("color: #baffdc;")
    body.setWordWrap(True)
    layout.addWidget(body)

    if model["detail"]:
        detail_label = qt["QLabel"](model["detail_label"])
        detail_label.setFont(_summary_font(qt, 10, mono=True, bold=True))
        detail_label.setStyleSheet("color: #8ce7b8;")
        layout.addWidget(detail_label)

        detail = qt["QLabel"](model["detail"])
        detail.setFont(_summary_font(qt, 13, mono=True))
        detail.setStyleSheet(
            "color: #f3fff7; background: #07100b; border-left: 3px solid #69ffad; "
            "padding: 9px 11px;"
        )
        detail.setWordWrap(True)
        detail.setTextInteractionFlags(qt["Qt"].TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(detail)

    layout.addStretch(1)

    hint = qt["QLabel"]("Y accepts. N or Esc cancels.")
    hint.setFont(_summary_font(qt, 10))
    hint.setStyleSheet("color: #68c792;")

    buttons = qt["QHBoxLayout"]()
    buttons.addWidget(hint, 1)
    reject = qt["QPushButton"](model["reject"])
    reject.setMinimumWidth(112)
    reject.setMinimumHeight(38)
    _style_button(reject, "muted")
    accept = qt["QPushButton"](model["accept"])
    accept.setMinimumWidth(132)
    accept.setMinimumHeight(38)
    _style_button(accept, "primary")
    reject.clicked.connect(dialog.reject)
    accept.clicked.connect(dialog.accept)
    buttons.addWidget(reject)
    buttons.addWidget(accept)
    layout.addLayout(buttons)

    qt["QShortcut"](qt["QKeySequence"]("Y"), dialog).activated.connect(dialog.accept)
    qt["QShortcut"](qt["QKeySequence"]("N"), dialog).activated.connect(dialog.reject)
    qt["QShortcut"](qt["QKeySequence"]("Escape"), dialog).activated.connect(dialog.reject)
    return dialog


def _run_picker_counts(run: Any) -> tuple[int, int, int]:
    selected = sum(1 for result in run.results if result.status == "selected")
    total = run.result_count or len(run.results)
    attached = sum(
        1
        for result in run.results
        if result.status == "selected" and result.pdf_status == "attached"
    )
    return total, selected, attached


def _run_picker_title(run: Any) -> str:
    title = (run.title or "").strip()
    if title:
        return title
    return run.slug


def _run_picker_date(run: Any) -> str:
    value = run.exported_at or run.date
    return value[:16].replace("T", " ") if "T" in value else value


def _run_picker_model(
    runs: list[Any],
    vault: str,
    *,
    issue_counts: dict[str, int] | None = None,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    issue_counts = issue_counts or {}
    sorted_runs = sorted(
        runs,
        key=lambda run: (run.exported_at or run.date, run.slug),
        reverse=True,
    )
    for index, run in enumerate(sorted_runs):
        total, selected, attached = _run_picker_counts(run)
        prompt = " ".join((run.prompt or "").split())
        rows.append(
            {
                "run_id": run.slug,
                "title": _run_picker_title(run),
                "exported": _run_picker_date(run),
                "total": total,
                "selected": selected,
                "attached": attached,
                "issues": issue_counts.get(run.slug, 0),
                "accepted_now": len(run.matched_files),
                "unmatched_files": len(run.unmatched_files),
                "export_file": Path(run.export_file).name,
                "staging_folder": run.staging_folder,
                "note_file": run.note_file or "",
                "prompt": prompt,
                "is_latest": index == 0,
            }
        )
    return {"vault": vault, "rows": rows}


def _run_picker_metric(
    qt: dict[str, Any],
    label: str,
    value: object,
    *,
    color: str = "#f3fff7",
) -> Any:
    box = qt["QVBoxLayout"]()
    label_widget = qt["QLabel"](label)
    label_widget.setFont(_summary_font(qt, 9, mono=True, bold=True))
    label_widget.setStyleSheet("color: #8ce7b8; border: none;")
    value_widget = qt["QLabel"](str(value))
    value_widget.setFont(_summary_font(qt, 15, mono=True, bold=True))
    value_widget.setStyleSheet(f"color: {color}; border: none;")
    box.addWidget(label_widget)
    box.addWidget(value_widget)
    return box


def _build_run_picker_row(
    qt: dict[str, Any],
    row: dict[str, Any],
    choose: Any,
) -> Any:
    panel = qt["QFrame"]()
    panel.setStyleSheet(
        "QFrame { background: #030504; border: none; "
        f"border-left: {'3px solid #69ffad' if row['is_latest'] else '0px solid #030504'}; "
        "border-bottom: 1px solid #26553b; }"
    )
    layout = qt["QVBoxLayout"](panel)
    layout.setContentsMargins(14, 13, 14, 13)
    layout.setSpacing(8)

    title_row = qt["QHBoxLayout"]()
    title_row.setSpacing(10)
    title = qt["QLabel"](row["title"] or row["run_id"])
    title.setFont(_summary_font(qt, 15, bold=True))
    title.setStyleSheet("color: #f3fff7; border: none;")
    title.setWordWrap(True)
    title_row.addWidget(title, 1)
    if row["is_latest"]:
        latest = qt["QLabel"]("LATEST")
        latest.setFont(_summary_font(qt, 9, mono=True, bold=True))
        latest.setStyleSheet(
            "color: #030504; background: #69ffad; border: none; padding: 3px 7px;"
        )
        title_row.addWidget(latest, 0)
    button = qt["QPushButton"]("Rerun")
    button.setMinimumWidth(96)
    button.setMinimumHeight(38)
    _style_button(button, "primary" if row["is_latest"] else "neutral")
    button.clicked.connect(lambda _checked=False, run_id=row["run_id"]: choose(run_id))
    title_row.addWidget(button, 0)
    layout.addLayout(title_row)

    run_id = qt["QLabel"](row["run_id"])
    run_id.setFont(_summary_font(qt, 10, mono=True))
    run_id.setStyleSheet("color: #68c792; border: none;")
    run_id.setTextInteractionFlags(qt["Qt"].TextInteractionFlag.TextSelectableByMouse)
    layout.addWidget(run_id)

    prompt = qt["QLabel"](row["prompt"])
    prompt.setFont(_summary_font(qt, 10))
    prompt.setStyleSheet("color: #baffdc; border: none;")
    prompt.setWordWrap(True)
    prompt.setTextInteractionFlags(qt["Qt"].TextInteractionFlag.TextSelectableByMouse)
    layout.addWidget(prompt)

    details = qt["QLabel"](
        f"export: {row['export_file'] or '-'}"
        + (f"  // note: {row['note_file']}" if row["note_file"] else "")
        + f"  // accepted as new PDFs in that import: {row['accepted_now']}"
        + f"  // unmatched staged files recorded: {row['unmatched_files']}"
    )
    details.setFont(_summary_font(qt, 9, mono=True))
    details.setStyleSheet("color: #8ce7b8; border: none;")
    details.setWordWrap(True)
    layout.addWidget(details)

    metrics = qt["QHBoxLayout"]()
    metrics.setSpacing(18)
    metrics.addLayout(_run_picker_metric(qt, "EXPORTED", row["exported"]))
    metrics.addLayout(_run_picker_metric(qt, "RESULTS", row["total"]))
    metrics.addLayout(_run_picker_metric(qt, "PAPER CARDS", row["selected"]))
    metrics.addLayout(_run_picker_metric(qt, "ATTACHED PDFS", row["attached"]))
    metrics.addLayout(
        _run_picker_metric(
            qt,
            "FOLLOW-UP",
            row["issues"],
            color="#ff3b4f" if row["issues"] else "#45ffb0",
        )
    )
    metrics.addStretch(1)
    layout.addLayout(metrics)
    return panel


def choose_rerun(
    runs: list[Any],
    vault: str,
    *,
    issue_counts: dict[str, int] | None = None,
) -> str | None:
    qt = _load_qt_modules(require_fitz=False)
    app = _application(qt)
    model = _run_picker_model(runs, vault, issue_counts=issue_counts)
    selected: dict[str, str | None] = {"run_id": None}

    dialog = qt["QDialog"]()
    dialog.setWindowTitle("Scholar Vault Rerun")
    dialog.resize(1080, 720)
    dialog.setStyleSheet(_dark_dialog_stylesheet())

    def choose(run_id: str) -> None:
        selected["run_id"] = run_id
        dialog.accept()

    layout = qt["QVBoxLayout"](dialog)
    layout.setContentsMargins(28, 24, 28, 20)
    layout.setSpacing(14)

    header = qt["QHBoxLayout"]()
    title_block = qt["QVBoxLayout"]()
    kicker = qt["QLabel"]("SCHOLAR VAULT // RERUN")
    kicker.setFont(_summary_font(qt, 12, mono=True, bold=True))
    kicker.setStyleSheet("color: #69ffad;")
    heading = qt["QLabel"]("CHOOSE PREVIOUS RUN")
    heading.setFont(_summary_font(qt, 30, bold=True))
    heading.setStyleSheet("color: #f3fff7;")
    subheading = qt["QLabel"](
        "Most recent runs appear first. Pick one to rescan staging PDFs, reuse "
        "prior decisions, and then continue into the normal import workflow."
    )
    subheading.setFont(_summary_font(qt, 12))
    subheading.setStyleSheet("color: #8ce7b8;")
    subheading.setWordWrap(True)
    vault_label = qt["QLabel"](str(model["vault"]))
    vault_label.setFont(_summary_font(qt, 10, mono=True))
    vault_label.setStyleSheet("color: #68c792;")
    vault_label.setWordWrap(True)
    title_block.addWidget(kicker)
    title_block.addWidget(heading)
    title_block.addWidget(subheading)
    title_block.addWidget(vault_label)
    header.addLayout(title_block, 1)
    count_panel = _summary_panel(qt, "#69ffad" if model["rows"] else "#ff3b4f")
    count_panel.setFixedWidth(170)
    count_layout = qt["QVBoxLayout"](count_panel)
    count_label = qt["QLabel"]("RUNS")
    count_label.setFont(_summary_font(qt, 11, mono=True, bold=True))
    count_label.setStyleSheet("color: #8ce7b8; border: none;")
    count_value = qt["QLabel"](str(len(model["rows"])))
    count_value.setFont(_summary_font(qt, 34, mono=True, bold=True))
    count_value.setStyleSheet("color: #69ffad; border: none;")
    count_layout.addWidget(count_label)
    count_layout.addWidget(count_value)
    header.addWidget(count_panel)
    layout.addLayout(header)

    scroll = qt["QScrollArea"]()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(qt["QFrame"].Shape.NoFrame)
    scroll.setStyleSheet(
        "QScrollArea { background: #030504; border: 1px solid #26553b; }"
        "QScrollArea > QWidget > QWidget { background: #030504; }"
    )
    container = qt["QWidget"]()
    container.setStyleSheet("background: #030504;")
    rows_layout = qt["QVBoxLayout"](container)
    rows_layout.setContentsMargins(0, 0, 0, 0)
    rows_layout.setSpacing(0)
    if model["rows"]:
        for row in model["rows"]:
            rows_layout.addWidget(_build_run_picker_row(qt, row, choose))
        rows_layout.addStretch(1)
    else:
        empty = qt["QLabel"]("No previous Scholar Labs runs were found in this vault.")
        empty.setFont(_summary_font(qt, 14, bold=True))
        empty.setStyleSheet("color: #ffccd4; border: none; padding: 20px;")
        rows_layout.addWidget(empty)
    scroll.setWidget(container)
    layout.addWidget(scroll, 1)

    buttons = qt["QHBoxLayout"]()
    hint = qt["QLabel"]("Esc cancels.")
    hint.setFont(_summary_font(qt, 10))
    hint.setStyleSheet("color: #68c792;")
    buttons.addWidget(hint, 1)
    cancel = qt["QPushButton"]("Cancel")
    cancel.setMinimumWidth(110)
    _style_button(cancel, "muted")
    cancel.clicked.connect(dialog.reject)
    buttons.addWidget(cancel)
    layout.addLayout(buttons)

    qt["QShortcut"](qt["QKeySequence"]("Escape"), dialog).activated.connect(dialog.reject)
    result = dialog.exec()
    app.processEvents()
    if result == qt["QDialog"].DialogCode.Accepted:
        return selected["run_id"]
    return None


def edit_configuration(config: dict[str, Any]) -> dict[str, Any] | None:
    qt = _load_qt_modules(require_fitz=False)
    app = _application(qt)
    dialog = qt["QDialog"]()
    dialog.setWindowTitle("Scholar Vault Configuration")
    dialog.resize(900, 470)
    dialog.setStyleSheet(_dark_dialog_stylesheet())

    layout = qt["QVBoxLayout"](dialog)
    layout.setContentsMargins(28, 24, 28, 20)
    layout.setSpacing(14)

    heading = qt["QLabel"]("CONFIGURATION")
    heading.setFont(_summary_font(qt, 26, bold=True))
    heading.setStyleSheet("color: #f3fff7;")
    layout.addWidget(heading)

    intro = qt["QLabel"](
        "Choose default folders for Scholar Vault. Commands still accept explicit paths "
        "that override these defaults."
    )
    intro.setWordWrap(True)
    intro.setFont(_summary_font(qt, 12))
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
        _style_button(browse, "neutral")

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
        box.setStandardButtons(qt["QMessageBox"].StandardButton.Ok)
        _style_message_box(qt, box)
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
    _style_dialog_buttons(buttons, "primary")
    _style_standard_dialog_button(
        buttons,
        qt["QDialogButtonBox"].StandardButton.Cancel,
        "muted",
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


def _score_source_label(reason: str | None) -> str:
    labels = {
        "doi": "DOI match",
        "title": "PDF title text",
        "filename": "PDF filename",
        "text": "first-page text",
    }
    return labels.get(str(reason or "").strip().lower(), str(reason or "unknown source"))


def _confidence_detail_text(request: MatchReviewRequest) -> str:
    details = _confidence_detail_model(request)
    if request.score >= 100:
        return f"source: {details['source']}\nexact match"
    return f"source: {details['source']}\n-{details['deficit']} from exact: {details['cause']}"


def _confidence_detail_model(request: MatchReviewRequest) -> dict[str, str]:
    if request.score >= 100:
        return {
            "source": _score_source_label(request.match_reason),
            "deficit": "0",
            "cause": "exact match",
            "verdict": "AUTO",
        }
    deficit = 100 - request.score
    if request.match_reason == "filename":
        cause = "filename similarity, not confirmed by extracted title"
    elif request.match_reason == "text":
        cause = "first-page text similarity, not an exact title match"
    elif request.match_reason == "title":
        cause = "fuzzy PDF-title similarity"
    elif request.match_reason == "doi":
        cause = "DOI matched but score was reduced upstream"
    else:
        cause = "non-exact match evidence"
    verdict = "REVIEW" if request.score >= 70 else "LOW"
    return {
        "source": _score_source_label(request.match_reason),
        "deficit": str(deficit),
        "cause": cause,
        "verdict": verdict,
    }


def _confidence_info_row(qt: dict[str, Any], label: str, value: str, color: str = "#27352e") -> Any:
    row = qt["QWidget"]()
    layout = qt["QHBoxLayout"](row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(10)
    label_widget = qt["QLabel"](label)
    label_widget.setFixedWidth(58)
    label_widget.setFont(_summary_font(qt, 10, mono=True, bold=True))
    label_widget.setStyleSheet("border: none; color: #50645a;")
    value_widget = qt["QLabel"](value)
    value_widget.setWordWrap(True)
    value_widget.setFont(_summary_font(qt, 13))
    value_widget.setStyleSheet(f"border: none; color: {color};")
    layout.addWidget(label_widget)
    layout.addWidget(value_widget, 1)
    return row


def _build_match_dialog(qt: dict[str, Any], request: MatchReviewRequest):
    class MatchDialog(qt["QDialog"]):
        def keyPressEvent(self, event):  # noqa: N802 - Qt override name
            if event.key() == qt["Qt"].Key.Key_Escape:
                self.done(_ABORT_DIALOG_CODE)
                return
            super().keyPressEvent(event)

        def resizeEvent(self, event):  # noqa: N802 - Qt override name
            super().resizeEvent(event)
            refresh = getattr(self, "_refresh_preview", None)
            if callable(refresh):
                refresh(reset_scroll=False)

        def showEvent(self, event):  # noqa: N802 - Qt override name
            super().showEvent(event)
            refresh = getattr(self, "_refresh_preview", None)
            if callable(refresh):
                qt["QTimer"].singleShot(0, lambda: refresh(reset_scroll=True))
                qt["QTimer"].singleShot(80, lambda: refresh(reset_scroll=True))

        def closeEvent(self, event):  # noqa: N802 - Qt override name
            event.ignore()
            self.done(_ABORT_DIALOG_CODE)

    dialog = MatchDialog()
    dialog.setWindowTitle("Scholar Vault Match Review")
    dialog.resize(1560, 960)
    dialog.setStyleSheet(_match_review_stylesheet())

    layout = qt["QVBoxLayout"](dialog)
    layout.setContentsMargins(36, 26, 36, 24)
    layout.setSpacing(14)

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
    title_font.setPointSize(31)
    title_font.setBold(True)
    title.setFont(title_font)
    title.setStyleSheet("color: #050505;")
    document_layout.addWidget(title)

    metadata = qt["QLabel"](_metadata_line(request))
    metadata.setWordWrap(True)
    metadata.setAlignment(qt["Qt"].AlignmentFlag.AlignCenter)
    metadata_font = qt["QFont"]()
    metadata_font.setPointSize(15)
    metadata.setFont(metadata_font)
    metadata.setStyleSheet("color: #2d3430;")
    document_layout.addWidget(metadata)

    preview = qt["QLabel"]()
    preview.setAlignment(qt["Qt"].AlignmentFlag.AlignTop | qt["Qt"].AlignmentFlag.AlignHCenter)
    preview.setWordWrap(True)

    scroll = qt["QScrollArea"]()
    scroll.setWidgetResizable(False)
    scroll.setWidget(preview)
    scroll.viewport().setStyleSheet("background: #ffffff;")
    scroll.setHorizontalScrollBarPolicy(qt["Qt"].ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.setVerticalScrollBarPolicy(qt["Qt"].ScrollBarPolicy.ScrollBarAlwaysOn)
    document_layout.addWidget(scroll)
    document_layout.addStretch(1)
    body.addWidget(document_column, 1, qt["Qt"].AlignmentFlag.AlignTop)

    side = _build_match_side_panel(qt, request, dialog, scroll)
    body.addWidget(side, 0, qt["Qt"].AlignmentFlag.AlignTop)

    preview_source: dict[str, Any] = {"pixmap": None}

    def refresh_preview(*, reset_scroll: bool = True) -> None:
        try:
            if preview_source["pixmap"] is None:
                image = _render_pdf_image(qt, request.pdf_path, full_page=True)
                preview_source["pixmap"] = qt["QPixmap"].fromImage(image)
            pixmap = preview_source["pixmap"]
            viewport_width = scroll.viewport().width()
            if viewport_width <= 24:
                viewport_width = scroll.width() - scroll.verticalScrollBar().sizeHint().width() - 4
            available_width = max(1, viewport_width - 2)
            scaled = pixmap.scaled(
                available_width,
                max(1, int(pixmap.height() * (available_width / max(1, pixmap.width())))),
                qt["Qt"].AspectRatioMode.KeepAspectRatio,
                qt["Qt"].TransformationMode.SmoothTransformation,
            )
            preview.setPixmap(scaled)
            preview.setFixedSize(scaled.size())
            scroll.setFixedHeight(_preview_viewport_height(scaled.height()))
            if reset_scroll:
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
    hint.setStyleSheet("color: #323a35;")
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
    dialog._refresh_preview = refresh_preview  # type: ignore[attr-defined]
    refresh_preview()
    return dialog


def _build_match_side_panel(
    qt: dict[str, Any],
    request: MatchReviewRequest,
    dialog: Any,
    scroll: Any,
) -> Any:
    side = qt["QWidget"]()
    rail_width = 340
    side.setFixedWidth(rail_width)
    side_layout = qt["QVBoxLayout"](side)
    side_layout.setContentsMargins(0, 0, 0, 0)
    side_layout.setSpacing(12)

    confidence = qt["QFrame"]()
    confidence.setFrameShape(qt["QFrame"].Shape.StyledPanel)
    confidence.setStyleSheet("QFrame { background: #ffffff; border: 1px solid #aab4af; }")
    confidence.setFixedSize(rail_width, 190)
    confidence_layout = qt["QVBoxLayout"](confidence)
    confidence_layout.setContentsMargins(16, 12, 16, 12)
    confidence_layout.setSpacing(5)

    confidence_model = _confidence_detail_model(request)
    confidence_header = qt["QHBoxLayout"]()
    confidence_label = qt["QLabel"]("CONFIDENCE")
    confidence_label_font = qt["QFont"]()
    confidence_label_font.setPointSize(13)
    confidence_label_font.setBold(True)
    confidence_label.setFont(confidence_label_font)
    confidence_label.setStyleSheet("border: none; color: #111111;")
    confidence_header.addWidget(confidence_label)
    confidence_layout.addLayout(confidence_header)

    confidence_value = qt["QLabel"](f"{request.score}%")
    confidence_value.setAlignment(qt["Qt"].AlignmentFlag.AlignLeft)
    confidence_value_font = qt["QFont"]("Menlo")
    confidence_value_font.setStyleHint(qt["QFont"].StyleHint.Monospace)
    confidence_value_font.setPointSize(52)
    confidence_value_font.setBold(True)
    confidence_value.setFont(confidence_value_font)
    confidence_value.setStyleSheet(f"border: none; color: {_confidence_color(request.score)};")
    confidence_body = qt["QHBoxLayout"]()
    confidence_body.setContentsMargins(0, 0, 0, 0)
    confidence_body.setSpacing(14)
    confidence_body.addWidget(confidence_value, 0, qt["Qt"].AlignmentFlag.AlignTop)
    confidence_details = qt["QVBoxLayout"]()
    confidence_details.setContentsMargins(0, 4, 0, 0)
    confidence_details.setSpacing(6)
    confidence_details.addWidget(
        _confidence_info_row(qt, "SOURCE", confidence_model["source"])
    )
    confidence_details.addWidget(
        _confidence_info_row(
            qt,
            "GAP",
            f"{confidence_model['deficit']} below exact",
            _confidence_color(request.score),
        )
    )
    confidence_details.addWidget(
        _confidence_info_row(
            qt,
            "WHY",
            confidence_model["cause"],
            _confidence_color(request.score),
        )
    )
    confidence_body.addLayout(confidence_details, 1)
    confidence_layout.addLayout(confidence_body)
    side_layout.addWidget(confidence)

    accept = qt["QPushButton"]("YES")
    accept.setFixedSize(rail_width, 185)
    accept.setFocusPolicy(qt["Qt"].FocusPolicy.NoFocus)
    accept_font = qt["QFont"]()
    accept_font.setPointSize(40)
    accept_font.setBold(True)
    accept.setFont(accept_font)
    _style_light_button(accept, "success", large=True)
    accept.clicked.connect(dialog.accept)
    side_layout.addWidget(accept)

    reject = qt["QPushButton"]("NO")
    reject.setFixedSize(rail_width, 185)
    reject.setFocusPolicy(qt["Qt"].FocusPolicy.NoFocus)
    reject.setFont(accept_font)
    _style_light_button(reject, "danger", large=True)
    reject.clicked.connect(dialog.reject)
    side_layout.addWidget(reject)

    abort = qt["QPushButton"]("Abort Import")
    abort.setFixedSize(rail_width, 54)
    abort.setFocusPolicy(qt["Qt"].FocusPolicy.NoFocus)
    _style_light_button(abort, "danger")
    abort.clicked.connect(lambda: dialog.done(_ABORT_DIALOG_CODE))
    side_layout.addWidget(abort)

    open_pdf = qt["QPushButton"]("Open PDF")
    open_pdf.setFixedSize(rail_width, 54)
    open_pdf.setFocusPolicy(qt["Qt"].FocusPolicy.NoFocus)
    _style_light_button(open_pdf, "neutral")
    open_pdf.clicked.connect(lambda: _open_path(qt, request.pdf_path))
    side_layout.addWidget(open_pdf)

    side_layout.addStretch(1)
    return side


def _progress_parts(message: str) -> tuple[str, str, str]:
    text = message.strip()
    if not text:
        return "PROCESSING", "Waiting for the next update", ""
    if text == "Complete":
        return "COMPLETE", "Workflow finished", ""
    if text.startswith("Reading Scholar Labs export "):
        return (
            "READING EXPORT",
            "Validating Scholar Labs JSON and loading prior run state",
            text.removeprefix("Reading Scholar Labs export "),
        )
    match = re.fullmatch(r"Scanning (\d+) staged PDFs?", text)
    if match:
        count = match.group(1)
        return "PDF SCAN", "Building the staged PDF candidate list", f"{count} PDFs found"
    if text.startswith("Scanning staged PDF "):
        return (
            "PDF SCAN",
            "Extracting PDF title, DOI, year, and first-page text",
            text.removeprefix("Scanning staged PDF "),
        )
    match = re.fullmatch(r"Matching Scholar Labs result (\d+) \[([^\]]+)\]: (.+)", text)
    if match:
        rank, status, rest = match.groups()
        detail, _, identifier = rest.partition(" // ")
        return (
            "MATCHING",
            f"{status.upper()} // {detail}",
            f"rank {rank} // {identifier or f'r{int(rank):02d}'}",
        )
    match = re.fullmatch(r"Checking Scholar Labs result (\d+): (.+)", text)
    if match:
        rank, title = match.groups()
        return (
            "MATCHING",
            "Comparing this result with prior decisions, vault cards, and staged PDFs",
            f"rank {rank} // {_progress_rank_identifier(rank, title)}",
        )
    if text == "Writing run manifest":
        return "WRITING", "Saving run manifest, card links, and match decisions", ""
    match = re.fullmatch(r"Enriching citations \[([^\]]+)\]: (.+)", text)
    if match:
        status = match.group(1)
        return (
            "CITATION ENRICHMENT",
            f"{status.upper()} // {_enrichment_status_detail(status, abstracts=False)}",
            match.group(2),
        )
    match = re.fullmatch(r"Enriching abstracts \[([^\]]+)\]: (.+)", text)
    if match:
        status = match.group(1)
        return (
            "ABSTRACT ENRICHMENT",
            f"{status.upper()} // {_enrichment_status_detail(status, abstracts=True)}",
            match.group(2),
        )
    match = re.fullmatch(r"([^:]+): ([A-Za-z_-]+)", text)
    if match:
        return (
            "ENRICHMENT",
            f"{match.group(2).upper()} // processing canonical paper card",
            match.group(1),
        )
    if text == "Rebuilding indexes and exports":
        return "REBUILD", "Regenerating paper cards, indexes, and export files", ""
    return "PROCESSING", "Running current workflow step", text


def _enrichment_status_detail(status: str, *, abstracts: bool) -> str:
    normalized = status.lower().replace("-", "_")
    if normalized == "checking":
        return (
            "checking providers, cache, DOI, and PDF text"
            if abstracts
            else "checking DOI providers, cache, BibTeX, and missing fields"
        )
    if normalized == "skipped":
        return "no change; existing state, lock, cache, or retry rule"
    if normalized in {"verified", "resolved"}:
        return "ok; trusted metadata present"
    if normalized == "generated":
        return "generated metadata; review if needed"
    if normalized == "ambiguous":
        return "issue; multiple plausible candidates"
    if normalized == "unresolved":
        return "issue; no acceptable provider or PDF result"
    if normalized == "incomplete":
        return "issue; important fields still missing"
    return "processing canonical paper card"


def _progress_step_text(
    message: str,
    current: int | None = None,
    total: int | None = None,
) -> str:
    stage, substage, item = _progress_parts(message)
    prefix = f"[{current}/{total}] " if current is not None and total else ""
    suffix = f" // {item}" if item else ""
    return f"{prefix}{stage}: {substage}{suffix}"


def _progress_log_color(message: str) -> str:
    lowered = message.lower()
    if (
        "complete" in lowered
        or "[verified]" in lowered
        or "[resolved]" in lowered
        or "[accepted]" in lowered
        or "[linked]" in lowered
        or "[reused]" in lowered
    ):
        return "#69ffad"
    if "[generated]" in lowered or "[manual_lock]" in lowered:
        return "#8bffd0"
    if (
        "[checking]" in lowered
        or "[prior]" in lowered
        or "[card]" in lowered
        or "[pdf]" in lowered
        or "[review]" in lowered
        or "[proposed]" in lowered
        or "[card-found]" in lowered
    ):
        return "#ffb000"
    if (
        "[skipped]" in lowered
        or "[card-none]" in lowered
        or "[below-threshold]" in lowered
        or "[pdf-none]" in lowered
        or "[dry-run]" in lowered
    ):
        return "#a7b2aa"
    if "[ambiguous]" in lowered:
        return "#ffd34d"
    if (
        "[unresolved]" in lowered
        or "[rejected]" in lowered
        or "failed" in lowered
        or "canceled" in lowered
    ):
        return "#ff3b4f"
    if "matching" in lowered or "scanning" in lowered or "reading" in lowered:
        return "#8ce7b8"
    return "#baffdc"


def _progress_log_html(
    message: str,
    current: int | None = None,
    total: int | None = None,
    *,
    include_context: bool = True,
) -> str:
    color = _progress_log_color(message)
    stage, substage, item = _progress_parts(message)
    counter = f"{current}/{total}" if current is not None and total else "..."
    item_html = _progress_log_item_html(stage, item, include_context=include_context)
    return (
        f'<div style="margin-bottom:5px; white-space:nowrap; color:{color};">'
        f'<span style="background-color:{color}; color:#030504; font-weight:700;">'
        f"&nbsp;{html.escape(counter)}&nbsp;</span>"
        f' <span style="color:{color}; font-weight:700;">{html.escape(stage)}</span>'
        f" {_progress_substage_html(substage, color)}"
        f"{item_html}"
        "</div>"
    )


def _progress_substage_html(substage: str, color: str) -> str:
    if " // " not in substage:
        return f'<span style="color:#8ce7b8;">{html.escape(substage)}</span>'
    status, detail = substage.split(" // ", 1)
    return (
        f'<span style="color:{color}; font-weight:800;">{html.escape(status)}</span>'
        f' <span style="color:{color};">{html.escape(detail)}</span>'
    )


def _progress_log_item_html(stage: str, item: str, *, include_context: bool = True) -> str:
    if not item:
        return ""
    if stage in {"CITATION ENRICHMENT", "ABSTRACT ENRICHMENT"}:
        parts = [part.strip() for part in item.split(" // ")]
        identifier = parts[0]
        context = parts[2] if len(parts) >= 3 else ""
        if context and include_context:
            return (
                f' <span style="color:#f3fff7;">// {html.escape(identifier)} // </span>'
                f"{_progress_context_html(context)}"
            )
        return f' <span style="color:#f3fff7;">// {html.escape(identifier)}</span>'
    if stage == "MATCHING":
        parts = [part.strip() for part in item.split(" // ")]
        item = parts[1] if len(parts) >= 2 and parts[1] else parts[0]
    return f' <span style="color:#f3fff7;">// {html.escape(item)}</span>'


def _progress_context_html(context: str) -> str:
    parts: list[str] = []
    for raw_part in context.split(";"):
        part = raw_part.strip()
        if not part:
            continue
        if "=" in part:
            key, value = part.split("=", 1)
            key = key.strip()
            value = value.strip()
            value_color = _progress_context_value_color(key, value)
            parts.append(
                '<span style="color:#8ce7b8; font-weight:800;">'
                f"{html.escape(key)}"
                "</span>"
                f'<span style="color:{value_color}; font-weight:800;">'
                f"={html.escape(value)}</span>"
            )
        else:
            flag_color = _progress_context_value_color(part, "true")
            parts.append(
                f'<span style="color:{flag_color}; font-weight:800;">'
                f"{html.escape(part)}"
                "</span>"
            )
    return '<span style="color:#6f8f7d;">; </span>'.join(parts)


def _progress_context_value_color(key: str, value: str) -> str:
    normalized_key = key.strip().lower()
    normalized_value = value.strip().lower()
    if normalized_key == "state":
        if normalized_value in {"verified", "resolved", "manual_lock"}:
            return "#69ffad"
        if normalized_value in {"missing", "unresolved", "failed"}:
            return "#ff3b4f"
        if normalized_value in {"preview", "incomplete", "ambiguous"}:
            return "#ffb000"
        return "#f3fff7"
    if normalized_key == "source":
        if normalized_value in {"manual", "pdf_extracted"}:
            return "#8bffd0"
        if normalized_value in {"crossref", "openalex", "openalex_reconstructed"}:
            return "#69ffad"
        return "#baffdc"
    if normalized_key == "pdf":
        return "#69ffad" if normalized_value in {"yes", "true", "attached"} else "#ff3b4f"
    if normalized_key == "missing":
        return "#ffb000"
    if normalized_key in {"locked", "lock"} or normalized_value == "true":
        return "#8bffd0"
    if normalized_value in {"no", "false", "none"}:
        return "#ff3b4f"
    return "#f3fff7"


def _short_identifier(text: str, *, limit: int = 42) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    head = max(12, (limit - 3) // 2)
    tail = max(8, limit - head - 3)
    return f"{compact[:head]}...{compact[-tail:]}"


def _progress_rank_identifier(rank: str, title: str) -> str:
    words = re.findall(r"[a-z0-9]+", title.lower())
    filtered = [word for word in words if len(word) > 2][:5]
    compact = "".join(filtered)[:34]
    return f"r{int(rank):02d}-{compact or 'result'}"


def _progress_item_text(message: str) -> str:
    stage, _substage, item = _progress_parts(message)
    if not item:
        return ""
    if stage in {"CITATION ENRICHMENT", "ABSTRACT ENRICHMENT"}:
        parts = [part.strip() for part in item.split(" // ")]
        return parts[0]
    if stage == "MATCHING":
        parts = [part.strip() for part in item.split(" // ")]
        if len(parts) >= 2 and parts[1]:
            return parts[1]
        rank = re.search(r"\d+", parts[0] if parts else item)
        return f"r{int(rank.group(0)):02d}" if rank else "result"
    return _short_identifier(item)


def _progress_context_key(message: str) -> tuple[str, str] | None:
    stage, _substage, item = _progress_parts(message)
    if stage not in {"CITATION ENRICHMENT", "ABSTRACT ENRICHMENT"}:
        return None
    parts = [part.strip() for part in item.split(" // ")]
    if len(parts) < 3 or not parts[0] or not parts[2]:
        return None
    return parts[0], parts[2]


def _progress_item_html(
    message: str,
    current: int | None = None,
    total: int | None = None,
    *,
    active: bool = False,
) -> str:
    item = _progress_item_text(message)
    if not item:
        return ""
    color = _progress_log_color(message)
    counter = f"{current}/{total}" if current is not None and total else "..."
    background = "#123624" if active else "transparent"
    border = f"border-left: 3px solid {color};" if active else "border-left: 3px solid transparent;"
    return (
        f'<div style="margin-bottom:4px; white-space:nowrap; background:{background}; {border}">'
        f'<span style="background-color:{color}; color:#030504; font-weight:700;">'
        f"&nbsp;{html.escape(counter)}&nbsp;</span>"
        f' <span style="color:{color}; font-weight:700;">{html.escape(item)}</span>'
        "</div>"
    )


def _progress_stream_label(qt: dict[str, Any], text: str) -> Any:
    label = qt["QLabel"](text)
    label.setFont(_summary_font(qt, 10, mono=True, bold=True))
    label.setStyleSheet("color: #69ffad;")
    return label


def _progress_stream(
    qt: dict[str, Any],
    *,
    minimum_height: int = 150,
    compact: bool = False,
) -> Any:
    stream = qt["QTextEdit"]()
    stream.setReadOnly(True)
    stream.setFont(_summary_font(qt, 10 if compact else 11, mono=True))
    stream.setLineWrapMode(qt["QTextEdit"].LineWrapMode.NoWrap)
    stream.setHorizontalScrollBarPolicy(qt["Qt"].ScrollBarPolicy.ScrollBarAlwaysOff)
    stream.setStyleSheet(
        "QTextEdit { color: #baffdc; background: #07100b; "
        "border: 1px solid #26553b; padding: 8px; }"
    )
    stream.setMinimumHeight(minimum_height)
    return stream


def _progress_finished_state() -> dict[str, str]:
    return {
        "stage": "REPORT READY",
        "substage": (
            "Import, enrichment, and rebuild finished. Review the run report; "
            "this log stays scrollable until the final window closes."
        ),
        "counter": "DONE",
        "action": "Close Log",
    }


def _append_progress_stream(stream: Any, html_text: str) -> None:
    if not html_text:
        return
    stream.append(html_text)
    bar = stream.verticalScrollBar()
    bar.setValue(bar.maximum())


class _ProgressReporter:
    def __init__(self, qt: dict[str, Any], title: str) -> None:
        self._qt = qt
        self._app = _application(qt)
        self._cancelled = False
        self._finished = False
        self._last_step = ""
        self._active_item = ""
        self._item_order: list[str] = []
        self._item_events: dict[str, tuple[str, int | None, int | None]] = {}
        self._last_context_by_item: dict[str, str] = {}
        self._dialog = qt["QDialog"]()
        self._dialog.setWindowTitle(title)
        self._dialog.resize(1280, 720)
        self._dialog.setStyleSheet(_dark_dialog_stylesheet())

        layout = qt["QVBoxLayout"](self._dialog)
        layout.setContentsMargins(28, 24, 28, 20)
        layout.setSpacing(14)

        header = qt["QHBoxLayout"]()
        kicker = qt["QLabel"]("SCHOLAR VAULT // IMPORT")
        kicker.setFont(_summary_font(qt, 12, mono=True, bold=True))
        kicker.setStyleSheet("color: #69ffad;")
        header.addWidget(kicker)
        header.addStretch(1)
        self._counter = qt["QLabel"]("WAITING")
        self._counter.setFont(_summary_font(qt, 11, mono=True, bold=True))
        self._counter.setStyleSheet(
            "color: #030504; background: #69ffad; padding: 4px 8px;"
        )
        header.addWidget(self._counter)
        layout.addLayout(header)

        status_row = qt["QHBoxLayout"]()
        status_row.setSpacing(18)

        status_copy = qt["QVBoxLayout"]()
        status_copy.setSpacing(12)

        self._stage = qt["QLabel"]("STARTING")
        self._stage.setFont(_summary_font(qt, 30, bold=True))
        self._stage.setStyleSheet("color: #f3fff7;")
        status_copy.addWidget(self._stage)

        self._substage = qt["QLabel"]("Preparing workflow")
        self._substage.setFont(_summary_font(qt, 15, bold=True))
        self._substage.setStyleSheet("color: #baffdc;")
        self._substage.setWordWrap(True)
        status_copy.addWidget(self._substage)
        status_copy.addStretch(1)
        status_row.addLayout(status_copy, 1)

        item_column = qt["QVBoxLayout"]()
        item_column.setSpacing(6)
        item_column.addWidget(_progress_stream_label(qt, "CITEKEYS / ITEMS"))
        self._item_log = _progress_stream(qt, minimum_height=130, compact=True)
        self._item_log.setFixedWidth(430)
        self._item_log.setFixedHeight(150)
        item_column.addWidget(self._item_log)
        status_row.addLayout(item_column, 0)

        layout.addLayout(status_row)

        self._bar = qt["QProgressBar"]()
        self._bar.setRange(0, 0)
        self._bar.setTextVisible(False)
        layout.addWidget(self._bar)

        output_column = qt["QVBoxLayout"]()
        output_column.setSpacing(6)
        output_column.addWidget(_progress_stream_label(qt, "FULL OUTPUT"))
        self._log = _progress_stream(qt, minimum_height=270)
        output_column.addWidget(self._log, 1)
        layout.addLayout(output_column, 1)

        buttons = qt["QHBoxLayout"]()
        buttons.addStretch(1)
        self._cancel = qt["QPushButton"]("Cancel Import")
        _style_button(self._cancel, "danger")
        self._cancel.clicked.connect(self._handle_action_button)
        buttons.addWidget(self._cancel)
        layout.addLayout(buttons)

        self._dialog.show()
        self._app.processEvents()

    def _handle_action_button(self) -> None:
        if self._finished:
            self._dialog.accept()
            self._app.processEvents()
            return
        self._request_cancel()

    def _request_cancel(self) -> None:
        if self._finished:
            self._dialog.accept()
            self._app.processEvents()
            return
        self._cancelled = True
        self._stage.setText("CANCELING")
        self._substage.setText("Canceling after the current step...")
        self._counter.setText("STOP")
        self._app.processEvents()

    def _mark_finished(self) -> None:
        state = _progress_finished_state()
        self._finished = True
        self._stage.setText(state["stage"])
        self._substage.setText(state["substage"])
        self._bar.setRange(0, 1)
        self._bar.setValue(1)
        self._counter.setText(state["counter"])
        self._counter.setStyleSheet(
            "color: #030504; background: #45ffb0; padding: 4px 8px;"
        )
        self._cancel.setText(state["action"])
        _style_button(self._cancel, "neutral")
        self._app.processEvents()

    def __call__(
        self,
        message: str,
        current: int | None = None,
        total: int | None = None,
    ) -> None:
        complete = message.strip() == "Complete"
        if self._cancelled and not complete:
            raise MatchReviewAbort("Import canceled from progress window.")
        stage, substage, item = _progress_parts(message)
        self._stage.setText(stage)
        self._substage.setText(substage)
        if complete:
            self._bar.setRange(0, 1)
            self._bar.setValue(1)
            self._counter.setText("DONE")
        elif current is not None and total:
            self._bar.setRange(0, total)
            self._bar.setValue(current)
            self._counter.setText(f"{current}/{total}")
        else:
            self._bar.setRange(0, 0)
            self._counter.setText("BUSY")
        step = _progress_step_text(message, current, total)
        if self._last_step != step:
            self._last_step = step
            context = _progress_context_key(message)
            include_context = True
            if context is not None:
                context_item, context_value = context
                include_context = self._last_context_by_item.get(context_item) != context_value
                self._last_context_by_item[context_item] = context_value
            _append_progress_stream(
                self._log,
                _progress_log_html(
                    message,
                    current,
                    total,
                    include_context=include_context,
                ),
            )
        item_step = _progress_item_text(message)
        if item_step:
            self._active_item = item_step
            if item_step in self._item_order:
                self._item_order.remove(item_step)
            self._item_order.append(item_step)
            self._item_events[item_step] = (message, current, total)
            self._render_item_log()
        if complete:
            self._mark_finished()
        self._app.processEvents()
        if self._cancelled and not complete:
            raise MatchReviewAbort("Import canceled from progress window.")

    def _render_item_log(self) -> None:
        rows = [
            _progress_item_html(
                message,
                current,
                total,
                active=item == self._active_item,
            )
            for item in self._item_order
            for message, current, total in [self._item_events[item]]
        ]
        self._item_log.setHtml("".join(rows))
        bar = self._item_log.verticalScrollBar()
        bar.setValue(bar.maximum())

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
    followup_pending: bool = False,
) -> None:
    qt = _load_qt_modules(require_fitz=False)
    app = _application(qt)
    model = _import_summary_model(summary, lines)
    dialog = qt["QDialog"]()
    dialog.setWindowTitle(title)
    dialog.resize(1120, 760)
    dialog.setStyleSheet(_dark_dialog_stylesheet())

    shell = qt["QHBoxLayout"](dialog)
    shell.setContentsMargins(0, 0, 0, 0)
    shell.setSpacing(0)

    rail = qt["QFrame"]()
    rail.setFixedWidth(18)
    rail.setStyleSheet("background: #bd0027;")
    shell.addWidget(rail)

    layout = qt["QVBoxLayout"]()
    layout.setContentsMargins(24, 20, 24, 18)
    layout.setSpacing(12)
    shell.addLayout(layout, 1)

    header = qt["QHBoxLayout"]()
    title_block = qt["QVBoxLayout"]()
    kicker = qt["QLabel"]("SCHOLAR VAULT // IMPORT")
    kicker.setFont(_summary_font(qt, 12, mono=True, bold=True))
    kicker.setStyleSheet("color: #69ffad; letter-spacing: 0px;")
    heading = qt["QLabel"]("RUN REPORT")
    heading.setFont(_summary_font(qt, 30, bold=True))
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
    middle.setSpacing(12)
    middle.addWidget(_summary_flow_panel(qt, model), 2)
    middle.addWidget(_summary_enrichment_panel(qt, model), 1)
    layout.addLayout(middle, 1)

    layout.addWidget(_summary_breakdown_panel(qt, model), 0)
    layout.addWidget(_summary_next_step_panel(qt, model, followup_pending), 0)

    log = qt["QLabel"]("\n".join(model["lines"]))
    log.setWordWrap(True)
    log.setFont(_summary_font(qt, 10, mono=True))
    log.setTextInteractionFlags(qt["Qt"].TextInteractionFlag.TextSelectableByMouse)
    log.setStyleSheet(
        "QLabel { color: #8ce7b8; background: #07100b; "
        "border: 1px solid #26553b; padding: 10px; }"
    )
    layout.addWidget(log)

    buttons = qt["QDialogButtonBox"](qt["QDialogButtonBox"].StandardButton.Ok)
    ok_button = buttons.button(qt["QDialogButtonBox"].StandardButton.Ok)
    if ok_button is not None:
        ok_button.setText(
            "Open Follow-Up Issues" if followup_pending else "Close Report and Import Log"
        )
    _style_dialog_buttons(buttons, "primary")
    buttons.accepted.connect(dialog.accept)
    layout.addWidget(buttons)
    qt["QShortcut"](qt["QKeySequence"]("Escape"), dialog).activated.connect(dialog.accept)
    _exec_modeless_dialog(qt, app, dialog)


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


def _summary_enrichment_counts(
    label: str,
    summary_counts: dict[str, Any],
    details: list[dict[str, Any]],
) -> dict[str, Any]:
    problem_skip_messages = {
        "retry limit reached",
        "abstract previously failed",
        "metadata_lock",
    }
    checked = _summary_int(summary_counts.get("processed")) or len(details)
    updated = _summary_int(summary_counts.get("changed"))
    skipped_rows = {
        index
        for index, row in enumerate(details)
        if row.get("skipped") or row.get("category") == "skipped"
    }
    issue_rows = {
        index
        for index, row in enumerate(details)
        if row.get("category") in {"ambiguous", "unresolved", "incomplete"}
        or (
            row.get("category") == "skipped"
            and str(row.get("message") or "") in problem_skip_messages
        )
    }
    skipped = len(skipped_rows)
    issues = len(issue_rows)
    ok = max(checked - len(skipped_rows | issue_rows), 0)
    unchanged = max(checked - updated, 0)
    if issues:
        color = "#ff3b4f"
    elif updated:
        color = "#45ffb0"
    elif checked:
        color = "#8bffd0"
    else:
        color = "#426b58"
    return {
        "label": label,
        "checked": checked,
        "updated": updated,
        "unchanged": unchanged,
        "ok": ok,
        "issues": issues,
        "skipped": skipped,
        "color": color,
    }


def _summary_followup_issue_count(*detail_lists: list[dict[str, Any]]) -> int:
    problem_categories = {"incomplete", "ambiguous", "unresolved"}
    problem_skip_messages = {
        "retry limit reached",
        "abstract previously failed",
        "metadata_lock",
    }
    count = 0
    for details in detail_lists:
        for row in details:
            if row.get("category") in problem_categories:
                count += 1
            elif (
                row.get("category") == "skipped"
                and str(row.get("message") or "") in problem_skip_messages
            ):
                count += 1
    return count


def _import_summary_model(summary: dict[str, Any], lines: list[str]) -> dict[str, Any]:
    decisions = summary.get("decision_summary") or {}
    citations = summary.get("citation_enrichment") or {}
    abstracts = summary.get("abstract_enrichment") or {}
    citation_details = summary.get("enrichment_details") or []
    abstract_details = summary.get("abstract_details") or []
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
    pdf_upgrades = _summary_int(decisions.get("pdf_upgrades"))
    followup_issues = _summary_followup_issue_count(citation_details, abstract_details)

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
        "followup_issues": followup_issues,
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
            ("PDF upgrades", pdf_upgrades, "#45ffb0" if pdf_upgrades else "#426b58"),
            ("Citation updates", citation_changed, "#45ffb0" if citation_changed else "#426b58"),
            ("Abstract updates", abstract_changed, "#45ffb0" if abstract_changed else "#426b58"),
        ],
        "enrichment": [
            _summary_enrichment_counts("CITATIONS", citations, citation_details),
            _summary_enrichment_counts("ABSTRACTS", abstracts, abstract_details),
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


def _summary_enrichment_panel(qt: dict[str, Any], model: dict[str, Any]) -> Any:
    panel = _summary_panel(qt)
    layout = qt["QVBoxLayout"](panel)
    layout.setContentsMargins(14, 12, 14, 12)
    layout.setSpacing(10)
    title = qt["QLabel"]("ENRICHMENT")
    title.setFont(_summary_font(qt, 12, mono=True, bold=True))
    title.setStyleSheet("color: #8ce7b8; border: none;")
    layout.addWidget(title)
    for item in model["enrichment"]:
        layout.addWidget(_summary_enrichment_block(qt, item))
    layout.addStretch(1)
    return panel


def _summary_enrichment_block(qt: dict[str, Any], item: dict[str, Any]) -> Any:
    color = str(item["color"])
    block = qt["QFrame"]()
    block.setStyleSheet(f"QFrame {{ background: #020403; border: 1px solid {color}; }}")
    layout = qt["QVBoxLayout"](block)
    layout.setContentsMargins(10, 8, 10, 8)
    layout.setSpacing(4)

    top = qt["QHBoxLayout"]()
    label = qt["QLabel"](str(item["label"]))
    label.setFont(_summary_font(qt, 10, mono=True, bold=True))
    label.setStyleSheet("color: #8ce7b8; border: none;")
    checked = qt["QLabel"](f"{item['checked']} checked")
    checked.setAlignment(qt["Qt"].AlignmentFlag.AlignRight)
    checked.setFont(_summary_font(qt, 12, mono=True, bold=True))
    checked.setStyleSheet(f"color: {color}; border: none;")
    top.addWidget(label, 1)
    top.addWidget(checked, 0)
    layout.addLayout(top)

    updates = qt["QLabel"](
        f"{item['updated']} updated / {item['unchanged']} unchanged"
        if item["checked"]
        else "not run"
    )
    updates.setFont(_summary_font(qt, 10, mono=True))
    updates.setStyleSheet("color: #baffdc; border: none;")
    layout.addWidget(updates)

    footer = qt["QLabel"](
        f"{item['ok']} ok / {item['issues']} issues / {item['skipped']} skipped"
        if item["checked"]
        else "no enrichment events"
    )
    footer.setFont(_summary_font(qt, 10, mono=True))
    footer.setStyleSheet("color: #8ce7b8; border: none;")
    layout.addWidget(footer)
    return block


def _summary_next_step_panel(
    qt: dict[str, Any],
    model: dict[str, Any],
    followup_pending: bool,
) -> Any:
    issues = _summary_int(model.get("followup_issues"))
    pending = followup_pending or bool(issues)
    border = "#ff3b4f" if pending else "#45ffb0"
    panel = _summary_panel(qt, border)
    layout = qt["QHBoxLayout"](panel)
    layout.setContentsMargins(14, 10, 14, 10)
    label = qt["QLabel"]("NEXT")
    label.setFont(_summary_font(qt, 11, mono=True, bold=True))
    label.setStyleSheet(f"color: {border}; border: none;")
    if pending:
        if issues:
            issue_text = (
                f"{issues} enrichment issue" if issues == 1 else f"{issues} enrichment issues"
            )
        else:
            issue_text = "Enrichment follow-up issues"
        message = (
            f"{issue_text} will open in a follow-up window after this report. "
            "The import log stays available for review until the final window closes."
        )
    else:
        message = (
            "No enrichment follow-up issues are queued. Closing this report also closes "
            "the import log."
        )
    text = qt["QLabel"](message)
    text.setWordWrap(True)
    text.setFont(_summary_font(qt, 11, mono=True))
    text.setStyleSheet("color: #baffdc; border: none;")
    layout.addWidget(label, 0)
    layout.addWidget(text, 1)
    return panel


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
    close_label: str | None = None,
) -> None:
    qt = _load_qt_modules(require_fitz=False)
    app = _application(qt)
    dialog = qt["QDialog"]()
    window_title = title or (
        "Scholar Vault Abstract Results" if abstracts else "Scholar Vault Citation Results"
    )
    dialog.setWindowTitle(window_title)
    dialog.resize(1180, 760)
    dialog.setStyleSheet(_dark_dialog_stylesheet())

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
    count_value.setStyleSheet(
        f"color: {'#ff3b4f' if details else '#45ffb0'}; border: none;"
    )
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
    category_filter.setMinimumWidth(140)
    status_label = qt["QLabel"]("FILTER")
    status_label.setFont(_summary_font(qt, 11, mono=True, bold=True))
    filter_row.addWidget(status_label)
    filter_row.addWidget(category_filter)
    filter_row.addStretch(1)
    layout.addLayout(filter_row)

    scroll = qt["QScrollArea"]()
    scroll.setWidgetResizable(True)
    scroll.setStyleSheet(
        "QScrollArea { border: 1px solid #26553b; background: #030504; } "
        "QScrollArea > QWidget > QWidget { background: #030504; }"
    )
    scroll.viewport().setStyleSheet("background: #030504;")
    list_widget = qt["QWidget"]()
    list_widget.setStyleSheet("background: #030504;")
    list_layout = qt["QVBoxLayout"](list_widget)
    list_layout.setContentsMargins(18, 10, 18, 10)
    list_layout.setSpacing(0)
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
        for index, row in enumerate(visible):
            list_layout.addWidget(_issue_row(qt, row, refresh_list, dialog))
            if index < len(visible) - 1:
                list_layout.addWidget(_issue_separator(qt))
        list_layout.addStretch(1)

    buttons = qt["QHBoxLayout"]()
    close = qt["QPushButton"](close_label or "Close")
    _style_button(close, "primary")
    buttons.addStretch(1)
    buttons.addWidget(close)
    layout.addLayout(buttons)

    close.clicked.connect(dialog.accept)
    category_filter.currentIndexChanged.connect(refresh_list)
    qt["QShortcut"](qt["QKeySequence"]("Escape"), dialog).activated.connect(dialog.accept)

    refresh_list()
    _exec_modeless_dialog(qt, app, dialog)


def _issue_color(detail: dict[str, Any]) -> str:
    category = str(detail.get("category") or "")
    message = str(detail.get("message") or "")
    if category in {"unresolved", "ambiguous"} or "failed" in message:
        return "#ff3b4f"
    if category == "incomplete":
        return "#ffb000"
    return "#69ffad"


def _issue_separator(qt: dict[str, Any]) -> Any:
    separator = qt["QFrame"]()
    separator.setFrameShape(qt["QFrame"].Shape.HLine)
    separator.setStyleSheet("background: #26553b; border: none; max-height: 1px;")
    separator.setFixedHeight(1)
    return separator


def _issue_row(
    qt: dict[str, Any],
    detail: dict[str, Any],
    refresh,
    parent: Any | None = None,
) -> Any:
    color = _issue_color(detail)
    row = qt["QWidget"]()
    row.setObjectName("issueRow")
    row.setStyleSheet("#issueRow { background: #030504; }")
    layout = qt["QVBoxLayout"](row)
    layout.setContentsMargins(0, 18, 0, 18)
    layout.setSpacing(9)

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
        message.clicked.connect(lambda: _resolve_missing_abstract(qt, detail, refresh, parent))
        message.setStyleSheet(
            _button_stylesheet("danger")
            + "QPushButton { text-align: left; padding: 10px 12px; font-size: 20px; }"
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
        _style_button(resolve, "danger")
        resolve.clicked.connect(lambda: _resolve_missing_abstract(qt, detail, refresh, parent))
        actions.addWidget(resolve)
    open_card = qt["QPushButton"]("Open Card")
    open_pdf = qt["QPushButton"]("Open PDF")
    copy_citekey = qt["QPushButton"]("Copy Citekey")
    copy_doi = qt["QPushButton"]("Copy DOI")
    _style_button(open_card, "neutral")
    _style_button(open_pdf, "neutral")
    _style_button(copy_citekey, "muted")
    _style_button(copy_doi, "muted")
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
    return row


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


def _resolve_missing_abstract(
    qt: dict[str, Any],
    detail: dict[str, Any],
    refresh,
    parent: Any | None = None,
) -> None:
    pdf_file = str(detail.get("pdf_file") or "")
    if pdf_file:
        _open_path(qt, pdf_file)

    dialog = qt["QDialog"](parent)
    if parent is not None:
        dialog.setWindowModality(qt["Qt"].WindowModality.WindowModal)
    dialog.setWindowTitle("Resolve Missing Abstract")
    dialog.resize(880, 620)
    dialog.setStyleSheet(_dark_dialog_stylesheet())
    layout = qt["QVBoxLayout"](dialog)
    layout.setContentsMargins(24, 22, 24, 18)
    layout.setSpacing(12)
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
    editor_font = qt["QFont"]("Georgia")
    editor_font.setPointSize(18)
    editor.setFont(editor_font)
    editor.setStyleSheet(
        "QTextEdit { background: #07100b; color: #f3fff7; border: 1px solid #078a5d; "
        "padding: 14px; selection-background-color: #1d6f4b; }"
    )
    layout.addWidget(editor, 1)

    buttons = qt["QDialogButtonBox"](
        qt["QDialogButtonBox"].StandardButton.Save
        | qt["QDialogButtonBox"].StandardButton.Cancel
    )
    _style_dialog_buttons(buttons, "primary")
    _style_standard_dialog_button(
        buttons,
        qt["QDialogButtonBox"].StandardButton.Cancel,
        "muted",
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
            box.setStandardButtons(qt["QMessageBox"].StandardButton.Ok)
            _style_message_box(qt, box)
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
    dialog.show()
    dialog.raise_()
    dialog.activateWindow()
    dialog.exec()


def _copy_detail(qt: dict[str, Any], detail: dict[str, Any] | None, key: str) -> None:
    if not detail:
        return
    value = detail.get(key)
    if value:
        qt["QApplication"].clipboard().setText(str(value))


def _has_category(details: list[dict[str, Any]], category: str) -> bool:
    return any(row.get("category") == category for row in details)
