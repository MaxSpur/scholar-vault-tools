from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any


class GuiUnavailable(RuntimeError):
    """Raised when desktop GUI dependencies are not installed or usable."""

def _load_qt_modules(*, require_fitz: bool) -> dict[str, Any]:
    try:
        from PySide6.QtCore import QEventLoop, QSize, Qt, QTimer, QUrl
        from PySide6.QtGui import (
            QBrush,
            QColor,
            QDesktopServices,
            QFont,
            QFontDatabase,
            QImage,
            QKeySequence,
            QPixmap,
            QShortcut,
        )
        from PySide6.QtWidgets import (
            QApplication,
            QCheckBox,
            QComboBox,
            QDialog,
            QDialogButtonBox,
            QFileDialog,
            QFrame,
            QGridLayout,
            QHBoxLayout,
            QLabel,
            QLineEdit,
            QListWidget,
            QListWidgetItem,
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
        "QBrush": QBrush,
        "QCheckBox": QCheckBox,
        "QColor": QColor,
        "QComboBox": QComboBox,
        "QDesktopServices": QDesktopServices,
        "QDialog": QDialog,
        "QDialogButtonBox": QDialogButtonBox,
        "QEventLoop": QEventLoop,
        "QFileDialog": QFileDialog,
        "QFrame": QFrame,
        "QFont": QFont,
        "QFontDatabase": QFontDatabase,
        "QGridLayout": QGridLayout,
        "QHBoxLayout": QHBoxLayout,
        "QImage": QImage,
        "QKeySequence": QKeySequence,
        "QLabel": QLabel,
        "QLineEdit": QLineEdit,
        "QListWidget": QListWidget,
        "QListWidgetItem": QListWidgetItem,
        "QMessageBox": QMessageBox,
        "QPixmap": QPixmap,
        "QProgressBar": QProgressBar,
        "QPushButton": QPushButton,
        "QRadioButton": QRadioButton,
        "QScrollArea": QScrollArea,
        "QSize": QSize,
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

def _unique_staging_trash_path(staging: str, source: str) -> Path:
    staging_root = Path(staging).expanduser().resolve()
    source_path = Path(source).expanduser().resolve()
    if not source_path.exists():
        raise FileNotFoundError(f"Staged PDF no longer exists: {source_path}")
    if staging_root != source_path.parent and staging_root not in source_path.parents:
        raise ValueError(f"PDF is not inside the staging folder: {source_path}")
    trash_dir = staging_root / "trash"
    trash_dir.mkdir(parents=True, exist_ok=True)
    destination = trash_dir / source_path.name
    counter = 2
    while destination.exists():
        destination = trash_dir / f"{source_path.stem}-{counter}{source_path.suffix}"
        counter += 1
    return destination

def _move_staged_pdf_to_trash(staging: str, source: str) -> Path:
    destination = _unique_staging_trash_path(staging, source)
    shutil.move(str(Path(source).expanduser()), str(destination))
    return destination

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
        QLabel, QRadioButton, QCheckBox { color: #baffdc; }
        QLineEdit, QTextEdit, QComboBox, QListWidget {
            background: #07100b;
            color: #f3fff7;
            border: 1px solid #26553b;
            padding: 6px;
            selection-background-color: #1d6f4b;
        }
        QListWidget::item {
            padding: 8px;
            border-bottom: 1px solid #123824;
        }
        QListWidget::item:selected {
            background: #123824;
            border-left: 3px solid #ffb000;
        }
        QCheckBox { spacing: 8px; }
        QCheckBox::indicator {
            width: 14px;
            height: 14px;
            border: 1px solid #45ffb0;
            background: #030504;
        }
        QCheckBox::indicator:checked { background: #45ffb0; }
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

def _button_stylesheet(tone: str = "neutral") -> str:
    tones = {
        "primary": ("#69ffad", "#f3fff7", "#0b2417"),
        "danger": ("#ff3b4f", "#ffd4d9", "#22050a"),
        "warning": ("#ffb000", "#fff4cf", "#221700"),
        "info": ("#9ecbff", "#eaf4ff", "#071322"),
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

def _summary_font(qt: dict[str, Any], size: int, *, mono: bool = False, bold: bool = False):
    database = qt.get("QFontDatabase")
    if database is not None:
        system_font = (
            database.SystemFont.FixedFont if mono else database.SystemFont.GeneralFont
        )
        font = database.systemFont(system_font)
    else:  # pragma: no cover - compatibility fallback for unusual Qt builds
        font = qt["QFont"]()
        if mono:
            font.setStyleHint(qt["QFont"].StyleHint.Monospace)
    font.setPointSize(size)
    font.setBold(bold)
    return font

def _summary_panel(qt: dict[str, Any], border: str = "#2b6748") -> Any:
    frame = qt["QFrame"]()
    frame.setFrameShape(qt["QFrame"].Shape.StyledPanel)
    frame.setStyleSheet(
        f"QFrame {{ background: #07100b; border: 1px solid {border}; }}"
    )
    return frame
