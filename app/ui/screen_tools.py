"""
Lumina — Ecran 6 : Outils avances (style Windows 98)
Rapport S.M.A.R.T. fonctionnel ; autres outils prevus dans une future version.
"""

import logging
import pathlib
import subprocess

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
from app.ui.palette import (
    ERR as _ERR,
)
from app.ui.palette import (
    OK as _OK,
)
from app.ui.palette import (
    WARN as _WARN,
)

# Outils — (title, desc, badge, available, detail, action_id|None)
_TOOLS = [
    ("Analyseur Hexadecimal",
     "Explorez le contenu brut de votre disque octet par octet.",
     "Avance", False,
     "Ouvre une vue hexadecimale du disque selectionne.\n\n"
     "- Parcourez les secteurs bruts (512 o / 4096 o)\n"
     "- Recherchez des signatures de fichiers (magic bytes)\n"
     "- Identifiez les tables de partition MBR/GPT\n"
     "- Exportez des plages de secteurs en fichier binaire",
     None),

    ("Rapport S.M.A.R.T.",
     "Consultez les indicateurs de sante de votre disque dur.",
     "Diagnostic", True,
     "Lit les attributs S.M.A.R.T. directement depuis le firmware du disque.\n\n"
     "- Etat general (OK / Degrade / Critique)\n"
     "- Modele, numero de serie, revision firmware\n"
     "- Interface (SATA, NVMe, USB...) et capacite\n"
     "- Nombre de partitions et type de media\n"
     "- Alerte predictive de panne imminente",
     "launch_smart"),

    ("Effacer les logs",
     "Supprimez lumina.log, l'historique et les rapports de scan.",
     "Maintenance", True,
     "Purge complete des fichiers de log Lumina.\n\n"
     "- Vide logs/lumina.log\n"
     "- Reinitialise logs/history.json a []\n"
     "- Supprime tous les logs/scan_*.json orphelins\n"
     "- Demande confirmation avant toute action",
     "purge_logs"),

    ("Recuperation NAS",
     "Recuperez des donnees depuis un NAS (RAID 0, 1, 5, 6).",
     "Reseau", False,
     "Reconstruit les volumes RAID logiciels pour acceder aux donnees.\n\n"
     "- Supporte RAID 0, 1, 5, 6 et JBOD\n"
     "- Compatible Synology, QNAP, Netgear\n"
     "- Recalcule la parite pour les matrices degradees\n"
     "- Monte le volume virtuel pour une recuperation normale",
     None),

    ("Recuperation Linux/macOS",
     "Lisez les partitions ext4, Btrfs, APFS et HFS+.",
     "Cross-OS", False,
     "Accede aux systemes de fichiers non-Windows depuis Lumina.\n\n"
     "- Lecture ext2 / ext3 / ext4 (Linux)\n"
     "- Lecture Btrfs avec support des instantanes\n"
     "- Lecture APFS et HFS+ (macOS)\n"
     "- Recuperation sur Time Machine et partitions Boot Camp",
     None),

    ("Recuperation chiffree",
     "Recuperez des donnees sur des volumes BitLocker ou VeraCrypt.",
     "Securite", False,
     "Dechiffre a la volee pour permettre la recuperation de fichiers.\n\n"
     "- BitLocker (mot de passe ou cle de recuperation 48 chiffres)\n"
     "- VeraCrypt (volume standard et volume cache)\n"
     "- La cle n'est jamais stockee sur disque\n"
     "- Compatible avec les disques partiellement corrompus",
     None),

    ("Recuperation Cloud",
     "Synchronisez et recuperez depuis OneDrive, Google Drive, etc.",
     "Cloud", False,
     "Restaure des fichiers supprimes ou ecrases depuis les services cloud.\n\n"
     "- OneDrive, Google Drive, Dropbox, iCloud\n"
     "- Accede a la corbeille et a l'historique de versions\n"
     "- Telecharge directement vers un dossier local\n"
     "- Fonctionne meme si le client de synchronisation est desinstalle",
     None),
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
            "QDialog { background-color: #C0C0C0; }"
            "QLabel  { font-family: 'Work Sans', Arial; }"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(10)

        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(
            "color: #000000; font-size: 13px; font-weight: 700;"
            "background: transparent;"
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
        detail_lbl.setStyleSheet(
            "color: #000000; font-size: 11px; background: transparent;"
        )
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
            if isinstance(data, dict):
                data = [data]
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
        self.setFixedSize(600, 500)
        self.setStyleSheet(
            "QDialog { background-color: #C0C0C0; }"
            "QLabel  { font-family: 'Work Sans', Arial; }"
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
        self._scroll.setStyleSheet(
            "QScrollArea { background-color: #C0C0C0; border: none; }"
        )
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
        ok     = (status.upper() == "OK")
        s_col  = _OK if ok else (_ERR if "FAIL" in status.upper() else _WARN)

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

        lbl_top = QLabel("ETAT S.M.A.R.T.")
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
            warn_lbl = QLabel("PANNE IMMINENTE PREDITE")
            warn_lbl.setStyleSheet(
                f"color: {_ERR}; font-size: 11px; font-weight: 700; background: transparent;"
            )
            ban_lay.addWidget(warn_lbl)

        ban_lay.addStretch()
        self._content_lay.addWidget(banner)

        size_bytes = int(disk.get("Size", 0) or 0)
        size_str   = f"{size_bytes / (1024 ** 3):.1f} Go" if size_bytes else "—"

        props = [
            ("Modele",           disk.get("Caption",          "—") or "—"),
            ("Numero de serie",  disk.get("SerialNumber",     "—") or "—"),
            ("Interface",        disk.get("InterfaceType",    "—") or "—"),
            ("Capacite",         size_str),
            ("Type de media",    disk.get("MediaType",        "—") or "—"),
            ("Revision firmware",disk.get("FirmwareRevision", "—") or "—"),
            ("Partitions",       disk.get("Partitions",       "—") or "—"),
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
        self.setFixedHeight(72)
        self.setStyleSheet(
            "_ToolCard {"
            "  background-color: #C0C0C0;"
            "  border-top: 2px solid #FFFFFF; border-left: 2px solid #FFFFFF;"
            "  border-bottom: 2px solid #808080; border-right: 2px solid #808080;"
            "}"
        )

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(12)

        txt = QVBoxLayout()
        txt.setSpacing(4)
        t = QLabel(title)
        t.setStyleSheet(
            "color: #000000; font-size: 12px; font-weight: 700;"
            "font-family: 'Work Sans', Arial; background: transparent;"
        )
        d = QLabel(desc)
        d.setStyleSheet(
            "color: #404040; font-size: 11px;"
            "font-family: 'Work Sans', Arial; background: transparent;"
        )
        txt.addWidget(t)
        txt.addWidget(d)
        lay.addLayout(txt, stretch=1)

        bdg = QLabel(badge)
        bdg.setFixedHeight(18)
        bdg.setStyleSheet(
            "color: #FFFFFF; font-size: 9px; font-weight: 700;"
            "background-color: #000080; padding: 0px 6px;"
            "font-family: 'Work Sans', Arial;"
        )
        lay.addWidget(bdg)

        info_btn = QPushButton("?")
        info_btn.setFixedSize(22, 22)
        info_btn.setCursor(Qt.CursorShape.ArrowCursor)
        info_btn.setToolTip("En savoir plus")
        info_btn.clicked.connect(
            lambda checked, ti=title, de=detail:
                _InfoDialog(ti, de, self).exec()
        )
        lay.addWidget(info_btn)

        btn = QPushButton("Analyser" if available else "Bientot dispo")
        btn.setFixedSize(100, 26)
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
        self.setStyleSheet("background-color: #C0C0C0;")
        self._smart_worker: _SmartWorker | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # En-tete
        hdr = QWidget()
        hdr.setFixedHeight(40)
        hdr.setStyleSheet(
            "background-color: #C0C0C0; border-bottom: 2px solid #808080;"
        )
        hr = QHBoxLayout(hdr)
        hr.setContentsMargins(8, 4, 8, 4)
        title = QLabel("Outils avances")
        title.setStyleSheet(
            "color: #000000; font-size: 12px; font-weight: 700;"
            "font-family: 'Work Sans', Arial; background: transparent;"
        )
        hr.addWidget(title)
        hr.addStretch()
        root.addWidget(hdr)

        # Zone scrollable
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background-color: #C0C0C0; border: none; }")

        cw = QWidget()
        cw.setStyleSheet("background-color: #C0C0C0;")
        lay = QVBoxLayout(cw)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(6)
        lay.setAlignment(Qt.AlignmentFlag.AlignTop)

        # Badge info
        info_lbl = QLabel(
            "Rapport S.M.A.R.T. et Effacer les logs disponibles  —  "
            "Les autres fonctionnalites arrivent dans une prochaine version."
        )
        info_lbl.setWordWrap(True)
        info_lbl.setStyleSheet(
            "background-color: #FFFFFF; color: #000000; font-size: 11px;"
            "padding: 6px 10px; font-family: 'Work Sans', Arial;"
            "border-top: 2px solid #808080; border-left: 2px solid #808080;"
            "border-bottom: 2px solid #FFFFFF; border-right: 2px solid #FFFFFF;"
        )
        lay.addWidget(info_lbl)
        lay.addSpacing(6)

        for title_t, desc, badge, available, detail, action_id in _TOOLS:
            action = getattr(self, f"_{action_id}", None) if action_id else None
            lay.addWidget(_ToolCard(title_t, desc, badge, available, action, detail))

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
                "Aucun disque detecte via wmic.\n"
                "Assurez-vous de lancer Lumina en tant qu'administrateur.",
            )
            return
        dlg = _SmartDialog(disks, self)
        dlg.exec()

    def _on_smart_error(self, msg: str):
        QMessageBox.critical(
            self, "Erreur S.M.A.R.T.",
            f"Impossible de lire les donnees disque :\n{msg}",
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
            f"  - lumina.log\n"
            f"  - history.json (reinitialise a [])\n"
            f"  - {len(scan_files)} rapport(s) scan_*.json\n\n"
            "Cette operation est irreversible. Continuer ?",
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
                self, "Purge partielle",
                "Certains fichiers n'ont pas pu etre supprimes :\n\n"
                + "\n".join(errors),
            )
        else:
            QMessageBox.information(
                self, "Logs effaces",
                f"Logs purges avec succes.\n"
                f"  - lumina.log vide\n"
                f"  - history.json reinitialise\n"
                f"  - {deleted} rapport(s) scan supprime(s)",
            )
