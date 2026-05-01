"""
Lumina — Ecran 5 : Diagnostic disque (style Windows 98)
Informations sur les partitions, lancement de CHKDSK et SFC depuis l'UI,
sans dependance a une API externe.
"""

import subprocess

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.core.disk_detector import DiskDetector
from app.ui.palette import (
    ERR as _ERR,
)
from app.ui.palette import (
    OK as _OK,
)
from app.ui.palette import (
    WARN as _WARN,
)


def _section_hdr(title: str) -> QWidget:
    w = QWidget()
    w.setFixedHeight(24)
    w.setStyleSheet("background-color: #C0C0C0;")
    row = QHBoxLayout(w)
    row.setContentsMargins(0, 4, 0, 0)
    row.setSpacing(8)
    lbl = QLabel(title.upper())
    lbl.setStyleSheet(
        "color: #000000; font-size: 10px; font-weight: 700;"
        "font-family: 'Work Sans', Arial; background: transparent;"
    )
    row.addWidget(lbl)
    row.addStretch()
    return w


# ═══════════════════════════════════════════════════════════════════════════════
#  Worker subprocess (QThread)
# ═══════════════════════════════════════════════════════════════════════════════

class _CmdWorker(QThread):
    output  = pyqtSignal(str)
    done    = pyqtSignal(int)

    def __init__(self, cmd: list[str], parent=None):
        super().__init__(parent)
        self._cmd = cmd

    def run(self):
        try:
            proc = subprocess.Popen(
                self._cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="cp850",
                errors="replace",
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            for line in proc.stdout:
                self.output.emit(line.rstrip())
            proc.wait()
            self.done.emit(proc.returncode)
        except Exception as exc:
            self.output.emit(f"[Erreur] {exc}")
            self.done.emit(-1)


# ═══════════════════════════════════════════════════════════════════════════════
#  Carte de stat disque
# ═══════════════════════════════════════════════════════════════════════════════

class _StatCard(QFrame):
    def __init__(self, label: str, value: str, color: str = "#000000", parent=None):
        super().__init__(parent)
        self.setFixedHeight(56)
        self.setStyleSheet(
            "_StatCard {"
            "  background-color: #C0C0C0;"
            "  border-top: 2px solid #FFFFFF; border-left: 2px solid #FFFFFF;"
            "  border-bottom: 2px solid #808080; border-right: 2px solid #808080;"
            "}"
        )
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)

        col = QVBoxLayout()
        col.setSpacing(2)
        lbl_w = QLabel(label)
        lbl_w.setStyleSheet(
            "color: #808080; font-size: 10px; font-weight: 700;"
            "font-family: 'Work Sans', Arial; background: transparent;"
        )
        val_w = QLabel(value)
        val_w.setStyleSheet(
            f"color: {color}; font-size: 13px; font-weight: 700;"
            "font-family: 'Work Sans', Arial; background: transparent;"
        )
        col.addWidget(lbl_w)
        col.addWidget(val_w)
        lay.addLayout(col, stretch=1)


# ═══════════════════════════════════════════════════════════════════════════════
#  Ecran de diagnostic
# ═══════════════════════════════════════════════════════════════════════════════

