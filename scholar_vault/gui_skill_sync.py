from __future__ import annotations

from pathlib import Path
from typing import Any

from .gui_common import (
    _application,
    _dark_dialog_stylesheet,
    _load_qt_modules,
    _style_button,
    _style_dialog_buttons,
    _style_message_box,
    _summary_font,
    _summary_panel,
)


def _skill_sync_color(row: dict[str, Any]) -> str:
    status = row.get("status")
    newer = row.get("newer")
    if status == "source-only":
        return "#45ffb0"
    if status == "target-only":
        return "#9ecbff"
    if status == "changed" and newer == "source":
        return "#45ffb0"
    if status == "changed" and newer == "target":
        return "#ffb000"
    if status == "changed":
        return "#ff6b7a"
    return "#8ce7b8"


def _skill_sync_row_text(row: dict[str, Any]) -> str:
    status = str(row.get("status") or "")
    newer = str(row.get("newer") or "unknown")
    if status == "changed" and newer == "source":
        hint = "repository newer"
    elif status == "changed" and newer == "target":
        hint = "vault newer"
    elif status == "changed":
        hint = "mtime unclear"
    elif status == "target-only":
        hint = "vault-only"
    elif status == "source-only":
        hint = "repository-only"
    else:
        hint = status
    changed_files = int(row.get("changed_files") or 0)
    changed_text = ""
    if changed_files:
        suffix = "" if changed_files == 1 else "s"
        changed_text = f"  -  {changed_files} file{suffix} differ"
    return f"{status}  -  {hint}{changed_text}"


def _skill_sync_badge_text(row: dict[str, Any]) -> str:
    status = str(row.get("status") or "")
    newer = str(row.get("newer") or "unknown")
    if status == "changed" and newer == "source":
        return "repo newer"
    if status == "changed" and newer == "target":
        return "vault newer"
    if status == "changed":
        return "unclear"
    if status == "source-only":
        return "repo only"
    if status == "target-only":
        return "vault only"
    return status or newer


def _skill_sync_default_selected(row: dict[str, Any]) -> bool:
    return row.get("status") in {"changed", "source-only", "target-only"}


def _skill_sync_can_update(row: dict[str, Any]) -> bool:
    return row.get("status") in {"changed", "source-only"}


def _skill_sync_can_pull(row: dict[str, Any]) -> bool:
    return row.get("status") in {"changed", "target-only"}


