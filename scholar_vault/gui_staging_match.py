from __future__ import annotations

from pathlib import Path
from typing import Any

from .gui_common import (
    _application,
    _dark_dialog_stylesheet,
    _exec_modeless_dialog,
    _load_qt_modules,
    _move_staged_pdf_to_trash,
    _open_path,
    _style_button,
    _style_message_box,
    _summary_font,
    _summary_panel,
)


def _clip_text(value: object, limit: int = 90) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "..."


def _staging_match_color(score: int) -> str:
    if score >= 90:
        return "#45ffb0"
    if score >= 75:
        return "#ffb000"
    return "#ff6b7a"


def _staging_match_model(summary: dict[str, Any]) -> dict[str, Any]:
    rows = []
    for row in summary.get("matches") or []:
        score = int(row.get("score") or 0)
        pdf_label = row.get("pdf_filename") or row.get("query_title") or "(title query)"
        pdf_title = row.get("pdf_title")
        rationale_points = row.get("rationale_points") or []
        rationale_text = "; ".join(
            str(point.get("text") or point.get("label") or "").strip()
            for point in rationale_points
            if isinstance(point, dict)
        )
        rows.append(
            {
                "run_id": str(row.get("run_id") or ""),
                "run_title": str(row.get("run_title") or row.get("run_id") or ""),
                "rank": row.get("rank") or "",
                "scholar_cid": str(row.get("scholar_cid") or ""),
                "score": score,
                "score_color": _staging_match_color(score),
                "result_title": str(row.get("result_title") or ""),
                "pdf_label": str(pdf_label or ""),
                "pdf_path": str(row.get("pdf_path") or ""),
                "pdf_title": str(pdf_title or ""),
                "paper_card": str(row.get("paper_card") or ""),
                "attached": bool(row.get("attached")),
                "reason": str(row.get("reason") or ""),
                "decision": str(row.get("decision") or ""),
                "summary": str(row.get("summary") or ""),
                "rationale": rationale_text,
                "state": (
                    f"{row.get('status') or '-'} / {row.get('pdf_status') or '-'}"
                    f"{' / already attached' if row.get('attached') else ''}"
                ),
                "year": row.get("year") or "",
            }
        )
    return {
        "runs": int(summary.get("runs") or 0),
        "scanned": int(summary.get("staged_pdfs_scanned") or 0),
        "cache_hits": int(summary.get("staged_pdf_cache_hits") or 0),
        "min_score": int(summary.get("min_score") or 0),
        "rows": rows,
    }


