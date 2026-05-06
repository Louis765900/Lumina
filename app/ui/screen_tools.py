"""
Lumina — Ecran 6 : Outils avances (style Windows 98)
Rapport S.M.A.R.T. fonctionnel ; autres outils prevus dans une future version.
"""

import logging
import pathlib

from PyQt6.QtCore import Qt, QThread, pyqtSignal
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
from app.modules import is_module_enabled
from app.ui.palette import (
    ACCENT as _ACCENT,
)
from app.ui.palette import (
    CARD as _CARD,
)
from app.ui.palette import (
    ERR as _ERR,
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

_PANEL = "#F8FAFC"
_SURFACE = "#FFFFFF"
_LINE = "#D0D5DD"
_SOFT_BLUE = "#EAF2FB"
_FONT = "'Segoe UI', Arial"

# Outils — (title, desc, badge, available, detail, action_id|None)
_TOOLS = [
    (
        "Analyseur hexadécimal",
        "Explorez le contenu brut de votre disque octet par octet.",
        "Avancé",
        False,
        "Ouvre une vue hexadécimale du disque sélectionné.\n\n"
        "- Parcourez les secteurs bruts (512 o / 4096 o)\n"
        "- Recherchez des signatures de fichiers (magic bytes)\n"
        "- Identifiez les tables de partition MBR/GPT\n"
        "- Exportez des plages de secteurs en fichier binaire",
        None,
    ),
    (
        "Rapport S.M.A.R.T.",
        "Consultez les indicateurs de santé de votre disque dur.",
        "Diagnostic",
        True,
        "Lit les attributs S.M.A.R.T. directement depuis le firmware du disque.\n\n"
        "- État général (OK / Dégradé / Critique)\n"
        "- Modèle, numéro de série, révision firmware\n"
        "- Interface (SATA, NVMe, USB...) et capacité\n"
        "- Nombre de partitions et type de média\n"
        "- Alerte prédictive de panne imminente",
        "launch_smart",
    ),
    (
        "Effacer les logs",
        "Supprimez lumina.log, l'historique et les rapports de scan.",
        "Maintenance",
        True,
        "Purge complète des fichiers de log Lumina.\n\n"
        "- Vide logs/lumina.log\n"
        "- Réinitialise logs/history.json à []\n"
        "- Supprime tous les logs/scan_*.json orphelins\n"
        "- Demande confirmation avant toute action",
        "purge_logs",
    ),
    (
        "Réparation de fichiers",
        "Reconstruisez des JPEG ou MP4 corrompus.",
        "Réparation",
        True,
        "Répare les fichiers média endommagés dont les marqueurs sont absents "
        "ou mal placés.\n\n"
        "- JPEG : restauration des marqueurs SOI/EOI manquants\n"
        "- JPEG : nettoyage des octets parasites avant le marqueur de début\n"
        "- JPEG : vérification des longueurs de segment\n"
        "- MP4/MOV : reordonnancement moov/mdat (fast-start)\n"
        "- MP4/MOV : détection des atomes invalides ou tronqués\n"
        "- Diagnostic en lecture seule avant écriture",
        "launch_repair",
    ),
    (
        "Récupération NAS",
        "Récupérez des données depuis un NAS (RAID 0, 1, 5, 6).",
        "Réseau",
        False,
        "Reconstruit les volumes RAID logiciels pour accéder aux données.\n\n"
        "- Supporte RAID 0, 1, 5, 6 et JBOD\n"
        "- Compatible Synology, QNAP, Netgear\n"
        "- Recalcule la parité pour les matrices dégradées\n"
        "- Monte le volume virtuel pour une récupération normale",
        None,
    ),
    (
        "Récupération Linux/macOS",
        "Lisez les partitions ext4, Btrfs, APFS et HFS+.",
        "Cross-OS",
        False,
        "Accède aux systèmes de fichiers non-Windows depuis Lumina.\n\n"
        "- Lecture ext2 / ext3 / ext4 (Linux)\n"
        "- Lecture Btrfs avec support des instantanés\n"
        "- Lecture APFS et HFS+ (macOS)\n"
        "- Récupération sur Time Machine et partitions Boot Camp",
        None,
    ),
    (
        "Récupération chiffrée",
        "Récupérez des données sur des volumes BitLocker ou VeraCrypt.",
        "Sécurité",
        False,
        "Déchiffre à la volée pour permettre la récupération de fichiers.\n\n"
        "- BitLocker (mot de passe ou clé de récupération 48 chiffres)\n"
        "- VeraCrypt (volume standard et volume caché)\n"
        "- La clé n'est jamais stockée sur disque\n"
        "- Compatible avec les disques partiellement corrompus",
        None,
    ),
    (
        "Récupération Cloud",
        "Synchronisez et récupérez depuis OneDrive, Google Drive, etc.",
        "Cloud",
        False,
        "Restaure des fichiers supprimés ou écrasés depuis les services cloud.\n\n"
        "- OneDrive, Google Drive, Dropbox, iCloud\n"
        "- Accède à la corbeille et à l'historique de versions\n"
        "- Télécharge directement vers un dossier local\n"
        "- Fonctionne même si le client de synchronisation est désinstallé",
        None,
    ),
]


# ═══════════════════════════════════════════════════════════════════════════════
#  Popup d'information
# ═══════════════════════════════════════════════════════════════════════════════


class _InfoDialog(QDialog):
    def __init__(self, title: str, detail: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"A propos — {title}")
        self.setFixedWidth(420)
        self.setStyleSheet(
            "QDialog { background-color: #C0C0C0; }QLabel  { font-family: 'Work Sans', Arial; }"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(10)

        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(
            "color: #000000; font-size: 13px; font-weight: 700;background: transparent;"
        )
        root.addWidget(title_lbl)

        sep = QFrame()
        sep.setFixedHeight(2)
        sep.setStyleSheet(
            "border-top: 1px solid #808080; border-bottom: 1px solid #FFFFFF;"
            "border-left: none; border-right: none;"
        )
        root.addWidget(sep)

        detail_lbl = QLabel(detail)
        detail_lbl.setWordWrap(True)
        detail_lbl.setStyleSheet("color: #000000; font-size: 11px; background: transparent;")
        root.addWidget(detail_lbl)

        close_btn = QPushButton("Fermer")
        close_btn.setFixedSize(80, 26)
        close_btn.setCursor(Qt.CursorShape.ArrowCursor)
        close_btn.clicked.connect(self.accept)
        root.addWidget(close_btn, alignment=Qt.AlignmentFlag.AlignRight)


# ═══════════════════════════════════════════════════════════════════════════════
#  Worker wmic (QThread)
# ═══════════════════════════════════════════════════════════════════════════════


class _SmartWorker(QThread):
    result = pyqtSignal(list)
    error = pyqtSignal(str)

    def run(self):
        try:
            from app.modules.disk_health import collect_disk_health

            self.result.emit(collect_disk_health())
        except Exception as exc:
            self.error.emit(str(exc))


# ═══════════════════════════════════════════════════════════════════════════════
#  Dialogue S.M.A.R.T.
# ═══════════════════════════════════════════════════════════════════════════════


class _SmartDialog(QDialog):
    def __init__(self, disks: list[dict], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Lumina — Rapport S.M.A.R.T.")
        self.setFixedSize(600, 500)
        self.setStyleSheet(
            "QDialog { background-color: #C0C0C0; }QLabel  { font-family: 'Work Sans', Arial; }"
        )
        self._disks = disks

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(10)

        hdr_row = QHBoxLayout()
        title = QLabel("Rapport S.M.A.R.T.")
        title.setStyleSheet(
            "color: #000000; font-size: 14px; font-weight: 700; background: transparent;"
        )
        hdr_row.addWidget(title)
        hdr_row.addStretch()

        if len(disks) > 1:
            self._combo = QComboBox()
            self._combo.setFixedWidth(260)
            self._combo.setFixedHeight(24)
            for d in disks:
                self._combo.addItem(d.get("Caption", "—"))
            self._combo.currentIndexChanged.connect(self._show_disk)
            hdr_row.addWidget(self._combo)
        else:
            self._combo = None

        root.addLayout(hdr_row)

        sep = QFrame()
        sep.setFixedHeight(2)
        sep.setStyleSheet(
            "border-top: 1px solid #808080; border-bottom: 1px solid #FFFFFF;"
            "border-left: none; border-right: none;"
        )
        root.addWidget(sep)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setStyleSheet("QScrollArea { background-color: #C0C0C0; border: none; }")
        self._content_widget = QWidget()
        self._content_widget.setStyleSheet("background-color: #C0C0C0;")
        self._content_lay = QVBoxLayout(self._content_widget)
        self._content_lay.setContentsMargins(0, 0, 0, 0)
        self._content_lay.setSpacing(6)
        self._scroll.setWidget(self._content_widget)
        root.addWidget(self._scroll, stretch=1)

        close_btn = QPushButton("Fermer")
        close_btn.setFixedSize(80, 26)
        close_btn.setCursor(Qt.CursorShape.ArrowCursor)
        close_btn.clicked.connect(self.accept)
        root.addWidget(close_btn, alignment=Qt.AlignmentFlag.AlignRight)

        self._show_disk(0)

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

        status = disk.get("Status", "Unknown") or "Unknown"
        ok = status.upper() == "OK"
        s_col = _OK if ok else (_ERR if "FAIL" in status.upper() else _WARN)

        banner = QFrame()
        banner.setFixedHeight(50)
        banner.setStyleSheet(
            "QFrame {"
            "  background-color: #C0C0C0;"
            "  border-top: 2px solid #FFFFFF; border-left: 2px solid #FFFFFF;"
            "  border-bottom: 2px solid #808080; border-right: 2px solid #808080;"
            "}"
        )
        ban_lay = QHBoxLayout(banner)
        ban_lay.setContentsMargins(12, 8, 12, 8)
        ban_lay.setSpacing(12)

        lbl_top = QLabel("ÉTAT S.M.A.R.T.")
        lbl_top.setStyleSheet(
            "color: #808080; font-size: 10px; font-weight: 700; background: transparent;"
        )
        lbl_val = QLabel(status)
        lbl_val.setStyleSheet(
            f"color: {s_col}; font-size: 14px; font-weight: 700; background: transparent;"
        )
        ban_lay.addWidget(lbl_top)
        ban_lay.addWidget(lbl_val)

        predict = disk.get("PredictFailure", "")
        if predict and predict.upper() == "TRUE":
            warn_lbl = QLabel("PANNE IMMINENTE PRÉDITE")
            warn_lbl.setStyleSheet(
                f"color: {_ERR}; font-size: 11px; font-weight: 700; background: transparent;"
            )
            ban_lay.addWidget(warn_lbl)

        ban_lay.addStretch()
        self._content_lay.addWidget(banner)

        size_bytes = int(disk.get("Size", 0) or 0)
        size_str = f"{size_bytes / (1024**3):.1f} Go" if size_bytes else "—"

        props = [
            ("Modèle", disk.get("Caption", "—") or "—"),
            ("Numéro de série", disk.get("SerialNumber", "—") or "—"),
            ("Interface", disk.get("InterfaceType", "—") or "—"),
            ("Capacité", size_str),
            ("Type de média", disk.get("MediaType", "—") or "—"),
            ("Révision firmware", disk.get("FirmwareRevision", "—") or "—"),
            ("Partitions", disk.get("Partitions", "—") or "—"),
        ]

        grid = QGridLayout()
        grid.setSpacing(6)
        for i, (label, value) in enumerate(props):
            card = QFrame()
            card.setFixedHeight(52)
            card.setStyleSheet(
                "QFrame {"
                "  background-color: #C0C0C0;"
                "  border-top: 2px solid #FFFFFF; border-left: 2px solid #FFFFFF;"
                "  border-bottom: 2px solid #808080; border-right: 2px solid #808080;"
                "}"
            )
            c_lay = QVBoxLayout(card)
            c_lay.setContentsMargins(10, 6, 10, 6)
            c_lay.setSpacing(2)

            lbl_h = QLabel(label.upper())
            lbl_h.setStyleSheet(
                "color: #808080; font-size: 9px; font-weight: 700; background: transparent;"
            )
            lbl_v = QLabel(value)
            lbl_v.setWordWrap(True)
            lbl_v.setStyleSheet(
                "color: #000000; font-size: 11px; font-weight: 600; background: transparent;"
            )
            c_lay.addWidget(lbl_h)
            c_lay.addWidget(lbl_v)
            grid.addWidget(card, i // 2, i % 2)

        grid_w = QWidget()
        grid_w.setStyleSheet("background-color: #C0C0C0;")
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
        title: str,
        desc: str,
        badge: str,
        available: bool = False,
        action=None,
        detail: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self.setObjectName("ToolCard")
        self.setFixedHeight(84)
        self.setStyleSheet(
            "QFrame#ToolCard {"
            f"  background-color: {_SURFACE};"
            f"  border: 1px solid {_LINE};"
            "  border-radius: 4px;"
            "}"
        )

        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 12, 14, 12)
        lay.setSpacing(14)

        txt = QVBoxLayout()
        txt.setSpacing(4)
        t = QLabel(title)
        t.setStyleSheet(
            f"color: {_TEXT}; font-size: 13px; font-weight: 800;"
            f"font-family: {_FONT}; background: transparent;"
        )
        d = QLabel(desc)
        d.setStyleSheet(
            f"color: {_SUB}; font-size: 12px;"
            f"font-family: {_FONT}; background: transparent;"
        )
        txt.addWidget(t)
        txt.addWidget(d)
        lay.addLayout(txt, stretch=1)

        bdg = QLabel(badge)
        bdg.setFixedHeight(22)
        bdg.setStyleSheet(
            f"color: {_ACCENT}; font-size: 10px; font-weight: 800;"
            f"background-color: {_SOFT_BLUE}; padding: 2px 8px;"
            f"border: 1px solid {_LINE}; border-radius: 3px;"
            f"font-family: {_FONT};"
        )
        lay.addWidget(bdg)

        info_btn = QPushButton("?")
        info_btn.setFixedSize(22, 22)
        info_btn.setCursor(Qt.CursorShape.ArrowCursor)
        info_btn.setToolTip("En savoir plus")
        info_btn.setStyleSheet(
            f"color: {_ACCENT}; font-weight: 800; font-family: {_FONT};"
            f"background-color: {_SOFT_BLUE}; border: 1px solid {_LINE};"
        )
        info_btn.clicked.connect(
            lambda checked, ti=title, de=detail: _InfoDialog(ti, de, self).exec()
        )
        lay.addWidget(info_btn)

        btn = QPushButton("Analyser")
        btn.setFixedSize(104, 32)
        btn.setCursor(Qt.CursorShape.ArrowCursor)
        if available:
            btn.clicked.connect(action)
        else:
            btn.setEnabled(False)
            btn.setStyleSheet(
                "QPushButton {"
                "  background-color: #C0C0C0; color: #808080;"
                "  border-top: 2px solid #FFFFFF; border-left: 2px solid #FFFFFF;"
                "  border-bottom: 2px solid #808080; border-right: 2px solid #808080;"
                "}"
            )
        lay.addWidget(btn)


# ═══════════════════════════════════════════════════════════════════════════════
#  Ecran outils
# ═══════════════════════════════════════════════════════════════════════════════

ensure_lumina_log()
_log = logging.getLogger("lumina.recovery")
_LOGS_DIR = pathlib.Path(__file__).parent.parent.parent / "logs"


class ToolsScreen(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background-color: {_CARD};")
        self._smart_worker: _SmartWorker | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # En-tete
        hdr = QWidget()
        hdr.setFixedHeight(62)
        hdr.setStyleSheet(
            f"background-color: {_PANEL}; border-bottom: 1px solid {_LINE};"
        )
        hr = QHBoxLayout(hdr)
        hr.setContentsMargins(18, 10, 18, 10)
        title = QLabel("Outils avancés")
        title.setStyleSheet(
            f"color: {_TEXT}; font-size: 15px; font-weight: 800;"
            f"font-family: {_FONT}; background: transparent;"
        )
        hr.addWidget(title)
        hr.addStretch()
        root.addWidget(hdr)

        # Zone scrollable
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(f"QScrollArea {{ background-color: {_CARD}; border: none; }}")

        cw = QWidget()
        cw.setStyleSheet(f"background-color: {_CARD};")
        lay = QVBoxLayout(cw)
        lay.setContentsMargins(18, 16, 18, 18)
        lay.setSpacing(8)
        lay.setAlignment(Qt.AlignmentFlag.AlignTop)

        # Badge info
        info_lbl = QLabel("Outils de maintenance et diagnostic disponibles pour Lumina V2 Windows.")
        info_lbl.setWordWrap(True)
        info_lbl.setStyleSheet(
            f"background-color: {_SURFACE}; color: {_TEXT}; font-size: 12px;"
            f"padding: 10px 12px; font-family: {_FONT};"
            f"border: 1px solid {_LINE}; border-radius: 4px;"
        )
        lay.addWidget(info_lbl)
        lay.addSpacing(4)

        for title_t, desc, badge, available, detail, action_id in _TOOLS:
            effective_available = available
            if action_id == "launch_smart":
                effective_available = effective_available and is_module_enabled("disk-health")
            if not effective_available:
                continue
            action = getattr(self, f"_{action_id}", None) if action_id else None
            lay.addWidget(_ToolCard(title_t, desc, badge, effective_available, action, detail))

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
                self,
                "S.M.A.R.T.",
                "Aucun disque détecté via le module disk-health.\n"
                "Assurez-vous de lancer Lumina en tant qu'administrateur.",
            )
            return
        dlg = _SmartDialog(disks, self)
        dlg.exec()

    def _on_smart_error(self, msg: str):
        QMessageBox.critical(
            self,
            "Erreur S.M.A.R.T.",
            f"Impossible de lire les données disque :\n{msg}",
        )

    # ── Reparation de fichiers ─────────────────────────────────────────────

    def _launch_repair(self):
        from app.ui.repair_dialog import RepairDialog

        dlg = RepairDialog(self)
        dlg.exec()

    # ── Purge des logs ────────────────────────────────────────────────────────

    def _purge_logs(self):
        history_path = _LOGS_DIR / "history.json"
        log_path = _LOGS_DIR / "lumina.log"
        scan_files = list(_LOGS_DIR.glob("scan_*.json"))

        reply = QMessageBox.question(
            self,
            "Effacer les logs",
            f"Cette action supprimera :\n"
            f"  - lumina.log\n"
            f"  - history.json (réinitialisé à [])\n"
            f"  - {len(scan_files)} rapport(s) scan_*.json\n\n"
            "Cette opération est irréversible. Continuer ?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        errors: list[str] = []

        try:
            if log_path.exists():
                log_path.write_text("", encoding="utf-8")
        except OSError as e:
            errors.append(f"lumina.log : {e}")

        try:
            history_path.write_text("[]", encoding="utf-8")
        except OSError as e:
            errors.append(f"history.json : {e}")

        deleted = 0
        for f in scan_files:
            try:
                f.unlink()
                deleted += 1
            except OSError as e:
                errors.append(f"{f.name} : {e}")

        _log.info("Purge des logs effectuee — %d scan_*.json supprime(s).", deleted)

        if errors:
            QMessageBox.warning(
                self,
                "Purge partielle",
                "Certains fichiers n'ont pas pu être supprimés :\n\n" + "\n".join(errors),
            )
        else:
            QMessageBox.information(
                self,
                "Logs effacés",
                f"Logs purgés avec succès.\n"
                f"  - lumina.log vide\n"
                f"  - history.json réinitialisé\n"
                f"  - {deleted} rapport(s) scan supprimé(s)",
            )
