from __future__ import annotations

from pathlib import Path
from typing import Any

from .gui_common import (
    _application,
    _dark_dialog_stylesheet,
    _load_qt_modules,
    _open_path,
    _style_message_box,
    _summary_font,
)


def _project_workspace_model(vault: Path | str) -> dict[str, Any]:
    from .obsidian import _collect_research_artifacts
    from .projects import initialize_vault, project_list
    from .sources import load_run_records, load_source_cards, read_frontmatter_markdown

    paths = initialize_vault(vault, rebuild=False)
    projects = project_list(paths.vault).get("projects") or []
    papers = []
    for card in load_source_cards(paths):
        key = card.citekey or card.slug
        papers.append(
            {
                "key": key,
                "slug": card.slug,
                "citekey": card.citekey or "",
                "title": card.title,
                "path": f"papers/{card.slug}.md",
                "pdf": "attached" if card.pdf else "missing",
                "status": card.enrichment_status or "",
                "target": key,
                "kind": "Paper",
            }
        )
    artifacts = _collect_research_artifacts(paths)
    resources: dict[str, list[dict[str, Any]]] = {"Paper": papers}
    for label, folder in [
        ("Concept", "concepts"),
        ("Synthesis", "syntheses"),
        ("Task", "tasks"),
    ]:
        resources[label] = [
            {
                "key": str(row.get("path") or ""),
                "target": str(row.get("path") or ""),
                "title": str(row.get("title") or row.get("path") or ""),
                "path": str(row.get("path") or ""),
                "type": str(row.get("type") or ""),
                "kind": label,
            }
            for row in artifacts.get(folder, [])
        ]
    resources["Run"] = [
        {
            "key": run.slug,
            "target": run.slug,
            "title": run.title or run.slug,
            "path": run.slug,
            "date": run.date,
            "kind": "Run",
        }
        for run in load_run_records(paths)
    ]
    proposal_rows: list[dict[str, Any]] = []
    if paths.proposals.exists():
        for child in sorted(paths.proposals.iterdir()):
            if child.name.startswith("."):
                continue
            if child.is_dir():
                title_path = child / "index.md"
                markdown_files = sorted(child.glob("*.md"))
                if not title_path.exists() and markdown_files:
                    title_path = markdown_files[0]
                if title_path.exists():
                    frontmatter, body = read_frontmatter_markdown(title_path)
                    title = str(
                        frontmatter.get("title")
                        or next(
                            (
                                line.removeprefix("#").strip()
                                for line in body.splitlines()
                                if line.startswith("# ")
                            ),
                            child.name,
                        )
                    )
                else:
                    title = child.name.replace("-", " ").replace("_", " ").title()
                proposal_rows.append(
                    {
                        "key": f"proposals/{child.name}",
                        "target": f"proposals/{child.name}",
                        "title": title,
                        "path": f"proposals/{child.name}",
                        "kind": "Proposal",
                    }
                )
            elif child.suffix.casefold() == ".md":
                frontmatter, body = read_frontmatter_markdown(child)
                title = str(
                    frontmatter.get("title")
                    or next(
                        (
                            line.removeprefix("#").strip()
                            for line in body.splitlines()
                            if line.startswith("# ")
                        ),
                        child.stem,
                    )
                )
                proposal_rows.append(
                    {
                        "key": f"proposals/{child.name}",
                        "target": f"proposals/{child.name}",
                        "title": title,
                        "path": f"proposals/{child.name}",
                        "kind": "Proposal",
                    }
                )
    resources["Proposal"] = proposal_rows
    return {
        "vault": str(paths.vault),
        "projects": sorted(projects, key=lambda row: str(row.get("slug") or "")),
        "papers": sorted(papers, key=lambda row: str(row.get("title") or "").casefold()),
        "resources": {
            key: sorted(rows, key=lambda row: str(row.get("title") or "").casefold())
            for key, rows in resources.items()
        },
    }


