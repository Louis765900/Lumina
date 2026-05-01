"""
Lumina v2.0 — Écran 6 : Outils avancés
Rapport S.M.A.R.T. fonctionnel (wmic) ; autres outils prévus dans une future version.
"""

import logging
import pathlib
import subprocess

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.core.recovery import ensure_lumina_log
from app.ui.palette import (
    ACCENT as _ACCENT,
)
from app.ui.palette import (
    BORDER as _BORDER,
)
from app.ui.palette import (
    CARD as _CARD,
)
from app.ui.palette import (
    ERR as _ERR,
)
from app.ui.palette import (
    HOVER as _HOVER,
)
from app.ui.palette import (
    MUTED as _MUTED,
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

# Outils — (icon, title, desc, badge, badge_col, available, detail, action_id|None)
# action_id maps to a ToolsScreen method named f"_{action_id}"
_TOOLS = [
    ("🔬", "Analyseur Hexadécimal",
     "Explorez le contenu brut de votre disque octet par octet.",
     "Avancé",     "#8B5CF6", False,
     "Ouvre une vue hexadécimale du disque sélectionné.\n\n"
     "• Parcourez les secteurs bruts (512 o / 4096 o)\n"
     "• Recherchez des signatures de fichiers (magic bytes)\n"
     "• Identifiez les tables de partition MBR/GPT\n"
     "• Exportez des plages de secteurs en fichier binaire",
     None),

    ("📊", "Rapport S.M.A.R.T.",
     "Consultez les indicateurs de santé de votre disque dur.",
     "Diagnostic", "#3B82F6", True,
     "Lit les attributs S.M.A.R.T. directement depuis le firmware du disque.\n\n"
     "• État général (OK / Dégradé / Critique)\n"
     "• Modèle, numéro de série, révision firmware\n"
     "• Interface (SATA, NVMe, USB…) et capacité\n"
     "• Nombre de partitions et type de média\n"
     "• Alerte prédictive de panne imminente",
     "launch_smart"),

    ("🗑", "Effacer les logs",
     "Supprimez lumina.log, l'historique et les rapports de scan.",
     "Maintenance", "#64748B", True,
     "Purge complète des fichiers de log Lumina.\n\n"
     "• Vide logs/lumina.log\n"
     "• Réinitialise logs/history.json à []\n"
     "• Supprime tous les logs/scan_*.json orphelins\n"
     "• Demande confirmation avant toute action",
     "purge_logs"),

    ("🖧", "Récupération NAS",
     "Récupérez des données depuis un NAS (RAID 0, 1, 5, 6).",
     "Réseau",     "#10B981", False,
     "Reconstruit les volumes RAID logiciels pour accéder aux données.\n\n"
     "• Supporte RAID 0, 1, 5, 6 et JBOD\n"
     "• Compatible Synology, QNAP, Netgear\n"
     "• Recalcule la parité pour les matrices dégradées\n"
     "• Monte le volume virtuel pour une récupération normale",
     None),

    ("🐧", "Récupération Linux/macOS",
     "Lisez les partitions ext4, Btrfs, APFS et HFS+.",
     "Cross-OS",   "#F59E0B", False,
     "Accède aux systèmes de fichiers non-Windows depuis Lumina.\n\n"
     "• Lecture ext2 / ext3 / ext4 (Linux)\n"
     "• Lecture Btrfs avec support des instantanés\n"
     "• Lecture APFS et HFS+ (macOS)\n"
     "• Récupération sur Time Machine et partitions Boot Camp",
     None),

    ("🔐", "Récupération chiffrée",
     "Récupérez des données sur des volumes BitLocker ou VeraCrypt.",
     "Sécurité",   "#EF4444", False,
     "Déchiffre à la volée pour permettre la récupération de fichiers.\n\n"
     "• BitLocker (mot de passe ou clé de récupération 48 chiffres)\n"
     "• VeraCrypt (volume standard et volume caché)\n"
     "• La clé n'est jamais stockée sur disque\n"
     "• Compatible avec les disques partiellement corrompus",
     None),

    ("☁",  "Récupération Cloud",
     "Synchronisez et récupérez depuis OneDrive, Google Drive, etc.",
     "Cloud",      "#06B6D4", False,
     "Restaure des fichiers supprimés ou écrasés depuis les services cloud.\n\n"
     "• OneDrive, Google Drive, Dropbox, iCloud\n"
     "• Accède à la corbeille et à l'historique de versions\n"
     "• Télécharge directement vers un dossier local\n"
     "• Fonctionne même si le client de synchronisation est désinstallé",
     None),
]


# ═══════════════════════════════════════════════════════════════════════════════
#  Popup d'information
# ═══════════════════════════════════════════════════════════════════════════════

class _InfoDialog(QDialog):
    def __init__(self, icon: str, title: str, detail: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"À propos — {title}")
        self.setFixedWidth(400)
        self.setStyleSheet(
            "QDialog { background: #0F172A; border: 1px solid rgba(255,255,255,0.10);"
            "  border-radius: 14px; }"
            "QLabel  { font-family: 'Inter'; }"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)

        # En-tête : icône + titre
        hdr = QHBoxLayout()
        hdr.setSpacing(12)
        ico_lbl = QLabel(icon)
        ico_lbl.setFixedSize(42, 42)
        ico_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ico_lbl.setStyleSheet(
            "font-size: 20px; background: rgba(0,122,255,0.12);"
            "border-radius: 10px;"
        )
        hdr.addWidget(ico_lbl)
        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(
            f"color: {_TEXT}; font-size: 16px; font-weight: 700;"
        )
        hdr.addWidget(title_lbl, stretch=1)
        root.addLayout(hdr)

        # Séparateur
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background: {_BORDER}; border: none;")
        root.addWidget(sep)

        # Contenu détaillé
        detail_lbl = QLabel(detail)
        detail_lbl.setWordWrap(True)
        detail_lbl.setStyleSheet(
            f"color: {_SUB}; font-size: 12px; line-height: 1.6;"
        )
        root.addWidget(detail_lbl)

        # Bouton fermer
        close_btn = QPushButton("Fermer")
        close_btn.setFixedSize(80, 30)
        close_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        close_btn.setStyleSheet(
            f"QPushButton {{ background: {_CARD}; border: 1px solid {_BORDER};"
            f"  border-radius: 8px; color: {_SUB}; font-size: 11px; }}"
            f"QPushButton:hover {{ background: {_HOVER}; color: {_TEXT}; }}"
        )
        close_btn.clicked.connect(self.accept)
        root.addWidget(close_btn, alignment=Qt.AlignmentFlag.AlignRight)


# ═══════════════════════════════════════════════════════════════════════════════
#  Worker wmic (QThread)
# ═══════════════════════════════════════════════════════════════════════════════

class _SmartWorker(QThread):
    result = pyqtSignal(list)   # list[dict]
    error  = pyqtSignal(str)

    def run(self):
        try:
            import json as _json
            ps_cmd = (
                "Get-CimInstance Win32_DiskDrive | "
                "Select-Object Caption,SerialNumber,Status,Size,"
                "InterfaceType,MediaType,FirmwareRevision,Partitions | "
                "ConvertTo-Json -Depth 2"
            )
            raw = subprocess.check_output(
                ["powershell", "-NoProfile", "-NonInteractive",
                 "-Command", ps_cmd],
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=subprocess.CREATE_NO_WINDOW,
                timeout=20,
            )
            data = _json.loads(raw.strip())
            # ConvertTo-Json retourne un objet si 1 disque, liste si plusieurs
            if isinstance(data, dict):
                data = [data]
            # Normaliser les clés vers les mêmes noms qu'avant
            disks = []
            for d in data:
                disks.append({
                    "Caption":          str(d.get("Caption")          or "—"),
                    "SerialNumber":     str(d.get("SerialNumber")     or "—").strip(),
                    "Status":           str(d.get("Status")           or "Unknown"),
                    "Size":             str(d.get("Size")             or 0),
                    "InterfaceType":    str(d.get("InterfaceType")    or "—"),
                    "MediaType":        str(d.get("MediaType")        or "—"),
                    "FirmwareRevision": str(d.get("FirmwareRevision") or "—").strip(),
                    "Partitions":       str(d.get("Partitions")       or "—"),
                })
            self.result.emit([d for d in disks if d.get("Caption") != "—"])
        except Exception as exc:
            self.error.emit(str(exc))


# ═══════════════════════════════════════════════════════════════════════════════
#  Dialogue S.M.A.R.T.
# ═══════════════════════════════════════════════════════════════════════════════

class _SmartDialog(QDialog):
    def __init__(self, disks: list[dict], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Lumina — Rapport S.M.A.R.T.")
        self.setFixedSize(620, 510)
        self.setStyleSheet(
            "QDialog { background: #0F172A; }"
            "QLabel  { font-family: 'Inter'; }"
        )
        self._disks = disks

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 20)
        root.setSpacing(14)

        # Titre
        hdr_row = QHBoxLayout()
        title = QLabel("📊  Rapport S.M.A.R.T.")
        title.setStyleSheet(
            f"color: {_TEXT}; font-size: 18px; font-weight: 700;"
        )
        hdr_row.addWidget(title)
        hdr_row.addStretch()

        if len(disks) > 1:
            self._combo = QComboBox()
            self._combo.setFixedWidth(260)
            self._combo.setFixedHeight(30)
            for d in disks:
                self._combo.addItem(d.get("Caption", "—"))
            self._combo.setStyleSheet(
                f"QComboBox {{ background: {_CARD}; border: 1px solid {_BORDER};"
                f"  border-radius: 8px; color: {_SUB}; font-size: 11px; padding: 0 8px; }}"
                f"QComboBox QAbstractItemView {{ background: #1E293B; color: {_TEXT};"
                f"  selection-background-color: rgba(59,130,246,0.3); border: 1px solid {_BORDER}; }}"
                "QComboBox::drop-down { border: none; width: 18px; }"
            )
            self._combo.currentIndexChanged.connect(self._show_disk)
            hdr_row.addWidget(self._combo)
        else:
            self._combo = None

        root.addLayout(hdr_row)

        # Zone de contenu (scrollable)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
        )
        self._content_widget = QWidget()
        self._content_widget.setStyleSheet("background: transparent;")
        self._content_lay = QVBoxLayout(self._content_widget)
        self._content_lay.setContentsMargins(0, 0, 0, 0)
        self._content_lay.setSpacing(10)
        self._scroll.setWidget(self._content_widget)
        root.addWidget(self._scroll, stretch=1)

        # Bouton Fermer
        close_btn = QPushButton("Fermer")
        close_btn.setFixedSize(90, 32)
        close_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        close_btn.setStyleSheet(
            f"QPushButton {{ background: {_CARD}; border: 1px solid {_BORDER};"
            f"  border-radius: 8px; color: {_SUB}; font-size: 12px; }}"
            f"QPushButton:hover {{ background: {_HOVER}; color: {_TEXT}; }}"
        )
        close_btn.clicked.connect(self.accept)
        root.addWidget(close_btn, alignment=Qt.AlignmentFlag.AlignRight)

        self._show_disk(0)

    # ── Affichage d'un disque ─────────────────────────────────────────────────

    def _show_disk(self, idx: int):
        while self._content_lay.count():
            item = self._content_lay.takeAt(0)
            if w := item.widget():
                w.deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())

        if not self._disks or idx >= len(self._disks):
            return
        disk = self._disks[idx]

        # ── Bannière de statut ────────────────────────────────────────────────
        status   = disk.get("Status", "Unknown") or "Unknown"
        ok       = (status.upper() == "OK")
        s_col    = _OK if ok else (_ERR if "FAIL" in status.upper() else _WARN)
        s_bg     = "rgba(52,199,89,0.08)"  if ok else "rgba(239,68,68,0.08)"
        s_border = "rgba(52,199,89,0.25)"  if ok else "rgba(239,68,68,0.25)"
        s_icon   = "✅" if ok else "❌"

        banner = QFrame()
        banner.setStyleSheet(
            f"QFrame {{ background: {s_bg}; border: 1px solid {s_border}; border-radius: 12px; }}"
        )
        ban_lay = QHBoxLayout(banner)
        ban_lay.setContentsMargins(20, 14, 20, 14)
        ban_lay.setSpacing(14)

        ico_lbl = QLabel(s_icon)
        ico_lbl.setStyleSheet("font-size: 22px; background: transparent;")
        ban_lay.addWidget(ico_lbl)

        txt_col = QVBoxLayout()
        txt_col.setSpacing(2)
        lbl_top = QLabel("ÉTAT S.M.A.R.T.")
        lbl_top.setStyleSheet(
            f"color: {_MUTED}; font-size: 10px; font-weight: 700;"
            "letter-spacing: 1px; background: transparent;"
        )
        lbl_val = QLabel(status)
        lbl_val.setStyleSheet(
            f"color: {s_col}; font-size: 20px; font-weight: 700; background: transparent;"
        )
        txt_col.addWidget(lbl_top)
        txt_col.addWidget(lbl_val)
        ban_lay.addLayout(txt_col, stretch=1)

        predict = disk.get("PredictFailure", "")
        if predict and predict.upper() == "TRUE":
            warn_lbl = QLabel("⚠  Panne imminente prédite")
            warn_lbl.setStyleSheet(
                f"color: {_ERR}; font-size: 11px; font-weight: 700; background: transparent;"
            )
            ban_lay.addWidget(warn_lbl)

        self._content_lay.addWidget(banner)

        # ── Grille de propriétés ──────────────────────────────────────────────
        size_bytes = int(disk.get("Size", 0) or 0)
        size_str   = f"{size_bytes / (1024 ** 3):.1f} Go" if size_bytes else "—"

        props = [
            ("💾", "Modèle",           disk.get("Caption",          "—") or "—"),
            ("🔑", "Numéro de série",  disk.get("SerialNumber",     "—") or "—"),
            ("🔌", "Interface",        disk.get("InterfaceType",    "—") or "—"),
            ("📏", "Capacité",         size_str),
            ("💿", "Type de média",    disk.get("MediaType",        "—") or "—"),
            ("🔧", "Révision firmware",disk.get("FirmwareRevision", "—") or "—"),
            ("📂", "Partitions",       disk.get("Partitions",       "—") or "—"),
        ]

        grid = QGridLayout()
        grid.setSpacing(10)
        for i, (icon, label, value) in enumerate(props):
            card = QFrame()
            card.setStyleSheet(
                f"QFrame {{ background: {_CARD}; border: 1px solid {_BORDER};"
                "  border-radius: 10px; }}"
            )
            c_lay = QVBoxLayout(card)
            c_lay.setContentsMargins(14, 10, 14, 10)
            c_lay.setSpacing(4)

            lbl_h = QLabel(f"{icon}  {label.upper()}")
            lbl_h.setStyleSheet(
                f"color: {_MUTED}; font-size: 9px; font-weight: 700;"
                "letter-spacing: 0.8px; background: transparent;"
            )
            lbl_v = QLabel(value)
            lbl_v.setWordWrap(True)
            lbl_v.setStyleSheet(
                f"color: {_TEXT}; font-size: 12px; font-weight: 600; background: transparent;"
            )
            c_lay.addWidget(lbl_h)
            c_lay.addWidget(lbl_v)
            grid.addWidget(card, i // 2, i % 2)

        grid_w = QWidget()
        grid_w.setStyleSheet("background: transparent;")
        grid_w.setLayout(grid)
        self._content_lay.addWidget(grid_w)
        self._content_lay.addStretch()

    @staticmethod
    def _clear_layout(layout):
        while layout.count():
            item = layout.takeAt(0)
            if w := item.widget():
                w.deleteLater()


# ═══════════════════════════════════════════════════════════════════════════════
#  Carte d'outil
# ═══════════════════════════════════════════════════════════════════════════════

class _ToolCard(QFrame):
    def __init__(
        self,
        icon: str,
        title: str,
        desc: str,
        badge: str,
        badge_color: str,
        available: bool = False,
        action=None,
        detail: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self._hovered = False
        self.setFixedHeight(100)
        self._set_style(False)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

        lay = QHBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(18)

        # Icône avec couleur du badge
        # Convertir hex en rgba avec 20% opacité
        def _hex_to_rgba20(hex_col: str) -> str:
            h = hex_col.lstrip("#")
            r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
            return f"rgba({r},{g},{b},0.15)"

        ico = QLabel(icon)
        ico.setFixedSize(44, 44)
        ico.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ico.setStyleSheet(
            f"font-size: 22px; background: {_hex_to_rgba20(badge_color)};"
            f"color: {badge_color}; border-radius: 10px;"
        )
        lay.addWidget(ico)

        # Texte
        txt = QVBoxLayout()
        txt.setSpacing(5)
        t = QLabel(title)
        t.setStyleSheet(
            f"color: {_TEXT}; font-size: 14px; font-weight: 700;"
            "font-family: 'Inter'; background: transparent;"
        )
        d = QLabel(desc)
        d.setStyleSheet(
            f"color: {_MUTED}; font-size: 12px;"
            "font-family: 'Inter'; background: transparent;"
        )
        txt.addWidget(t)
        txt.addWidget(d)
        lay.addLayout(txt, stretch=1)

        # Badge
        bdg = QLabel(badge)
        bdg.setStyleSheet(
            f"color: {badge_color}; font-size: 10px; font-weight: 700;"
            "background: transparent; border-radius: 10px; padding: 3px 10px;"
            f"border: 1px solid {badge_color};"
        )
        lay.addWidget(bdg)

        # Bouton ⓘ
        info_btn = QPushButton("ⓘ")
        info_btn.setFixedSize(28, 28)
        info_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        info_btn.setToolTip("En savoir plus")
        info_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; border: 1px solid {_BORDER};"
            f"  border-radius: 14px; color: {_MUTED}; font-size: 13px; }}"
            f"QPushButton:hover {{ background: rgba(0,122,255,0.12);"
            f"  border-color: rgba(0,122,255,0.5); color: {_ACCENT}; }}"
        )
        info_btn.clicked.connect(
            lambda checked, ic=icon, ti=title, de=detail:
                _InfoDialog(ic, ti, de, self).exec()
        )
        lay.addWidget(info_btn)

        # Bouton action
        btn = QPushButton("Analyser →" if available else "Bientôt dispo")
        btn.setFixedSize(120, 32)
        btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        if available:
            btn.setStyleSheet(
                "QPushButton { background: qlineargradient(x1:0,y1:0,x2:1,y2:1,"
                "  stop:0 #adc6ff, stop:1 #4b8eff);"
                "  border: none; border-radius: 8px; color: #002e69;"
                "  font-size: 11px; font-weight: 700; }"
                "QPushButton:hover { background: qlineargradient(x1:0,y1:0,x2:1,y2:1,"
                "  stop:0 #c5d8ff, stop:1 #6ba3ff); }"
            )
            btn.clicked.connect(action)
        else:
            btn.setStyleSheet(
                f"QPushButton {{ background: rgba(255,255,255,0.05); border: none;"
                f"  border-radius: 8px; color: {_MUTED}; font-size: 11px; }}"
                f"QPushButton:hover {{ background: rgba(255,255,255,0.08); color: {_TEXT}; }}"
            )
            btn.clicked.connect(lambda checked, t=title: QMessageBox.information(
                self, "Bientôt disponible",
                f"« {t} » sera disponible dans une prochaine version de Lumina.\n\n"
                "Restez à l'affût des mises à jour !",
            ))
        lay.addWidget(btn)

    def _set_style(self, hovered: bool):
        if hovered:
            self.setStyleSheet(
                f"_ToolCard {{ background: rgba(255,255,255,0.07);"
                f"  border: 1px solid {_BORDER}; border-radius: 14px;"
                f"  border-left: 2px solid #adc6ff; }}"
            )
        else:
            self.setStyleSheet(
                f"_ToolCard {{ background: {_CARD}; border: 1px solid {_BORDER}; border-radius: 14px; }}"
            )

    def enterEvent(self, e):
        self._set_style(True)
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._set_style(False)
        super().leaveEvent(e)


# ═══════════════════════════════════════════════════════════════════════════════
#  Écran outils
# ═══════════════════════════════════════════════════════════════════════════════

ensure_lumina_log()
_log = logging.getLogger("lumina.recovery")
_LOGS_DIR = pathlib.Path(__file__).parent.parent.parent / "logs"


class ToolsScreen(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background: transparent;")
        self._smart_worker: _SmartWorker | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # En-tête
        hdr = QWidget()
        hdr.setFixedHeight(100)
        hdr.setStyleSheet("background: transparent;")
        hr = QHBoxLayout(hdr)
        hr.setContentsMargins(40, 20, 40, 20)
        col = QVBoxLayout()
        col.setSpacing(6)
        title = QLabel("Outils avancés")
        title.setStyleSheet(
            f"color: {_TEXT}; font-size: 22px; font-weight: 700; font-family: 'Inter';"
        )
        sub = QLabel("Des outils spécialisés pour les cas de récupération complexes.")
        sub.setStyleSheet(f"color: {_SUB}; font-size: 13px; font-family: 'Inter';")
        col.addWidget(title)
        col.addWidget(sub)
        hr.addLayout(col)
        root.addWidget(hdr)

        # Zone scrollable
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        cw = QWidget()
        cw.setStyleSheet("background: transparent;")
        lay = QVBoxLayout(cw)
        lay.setContentsMargins(40, 0, 40, 40)
        lay.setSpacing(14)
        lay.setAlignment(Qt.AlignmentFlag.AlignTop)

        # Badge info
        dev_badge = QLabel(
            "✅  Rapport S.M.A.R.T. et Effacer les logs disponibles  ·  "
            "🚧  Les autres fonctionnalités arrivent dans une prochaine version."
        )
        dev_badge.setWordWrap(True)
        dev_badge.setStyleSheet(
            "background: rgba(0,122,255,0.06); border: 1px solid rgba(0,122,255,0.2);"
            "border-radius: 10px; color: #94A3B8; font-size: 12px; padding: 10px 16px;"
            "font-family: 'Inter';"
        )
        lay.addWidget(dev_badge)
        lay.addSpacing(8)

        for icon, title_t, desc, badge, badge_col, available, detail, action_id in _TOOLS:
            action = getattr(self, f"_{action_id}", None) if action_id else None
            lay.addWidget(_ToolCard(icon, title_t, desc, badge, badge_col, available, action, detail))

        lay.addStretch()
        scroll.setWidget(cw)
        root.addWidget(scroll, stretch=1)

    # ── Lancement du rapport S.M.A.R.T. ─────────────────────────────────────

    def _launch_smart(self):
        if self._smart_worker and self._smart_worker.isRunning():
            return

        self._smart_worker = _SmartWorker()
        self._smart_worker.result.connect(self._on_smart_result)
        self._smart_worker.error.connect(self._on_smart_error)
        self._smart_worker.start()

    def _on_smart_result(self, disks: list[dict]):
        if not disks:
            QMessageBox.warning(
                self, "S.M.A.R.T.",
                "Aucun disque détecté via wmic.\n"
                "Assurez-vous de lancer Lumina en tant qu'administrateur.",
            )
            return
        dlg = _SmartDialog(disks, self)
        dlg.exec()

    def _on_smart_error(self, msg: str):
        QMessageBox.critical(
            self, "Erreur S.M.A.R.T.",
            f"Impossible de lire les données disque :\n{msg}",
        )

    # ── Purge des logs ────────────────────────────────────────────────────────

    def _purge_logs(self):
        history_path = _LOGS_DIR / "history.json"
        log_path     = _LOGS_DIR / "lumina.log"
        scan_files   = list(_LOGS_DIR.glob("scan_*.json"))

        reply = QMessageBox.question(
            self,
            "Effacer les logs",
            f"Cette action supprimera :\n"
            f"  • lumina.log\n"
            f"  • history.json (réinitialisé à [])\n"
            f"  • {len(scan_files)} rapport(s) scan_*.json\n\n"
            "Cette opération est irréversible. Continuer ?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        errors: list[str] = []

        # Vider lumina.log
        try:
            if log_path.exists():
                log_path.write_text("", encoding="utf-8")
        except OSError as e:
            errors.append(f"lumina.log : {e}")

        # Réinitialiser history.json
        try:
            history_path.write_text("[]", encoding="utf-8")
        except OSError as e:
            errors.append(f"history.json : {e}")

        # Supprimer les scan_*.json
        deleted = 0
        for f in scan_files:
            try:
                f.unlink()
                deleted += 1
            except OSError as e:
                errors.append(f"{f.name} : {e}")

        _log.info("Purge des logs effectuée — %d scan_*.json supprimé(s).", deleted)

        if errors:
            QMessageBox.warning(
                self, "Purge partielle",
                "Certains fichiers n'ont pas pu être supprimés :\n\n"
                + "\n".join(errors),
            )
        else:
            QMessageBox.information(
                self, "Logs effacés",
                f"Logs purgés avec succès.\n"
                f"  • lumina.log vidé\n"
                f"  • history.json réinitialisé\n"
                f"  • {deleted} rapport(s) scan supprimé(s)",
            )
