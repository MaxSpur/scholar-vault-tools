from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any


class GuiUnavailable(RuntimeError):
    """Raised when desktop GUI dependencies are not installed or usable."""


_TONE_COLORS = {
    "green": "#69ffad",
    "soft": "#8ce7b8",
    "body": "#baffdc",
    "white": "#f3fff7",
    "blue": "#9ecbff",
    "warning": "#fff4cf",
    "danger": "#ff6b7a",
    "dim-blue": "#d7eaff",
    "muted": "#426b58",
}


def _tone_color(tone: str) -> str:
    if tone.startswith("#"):
        return tone
    return _TONE_COLORS.get(tone, tone)


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


def make_kicker_label(qt: dict[str, Any], text: str, *, size: int = 10) -> Any:
    label = qt["QLabel"](text)
    label.setFont(_summary_font(qt, size, mono=True, bold=True))
    label.setStyleSheet(f"color: {_tone_color('green')};")
    return label


def make_title_label(qt: dict[str, Any], text: str, *, size: int = 24) -> Any:
    label = qt["QLabel"](text)
    label.setFont(_summary_font(qt, size, bold=True))
    label.setStyleSheet(f"color: {_tone_color('white')};")
    return label


def make_section_label(
    qt: dict[str, Any],
    text: str,
    *,
    tone: str = "soft",
    size: int = 10,
    mono: bool = True,
    bold: bool = True,
    borderless: bool = False,
) -> Any:
    label = qt["QLabel"](text)
    label.setFont(_summary_font(qt, size, mono=mono, bold=bold))
    border = " border: none;" if borderless else ""
    label.setStyleSheet(f"color: {_tone_color(tone)};{border}")
    return label


def make_body_label(
    qt: dict[str, Any],
    text: str,
    *,
    tone: str = "body",
    size: int = 10,
    word_wrap: bool = True,
    borderless: bool = False,
) -> Any:
    label = qt["QLabel"](text)
    label.setWordWrap(word_wrap)
    label.setFont(_summary_font(qt, size))
    border = " border: none;" if borderless else ""
    label.setStyleSheet(f"color: {_tone_color(tone)};{border}")
    return label


def style_compact_field(
    qt: dict[str, Any],
    field: Any,
    *,
    min_height: int = 30,
    size: int = 10,
    mono: bool = False,
) -> Any:
    field.setMinimumHeight(min_height)
    field.setFont(_summary_font(qt, size, mono=mono))
    return field


def make_labeled_field(
    qt: dict[str, Any],
    label_text: str,
    field: Any,
    *,
    label_tone: str = "soft",
    field_min_height: int = 30,
    field_size: int = 10,
    field_mono: bool = False,
) -> tuple[Any, Any]:
    layout = qt["QVBoxLayout"]()
    label = make_section_label(qt, label_text, tone=label_tone, size=9)
    style_compact_field(
        qt,
        field,
        min_height=field_min_height,
        size=field_size,
        mono=field_mono,
    )
    layout.addWidget(label)
    layout.addWidget(field)
    return layout, label


def make_action_button(
    qt: dict[str, Any],
    text: str,
    *,
    tone: str = "neutral",
    min_height: int = 34,
    stylesheet: Callable[[str], str] | None = None,
) -> Any:
    button = qt["QPushButton"](text)
    button.setMinimumHeight(min_height)
    button.setStyleSheet((stylesheet or _button_stylesheet)(tone))
    return button


