"""
Lumina — Ecran 1 : Scan en cours (style Windows 98)
Barre de progression Win98, log de fichiers en temps reel,
pause / reprise / annulation, ETA, chronometre.
"""

import json
import logging
import time
from collections import deque
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QPainter
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.core.i18n import t
from app.core.recovery import ensure_lumina_log
from app.core.settings import is_demo_enabled
from app.ui.palette import (
    ACCENT as _ACCENT,
)
from app.ui.palette import (
    BEVEL_LIGHT as _BEVEL_LIGHT,
)
from app.ui.palette import (
    MUTED as _MUTED,
)
from app.ui.palette import (
    OK as _OK,
)
from app.ui.palette import (
    OK_BG as _OK_BG,
)
from app.ui.palette import (
    SUB as _SUB,
)
from app.ui.palette import (
    TEXT as _TEXT,
)
from app.ui.palette import (
    WARN as _WARN,
)
from app.workers.scan_worker import ScanWorker

_PANEL = "#F8FAFC"
_SURFACE = "#FFFFFF"
_LINE = "#D0D5DD"
_SOFT_BLUE = "#EAF2FB"
_SOFT_WARN = "#FFF4E5"
_FONT = "'Segoe UI', Arial"

# Categories de types pour le compteur live
_CAT_MAP: dict[str, set[str]] = {
    "Images":    {"JPG","JPEG","PNG","BMP","GIF","TIFF","WEBP","HEIC","HEIF","PSD","SVG",
                  "CR2","CR3","NEF","ARW","DNG","ORF","RW2","RAF","PEF","SRW","AI","EPS","INDD"},
    "Vidéos":    {"MP4","MOV","MKV","AVI","FLV","WMV","MPG","M2TS","3GP","VOB","RM","MXF","MKA"},
    "Audio":     {"MP3","WAV","FLAC","AAC","OGG","WMA","M4A","AIFF","OPUS","APE","WV"},
    "Documents": {"PDF","DOC","DOCX","XLS","XLSX","PPT","PPTX","ODT","ODS","TXT",
                  "HTML","XML","RTF","EML","PST","VCF","ICS","DWG","WMF"},
    "Archives":  {"ZIP","RAR","7Z","GZ","BZ2","XZ","TAR","ISO","EPUB","CAB","SWF"},
}

# Icones par type de fichier (ASCII-friendly)
_ICONS: dict[str, str] = {
    "JPG": "IMG", "JPEG": "IMG", "PNG": "IMG", "BMP": "IMG",
    "GIF": "IMG", "TIFF": "IMG", "WEBP": "IMG", "HEIC": "IMG", "PSD": "IMG",
    "MP4": "VID", "MOV": "VID", "MKV": "VID", "AVI": "VID",
    "FLV": "VID", "WMV": "VID", "MPG": "VID",
    "MP3": "AUD", "WAV": "AUD", "FLAC": "AUD", "AAC": "AUD", "OGG": "AUD",
    "PDF": "DOC", "DOC": "DOC", "DOCX": "DOC",
    "XLS": "XLS", "XLSX": "XLS", "PPT": "PPT", "PPTX": "PPT",
    "ZIP": "ARC", "RAR": "ARC", "7Z": "ARC", "GZ": "ARC",
    "EXE": "EXE", "DLL": "DLL", "SQLITE": "DB", "PST": "EML",
}


# ═══════════════════════════════════════════════════════════════════════════════
#  Barre de progression Win98 (segments bleus)
# ═══════════════════════════════════════════════════════════════════════════════

