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
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.core.i18n import t
from app.core.recovery import ensure_lumina_log
from app.core.settings import is_demo_enabled
from app.workers.scan_worker import ScanWorker
from app.ui.palette import (
    ACCENT as _ACCENT,
    BEVEL_INSET_LIGHT as _BEVEL_INSET_LIGHT,
    BEVEL_INSET_SHADOW as _BEVEL_INSET_SHADOW,
    BEVEL_LIGHT as _BEVEL_LIGHT,
    BEVEL_SHADOW as _BEVEL_SHADOW,
    CARD as _CARD,
    MUTED as _MUTED,
    OK as _OK,
    SUB as _SUB,
    TEXT as _TEXT,
    WARN as _WARN,
)

# Categories de types pour le compteur live
_CAT_MAP: dict[str, set[str]] = {
    "Images":    {"JPG","JPEG","PNG","BMP","GIF","TIFF","WEBP","HEIC","HEIF","PSD","SVG",
                  "CR2","CR3","NEF","ARW","DNG","ORF","RW2","RAF","PEF","SRW","AI","EPS","INDD"},
    "Videos":    {"MP4","MOV","MKV","AVI","FLV","WMV","MPG","M2TS","3GP","VOB","RM","MXF","MKA"},
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
        self.setFixedHeight(28)
        self.setStyleSheet(
            f"background-color: {_BEVEL_LIGHT};"
            f"border-top: 2px solid {_BEVEL_INSET_LIGHT};"
            f"border-left: 2px solid {_BEVEL_INSET_LIGHT};"
            f"border-bottom: 2px solid {_BEVEL_INSET_SHADOW};"
            f"border-right: 2px solid {_BEVEL_INSET_SHADOW};"
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

        # Background
        p.fillRect(0, 0, w, h, QColor(_BEVEL_LIGHT))

        if self._value > 0:
            fill_w = int(w * self._value / 100)
            color  = QColor(_WARN) if self._paused else QColor(_ACCENT)

            # Draw segments (each segment is 8px wide with 1px gap)
            seg_w = 10
            x = 0
            while x < fill_w:
                sw = min(seg_w - 1, fill_w - x)
                p.fillRect(x, 1, sw, h - 2, color)
                x += seg_w

        p.end()


# ═══════════════════════════════════════════════════════════════════════════════
#  Ligne du log de fichier
# ═══════════════════════════════════════════════════════════════════════════════

class _FileRow(QWidget):
    def __init__(self, icon: str, name: str, meta: str, integrity: int, parent=None):
        super().__init__(parent)
        self.setFixedHeight(20)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 0, 4, 0)
        lay.setSpacing(8)

        ico = QLabel(f"[{icon}]")
        ico.setFixedWidth(36)
        ico.setStyleSheet(
            f"color: {_ACCENT}; font-size: 9px; font-weight: 700;"
            "background: transparent; font-family: 'Work Sans', Arial;"
        )

        nam = QLabel(name)
        nam.setStyleSheet(
            f"color: {_TEXT}; font-size: 10px;"
            "font-family: 'Work Sans', Arial; background: transparent;"
        )

        meta_lbl = QLabel(meta)
        meta_lbl.setStyleSheet(
            f"color: {_SUB}; font-size: 10px;"
            "font-family: 'Work Sans', Arial; background: transparent;"
        )

        if integrity >= 90:
            sc, st = _OK, "OK"
        elif integrity >= 60:
            sc, st = _ACCENT, "Partiel"
        else:
            sc, st = _WARN, "Degrade"

        status = QLabel(st)
        status.setFixedWidth(46)
        status.setAlignment(Qt.AlignmentFlag.AlignRight)
        status.setStyleSheet(
            f"color: {sc}; font-size: 10px; font-weight: 700;"
            "font-family: 'Work Sans', Arial; background: transparent;"
        )

        lay.addWidget(ico)
        lay.addWidget(nam, stretch=1)
        lay.addWidget(meta_lbl)
        lay.addWidget(status)

        self.setStyleSheet("QWidget { background: transparent; }")


# ═══════════════════════════════════════════════════════════════════════════════
#  Ecran de scan Win98
# ═══════════════════════════════════════════════════════════════════════════════

ensure_lumina_log()
_log = logging.getLogger("lumina.recovery")


class ScanScreen(QWidget):
    scan_finished  = pyqtSignal(list)
    scan_cancelled = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background-color: {_CARD};")
        self._worker: ScanWorker | None = None
        self._disk: dict = {}
        self._found_count  = 0
        self._bad_sectors  = 0
        self._start_time   = 0.0
        self._had_error    = False
        self._speed_buf: deque = deque()
        self._cat_counts: dict[str, int] = {
            "Images": 0, "Videos": 0, "Audio": 0,
            "Documents": 0, "Archives": 0, "Autres": 0,
        }

        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(1000)
        self._elapsed_timer.timeout.connect(self._update_elapsed)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(6)

        # ── En-tete ────────────────────────────────────────────────────────────
        hdr_frame = QFrame()
        hdr_frame.setFixedHeight(50)
        hdr_frame.setStyleSheet(
            f"QFrame {{"
            f"  background-color: {_CARD};"
            f"  border-top: 2px solid {_BEVEL_LIGHT};"
            f"  border-left: 2px solid {_BEVEL_LIGHT};"
            f"  border-bottom: 2px solid {_BEVEL_SHADOW};"
            f"  border-right: 2px solid {_BEVEL_SHADOW};"
            f"}}"
        )
        hdr_lay = QHBoxLayout(hdr_frame)
        hdr_lay.setContentsMargins(8, 4, 8, 4)

        left_col = QVBoxLayout()
        left_col.setSpacing(2)
        self._title    = QLabel("Analyse en cours...")
        self._disk_lbl = QLabel("")
        self._title.setStyleSheet(
            f"color: {_TEXT}; font-size: 12px; font-weight: 700;"
            "font-family: 'Work Sans', Arial; background: transparent;"
        )
        self._disk_lbl.setStyleSheet(
            f"color: {_SUB}; font-size: 10px;"
            "font-family: 'Work Sans', Arial; background: transparent;"
        )
        left_col.addWidget(self._title)
        left_col.addWidget(self._disk_lbl)
        hdr_lay.addLayout(left_col)
        hdr_lay.addStretch()

        self._pause_btn = QPushButton("Pause")
        self._pause_btn.setFixedSize(70, 24)
        self._pause_btn.clicked.connect(self._on_pause)
        hdr_lay.addWidget(self._pause_btn)

        self._cancel_btn = QPushButton("Annuler")
        self._cancel_btn.setFixedSize(70, 24)
        self._cancel_btn.clicked.connect(self._on_cancel)
        hdr_lay.addSpacing(4)
        hdr_lay.addWidget(self._cancel_btn)
        outer.addWidget(hdr_frame)

        # ── Barre de progression ───────────────────────────────────────────────
        prog_frame = QFrame()
        prog_frame.setStyleSheet(f"QFrame {{ background-color: {_CARD}; border: 0px; }}")
        prog_lay = QVBoxLayout(prog_frame)
        prog_lay.setContentsMargins(0, 0, 0, 0)
        prog_lay.setSpacing(4)

        self._prog_bar = _Win98ProgressBar()
        prog_lay.addWidget(self._prog_bar)

        prog_info = QHBoxLayout()
        self._pct_lbl = QLabel("0%")
        self._pct_lbl.setStyleSheet(
            f"color: {_TEXT}; font-size: 11px; font-weight: 700; background: transparent;"
            "font-family: 'Work Sans', Arial;"
        )
        self._status_lbl = QLabel("Initialisation...")
        self._status_lbl.setStyleSheet(
            f"color: {_ACCENT}; font-size: 10px; background: transparent;"
            "font-family: 'Work Sans', Arial;"
        )
        self._eta_lbl = QLabel("")
        self._eta_lbl.setStyleSheet(
            f"color: {_SUB}; font-size: 10px; background: transparent;"
            "font-family: 'Work Sans', Arial;"
        )
        prog_info.addWidget(self._pct_lbl)
        prog_info.addSpacing(8)
        prog_info.addWidget(self._status_lbl, stretch=1)
        prog_info.addWidget(self._eta_lbl)
        prog_lay.addLayout(prog_info)
        outer.addWidget(prog_frame)

        # ── Bouton "Lancer le Deep Scan" ───────────────────────────────────────
        self._deep_scan_btn = QPushButton("Lancer le Scan Complet")
        self._deep_scan_btn.setFixedHeight(24)
        self._deep_scan_btn.clicked.connect(self._on_switch_to_deep)
        self._deep_scan_btn.hide()
        outer.addWidget(self._deep_scan_btn)

        # ── Compteurs stats ────────────────────────────────────────────────────
        stats_frame = QFrame()
        stats_frame.setFixedHeight(28)
        stats_frame.setStyleSheet(
            f"QFrame {{"
            f"  background-color: {_BEVEL_LIGHT};"
            f"  border-top: 2px solid {_BEVEL_INSET_LIGHT};"
            f"  border-left: 2px solid {_BEVEL_INSET_LIGHT};"
            f"  border-bottom: 2px solid {_BEVEL_INSET_SHADOW};"
            f"  border-right: 2px solid {_BEVEL_INSET_SHADOW};"
            f"}}"
        )
        stats_row = QHBoxLayout(stats_frame)
        stats_row.setContentsMargins(6, 0, 6, 0)
        stats_row.setSpacing(16)

        self._counter_lbl = QLabel("0 fichier detecte")
        self._counter_lbl.setStyleSheet(
            f"color: {_ACCENT}; font-size: 10px; font-weight: 700; background: transparent;"
            "font-family: 'Work Sans', Arial;"
        )
        self._speed_lbl = QLabel("")
        self._speed_lbl.setStyleSheet(
            f"color: {_SUB}; font-size: 10px; background: transparent;"
            "font-family: 'Work Sans', Arial;"
        )
        self._elapsed_lbl = QLabel("")
        self._elapsed_lbl.setStyleSheet(
            f"color: {_SUB}; font-size: 10px; background: transparent;"
            "font-family: 'Work Sans', Arial;"
        )
        self._bad_lbl = QLabel("")
        self._bad_lbl.setStyleSheet(
            f"color: {_WARN}; font-size: 10px; background: transparent;"
            "font-family: 'Work Sans', Arial;"
        )

        stats_row.addWidget(self._counter_lbl)
        stats_row.addWidget(self._speed_lbl)
        stats_row.addWidget(self._elapsed_lbl)
        stats_row.addWidget(self._bad_lbl)
        stats_row.addStretch()
        outer.addWidget(stats_frame)

        # ── Compteurs par categorie ────────────────────────────────────────────
        cat_frame = QFrame()
        cat_frame.setFixedHeight(22)
        cat_frame.setStyleSheet(f"QFrame {{ background-color: {_CARD}; border: 0px; }}")
        cat_row = QHBoxLayout(cat_frame)
        cat_row.setContentsMargins(0, 0, 0, 0)
        cat_row.setSpacing(12)

        self._cat_lbls: dict[str, QLabel] = {}
        for cat in ("Images", "Videos", "Audio", "Documents", "Archives", "Autres"):
            lbl = QLabel(f"{cat}: 0")
            lbl.setStyleSheet(
                f"color: {_MUTED}; font-size: 10px; background: transparent;"
                "font-family: 'Work Sans', Arial;"
            )
            self._cat_lbls[cat] = lbl
            cat_row.addWidget(lbl)
        cat_row.addStretch()
        outer.addWidget(cat_frame)

        # ── Log en temps reel ──────────────────────────────────────────────────
        log_frame = QFrame()
        log_frame.setStyleSheet(
            f"QFrame {{"
            f"  background-color: {_BEVEL_LIGHT};"
            f"  border-top: 2px solid {_BEVEL_INSET_LIGHT};"
            f"  border-left: 2px solid {_BEVEL_INSET_LIGHT};"
            f"  border-bottom: 2px solid {_BEVEL_INSET_SHADOW};"
            f"  border-right: 2px solid {_BEVEL_INSET_SHADOW};"
            f"}}"
        )
        log_col = QVBoxLayout(log_frame)
        log_col.setContentsMargins(0, 0, 0, 0)
        log_col.setSpacing(0)

        # En-tete du log
        log_hdr = QWidget()
        log_hdr.setFixedHeight(20)
        log_hdr.setStyleSheet(
            f"background-color: {_ACCENT}; border: 0px;"
        )
        hdr_l = QHBoxLayout(log_hdr)
        hdr_l.setContentsMargins(6, 0, 6, 0)
        log_title = QLabel("Fichiers detectes en temps reel")
        log_title.setStyleSheet(
            f"color: {_BEVEL_LIGHT}; font-size: 10px; font-weight: 700;"
            "font-family: 'Work Sans', Arial; background: transparent;"
        )
        hdr_l.addWidget(log_title)
        hdr_l.addStretch()
        log_col.addWidget(log_hdr)

        self._log_list = QListWidget()
        self._log_list.setStyleSheet(
            "QListWidget {"
            "  background-color: #FFFFFF; border: none; outline: none;"
            "  font-family: 'Work Sans', Arial;"
            "}"
            "QListWidget::item { background: transparent; border: 0px; }"
            "QListWidget::item:selected { background-color: #000080; color: #FFFFFF; }"
        )
        self._log_list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        log_col.addWidget(self._log_list, stretch=1)

        outer.addWidget(log_frame, stretch=1)

    # ── API publique ──────────────────────────────────────────────────────────

    def start_scan(self, disk: dict):
        self._disk        = disk
        self._found_count = 0
        self._bad_sectors = 0
        self._start_time  = time.monotonic()
        self._had_error   = False
        self._speed_buf.clear()
        self._log_list.clear()
        self._deep_scan_btn.hide()
        self._cat_counts = {k: 0 for k in self._cat_counts}
        for cat, lbl in self._cat_lbls.items():
            lbl.setText(f"{cat}: 0")
            lbl.setStyleSheet(
                f"color: {_MUTED}; font-size: 10px; background: transparent;"
                "font-family: 'Work Sans', Arial;"
            )

        self._prog_bar.set_value(0)
        self._prog_bar.set_paused(False)
        self._pct_lbl.setText("0%")

        self._status_lbl.setText("Initialisation...")
        self._counter_lbl.setText("0 fichier detecte")
        self._eta_lbl.setText("")
        self._speed_lbl.setText("")
        self._elapsed_lbl.setText("")
        self._bad_lbl.setText("")
        self._cancel_btn.setEnabled(True)
        self._pause_btn.setEnabled(True)
        self._pause_btn.setText("Pause")

        mode = disk.get("scan_mode", "deep")
        mode_lbl = "Scan Rapide" if mode == "quick" else "Scan Complet"
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
        dlg.setWindowTitle("Scan interrompu detecte")
        dlg.setText(
            f"Un scan precedent sur {disk.get('device', '?')} a ete interrompu.\n"
            f"{file_count} fichier(s) avaient deja ete trouves.\n\n"
            "Reprendre a partir de ces resultats partiels ?"
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
            f"{file_count} fichier{plural} pre-charge{plural} (reprise)"
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
            f"{self._found_count} fichier{plural} detecte{plural}"
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
                lbl.setStyleSheet(
                    "color: #000080; font-size: 10px; font-weight: 700; background: transparent;"
                    "font-family: 'Work Sans', Arial;"
                )

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
            meta = f"{ext} | {size_str}"

            item = QListWidgetItem(self._log_list)
            row  = _FileRow(icon, name, meta, integrity)
            item.setSizeHint(row.sizeHint())
            self._log_list.addItem(item)
            self._log_list.setItemWidget(item, row)

        while self._log_list.count() > 800:
            self._log_list.takeItem(0)

        self._log_list.scrollToBottom()

    def _on_finished(self, files: list):
        if self._had_error:
            return
        self._elapsed_timer.stop()
        self._prog_bar.set_value(100)
        self._pct_lbl.setText("100%")
        self._cancel_btn.setEnabled(False)
        self._pause_btn.setEnabled(False)
        self._title.setText("Analyse terminee")
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
        worker.finished.connect(worker.deleteLater)

    # ── ETA + chronometre ─────────────────────────────────────────────────────

    def _update_elapsed(self):
        elapsed = int(time.monotonic() - self._start_time)
        if elapsed < 60:
            self._elapsed_lbl.setText(f"Duree: {elapsed}s")
        else:
            m, s = divmod(elapsed, 60)
            self._elapsed_lbl.setText(f"Duree: {m}m{s:02d}s")

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
