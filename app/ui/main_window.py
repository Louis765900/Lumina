"""
Lumina v2.0 — Fenêtre principale
Fenêtre sans bordure (FramelessWindowHint), barre de titre draggable,
feux tricolores macOS, sidebar de navigation, QStackedWidget pour les écrans,
icône de barre des tâches système.
"""

from PyQt6.QtCore import Qt, QPropertyAnimation, QEasingCurve, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QApplication, QDialog, QFrame, QGraphicsOpacityEffect, QHBoxLayout,
    QLabel, QMainWindow, QPushButton, QSizePolicy, QStackedWidget,
    QSystemTrayIcon, QMenu, QVBoxLayout, QWidget,
)

from app.ui.screen_home       import HomeScreen
from app.ui.screen_scan       import ScanScreen
from app.ui.screen_results    import ResultsScreen
from app.ui.screen_sd_card    import SdCardScreen
from app.ui.screen_partitions import PartitionsScreen
from app.ui.screen_repair     import RepairScreen
from app.ui.screen_tools      import ToolsScreen

# ── Palette ──────────────────────────────────────────────────────────────────
_BG      = "#0D0E1A"
_BG2     = "#0F1120"
_SIDEBAR = "#1a1b27"
_BORDER  = "rgba(255,255,255,0.08)"
_TEXT    = "#FFFFFF"
_SUB     = "#94A3B8"
_MUTED   = "#64748B"
_ACCENT  = "#007AFF"
_HOVER   = "rgba(255,255,255,0.05)"

# ── Indices des écrans ────────────────────────────────────────────────────────
IDX_HOME       = 0
IDX_SCAN       = 1
IDX_RESULTS    = 2
IDX_SD         = 3
IDX_PARTITIONS = 4
IDX_REPAIR     = 5
IDX_TOOLS      = 6


# ═══════════════════════════════════════════════════════════════════════════════
#  Composants de la barre de titre
# ═══════════════════════════════════════════════════════════════════════════════

class _TrafficBtn(QPushButton):
    """Un bouton rond macOS (12×12)."""

    def __init__(self, color: str, symbol: str, parent=None):
        super().__init__("", parent)
        self._sym = symbol
        self.setFixedSize(12, 12)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(
            f"QPushButton {{ background: {color}; border: none; border-radius: 6px;"
            "  color: rgba(0,0,0,0.65); font-size: 7px; font-weight: 900; }}"
        )

    def show_symbol(self, v: bool):
        self.setText(self._sym if v else "")


class _TrafficLights(QWidget):
    """Groupe de feux tricolores macOS (fermer / minimiser / maximiser)."""

    def __init__(self, win: "MainWindow", parent=None):
        super().__init__(parent)
        self._win = win
        self._max = False

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        self._close = _TrafficBtn("#FF5F57", "×")
        self._min   = _TrafficBtn("#FEBC2E", "−")
        self._zoom  = _TrafficBtn("#28C840", "+")

        self._close.clicked.connect(win.close)
        self._min.clicked.connect(win.showMinimized)
        self._zoom.clicked.connect(self._toggle_max)

        for btn in (self._close, self._min, self._zoom):
            row.addWidget(btn)

    def _toggle_max(self):
        if self._max:
            self._win.showNormal()
        else:
            self._win.showMaximized()
        self._max = not self._max

    def enterEvent(self, e):
        for b, s in [(self._close, "×"), (self._min, "−"), (self._zoom, "+")]:
            b.show_symbol(True)
        super().enterEvent(e)

    def leaveEvent(self, e):
        for b in (self._close, self._min, self._zoom):
            b.show_symbol(False)
        super().leaveEvent(e)