def _project_workspace_action_text(label: str, summary: dict[str, Any]) -> str:
    lines = [label]
    if "project_map" in summary:
        lines.append(f"Map: {summary.get('project_map')}")
        lines.append(
            "Linked papers={linked_papers}, gaps={gaps}, actions={recommended_next_actions}".format(
                **summary
            )
        )
    elif "issue_counts" in summary:
        lines.append(f"Audit: {summary.get('project')} [{'OK' if summary.get('ok') else 'ISSUES'}]")
        counts = summary.get("issue_counts") or {}
        for key, value in counts.items():
            if value:
                lines.append(f"- {key}: {value}")
        if summary.get("ok"):
            lines.append("- No issues found.")
    elif "changed" in summary:
        state = "linked" if summary.get("changed") else "already linked"
        lines.append(f"Paper {state}: {summary.get('ref')}")
        lines.append(f"Project: {summary.get('project')}")
    else:
        lines.append(f"Project: {summary.get('project')}")
        lines.append(f"State: {summary.get('state')}")
    refresh = summary.get("refresh") or {}
    if refresh:
        lines.append(
            "Refresh: {index_files_written} index, {llm_files_written} LLM files".format(
                **refresh
            )
        )
    return "\n".join(lines)


def _project_resource_accent(row: dict[str, Any]) -> str:
    colors = {
        "Paper": "#45ffb0" if row.get("pdf") == "attached" else "#ff3b4f",
        "Run": "#9ecbff",
        "Concept": "#45ffb0",
        "Synthesis": "#d2a8ff",
        "Task": "#ffb000",
        "Proposal": "#ff8bd1",
        "Project": "#69ffad",
    }
    return colors.get(str(row.get("kind") or ""), "#8ce7b8")


def _project_row_slug(row: dict[str, Any]) -> str:
    for key in ["slug", "key", "path", "target"]:
        value = str(row.get(key) or "").strip()
        if not value:
            continue
        path = Path(value)
        if value.endswith(".md"):
            return path.stem
        if "/" in value:
            return path.name
        return value
    return ""


def _project_button_stylesheet(tone: str = "neutral") -> str:
    tones = {
        "refresh": ("#1d6f4b", "#e4fff0", "#082015", "#103824"),
        "scaffold": ("#45ffb0", "#021007", "#45ffb0", "#69ffc0"),
        "link": ("#9ecbff", "#061526", "#9ecbff", "#b8dcff"),
        "map": ("#5db2ff", "#041321", "#5db2ff", "#87c7ff"),
        "audit": ("#ffb000", "#221700", "#ffb000", "#ffc94a"),
        "open": ("#d2a8ff", "#160521", "#d2a8ff", "#dfbdff"),
        "close": ("#426b58", "#d7ffe8", "#07100b", "#0d2418"),
        "neutral": ("#8ce7b8", "#f3fff7", "#07100b", "#102719"),
    }
    border, text, background, hover = tones.get(tone, tones["neutral"])
    return f"""
        QPushButton {{
            background: {background};
            color: {text};
            border: 1px solid {border};
            padding: 7px 14px;
            min-height: 30px;
            font-weight: 650;
        }}
        QPushButton:hover {{ background: {hover}; }}
        QPushButton:pressed {{
            background: #030504;
            color: #f3fff7;
        }}
        QPushButton:disabled {{
            color: #52705f;
            border-color: #244533;
            background: #030504;
        }}
    """


def _style_project_button(button: Any, tone: str = "neutral") -> None:
    button.setStyleSheet(_project_button_stylesheet(tone))


