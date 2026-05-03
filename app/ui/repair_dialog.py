"""
Lumina — RepairDialog.

QDialog that wraps :mod:`app.core.repair.jpeg_repair` and
:mod:`app.core.repair.mp4_repair` so users can analyze and rebuild
JPEG/MP4 files from the Outils screen.

The diagnose pass is read-only and runs synchronously (small files only).
The repair pass runs in a QThread so the UI never freezes.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from app.core.repair.jpeg_repair import (
    RepairReport,
    diagnose_jpeg,
    repair_jpeg,
)
from app.core.repair.mp4_repair import (
    Mp4RepairReport,
    diagnose_mp4,
    repair_mp4,
)
from app.ui.palette import (
    BEVEL_LIGHT,
    BEVEL_SHADOW,
    ERR,
    OK,
    SUB,
    TEXT,
    WIN98_NAVY,
    WIN98_SILVER,
    WIN98_WHITE,
)

_log = logging.getLogger("lumina.recovery")

_JPEG_EXTS = {".jpg", ".jpeg", ".jpe", ".jfif"}
_MP4_EXTS = {".mp4", ".m4v", ".mov"}


def _detect_kind(filepath: str) -> str | None:
    ext = Path(filepath).suffix.lower()
    if ext in _JPEG_EXTS:
        return "jpeg"
    if ext in _MP4_EXTS:
        return "mp4"
    return None


# ─────────────────────────────────────────────────────────────────────────────
#  Repair worker (runs the actual write in a QThread)
# ─────────────────────────────────────────────────────────────────────────────


class _RepairWorker(QThread):
    """Background thread that calls repair_jpeg / repair_mp4."""

    finished_ok = pyqtSignal(object)  # RepairReport | Mp4RepairReport
    failed = pyqtSignal(str)

    def __init__(self, kind: str, input_path: str, output_path: str) -> None:
        super().__init__()
        self._kind = kind
        self._input = input_path
        self._output = output_path

    def run(self) -> None:
        try:
            if self._kind == "jpeg":
                report = repair_jpeg(self._input, self._output)
            elif self._kind == "mp4":
                report = repair_mp4(self._input, self._output)
            else:
                raise ValueError(f"Unsupported kind: {self._kind!r}")
            self.finished_ok.emit(report)
        except Exception as exc:
            _log.exception("[RepairWorker] failed: %s", exc)
            self.failed.emit(str(exc))


# ─────────────────────────────────────────────────────────────────────────────
#  Dialog
# ─────────────────────────────────────────────────────────────────────────────


class RepairDialog(QDialog):
    """Win98-styled dialog: pick a file → diagnose → repair."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Lumina — Reparation de fichiers")
        self.setMinimumSize(560, 460)
        self.setStyleSheet(
            f"QDialog {{ background-color: {WIN98_SILVER}; }} "
            f"QLabel  {{ color: {TEXT}; font-family: 'Work Sans', Arial; }}"
        )

        self._input_path: str | None = None
        self._kind: str | None = None
        self._worker: _RepairWorker | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)

        # ── Header ─────────────────────────────────────────────────────────
        title = QLabel("Reparation de fichiers JPEG / MP4")
        title.setStyleSheet(
            f"font-size: 13px; font-weight: 700; color: {TEXT}; background: transparent;"
        )
        root.addWidget(title)

        intro = QLabel(
            "Choisissez un fichier image ou video corrompu. Lumina detecte "
            "les marqueurs SOI/EOI manquants (JPEG) ou les atomes moov/mdat "
            "mal places (MP4/MOV) et tente de reconstruire un fichier "
            "lisible."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color: {SUB}; font-size: 11px; background: transparent;")
        root.addWidget(intro)

        # ── File picker row ─────────────────────────────────────────────────
        picker_row = QHBoxLayout()
        picker_row.setSpacing(8)

        self._file_lbl = QLabel("Aucun fichier selectionne.")
        self._file_lbl.setStyleSheet(
            f"background-color: {WIN98_WHITE}; color: {TEXT}; "
            f"border: 1px solid {BEVEL_SHADOW}; padding: 4px 6px; "
            "font-size: 11px;"
        )
        picker_row.addWidget(self._file_lbl, stretch=1)

        self._pick_btn = QPushButton("Parcourir…")
        self._pick_btn.setFixedSize(96, 26)
        self._pick_btn.setCursor(Qt.CursorShape.ArrowCursor)
        self._pick_btn.clicked.connect(self._on_pick_file)
        picker_row.addWidget(self._pick_btn)

        root.addLayout(picker_row)

        # ── Diagnose / Repair buttons ───────────────────────────────────────
        action_row = QHBoxLayout()
        action_row.setSpacing(8)

        self._diag_btn = QPushButton("Analyser")
        self._diag_btn.setFixedSize(110, 26)
        self._diag_btn.setEnabled(False)
        self._diag_btn.clicked.connect(self._on_diagnose)
        action_row.addWidget(self._diag_btn)

        self._repair_btn = QPushButton("Reparer…")
        self._repair_btn.setFixedSize(110, 26)
        self._repair_btn.setEnabled(False)
        self._repair_btn.clicked.connect(self._on_repair)
        action_row.addWidget(self._repair_btn)

        action_row.addStretch()

        self._close_btn = QPushButton("Fermer")
        self._close_btn.setFixedSize(96, 26)
        self._close_btn.clicked.connect(self.accept)
        action_row.addWidget(self._close_btn)

        root.addLayout(action_row)

        # ── Issues report ───────────────────────────────────────────────────
        self._report = QTextEdit()
        self._report.setReadOnly(True)
        self._report.setStyleSheet(
            f"background-color: {WIN98_WHITE}; color: {TEXT}; "
            f"border-top: 1px solid {BEVEL_SHADOW}; "
            f"border-left: 1px solid {BEVEL_SHADOW}; "
            f"border-bottom: 1px solid {BEVEL_LIGHT}; "
            f"border-right: 1px solid {BEVEL_LIGHT}; "
            "font-family: 'Consolas', monospace; font-size: 11px; padding: 6px;"
        )
        self._report.setPlaceholderText(
            "Le rapport d'analyse s'affichera ici apres avoir clique sur Analyser."
        )
        root.addWidget(self._report, stretch=1)

        # ── Progress bar (shown during repair) ──────────────────────────────
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)  # indeterminate
        self._progress.setVisible(False)
        self._progress.setStyleSheet(
            f"QProgressBar {{ background-color: {WIN98_WHITE}; "
            f"border: 1px solid {BEVEL_SHADOW}; height: 16px; }} "
            f"QProgressBar::chunk {{ background-color: {WIN98_NAVY}; }}"
        )
        root.addWidget(self._progress)

    # ────────────────────────────────────────────────────────────────────────
    # File picker
    # ────────────────────────────────────────────────────────────────────────

    def _on_pick_file(self) -> None:
        filt = (
            "Fichiers reparables (*.jpg *.jpeg *.jpe *.jfif *.mp4 *.m4v *.mov);;"
            "Images JPEG (*.jpg *.jpeg *.jpe *.jfif);;"
            "Videos MP4/MOV (*.mp4 *.m4v *.mov);;"
            "Tous les fichiers (*)"
        )
        path, _selected = QFileDialog.getOpenFileName(
            self,
            "Choisir un fichier a reparer",
            "",
            filt,
        )
        if not path:
            return
        kind = _detect_kind(path)
        if kind is None:
            QMessageBox.warning(
                self,
                "Type non supporte",
                "Lumina ne peut reparer que les fichiers JPEG, MP4 et MOV.",
            )
            return
        self._input_path = path
        self._kind = kind
        self._file_lbl.setText(os.path.basename(path))
        self._diag_btn.setEnabled(True)
        self._repair_btn.setEnabled(False)
        self._report.clear()
        self._report.setPlaceholderText(f"Pret a analyser le fichier {kind.upper()}.")

    # ────────────────────────────────────────────────────────────────────────
    # Diagnose
    # ────────────────────────────────────────────────────────────────────────

    def _on_diagnose(self) -> None:
        if not self._input_path or not self._kind:
            return
        try:
            if self._kind == "jpeg":
                report: RepairReport | Mp4RepairReport = diagnose_jpeg(self._input_path)
            else:
                report = diagnose_mp4(self._input_path)
        except OSError as exc:
            QMessageBox.critical(
                self,
                "Erreur de lecture",
                f"Impossible de lire le fichier :\n{exc}",
            )
            return

        self._render_report(report, mode="diagnosis")
        self._repair_btn.setEnabled(True)

    # ────────────────────────────────────────────────────────────────────────
    # Repair
    # ────────────────────────────────────────────────────────────────────────

    def _on_repair(self) -> None:
        if not self._input_path or not self._kind:
            return
        if self._worker is not None and self._worker.isRunning():
            return

        default_ext = ".repaired.jpg" if self._kind == "jpeg" else ".repaired.mp4"
        default_out = str(self._input_path) + default_ext
        filt = "Image JPEG (*.jpg *.jpeg)" if self._kind == "jpeg" else "Video MP4 (*.mp4 *.mov)"
        out_path, _selected = QFileDialog.getSaveFileName(
            self,
            "Enregistrer le fichier repare sous",
            default_out,
            filt,
        )
        if not out_path:
            return

        self._set_busy(True)
        self._worker = _RepairWorker(self._kind, self._input_path, out_path)
        self._worker.finished_ok.connect(self._on_repair_done)
        self._worker.failed.connect(self._on_repair_failed)
        self._worker.start()

    def _on_repair_done(self, report: object) -> None:
        self._set_busy(False)
        self._render_report(report, mode="repaired")
        QMessageBox.information(
            self,
            "Reparation terminee",
            "Le fichier a ete reconstruit. Verifiez le resultat dans une "
            "visionneuse avant de remplacer l'original.",
        )

    def _on_repair_failed(self, msg: str) -> None:
        self._set_busy(False)
        QMessageBox.critical(
            self,
            "Reparation echouee",
            f"La reparation n'a pas pu aboutir :\n{msg}",
        )

    # ────────────────────────────────────────────────────────────────────────
    # Helpers
    # ────────────────────────────────────────────────────────────────────────

    def _set_busy(self, busy: bool) -> None:
        self._progress.setVisible(busy)
        self._pick_btn.setDisabled(busy)
        self._diag_btn.setDisabled(busy)
        self._repair_btn.setDisabled(busy)
        self._close_btn.setDisabled(busy)

    def _render_report(self, report: object, *, mode: str) -> None:
        lines: list[str] = []
        if mode == "diagnosis":
            lines.append("─── Analyse ──────────────────────")
        else:
            lines.append("─── Reparation effectuee ─────────")

        original = getattr(report, "original_size", 0)
        repaired = getattr(report, "repaired_size", 0)
        lines.append(f"Taille originale : {original:,} octets")
        lines.append(f"Taille apres     : {repaired:,} octets")

        issues: list[str] = list(getattr(report, "issues_found", []) or [])
        if not issues:
            lines.append("")
            lines.append(
                f"<span style='color:{OK}'>Aucun probleme detecte. Le fichier semble valide.</span>"
            )
        else:
            lines.append("")
            lines.append(f"Problemes detectes : {len(issues)}")
            for n, issue in enumerate(issues, 1):
                lines.append(f"  {n}. {issue}")

        if mode == "repaired":
            ok = bool(getattr(report, "repaired", False))
            colour = OK if ok else ERR
            verdict = "Reparation reussie" if ok else "Reparation impossible"
            lines.append("")
            lines.append(f"<span style='color:{colour}'>{verdict}</span>")

        self._report.setHtml("<br/>".join(lines))