class TitleBar(QWidget):
    """Barre de titre draggable avec feux tricolores et logo."""

    def __init__(self, win: "MainWindow", parent=None):
        super().__init__(parent)
        self._win      = win
        self._drag_pos = None

        self.setFixedHeight(44)
        self.setStyleSheet(f"background: transparent; border-bottom: 1px solid {_BORDER};")

        row = QHBoxLayout(self)
        row.setContentsMargins(20, 0, 20, 0)
        row.setSpacing(0)

        # Feux tricolores
        self._lights = _TrafficLights(win)
        row.addWidget(self._lights, alignment=Qt.AlignmentFlag.AlignVCenter)
        row.addSpacing(18)

        # Logo + titre
        star = QLabel("✦")
        star.setStyleSheet(
            f"color: {_ACCENT}; font-size: 20px; font-weight: 900; background: transparent;"
        )
        title = QLabel("Lumina")
        title.setStyleSheet(
            f"color: {_TEXT}; font-size: 15px; font-weight: 700;"
            "letter-spacing: -0.3px;"
            "font-family: 'Inter', 'SF Pro Display', 'Segoe UI', Arial;"
            " background: transparent;"
        )
        sub = QLabel("Data Recovery")
        sub.setStyleSheet(
            f"color: {_MUTED}; font-size: 10px; font-weight: 500;"
            "letter-spacing: 0.8px;"
            "font-family: 'Inter', 'Segoe UI', Arial; background: transparent;"
        )

        row.addWidget(star)
        row.addSpacing(8)
        row.addWidget(title)
        row.addSpacing(10)
        row.addWidget(sub, alignment=Qt.AlignmentFlag.AlignBottom)
        row.addStretch()

        # Badge "System Ready"
        dot = QLabel()
        dot.setFixedSize(7, 7)
        dot.setStyleSheet("background: #34C759; border-radius: 4px;")
        ready = QLabel("Système prêt")
        ready.setStyleSheet(
            f"color: {_MUTED}; font-size: 11px; background: transparent;"
        )
        row.addWidget(dot)
        row.addSpacing(6)
        row.addWidget(ready)

    # Drag-to-move
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = e.globalPosition().toPoint() - self._win.frameGeometry().topLeft()
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if e.buttons() == Qt.MouseButton.LeftButton and self._drag_pos:
            self._win.move(e.globalPosition().toPoint() - self._drag_pos)
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        self._drag_pos = None
        super().mouseReleaseEvent(e)

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._lights._toggle_max()
        super().mouseDoubleClickEvent(e)


# ═══════════════════════════════════════════════════════════════════════════════
#  Sidebar
# ═══════════════════════════════════════════════════════════════════════════════

class NavItem(QWidget):
    clicked = pyqtSignal(int)

    def __init__(self, icon: str, label: str, idx: int, parent=None):
        super().__init__(parent)
        self._idx    = idx
        self._active = False

        self.setFixedHeight(36)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        row = QHBoxLayout(self)
        row.setContentsMargins(12, 0, 12, 0)
        row.setSpacing(10)

        self._ico = QLabel(icon)
        self._ico.setFixedWidth(20)
        self._ico.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._lbl = QLabel(label)
        self._lbl.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )

        row.addWidget(self._ico)
        row.addWidget(self._lbl)
        self._refresh()

    def set_active(self, v: bool):
        self._active = v
        self._refresh()

    def _refresh(self):
        if self._active:
            self.setStyleSheet(
                "NavItem { background: rgba(0,122,255,0.15);"
                "  border-left: 2px solid #007AFF;"
                "  border-top: 0px; border-right: 0px; border-bottom: 0px;"
                "  border-radius: 10px; }"
            )
            color, weight = _ACCENT, "600"
        else:
            self.setStyleSheet(
                "NavItem { background: transparent; border-radius: 10px; }"
            )
            color, weight = _SUB, "500"

        self._ico.setStyleSheet(
            f"font-size: 15px; color: {color}; background: transparent;"
        )
        self._lbl.setStyleSheet(
            f"color: {color}; font-size: 13px; font-weight: {weight};"
            "font-family: 'Inter', 'Segoe UI', Arial; background: transparent;"
        )

    def enterEvent(self, e):
        if not self._active:
            self.setStyleSheet(
                "NavItem { background: rgba(255,255,255,0.05); border-radius: 10px; }"
            )
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._refresh()
        super().leaveEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._idx)
        super().mousePressEvent(e)


