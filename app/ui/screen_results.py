"""
Lumina v2.0 — Écran 2 : Résultats de scan
Grille de miniatures, filtres par type, recherche, sélection multiple,
extraction vers un dossier choisi par l'utilisateur.
"""

import contextlib
import datetime
import errno
import glob
import hashlib
import json
import logging
import os
import threading
import unicodedata
import xml.etree.ElementTree as ET

from PyQt6.QtCore import QRectF, Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QAction,
    QColor,
    QCursor,
    QFont,
    QImage,
    QPainter,
    QPixmap,
)
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QProgressBar,
    QProgressDialog,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.core.recovery import (
    default_recovery_dir,
    ensure_lumina_log,
    persist_recovery_dir,
    validate_recovery_destination,
)
from app.core.version import DISPLAY_VERSION, VERSION
from app.modules import is_module_enabled
from app.modules.search_filters import FilterCriteria, apply_filters
from app.ui.palette import (
    ACCENT as _ACCENT,
)
from app.ui.palette import (
    BEVEL_LIGHT as _BEVEL_LIGHT,
)
from app.ui.palette import (
    BEVEL_SHADOW as _BEVEL_SHADOW,
)
from app.ui.palette import (
    CARD as _CARD,
)
from app.ui.palette import (
    HOVER as _HOVER,
)
from app.ui.palette import (
    OK as _OK,
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

_HISTORY_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "logs", "history.json",
)

# ── Logger ───────────────────────────────────────────────────────────────────
_log = logging.getLogger("lumina.recovery")
ensure_lumina_log()
_log.setLevel(logging.INFO)

_PANEL = "#F8FAFC"
_SURFACE = "#FFFFFF"
_LINE = "#D0D5DD"
_SOFT_BLUE = "#EAF2FB"
_FONT = "'Segoe UI', Arial"

# Couleurs de dégradé par type
_THUMB_GRAD: dict[str, tuple[str, str]] = {
    "JPG":  ("#FB923C", "#EC4899"), "JPEG": ("#FB923C", "#EC4899"),
    "PNG":  ("#60A5FA", "#2DD4BF"), "BMP":  ("#34D399", "#059669"),
    "GIF":  ("#A78BFA", "#7C3AED"), "TIFF": ("#FCD34D", "#F59E0B"),
    "WEBP": ("#6EE7B7", "#10B981"), "HEIC": ("#F472B6", "#EC4899"),
    "PSD":  ("#818CF8", "#4F46E5"),
    "MP4":  ("#A855F7", "#D946EF"), "MOV":  ("#A855F7", "#EC4899"),
    "MKV":  ("#7C3AED", "#A855F7"), "AVI":  ("#6366F1", "#4338CA"),
    "FLV":  ("#F87171", "#EF4444"), "WMV":  ("#60A5FA", "#2563EB"),
    "MPG":  ("#A78BFA", "#6D28D9"),
    "MP3":  ("#34D399", "#059669"), "WAV":  ("#6EE7B7", "#10B981"),
    "FLAC": ("#FCA5A5", "#EF4444"), "AAC":  ("#FCD34D", "#D97706"),
    "OGG":  ("#C4B5FD", "#7C3AED"),
    "PDF":  ("#EF4444", "#EA580C"), "DOC":  ("#3B82F6", "#1D4ED8"),
    "DOCX": ("#3B82F6", "#1D4ED8"), "XLS":  ("#22C55E", "#15803D"),
    "XLSX": ("#22C55E", "#15803D"), "PPT":  ("#F97316", "#C2410C"),
    "PPTX": ("#F97316", "#C2410C"),
    "ZIP":  ("#F59E0B", "#B45309"), "RAR":  ("#EF4444", "#991B1B"),
    "7Z":   ("#8B5CF6", "#6D28D9"), "GZ":   ("#64748B", "#475569"),
    "EXE":  ("#64748B", "#334155"), "DLL":  ("#64748B", "#334155"),
    "SQLITE": ("#60A5FA", "#1D4ED8"),
    "CAB":  ("#94A3B8", "#64748B"), "SWF":  ("#F87171", "#DC2626"),
    "WMF":  ("#C084FC", "#7C3AED"), "DWG":  ("#FBBF24", "#D97706"),
    "RTF":  ("#93C5FD", "#2563EB"), "EML":  ("#6EE7B7", "#059669"),
    "VCF":  ("#34D399", "#059669"), "ICS":  ("#60A5FA", "#2563EB"),
    "ORF":  ("#FCD34D", "#F59E0B"), "RW2":  ("#FCD34D", "#D97706"),
    "RAF":  ("#FCD34D", "#B45309"), "CR3":  ("#F97316", "#EA580C"),
    "NEF":  ("#FCD34D", "#F59E0B"), "ARW":  ("#FCD34D", "#F59E0B"),
}
_THUMB_ICON: dict[str, str] = {
    "JPG": "📸", "JPEG": "📸", "PNG": "🎨", "BMP": "🖼", "GIF": "🎭",
    "TIFF": "📷", "WEBP": "🖼", "HEIC": "📱", "PSD": "🎨",
    "MP4": "🎬", "MOV": "🎬", "MKV": "🎬", "AVI": "🎬",
    "FLV": "🎬", "WMV": "🎬", "MPG": "🎬",
    "MP3": "🎵", "WAV": "🎵", "FLAC": "🎵", "AAC": "🎵", "OGG": "🎵",
    "PDF": "📄", "DOC": "📝", "DOCX": "📝", "XLS": "📊", "XLSX": "📊",
    "PPT": "📋", "PPTX": "📋",
    "ZIP": "📦", "RAR": "📦", "7Z": "📦", "GZ": "📦",
    "EXE": "⚙", "DLL": "⚙", "SQLITE": "🗄", "PST": "📧",
    "CAB": "📦", "SWF": "🎬", "WMF": "🖼", "DWG": "📐",
    "RTF": "📝", "EML": "📧", "VCF": "👤", "ICS": "📅",
    "ORF": "📷", "RW2": "📷", "RAF": "📷", "CR3": "📷",
    "NEF": "📷", "ARW": "📷", "MKA": "🎵", "APE": "🎵", "WV": "🎵",
}

# Types d'images pour lesquels Qt peut charger les bytes bruts directement
# TIFF est supporté nativement par Qt6 via libtiff.
_THUMB_IMAGE_TYPES = {"JPG", "JPEG", "PNG", "BMP", "GIF", "WEBP", "TIFF"}

# Groupes de types pour les filtres
_TYPE_GROUPS: dict[str, set[str]] = {
    "Images":    {"JPG","JPEG","PNG","BMP","GIF","TIFF","WEBP","HEIC","HEIF","PSD","SVG",
                  "CR2","CR3","NEF","ARW","DNG","ORF","RW2","RAF","PEF","SRW","AI","EPS","INDD",
                  "WMF"},
    "Vidéos":    {"MP4","MOV","MKV","AVI","FLV","WMV","MPG","M2TS","3GP","VOB","RM","MXF","MKA"},
    "Audio":     {"MP3","WAV","FLAC","AAC","OGG","WMA","M4A","AIFF","OPUS","APE","WV"},
    "Documents": {"PDF","DOC","DOCX","XLS","XLSX","PPT","PPTX","ODT","ODS","TXT",
                  "HTML","XML","RTF","EML","PST","VCF","ICS","DWG","ACCDB"},
    "Archives":  {"ZIP","RAR","7Z","GZ","BZ2","XZ","TAR","ISO","EPUB","CAB","SWF"},
    "Autres":    set(),   # tout le reste
}

_SYSTEM_TYPES: frozenset[str] = frozenset({
    "EXE", "DLL", "SYS", "MSI", "MSP", "MSU",
    "OCX", "COM", "SCR", "CPL", "PIF",
    "INF", "CAT", "INI",
    "DAT", "LOG", "TMP", "LNK", "PDB",
})