class RepairScreen(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background-color: #C0C0C0;")
        self._worker: _CmdWorker | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── En-tete ───────────────────────────────────────────────────────────
        hdr = QWidget()
        hdr.setFixedHeight(40)
        hdr.setStyleSheet(
            "background-color: #C0C0C0; border-bottom: 2px solid #808080;"
        )
        hr = QHBoxLayout(hdr)
        hr.setContentsMargins(8, 4, 8, 4)
        title = QLabel("Diagnostic disque")
        title.setStyleSheet(
            "color: #000000; font-size: 12px; font-weight: 700;"
            "font-family: 'Work Sans', Arial; background: transparent;"
        )
        hr.addWidget(title)
        hr.addStretch()
        root.addWidget(hdr)

        # ── Zone principale scrollable ────────────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background-color: #C0C0C0; border: none; }")

        cw = QWidget()
        cw.setStyleSheet("background-color: #C0C0C0;")
        lay = QVBoxLayout(cw)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(10)
        lay.setAlignment(Qt.AlignmentFlag.AlignTop)

        # ── Selecteur de disque ───────────────────────────────────────────────
        lay.addWidget(_section_hdr("Selectionner un disque"))

        sel_row = QHBoxLayout()
        self._disk_combo = QComboBox()
        self._disk_combo.setFixedWidth(320)
        self._disks: list[dict] = []
        self._load_disks()
        sel_row.addWidget(self._disk_combo)
        sel_row.addSpacing(8)

        analyze_btn = QPushButton("Analyser")
        analyze_btn.setFixedSize(90, 26)
        analyze_btn.setCursor(Qt.CursorShape.ArrowCursor)
        analyze_btn.clicked.connect(self._analyze)
        sel_row.addWidget(analyze_btn)
        sel_row.addStretch()
        lay.addLayout(sel_row)

        # ── Stats ─────────────────────────────────────────────────────────────
        lay.addWidget(_section_hdr("Informations du disque"))
        self._stats_container = QWidget()
        self._stats_container.setStyleSheet("background-color: #C0C0C0;")
        self._stats_lay = QHBoxLayout(self._stats_container)
        self._stats_lay.setContentsMargins(0, 0, 0, 0)
        self._stats_lay.setSpacing(8)
        self._stats_lay.addStretch()
        lay.addWidget(self._stats_container)

        # ── Outils de reparation ─────────────────────────────────────────────
        lay.addWidget(_section_hdr("Outils de reparation"))

        tools_grid = QHBoxLayout()
        tools_grid.setSpacing(8)

        self._chkdsk_btn = self._tool_btn("CHKDSK /scan", "Verification rapide du systeme de fichiers.")
        self._chkdsk_btn.clicked.connect(self._run_chkdsk)
        tools_grid.addWidget(self._chkdsk_btn)

        sfc_col = QVBoxLayout()
        sfc_col.setSpacing(4)
        self._sfc_btn = self._tool_btn("SFC", "Verification ou reparation des fichiers systeme.")
        self._sfc_btn.clicked.connect(self._run_sfc)
        self._sfc_combo = QComboBox()
        self._sfc_combo.addItem("Reparer (/scannow)",        "scannow")
        self._sfc_combo.addItem("Verifier seul (/verifyonly)", "verifyonly")
        self._sfc_combo.setFixedWidth(200)
        self._sfc_combo.setToolTip(
            "/scannow : repare les fichiers corrompus\n"
            "/verifyonly : verifie sans modifier"
        )
        sfc_col.addWidget(self._sfc_btn)
        sfc_col.addWidget(self._sfc_combo)
        tools_grid.addLayout(sfc_col)

        dism_col = QVBoxLayout()
        dism_col.setSpacing(4)
        self._dism_btn = self._tool_btn("DISM", "Controle ou reparation de l'image Windows.")
        self._dism_btn.clicked.connect(self._run_dism)
        self._dism_combo = QComboBox()
        self._dism_combo.addItem("Verification (/CheckHealth)",   "CheckHealth")
        self._dism_combo.addItem("Reparation (/RestoreHealth)",   "RestoreHealth")
        self._dism_combo.setFixedWidth(200)
        self._dism_combo.setToolTip(
            "/CheckHealth : verification rapide, hors ligne\n"
            "/RestoreHealth : repare via Windows Update (connexion internet requise)"
        )
        dism_col.addWidget(self._dism_btn)
        dism_col.addWidget(self._dism_combo)
        tools_grid.addLayout(dism_col)

        tools_grid.addStretch()
        lay.addLayout(tools_grid)

        # ── Console de sortie ─────────────────────────────────────────────────
        lay.addWidget(_section_hdr("Sortie de commande"))

        self._console = QTextEdit()
        self._console.setReadOnly(True)
        self._console.setFixedHeight(200)
        self._console.setStyleSheet(
            "QTextEdit {"
            "  background-color: #FFFFFF; color: #000000;"
            "  border-top: 2px solid #808080; border-left: 2px solid #808080;"
            "  border-bottom: 2px solid #FFFFFF; border-right: 2px solid #FFFFFF;"
            "  font-family: 'Courier New', monospace; font-size: 10px;"
            "}"
        )
        self._console.setPlaceholderText(
            "La sortie des commandes s'affichera ici...\n"
            "Selectionnez un disque et cliquez sur un outil pour commencer."
        )
        lay.addWidget(self._console)

        lay.addStretch()
        scroll.setWidget(cw)
        root.addWidget(scroll, stretch=1)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _tool_btn(self, title: str, desc: str) -> QPushButton:
        btn = QPushButton()
        btn.setFixedSize(200, 60)
        btn.setCursor(Qt.CursorShape.ArrowCursor)
        btn.setStyleSheet(
            "QPushButton {"
            "  background-color: #C0C0C0; text-align: left;"
            "  border-top: 2px solid #FFFFFF; border-left: 2px solid #FFFFFF;"
            "  border-bottom: 2px solid #808080; border-right: 2px solid #808080;"
            "}"
            "QPushButton:pressed {"
            "  border-top: 2px solid #808080; border-left: 2px solid #808080;"
            "  border-bottom: 2px solid #FFFFFF; border-right: 2px solid #FFFFFF;"
            "}"
        )
        inner = QVBoxLayout(btn)
        inner.setContentsMargins(10, 8, 10, 8)
        inner.setSpacing(3)

        head = QLabel(title)
        head.setStyleSheet(
            "color: #000000; font-size: 11px; font-weight: 700;"
            "font-family: 'Work Sans', Arial; background: transparent;"
        )
        body = QLabel(desc)
        body.setWordWrap(True)
        body.setStyleSheet(
            "color: #404040; font-size: 10px;"
            "font-family: 'Work Sans', Arial; background: transparent;"
        )
        inner.addWidget(head)
        inner.addWidget(body)
        return btn

    def _load_disks(self):
        self._disks = DiskDetector.list_disks()
        self._disk_combo.clear()
        for d in self._disks:
            self._disk_combo.addItem(
                f"{d.get('name','?')}  ({d.get('device','')})",
            )

    def _current_disk(self) -> dict | None:
        idx = self._disk_combo.currentIndex()
        if 0 <= idx < len(self._disks):
            return self._disks[idx]
        return None

    def _analyze(self):
        disk = self._current_disk()
        if not disk:
            return

        device  = disk.get("device", "?")
        total   = disk.get("size_gb", 0.0)
        used    = disk.get("used_gb", 0.0)
        free    = max(0.0, total - used)
        fstype  = disk.get("model", "Inconnu")

        pct = (used / total * 100) if total > 0 else 0
        pct_col = _ERR if pct > 90 else (_WARN if pct > 75 else _OK)

        while self._stats_lay.count() > 1:
            item = self._stats_lay.takeAt(0)
            if w := item.widget():
                w.deleteLater()

        data = [
            ("Peripherique",  device,             "#000000"),
            ("Espace total",  f"{total:.1f} Go",  "#000000"),
            ("Espace libre",  f"{free:.1f} Go",   _OK),
            ("Utilisation",   f"{pct:.0f}%",      pct_col),
        ]
        for i, (label, value, color) in enumerate(data):
            sc = _StatCard(label, value, color)
            self._stats_lay.insertWidget(i, sc)

        self._console.setPlainText(
            f"Disque analyse : {disk.get('name','?')}\n"
            f"Peripherique   : {device}\n"
            f"Taille totale  : {total:.1f} Go\n"
            f"Espace utilise : {used:.1f} Go ({pct:.0f}%)\n"
            f"Espace libre   : {free:.1f} Go\n"
            f"Modele/FS      : {fstype}\n\n"
            "Selectionnez un outil ci-dessous pour lancer une analyse approfondie."
        )

    def _run_chkdsk(self):
        disk = self._current_disk()
        if not disk:
            return
        drive = disk.get("device", "C:").strip().rstrip("\\")
        if not drive.endswith(":"):
            drive = "C:"
        self._run_cmd(["chkdsk", drive, "/scan"])

    def _run_sfc(self):
        mode = self._sfc_combo.currentData() or "scannow"
        self._run_cmd(["sfc", f"/{mode}"])

    def _run_dism(self):
        op = self._dism_combo.currentData() or "CheckHealth"
        if op == "RestoreHealth":
            reply = QMessageBox.warning(
                self,
                "DISM RestoreHealth",
                "Cette operation peut prendre plusieurs minutes\n"
                "et necessite une connexion internet active.\n\n"
                "Continuer ?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        self._run_cmd(["dism", "/Online", "/Cleanup-Image", f"/{op}"])

    def _run_cmd(self, cmd: list[str]):
        if self._worker and self._worker.isRunning():
            return

        self._console.setPlainText(f"Execution : {' '.join(cmd)}\n{'-'*60}\n")

        self._worker = _CmdWorker(cmd)
        self._worker.output.connect(lambda line: self._console.append(line))
        self._worker.done.connect(self._on_cmd_done)
        self._worker.start()

    def _on_cmd_done(self, code: int):
        msg = f"\n{'-'*60}\nTermine (code {code})"
        if code == 0:
            msg += " — Aucune erreur detectee."
        elif code == 1:
            msg += " — Erreurs corrigees."
        elif code == 2:
            msg += " — Des problemes ont ete detectes mais non corriges."
        else:
            msg += " — Erreur ou acces refuse."
        self._console.append(msg)
