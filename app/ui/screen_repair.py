"""
Lumina v2.0 — Écran 5 : Diagnostic disque
Informations sur les partitions, lancement de CHKDSK et SFC depuis l'UI,
sans dépendance à une API externe.
"""

import subprocess

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QCursor
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


def _fmt_gb(n: int) -> str:
    return f"{n / (1024**3):.1f} Go"


def _section_hdr(title: str) -> QWidget:
    w = QWidget()
    w.setFixedHeight(28)
    row = QHBoxLayout(w)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(12)
    lbl = QLabel(title.upper())
    lbl.setStyleSheet(
        f"color: {_MUTED}; font-size: 10px; font-weight: 700; letter-spacing: 1.2px;"
        "font-family: 'Inter'; background: transparent;"
    )
    line = QFrame()
    line.setFixedHeight(1)
    line.setStyleSheet(f"background: {_BORDER}; border: none;")
    row.addWidget(lbl)
    row.addWidget(line, stretch=1)
    return w


# ═══════════════════════════════════════════════════════════════════════════════
#  Worker subprocess (QThread)
# ═══════════════════════════════════════════════════════════════════════════════

class _CmdWorker(QThread):
    output  = pyqtSignal(str)
    done    = pyqtSignal(int)   # code de retour

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
    def __init__(self, icon: str, label: str, value: str, color: str = "#94A3B8", parent=None):
        super().__init__(parent)
        self.setFixedHeight(72)
        self.setStyleSheet(
            f"_StatCard {{ background: {_CARD}; border: 1px solid {_BORDER}; border-radius: 10px; }}"
        )
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(14)

        ico = QLabel(icon)
        ico.setFixedSize(34, 34)
        ico.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ico.setStyleSheet(
            "font-size: 18px; background: rgba(0,122,255,0.1); border-radius: 7px;"
        )
        lay.addWidget(ico)

        col = QVBoxLayout()
        col.setSpacing(3)
        lbl_w = QLabel(label)
        lbl_w.setStyleSheet(
            f"color: {_MUTED}; font-size: 11px; font-family: 'Inter'; background: transparent;"
        )
        val_w = QLabel(value)
        val_w.setStyleSheet(
            f"color: {color}; font-size: 14px; font-weight: 700;"
            "font-family: 'Inter'; background: transparent;"
        )
        col.addWidget(lbl_w)
        col.addWidget(val_w)
        lay.addLayout(col, stretch=1)


# ═══════════════════════════════════════════════════════════════════════════════
#  Écran de diagnostic
# ═══════════════════════════════════════════════════════════════════════════════