def _project_list_item_widget(
    qt: dict[str, Any],
    row: dict[str, Any],
    *,
    selected_callback: Any,
    row_height: int = 36,
) -> tuple[Any, Any]:
    item = qt["QListWidgetItem"]()
    item.setData(qt["Qt"].ItemDataRole.UserRole, row.get("key"))
    widget = qt["QWidget"]()
    widget.setFixedHeight(row_height)
    accent = _project_resource_accent(row)
    widget.setStyleSheet(
        "background: transparent; "
        f"border-left: 3px solid {accent}; border-bottom: 1px solid #123824;"
    )
    layout = qt["QHBoxLayout"](widget)
    layout.setContentsMargins(8, 4, 10, 4)
    layout.setSpacing(10)
    title_text = str(row.get("title") or row.get("key") or "")
    title = qt["QLabel"](title_text)
    title.setMinimumWidth(0)
    title.setFont(_summary_font(qt, 12, bold=True))
    title.setStyleSheet("color: #f3fff7; border: none;")
    title.setWordWrap(False)
    title.setToolTip(title_text)
    title.setAttribute(qt["Qt"].WidgetAttribute.WA_TransparentForMouseEvents, True)
    slug_text = _project_row_slug(row)
    slug = qt["QLabel"](slug_text)
    slug.setMinimumWidth(0)
    slug.setMaximumWidth(260)
    slug.setFont(_summary_font(qt, 10, mono=True))
    slug.setStyleSheet("color: #8ce7b8; border: none;")
    slug.setWordWrap(False)
    slug.setToolTip(slug_text)
    slug.setAttribute(qt["Qt"].WidgetAttribute.WA_TransparentForMouseEvents, True)
    layout.addWidget(title, 1)
    layout.addWidget(slug, 0)

    def activate(_event: Any) -> None:
        item.setSelected(True)
        selected_callback(item)

    widget.mousePressEvent = activate
    item.setSizeHint(qt["QSize"](0, row_height))
    return item, widget