def _normalize(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()


def _integrity_label(pct: int) -> str:
    """Human-readable recoverability label for a given integrity percentage."""
    if pct >= 90:
        return "Excellent"
    if pct >= 75:
        return "Bon"
    if pct >= 60:
        return "Partiel"
    return "Fragmenté"


# ═══════════════════════════════════════════════════════════════════════════════
#  Miniature de fichier récupéré (140 x 160)
# ═══════════════════════════════════════════════════════════════════════════════

class FileThumb(QWidget):
    selection_changed = pyqtSignal(bool)
    detail_requested  = pyqtSignal(dict)

    W, H = 156, 178

    def __init__(self, info: dict, parent=None):
        super().__init__(parent)
        self.info       = info
        self._selected  = False

        self.setObjectName("FileThumb")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedSize(self.W, self.H)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._update_style()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # ── Miniature ─────────────────────────────────────────────────────────
        thumb_area = QWidget()
        thumb_area.setFixedHeight(106)
        thumb_area.setObjectName("ThumbArea")
        thumb_area.setStyleSheet("background: transparent;")
        thumb_lay = QVBoxLayout(thumb_area)
        thumb_lay.setContentsMargins(0, 0, 0, 0)

        self._thumb = _GradientThumb(info.get("type", "???").upper())
        self._thumb.setFixedSize(self.W, 106)
        thumb_lay.addWidget(self._thumb)
        lay.addWidget(thumb_area)

        # ── Infos ─────────────────────────────────────────────────────────────
        info_area = QWidget()
        info_area.setFixedHeight(72)
        info_area.setStyleSheet("background: transparent;")
        info_lay = QVBoxLayout(info_area)
        info_lay.setContentsMargins(12, 9, 12, 9)
        info_lay.setSpacing(3)

        full_name = info.get("name", "inconnu")
        name = full_name
        if len(name) > 18:
            name = name[:16] + "…"
        name_lbl = QLabel(name)
        name_lbl.setToolTip(full_name)
        self.setToolTip(full_name)
        name_lbl.setStyleSheet(
            f"color: {_TEXT}; font-size: 11px; font-weight: 800;"
            f"font-family: {_FONT}; background: transparent;"
        )

        size_kb    = info.get("size_kb", 0)
        size_str   = f"{size_kb / 1024:.1f} Mo" if size_kb >= 1024 else f"{size_kb} Ko"
        integrity  = info.get("integrity", 60)
        int_color  = f"{_OK}" if integrity >= 90 else (f"{_ACCENT}" if integrity >= 60 else f"{_WARN}")
        int_lbl_str = _integrity_label(integrity)
        meta_lbl = QLabel(f"{size_str} {int_lbl_str}")
        meta_lbl.setStyleSheet(
            f"color: {int_color}; font-size: 10px; font-weight: 700;"
            f"font-family: {_FONT}; background: transparent;"
        )

        info_lay.addWidget(name_lbl)
        info_lay.addWidget(meta_lbl)
        lay.addWidget(info_area)

        # ── Case à cocher ─────────────────────────────────────────────────────
        self._chk = QCheckBox(info_area)
        self._chk.setGeometry(self.W - 24, 6, 18, 18)
        self._chk.setStyleSheet(
            "QCheckBox { background: transparent; }"
            "QCheckBox::indicator {"
            "  width: 14px; height: 14px;"
            f"  background-color: {_SURFACE};"
            f"  border: 1px solid {_LINE};"
            "  border-radius: 2px;"
            "}"
            f"QCheckBox::indicator:checked {{ background-color: {_ACCENT}; border-color: {_ACCENT}; }}"
        )
        self._chk.stateChanged.connect(self._on_check)

        # ── Badge NTFS (fichiers issus de la MFT) ────────────────────────────
        if info.get("source") == "mft":
            fs_tag = info.get("fs", "MFT")
            badge = QLabel(fs_tag, thumb_area)
            badge.setToolTip("Nom d'origine récupéré depuis le système de fichiers")
            badge.setGeometry(2, 2, 36, 14)
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            badge.setStyleSheet(
                f"background-color: {_OK}; color: {_BEVEL_LIGHT};"
                "font-size: 9px; font-weight: 800;"
                f"font-family: {_FONT}; border-radius: 2px;"
            )

        # ── Badge statut supprime/actif ───────────────────────────────────────
        if info.get("deleted"):
            del_badge = QLabel("DEL", thumb_area)
            del_badge.setToolTip("Fichier supprime - entree MFT toujours lisible")
            del_badge.setGeometry(2, 80, 28, 14)
            del_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            del_badge.setStyleSheet(
                f"background-color: {_WARN}; color: {_BEVEL_LIGHT};"
                f"font-size: 9px; font-weight: 800; font-family: {_FONT}; border-radius: 2px;"
            )
        elif info.get("source") == "mft" and not info.get("deleted"):
            act_badge = QLabel("OK", thumb_area)
            act_badge.setToolTip("Fichier toujours present sur le disque")
            act_badge.setGeometry(2, 80, 22, 14)
            act_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            act_badge.setStyleSheet(
                f"background-color: {_OK}; color: {_BEVEL_LIGHT};"
                f"font-size: 9px; font-weight: 800; font-family: {_FONT}; border-radius: 2px;"
            )

    def _update_style(self):
        if self._selected:
            self.setStyleSheet(
                "QWidget#FileThumb {"
                f"  background-color: {_SOFT_BLUE};"
                f"  border: 1px solid {_ACCENT};"
                "  border-radius: 4px;"
                "}"
            )
        else:
            self.setStyleSheet(
                "QWidget#FileThumb {"
                f"  background-color: {_SURFACE};"
                f"  border: 1px solid {_LINE};"
                "  border-radius: 4px;"
                "}"
            )

    def _on_check(self, state):
        self._selected = state == Qt.CheckState.Checked.value
        self._update_style()
        self.selection_changed.emit(self._selected)

    def is_selected(self) -> bool:
        return self._chk.isChecked()

    def set_selected(self, v: bool):
        self._chk.setChecked(v)

    def set_real_thumb(self, pixmap: QPixmap):
        """Remplace le dégradé par la vraie miniature image."""
        self._thumb.set_pixmap(pixmap)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.detail_requested.emit(self.info)
        super().mousePressEvent(e)


class _GradientThumb(QWidget):
    """Miniature colorée avec icône, ou vraie image si chargée en arrière-plan."""

    def __init__(self, ftype: str, parent=None):
        super().__init__(parent)
        self._ftype  = ftype
        self._pixmap: QPixmap | None = None
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def set_pixmap(self, px: QPixmap):
        """Remplace le dégradé par la vraie miniature (appelé depuis le thread principal)."""
        self._pixmap = px
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        w, h = self.width(), self.height()

        # Win98 flat silver background for thumb
        p.fillRect(0, 0, w, h, QColor(f"{_CARD}"))

        if self._pixmap and not self._pixmap.isNull():
            # ── Vraie miniature ──────────────────────────────────────────────
            scaled = self._pixmap.scaled(
                w, h,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            x = (w - scaled.width()) // 2
            y = (h - scaled.height()) // 2
            p.drawPixmap(x, y, scaled)
        else:
            p.fillRect(0, 0, w, h, QColor("#F2F5F9"))
            p.fillRect(0, h - 24, w, 24, QColor(f"{_ACCENT}"))
            p.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
            p.setPen(QColor(f"{_BEVEL_LIGHT}"))
            p.drawText(QRectF(0, h - 24, w, 24), Qt.AlignmentFlag.AlignCenter, self._ftype)

        p.end()


# ═══════════════════════════════════════════════════════════════════════════════
#  Chargeur de miniatures (QThread)
# ═══════════════════════════════════════════════════════════════════════════════

class _ThumbnailLoader(QThread):
    """
    Charge les vraies miniatures pour les fichiers images en arrière-plan.
    Utilise QImage (thread-safe) ; la conversion en QPixmap se fait dans le
    thread principal via le signal ready.
    """
    ready = pyqtSignal(int, "PyQt_PyObject")   # (index visible, QImage)

    def __init__(self, indexed_files: list[tuple[int, dict]], parent=None):
        super().__init__(parent)
        self._files = indexed_files
        self._stop  = False

    def stop(self):
        self._stop = True

    def run(self):
        for idx, info in self._files:
            if self._stop:
                break
            device  = info.get("device", "")
            offset  = info.get("offset", 0)
            size_kb = info.get("size_kb", 0)
            if not device:
                continue
            try:
                dev = device.strip()
                if len(dev) == 2 and dev[1] == ":" and not dev.startswith("\\\\.\\"):
                    dev = f"\\\\.\\{dev[0].upper()}:"
                max_bytes = min(size_kb * 1024, 2 * 1024 * 1024)   # plafond 2 Mo
                if max_bytes < 64:
                    continue
                fd = os.open(dev, os.O_RDONLY | getattr(os, "O_BINARY", 0))
                try:
                    os.lseek(fd, offset, os.SEEK_SET)
                    data = os.read(fd, max_bytes)
                finally:
                    os.close(fd)
                img = QImage()
                if img.loadFromData(data):
                    self.ready.emit(idx, img)
            except Exception:
                pass


# ═══════════════════════════════════════════════════════════════════════════════
#  Worker d'extraction (QThread)
# ═══════════════════════════════════════════════════════════════════════════════

class _ExtractionWorker(QThread):
    progress = pyqtSignal(int, str)    # (n_done, current_name)
    file_progress = pyqtSignal(int, str, int)  # (index, current_name, percent)
    finished = pyqtSignal(int, int)    # (n_ok, n_fail)

    _CHUNK    = 1 << 20                 # 1 MiB — balances RAM use and cancel latency

    def __init__(self, files: list[dict], dest: str, parent=None):
        super().__init__(parent)
        self._files = files
        self._dest  = dest
        self._stop  = threading.Event()

    def stop(self) -> None:
        """Request cooperative cancellation from the UI thread."""
        self._stop.set()

    def run(self):
        ok = fail = 0
        for i, info in enumerate(self._files):
            if self._stop.is_set():
                break
            name = info.get("name", f"recovered_{i}")
            self.progress.emit(i, name)
            self.file_progress.emit(i, name, 0)
            try:
                self._extract(info, lambda pct, idx=i, n=name: self.file_progress.emit(idx, n, pct))
                ok += 1
                _log.info("Extracted: %s → %s", name, self._dest)
            except InterruptedError:
                _log.info("Extraction cancelled: %s", name)
                break
            except Exception as exc:
                fail += 1
                _log.warning("Extraction failed for %s: %s", name, exc)
        self.finished.emit(ok, fail)

    @staticmethod
    def _partial_dest_path(dest_path: str) -> str:
        root, ext = os.path.splitext(dest_path)
        candidate = f"{root}_PARTIEL{ext}"
        n = 2
        while os.path.exists(candidate):
            candidate = f"{root}_PARTIEL_{n}{ext}"
            n += 1
        return candidate

    @classmethod
    def _mark_partial(cls, info: dict, dest_path: str, written: int, expected: int, reason: str) -> str:
        final_path = dest_path
        if written > 0 and os.path.exists(dest_path):
            final_path = cls._partial_dest_path(dest_path)
            os.replace(dest_path, final_path)
        info["partial"] = True
        info["partial_reason"] = reason
        info["extracted_name"] = os.path.basename(final_path)
        info["extracted_size"] = written
        info["expected_size"] = expected
        return final_path

    def _extract(self, info: dict, progress_cb=None):
        dest_path = os.path.join(self._dest, info.get("name", "recovered"))

        # Fichier simulé : pas de vraies données brutes disponibles
        if info.get("simulated"):
            with open(dest_path, "wb") as f:
                ext = info.get("type", "BIN").lower()
                f.write(
                    f"[Fichier simulé — scan de démonstration]\n"
                    f"Nom: {info.get('name','?')}\n"
                    f"Type: {ext}\n"
                    f"Taille estimée: {info.get('size_kb',0)} Ko\n"
                    f"Intégrité: {info.get('integrity',0)}%\n".encode()
                )
            info["extracted_name"] = os.path.basename(dest_path)
            return

        # Fichier réel : extraction depuis le disque brut
        device  = info.get("device", "")
        offset  = info.get("offset", 0)
        size_kb = info.get("size_kb", 0)

        if not device:
            raise ValueError("Périphérique source inconnu")

        # Convertir en chemin brut Windows si nécessaire
        dev = device.strip()
        logical_drive = dev.rstrip("\\/")
        if len(logical_drive) == 2 and logical_drive[1] == ":" and not dev.startswith("\\\\.\\"):
            dev = f"\\\\.\\{dev[0].upper()}:"

        raw_size = max(0, int(size_kb) * 1024)

        # Streaming read + incremental SHA-256 — single disk pass, bounded RAM.
        sha = hashlib.sha256()
        remaining = raw_size
        written = 0
        cancelled = False
        fd = os.open(dev, os.O_RDONLY | getattr(os, "O_BINARY", 0))
        try:
            os.lseek(fd, offset, os.SEEK_SET)
            try:
                with open(dest_path, "wb") as out:
                    while remaining > 0:
                        if self._stop.is_set():
                            cancelled = True
                            break
                        chunk = os.read(fd, min(self._CHUNK, remaining))
                        if not chunk:
                            break
                        out.write(chunk)
                        sha.update(chunk)
                        written += len(chunk)
                        remaining -= len(chunk)
                        if progress_cb and raw_size:
                            progress_cb(min(100, int(written * 100 / raw_size)))
            except OSError as exc:
                reason = (
                    "Espace insuffisant sur le disque de destination"
                    if exc.errno == errno.ENOSPC
                    else f"Erreur d'ecriture: {exc}"
                )
                self._mark_partial(info, dest_path, written, raw_size, reason)
                raise
        finally:
            os.close(fd)

        info["sha256"]         = sha.hexdigest()
        info["extracted_name"] = os.path.basename(dest_path)
        info["extracted_size"] = written
        info["expected_size"]  = raw_size
        if cancelled:
            self._mark_partial(info, dest_path, written, raw_size, "Extraction annulee")
            raise InterruptedError("cancelled")
        if remaining > 0:
            self._mark_partial(
                info,
                dest_path,
                written,
                raw_size,
                "Source terminee avant la taille attendue",
            )
            _log.warning(
                "Extraction partielle: %s (%d/%d bytes)",
                info.get("name", "?"),
                written,
                raw_size,
            )
        elif progress_cb:
            progress_cb(100)


# ═══════════════════════════════════════════════════════════════════════════════
#  Panneau de détail latéral
# ═══════════════════════════════════════════════════════════════════════════════

class _FileDetailPanel(QWidget):
    recover_requested = pyqtSignal(dict)
    closed            = pyqtSignal()

    WIDTH = 290

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(self.WIDTH)
        self.setStyleSheet(
            "_FileDetailPanel {"
            f"  background-color: {_CARD};"
            f"  border-left: 2px solid {_BEVEL_SHADOW};"
            "}"
        )
        self._info: dict = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 20)
        root.setSpacing(0)

        # ── En-tete ───────────────────────────────────────────────────────────
        hdr_bar = QWidget()
        hdr_bar.setFixedHeight(20)
        hdr_bar.setStyleSheet(f"background-color: {_ACCENT}; border: 0px;")
        hdr = QHBoxLayout(hdr_bar)
        hdr.setContentsMargins(6, 0, 2, 0)
        title = QLabel("Details")
        title.setStyleSheet(
            f"color: {_BEVEL_LIGHT}; font-size: 11px; font-weight: 700;"
            "font-family: 'Work Sans', Arial; background: transparent;"
        )
        hdr.addWidget(title, stretch=1)
        close_btn = QPushButton("x")
        close_btn.setFixedSize(17, 15)
        close_btn.setCursor(Qt.CursorShape.ArrowCursor)
        close_btn.setStyleSheet(
            "QPushButton {"
            f"  background-color: {_CARD}; color: {_TEXT};"
            "  font-size: 9px; font-weight: 700;"
            f"  border-top: 2px solid {_BEVEL_LIGHT};"
            f"  border-left: 2px solid {_BEVEL_LIGHT};"
            f"  border-bottom: 2px solid {_BEVEL_SHADOW};"
            f"  border-right: 2px solid {_BEVEL_SHADOW};"
            "}"
        )
        close_btn.clicked.connect(self.closed.emit)
        hdr.addWidget(close_btn)
        root.addWidget(hdr_bar)
        root.addSpacing(8)

        # ── Miniature ─────────────────────────────────────────────────────────
        self._preview = _GradientThumb("???")
        self._preview.setFixedSize(self.WIDTH - 36, 150)
        root.addWidget(self._preview)
        root.addSpacing(14)

        # ── Nom ───────────────────────────────────────────────────────────────
        self._name_lbl = QLabel()
        self._name_lbl.setWordWrap(True)
        self._name_lbl.setStyleSheet(
            f"color: {_TEXT}; font-size: 11px; font-weight: 700;"
            "font-family: 'Work Sans', Arial; background: transparent;"
        )
        root.addWidget(self._name_lbl)
        root.addSpacing(4)

        # Badge type
        self._type_lbl = QLabel()
        self._type_lbl.setStyleSheet(
            f"color: {_BEVEL_LIGHT}; font-size: 9px; font-weight: 700;"
            f"background-color: {_ACCENT}; padding: 1px 6px; font-family: 'Work Sans', Arial;"
        )
        root.addWidget(self._type_lbl)
        root.addSpacing(8)

        # Separateur
        sep = QFrame()
        sep.setFixedHeight(2)
        sep.setStyleSheet(f"background-color: {_BEVEL_SHADOW}; border: 0px;")
        root.addWidget(sep)
        root.addSpacing(8)

        # ── Métadonnées ───────────────────────────────────────────────────────
        self._meta_widget = QWidget()
        self._meta_widget.setStyleSheet("background: transparent;")
        self._meta_lay = QVBoxLayout(self._meta_widget)
        self._meta_lay.setContentsMargins(0, 0, 0, 0)
        self._meta_lay.setSpacing(9)
        root.addWidget(self._meta_widget)
        root.addSpacing(14)

        # ── Barre d'integrite ─────────────────────────────────────────────────
        int_row = QHBoxLayout()
        int_lbl = QLabel("Intégrité:")
        int_lbl.setStyleSheet(
            f"color: {_TEXT}; font-size: 10px; font-family: 'Work Sans', Arial; background: transparent;"
        )
        self._int_pct_lbl = QLabel("-")
        self._int_pct_lbl.setStyleSheet(
            f"color: {_ACCENT}; font-size: 10px; font-weight: 700;"
            "font-family: 'Work Sans', Arial; background: transparent;"
        )
        int_row.addWidget(int_lbl, stretch=1)
        int_row.addWidget(self._int_pct_lbl)
        root.addLayout(int_row)
        root.addSpacing(4)

        self._int_bar = QProgressBar()
        self._int_bar.setFixedHeight(12)
        self._int_bar.setTextVisible(False)
        self._int_bar.setRange(0, 100)
        root.addWidget(self._int_bar)
        root.addStretch()

        # ── Bouton Recuperer ──────────────────────────────────────────────────
        self._recover_btn = QPushButton("Récupérer ce fichier")
        self._recover_btn.setFixedHeight(28)
        self._recover_btn.setCursor(Qt.CursorShape.ArrowCursor)
        self._recover_btn.clicked.connect(lambda: self.recover_requested.emit(self._info))
        root.addWidget(self._recover_btn)

    def show_file(self, info: dict, pixmap: QPixmap | None = None):
        self._info = info
        ftype = info.get("type", "???").upper()

        # Miniature
        self._preview._ftype  = ftype
        self._preview._pixmap = pixmap
        self._preview.update()

        # Nom
        self._name_lbl.setText(info.get("name", "Inconnu"))

        # Badge type
        self._type_lbl.setText(ftype)
        self._type_lbl.setStyleSheet(
            f"color: {_BEVEL_LIGHT}; background-color: {_ACCENT}; padding: 1px 6px;"
            "font-size: 9px; font-weight: 700; font-family: 'Work Sans', Arial;"
        )

        # Métadonnées
        while self._meta_lay.count():
            item = self._meta_lay.takeAt(0)
            if w := item.widget():
                w.deleteLater()

        size_kb  = info.get("size_kb", 0)
        size_str = f"{size_kb / 1024:.1f} Mo" if size_kb >= 1024 else f"{size_kb} Ko"
        offset   = info.get("offset", 0)
        device   = info.get("device", "—")

        rows: list[tuple[str, str, str]] = [
            ("Taille",  size_str),
            ("Source",  device),
            ("Offset",  f"0x{offset:X}" if offset else "-"),
            ("Mode",    "Simulation" if info.get("simulated") else "Réel"),
        ]
        if info.get("source") == "mft":
            deleted = info.get("deleted", False)
            statut  = "Supprimé" if deleted else "Actif"
            rows.append(("Statut",  statut))
            rows.append(("Origine", f"Nom d'origine ({info.get('fs', 'MFT')})"))
        if mft_path := info.get("mft_path"):
            rows.append(("Chemin",  mft_path))
        if fs_name := info.get("fs"):
            rows.append(("Système", fs_name))
        if (runs := info.get("data_runs")) and len(runs) > 1:
            rows.append(("Runs",    f"{len(runs)} fragments"))

        for lbl_text, val_text in rows:
            row_w = QWidget()
            row_w.setStyleSheet("background: transparent;")
            row_h = QHBoxLayout(row_w)
            row_h.setContentsMargins(0, 0, 0, 0)
            row_h.setSpacing(8)
            lbl_w = QLabel(f"{lbl_text}:")
            lbl_w.setFixedWidth(65)
            lbl_w.setStyleSheet(
                "color: #404040; font-size: 10px; font-family: 'Work Sans', Arial; background: transparent;"
            )
            val_w = QLabel(val_text)
            val_w.setWordWrap(True)
            val_w.setStyleSheet(
                f"color: {_TEXT}; font-size: 10px; font-family: 'Work Sans', Arial; background: transparent;"
            )
            row_h.addWidget(lbl_w)
            row_h.addWidget(val_w, stretch=1)
            self._meta_lay.addWidget(row_w)

        # Integrite
        integrity = info.get("integrity", 0)
        int_text  = _integrity_label(integrity)
        self._int_pct_lbl.setText(f"{integrity}%  {int_text}")
        int_col = f"{_OK}" if integrity >= 90 else (f"{_ACCENT}" if integrity >= 60 else f"{_WARN}")
        self._int_pct_lbl.setStyleSheet(
            f"color: {int_col}; font-size: 10px; font-weight: 700;"
            "font-family: 'Work Sans', Arial; background: transparent;"
        )
        self._int_bar.setValue(integrity)
        self._int_bar.setStyleSheet(
            "QProgressBar {"
            f"  background-color: {_BEVEL_LIGHT};"
            f"  border-top: 2px solid {_BEVEL_SHADOW}; border-left: 2px solid {_BEVEL_SHADOW};"
            f"  border-bottom: 2px solid {_BEVEL_LIGHT}; border-right: 2px solid {_BEVEL_LIGHT};"
            "}"
            f"QProgressBar::chunk {{ background-color: {int_col}; }}"
        )
        self.show()


# ═══════════════════════════════════════════════════════════════════════════════
#  Écran de résultats
# ═══════════════════════════════════════════════════════════════════════════════

class ResultsScreen(QWidget):
    new_scan_requested = pyqtSignal()

    _PAGE_SIZE = 500

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background-color: {_CARD};")

        self._all_files: list[dict]      = []
        self._thumbs:    list[FileThumb]  = []
        self._active_filter  = "Tous"
        self._search_text    = ""
        self._sort_key       = "integrity"
        self._hide_system    = False
        self._thumb_loader: _ThumbnailLoader | None = None
        self._displayed_count: int = 0
        self._last_grid_cols: int = 0
        self._search_filters_enabled = is_module_enabled("search-filters")
        self._reporting_suite_enabled = is_module_enabled("reporting-suite")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Barre d'en-tete Win98 ─────────────────────────────────────────────
        topbar = QWidget()
        topbar.setFixedHeight(62)
        topbar.setStyleSheet(
            f"background-color: {_PANEL};"
            f"border-bottom: 1px solid {_LINE};"
        )
        tb = QHBoxLayout(topbar)
        tb.setContentsMargins(18, 10, 18, 10)
        tb.setSpacing(10)

        self._title_lbl = QLabel("Fichiers récupérables")
        self._title_lbl.setStyleSheet(
            f"color: {_TEXT}; font-size: 15px; font-weight: 800;"
            f"font-family: {_FONT}; background: transparent;"
        )
        self._count_lbl = QLabel("")
        self._count_lbl.setStyleSheet(
            f"color: {_SUB}; font-size: 12px;"
            f"font-family: {_FONT}; background: transparent;"
        )
        tb.addWidget(self._title_lbl)
        tb.addSpacing(8)
        tb.addWidget(self._count_lbl)
        tb.addStretch()

        # Barre de recherche
        self._search = QLineEdit()
        self._search.setPlaceholderText("Rechercher...")
        self._search.setFixedSize(220, 32)
        self._search.textChanged.connect(self._on_search)
        tb.addWidget(self._search)

        # Bouton "Exporter le rapport" avec menu HTML / DFXML
        export_btn = QPushButton("Rapport")
        export_btn.setFixedSize(88, 32)
        export_btn.setCursor(Qt.CursorShape.ArrowCursor)
        export_btn.setStyleSheet(
            "QPushButton::menu-indicator { width: 0; image: none; }"
        )
        export_menu = QMenu(export_btn)
        act_html = QAction("Export HTML", export_menu)
        act_html.triggered.connect(self._on_export)
        export_menu.addAction(act_html)

        act_dfxml = QAction("Export DFXML", export_menu)
        act_dfxml.triggered.connect(self._on_export_dfxml)
        export_menu.addAction(act_dfxml)

        export_btn.setMenu(export_menu)
        tb.addWidget(export_btn)

        # Bouton "Nouveau scan"
        new_btn = QPushButton("Nouveau scan")
        new_btn.setFixedSize(118, 32)
        new_btn.setCursor(Qt.CursorShape.ArrowCursor)
        new_btn.clicked.connect(self.new_scan_requested)
        tb.addWidget(new_btn)

        root.addWidget(topbar)

        # ── Filtres Win98 ─────────────────────────────────────────────────────
        filter_bar = QWidget()
        filter_bar.setFixedHeight(48)
        filter_bar.setStyleSheet(
            f"background-color: {_CARD}; border-bottom: 1px solid {_LINE};"
        )
        fb = QHBoxLayout(filter_bar)
        fb.setContentsMargins(18, 8, 18, 8)
        fb.setSpacing(6)

        self._filter_btns: dict[str, QPushButton] = {}
        for label in ("Tous", "Images", "Vidéos", "Audio", "Documents", "Archives", "Autres"):
            btn = QPushButton(label)
            btn.setFixedHeight(28)
            btn.setCursor(Qt.CursorShape.ArrowCursor)
            btn.clicked.connect(lambda _, lbl=label: self._set_filter(lbl))
            self._filter_btns[label] = btn
            fb.addWidget(btn)

        # Bouton masquer fichiers systeme
        self._sys_toggle = QPushButton("Masq. système")
        self._sys_toggle.setFixedHeight(28)
        self._sys_toggle.setCheckable(True)
        self._sys_toggle.setCursor(Qt.CursorShape.ArrowCursor)
        self._sys_toggle.setToolTip("Masquer les fichiers système (EXE, DLL, SYS, TMP...)")
        self._sys_toggle.clicked.connect(self._on_sys_toggle)
        fb.addWidget(self._sys_toggle)

        fb.addStretch()

        # Tri
        sort_lbl = QLabel("Trier:")
        sort_lbl.setStyleSheet(
            f"color: {_SUB}; font-size: 12px; font-family: {_FONT}; background: transparent;"
        )
        fb.addWidget(sort_lbl)

        self._sort_combo = QComboBox()
        self._sort_combo.addItems(["Intégrité", "Taille", "Nom A-Z", "Type"])
        self._sort_combo.setFixedHeight(28)
        self._sort_combo.setFixedWidth(112)
        self._sort_combo.currentIndexChanged.connect(self._on_sort_changed)
        fb.addWidget(self._sort_combo)
        fb.addSpacing(8)

        # Selection / deselection
        self._sel_all_btn = QPushButton("Tout sélectionner")
        self._sel_all_btn.setFixedHeight(28)
        self._sel_all_btn.setCursor(Qt.CursorShape.ArrowCursor)
        self._sel_all_btn.clicked.connect(self._select_all)
        fb.addWidget(self._sel_all_btn)

        self._recover_btn = QPushButton("Récupérer")
        self._recover_btn.setFixedSize(96, 28)
        self._recover_btn.setCursor(Qt.CursorShape.ArrowCursor)
        self._recover_btn.clicked.connect(self._on_recover)
        self._recover_btn.setEnabled(False)
        fb.addWidget(self._recover_btn)

        self._update_filter_styles()
        root.addWidget(filter_bar)

        # ── Grille de resultats ───────────────────────────────────────────────
        scroll = QScrollArea()
        self._grid_scroll = scroll
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(
            f"QScrollArea {{ background-color: {_CARD}; border: none; }}"
        )

        self._grid_widget = QWidget()
        self._grid_widget.setStyleSheet(f"background-color: {_CARD};")
        self._grid = QGridLayout(self._grid_widget)
        self._grid.setContentsMargins(18, 18, 18, 18)
        self._grid.setSpacing(12)
        self._grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

        scroll.setWidget(self._grid_widget)

        # ── Panneau de detail lateral ─────────────────────────────────────────
        self._detail_panel = _FileDetailPanel()
        self._detail_panel.hide()
        self._detail_panel.closed.connect(self._detail_panel.hide)
        self._detail_panel.recover_requested.connect(self._on_detail_recover)

        main_area = QWidget()
        main_area.setStyleSheet(f"background-color: {_CARD};")
        main_lay = QHBoxLayout(main_area)
        main_lay.setContentsMargins(0, 0, 0, 0)
        main_lay.setSpacing(0)
        main_lay.addWidget(scroll, stretch=1)
        main_lay.addWidget(self._detail_panel)
        root.addWidget(main_area, stretch=1)

        # ── Message "aucun resultat" ───────────────────────────────────────────
        self._empty_lbl = QLabel("Aucun fichier trouve pour ce filtre.")
        self._empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_lbl.setStyleSheet(
            f"color: {_SUB}; font-size: 13px; font-family: {_FONT}; background: transparent;"
        )
        self._empty_lbl.hide()
        root.addWidget(self._empty_lbl)

        # ── Bouton "Charger X fichiers de plus" ───────────────────────────────
        self._load_more_btn = QPushButton()
        self._load_more_btn.setCursor(Qt.CursorShape.ArrowCursor)
        self._load_more_btn.setFixedHeight(34)
        self._load_more_btn.clicked.connect(self._load_more)
        self._load_more_btn.hide()

        load_more_wrap = QWidget()
        load_more_wrap.setStyleSheet(f"background-color: {_CARD};")
        load_more_lay = QHBoxLayout(load_more_wrap)
        load_more_lay.setContentsMargins(18, 8, 18, 10)
        load_more_lay.addStretch()
        load_more_lay.addWidget(self._load_more_btn)
        load_more_lay.addStretch()
        root.addWidget(load_more_wrap)
        self._load_more_wrap = load_more_wrap

    # ── API publique ──────────────────────────────────────────────────────────

    def load_results(self, files: list[dict]):
        self._all_files = files
        self._displayed_count = 0
        self._hide_system = False
        self._sys_toggle.setChecked(False)
        self._sys_toggle.setStyleSheet("")
        n = len(files)
        if n == 0:
            self._count_lbl.setText("Aucun fichier récupérable trouvé sur ce disque.")
            self._title_lbl.setText("Aucun résultat")
        else:
            plural = "s" if n > 1 else ""
            self._count_lbl.setText(f"{n} fichier{plural} récupérable{plural} détecté{plural}")
            self._title_lbl.setText("Fichiers récupérables")
        self._active_filter = "Tous"
        self._search_text   = ""
        self._search.clear()
        self._update_filter_counts()
        self._update_filter_styles()
        self._rebuild_grid()
        self._save_to_history(files)

    def _save_to_history(self, files: list[dict]):
        """Ajoute cette session à logs/history.json et sauvegarde la liste complète."""
        device = files[0].get("device", "—") if files else "—"
        ts = datetime.datetime.now()
        scan_fname = f"scan_{ts.strftime('%Y%m%d_%H%M%S')}.json"
        scan_path  = os.path.join(os.path.dirname(_HISTORY_PATH), scan_fname)
        entry = {
            "date":       ts.isoformat(timespec="seconds"),
            "device":     device,
            "file_count": len(files),
            "simulated":  bool(files and files[0].get("simulated")),
            "scan_file":  scan_path,
        }
        try:
            os.makedirs(os.path.dirname(_HISTORY_PATH), exist_ok=True)
            with open(scan_path, "w", encoding="utf-8") as fh:
                json.dump(files, fh, ensure_ascii=False)
            try:
                with open(_HISTORY_PATH, encoding="utf-8") as fh:
                    history = json.load(fh)
            except Exception:
                history = []
            history.insert(0, entry)
            history = history[:20]
            with open(_HISTORY_PATH, "w", encoding="utf-8") as fh:
                json.dump(history, fh, ensure_ascii=False, indent=2)
            # Purge orphan scan_*.json not referenced by any history entry
            referenced = {e.get("scan_file") for e in history}
            logs_dir = os.path.dirname(_HISTORY_PATH)
            for orphan in glob.glob(os.path.join(logs_dir, "scan_*.json")):
                if orphan not in referenced and orphan != scan_path:
                    with contextlib.suppress(OSError):
                        os.remove(orphan)
        except Exception:
            pass   # échec silencieux

    # ── Filtres & recherche ───────────────────────────────────────────────────

    def _on_sys_toggle(self, checked: bool):
        self._hide_system = checked
        if checked:
            self._sys_toggle.setStyleSheet(
                "QPushButton {"
                f"  background-color: #FFF4E5; color: {_WARN}; font-weight: 800;"
                f"  border: 1px solid {_WARN}; border-radius: 3px;"
                f"  font-family: {_FONT}; font-size: 12px;"
                "}"
            )
        else:
            self._sys_toggle.setStyleSheet("")
        self._displayed_count = 0
        self._rebuild_grid()

    def _set_filter(self, label: str):
        self._active_filter = label
        self._displayed_count = 0
        self._update_filter_styles()
        self._rebuild_grid()

    def _on_search(self, text: str):
        self._search_text = _normalize(text)
        self._displayed_count = 0
        self._rebuild_grid()

    def _on_sort_changed(self, idx: int):
        self._sort_key = ("integrity", "size", "name", "type")[idx]
        self._displayed_count = 0
        self._rebuild_grid()

    def _update_filter_counts(self):
        """Met à jour les labels des boutons de filtre avec le nombre de fichiers par catégorie."""
        counts: dict[str, int] = {lbl: 0 for lbl in self._filter_btns}
        counts["Tous"] = len(self._all_files)
        for f in self._all_files:
            ftype = f.get("type", "").upper()
            matched = False
            for group, types in _TYPE_GROUPS.items():
                if types and ftype in types:
                    counts[group] = counts.get(group, 0) + 1
                    matched = True
                    break
            if not matched:
                counts["Autres"] = counts.get("Autres", 0) + 1
        for lbl, btn in self._filter_btns.items():
            c = counts.get(lbl, 0)
            btn.setText(f"{lbl} ({c})" if c > 0 else lbl)

    def _update_filter_styles(self):
        for label, btn in self._filter_btns.items():
            if label == self._active_filter:
                btn.setStyleSheet(
                    "QPushButton {"
                    f"  background-color: {_ACCENT}; color: {_BEVEL_LIGHT};"
                    f"  border: 1px solid {_ACCENT}; border-radius: 3px;"
                    f"  font-family: {_FONT}; font-size: 12px; font-weight: 800;"
                    "}"
                )
            else:
                btn.setStyleSheet(
                    "QPushButton {"
                    f"  background-color: {_SURFACE}; color: {_TEXT};"
                    f"  border: 1px solid {_LINE}; border-radius: 3px;"
                    f"  font-family: {_FONT}; font-size: 12px;"
                    "}"
                    f"QPushButton:hover {{ background-color: {_HOVER}; }}"
                )

    def _filtered_files(self) -> list[dict]:
        if self._search_filters_enabled:
            return apply_filters(
                self._all_files,
                FilterCriteria(
                    query=self._search_text,
                    group=self._active_filter,
                    hide_system=self._hide_system,
                    sort_key=self._sort_key,
                ),
                type_groups=_TYPE_GROUPS,
                system_types=_SYSTEM_TYPES,
            )

        result = []
        for f in self._all_files:
            ftype = f.get("type", "").upper()

            # Filtre fichiers système
            if self._hide_system and ftype in _SYSTEM_TYPES:
                continue

            # Filtre par catégorie
            if self._active_filter != "Tous":
                group = _TYPE_GROUPS.get(self._active_filter, set())
                if self._active_filter == "Autres":
                    in_any = any(ftype in g for g in _TYPE_GROUPS.values() if g)
                    if in_any:
                        continue
                elif ftype not in group:
                    continue

            # Filtre par recherche
            if self._search_text:
                name_norm = _normalize(f.get("name", ""))
                if self._search_text not in name_norm:
                    continue

            result.append(f)

        # Tri
        if self._sort_key == "integrity":
            result.sort(key=lambda f: f.get("integrity", 0), reverse=True)
        elif self._sort_key == "size":
            result.sort(key=lambda f: f.get("size_kb", 0), reverse=True)
        elif self._sort_key == "name":
            result.sort(key=lambda f: f.get("name", "").lower())
        elif self._sort_key == "type":
            result.sort(key=lambda f: f.get("type", ""))

        return result

    # ── Construction de la grille ─────────────────────────────────────────────

    def _rebuild_grid(self):
        # Supprimer les anciennes miniatures
        for thumb in self._thumbs:
            thumb.setParent(None)
            thumb.deleteLater()
        self._thumbs.clear()

        while self._grid.count():
            item = self._grid.takeAt(0)
            if w := item.widget():
                w.deleteLater()

        visible = self._filtered_files()

        if not visible:
            if not self._all_files:
                self._empty_lbl.setText(
                    "Aucun fichier récupérable n'a été trouvé.\n"
                    "Essayez le Scan Complet pour une analyse approfondie."
                )
            else:
                self._empty_lbl.setText("Aucun fichier ne correspond à ce filtre ou à cette recherche.")
            self._empty_lbl.show()
            self._load_more_btn.hide()
            self._recover_btn.setEnabled(False)
            return

        self._empty_lbl.hide()

        # Pagination : on affiche au plus _displayed_count fichiers.
        # Si _displayed_count == 0, on initialise à _PAGE_SIZE.
        if self._displayed_count == 0:
            self._displayed_count = self._PAGE_SIZE

        to_display = visible[: self._displayed_count]
        reste = len(visible) - len(to_display)

        cols = self._grid_column_count()
        self._last_grid_cols = cols
        for i, info in enumerate(to_display):
            thumb = FileThumb(info)
            thumb.selection_changed.connect(self._on_selection_changed)
            thumb.detail_requested.connect(self._on_detail_requested)
            self._thumbs.append(thumb)
            self._grid.addWidget(thumb, i // cols, i % cols)

        self._on_selection_changed(False)   # mettre à jour le bouton Récupérer

        # Bouton "Charger X fichiers de plus"
        if reste > 0:
            plural = "s" if reste > 1 else ""
            self._load_more_btn.setText(f"Charger {reste} fichier{plural} de plus")
            self._load_more_btn.show()
            self._load_more_wrap.show()
        else:
            self._load_more_btn.hide()

        # ── Chargement asynchrone des vraies miniatures images ───────────────
        if self._thumb_loader:
            self._thumb_loader.stop()
            self._thumb_loader.finished.connect(self._thumb_loader.deleteLater)
            self._thumb_loader = None

        image_items = [
            (i, info) for i, info in enumerate(to_display)
            if info.get("type", "").upper() in _THUMB_IMAGE_TYPES
            and not info.get("simulated")
            and info.get("device")
        ]
        if image_items:
            self._thumb_loader = _ThumbnailLoader(image_items)
            self._thumb_loader.ready.connect(self._on_thumb_ready)
            self._thumb_loader.start()

    def _grid_column_count(self) -> int:
        spacing = self._grid.spacing()
        available = max(1, self._grid_scroll.viewport().width() - 36)
        return max(1, min(6, available // (FileThumb.W + spacing)))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._all_files and self._grid_column_count() != self._last_grid_cols:
            QTimer.singleShot(0, self._rebuild_grid)

    def showEvent(self, event):
        super().showEvent(event)
        if self._all_files:
            QTimer.singleShot(0, self._rebuild_grid)

    def _load_more(self):
        """Charge une page supplémentaire de FileThumb."""
        self._displayed_count += self._PAGE_SIZE
        self._rebuild_grid()

    def _on_thumb_ready(self, idx: int, image: QImage):
        """Reçu depuis _ThumbnailLoader — conversion QImage → QPixmap dans le thread principal."""
        if 0 <= idx < len(self._thumbs):
            self._thumbs[idx].set_real_thumb(QPixmap.fromImage(image))

    # ── Sélection ─────────────────────────────────────────────────────────────

    def _on_selection_changed(self, _):
        n_sel = sum(1 for t in self._thumbs if t.is_selected())
        self._recover_btn.setEnabled(n_sel > 0)
        if n_sel > 0:
            self._recover_btn.setText(f"⬇  Récupérer ({n_sel})")
        else:
            self._recover_btn.setText("⬇  Récupérer")

        # Texte du bouton sélection
        n_vis = len(self._thumbs)
        if n_sel == n_vis and n_vis > 0:
            self._sel_all_btn.setText("Tout désélectionner")
        else:
            self._sel_all_btn.setText("Tout sélectionner")

    def _select_all(self):
        n_sel = sum(1 for t in self._thumbs if t.is_selected())
        select = n_sel < len(self._thumbs)
        for t in self._thumbs:
            t.set_selected(select)
        self._on_selection_changed(False)

    # ── Export rapport ────────────────────────────────────────────────────────

    def _on_export(self):
        if not self._all_files:
            QMessageBox.information(self, "Aucun résultat", "Lancez d'abord un scan pour générer un rapport.")
            return

        path, _ = QFileDialog.getSaveFileName(
            self, "Enregistrer le rapport",
            os.path.join(os.path.expanduser("~"), f"lumina_rapport_{datetime.date.today()}.html"),
            "Rapport HTML (*.html)",
        )
        if not path:
            return

        if self._reporting_suite_enabled:
            from app.modules.reporting_suite import build_html_report

            html = build_html_report(self._all_files)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(html)

            msg = QMessageBox(self)
            msg.setWindowTitle("Rapport exporté")
            msg.setIcon(QMessageBox.Icon.Information)
            msg.setText("<b>Rapport enregistré avec succès.</b>")
            msg.setInformativeText(path)
            open_btn = msg.addButton("🌐  Ouvrir dans le navigateur", QMessageBox.ButtonRole.ActionRole)
            msg.addButton("Fermer", QMessageBox.ButtonRole.RejectRole)
            msg.exec()
            if msg.clickedButton() == open_btn:
                os.startfile(path)
            return

        # ── Comptages par catégorie ──────────────────────────────────────────
        counts: dict[str, int] = {}
        for f in self._all_files:
            ftype = f.get("type", "").upper()
            counts[ftype] = counts.get(ftype, 0) + 1

        total_kb = sum(f.get("size_kb", 0) for f in self._all_files)
        total_str = f"{total_kb / 1024:.1f} Mo" if total_kb >= 1024 else f"{total_kb} Ko"
        avg_int   = int(sum(f.get("integrity", 0) for f in self._all_files) / max(len(self._all_files), 1))
        device    = self._all_files[0].get("device", "—") if self._all_files else "—"
        now       = datetime.datetime.now().strftime("%d/%m/%Y à %H:%M")

        # ── Lignes du tableau ────────────────────────────────────────────────
        rows_html = ""
        for f in sorted(self._all_files, key=lambda x: x.get("integrity", 0), reverse=True):
            integrity = f.get("integrity", 0)
            col = "#34C759" if integrity >= 90 else ("#3B82F6" if integrity >= 60 else "#F59E0B")
            size_kb = f.get("size_kb", 0)
            size_str = f"{size_kb / 1024:.1f} Mo" if size_kb >= 1024 else f"{size_kb} Ko"
            rows_html += (
                f"<tr>"
                f"<td>{f.get('name','—')}</td>"
                f"<td>{f.get('type','—')}</td>"
                f"<td>{size_str}</td>"
                f"<td style='color:{col};font-weight:700'>{integrity}%</td>"
                f"<td style='color:#94A3B8;font-size:11px'>{f.get('device','—')}</td>"
                f"</tr>\n"
            )

        # ── Badges types ─────────────────────────────────────────────────────
        badges_html = "".join(
            f"<span class='badge'>{t} <b>{c}</b></span>"
            for t, c in sorted(counts.items(), key=lambda x: -x[1])
        )

        html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<title>Lumina — Rapport de scan</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: 'Segoe UI', Inter, sans-serif; background: #0F172A; color: #F1F5F9; padding: 40px; }}
  h1 {{ font-size: 26px; font-weight: 700; color: #F1F5F9; }}
  h1 span {{ color: #3B82F6; }}
  .meta {{ color: #64748B; font-size: 13px; margin-top: 6px; }}
  .stats {{ display: flex; gap: 16px; margin: 28px 0; }}
  .stat {{ background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.08);
           border-radius: 12px; padding: 16px 24px; min-width: 140px; }}
  .stat .val {{ font-size: 22px; font-weight: 700; color: #F1F5F9; }}
  .stat .lbl {{ font-size: 11px; color: #64748B; margin-top: 4px; letter-spacing: .5px; text-transform: uppercase; }}
  .badges {{ margin-bottom: 24px; display: flex; flex-wrap: wrap; gap: 8px; }}
  .badge {{ background: rgba(59,130,246,0.1); border: 1px solid rgba(59,130,246,0.3);
            border-radius: 20px; padding: 4px 12px; font-size: 12px; color: #94A3B8; }}
  .badge b {{ color: #3B82F6; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  thead th {{ background: rgba(255,255,255,0.06); padding: 10px 14px; text-align: left;
              color: #64748B; font-size: 10px; letter-spacing: 1px; text-transform: uppercase; }}
  tbody tr {{ border-bottom: 1px solid rgba(255,255,255,0.05); }}
  tbody tr:hover {{ background: rgba(255,255,255,0.03); }}
  tbody td {{ padding: 9px 14px; }}
  .footer {{ margin-top: 32px; color: #334155; font-size: 11px; text-align: center; }}
</style>
</head>
<body>
  <h1>Lumina — <span>Rapport de scan</span></h1>
  <p class="meta">Généré le {now} · Périphérique : {device}</p>

  <div class="stats">
    <div class="stat"><div class="val">{len(self._all_files)}</div><div class="lbl">Fichiers trouvés</div></div>
    <div class="stat"><div class="val">{total_str}</div><div class="lbl">Volume total</div></div>
    <div class="stat"><div class="val">{avg_int}%</div><div class="lbl">Intégrité moy.</div></div>
    <div class="stat"><div class="val">{len(counts)}</div><div class="lbl">Types détectés</div></div>
  </div>

  <div class="badges">{badges_html}</div>

  <table>
    <thead><tr><th>Nom</th><th>Type</th><th>Taille</th><th>Intégrité</th><th>Source</th></tr></thead>
    <tbody>{rows_html}</tbody>
  </table>

  <p class="footer">{DISPLAY_VERSION} — Rapport généré automatiquement</p>
</body>
</html>"""

        with open(path, "w", encoding="utf-8") as fh:
            fh.write(html)

        msg = QMessageBox(self)
        msg.setWindowTitle("Rapport exporté")
        msg.setIcon(QMessageBox.Icon.Information)
        msg.setText("<b>Rapport enregistré avec succès.</b>")
        msg.setInformativeText(path)
        open_btn = msg.addButton("🌐  Ouvrir dans le navigateur", QMessageBox.ButtonRole.ActionRole)
        msg.addButton("Fermer", QMessageBox.ButtonRole.RejectRole)
        msg.exec()
        if msg.clickedButton() == open_btn:
            os.startfile(path)

    # ── Export DFXML (Digital Forensics XML) ──────────────────────────────────

    def _on_export_dfxml(self):
        """
        Generate a DFXML 1.2.0 report of the current scan results.

        Each <fileobject> carries filename, filesize, byte_runs (img_offset),
        and — when the file has been extracted with SHA-256 — a <hashdigest>.
        Lumina-specific metadata (integrity, type, simulated flag) lives under
        the `lumina:` namespace to keep the document extensible without
        violating the DFXML schema.
        """
        if not self._all_files:
            QMessageBox.information(self, "Aucun résultat", "Lancez d'abord un scan pour générer un rapport.")
            return

        default_name = f"lumina_dfxml_{datetime.date.today()}.xml"
        path, _ = QFileDialog.getSaveFileName(
            self, "Enregistrer le rapport DFXML",
            os.path.join(os.path.expanduser("~"), default_name),
            "Rapport DFXML (*.xml)",
        )
        if not path:
            return

        if self._reporting_suite_enabled:
            from app.modules.reporting_suite import emit_dfxml

            source = str(self._all_files[0].get("device", "—")) if self._all_files else "—"
            emit_dfxml(self._all_files, source, path)
            _log.info("DFXML report exported: %s (%d fileobjects)", path, len(self._all_files))

            msg = QMessageBox(self)
            msg.setWindowTitle("Rapport DFXML exporté")
            msg.setIcon(QMessageBox.Icon.Information)
            msg.setText(f"<b>{len(self._all_files)} fileobject(s) écrit(s).</b>")
            msg.setInformativeText(path)
            open_btn = msg.addButton("📂  Ouvrir le dossier", QMessageBox.ButtonRole.ActionRole)
            msg.addButton("Fermer", QMessageBox.ButtonRole.RejectRole)
            msg.exec()
            if msg.clickedButton() == open_btn:
                os.startfile(os.path.dirname(path))
            return

        # ── Namespaces ──────────────────────────────────────────────────────
        ns_dfxml  = "http://www.forensicswiki.org/wiki/Category:Digital_Forensics_XML"
        ns_dc     = "http://purl.org/dc/elements/1.1/"
        ns_lumina = "https://lumina.local/dfxml-ext"
        ET.register_namespace("",       ns_dfxml)
        ET.register_namespace("dc",     ns_dc)
        ET.register_namespace("lumina", ns_lumina)

        def dfxml(tag: str) -> str:   return f"{{{ns_dfxml}}}{tag}"
        def dc(tag: str) -> str:      return f"{{{ns_dc}}}{tag}"
        def lumina(tag: str) -> str:  return f"{{{ns_lumina}}}{tag}"

        # ── Root ────────────────────────────────────────────────────────────
        root = ET.Element(dfxml("dfxml"), attrib={"xmloutputversion": "1.0"})

        now_iso = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

        meta = ET.SubElement(root, dfxml("metadata"))
        ET.SubElement(meta, dc("type")).text    = "Disk Image Carving Report"
        ET.SubElement(meta, dc("creator")).text = DISPLAY_VERSION
        ET.SubElement(meta, dc("date")).text    = now_iso

        creator = ET.SubElement(root, dfxml("creator"))
        ET.SubElement(creator, dfxml("program")).text = "Lumina"
        ET.SubElement(creator, dfxml("version")).text = VERSION
        execenv = ET.SubElement(creator, dfxml("execution_environment"))
        ET.SubElement(execenv, dfxml("os_sysname")).text = "Windows"
        ET.SubElement(execenv, dfxml("start_time")).text = now_iso

        # ── Source device metadata (from first file — all share the device) ─
        first = self._all_files[0]
        source = ET.SubElement(root, dfxml("source"))
        ET.SubElement(source, dfxml("device_name")).text  = str(first.get("device", "—"))
        ET.SubElement(source, dfxml("device_model")).text = str(first.get("model", "—"))
        ET.SubElement(source, dfxml("image_size")).text   = str(first.get("size_bytes", 0))
        ET.SubElement(source, lumina("scan_mode")).text   = (
            "quick" if first.get("simulated") else "deep"
        )
        ET.SubElement(source, lumina("file_count")).text = str(len(self._all_files))

        # ── One <fileobject> per file ───────────────────────────────────────
        for info in self._all_files:
            fo = ET.SubElement(root, dfxml("fileobject"))

            # Prefer the extracted name when available (e.g. deduped), else original
            name = info.get("extracted_name") or info.get("name", "recovered.bin")
            ET.SubElement(fo, dfxml("filename")).text = str(name)

            size_bytes = info.get("extracted_size")
            if size_bytes is None:
                size_bytes = int(info.get("size_kb", 0)) * 1024
            ET.SubElement(fo, dfxml("filesize")).text = str(size_bytes)

            byte_runs = ET.SubElement(fo, dfxml("byte_runs"))
            runs = info.get("data_runs") or []
            if runs:
                file_off = 0
                for run_offset, run_len in runs:
                    if run_len <= 0:
                        continue
                    ET.SubElement(byte_runs, dfxml("byte_run"), attrib={
                        "file_offset": str(file_off),
                        "img_offset":  str(run_offset),
                        "len":         str(run_len),
                    })
                    file_off += run_len
            else:
                ET.SubElement(byte_runs, dfxml("byte_run"), attrib={
                    "file_offset": "0",
                    "img_offset":  str(info.get("offset", 0)),
                    "len":         str(size_bytes),
                })

            sha256 = info.get("sha256")
            if sha256:
                ET.SubElement(
                    fo, dfxml("hashdigest"), attrib={"type": "sha256"}
                ).text = sha256

            ET.SubElement(fo, lumina("integrity")).text = str(info.get("integrity", 0))
            ET.SubElement(fo, lumina("filetype")).text  = str(info.get("type", "")).upper()
            if src := info.get("source"):
                ET.SubElement(fo, lumina("source")).text = src
            if fs_name := info.get("fs"):
                ET.SubElement(fo, lumina("fs")).text = fs_name
            if mft_path := info.get("mft_path"):
                ET.SubElement(fo, lumina("mft_path")).text = mft_path
            if info.get("simulated"):
                ET.SubElement(fo, lumina("simulated")).text = "true"
            if info.get("partial") or info.get("truncated"):
                ET.SubElement(fo, lumina("partial")).text = "true"
                if reason := info.get("partial_reason"):
                    ET.SubElement(fo, lumina("partial_reason")).text = str(reason)

        # ── Serialize ───────────────────────────────────────────────────────
        ET.indent(root, space="  ")
        tree = ET.ElementTree(root)
        tree.write(path, encoding="UTF-8", xml_declaration=True)

        _log.info("DFXML report exported: %s (%d fileobjects)", path, len(self._all_files))

        msg = QMessageBox(self)
        msg.setWindowTitle("Rapport DFXML exporté")
        msg.setIcon(QMessageBox.Icon.Information)
        msg.setText(f"<b>{len(self._all_files)} fileobject(s) écrit(s).</b>")
        msg.setInformativeText(path)
        open_btn = msg.addButton("📂  Ouvrir le dossier", QMessageBox.ButtonRole.ActionRole)
        msg.addButton("Fermer", QMessageBox.ButtonRole.RejectRole)
        msg.exec()
        if msg.clickedButton() == open_btn:
            os.startfile(os.path.dirname(path))

    # ── Panneau de détail ─────────────────────────────────────────────────────

    def _on_detail_requested(self, info: dict):
        """Affiche le panneau latéral avec les détails du fichier cliqué."""
        idx = next((i for i, t in enumerate(self._thumbs) if t.info is info), -1)
        pixmap = self._thumbs[idx]._thumb._pixmap if idx >= 0 else None
        self._detail_panel.show_file(info, pixmap)

    def _on_detail_recover(self, info: dict):
        """Récupération d'un seul fichier depuis le panneau de détail."""
        dest = QFileDialog.getExistingDirectory(
            self, "Choisir le dossier de destination", self._suggested_recovery_dir(),
        )
        if dest:
            self._start_extraction([info], dest)

    # ── Extraction ────────────────────────────────────────────────────────────

    def _on_recover(self):
        selected = [t.info for t in self._thumbs if t.is_selected()]
        if not selected:
            return
        dest = QFileDialog.getExistingDirectory(
            self, "Choisir le dossier de destination", self._suggested_recovery_dir(),
        )
        if dest:
            self._start_extraction(selected, dest)

    @staticmethod
    def _suggested_recovery_dir() -> str:
        path = default_recovery_dir()
        try:
            os.makedirs(path, exist_ok=True)
        except OSError as exc:
            _log.warning("Cannot create default recovery directory %s: %s", path, exc)
        return path

    def _start_extraction(self, selected: list[dict], dest: str):
        check = validate_recovery_destination(selected, dest)
        if check.blocked:
            _log.warning(
                "extraction_blocked destination=%s reason=%s",
                dest,
                check.message,
            )
            QMessageBox.critical(self, "Destination interdite", check.message)
            return
        if check.warning:
            reply = QMessageBox.warning(
                self,
                "Risque de récupération",
                f"{check.message}\n\nContinuer vers :\n{check.destination} ?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                _log.info(
                    "extraction_cancelled_after_warning destination=%s",
                    check.destination,
                )
                return

        persist_recovery_dir(check.destination)
        dest = str(check.destination)
        _log.info(
            "extraction_start source=%s destination=%s files=%d",
            selected[0].get("device", "—") if selected else "—",
            dest,
            len(selected),
        )

        if any(f.get("simulated") for f in selected):
            reply = QMessageBox.question(
                self,
                "Scan de simulation",
                "Ce scan était en mode simulation (Scan Rapide).\n"
                "Les fichiers extraits seront des fichiers vides avec des informations de texte.\n\n"
                "Pour extraire de véritables données, utilisez le Scan Complet.\n\n"
                "Continuer quand même ?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        prog = QProgressDialog(
            "Extraction en cours…", "Annuler", 0, len(selected) * 100, self
        )
        prog.setWindowTitle("Lumina — Récupération")
        prog.setWindowModality(Qt.WindowModality.WindowModal)
        prog.setMinimumDuration(0)
        prog.setValue(0)

        self._ext_worker = _ExtractionWorker(selected, dest)

        def _on_prog(n, name):
            if prog.wasCanceled():
                self._ext_worker.stop()
                return
            prog.setValue(n * 100)
            prog.setLabelText(f"Extraction de {name}…")

        def _on_file_prog(n, name, pct):
            if prog.wasCanceled():
                self._ext_worker.stop()
                return
            prog.setValue(min(len(selected) * 100, n * 100 + pct))
            prog.setLabelText(f"Extraction de {name}… {pct}%")

        prog.canceled.connect(self._ext_worker.stop)

        def _on_done(ok, fail):
            prog.setValue(len(selected) * 100)
            prog.close()
            _log.info(
                "extraction_finished destination=%s ok=%d fail=%d",
                dest, ok, fail,
            )
            # Warn about partial files before the summary dialog.
            partial_names = [
                f"{f.get('extracted_name') or f.get('name', '?')} ({f.get('partial_reason', 'partiel')})"
                for f in selected
                if f.get("partial") or f.get("truncated")
            ]
            if partial_names:
                names_txt = "\n".join(f"  - {n}" for n in partial_names)
                QMessageBox.warning(
                    self,
                    "Fichiers récupérés partiellement",
                    "Les fichiers suivants ne sont pas complets. Leur nom de "
                    "sortie indique clairement qu'ils sont partiels :\n\n" + names_txt,
                )
            msg = QMessageBox(self)
            msg.setWindowTitle("Récupération terminée")
            if fail == 0:
                msg.setIcon(QMessageBox.Icon.Information)
                msg.setText(f"<b>{ok} fichier(s) récupéré(s) avec succès.</b>")
            else:
                msg.setIcon(QMessageBox.Icon.Warning)
                msg.setText(
                    f"<b>{ok} fichier(s) récupéré(s)</b>, "
                    f"<span style='color:#F59E0B'>{fail} échec(s)</span>."
                )
            msg.setInformativeText(f"Dossier de destination :\n{dest}")
            open_btn = msg.addButton("📂  Ouvrir le dossier", QMessageBox.ButtonRole.ActionRole)
            msg.addButton("Fermer", QMessageBox.ButtonRole.RejectRole)
            msg.exec()
            if msg.clickedButton() == open_btn:
                os.startfile(dest)

        self._ext_worker.progress.connect(_on_prog)
        self._ext_worker.file_progress.connect(_on_file_prog)
        self._ext_worker.finished.connect(_on_done)
        self._ext_worker.start()
        prog.exec()