class Sidebar(QWidget):
    nav_requested = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(240)
        self.setStyleSheet(
            f"Sidebar {{ background: {_SIDEBAR}; border-right: 1px solid {_BORDER}; }}"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 14, 8, 12)
        root.setSpacing(2)

        self._items: list[NavItem] = []

        # Section Récupération
        root.addWidget(self._section("Récupération"))
        root.addSpacing(2)
        for icon, label, idx in [
            ("💾", "Disques & Emplacements", IDX_HOME),
            ("💳", "Cartes SD & Externes",   IDX_SD),
        ]:
            item = NavItem(icon, label, idx)
            item.clicked.connect(self.nav_requested)
            self._items.append(item)
            root.addWidget(item)

        root.addSpacing(18)

        # Section Outils
        root.addWidget(self._section("Outils"))
        root.addSpacing(2)
        for icon, label, idx in [
            ("⚙",  "Gestion des partitions", IDX_PARTITIONS),
            ("🔧", "Diagnostic disque",       IDX_REPAIR),
            ("🛠",  "Outils avancés",          IDX_TOOLS),
        ]:
            item = NavItem(icon, label, idx)
            item.clicked.connect(self.nav_requested)
            self._items.append(item)
            root.addWidget(item)

        root.addStretch()

        # Numéro de version
        ver = QLabel("Lumina v2.0")
        ver.setStyleSheet(
            f"color: {_MUTED}; font-size: 10px;"
            "font-family: 'Inter', 'Segoe UI', Arial; background: transparent; padding: 2px 12px;"
        )
        root.addWidget(ver)

    @staticmethod
    def _section(title: str) -> QLabel:
        lbl = QLabel(title.upper())
        lbl.setContentsMargins(12, 4, 8, 2)
        lbl.setStyleSheet(
            "color: #c1c6d7; font-size: 10px; font-weight: 700; letter-spacing: 1.2px;"
            "font-family: 'Inter', 'Segoe UI', Arial; background: transparent;"
        )
        return lbl

    def set_active(self, idx: int):
        # SCAN et RESULTS restent en surbrillance HOME dans la sidebar
        active = IDX_HOME if idx in (IDX_SCAN, IDX_RESULTS) else idx
        for item in self._items:
            item.set_active(item._idx == active)


# ═══════════════════════════════════════════════════════════════════════════════
#  Dialogue de choix du mode de scan
# ═══════════════════════════════════════════════════════════════════════════════

class _ScanModeDialog(QDialog):

    def __init__(self, disk: dict, parent=None):
        super().__init__(parent)
        self._chosen = "deep"
        self.setModal(True)
        self.setFixedSize(480, 270)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        card = QFrame()
        card.setObjectName("ScanCard")
        card.setStyleSheet(
            "QFrame#ScanCard {"
            "  background: #1A1B2E;"
            f"  border: 1px solid {_BORDER};"
            "  border-radius: 16px;"
            "}"
        )
        lay = QVBoxLayout(card)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(18)

        name = disk.get("name", "Disque")
        title = QLabel(f"Mode de scan — {name}")
        title.setStyleSheet(
            f"color: {_TEXT}; font-size: 16px; font-weight: 700;"
            "font-family: 'Inter', 'Segoe UI', Arial; background: transparent;"
        )
        lay.addWidget(title)

        modes_row = QHBoxLayout()
        modes_row.setSpacing(14)
        self._quick_btn = self._make_mode_card(
            "⚡", "Scan Rapide",
            "Fichiers récemment supprimés.\nAnalyse MFT : 2–5 min.",
            active=False,
        )
        self._deep_btn = self._make_mode_card(
            "🔬", "Scan Complet",
            "Analyse secteur par secteur.\nPlus long mais exhaustif.",
            active=True,
        )
        self._quick_btn.clicked.connect(lambda: self._select("quick"))
        self._deep_btn.clicked.connect(lambda: self._select("deep"))
        modes_row.addWidget(self._quick_btn)
        modes_row.addWidget(self._deep_btn)
        lay.addLayout(modes_row)

        btns = QHBoxLayout()
        btns.addStretch()

        cancel = QPushButton("Annuler")
        cancel.setFixedSize(90, 34)
        cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel.setStyleSheet(
            f"QPushButton {{ color: {_SUB}; background: transparent;"
            f"  border: 1px solid {_BORDER}; border-radius: 8px;"
            "  font-size: 13px; font-weight: 500; }}"
            f"QPushButton:hover {{ background: {_HOVER}; color: {_TEXT}; }}"
        )
        cancel.clicked.connect(self.reject)

        start = QPushButton("Démarrer →")
        start.setFixedSize(120, 34)
        start.setCursor(Qt.CursorShape.PointingHandCursor)
        start.setStyleSheet(
            f"QPushButton {{ color: white; background: {_ACCENT};"
            "  border: none; border-radius: 8px;"
            "  font-size: 13px; font-weight: 700; }}"
            "QPushButton:hover { background: #005FCC; }"
        )
        start.clicked.connect(self.accept)

        btns.addWidget(cancel)
        btns.addSpacing(8)
        btns.addWidget(start)
        lay.addLayout(btns)

        root.addWidget(card)

    def _make_mode_card(self, icon: str, title: str, desc: str, active: bool) -> QPushButton:
        btn = QPushButton()
        btn.setFixedSize(192, 96)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)

        inner = QVBoxLayout(btn)
        inner.setContentsMargins(14, 12, 14, 12)
        inner.setSpacing(4)

        head = QLabel(f"{icon}  {title}")
        head.setStyleSheet(
            "color: #F1F5F9; font-size: 13px; font-weight: 700;"
            "font-family: 'Inter'; background: transparent;"
        )
        body = QLabel(desc)
        body.setWordWrap(True)
        body.setStyleSheet(
            "color: #64748B; font-size: 10px;"
            "font-family: 'Inter'; background: transparent;"
        )
        inner.addWidget(head)
        inner.addWidget(body)
        inner.addStretch()

        self._style_mode(btn, active)
        return btn

    @staticmethod
    def _style_mode(btn: QPushButton, active: bool):
        if active:
            btn.setStyleSheet(
                f"QPushButton {{ background: rgba(0,122,255,0.15);"
                f"  border: 1.5px solid {_ACCENT}; border-radius: 12px; text-align: left; }}"
            )
        else:
            btn.setStyleSheet(
                "QPushButton { background: rgba(255,255,255,0.04);"
                f"  border: 1px solid {_BORDER}; border-radius: 12px; text-align: left; }}"
                "QPushButton:hover { background: rgba(255,255,255,0.08); }"
            )

    def _select(self, mode: str):
        self._chosen = mode
        self._style_mode(self._quick_btn, mode == "quick")
        self._style_mode(self._deep_btn,  mode == "deep")

    def chosen_mode(self) -> str:
        return self._chosen


