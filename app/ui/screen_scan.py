"""
Lumina v2.0 — Écran 1 : Scan en cours
Anneau circulaire de progression, log de fichiers en temps réel,
pause / reprise / annulation, ETA, chronomètre.
"""

import math
import random
import time
from collections import deque

from PyQt6.QtCore import Qt, QPointF, QRectF, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QBrush, QColor, QConicalGradient, QCursor, QFont, QPainter, QPen,
)
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QPushButton, QVBoxLayout, QWidget,
)

from app.core.i18n import t
from app.core.settings import is_demo_enabled
from app.workers.scan_worker import ScanWorker

from app.ui.palette import (
    ACCENT as _ACCENT,
    ACCENT2 as _ACCENT2,
    BORDER as _BORDER,
    CARD as _CARD,
    ERR as _ERR,
    HOVER as _HOVER,
    MUTED as _MUTED,
    OK as _OK,
    OK_BG as _OK_BG,
    SUB as _SUB,
    TEXT as _TEXT,
    WARN as _WARN,
)

# Icônes par type de fichier
_ICONS: dict[str, str] = {
    "JPG": "🖼", "JPEG": "🖼", "PNG": "🎨", "BMP": "🖼",
    "GIF": "🎭", "TIFF": "📷", "WEBP": "🖼", "HEIC": "📱", "PSD": "🎨",
    "MP4": "🎬", "MOV": "🎬", "MKV": "🎬", "AVI": "🎬",
    "FLV": "🎬", "WMV": "🎬", "MPG": "🎬",
    "MP3": "🎵", "WAV": "🎵", "FLAC": "🎵", "AAC": "🎵", "OGG": "🎵",
    "PDF": "📄", "DOC": "📝", "DOCX": "📝",
    "XLS": "📊", "XLSX": "📊", "PPT": "📋", "PPTX": "📋",
    "ZIP": "📦", "RAR": "📦", "7Z": "📦", "GZ": "📦",
    "EXE": "⚙", "DLL": "⚙", "SQLITE": "🗄", "PST": "📧",
}


# ═══════════════════════════════════════════════════════════════════════════════
#  Anneau de progression circulaire
# ═══════════════════════════════════════════════════════════════════════════════