class RepairScreen(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background: transparent;")
        self._worker: _CmdWorker | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── En-tête ───────────────────────────────────────────────────────────
        hdr = QWidget()
        hdr.setFixedHeight(100)
        hdr.setStyleSheet("background: transparent;")
        hr = QHBoxLayout(hdr)
        hr.setContentsMargins(40, 20, 40, 20)
        col = QVBoxLayout()
        col.setSpacing(6)
        title = QLabel("Diagnostic disque")
        title.setStyleSheet(
            f"color: {_TEXT}; font-size: 22px; font-weight: 700; font-family: 'Inter';"
        )
        sub = QLabel("Analysez la santé de vos disques et lancez des outils de réparation.")
        sub.setStyleSheet(f"color: {_SUB}; font-size: 13px; font-family: 'Inter';")
        col.addWidget(title)
        col.addWidget(sub)
        hr.addLayout(col)
        root.addWidget(hdr)

        # ── Zone principale scrollable ────────────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        cw = QWidget()
        cw.setStyleSheet("background: transparent;")
        lay = QVBoxLayout(cw)
        lay.setContentsMargins(40, 0, 40, 40)
        lay.setSpacing(20)
        lay.setAlignment(Qt.AlignmentFlag.AlignTop)

        # ── Sélecteur de disque ───────────────────────────────────────────────
        lay.addWidget(_section_hdr("Sélectionner un disque"))

        sel_row = QHBoxLayout()
        self._disk_combo = QComboBox()
        self._disk_combo.setFixedWidth(320)
        self._disks: list[dict] = []
        self._load_disks()
        sel_row.addWidget(self._disk_combo)
        sel_row.addSpacing(12)

        analyze_btn = QPushButton("Analyser →")
        analyze_btn.setFixedSize(120, 34)
        analyze_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        analyze_btn.setStyleSheet(
            f"QPushButton {{ background: {_ACCENT}; color: white; border: none;"
            "  border-radius: 8px; font-size: 13px; font-weight: 700; }}"
            "QPushButton:hover { background: #005FCC; }"
        )
        analyze_btn.clicked.connect(self._analyze)
        sel_row.addWidget(analyze_btn)
        sel_row.addStretch()
        lay.addLayout(sel_row)

        # ── Stats ─────────────────────────────────────────────────────────────
        lay.addWidget(_section_hdr("Informations du disque"))
        self._stats_container = QWidget()
        self._stats_container.setStyleSheet("background: transparent;")
        self._stats_lay = QHBoxLayout(self._stats_container)
        self._stats_lay.setContentsMargins(0, 0, 0, 0)
        self._stats_lay.setSpacing(12)
        self._stats_lay.addStretch()
        lay.addWidget(self._stats_container)

        # ── Outils de réparation ─────────────────────────────────────────────
        lay.addWidget(_section_hdr("Outils de réparation"))

        tools_grid = QHBoxLayout()
        tools_grid.setSpacing(12)

        self._chkdsk_btn = self._tool_btn("🔍", "CHKDSK /scan", "Vérification rapide du système de fichiers.")
        self._chkdsk_btn.clicked.connect(self._run_chkdsk)
        tools_grid.addWidget(self._chkdsk_btn)

        # SFC — avec sélecteur de mode
        sfc_col = QVBoxLayout()
        sfc_col.setSpacing(6)
        self._sfc_btn = self._tool_btn("🛡", "SFC", "Vérification ou réparation des fichiers système.")
        self._sfc_btn.clicked.connect(self._run_sfc)
        self._sfc_combo = QComboBox()
        self._sfc_combo.addItem("Réparer (/scannow)",        "scannow")
        self._sfc_combo.addItem("Vérifier seul (/verifyonly)", "verifyonly")
        self._sfc_combo.setFixedWidth(220)
        self._sfc_combo.setToolTip(
            "/scannow : répare les fichiers corrompus\n"
            "/verifyonly : vérifie sans modifier"
        )
        sfc_col.addWidget(self._sfc_btn)
        sfc_col.addWidget(self._sfc_combo)
        tools_grid.addLayout(sfc_col)

        # DISM — avec sélecteur CheckHealth / RestoreHealth
        dism_col = QVBoxLayout()
        dism_col.setSpacing(6)
        self._dism_btn = self._tool_btn("🔧", "DISM", "Contrôle ou réparation de l'image Windows.")
        self._dism_btn.clicked.connect(self._run_dism)
        self._dism_combo = QComboBox()
        self._dism_combo.addItem("Vérification (/CheckHealth)",   "CheckHealth")
        self._dism_combo.addItem("Réparation (/RestoreHealth)",   "RestoreHealth")
        self._dism_combo.setFixedWidth(220)
        self._dism_combo.setToolTip(
            "/CheckHealth : vérification rapide, hors ligne\n"
            "/RestoreHealth : répare via Windows Update (connexion internet requise)"
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
        self._console.setFixedHeight(220)
        self._console.setPlaceholderText(
            "La sortie des commandes s'affichera ici…\n"
            "Sélectionnez un disque et cliquez sur un outil pour commencer."
        )
        lay.addWidget(self._console)

        lay.addStretch()
        scroll.setWidget(cw)
        root.addWidget(scroll, stretch=1)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _tool_btn(self, icon: str, title: str, desc: str) -> QPushButton:
        btn = QPushButton()
        btn.setFixedSize(220, 72)
        btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn.setStyleSheet(
            f"QPushButton {{ background: {_CARD}; border: 1px solid {_BORDER};"
            "  border-radius: 12px; text-align: left; }}"
            f"QPushButton:hover {{ background: rgba(255,255,255,0.08); border-color: rgba(0,122,255,0.4); }}"
        )
        inner = QVBoxLayout(btn)
        inner.setContentsMargins(16, 10, 16, 10)
        inner.setSpacing(4)

        head = QLabel(f"{icon}  {title}")
        head.setStyleSheet(
            f"color: {_TEXT}; font-size: 12px; font-weight: 700;"
            "font-family: 'Inter'; background: transparent;"
        )
        body = QLabel(desc)
        body.setWordWrap(True)
        body.setStyleSheet(
            f"color: {_MUTED}; font-size: 10px; font-family: 'Inter'; background: transparent;"
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

        # Vider et reconstruire le conteneur de stats
        while self._stats_lay.count() > 1:   # garder le stretch final
            item = self._stats_lay.takeAt(0)
            if w := item.widget():
                w.deleteLater()

        data = [
            ("💾", "Périphérique",  device,            _TEXT),
            ("📊", "Espace total",  f"{total:.1f} Go",  _TEXT),
            ("✅", "Espace libre",  f"{free:.1f} Go",   _OK),
            ("📈", "Utilisation",   f"{pct:.0f}%",      pct_col),
        ]
        for i, (icon, label, value, color) in enumerate(data):
            sc = _StatCard(icon, label, value, color)
            self._stats_lay.insertWidget(i, sc)

        self._console.setPlainText(
            f"Disque analysé : {disk.get('name','?')}\n"
            f"Périphérique   : {device}\n"
            f"Taille totale  : {total:.1f} Go\n"
            f"Espace utilisé : {used:.1f} Go ({pct:.0f}%)\n"
            f"Espace libre   : {free:.1f} Go\n"
            f"Modèle/FS      : {fstype}\n\n"
            "Sélectionnez un outil ci-dessous pour lancer une analyse approfondie."
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
                "Cette opération peut prendre plusieurs minutes\n"
                "et nécessite une connexion internet active.\n\n"
                "Continuer ?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        self._run_cmd(["dism", "/Online", "/Cleanup-Image", f"/{op}"])

    def _run_cmd(self, cmd: list[str]):
        if self._worker and self._worker.isRunning():
            return   # commande déjà en cours

        self._console.setPlainText(f"Exécution : {' '.join(cmd)}\n{'─'*60}\n")

        self._worker = _CmdWorker(cmd)
        self._worker.output.connect(lambda line: self._console.append(line))
        self._worker.done.connect(self._on_cmd_done)
        self._worker.start()

    def _on_cmd_done(self, code: int):
        msg = f"\n{'─'*60}\nTerminé (code {code})"
        if code == 0:
            msg += " — ✅ Aucune erreur détectée."
        elif code == 1:
            msg += " — ✅ Erreurs corrigées."
        elif code == 2:
            msg += " — ⚠ Des problèmes ont été détectés mais non corrigés."
        else:
            msg += " — ❌ Erreur ou accès refusé."
        self._console.append(msg)