def _skill_sync_metric_panel(
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
    title.setStyleSheet("color: #baffdc; border: none;")
    title.setAlignment(qt["Qt"].AlignmentFlag.AlignVCenter)
    layout.addWidget(number, 0)
    layout.addWidget(title, 1)
    return panel, number


def show_skill_sync(
    source: Path | str,
    target: Path | str,
    *,
    source_agent_guide: Path | str | None = None,
    target_agent_guide: Path | str | None = None,
) -> None:
    from .skill_sync import (
        adopt_skill,
        compare_skillsets,
        format_skillset_summary,
        install_external_skill_source,
        known_external_skill_sources,
        publish_skillset,
        resolve_external_skill_source,
    )

    qt = _load_qt_modules(require_fitz=False)
    app = _application(qt)
    dialog = qt["QDialog"]()
    dialog.setWindowTitle("Scholar Vault Skill Sync")
    dialog.resize(1080, 720)
    dialog.setMinimumWidth(880)
    dialog.setStyleSheet(_dark_dialog_stylesheet())

    layout = qt["QVBoxLayout"](dialog)
    layout.setContentsMargins(22, 18, 22, 18)
    layout.setSpacing(8)

    kicker = qt["QLabel"]("SCHOLAR VAULT // SKILL + AGENTS SYNC")
    kicker.setFont(_summary_font(qt, 10, mono=True, bold=True))
    kicker.setStyleSheet("color: #69ffad;")
    layout.addWidget(kicker)

    heading = qt["QLabel"]("Repository -> Vault Sync")
    heading.setFont(_summary_font(qt, 24, bold=True))
    heading.setStyleSheet("color: #f3fff7;")
    layout.addWidget(heading)

    body = qt["QLabel"](
        "Repository source is the canonical vault-agent skill set and vault AGENTS "
        "template in this tools repo. Vault target is the installed skill set and "
        "AGENTS.md used by Codex inside the vault. Update publishes repository -> vault; "
        "pull only when vault-side edits should become canonical."
    )
    body.setWordWrap(True)
    body.setFont(_summary_font(qt, 11))
    body.setStyleSheet("color: #baffdc;")
    layout.addWidget(body)
    layout.addSpacing(6)

    source_field = qt["QLineEdit"]()
    source_field.setText(str(Path(source).expanduser().resolve()))
    target_field = qt["QLineEdit"]()
    target_field.setText(str(Path(target).expanduser().resolve()))
    path_grid = qt["QGridLayout"]()
    path_grid.setHorizontalSpacing(12)
    path_grid.setVerticalSpacing(4)
    for column, (label_text, field) in enumerate(
        [
            ("Repository vault-agent skills", source_field),
            ("Vault target skills", target_field),
        ]
    ):
        label = qt["QLabel"](label_text)
        label.setFont(_summary_font(qt, 9, mono=True, bold=True))
        label.setStyleSheet("color: #8ce7b8;")
        field.setMinimumHeight(30)
        field.setFont(_summary_font(qt, 10, mono=True))
        path_grid.addWidget(label, 0, column)
        path_grid.addWidget(field, 1, column)
        path_grid.setColumnStretch(column, 1)
    layout.addLayout(path_grid)

    metrics_row = qt["QHBoxLayout"]()
    metrics_row.setSpacing(6)
    metric_values: dict[str, Any] = {}
    for key, label, color in [
        ("source_newer", "REPO NEWER", "#45ffb0"),
        ("target_newer", "VAULT NEWER", "#ffb000"),
        ("unclear", "UNCLEAR", "#ff6b7a"),
        ("source_only", "REPO ONLY", "#69ffad"),
        ("target_only", "VAULT ONLY", "#9ecbff"),
    ]:
        panel, number = _skill_sync_metric_panel(qt, label, 0, color)
        metric_values[key] = number
        metrics_row.addWidget(panel, 1)
    layout.addLayout(metrics_row)

    comparison_row = qt["QHBoxLayout"]()
    comparison_row.setSpacing(10)

    summary_column = qt["QWidget"]()
    summary_layout = qt["QVBoxLayout"](summary_column)
    summary_layout.setContentsMargins(0, 0, 0, 0)
    summary_layout.setSpacing(6)
    summary_label = qt["QLabel"]("Roles and comparison details")
    summary_label.setFont(_summary_font(qt, 10, mono=True, bold=True))
    summary_label.setStyleSheet("color: #8ce7b8;")
    summary_text = qt["QTextEdit"]()
    summary_text.setReadOnly(True)
    summary_text.setMinimumHeight(120)
    summary_text.setFont(_summary_font(qt, 10, mono=True))
    summary_text.setStyleSheet(
        "QTextEdit { color: #d7ffe8; background: #00120b; border: 1px solid #006b45; "
        "padding: 8px; }"
    )
    summary_layout.addWidget(summary_label, 0)
    summary_layout.addWidget(summary_text, 1)
    comparison_row.addWidget(summary_column, 1)

    skill_column = qt["QWidget"]()
    skill_layout = qt["QVBoxLayout"](skill_column)
    skill_layout.setContentsMargins(0, 0, 0, 0)
    skill_layout.setSpacing(6)
    skill_label = qt["QLabel"]("Skill and AGENTS differences")
    skill_label.setFont(_summary_font(qt, 10, mono=True, bold=True))
    skill_label.setStyleSheet("color: #69ffad;")
    skill_list = qt["QListWidget"]()
    skill_list.setMinimumHeight(120)
    skill_list.setFont(_summary_font(qt, 10))
    skill_list.setSelectionMode(qt["QListWidget"].SelectionMode.NoSelection)
    skill_list.setSpacing(4)
    skill_layout.addWidget(skill_label, 0)
    skill_layout.addWidget(skill_list, 1)
    comparison_row.addWidget(skill_column, 1)
    layout.addLayout(comparison_row, 1)

    direction_hint = qt["QLabel"](
        "Select individual rows, then choose the direction. Modification times choose the "
        "initial selection only; inspect changed items before overwriting."
    )
    direction_hint.setWordWrap(True)
    direction_hint.setFont(_summary_font(qt, 9))
    direction_hint.setStyleSheet("color: #fff4cf;")
    layout.addWidget(direction_hint)

    external_panel = _summary_panel(qt, "#9ecbff")
    external_layout = qt["QVBoxLayout"](external_panel)
    external_layout.setContentsMargins(10, 8, 10, 10)
    external_layout.setSpacing(5)
    external_header = qt["QHBoxLayout"]()
    external_header.setSpacing(10)
    external_label = qt["QLabel"]("External skill sources")
    external_label.setFont(_summary_font(qt, 10, mono=True, bold=True))
    external_label.setStyleSheet("color: #9ecbff; border: none;")
    external_hint = qt["QLabel"](
        "Built-ins fill the fields; custom sources need a repository."
    )
    external_hint.setWordWrap(True)
    external_hint.setFont(_summary_font(qt, 9))
    external_hint.setStyleSheet("color: #d7eaff; border: none;")
    external_header.addWidget(external_label)
    external_header.addWidget(external_hint, 1)
    external_layout.addLayout(external_header)

    known_external_sources = known_external_skill_sources()
    external_source_select = qt["QComboBox"]()
    external_source_select.setMinimumHeight(30)
    external_source_select.setFont(_summary_font(qt, 10))
    external_source_select.addItem("Custom source", "")
    for source_name in sorted(known_external_sources):
        external_source_select.addItem(source_name, source_name)

    external_grid = qt["QGridLayout"]()
    external_grid.setHorizontalSpacing(10)
    external_grid.setVerticalSpacing(4)
    external_source_field = qt["QLineEdit"]()
    external_source_field.setText("obsidian-skills")
    external_repository_field = qt["QLineEdit"]()
    external_repository_field.setPlaceholderText("Optional for built-in sources")
    external_ref_field = qt["QLineEdit"]()
    external_ref_field.setPlaceholderText("Default ref")
    external_subdir_field = qt["QLineEdit"]()
    external_subdir_field.setPlaceholderText("skills")
    advanced_external_button = qt["QPushButton"]("Advanced...")
    preview_external_button = qt["QPushButton"]("Preview")
    install_external_button = qt["QPushButton"]("Install / Update")
    for button, tone in [
        (advanced_external_button, "muted"),
        (preview_external_button, "neutral"),
        (install_external_button, "primary"),
    ]:
        button.setMinimumHeight(30)
        _style_button(button, tone)

    for column, (label_text, widget) in enumerate(
        [
            ("Built-in", external_source_select),
            ("Source", external_source_field),
            ("Repository", external_repository_field),
            ("Ref/Subdir", advanced_external_button),
            ("Preview", preview_external_button),
            ("Install", install_external_button),
        ]
    ):
        label = qt["QLabel"](label_text)
        label.setFont(_summary_font(qt, 9, mono=True, bold=True))
        label.setStyleSheet("color: #9ecbff; border: none;")
        widget.setMinimumHeight(30)
        if hasattr(widget, "setFont"):
            widget.setFont(_summary_font(qt, 10))
        external_grid.addWidget(label, 0, column)
        external_grid.addWidget(widget, 1, column)
    external_grid.setColumnStretch(2, 3)
    external_layout.addLayout(external_grid)

    def fill_external_source_fields(source_name: str) -> None:
        source = known_external_sources.get(source_name)
        if source is None:
            return
        external_source_field.setText(source.name)
        external_repository_field.setText(source.repository)
        external_ref_field.setText(source.ref)
        external_subdir_field.setText(source.skills_subdir)
        update_external_advanced_button()

    def update_external_advanced_button() -> None:
        ref = external_ref_field.text().strip()
        subdir = external_subdir_field.text().strip()
        custom = bool(ref and ref != "main") or bool(subdir and subdir != "skills")
        advanced_external_button.setText("Advanced: custom" if custom else "Advanced...")
        advanced_external_button.setToolTip(
            f"Git ref: {ref or 'default main'}\n"
            f"Skills subdirectory: {subdir or 'default skills'}"
        )

    def edit_external_advanced() -> None:
        settings_dialog = qt["QDialog"](dialog)
        settings_dialog.setWindowTitle("External Source Advanced Settings")
        settings_dialog.setStyleSheet(_dark_dialog_stylesheet())
        settings_layout = qt["QVBoxLayout"](settings_dialog)
        settings_layout.setContentsMargins(18, 16, 18, 16)
        settings_layout.setSpacing(8)
        intro = qt["QLabel"](
            "Most sources use the default Git ref and a top-level skills directory."
        )
        intro.setWordWrap(True)
        intro.setFont(_summary_font(qt, 10))
        intro.setStyleSheet("color: #d7eaff;")
        settings_layout.addWidget(intro)
        fields = qt["QGridLayout"]()
        fields.setHorizontalSpacing(10)
        fields.setVerticalSpacing(5)
        ref_edit = qt["QLineEdit"]()
        ref_edit.setText(external_ref_field.text())
        ref_edit.setPlaceholderText("main")
        subdir_edit = qt["QLineEdit"]()
        subdir_edit.setText(external_subdir_field.text())
        subdir_edit.setPlaceholderText("skills")
        for row, (label_text, field) in enumerate(
            [("Git ref", ref_edit), ("Skills subdirectory", subdir_edit)]
        ):
            label = qt["QLabel"](label_text)
            label.setFont(_summary_font(qt, 9, mono=True, bold=True))
            label.setStyleSheet("color: #9ecbff;")
            field.setMinimumHeight(30)
            field.setFont(_summary_font(qt, 10))
            fields.addWidget(label, row, 0)
            fields.addWidget(field, row, 1)
        fields.setColumnStretch(1, 1)
        settings_layout.addLayout(fields)
        settings_buttons = qt["QDialogButtonBox"](
            qt["QDialogButtonBox"].StandardButton.Ok
            | qt["QDialogButtonBox"].StandardButton.Cancel
        )
        _style_dialog_buttons(settings_buttons, "neutral")
        settings_buttons.accepted.connect(settings_dialog.accept)
        settings_buttons.rejected.connect(settings_dialog.reject)
        settings_layout.addWidget(settings_buttons)
        if settings_dialog.exec():
            external_ref_field.setText(ref_edit.text().strip())
            external_subdir_field.setText(subdir_edit.text().strip())
            update_external_advanced_button()

    for index in range(external_source_select.count()):
        if external_source_select.itemData(index) == "obsidian-skills":
            external_source_select.setCurrentIndex(index)
            fill_external_source_fields("obsidian-skills")
            break

    def built_in_source_changed(_index: int) -> None:
        source_name = external_source_select.currentData()
        if source_name:
            fill_external_source_fields(str(source_name))
        else:
            external_source_field.clear()
            external_repository_field.clear()
            external_ref_field.clear()
            external_subdir_field.clear()
            update_external_advanced_button()

    external_source_select.currentIndexChanged.connect(built_in_source_changed)
    advanced_external_button.clicked.connect(edit_external_advanced)
    layout.addWidget(external_panel)

    option_row = qt["QHBoxLayout"]()
    option_row.setSpacing(18)
    force_box = qt["QCheckBox"]("Allow vault overwrite")
    force_box.setFont(_summary_font(qt, 9))
    force_box.setToolTip(
        "Allow Pull Selected Into Repository to overwrite an existing differing "
        "repository copy."
    )
    archive_box = qt["QCheckBox"]("Archive vault-only on update")
    archive_box.setFont(_summary_font(qt, 9))
    archive_box.setToolTip(
        "During Update Vault From Repository, move selected vault-only target skills "
        "into .sync-backups instead of leaving them installed."
    )
    archive_box.setStyleSheet("color: #baffdc;")
    option_row.addWidget(force_box)
    option_row.addWidget(archive_box)
    option_row.addStretch(1)
    layout.addLayout(option_row)

    buttons = qt["QHBoxLayout"]()
    refresh_button = qt["QPushButton"]("Refresh")
    adopt_button = qt["QPushButton"]("Pull Selected Into Repository")
    publish_button = qt["QPushButton"]("Update Vault From Repository")
    close_button = qt["QPushButton"]("Close")
    for button, tone in [
        (refresh_button, "neutral"),
        (adopt_button, "warning"),
        (publish_button, "success"),
        (close_button, "muted"),
    ]:
        button.setMinimumHeight(34)
        _style_button(button, tone)
    buttons.addWidget(refresh_button, 0)
    buttons.addStretch(1)
    buttons.addWidget(adopt_button)
    buttons.addWidget(publish_button)
    buttons.addStretch(1)
    buttons.addWidget(close_button, 0)
    layout.addLayout(buttons)

    def paths() -> tuple[Path, Path]:
        return (
            Path(source_field.text()).expanduser().resolve(),
            Path(target_field.text()).expanduser().resolve(),
        )

    current_summary: dict[str, Any] = {}
    current_rows: dict[str, dict[str, Any]] = {}
    selected_skills: set[str] = set()
    row_widgets: dict[str, dict[str, Any]] = {}

    def message(title: str, text: str) -> None:
        box = qt["QMessageBox"](dialog)
        box.setWindowTitle(title)
        box.setText(text)
        _style_message_box(qt, box)
        box.exec()

    def confirm(title: str, text: str) -> bool:
        box = qt["QMessageBox"](dialog)
        box.setWindowTitle(title)
        box.setText(text)
        box.setStandardButtons(
            qt["QMessageBox"].StandardButton.Cancel
            | qt["QMessageBox"].StandardButton.Ok
        )
        _style_message_box(qt, box)
        return box.exec() == qt["QMessageBox"].StandardButton.Ok

    def _optional_field_text(field: Any) -> str | None:
        text = field.text().strip()
        return text or None

    def external_source_from_fields() -> Any | None:
        source_name = external_source_field.text().strip()
        if not source_name:
            message("External Source Required", "Enter an external source name.")
            return None
        try:
            return resolve_external_skill_source(
                source_name,
                repository=_optional_field_text(external_repository_field),
                ref=_optional_field_text(external_ref_field),
                skills_subdir=_optional_field_text(external_subdir_field),
            )
        except ValueError as exc:
            message("External Source Error", str(exc))
            return None

    def external_result_text(result: dict[str, Any]) -> str:
        lines = [
            f"Source: {result.get('source')}",
            f"Repository: {result.get('repository')}",
            f"Ref: {result.get('ref')}",
            f"Target: {result.get('target')}",
            f"Skills: {', '.join(result.get('skills') or []) or 'none'}",
        ]
        if result.get("commit"):
            lines.append(f"Commit: {result['commit']}")
        if result.get("copied"):
            lines.append(f"Copied: {', '.join(result['copied'])}")
        if result.get("manifest"):
            lines.append(f"Manifest: {result['manifest']}")
        if result.get("backups"):
            lines.append(f"Backups: {', '.join(result['backups'])}")
        return "\n".join(lines)

    def install_external(*, apply: bool) -> None:
        source = external_source_from_fields()
        if source is None:
            return
        target_path = paths()[1]
        if apply and not confirm(
            "Install / Update External Source",
            (
                "Clone the external source and copy its skill folders into the vault "
                "target?\n\n"
                f"Source: {source.name}\n"
                f"Repository: {source.repository}\n"
                f"Target: {target_path}\n\n"
                "Existing skill folders with the same names are backed up before "
                "being replaced."
            ),
        ):
            return
        result: dict[str, Any] | None = None
        error: Exception | None = None
        cursor_set = False
        try:
            qt["QApplication"].setOverrideCursor(qt["Qt"].CursorShape.WaitCursor)
            cursor_set = True
            app.processEvents()
            result = install_external_skill_source(
                target_path,
                source,
                apply=apply,
                backup=True,
            )
        except Exception as exc:  # pragma: no cover - GUI error path
            error = exc
        finally:
            if cursor_set:
                qt["QApplication"].restoreOverrideCursor()
        if error is not None:
            message("External Install Failed", str(error))
            return
        if result is None:
            return
        title = "External Source Installed" if apply else "External Source Preview"
        message(title, external_result_text(result))
        if apply:
            refresh()

    def selected_rows() -> list[dict[str, Any]]:
        return [current_rows[skill] for skill in selected_skills if skill in current_rows]

    def selected_skill_names(*, pull: bool | None = None) -> list[str]:
        rows = selected_rows()
        if pull is True:
            rows = [row for row in rows if _skill_sync_can_pull(row)]
        elif pull is False:
            rows = [row for row in rows if _skill_sync_can_update(row)]
        return sorted(str(row["skill"]) for row in rows)

    def update_action_state() -> None:
        pull_count = len(selected_skill_names(pull=True))
        publish_count = len(selected_skill_names(pull=False))
        selected_count = len(selected_skills)
        skill_label.setText(
            f"Skill and AGENTS differences - {selected_count} selected"
            if selected_count
            else "Skill and AGENTS differences - none selected"
        )
        adopt_button.setEnabled(bool(pull_count))
        publish_button.setEnabled(bool(publish_count))
        adopt_button.setText(
            f"Pull Selected Into Repository ({pull_count})"
            if pull_count
            else "Pull Selected Into Repository"
        )
        publish_button.setText(
            f"Update Vault From Repository ({publish_count})"
            if publish_count
            else "Update Vault From Repository"
        )

    def paint_skill_row(skill: str) -> None:
        widgets = row_widgets.get(skill)
        row = current_rows.get(skill)
        if not widgets or not row:
            return
        selected = skill in selected_skills
        color = _skill_sync_color(row)
        background = "#083f2a" if selected else "#07100b"
        border = color if selected else "#26553b"
        widgets["frame"].setStyleSheet(
            f"QFrame {{ background: {background}; border: 1px solid {border}; }}"
        )
        widgets["rail"].setStyleSheet(f"QFrame {{ background: {color}; border: none; }}")
        widgets["checkbox"].blockSignals(True)
        widgets["checkbox"].setChecked(selected)
        widgets["checkbox"].blockSignals(False)
        widgets["status"].setStyleSheet(
            f"color: {color}; border: 1px solid {color}; padding: 2px 7px; "
            "background: #030504;"
        )

    def set_skill_selected(skill: str, selected: bool) -> None:
        if selected:
            selected_skills.add(skill)
        else:
            selected_skills.discard(skill)
        paint_skill_row(skill)
        update_action_state()

    def toggle_skill(skill: str) -> None:
        set_skill_selected(skill, skill not in selected_skills)

    def add_skill_row(row: dict[str, Any]) -> None:
        skill = str(row["skill"])
        item = qt["QListWidgetItem"]()
        item.setData(qt["Qt"].ItemDataRole.UserRole, skill)
        frame = qt["QFrame"]()
        frame.setMinimumHeight(42)
        frame.setToolTip(
            f"Status: {row.get('status')}; newer hint: {row.get('newer')}; "
            f"source modified: {row.get('source_modified') or '-'}; "
            f"vault modified: {row.get('target_modified') or '-'}"
        )
        item_layout = qt["QHBoxLayout"](frame)
        item_layout.setContentsMargins(0, 0, 8, 0)
        item_layout.setSpacing(8)

        rail = qt["QFrame"]()
        rail.setFixedWidth(4)
        rail.setAttribute(qt["Qt"].WidgetAttribute.WA_TransparentForMouseEvents, True)
        item_layout.addWidget(rail)

        checkbox = qt["QCheckBox"]()
        checkbox.setToolTip("Select this item for the next pull or update action.")
        item_layout.addWidget(checkbox, 0)

        text_block = qt["QVBoxLayout"]()
        text_block.setContentsMargins(0, 4, 0, 4)
        text_block.setSpacing(1)
        title = qt["QLabel"](skill)
        title.setFont(_summary_font(qt, 10, bold=True))
        title.setStyleSheet("color: #f3fff7; border: none;")
        title.setAttribute(qt["Qt"].WidgetAttribute.WA_TransparentForMouseEvents, True)
        meta = qt["QLabel"](_skill_sync_row_text(row))
        meta.setFont(_summary_font(qt, 9, mono=True))
        meta.setStyleSheet("color: #baffdc; border: none;")
        meta.setWordWrap(False)
        meta.setAttribute(qt["Qt"].WidgetAttribute.WA_TransparentForMouseEvents, True)
        text_block.addWidget(title)
        text_block.addWidget(meta)
        item_layout.addLayout(text_block, 1)

        status = qt["QLabel"]()
        status.setText(_skill_sync_badge_text(row))
        status.setFont(_summary_font(qt, 8, mono=True, bold=True))
        status.setAlignment(qt["Qt"].AlignmentFlag.AlignCenter)
        status.setAttribute(qt["Qt"].WidgetAttribute.WA_TransparentForMouseEvents, True)
        item_layout.addWidget(status, 0)

        checkbox.stateChanged.connect(
            lambda state, selected_skill=skill: set_skill_selected(
                selected_skill, bool(state)
            )
        )
        frame.mousePressEvent = lambda _event, selected_skill=skill: toggle_skill(
            selected_skill
        )
        skill_list.addItem(item)
        skill_list.setItemWidget(item, frame)
        item.setSizeHint(qt["QSize"](0, 42))
        row_widgets[skill] = {
            "frame": frame,
            "rail": rail,
            "checkbox": checkbox,
            "status": status,
        }
        paint_skill_row(skill)

    def refresh() -> None:
        source_path, target_path = paths()
        summary = compare_skillsets(
            source_path,
            target_path,
            source_agent_guide=source_agent_guide,
            target_agent_guide=target_agent_guide,
        )
        current_summary["value"] = summary
        summary_text.setPlainText(format_skillset_summary(summary))
        changed_rows = [row for row in summary["skills"] if row["status"] == "changed"]
        metric_values["source_newer"].setText(
            str(sum(1 for row in changed_rows if row.get("newer") == "source"))
        )
        metric_values["target_newer"].setText(
            str(sum(1 for row in changed_rows if row.get("newer") == "target"))
        )
        metric_values["unclear"].setText(
            str(
                sum(
                    1
                    for row in changed_rows
                    if row.get("newer") not in {"source", "target"}
                )
            )
        )
        metric_values["source_only"].setText(str(summary["counts"]["source_only"]))
        metric_values["target_only"].setText(str(summary["counts"]["target_only"]))
        rows = [row for row in summary["skills"] if row["status"] != "identical"]
        agent_guide = summary.get("agent_guide")
        if agent_guide and agent_guide["status"] != "identical":
            rows.append(agent_guide)
        current_rows.clear()
        current_rows.update({str(row["skill"]): row for row in rows})
        selected_skills.clear()
        selected_skills.update(
            str(row["skill"]) for row in rows if _skill_sync_default_selected(row)
        )
        row_widgets.clear()
        skill_list.clear()
        for row in rows:
            add_skill_row(row)
        update_action_state()
        if not rows:
            item = qt["QListWidgetItem"]("No skill or AGENTS differences found.")
            item.setForeground(qt["QBrush"](qt["QColor"]("#426b58")))
            skill_list.addItem(item)

    def adopt_selected() -> None:
        skills = selected_skill_names(pull=True)
        if not skills:
            return
        if not confirm(
            "Pull Vault Items Into Repository",
            (
                "Copy selected vault target items back into the repository source?\n\n"
                f"Items: {', '.join(skills)}\n\n"
                "Use this only for vault-side edits you want to keep in the repo."
            ),
        ):
            return
        source_path, target_path = paths()
        pulled: list[str] = []
        blocked: list[str] = []
        for skill in skills:
            result = adopt_skill(
                source_path,
                target_path,
                skill,
                apply=True,
                force=force_box.isChecked(),
                source_agent_guide=source_agent_guide,
                target_agent_guide=target_agent_guide,
            )
            if result.get("action") == "blocked":
                blocked.append(f"{skill}: {result.get('reason')}")
            else:
                pulled.append(skill)
        if blocked:
            message(
                "Pull Partially Blocked" if pulled else "Pull Blocked",
                f"Pulled: {', '.join(pulled) or 'none'}\nBlocked:\n" + "\n".join(blocked),
            )
        else:
            message("Pulled Into Repository", f"Pulled: {', '.join(pulled) or 'none'}")
        refresh()

    def publish() -> None:
        summary = current_summary.get("value") or {}
        skills = selected_skill_names(pull=False)
        if not skills:
            return
        comparison_rows = list(summary.get("skills", []))
        agent_guide = summary.get("agent_guide")
        if agent_guide:
            comparison_rows.append(agent_guide)
        vault_newer = [
            row["skill"]
            for row in comparison_rows
            if row.get("skill") in skills
            and row.get("status") == "changed"
            and row.get("newer") == "target"
        ]
        warning = ""
        if vault_newer:
            warning = (
                "\n\nMtime warning: these changed vault target items look newer than "
                f"the repository source: {', '.join(vault_newer)}. Pull them first if "
                "those vault-side edits should be preserved."
            )
        if not confirm(
            "Update Vault From Repository",
            (
                "Copy selected repository source items into the vault target?\n\n"
                f"Items: {', '.join(skills)}\n\n"
                "Changed vault copies are backed up before being overwritten. Vault-only "
                "skill extras are kept unless the archive checkbox is enabled."
                f"{warning}"
            ),
        ):
            return
        source_path, target_path = paths()
        result = publish_skillset(
            source_path,
            target_path,
            apply=True,
            archive_extra=archive_box.isChecked(),
            skills=skills,
            source_agent_guide=source_agent_guide,
            target_agent_guide=target_agent_guide,
        )
        copied = ", ".join(result.get("copied") or []) or "none"
        guide = "yes" if (result.get("agent_guide") or {}).get("copied") else "no"
        archived = ", ".join(result.get("archived") or []) or "none"
        message(
            "Vault Updated",
            f"Copied from repository: {copied}\nAGENTS guide copied: {guide}\nArchived: {archived}",
        )
        refresh()

    refresh_button.clicked.connect(refresh)
    adopt_button.clicked.connect(adopt_selected)
    publish_button.clicked.connect(publish)
    preview_external_button.clicked.connect(lambda: install_external(apply=False))
    install_external_button.clicked.connect(lambda: install_external(apply=True))
    close_button.clicked.connect(dialog.accept)
    qt["QShortcut"](qt["QKeySequence"]("Escape"), dialog).activated.connect(dialog.reject)

    refresh()
    dialog.exec()
    app.processEvents()