# ═══════════════════════════════════════════════════════════════════════════════
#  Fenêtre principale
# ═══════════════════════════════════════════════════════════════════════════════

class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Lumina — Data Recovery")
        self.setMinimumSize(960, 640)
        self.resize(1240, 780)

        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        # Widget central avec gradient de fond
        central = QWidget()
        central.setObjectName("LuminaCentral")
        central.setStyleSheet(
            "QWidget#LuminaCentral {"
            "  background: qlineargradient(x1:0,y1:0,x2:1,y2:1,"
            f"    stop:0 {_BG}, stop:1 {_BG2});"
            "  border-radius: 12px;"
            f"  border: 1px solid {_BORDER};"
            "}"
        )
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Barre de titre
        self._title_bar = TitleBar(self)
        root.addWidget(self._title_bar)

        # Corps : sidebar + contenu
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        self._sidebar = Sidebar()
        self._sidebar.nav_requested.connect(self._on_nav)
        body.addWidget(self._sidebar)

        self._stack = QStackedWidget()
        self._stack.setStyleSheet("background: transparent;")
        body.addWidget(self._stack, stretch=1)

        root.addLayout(body, stretch=1)

        # ── Créer les écrans ──────────────────────────────────────────────────
        self._home       = HomeScreen()
        self._scan       = ScanScreen()
        self._results    = ResultsScreen()
        self._sd         = SdCardScreen()
        self._partitions = PartitionsScreen()
        self._repair     = RepairScreen()
        self._tools      = ToolsScreen()

        for screen in (
            self._home, self._scan, self._results,
            self._sd, self._partitions, self._repair, self._tools,
        ):
            self._stack.addWidget(screen)

        # ── Connexions de signaux ──────────────────────────────────────────────
        self._home.disk_selected.connect(self._go_scan)
        self._home.history_scan_requested.connect(self._go_results)
        self._sd.disk_selected.connect(self._go_scan)
        self._scan.scan_finished.connect(self._go_results)
        self._scan.scan_cancelled.connect(self.show_home)
        self._results.new_scan_requested.connect(self.show_home)

        self.show_home()
        self._init_tray()

    # ── Icône de barre des tâches ─────────────────────────────────────────────

    def _init_tray(self):
        self._tray = QSystemTrayIcon(self)

        pix = QPixmap(32, 32)
        pix.fill(Qt.GlobalColor.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QColor(_ACCENT))
        p.setFont(QFont("Inter", 22, QFont.Weight.Bold))
        p.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter, "✦")
        p.end()

        self._tray.setIcon(QIcon(pix))
        self._tray.setToolTip("Lumina Data Recovery")

        menu = QMenu()
        restore_act = QAction("Restaurer", self)
        restore_act.triggered.connect(self.showNormal)
        restore_act.triggered.connect(self.activateWindow)
        quit_act = QAction("Quitter Lumina", self)
        quit_act.triggered.connect(QApplication.instance().quit)
        menu.addAction(restore_act)
        menu.addSeparator()
        menu.addAction(quit_act)

        self._tray.setContextMenu(menu)
        self._tray.activated.connect(self._on_tray_activated)
        self._tray.show()

    def _on_tray_activated(self, reason):
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            if self.isVisible():
                self.hide()
            else:
                self.showNormal()
                self.activateWindow()

    # ── Fermeture ─────────────────────────────────────────────────────────────

    def closeEvent(self, event):
        worker = getattr(self._scan, "_worker", None)
        if worker and worker.isRunning():
            self.hide()
            self._tray.showMessage(
                "Lumina",
                "Analyse en cours en arrière-plan. "
                "Utilisez « Quitter Lumina » dans la barre système pour arrêter.",
                QSystemTrayIcon.MessageIcon.Information,
                4000,
            )
            event.ignore()
        else:
            event.accept()
            QApplication.instance().quit()

    # ── Navigation ────────────────────────────────────────────────────────────

    def _on_nav(self, idx: int):
        routes = {
            IDX_HOME:       self.show_home,
            IDX_SD:         lambda: self._show_screen(IDX_SD),
            IDX_PARTITIONS: lambda: self._show_screen(IDX_PARTITIONS),
            IDX_REPAIR:     lambda: self._show_screen(IDX_REPAIR),
            IDX_TOOLS:      lambda: self._show_screen(IDX_TOOLS),
        }
        if handler := routes.get(idx):
            handler()

    def show_home(self):
        self._sidebar.set_active(IDX_HOME)
        if self._stack.currentIndex() == IDX_HOME:
            self._home.refresh_disks()
            return
        self._fade_to(IDX_HOME)
        QTimer.singleShot(310, self._home.refresh_disks)

    def _show_screen(self, idx: int):
        self._sidebar.set_active(idx)
        self._fade_to(idx)

    def _go_scan(self, disk: dict):
        dlg = _ScanModeDialog(disk, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        disk["scan_mode"] = dlg.chosen_mode()
        self._scan.start_scan(disk)
        self._sidebar.set_active(IDX_SCAN)
        self._fade_to(IDX_SCAN)

    def _go_results(self, files: list):
        self._results.load_results(files)
        self._sidebar.set_active(IDX_RESULTS)
        self._fade_to(IDX_RESULTS)

    # ── Transition de fondu ───────────────────────────────────────────────────

    def _fade_to(self, idx: int):
        if self._stack.currentIndex() == idx:
            return

        # Nettoyer l'effet précédent pour éviter les fuites
        old = self._stack.graphicsEffect()
        if old:
            self._stack.setGraphicsEffect(None)
            old.deleteLater()

        effect = QGraphicsOpacityEffect(self._stack)
        self._stack.setGraphicsEffect(effect)

        fade_out = QPropertyAnimation(effect, b"opacity", self)
        fade_out.setDuration(100)
        fade_out.setStartValue(1.0)
        fade_out.setEndValue(0.0)
        fade_out.setEasingCurve(QEasingCurve.Type.InCubic)

        def _switch():
            self._stack.setCurrentIndex(idx)
            fade_in = QPropertyAnimation(effect, b"opacity", self)
            fade_in.setDuration(180)
            fade_in.setStartValue(0.0)
            fade_in.setEndValue(1.0)
            fade_in.setEasingCurve(QEasingCurve.Type.OutCubic)
            fade_in.finished.connect(lambda: self._stack.setGraphicsEffect(None))
            fade_in.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)

        fade_out.finished.connect(_switch)
        fade_out.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