class CircularProgress(QWidget):
    DIAMETER = 210
    RING_W   = 14

    def __init__(self, parent=None):
        super().__init__(parent)
        self._value       = 0
        self._active      = False
        self._paused      = False
        self._pulse       = 0
        self._particles: list[dict] = []

        self.setFixedSize(self.DIAMETER, self.DIAMETER)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self._timer = QTimer(self)
        self._timer.setInterval(33)   # ~30 fps
        self._timer.timeout.connect(self._tick)

    def setValue(self, v: int):
        self._value = max(0, min(100, v))
        self.update()

    def setActive(self, v: bool):
        self._active = v
        if v:
            self._timer.start()
        else:
            self._timer.stop()
            self._particles.clear()
        self.update()

    def setPaused(self, v: bool):
        self._paused = v
        self.update()

    def _tick(self):
        self._pulse = (self._pulse + 2) % 360

        # Générer des particules au bout de l'arc
        if self._active and not self._paused and self._value > 0:
            tip_deg = 90.0 - self._value * 3.6
            tip_rad = math.radians(tip_deg)
            r_mid   = self.DIAMETER / 2 - self.RING_W / 2 - 4
            cx = cy = self.DIAMETER / 2.0
            sx = cx + r_mid * math.cos(tip_rad)
            sy = cy - r_mid * math.sin(tip_rad)
            if random.random() < 0.35:
                angle = math.radians(tip_deg + random.uniform(-20, 20))
                spd   = random.uniform(0.4, 1.5)
                self._particles.append({
                    "x": sx, "y": sy,
                    "vx": spd * math.cos(angle),
                    "vy": -spd * math.sin(angle),
                    "alpha": random.randint(130, 210),
                    "size":  random.uniform(1.8, 4.0),
                    "color": random.choice((_ACCENT, _ACCENT2, "#BFD7FF")),
                })

        # Mettre à jour les particules
        for pt in self._particles:
            pt["x"]     += pt["vx"]
            pt["y"]     += pt["vy"]
            pt["alpha"] -= 7
        self._particles = [pt for pt in self._particles if pt["alpha"] > 0]
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        d   = self.DIAMETER
        rw  = self.RING_W
        pad = rw // 2 + 6
        arc = QRectF(pad, pad, d - 2 * pad, d - 2 * pad)
        cx  = cy = d / 2.0

        # Fond intérieur
        p.setBrush(QBrush(QColor(10, 10, 22)))
        p.setPen(Qt.PenStyle.NoPen)
        inner_r = d / 2 - rw - 8
        p.drawEllipse(QPointF(cx, cy), inner_r, inner_r)

        # Piste de fond
        p.setPen(QPen(QColor(255, 255, 255, 14), rw,
                      Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawArc(arc, 0, 360 * 16)

        ring_col = _WARN if self._paused else _ACCENT

        # Lueur (glow) si actif
        if self._active and self._value > 0:
            pa = int(6 + 5 * math.sin(math.radians(self._pulse)))
            for grw, ga in ((rw + 16, pa), (rw + 7, pa * 2)):
                gpen = QPen(QColor(ring_col), grw,
                            Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
                gpen.setColor(QColor(ring_col))
                p.setPen(gpen)
                p.drawArc(arc, 90 * 16, int(-self._value * 360 * 16 / 100))

        # Arc principal avec dégradé conique
        if self._value > 0:
            c1 = QColor(_WARN if self._paused else _ACCENT)
            c2 = QColor("#D97706" if self._paused else _ACCENT2)
            cg = QConicalGradient(cx, cy, 90)
            cg.setColorAt(0.00, c1)
            cg.setColorAt(0.50, c2)
            cg.setColorAt(1.00, c1)
            p.setPen(QPen(QBrush(cg), rw,
                          Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawArc(arc, 90 * 16, int(-self._value * 360 * 16 / 100))

        # Particules
        p.setPen(Qt.PenStyle.NoPen)
        for pt in self._particles:
            col = QColor(pt["color"])
            col.setAlpha(int(pt["alpha"]))
            p.setBrush(QBrush(col))
            sz = pt["size"]
            p.drawEllipse(QPointF(pt["x"], pt["y"]), sz / 2, sz / 2)

        # Pourcentage centré
        p.setPen(QColor(_TEXT))
        p.setFont(QFont("Inter", 36, QFont.Weight.Bold))
        p.drawText(QRectF(0, cy - 36, d, 42), Qt.AlignmentFlag.AlignCenter, str(self._value))

        # Signe « % »
        fm   = p.fontMetrics()
        tw   = fm.horizontalAdvance(str(self._value))
        p.setFont(QFont("Inter", 15, QFont.Weight.Bold))
        p.setPen(QColor(0, 122, 255, 200))
        p.drawText(
            QRectF(cx + tw / 2 + 2, cy - 26, 28, 28),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            "%",
        )

        # Label sous le chiffre
        label = "EN PAUSE" if self._paused else "TRAITÉ"
        p.setFont(QFont("Inter", 8, QFont.Weight.Bold))
        p.setPen(QColor(_WARN if self._paused else _MUTED))
        p.drawText(QRectF(0, cy + 10, d, 20), Qt.AlignmentFlag.AlignCenter, label)
        p.end()


# ═══════════════════════════════════════════════════════════════════════════════
#  Ligne du log de fichier
# ═══════════════════════════════════════════════════════════════════════════════

class _FileRow(QWidget):
    def __init__(self, icon: str, name: str, meta: str, integrity: int, parent=None):
        super().__init__(parent)
        self.setFixedHeight(40)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 0, 16, 0)
        lay.setSpacing(14)

        ico = QLabel(icon)
        ico.setStyleSheet("font-size: 18px; background: transparent;")

        nam = QLabel(name)
        nam.setStyleSheet(
            f"color: {_TEXT}; font-size: 12px; font-weight: 500;"
            "font-family: 'Inter'; background: transparent;"
        )

        meta_lbl = QLabel(meta)
        meta_lbl.setStyleSheet(
            f"color: {_SUB}; font-size: 11px;"
            "font-family: 'Inter'; background: transparent;"
        )

        if integrity >= 90:
            sc, st = _OK,   "Excellent"
        elif integrity >= 60:
            sc, st = _ACCENT, "Partiel"
        else:
            sc, st = _WARN,  "Dégradé"

        status = QLabel(st)
        status.setStyleSheet(
            f"color: {sc}; font-size: 11px; font-weight: 500;"
            "font-family: 'Inter'; background: transparent;"
        )

        lay.addWidget(ico)
        lay.addWidget(nam, stretch=1)
        lay.addWidget(meta_lbl)
        lay.addWidget(status)

        self.setStyleSheet(
            f"QWidget {{ background: transparent; border-radius: 6px; }}"
            f"QWidget:hover {{ background: {_HOVER}; }}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
#  Écran de scan
# ═══════════════════════════════════════════════════════════════════════════════

class ScanScreen(QWidget):
    scan_finished  = pyqtSignal(list)
    scan_cancelled = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background: transparent;")
        self._worker: ScanWorker | None = None
        self._found_count  = 0
        self._bad_sectors  = 0
        self._start_time   = 0.0
        self._had_error    = False
        self._speed_buf: deque = deque()

        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(1000)
        self._elapsed_timer.timeout.connect(self._update_elapsed)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── Panneau haut : anneau + stats ──────────────────────────────────────
        top = QWidget()
        top.setStyleSheet("background: transparent;")
        top_lay = QVBoxLayout(top)
        top_lay.setContentsMargins(40, 14, 40, 14)
        top_lay.setSpacing(0)

        # En-tête
        hdr = QHBoxLayout()
        left_col = QVBoxLayout()
        left_col.setSpacing(4)
        self._title    = QLabel("Analyse en cours…")
        self._disk_lbl = QLabel("")
        self._title.setStyleSheet(
            f"color: {_TEXT}; font-size: 22px; font-weight: 700;"
            "font-family: 'Inter'; background: transparent;"
        )
        self._disk_lbl.setStyleSheet(
            f"color: {_SUB}; font-size: 13px;"
            "font-family: 'Inter'; background: transparent;"
        )
        left_col.addWidget(self._title)
        left_col.addWidget(self._disk_lbl)
        hdr.addLayout(left_col)
        hdr.addStretch()

        self._pause_btn = QPushButton("⏸  PAUSE")
        self._pause_btn.setFixedSize(100, 32)
        self._pause_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._pause_btn.setStyleSheet(
            f"QPushButton {{ background: {_CARD}; border: 1px solid {_BORDER};"
            f"  border-radius: 8px; color: {_TEXT}; font-size: 11px; font-weight: 600;"
            f"  letter-spacing: 0.5px; }}"
            f"QPushButton:hover {{ background: {_HOVER}; }}"
            f"QPushButton:disabled {{ color: {_MUTED}; }}"
        )
        self._pause_btn.clicked.connect(self._on_pause)
        hdr.addWidget(self._pause_btn, alignment=Qt.AlignmentFlag.AlignTop)
        top_lay.addLayout(hdr)
        top_lay.addSpacing(8)

        # Anneau
        self._ring = CircularProgress()
        top_lay.addWidget(self._ring, alignment=Qt.AlignmentFlag.AlignHCenter)
        top_lay.addSpacing(12)

        # Message de statut
        self._status_lbl = QLabel("Initialisation…")
        self._status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_lbl.setStyleSheet(
            f"color: {_ACCENT}; font-size: 12px;"
            "font-family: 'SF Mono', Consolas, monospace; background: transparent;"
        )
        top_lay.addWidget(self._status_lbl)
        top_lay.addSpacing(8)

        # Badges de stats
        stats_row = QHBoxLayout()
        stats_row.setSpacing(0)

        self._counter_lbl = QLabel("✓  0 fichier détecté")
        self._counter_lbl.setStyleSheet(
            f"color: {_OK}; font-size: 12px; font-weight: 500;"
            f"background: {_OK_BG}; border: 1px solid rgba(52,199,89,0.2);"
            "border-radius: 14px; padding: 4px 16px;"
        )
        self._speed_lbl = QLabel("")
        self._speed_lbl.setStyleSheet(
            f"color: {_MUTED}; font-size: 11px; padding: 0 12px;"
        )
        self._elapsed_lbl = QLabel("")
        self._elapsed_lbl.setStyleSheet(
            f"color: {_MUTED}; font-size: 11px; padding: 0 8px;"
        )
        self._bad_lbl = QLabel("")
        self._bad_lbl.setStyleSheet(
            f"color: {_WARN}; font-size: 11px; padding: 0 8px;"
        )

        stats_row.addStretch()
        for w in (self._counter_lbl, self._speed_lbl, self._elapsed_lbl, self._bad_lbl):
            stats_row.addWidget(w)
        stats_row.addStretch()
        top_lay.addLayout(stats_row)
        top_lay.addSpacing(6)

        # ETA
        self._eta_lbl = QLabel("")
        self._eta_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._eta_lbl.setStyleSheet(
            f"color: {_MUTED}; font-size: 11px; font-weight: 600;"
            "letter-spacing: 0.8px; background: transparent;"
        )
        top_lay.addWidget(self._eta_lbl)

        outer.addWidget(top)

        # ── Panneau bas : log en temps réel ────────────────────────────────────
        log_wrap = QWidget()
        log_main = QVBoxLayout(log_wrap)
        log_main.setContentsMargins(40, 0, 40, 40)

        log_frame = QFrame()
        log_frame.setStyleSheet(
            f"QFrame {{ background: {_CARD}; border: 1px solid {_BORDER}; border-radius: 14px; }}"
        )
        log_col = QVBoxLayout(log_frame)
        log_col.setContentsMargins(0, 0, 0, 0)
        log_col.setSpacing(0)

        # En-tête du log
        log_hdr = QWidget()
        log_hdr.setFixedHeight(44)
        log_hdr.setStyleSheet(
            "background: rgba(255,255,255,0.02);"
            "border-bottom: 1px solid rgba(255,255,255,0.05);"
            "border-top-left-radius: 14px; border-top-right-radius: 14px;"
        )
        hdr_l = QHBoxLayout(log_hdr)
        hdr_l.setContentsMargins(22, 0, 22, 0)

        log_title = QLabel("FICHIERS DÉTECTÉS EN TEMPS RÉEL")
        log_title.setStyleSheet(
            f"color: {_SUB}; font-size: 10px; font-weight: 700;"
            "letter-spacing: 1px; font-family: 'Inter'; border: none; background: transparent;"
        )
        live_tag = QLabel("LIVE")
        live_tag.setStyleSheet(
            f"color: {_ACCENT}; font-size: 9px; font-weight: 700;"
            "background: rgba(0,122,255,0.12); padding: 2px 7px;"
            "border-radius: 4px; border: none;"
        )
        hdr_l.addWidget(log_title)
        hdr_l.addStretch()
        hdr_l.addWidget(live_tag)
        log_col.addWidget(log_hdr)

        # Liste des fichiers
        self._log_list = QListWidget()
        self._log_list.setStyleSheet(
            "QListWidget { background: transparent; border: none; outline: none; padding: 6px; }"
            "QListWidget::item { background: transparent; border-radius: 6px; }"
        )
        self._log_list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        log_col.addWidget(self._log_list, stretch=1)

        # Barre du bas avec bouton annuler
        foot = QWidget()
        foot.setFixedHeight(44)
        foot.setStyleSheet(
            "border-top: 1px solid rgba(255,255,255,0.05);"
            "border-bottom-left-radius: 14px; border-bottom-right-radius: 14px;"
        )
        foot_l = QHBoxLayout(foot)
        foot_l.setContentsMargins(0, 0, 0, 0)
        self._cancel_btn = QPushButton("✕  Annuler le scan")
        self._cancel_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._cancel_btn.setStyleSheet(
            f"QPushButton {{ color: {_MUTED}; font-size: 11px; font-weight: 600;"
            f"  letter-spacing: 0.8px; background: transparent; border: none; }}"
            f"QPushButton:hover {{ color: {_ERR}; }}"
            f"QPushButton:disabled {{ color: {_MUTED}; opacity: 0.5; }}"
        )
        self._cancel_btn.clicked.connect(self._on_cancel)
        foot_l.addWidget(self._cancel_btn, alignment=Qt.AlignmentFlag.AlignCenter)
        log_col.addWidget(foot)

        log_main.addWidget(log_frame)
        outer.addWidget(log_wrap, stretch=1)

    # ── API publique ──────────────────────────────────────────────────────────

    def start_scan(self, disk: dict):
        self._found_count = 0
        self._bad_sectors = 0
        self._start_time  = time.monotonic()
        self._had_error   = False
        self._speed_buf.clear()
        self._log_list.clear()

        self._ring.setValue(0)
        self._ring.setActive(True)
        self._ring.setPaused(False)

        self._status_lbl.setText("Initialisation…")
        self._counter_lbl.setText("✓  0 fichier détecté")
        self._eta_lbl.setText("ESTIMATION DU TEMPS…")
        self._speed_lbl.setText("")
        self._elapsed_lbl.setText("")
        self._bad_lbl.setText("")
        self._cancel_btn.setEnabled(True)
        self._pause_btn.setEnabled(True)
        self._pause_btn.setText("⏸  PAUSE")

        mode = disk.get("scan_mode", "deep")
        mode_lbl = "Scan Rapide" if mode == "quick" else "Scan Complet"
        self._title.setText(f"{mode_lbl} en cours…")
        dev  = disk.get("device", "")
        size = disk.get("size_gb", 0)
        self._disk_lbl.setText(f"{dev}  ·  {size} Go  ·  {mode_lbl}")

        # Arrêter l'éventuel worker précédent sans bloquer l'UI
        if self._worker:
            self._detach_worker(self._worker)
            self._worker = None

        if mode == "demo" and not is_demo_enabled():
            self._on_error(t("scan.demo_disabled"))
            self._cancel_btn.setEnabled(False)
            self._pause_btn.setEnabled(False)
            return

        # Development-only demo path. Quick scan is metadata-only and must not
        # route to the legacy simulation engine.
        simulate = mode == "demo" and is_demo_enabled()
        self._worker = ScanWorker(disk, simulate=simulate)
        self._worker.progress.connect(self._on_progress)
        self._worker.status_text.connect(self._on_status)
        self._worker.files_batch_found.connect(self._on_batch)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.start()
        self._elapsed_timer.start()

    # ── Slots du worker ───────────────────────────────────────────────────────

    def _on_progress(self, pct: int):
        self._ring.setValue(pct)
        self._update_eta(pct)

    def _on_status(self, text: str):
        self._status_lbl.setText(text)
        txt_low = text.lower()
        if "illisible" in txt_low or "sector" in txt_low or "bad" in txt_low:
            self._bad_sectors += 1
            self._bad_lbl.setText(f"·  ⚠ {self._bad_sectors} secteur(s) illisible(s)")

    def _on_batch(self, batch: list):
        self._found_count += len(batch)
        plural = "s" if self._found_count > 1 else ""
        self._counter_lbl.setText(f"✓  {self._found_count} fichier{plural} détecté{plural}")

        for info in batch:
            ext        = info.get("type", "???").upper()
            name       = info.get("name", "inconnu")
            size_kb    = info.get("size_kb", 0)
            integrity  = info.get("integrity", 60)
            size_str   = (
                f"{size_kb / 1024:.1f} Mo" if size_kb >= 1024
                else f"{size_kb} Ko" if size_kb else "—"
            )
            icon = _ICONS.get(ext, "📁")
            meta = f"{ext}  ·  {size_str}"

            item = QListWidgetItem(self._log_list)
            row  = _FileRow(icon, name, meta, integrity)
            item.setSizeHint(row.sizeHint())
            self._log_list.addItem(item)
            self._log_list.setItemWidget(item, row)

        # Limiter à 800 entrées
        while self._log_list.count() > 800:
            self._log_list.takeItem(0)

        self._log_list.scrollToBottom()

    def _on_finished(self, files: list):
        if self._had_error:
            return
        self._elapsed_timer.stop()
        self._ring.setActive(False)
        self._ring.setValue(100)
        self._cancel_btn.setEnabled(False)
        self._pause_btn.setEnabled(False)
        self._title.setText("Analyse terminée")
        self._eta_lbl.setText("")
        self.scan_finished.emit(files)

    def _on_error(self, msg: str):
        self._had_error = True
        self._elapsed_timer.stop()
        self._ring.setActive(False)
        self._status_lbl.setText(f"Erreur : {msg}")
        self._title.setText("Erreur d'analyse")
        self._eta_lbl.setText("")
        self._cancel_btn.setEnabled(False)
        self._pause_btn.setEnabled(False)

    # ── Contrôles pause / annuler ─────────────────────────────────────────────

    def _on_pause(self):
        if not self._worker:
            return
        if self._worker.is_paused():
            self._worker.resume()
            self._ring.setPaused(False)
            self._pause_btn.setText("⏸  PAUSE")
            self._elapsed_timer.start()
        else:
            self._worker.pause()
            self._ring.setPaused(True)
            self._pause_btn.setText("▶  REPRENDRE")
            self._elapsed_timer.stop()

    def _on_cancel(self):
        self._elapsed_timer.stop()
        self._ring.setActive(False)
        self._ring.setPaused(False)
        self._eta_lbl.setText("")
        if self._worker:
            self._detach_worker(self._worker)
            self._worker = None
        self.scan_cancelled.emit()

    # ── Déconnexion propre sans bloquer l'UI ─────────────────────────────────

    def is_scanning(self) -> bool:
        return self._worker is not None and self._worker.isRunning()

    @staticmethod
    def _detach_worker(worker):
        """Déconnecte tous les signaux et demande l'arrêt sans wait()."""
        try:
            worker.progress.disconnect()
            worker.status_text.disconnect()
            worker.files_batch_found.disconnect()
            worker.finished.disconnect()
            worker.error.disconnect()
        except RuntimeError:
            pass
        worker.stop()
        # Le thread finit en arrière-plan ; deleteLater() libère la mémoire
        worker.finished.connect(worker.deleteLater)

    # ── ETA + chronomètre ─────────────────────────────────────────────────────

    def _update_elapsed(self):
        elapsed = int(time.monotonic() - self._start_time)
        if elapsed < 60:
            self._elapsed_lbl.setText(f"·  {elapsed}s")
        else:
            m, s = divmod(elapsed, 60)
            self._elapsed_lbl.setText(f"·  {m}m {s:02d}s")

    def _update_eta(self, pct: int):
        now = time.monotonic()
        self._speed_buf.append((now, pct))
        cutoff = now - 12.0
        while self._speed_buf and self._speed_buf[0][0] < cutoff:
            self._speed_buf.popleft()

        if pct >= 100:
            self._eta_lbl.setText("FINALISATION…")
            return
        if len(self._speed_buf) < 3 or pct <= 0:
            return

        t0, p0 = self._speed_buf[0]
        t1, p1 = self._speed_buf[-1]
        dt = t1 - t0
        if dt < 1.0 or p1 <= p0:
            return

        speed = (p1 - p0) / dt          # % par seconde
        remaining = 100 - p1
        if speed > 0 and remaining > 0:
            eta_s = int(remaining / speed)
            if eta_s < 86400:
                self._eta_lbl.setText(self._fmt_eta(eta_s))
        self._speed_lbl.setText(f"·  {speed:.1f}%/s")

    @staticmethod
    def _fmt_eta(seconds: int) -> str:
        if seconds < 60:
            return f"ENVIRON {seconds}S RESTANTES"
        if seconds < 3600:
            m, s = divmod(seconds, 60)
            return f"ENVIRON {m}MIN {s:02d}S RESTANTES"
        h, rem = divmod(seconds, 3600)
        return f"ENVIRON {h}H {rem // 60:02d}MIN RESTANTES"