def show_project_workspace(
    vault: Path | str,
    *,
    initial_slug: str | None = None,
    initial_title: str | None = None,
    initial_citekey: str | None = None,
) -> None:
    from .projects import (
        project_audit,
        project_link_concept,
        project_link_paper,
        project_link_proposal,
        project_link_run,
        project_link_synthesis,
        project_link_task,
        project_map,
        project_scaffold,
    )

    qt = _load_qt_modules(require_fitz=False)
    app = _application(qt)
    resolved_vault = str(Path(vault).expanduser().resolve())

    dialog = qt["QDialog"]()
    dialog.setWindowTitle("Scholar Vault Project Workspace")
    dialog.resize(1180, 780)
    dialog.setMinimumWidth(940)
    dialog.setStyleSheet(_dark_dialog_stylesheet())

    layout = qt["QVBoxLayout"](dialog)
    layout.setContentsMargins(26, 22, 26, 20)
    layout.setSpacing(10)

    kicker = qt["QLabel"]("SCHOLAR VAULT // PROJECT WORKSPACE")
    kicker.setFont(_summary_font(qt, 11, mono=True, bold=True))
    kicker.setStyleSheet("color: #69ffad;")
    layout.addWidget(kicker)

    heading = qt["QLabel"]("Project Workspace")
    heading.setFont(_summary_font(qt, 28, bold=True))
    heading.setStyleSheet("color: #f3fff7;")
    layout.addWidget(heading)

    vault_label = qt["QLabel"](resolved_vault)
    vault_label.setFont(_summary_font(qt, 10, mono=True))
    vault_label.setStyleSheet("color: #8ce7b8;")
    vault_label.setTextInteractionFlags(qt["Qt"].TextInteractionFlag.TextSelectableByMouse)
    layout.addWidget(vault_label)

    form = qt["QHBoxLayout"]()
    form.setSpacing(12)
    slug_field = qt["QLineEdit"]()
    slug_field.setPlaceholderText("project-slug")
    slug_field.setText(initial_slug or "")
    title_field = qt["QLineEdit"]()
    title_field.setPlaceholderText("Project title")
    title_field.setText(initial_title or "")
    target_field = qt["QLineEdit"]()
    target_field.setPlaceholderText("Selected resource id or path")
    target_field.setText(initial_citekey or "")
    for label_text, field, stretch in [
        ("Project", slug_field, 2),
        ("Title", title_field, 3),
        ("Link target", target_field, 3),
    ]:
        group = qt["QVBoxLayout"]()
        label = qt["QLabel"](label_text)
        label.setFont(_summary_font(qt, 9, mono=True, bold=True))
        label.setStyleSheet("color: #8ce7b8;")
        field.setMinimumHeight(34)
        field.setFont(_summary_font(qt, 11))
        group.addWidget(label)
        group.addWidget(field)
        form.addLayout(group, stretch)
    layout.addLayout(form)

    content = qt["QHBoxLayout"]()
    content.setSpacing(14)
    left_column = qt["QVBoxLayout"]()
    left_column.setSpacing(6)
    right_column = qt["QVBoxLayout"]()
    right_column.setSpacing(6)

    project_heading = qt["QLabel"]("Projects")
    project_heading.setFont(_summary_font(qt, 10, mono=True, bold=True))
    project_heading.setStyleSheet("color: #69ffad;")
    project_list_widget = qt["QListWidget"]()
    project_list_widget.setMinimumHeight(250)
    project_list_widget.setFont(_summary_font(qt, 10))
    project_list_widget.setSpacing(2)
    project_list_widget.setSelectionMode(qt["QListWidget"].SelectionMode.SingleSelection)
    project_list_widget.setStyleSheet(
        "QListWidget { border: 1px solid #1d6f4b; background: #020806; color: #f3fff7; }"
        "QListWidget::item { padding: 0; border: none; }"
        "QListWidget::item:selected { background: #0b3f2a; }"
    )
    left_column.addWidget(project_heading)
    left_column.addWidget(project_list_widget, 1)

    resource_controls = qt["QHBoxLayout"]()
    resource_heading = qt["QLabel"]("Link Resource")
    resource_heading.setFont(_summary_font(qt, 10, mono=True, bold=True))
    resource_heading.setStyleSheet("color: #9ecbff;")
    resource_type = qt["QComboBox"]()
    resource_types = ["Paper", "Run", "Concept", "Synthesis", "Task", "Proposal"]
    resource_type.addItems(resource_types)
    if initial_citekey:
        resource_type.setCurrentText("Paper")
    resource_type.setMinimumWidth(150)
    resource_type.setMinimumHeight(34)
    resource_type.setFont(_summary_font(qt, 11))
    resource_type.setStyleSheet(
        """
        QComboBox {
            background: #07100b;
            color: #f3fff7;
            border: 1px solid #9ecbff;
            padding: 6px 28px 6px 9px;
            selection-background-color: #1d6f4b;
        }
        QComboBox:hover { border-color: #b8dcff; }
        QComboBox::drop-down {
            width: 24px;
            border-left: 1px solid #2f73a5;
        }
        QComboBox QAbstractItemView {
            background: #07100b;
            color: #f3fff7;
            border: 1px solid #9ecbff;
            selection-background-color: #1d6f4b;
            selection-color: #ffffff;
            outline: 0;
        }
        """
    )
    resource_type.view().setFont(_summary_font(qt, 11))
    resource_type.view().setMinimumWidth(150)
    resource_type.view().setStyleSheet(
        """
        QListView {
            background: #07100b;
            color: #f3fff7;
            border: 1px solid #9ecbff;
            outline: 0;
        }
        QListView::item {
            min-height: 28px;
            padding: 6px 10px;
        }
        QListView::item:selected {
            background: #1d6f4b;
            color: #ffffff;
        }
        """
    )
    resource_filter = qt["QLineEdit"]()
    resource_filter.setPlaceholderText("Filter by title, id, path, status")
    resource_controls.addWidget(resource_heading)
    resource_controls.addWidget(resource_type)
    resource_controls.addWidget(resource_filter, 1)

    resource_list_widget = qt["QListWidget"]()
    resource_list_widget.setMinimumHeight(250)
    resource_list_widget.setFont(_summary_font(qt, 10))
    resource_list_widget.setSpacing(2)
    resource_list_widget.setSelectionMode(qt["QListWidget"].SelectionMode.SingleSelection)
    resource_list_widget.setStyleSheet(
        "QListWidget { border: 1px solid #2f73a5; background: #020806; color: #f3fff7; }"
        "QListWidget::item { padding: 0; border: none; }"
        "QListWidget::item:selected { background: #102f48; }"
    )
    right_column.addLayout(resource_controls)
    right_column.addWidget(resource_list_widget, 1)

    content.addLayout(left_column, 2)
    content.addLayout(right_column, 4)
    layout.addLayout(content, 1)

    result_box = qt["QTextEdit"]()
    result_box.setReadOnly(True)
    result_box.setMinimumHeight(118)
    result_box.setFont(_summary_font(qt, 10, mono=True))
    result_box.setStyleSheet(
        "QTextEdit { color: #d7ffe8; background: #00120b; border: 1px solid #006b45; "
        "padding: 10px; }"
    )
    layout.addWidget(result_box)

    buttons = qt["QHBoxLayout"]()
    refresh_button = qt["QPushButton"]("Refresh")
    scaffold_button = qt["QPushButton"]("Scaffold / Update")
    link_button = qt["QPushButton"]("Link Selected")
    map_button = qt["QPushButton"]("Generate Map")
    audit_button = qt["QPushButton"]("Run Audit")
    open_button = qt["QPushButton"]("Open Project")
    close_button = qt["QPushButton"]("Close")
    for button, tone in [
        (refresh_button, "refresh"),
        (scaffold_button, "scaffold"),
        (link_button, "link"),
        (map_button, "map"),
        (audit_button, "audit"),
        (open_button, "open"),
        (close_button, "close"),
    ]:
        button.setMinimumHeight(38)
        _style_project_button(button, tone)
        buttons.addWidget(button)
    buttons.addStretch(1)
    layout.addLayout(buttons)

    model: dict[str, Any] = {"projects": [], "resources": {}}
    project_rows: dict[str, dict[str, Any]] = {}
    resource_rows: dict[str, dict[str, Any]] = {}

    linkers = {
        "Paper": project_link_paper,
        "Run": project_link_run,
        "Concept": project_link_concept,
        "Synthesis": project_link_synthesis,
        "Task": project_link_task,
        "Proposal": project_link_proposal,
    }

    def message(title: str, text: str) -> None:
        box = qt["QMessageBox"](dialog)
        box.setWindowTitle(title)
        box.setText(text)
        _style_message_box(qt, box)
        box.exec()

    def current_slug() -> str:
        return slug_field.text().strip()

    def current_title() -> str | None:
        title = title_field.text().strip()
        return title or None

    def current_target() -> str:
        return target_field.text().strip()

    def project_exists() -> bool:
        slug = current_slug()
        return bool(slug and (Path(resolved_vault) / "projects" / slug / "index.md").exists())

    def update_action_buttons() -> None:
        has_slug = bool(current_slug())
        has_project = project_exists()
        has_target = bool(current_target())
        scaffold_button.setEnabled(has_slug)
        map_button.setEnabled(has_project)
        audit_button.setEnabled(has_project)
        open_button.setEnabled(has_project)
        link_button.setEnabled(has_project and has_target)

    def select_project(item: Any) -> None:
        slug = item.data(qt["Qt"].ItemDataRole.UserRole)
        row = project_rows.get(str(slug))
        if not row:
            return
        slug_field.setText(str(row.get("slug") or ""))
        title_field.setText(str(row.get("title") or ""))
        update_action_buttons()

    def select_resource(item: Any) -> None:
        key = item.data(qt["Qt"].ItemDataRole.UserRole)
        row = resource_rows.get(str(key))
        if not row:
            return
        target_field.setText(str(row.get("target") or row.get("key") or ""))
        update_action_buttons()

    def populate_projects() -> None:
        project_list_widget.clear()
        project_rows.clear()
        for row in model.get("projects", []):
            slug = str(row.get("slug") or "")
            item_row = {
                "kind": "Project",
                "key": slug,
                "title": row.get("title") or slug,
                "path": row.get("path") or "",
            }
            project_rows[slug] = row
            item, widget = _project_list_item_widget(
                qt,
                item_row,
                selected_callback=select_project,
                row_height=38,
            )
            project_list_widget.addItem(item)
            project_list_widget.setItemWidget(item, widget)
            if slug and slug == current_slug():
                project_list_widget.setCurrentItem(item)
        if not model.get("projects"):
            project_list_widget.addItem(qt["QListWidgetItem"]("No projects yet."))

    def populate_resources(_value: str | None = None) -> None:
        resource_list_widget.clear()
        resource_rows.clear()
        kind = resource_type.currentText()
        needle = resource_filter.text().strip().casefold()
        rows = model.get("resources", {}).get(kind, [])
        visible = []
        for row in rows:
            haystack = " ".join(str(value or "") for value in row.values()).casefold()
            if needle and needle not in haystack:
                continue
            visible.append(row)
        for row in visible[:300]:
            key = str(row.get("key") or row.get("target") or "")
            resource_rows[key] = row
            item, widget = _project_list_item_widget(
                qt,
                row,
                selected_callback=select_resource,
                row_height=38,
            )
            resource_list_widget.addItem(item)
            resource_list_widget.setItemWidget(item, widget)
            if key and key == current_target():
                resource_list_widget.setCurrentItem(item)
        if not visible:
            resource_list_widget.addItem(qt["QListWidgetItem"](f"No matching {kind.lower()}s."))

    def change_resource_type(_value: int | None = None) -> None:
        target_field.clear()
        populate_resources()
        update_action_buttons()

    def refresh(_checked: bool = False, *, reset_result: bool = True) -> None:
        try:
            model.clear()
            model.update(_project_workspace_model(resolved_vault))
        except Exception as exc:
            message("Project UI Error", str(exc))
            return
        populate_projects()
        populate_resources()
        if reset_result:
            resource_counts = model.get("resources", {})
            lines = [f"Projects: {len(model.get('projects', []))}"]
            lines.extend(
                f"{name}s: {len(resource_counts.get(name, []))}"
                for name in ["Paper", "Run", "Concept", "Synthesis", "Task", "Proposal"]
            )
            result_box.setPlainText("\n".join(lines))
        update_action_buttons()

    def run_scaffold() -> None:
        if not current_slug():
            message("Missing Project Slug", "Enter a project slug first.")
            return
        try:
            summary = project_scaffold(resolved_vault, current_slug(), title=current_title())
            result_box.setPlainText(_project_workspace_action_text("Project scaffold", summary))
            refresh(reset_result=False)
        except Exception as exc:
            message("Project Scaffold Failed", str(exc))

    def run_link_selected() -> None:
        kind = resource_type.currentText()
        target = current_target()
        if not current_slug() or not target:
            message("Missing Project Or Resource", "Enter a project slug and link target first.")
            return
        try:
            summary = linkers[kind](resolved_vault, current_slug(), target)
            result_box.setPlainText(
                _project_workspace_action_text(f"Project link-{kind.casefold()}", summary)
            )
            refresh(reset_result=False)
        except Exception as exc:
            message(f"Project Link {kind} Failed", str(exc))

    def run_map() -> None:
        if not current_slug():
            message("Missing Project Slug", "Enter or select a project slug first.")
            return
        try:
            summary = project_map(resolved_vault, current_slug())
            result_box.setPlainText(_project_workspace_action_text("Project map", summary))
            refresh(reset_result=False)
        except Exception as exc:
            message("Project Map Failed", str(exc))

    def run_audit() -> None:
        if not current_slug():
            message("Missing Project Slug", "Enter or select a project slug first.")
            return
        try:
            summary = project_audit(resolved_vault, current_slug())
            result_box.setPlainText(_project_workspace_action_text("Project audit", summary))
        except Exception as exc:
            message("Project Audit Failed", str(exc))

    def open_project() -> None:
        if not current_slug():
            message("Missing Project Slug", "Enter or select a project slug first.")
            return
        project_path = Path(resolved_vault) / "projects" / current_slug() / "index.md"
        if not project_path.exists():
            message("Project Missing", f"Project file does not exist: {project_path}")
            return
        _open_path(qt, str(project_path))

    project_list_widget.itemClicked.connect(select_project)
    resource_list_widget.itemClicked.connect(select_resource)
    slug_field.textChanged.connect(update_action_buttons)
    target_field.textChanged.connect(update_action_buttons)
    resource_filter.textChanged.connect(populate_resources)
    resource_type.currentIndexChanged.connect(change_resource_type)
    refresh_button.clicked.connect(refresh)
    scaffold_button.clicked.connect(run_scaffold)
    link_button.clicked.connect(run_link_selected)
    map_button.clicked.connect(run_map)
    audit_button.clicked.connect(run_audit)
    open_button.clicked.connect(open_project)
    close_button.clicked.connect(dialog.accept)
    qt["QShortcut"](qt["QKeySequence"]("Escape"), dialog).activated.connect(dialog.accept)

    refresh()
    update_action_buttons()
    dialog.exec()
    app.processEvents()