def make_compact_counter(
    qt: dict[str, Any],
    label: str,
    value: int,
    color: str,
) -> tuple[Any, Any]:
    panel = _summary_panel(qt, color)
    panel.setMinimumHeight(34)
    panel.setMaximumHeight(38)
    layout = qt["QHBoxLayout"](panel)
    layout.setContentsMargins(10, 5, 10, 5)
    layout.setSpacing(7)
    number = qt["QLabel"](str(value))
    number.setMinimumWidth(18)
    number.setAlignment(
        qt["Qt"].AlignmentFlag.AlignRight | qt["Qt"].AlignmentFlag.AlignVCenter
    )
    number.setFont(_summary_font(qt, 14, mono=True, bold=True))
    number.setStyleSheet(f"color: {color}; border: none;")
    title = qt["QLabel"](label.lower())
    title.setFont(_summary_font(qt, 9, mono=True, bold=True))
    title.setStyleSheet(f"color: {_tone_color('body')}; border: none;")
    title.setAlignment(qt["Qt"].AlignmentFlag.AlignVCenter)
    layout.addWidget(number, 0)
    layout.addWidget(title, 1)
    return panel, number


def make_text_panel(
    qt: dict[str, Any],
    *,
    min_height: int = 120,
    border: str = "#006b45",
    color: str = "#d7ffe8",
    background: str = "#00120b",
    padding: int = 8,
    mono: bool = True,
    size: int = 10,
    read_only: bool = True,
) -> Any:
    panel = qt["QTextEdit"]()
    panel.setReadOnly(read_only)
    panel.setMinimumHeight(min_height)
    panel.setFont(_summary_font(qt, size, mono=mono))
    panel.setStyleSheet(
        f"QTextEdit {{ color: {color}; background: {background}; "
        f"border: 1px solid {border}; padding: {padding}px; }}"
    )
    return panel


def make_list_widget(
    qt: dict[str, Any],
    *,
    min_height: int = 120,
    border: str = "#1d6f4b",
    selected: str = "#0b3f2a",
    font_size: int = 10,
    selection_mode: str = "single",
    spacing: int = 2,
    item_padding: int = 0,
    item_border: str = "none",
) -> Any:
    widget = qt["QListWidget"]()
    widget.setMinimumHeight(min_height)
    widget.setFont(_summary_font(qt, font_size))
    widget.setSpacing(spacing)
    modes = qt["QListWidget"].SelectionMode
    if selection_mode == "none":
        widget.setSelectionMode(modes.NoSelection)
    elif selection_mode == "multi":
        widget.setSelectionMode(modes.MultiSelection)
    else:
        widget.setSelectionMode(modes.SingleSelection)
    widget.setStyleSheet(
        f"QListWidget {{ border: 1px solid {border}; background: #020806; color: #f3fff7; }}"
        f"QListWidget::item {{ padding: {item_padding}px; border: {item_border}; }}"
        f"QListWidget::item:selected {{ background: {selected}; }}"
    )
    return widget


def style_compact_combo_box(
    qt: dict[str, Any],
    combo: Any,
    *,
    border: str = "#9ecbff",
    dropdown_border: str = "#2f73a5",
    min_width: int = 150,
    min_height: int = 34,
    size: int = 11,
) -> Any:
    combo.setMinimumWidth(min_width)
    combo.setMinimumHeight(min_height)
    combo.setFont(_summary_font(qt, size))
    combo.setStyleSheet(
        f"""
        QComboBox {{
            background: #07100b;
            color: #f3fff7;
            border: 1px solid {border};
            padding: 6px 28px 6px 9px;
            selection-background-color: #1d6f4b;
        }}
        QComboBox:hover {{ border-color: #b8dcff; }}
        QComboBox::drop-down {{
            width: 24px;
            border-left: 1px solid {dropdown_border};
        }}
        QComboBox QAbstractItemView {{
            background: #07100b;
            color: #f3fff7;
            border: 1px solid {border};
            selection-background-color: #1d6f4b;
            selection-color: #ffffff;
            outline: 0;
        }}
        """
    )
    combo.view().setFont(_summary_font(qt, size))
    combo.view().setMinimumWidth(min_width)
    combo.view().setStyleSheet(
        f"""
        QListView {{
            background: #07100b;
            color: #f3fff7;
            border: 1px solid {border};
            outline: 0;
        }}
        QListView::item {{
            min-height: 28px;
            padding: 6px 10px;
        }}
        QListView::item:selected {{
            background: #1d6f4b;
            color: #ffffff;
        }}
        """
    )
    return combo