class _Win98ProgressBar(QWidget):
    """Barre de progression Win98 segmentee."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._value   = 0
        self._paused  = False
        self.setFixedHeight(24)
        self.setStyleSheet(
            f"background-color: {_SURFACE};"
            f"border: 1px solid {_LINE};"
            "border-radius: 3px;"
        )

    def set_value(self, v: int):
        self._value = max(0, min(100, v))
        self.update()

    def set_paused(self, v: bool):
        self._paused = v
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        w = self.width()
        h = self.height()

        p.fillRect(0, 0, w, h, QColor(_SURFACE))

        if self._value > 0:
            fill_w = int(w * self._value / 100)
            color  = QColor(_WARN) if self._paused else QColor("#1C6EAE")

            p.fillRect(1, 1, max(0, fill_w - 2), h - 2, color)
            stripe = QColor("#FFFFFF")
            stripe.setAlpha(35)
            x = 6
            while x < fill_w:
                p.fillRect(x, 1, 2, h - 2, stripe)
                x += 14

        p.end()


# ═══════════════════════════════════════════════════════════════════════════════
#  Ecran de scan Win98
# ═══════════════════════════════════════════════════════════════════════════════

ensure_lumina_log()
_log = logging.getLogger("lumina.recovery")


class ScanScreen(QWidget):
    scan_finished  = pyqtSignal(list)
    scan_cancelled = pyqtSignal()
    _MAX_LOG_ROWS = 800

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background-color: #E6E9EF;")
        self._worker: ScanWorker | None = None
        self._disk: dict = {}
        self._found_count  = 0
        self._bad_sectors  = 0
        self._start_time   = 0.0
        self._had_error    = False
        self._speed_buf: deque = deque()
        self._cat_counts: dict[str, int] = {
            "Images": 0, "Vidéos": 0, "Audio": 0,
            "Documents": 0, "Archives": 0, "Autres": 0,
        }

        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(1000)
        self._elapsed_timer.timeout.connect(self._update_elapsed)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 18, 18, 18)
        outer.setSpacing(14)

        # ── En-tete ────────────────────────────────────────────────────────────
        hdr_frame = QFrame()
        hdr_frame.setObjectName("ScanHeaderPanel")
        hdr_frame.setFixedHeight(86)
        hdr_frame.setStyleSheet(
            "QFrame#ScanHeaderPanel {"
            f"  background-color: {_PANEL};"
            f"  border: 1px solid {_LINE};"
            "  border-radius: 4px;"
            "}"
        )
        hdr_lay = QHBoxLayout(hdr_frame)
        hdr_lay.setContentsMargins(18, 12, 18, 12)
        hdr_lay.setSpacing(16)

        left_col = QVBoxLayout()
        left_col.setSpacing(6)
        self._title    = QLabel("Analyse en cours...")
        self._disk_lbl = QLabel("")
        self._title.setStyleSheet(
            f"color: {_TEXT}; font-size: 17px; font-weight: 800;"
            f"font-family: {_FONT}; background: transparent;"
        )
        self._disk_lbl.setStyleSheet(
            f"color: {_SUB}; font-size: 12px;"
            f"font-family: {_FONT}; background: transparent;"
        )
        left_col.addWidget(self._title)
        left_col.addWidget(self._disk_lbl)
        hdr_lay.addLayout(left_col)
        hdr_lay.addStretch()

        self._pause_btn = QPushButton("Pause")
        self._pause_btn.setFixedSize(96, 34)
        self._pause_btn.clicked.connect(self._on_pause)
        hdr_lay.addWidget(self._pause_btn)

        self._cancel_btn = QPushButton("Annuler")
        self._cancel_btn.setFixedSize(96, 34)
        self._cancel_btn.clicked.connect(self._on_cancel)
        hdr_lay.addSpacing(2)
        hdr_lay.addWidget(self._cancel_btn)
        outer.addWidget(hdr_frame)

        # ── Barre de progression ───────────────────────────────────────────────
        prog_frame = QFrame()
        prog_frame.setObjectName("ScanProgressPanel")
        prog_frame.setStyleSheet(
            "QFrame#ScanProgressPanel {"
            f"  background-color: {_PANEL};"
            f"  border: 1px solid {_LINE};"
            "  border-radius: 4px;"
            "}"
        )
        prog_lay = QVBoxLayout(prog_frame)
        prog_lay.setContentsMargins(14, 12, 14, 12)
        prog_lay.setSpacing(8)

        self._prog_bar = _Win98ProgressBar()
        prog_lay.addWidget(self._prog_bar)

        prog_info = QHBoxLayout()
        self._pct_lbl = QLabel("0%")
        self._pct_lbl.setStyleSheet(
            f"color: {_TEXT}; font-size: 13px; font-weight: 800; background: transparent;"
            f"font-family: {_FONT};"
        )
        self._status_lbl = QLabel("Initialisation...")
        self._status_lbl.setStyleSheet(
            f"color: {_ACCENT}; font-size: 12px; font-weight: 600; background: transparent;"
            f"font-family: {_FONT};"
        )
        self._eta_lbl = QLabel("")
        self._eta_lbl.setStyleSheet(
            f"color: {_SUB}; font-size: 12px; background: transparent;"
            f"font-family: {_FONT};"
        )
        prog_info.addWidget(self._pct_lbl)
        prog_info.addSpacing(8)
        prog_info.addWidget(self._status_lbl, stretch=1)
        prog_info.addWidget(self._eta_lbl)
        prog_lay.addLayout(prog_info)
        outer.addWidget(prog_frame)

        # ── Bouton "Lancer le Deep Scan" ───────────────────────────────────────
        self._deep_scan_btn = QPushButton("Lancer le Scan Complet")
        self._deep_scan_btn.setFixedHeight(32)
        self._deep_scan_btn.clicked.connect(self._on_switch_to_deep)
        self._deep_scan_btn.hide()
        outer.addWidget(self._deep_scan_btn)

        # ── Compteurs stats ────────────────────────────────────────────────────
        stats_frame = QFrame()
        stats_frame.setObjectName("ScanStatsPanel")
        stats_frame.setFixedHeight(58)
        stats_frame.setStyleSheet(
            "QFrame#ScanStatsPanel {"
            f"  background-color: {_PANEL};"
            f"  border: 1px solid {_LINE};"
            "  border-radius: 4px;"
            "}"
        )
        stats_row = QHBoxLayout(stats_frame)
        stats_row.setContentsMargins(14, 10, 14, 10)
        stats_row.setSpacing(10)

        self._counter_lbl = QLabel("0 fichier détecté")
        self._counter_lbl.setStyleSheet(self._metric_style(strong=True))
        self._speed_lbl = QLabel("")
        self._speed_lbl.setStyleSheet(self._metric_style())
        self._speed_lbl.hide()
        self._elapsed_lbl = QLabel("")
        self._elapsed_lbl.setStyleSheet(self._metric_style())
        self._elapsed_lbl.hide()
        self._bad_lbl = QLabel("")
        self._bad_lbl.setStyleSheet(self._metric_style(warn=True))
        self._bad_lbl.hide()

        stats_row.addWidget(self._counter_lbl)
        stats_row.addWidget(self._speed_lbl)
        stats_row.addWidget(self._elapsed_lbl)
        stats_row.addWidget(self._bad_lbl)
        stats_row.addStretch()
        outer.addWidget(stats_frame)

        # ── Compteurs par categorie ────────────────────────────────────────────
        cat_frame = QFrame()
        cat_frame.setFixedHeight(38)
        cat_frame.setStyleSheet("background-color: transparent; border: 0px;")
        cat_row = QHBoxLayout(cat_frame)
        cat_row.setContentsMargins(0, 0, 0, 0)
        cat_row.setSpacing(8)

        self._cat_lbls: dict[str, QLabel] = {}
        for cat in ("Images", "Vidéos", "Audio", "Documents", "Archives", "Autres"):
            lbl = QLabel(f"{cat}: 0")
            lbl.setStyleSheet(self._category_style(active=False))
            self._cat_lbls[cat] = lbl
            cat_row.addWidget(lbl)
        cat_row.addStretch()
        outer.addWidget(cat_frame)

        # ── Log en temps reel ──────────────────────────────────────────────────
        log_frame = QFrame()
        log_frame.setObjectName("ScanLogPanel")
        log_frame.setStyleSheet(
            "QFrame#ScanLogPanel {"
            f"  background-color: {_SURFACE};"
            f"  border: 1px solid {_LINE};"
            "  border-radius: 4px;"
            "}"
        )
        log_col = QVBoxLayout(log_frame)
        log_col.setContentsMargins(0, 0, 0, 0)
        log_col.setSpacing(0)

        # En-tete du log
        log_hdr = QWidget()
        log_hdr.setFixedHeight(38)
        log_hdr.setStyleSheet(
            f"background-color: {_ACCENT}; border: 0px; border-radius: 4px;"
        )
        hdr_l = QHBoxLayout(log_hdr)
        hdr_l.setContentsMargins(14, 0, 14, 0)
        log_title = QLabel("Fichiers détectés en temps réel")
        log_title.setStyleSheet(
            f"color: {_BEVEL_LIGHT}; font-size: 13px; font-weight: 800;"
            f"font-family: {_FONT}; background: transparent;"
        )
        hdr_l.addWidget(log_title)
        hdr_l.addStretch()
        log_col.addWidget(log_hdr)

        self._log_table = QTableWidget()
        self._log_table.setColumnCount(5)
        self._log_table.setHorizontalHeaderLabels(
            ["Type", "Nom du fichier", "Ext.", "Taille", "Statut"]
        )
        self._log_table.verticalHeader().hide()
        self._log_table.setShowGrid(False)
        self._log_table.setAlternatingRowColors(True)
        self._log_table.setWordWrap(False)
        self._log_table.setTextElideMode(Qt.TextElideMode.ElideRight)
        self._log_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self._log_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._log_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._log_table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self._log_table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerItem)
        self._log_table.setStyleSheet(
            "QTableWidget {"
            "  background-color: #FFFFFF;"
            "  alternate-background-color: #F7F9FC;"
            "  border: none;"
            "  color: #111827;"
            f"  font-family: {_FONT};"
            "  font-size: 12px;"
            "  outline: none;"
            "}"
            "QTableWidget::item {"
            "  border: none;"
            "  padding: 5px 10px;"
            "}"
            "QHeaderView::section {"
            "  background-color: #EEF2F7;"
            "  color: #243043;"
            "  border: none;"
            "  border-right: 1px solid #D0D5DD;"
            "  border-bottom: 1px solid #C4CAD4;"
            "  padding: 8px 10px;"
            f"  font-family: {_FONT};"
            "  font-size: 12px;"
            "  font-weight: 800;"
            "}"
        )
        header = self._log_table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(70)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self._log_table.verticalHeader().setDefaultSectionSize(38)
        self._table_empty_lbl = QLabel(
            "Les fichiers détectés apparaîtront ici pendant le scan.",
            self._log_table.viewport(),
        )
        self._table_empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._table_empty_lbl.setStyleSheet(
            "background-color: #FFFFFF;"
            "color: #667085;"
            f"font-family: {_FONT};"
            "font-size: 12px;"
            "font-weight: 700;"
        )
        self._update_table_empty_state()
        QTimer.singleShot(0, self._update_table_empty_state)
        log_col.addWidget(self._log_table, stretch=1)

        outer.addWidget(log_frame, stretch=1)

    # ── API publique ──────────────────────────────────────────────────────────

    @staticmethod
    def _metric_style(*, strong: bool = False, warn: bool = False) -> str:
        color = _WARN if warn else (_ACCENT if strong else _SUB)
        weight = "800" if strong else "600"
        bg = _SOFT_WARN if warn else (_SOFT_BLUE if strong else "#FFFFFF")
        return (
            f"color: {color};"
            f"background-color: {bg};"
            f"border: 1px solid {_LINE};"
            "border-radius: 4px;"
            "padding: 6px 10px;"
            f"font-size: 12px; font-weight: {weight};"
            f"font-family: {_FONT};"
        )

    @staticmethod
    def _category_style(*, active: bool) -> str:
        color = _ACCENT if active else _MUTED
        bg = _SOFT_BLUE if active else "#FFFFFF"
        border = "#BFD2EA" if active else _LINE
        weight = "800" if active else "600"
        return (
            f"color: {color};"
            f"background-color: {bg};"
            f"border: 1px solid {border};"
            "border-radius: 4px;"
            "padding: 5px 9px;"
            f"font-size: 12px; font-weight: {weight};"
            f"font-family: {_FONT};"
        )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._position_table_empty_state()

    def _position_table_empty_state(self) -> None:
        if hasattr(self, "_table_empty_lbl"):
            self._table_empty_lbl.setGeometry(self._log_table.viewport().rect())

    def _update_table_empty_state(self) -> None:
        self._position_table_empty_state()
        is_empty = self._log_table.rowCount() == 0
        self._table_empty_lbl.setVisible(is_empty)
        if is_empty:
            self._table_empty_lbl.raise_()

    def start_scan(self, disk: dict):
        self._disk        = disk
        self._found_count = 0
        self._bad_sectors = 0
        self._start_time  = time.monotonic()
        self._had_error   = False
        self._speed_buf.clear()
        self._log_table.setRowCount(0)
        self._update_table_empty_state()
        self._deep_scan_btn.hide()
        self._cat_counts = {k: 0 for k in self._cat_counts}
        for cat, lbl in self._cat_lbls.items():
            lbl.setText(f"{cat}: 0")
            lbl.setStyleSheet(self._category_style(active=False))

        self._prog_bar.set_value(0)
        self._prog_bar.set_paused(False)
        self._pct_lbl.setText("0%")

        self._status_lbl.setText("Initialisation...")
        self._counter_lbl.setText("0 fichier détecté")
        self._eta_lbl.setText("")
        self._speed_lbl.setText("")
        self._speed_lbl.hide()
        self._elapsed_lbl.setText("")
        self._elapsed_lbl.hide()
        self._bad_lbl.setText("")
        self._bad_lbl.hide()
        self._cancel_btn.setEnabled(True)
        self._pause_btn.setEnabled(True)
        self._pause_btn.setText("Pause")

        mode = disk.get("scan_mode", "deep")
        mode_lbl = "Scan rapide" if mode == "quick" else "Scan complet"
        self._title.setText(f"{mode_lbl} en cours...")
        dev  = disk.get("device", "")
        size = disk.get("size_gb", 0)
        self._disk_lbl.setText(f"{dev}  |  {size} Go  |  {mode_lbl}")

        if self._worker:
            self._detach_worker(self._worker)
            self._worker = None

        if mode == "demo" and not is_demo_enabled():
            self._on_error(t("scan.demo_disabled"))
            self._cancel_btn.setEnabled(False)
            self._pause_btn.setEnabled(False)
            return

        preloaded: list[dict] = []
        if mode == "deep":
            preloaded = self._maybe_resume_checkpoint(disk)

        simulate = mode == "demo" and is_demo_enabled()
        self._worker = ScanWorker(
            disk,
            simulate=simulate,
            preloaded_files=preloaded if preloaded else None,
        )
        self._worker.progress.connect(self._on_progress)
        self._worker.status_text.connect(self._on_status)
        self._worker.files_batch_found.connect(self._on_batch)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.start()
        self._elapsed_timer.start()

    # ── Checkpoint resume ─────────────────────────────────────────────────────

    def _maybe_resume_checkpoint(self, disk: dict) -> list[dict]:
        checkpoint_path = Path("logs") / "scan_checkpoint.json"
        if not checkpoint_path.exists():
            return []
        try:
            raw = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            files = raw if isinstance(raw, list) else raw.get("files", [])
            if not files:
                return []
            if files[0].get("device", "") != disk.get("device", ""):
                return []
            file_count = len(files)
        except Exception:
            return []

        dlg = QMessageBox(self)
        dlg.setWindowTitle("Scan interrompu détecté")
        dlg.setText(
            f"Un scan précédent sur {disk.get('device', '?')} a été interrompu.\n"
            f"{file_count} fichier(s) avaient déjà été trouvés.\n\n"
            "Reprendre à partir de ces résultats partiels ?"
        )
        dlg.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        dlg.setDefaultButton(QMessageBox.StandardButton.Yes)
        if dlg.exec() != QMessageBox.StandardButton.Yes:
            return []

        self._found_count = file_count
        plural = "s" if file_count > 1 else ""
        self._counter_lbl.setText(
            f"{file_count} fichier{plural} préchargé{plural} (reprise)"
        )
        _log.info(
            "Checkpoint resume: %d files pre-loaded from %s",
            file_count, checkpoint_path,
        )
        return files

    # ── Slots du worker ───────────────────────────────────────────────────────

    def _on_progress(self, pct: int):
        self._prog_bar.set_value(pct)
        self._pct_lbl.setText(f"{pct}%")
        self._update_eta(pct)

    def _on_status(self, text: str):
        self._status_lbl.setText(text)
        txt_low = text.lower()
        if "illisible" in txt_low or "sector" in txt_low or "bad" in txt_low:
            self._bad_sectors += 1
            self._bad_lbl.setText(f"Secteurs: {self._bad_sectors} illisible(s)")
            self._bad_lbl.show()
        if text in (t("scan.quick_unavailable"), t("scan.quick_few_results")):
            device = self._disk.get("device", "?")
            _log.info(
                "Quick Scan insuffisant sur %s, proposition Deep Scan affichee.", device
            )
            self._deep_scan_btn.show()

    def _on_batch(self, batch: list):
        self._found_count += len(batch)
        plural = "s" if self._found_count > 1 else ""
        self._counter_lbl.setText(
            f"{self._found_count} fichier{plural} détecté{plural}"
        )

        for info in batch:
            ftype = info.get("type", "").upper()
            cat = "Autres"
            for c, types in _CAT_MAP.items():
                if ftype in types:
                    cat = c
                    break
            self._cat_counts[cat] = self._cat_counts.get(cat, 0) + 1

        for cat, lbl in self._cat_lbls.items():
            n = self._cat_counts.get(cat, 0)
            if n > 0:
                lbl.setText(f"{cat}: {n}")
                lbl.setStyleSheet(self._category_style(active=True))

        for info in batch:
            ext        = info.get("type", "???").upper()
            name       = info.get("name", "inconnu")
            size_kb    = info.get("size_kb", 0)
            integrity  = info.get("integrity", 60)
            size_str   = (
                f"{size_kb / 1024:.1f} Mo" if size_kb >= 1024
                else f"{size_kb} Ko" if size_kb else "-"
            )
            icon = _ICONS.get(ext, "FIL")
            self._append_log_row(icon, name, ext, size_str, integrity)

        while self._log_table.rowCount() > self._MAX_LOG_ROWS:
            self._log_table.removeRow(0)

        self._update_table_empty_state()
        self._log_table.scrollToBottom()

    def _append_log_row(
        self,
        icon: str,
        name: str,
        ext: str,
        size_str: str,
        integrity: int,
    ) -> None:
        row = self._log_table.rowCount()
        self._log_table.insertRow(row)
        self._log_table.setRowHeight(row, 38)

        badge = QLabel(icon)
        badge.setFixedSize(46, 22)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setToolTip(ext)
        badge.setStyleSheet(
            f"color: {_ACCENT}; background-color: {_SOFT_BLUE};"
            "font-size: 10px; font-weight: 800;"
            f"font-family: {_FONT};"
            "border: 1px solid #BFD2EA;"
            "border-radius: 4px; padding: 2px 6px;"
        )
        badge_wrap = QWidget()
        badge_lay = QHBoxLayout(badge_wrap)
        badge_lay.setContentsMargins(6, 4, 6, 4)
        badge_lay.setSpacing(0)
        badge_lay.addWidget(badge)
        self._log_table.setCellWidget(row, 0, badge_wrap)

        name_item = self._table_item(name, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        name_item.setToolTip(name)
        self._log_table.setItem(row, 1, name_item)

        ext_item = self._table_item(ext or "-", Qt.AlignmentFlag.AlignCenter)
        ext_item.setToolTip(ext or "Extension inconnue")
        self._log_table.setItem(row, 2, ext_item)

        size_item = self._table_item(
            size_str,
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
        )
        self._log_table.setItem(row, 3, size_item)

        status_text, status_color, status_bg = self._status_for_integrity(integrity)
        status_item = self._table_item(
            status_text,
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
        )
        status_item.setForeground(QBrush(QColor(status_color)))
        status_item.setToolTip(f"Intégrité estimée : {integrity}%")
        self._log_table.setItem(row, 4, status_item)

        status_badge = QLabel(status_text)
        status_badge.setFixedSize(68, 22)
        status_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        status_badge.setToolTip(f"Intégrité estimée : {integrity}%")
        status_badge.setStyleSheet(
            f"color: {status_color};"
            f"background-color: {status_bg};"
            "border: 1px solid rgba(0, 0, 0, 0.10);"
            "border-radius: 4px;"
            "font-size: 11px; font-weight: 800;"
            f"font-family: {_FONT};"
        )
        status_wrap = QWidget()
        status_lay = QHBoxLayout(status_wrap)
        status_lay.setContentsMargins(4, 4, 10, 4)
        status_lay.addStretch()
        status_lay.addWidget(status_badge)
        self._log_table.setCellWidget(row, 4, status_wrap)
        self._update_table_empty_state()

    @staticmethod
    def _table_item(text: str, alignment: Qt.AlignmentFlag) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        item.setTextAlignment(alignment)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        return item

    @staticmethod
    def _status_for_integrity(integrity: int) -> tuple[str, str, str]:
        if integrity >= 90:
            return "OK", _OK, _OK_BG
        if integrity >= 60:
            return "Partiel", _ACCENT, _SOFT_BLUE
        return "Fragile", _WARN, _SOFT_WARN

    def _on_finished(self, files: list):
        self._elapsed_timer.stop()
        self._prog_bar.set_value(100)
        self._pct_lbl.setText("100%")
        self._cancel_btn.setEnabled(False)
        self._pause_btn.setEnabled(False)
        if not self._had_error:
            self._title.setText("Analyse terminée")
        self._eta_lbl.setText("")
        self.scan_finished.emit(files)

    def _on_error(self, msg: str):
        self._had_error = True
        self._elapsed_timer.stop()
        self._status_lbl.setText(f"Erreur : {msg}")
        self._title.setText("Erreur d'analyse")
        self._eta_lbl.setText("")
        self._cancel_btn.setEnabled(False)
        self._pause_btn.setEnabled(False)

    # ── Controles pause / annuler ─────────────────────────────────────────────

    def _on_pause(self):
        if not self._worker:
            return
        if self._worker.is_paused():
            self._worker.resume()
            self._prog_bar.set_paused(False)
            self._pause_btn.setText("Pause")
            self._elapsed_timer.start()
        else:
            self._worker.pause()
            self._prog_bar.set_paused(True)
            self._pause_btn.setText("Reprendre")
            self._elapsed_timer.stop()

    def _on_switch_to_deep(self):
        self._disk["scan_mode"] = "deep"
        self._deep_scan_btn.hide()
        self.start_scan(self._disk)

    def _on_cancel(self):
        self._elapsed_timer.stop()
        self._prog_bar.set_paused(False)
        self._eta_lbl.setText("")
        if self._worker:
            self._detach_worker(self._worker)
            self._worker = None
        self.scan_cancelled.emit()

    # ── Deconnexion propre sans bloquer l'UI ─────────────────────────────────

    def is_scanning(self) -> bool:
        return self._worker is not None and self._worker.isRunning()

    @staticmethod
    def _detach_worker(worker):
        try:
            worker.progress.disconnect()
            worker.status_text.disconnect()
            worker.files_batch_found.disconnect()
            worker.finished.disconnect()
            worker.error.disconnect()
        except RuntimeError:
            pass
        worker.stop()
        if worker.isRunning():
            worker.finished.connect(worker.deleteLater)
        else:
            worker.deleteLater()

    # ── ETA + chronometre ─────────────────────────────────────────────────────

    def _update_elapsed(self):
        elapsed = int(time.monotonic() - self._start_time)
        self._elapsed_lbl.show()
        if elapsed < 60:
            self._elapsed_lbl.setText(f"Durée: {elapsed}s")
        else:
            m, s = divmod(elapsed, 60)
            self._elapsed_lbl.setText(f"Durée: {m}m{s:02d}s")

    def _update_eta(self, pct: int):
        now = time.monotonic()
        self._speed_buf.append((now, pct))
        cutoff = now - 12.0
        while self._speed_buf and self._speed_buf[0][0] < cutoff:
            self._speed_buf.popleft()

        if pct >= 100:
            self._eta_lbl.setText("Finalisation...")
            return
        if len(self._speed_buf) < 3 or pct <= 0:
            return

        t0, p0 = self._speed_buf[0]
        t1, p1 = self._speed_buf[-1]
        dt = t1 - t0
        if dt < 1.0 or p1 <= p0:
            return

        speed = (p1 - p0) / dt
        remaining = 100 - p1
        if speed > 0 and remaining > 0:
            eta_s = int(remaining / speed)
            if eta_s < 86400:
                self._eta_lbl.setText(self._fmt_eta(eta_s))
        self._speed_lbl.show()
        self._speed_lbl.setText(f"{speed:.1f}%/s")

    @staticmethod
    def _fmt_eta(seconds: int) -> str:
        if seconds < 60:
            return f"Reste: {seconds}s"
        if seconds < 3600:
            m, s = divmod(seconds, 60)
            return f"Reste: {m}min{s:02d}s"
        h, rem = divmod(seconds, 3600)
        return f"Reste: {h}h{rem // 60:02d}min"