def _build_staging_match_row(
    qt: dict[str, Any],
    row: dict[str, Any],
    choose: Any,
    *,
    open_card: Any,
    remove_pdf: Any,
) -> Any:
    panel = qt["QFrame"]()
    panel.setStyleSheet(
        "QFrame { background: #030504; border: none; border-bottom: 1px solid #26553b; }"
    )
    layout = qt["QHBoxLayout"](panel)
    layout.setContentsMargins(14, 12, 14, 12)
    layout.setSpacing(14)

    score_box = qt["QVBoxLayout"]()
    score = qt["QLabel"](str(row["score"]))
    score.setFont(_summary_font(qt, 24, mono=True, bold=True))
    score.setStyleSheet(f"color: {row['score_color']}; border: none;")
    score_label = qt["QLabel"]("SCORE")
    score_label.setFont(_summary_font(qt, 8, mono=True, bold=True))
    score_label.setStyleSheet("color: #8ce7b8; border: none;")
    score_box.addWidget(score)
    score_box.addWidget(score_label)
    score_box.addStretch(1)
    layout.addLayout(score_box, 0)

    detail = qt["QVBoxLayout"]()
    title = qt["QLabel"](_clip_text(row["result_title"], 140))
    title.setWordWrap(True)
    title.setFont(_summary_font(qt, 14, bold=True))
    title.setStyleSheet("color: #f3fff7; border: none;")
    detail.addWidget(title)
    pdf = qt["QLabel"](f"PDF/query: {_clip_text(row['pdf_label'], 110)}")
    pdf.setWordWrap(True)
    pdf.setFont(_summary_font(qt, 10, mono=True))
    pdf.setStyleSheet("color: #8ce7b8; border: none;")
    detail.addWidget(pdf)
    if row["pdf_title"]:
        inferred = qt["QLabel"](f"PDF title: {_clip_text(row['pdf_title'], 140)}")
        inferred.setWordWrap(True)
        inferred.setFont(_summary_font(qt, 10))
        inferred.setStyleSheet("color: #baffdc; border: none;")
        detail.addWidget(inferred)
    if row.get("summary"):
        summary = qt["QLabel"](f"Scholar Labs summary: {_clip_text(row['summary'], 260)}")
        summary.setWordWrap(True)
        summary.setFont(_summary_font(qt, 10))
        summary.setStyleSheet("color: #d4fbe4; border: none;")
        summary.setTextInteractionFlags(qt["Qt"].TextInteractionFlag.TextSelectableByMouse)
        detail.addWidget(summary)
    if row.get("rationale"):
        rationale = qt["QLabel"](f"Rationale: {_clip_text(row['rationale'], 220)}")
        rationale.setWordWrap(True)
        rationale.setFont(_summary_font(qt, 9))
        rationale.setStyleSheet("color: #9be7bd; border: none;")
        rationale.setTextInteractionFlags(qt["Qt"].TextInteractionFlag.TextSelectableByMouse)
        detail.addWidget(rationale)
    meta = qt["QLabel"](
        f"run: {row['run_title']}  //  rank {row['rank']}  //  "
        f"{row['state']}  //  {row['reason']} {row['decision']}"
    )
    meta.setWordWrap(True)
    meta.setFont(_summary_font(qt, 9, mono=True))
    meta.setStyleSheet("color: #68c792; border: none;")
    detail.addWidget(meta)
    run_id = qt["QLabel"](row["run_id"])
    run_id.setFont(_summary_font(qt, 9, mono=True))
    run_id.setStyleSheet("color: #68c792; border: none;")
    run_id.setTextInteractionFlags(qt["Qt"].TextInteractionFlag.TextSelectableByMouse)
    detail.addWidget(run_id)
    layout.addLayout(detail, 1)

    actions = qt["QVBoxLayout"]()
    actions.setSpacing(8)
    if row.get("attached"):
        attached = qt["QPushButton"]("Attached")
        attached.setEnabled(False)
        attached.setMinimumWidth(118)
        attached.setMinimumHeight(34)
        _style_button(attached, "muted")
        actions.addWidget(attached)
    elif row.get("pdf_path"):
        import_button = qt["QPushButton"]("Import PDF")
        import_button.setMinimumWidth(118)
        import_button.setMinimumHeight(34)
        _style_button(import_button, "primary" if row["score"] >= 75 else "neutral")
        import_button.clicked.connect(lambda _checked=False, selected=row: choose(selected))
        actions.addWidget(import_button)
    else:
        needs_pdf = qt["QPushButton"]("Choose PDF")
        needs_pdf.setEnabled(False)
        needs_pdf.setMinimumWidth(118)
        needs_pdf.setMinimumHeight(34)
        _style_button(needs_pdf, "muted")
        actions.addWidget(needs_pdf)

    if row.get("attached") and row.get("paper_card"):
        open_card_button = qt["QPushButton"]("Open Card")
        open_card_button.setMinimumWidth(118)
        open_card_button.setMinimumHeight(32)
        _style_button(open_card_button, "neutral")
        open_card_button.clicked.connect(
            lambda _checked=False, selected=row: open_card(selected)
        )
        actions.addWidget(open_card_button)

    if row.get("attached") and row.get("pdf_path"):
        remove_button = qt["QPushButton"]("Remove PDF")
        remove_button.setMinimumWidth(118)
        remove_button.setMinimumHeight(32)
        _style_button(remove_button, "danger")
        remove_button.clicked.connect(
            lambda _checked=False, selected=row: remove_pdf(selected)
        )
        actions.addWidget(remove_button)

    actions.addStretch(1)
    layout.addLayout(actions, 0)
    return panel


def choose_staging_match(
    vault: str,
    staging: str,
    search_callback: Any,
    *,
    title: str | None = None,
    pdf: str | None = None,
    min_score: int = 60,
    limit: int = 50,
    unselected_only: bool = False,
    import_callback: Any | None = None,
) -> str | None:
    qt = _load_qt_modules(require_fitz=False)
    app = _application(qt)
    selected: dict[str, str | None] = {"run_id": None}

    dialog = qt["QDialog"]()
    dialog.setWindowTitle("Scholar Vault Staging Matches")
    dialog.resize(1180, 760)
    dialog.setStyleSheet(_dark_dialog_stylesheet())

    layout = qt["QVBoxLayout"](dialog)
    layout.setContentsMargins(28, 24, 28, 20)
    layout.setSpacing(14)

    header = qt["QHBoxLayout"]()
    heading_block = qt["QVBoxLayout"]()
    kicker = qt["QLabel"]("SCHOLAR VAULT // STAGING")
    kicker.setFont(_summary_font(qt, 12, mono=True, bold=True))
    kicker.setStyleSheet("color: #69ffad;")
    heading = qt["QLabel"]("MATCH LEFTOVER PDFS")
    heading.setFont(_summary_font(qt, 30, bold=True))
    heading.setStyleSheet("color: #f3fff7;")
    subheading = qt["QLabel"](
        "Search previous Scholar Labs runs by staged PDF text, one chosen PDF, or a typed "
        "title. Import PDF attaches the chosen file to that specific run result."
    )
    subheading.setFont(_summary_font(qt, 12))
    subheading.setStyleSheet("color: #8ce7b8;")
    subheading.setWordWrap(True)
    vault_label = qt["QLabel"](f"vault: {vault}\nstaging: {staging}")
    vault_label.setFont(_summary_font(qt, 10, mono=True))
    vault_label.setStyleSheet("color: #68c792;")
    vault_label.setWordWrap(True)
    heading_block.addWidget(kicker)
    heading_block.addWidget(heading)
    heading_block.addWidget(subheading)
    heading_block.addWidget(vault_label)
    header.addLayout(heading_block, 1)
    count_panel = _summary_panel(qt, "#69ffad")
    count_panel.setFixedWidth(180)
    count_layout = qt["QVBoxLayout"](count_panel)
    count_label = qt["QLabel"]("MATCHES")
    count_label.setFont(_summary_font(qt, 11, mono=True, bold=True))
    count_label.setStyleSheet("color: #8ce7b8; border: none;")
    count_value = qt["QLabel"]("0")
    count_value.setFont(_summary_font(qt, 34, mono=True, bold=True))
    count_value.setStyleSheet("color: #69ffad; border: none;")
    count_layout.addWidget(count_label)
    count_layout.addWidget(count_value)
    header.addWidget(count_panel)
    layout.addLayout(header)

    controls = qt["QFrame"]()
    controls.setStyleSheet("QFrame { background: #030504; border: 1px solid #26553b; }")
    controls_layout = qt["QVBoxLayout"](controls)
    controls_layout.setContentsMargins(12, 12, 12, 12)
    controls_layout.setSpacing(8)

    title_field = qt["QLineEdit"]()
    title_field.setText(title or "")
    title_field.setPlaceholderText("Paper title to find in previous Scholar Labs run results")
    controls_layout.addWidget(title_field)

    pdf_row = qt["QHBoxLayout"]()
    pdf_field = qt["QLineEdit"]()
    pdf_field.setText(pdf or "")
    pdf_field.setPlaceholderText("PDF path to import for the selected matching result")
    browse = qt["QPushButton"]("Choose PDF")
    clear_pdf = qt["QPushButton"]("Clear")
    _style_button(browse, "neutral")
    _style_button(clear_pdf, "muted")
    pdf_row.addWidget(pdf_field, 1)
    pdf_row.addWidget(browse)
    pdf_row.addWidget(clear_pdf)
    controls_layout.addLayout(pdf_row)

    option_row = qt["QHBoxLayout"]()
    min_field = qt["QLineEdit"](str(min_score))
    min_field.setMaximumWidth(80)
    limit_field = qt["QLineEdit"](str(limit))
    limit_field.setMaximumWidth(80)
    unselected = qt["QCheckBox"]("hide already attached")
    unselected.setChecked(unselected_only)
    search = qt["QPushButton"]("Search")
    scan_all = qt["QPushButton"]("Scan Staging")
    _style_button(search, "primary")
    _style_button(scan_all, "neutral")
    option_row.addWidget(qt["QLabel"]("min score"))
    option_row.addWidget(min_field)
    option_row.addWidget(qt["QLabel"]("limit"))
    option_row.addWidget(limit_field)
    option_row.addWidget(unselected)
    option_row.addStretch(1)
    option_row.addWidget(scan_all)
    option_row.addWidget(search)
    controls_layout.addLayout(option_row)
    layout.addWidget(controls)

    status = qt["QLabel"]("Ready.")
    status.setFont(_summary_font(qt, 10, mono=True))
    status.setStyleSheet("color: #8ce7b8;")
    layout.addWidget(status)

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
    scroll.setWidget(container)
    layout.addWidget(scroll, 1)

    def choose(row: dict[str, Any]) -> None:
        selected["run_id"] = str(row.get("run_id") or "")
        pdf_path = str(row.get("pdf_path") or "")
        if not pdf_path:
            status.setText("Choose a PDF path before importing this match.")
            return
        status.setText(
            f"Importing {Path(pdf_path).name} for run {selected['run_id']}..."
        )
        app.processEvents()
        if import_callback is None:
            dialog.accept()
            return

        search.setEnabled(False)
        scan_all.setEnabled(False)
        browse.setEnabled(False)
        clear_pdf.setEnabled(False)
        scroll.setEnabled(False)
        cancel.setEnabled(False)
        dialog.setCursor(qt["Qt"].CursorShape.WaitCursor)
        dialog.hide()
        app.processEvents()
        try:
            import_callback(row)
        except Exception as exc:  # pragma: no cover - defensive UI error handling
            dialog.show()
            dialog.raise_()
            dialog.activateWindow()
            box = qt["QMessageBox"](dialog)
            box.setWindowTitle("Targeted Import Failed")
            box.setIcon(qt["QMessageBox"].Icon.Warning)
            box.setText(str(exc))
            box.setStandardButtons(qt["QMessageBox"].StandardButton.Ok)
            _style_message_box(qt, box)
            box.exec()
        finally:
            dialog.unsetCursor()
            search.setEnabled(True)
            scan_all.setEnabled(True)
            browse.setEnabled(True)
            clear_pdf.setEnabled(True)
            scroll.setEnabled(True)
            cancel.setEnabled(True)
            if pdf_field.text().strip() and not Path(pdf_field.text().strip()).exists():
                pdf_field.clear()
            status.setText("Targeted import finished; refreshing leftover matches...")
            if not dialog.isVisible():
                dialog.show()
            dialog.raise_()
            dialog.activateWindow()
            app.processEvents()
            run_search(clear_query=False)

    def open_row_card(row: dict[str, Any]) -> None:
        paper_card = str(row.get("paper_card") or "")
        if paper_card:
            _open_path(qt, str(Path(vault).expanduser() / paper_card))

    def remove_row_pdf(row: dict[str, Any]) -> None:
        source = str(row.get("pdf_path") or "")
        if not source:
            return
        box = qt["QMessageBox"](dialog)
        box.setWindowTitle("Remove Staging PDF")
        box.setIcon(qt["QMessageBox"].Icon.Warning)
        box.setText(
            "Move this already attached staging PDF into the staging trash folder?"
        )
        box.setInformativeText(
            f"{Path(source).name}\n\nThe vault card keeps its own PDF copy."
        )
        box.setStandardButtons(
            qt["QMessageBox"].StandardButton.Ok
            | qt["QMessageBox"].StandardButton.Cancel
        )
        _style_message_box(qt, box)
        if box.exec() != qt["QMessageBox"].StandardButton.Ok:
            return
        try:
            destination = _move_staged_pdf_to_trash(staging, source)
        except Exception as exc:  # pragma: no cover - defensive UI error handling
            error = qt["QMessageBox"](dialog)
            error.setWindowTitle("PDF Not Removed")
            error.setIcon(qt["QMessageBox"].Icon.Warning)
            error.setText(str(exc))
            error.setStandardButtons(qt["QMessageBox"].StandardButton.Ok)
            _style_message_box(qt, error)
            error.exec()
            return
        if pdf_field.text().strip() == source:
            pdf_field.clear()
        status.setText(f"Moved {Path(source).name} to {destination.parent}.")
        app.processEvents()
        run_search(clear_query=False)

    def clear_rows() -> None:
        while rows_layout.count():
            item = rows_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def render(summary: dict[str, Any]) -> None:
        model = _staging_match_model(summary)
        count_value.setText(str(len(model["rows"])))
        clear_rows()
        if model["rows"]:
            for row in model["rows"]:
                rows_layout.addWidget(
                    _build_staging_match_row(
                        qt,
                        row,
                        choose,
                        open_card=open_row_card,
                        remove_pdf=remove_row_pdf,
                    )
                )
            rows_layout.addStretch(1)
        else:
            empty = qt["QLabel"]("No previous run result matched above the threshold.")
            empty.setFont(_summary_font(qt, 14, bold=True))
            empty.setStyleSheet("color: #ffccd4; border: none; padding: 20px;")
            rows_layout.addWidget(empty)
            rows_layout.addStretch(1)
        status.setText(
            f"{model['runs']} runs checked; {model['scanned']} PDF scan(s); "
            f"{model['cache_hits']} cached; min score {model['min_score']}."
        )
        app.processEvents()

    def progress(message: str, current: int | None = None, total: int | None = None) -> None:
        prefix = f"{current}/{total} " if current is not None and total else ""
        status.setText(f"{prefix}{message}")
        app.processEvents()

    def parsed_options() -> tuple[int, int] | None:
        try:
            parsed_min = int(min_field.text().strip() or "60")
            parsed_limit = int(limit_field.text().strip() or "50")
        except ValueError:
            status.setText("Min score and limit must be integers.")
            return None
        if parsed_min < 0 or parsed_min > 100 or parsed_limit < 0:
            status.setText("Min score must be 0-100 and limit must be 0 or greater.")
            return None
        return parsed_min, parsed_limit

    def run_search(*, clear_query: bool = False) -> None:
        options = parsed_options()
        if options is None:
            return
        if clear_query:
            title_field.clear()
            pdf_field.clear()
        search.setEnabled(False)
        scan_all.setEnabled(False)
        dialog.setCursor(qt["Qt"].CursorShape.WaitCursor)
        try:
            summary = search_callback(
                title_field.text().strip() or None,
                pdf_field.text().strip() or None,
                options[0],
                options[1],
                unselected.isChecked(),
                progress,
            )
        except Exception as exc:  # pragma: no cover - defensive UI error handling
            box = qt["QMessageBox"](dialog)
            box.setWindowTitle("Search Failed")
            box.setIcon(qt["QMessageBox"].Icon.Warning)
            box.setText(str(exc))
            box.setStandardButtons(qt["QMessageBox"].StandardButton.Ok)
            _style_message_box(qt, box)
            box.exec()
        else:
            render(summary)
        finally:
            dialog.unsetCursor()
            search.setEnabled(True)
            scan_all.setEnabled(True)

    def browse_pdf() -> None:
        chosen, _filter = qt["QFileDialog"].getOpenFileName(
            dialog,
            "Choose Staged PDF",
            str(Path(staging).expanduser()),
            "PDF files (*.pdf)",
        )
        if chosen:
            pdf_field.setText(chosen)

    browse.clicked.connect(browse_pdf)
    clear_pdf.clicked.connect(lambda _checked=False: pdf_field.clear())
    search.clicked.connect(lambda _checked=False: run_search(clear_query=False))
    scan_all.clicked.connect(lambda _checked=False: run_search(clear_query=True))
    title_field.returnPressed.connect(lambda: run_search(clear_query=False))

    buttons = qt["QHBoxLayout"]()
    hint = qt["QLabel"](
        "Esc closes. Import PDF accepts the chosen file for one matched run result, "
        "then refreshes this queue."
    )
    hint.setFont(_summary_font(qt, 10))
    hint.setStyleSheet("color: #68c792;")
    buttons.addWidget(hint, 1)
    cancel = qt["QPushButton"]("Close")
    cancel.setMinimumWidth(110)
    _style_button(cancel, "muted")
    cancel.clicked.connect(dialog.reject)
    buttons.addWidget(cancel)
    layout.addLayout(buttons)

    qt["QShortcut"](qt["QKeySequence"]("Escape"), dialog).activated.connect(dialog.reject)
    qt["QTimer"].singleShot(0, lambda: run_search(clear_query=False))
    if import_callback is None:
        result = dialog.exec()
    else:
        _exec_modeless_dialog(qt, app, dialog)
        result = dialog.result()
    app.processEvents()
    if result == qt["QDialog"].DialogCode.Accepted:
        return selected["run_id"]
    return None


