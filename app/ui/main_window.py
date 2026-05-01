"""
Lumina — Fenêtre principale Windows 98
Fenêtre sans bordure, barre de titre Win98 (gradient bleu, boutons carres),
sidebar grise, QStackedWidget pour les écrans.
"""

from PyQt6.QtCore import QEasingCurve, QPropertyAnimation, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QFont, QIcon, QLinearGradient, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from app.ui.palette import (
    WIN98_NAVY as _NAVY,
)
from app.ui.palette import (
    WIN98_TITLE1 as _TITLE1,
)
from app.ui.palette import (
    WIN98_TITLE2 as _TITLE2,
)
from app.ui.screen_home import HomeScreen
from app.ui.screen_partitions import PartitionsScreen
from app.ui.screen_repair import RepairScreen
from app.ui.screen_results import ResultsScreen
from app.ui.screen_scan import ScanScreen
from app.ui.screen_sd_card import SdCardScreen
from app.ui.screen_tools import ToolsScreen

# ── Indices des écrans ────────────────────────────────────────────────────────
IDX_HOME       = 0
IDX_SCAN       = 1
IDX_RESULTS    = 2
IDX_SD         = 3
IDX_PARTITIONS = 4
IDX_REPAIR     = 5
IDX_TOOLS      = 6


# ═══════════════════════════════════════════════════════════════════════════════
#  Bouton de controle Win98 (minimiser / maximiser / fermer)
# ═══════════════════════════════════════════════════════════════════════════════

class _Win98CtrlBtn(QPushButton):
    """Bouton carre Win98 pour la barre de titre (17x15)."""

    def __init__(self, symbol: str, parent=None):
        super().__init__(symbol, parent)
        self.setFixedSize(17, 15)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self._update_style(False)

    def _update_style(self, pressed: bool):
        if pressed:
            ss = (
                "QPushButton {"
                "  background-color: #C0C0C0;"
                "  color: #000000;"
                "  font-size: 9px; font-weight: 700;"
                "  font-family: 'Work Sans', 'Arial';"
                "  border-top: 2px solid #808080;"
                "  border-left: 2px solid #808080;"
                "  border-bottom: 2px solid #FFFFFF;"
                "  border-right: 2px solid #FFFFFF;"
                "  padding-top: 2px; padding-left: 2px;"
                "}"
            )
        else:
            ss = (
                "QPushButton {"
                "  background-color: #C0C0C0;"
                "  color: #000000;"
                "  font-size: 9px; font-weight: 700;"
                "  font-family: 'Work Sans', 'Arial';"
                "  border-top: 2px solid #FFFFFF;"
                "  border-left: 2px solid #FFFFFF;"
                "  border-bottom: 2px solid #808080;"
                "  border-right: 2px solid #808080;"
                "}"
                "QPushButton:hover {"
                "  background-color: #D4D0C8;"
                "}"
            )
        self.setStyleSheet(ss)

    def mousePressEvent(self, e):
        self._update_style(True)
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        self._update_style(False)
        super().mouseReleaseEvent(e)


# ═══════════════════════════════════════════════════════════════════════════════
#  Barre de titre Win98
# ═══════════════════════════════════════════════════════════════════════════════

class TitleBar(QWidget):
    """Barre de titre Win98 avec gradient bleu, icone, titre et 3 boutons carres."""

    def __init__(self, win: "MainWindow", parent=None):
        super().__init__(parent)
        self._win      = win
        self._drag_pos = None
        self._active   = True

        self.setFixedHeight(20)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        row = QHBoxLayout(self)
        row.setContentsMargins(3, 2, 2, 2)
        row.setSpacing(0)

        # Icone 16x16
        self._icon_lbl = QLabel()
        self._icon_lbl.setFixedSize(16, 16)
        self._icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._icon_lbl.setStyleSheet("background: transparent; font-size: 11px;")
        self._icon_lbl.setText("L")
        row.addWidget(self._icon_lbl)
        row.addSpacing(4)

        # Titre
        self._title_lbl = QLabel("Lumina Data Recovery")
        self._title_lbl.setStyleSheet(
            "color: #FFFFFF; font-size: 11px; font-weight: 700;"
            "font-family: 'Work Sans', 'Arial';"
            "background: transparent;"
        )
        row.addWidget(self._title_lbl)
        row.addStretch()

        # Boutons de controle
        self._min_btn   = _Win98CtrlBtn("_")
        self._max_btn   = _Win98CtrlBtn("o")
        self._close_btn = _Win98CtrlBtn("x")
        self._min_btn.clicked.connect(win.showMinimized)
        self._max_btn.clicked.connect(self._toggle_max)
        self._close_btn.clicked.connect(win.close)

        row.addSpacing(2)
        row.addWidget(self._min_btn)
        row.addSpacing(2)
        row.addWidget(self._max_btn)
        row.addSpacing(2)
        row.addWidget(self._close_btn)

    def _toggle_max(self):
        if self._win.isMaximized():
            self._win.showNormal()
        else:
            self._win.showMaximized()

    def paintEvent(self, e):
        p = QPainter(self)
        grad = QLinearGradient(0, 0, self.width(), 0)
        if self._active:
            grad.setColorAt(0, QColor(_TITLE1))
            grad.setColorAt(1, QColor(_TITLE2))
        else:
            grad.setColorAt(0, QColor("#808080"))
            grad.setColorAt(1, QColor("#C0C0C0"))
        p.fillRect(self.rect(), grad)
        p.end()
        super().paintEvent(e)

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
            self._toggle_max()
        super().mouseDoubleClickEvent(e)


# ═══════════════════════════════════════════════════════════════════════════════
#  Sidebar Win98
# ═══════════════════════════════════════════════════════════════════════════════

class NavItem(QWidget):
    clicked = pyqtSignal(int)

    def __init__(self, icon: str, label: str, idx: int, parent=None):
        super().__init__(parent)
        self._idx    = idx
        self._active = False

        self.setFixedHeight(22)
        self.setCursor(Qt.CursorShape.ArrowCursor)

        row = QHBoxLayout(self)
        row.setContentsMargins(16, 0, 8, 0)
        row.setSpacing(6)

        self._ico = QLabel(icon)
        self._ico.setFixedWidth(16)
        self._ico.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._ico.setStyleSheet("font-size: 12px; background: transparent;")

        self._lbl = QLabel(label)
        self._lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        row.addWidget(self._ico)
        row.addWidget(self._lbl)
        self._refresh()

    def set_active(self, v: bool):
        self._active = v
        self._refresh()

    def _refresh(self):
        if self._active:
            self.setStyleSheet(
                "NavItem {"
                "  background-color: #000080;"
                "  border: 0px;"
                "}"
            )
            self._lbl.setStyleSheet(
                "color: #FFFFFF; font-size: 11px; font-weight: 700;"
                "font-family: 'Work Sans', 'Arial'; background: transparent;"
            )
            self._ico.setStyleSheet("font-size: 12px; color: #FFFFFF; background: transparent;")
        else:
            self.setStyleSheet("NavItem { background: transparent; border: 0px; }")
            self._lbl.setStyleSheet(
                "color: #000000; font-size: 11px; font-weight: 400;"
                "font-family: 'Work Sans', 'Arial'; background: transparent;"
            )
            self._ico.setStyleSheet("font-size: 12px; color: #000000; background: transparent;")

    def enterEvent(self, e):
        if not self._active:
            self.setStyleSheet("NavItem { background-color: #D4D0C8; border: 0px; }")
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
        self.setFixedWidth(180)
        self.setStyleSheet(
            "Sidebar {"
            "  background-color: #C0C0C0;"
            "  border-right: 2px solid #808080;"
            "}"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 4, 0, 4)
        root.setSpacing(0)

        self._items: list[NavItem] = []

        # Section Récupération
        root.addWidget(self._section("Recuperation"))
        for icon, label, idx in [
            ("💾", "Disques",      IDX_HOME),
            ("💳", "Cartes SD",    IDX_SD),
        ]:
            item = NavItem(icon, label, idx)
            item.clicked.connect(self.nav_requested)
            self._items.append(item)
            root.addWidget(item)

        root.addSpacing(8)

        # Section Outils
        root.addWidget(self._section("Outils"))
        for icon, label, idx in [
            ("⚙",  "Partitions",   IDX_PARTITIONS),
            ("🔧", "Diagnostic",   IDX_REPAIR),
            ("🛠",  "Outils avances", IDX_TOOLS),
        ]:
            item = NavItem(icon, label, idx)
            item.clicked.connect(self.nav_requested)
            self._items.append(item)
            root.addWidget(item)

        root.addStretch()

        # Version
        ver = QLabel("Lumina v1.0.0")
        ver.setStyleSheet(
            "color: #808080; font-size: 10px;"
            "font-family: 'Work Sans', 'Arial'; background: transparent;"
            "padding: 2px 8px;"
        )
        root.addWidget(ver)

    @staticmethod
    def _section(title: str) -> QLabel:
        lbl = QLabel(title.upper())
        lbl.setContentsMargins(8, 4, 8, 2)
        lbl.setStyleSheet(
            "color: #000080; font-size: 10px; font-weight: 700;"
            "font-family: 'Work Sans', 'Arial'; background: transparent;"
        )
        return lbl

    def set_active(self, idx: int):
        active = IDX_HOME if idx in (IDX_SCAN, IDX_RESULTS) else idx
        for item in self._items:
            item.set_active(item._idx == active)


# ═══════════════════════════════════════════════════════════════════════════════
#  Dialogue de choix du mode de scan (style Win98)
# ═══════════════════════════════════════════════════════════════════════════════

class _ScanModeDialog(QDialog):

    def __init__(self, disk: dict, parent=None):
        super().__init__(parent)
        self._chosen = "deep"
        self.setModal(True)
        self.setFixedSize(400, 260)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        # Window outer raised border
        self.setStyleSheet(
            "QDialog {"
            "  background-color: #C0C0C0;"
            "  border-top: 2px solid #FFFFFF;"
            "  border-left: 2px solid #FFFFFF;"
            "  border-bottom: 2px solid #808080;"
            "  border-right: 2px solid #808080;"
            "}"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(2, 2, 2, 2)
        root.setSpacing(0)

        # Title bar
        self._drag_pos = None
        title_bar = QWidget()
        title_bar.setFixedHeight(20)
        title_bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        title_bar.installEventFilter(self)
        tb_row = QHBoxLayout(title_bar)
        tb_row.setContentsMargins(4, 2, 2, 2)
        tb_row.setSpacing(0)

        name = disk.get("name", "Disque")
        tb_lbl = QLabel(f"Choisir le mode de scan - {name}")
        tb_lbl.setStyleSheet(
            "color: #FFFFFF; font-size: 11px; font-weight: 700;"
            "font-family: 'Work Sans', Arial; background: transparent;"
        )
        tb_row.addWidget(tb_lbl)
        tb_row.addStretch()

        close_btn = _Win98CtrlBtn("x")
        close_btn.clicked.connect(self.reject)
        tb_row.addWidget(close_btn)

        self._tb = title_bar
        root.addWidget(title_bar)

        # Content area
        content = QWidget()
        content_lay = QVBoxLayout(content)
        content_lay.setContentsMargins(12, 8, 12, 8)
        content_lay.setSpacing(10)

        # Mode cards row
        modes_row = QHBoxLayout()
        modes_row.setSpacing(8)

        self._quick_btn = self._make_mode_card(
            "Scan Rapide",
            "Fichiers supprimes\nrecemment (MFT NTFS).\nDuree: 2-5 min.",
            active=False,
        )
        self._deep_btn = self._make_mode_card(
            "Scan Complet",
            "Tous fichiers - photos,\nvideos, docs.\nAnalyse par signature.",
            active=True,
        )
        self._quick_btn.clicked.connect(lambda: self._select("quick"))
        self._deep_btn.clicked.connect(lambda: self._select("deep"))
        modes_row.addWidget(self._quick_btn)
        modes_row.addWidget(self._deep_btn)
        content_lay.addLayout(modes_row)

        # Note
        note_frame = QFrame()
        note_frame.setStyleSheet(
            "QFrame {"
            "  background-color: #FFFFFF;"
            "  border-top: 2px solid #808080;"
            "  border-left: 2px solid #808080;"
            "  border-bottom: 2px solid #FFFFFF;"
            "  border-right: 2px solid #FFFFFF;"
            "}"
        )
        note_lay = QHBoxLayout(note_frame)
        note_lay.setContentsMargins(6, 4, 6, 4)
        note = QLabel(
            "Recommande: Scan Complet pour recuperer photos et videos perdues depuis longtemps."
        )
        note.setWordWrap(True)
        note.setStyleSheet("font-size: 10px; color: #000000; background: transparent;")
        note_lay.addWidget(note)
        content_lay.addWidget(note_frame)

        # Buttons row
        btns = QHBoxLayout()
        btns.addStretch()

        cancel = QPushButton("Annuler")
        cancel.setFixedSize(80, 24)
        cancel.setCursor(Qt.CursorShape.ArrowCursor)
        cancel.clicked.connect(self.reject)

        start = QPushButton("Demarrer")
        start.setFixedSize(80, 24)
        start.setCursor(Qt.CursorShape.ArrowCursor)
        start.clicked.connect(self.accept)

        btns.addWidget(cancel)
        btns.addSpacing(8)
        btns.addWidget(start)
        content_lay.addLayout(btns)

        root.addWidget(content)

    def eventFilter(self, obj, event):
        from PyQt6.QtCore import QEvent
        if obj is self._tb:
            if event.type() == QEvent.Type.MouseButtonPress:
                if event.button() == Qt.MouseButton.LeftButton:
                    self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            elif event.type() == QEvent.Type.MouseMove:
                if event.buttons() == Qt.MouseButton.LeftButton and self._drag_pos is not None:
                    self.move(event.globalPosition().toPoint() - self._drag_pos)
            elif event.type() == QEvent.Type.MouseButtonRelease:
                self._drag_pos = None
        return super().eventFilter(obj, event)

    def paintEvent(self, e):
        p = QPainter(self)
        # Draw title bar gradient
        grad = QLinearGradient(0, 0, self.width() - 4, 0)
        grad.setColorAt(0, QColor(_TITLE1))
        grad.setColorAt(1, QColor(_TITLE2))
        p.fillRect(2, 2, self.width() - 4, 20, grad)
        p.end()

    def _make_mode_card(self, title: str, desc: str, active: bool) -> QPushButton:
        btn = QPushButton()
        btn.setFixedSize(172, 100)
        btn.setCursor(Qt.CursorShape.ArrowCursor)

        inner = QVBoxLayout(btn)
        inner.setContentsMargins(8, 6, 8, 6)
        inner.setSpacing(4)

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
        inner.addStretch()

        self._style_mode(btn, active)
        return btn

    @staticmethod
    def _style_mode(btn: QPushButton, active: bool):
        if active:
            btn.setStyleSheet(
                "QPushButton {"
                "  background-color: #C0C0C0;"
                "  border-top: 2px solid #808080;"
                "  border-left: 2px solid #808080;"
                "  border-bottom: 2px solid #FFFFFF;"
                "  border-right: 2px solid #FFFFFF;"
                "  text-align: left;"
                "}"
            )
        else:
            btn.setStyleSheet(
                "QPushButton {"
                "  background-color: #C0C0C0;"
                "  border-top: 2px solid #FFFFFF;"
                "  border-left: 2px solid #FFFFFF;"
                "  border-bottom: 2px solid #808080;"
                "  border-right: 2px solid #808080;"
                "  text-align: left;"
                "}"
                "QPushButton:hover {"
                "  background-color: #D4D0C8;"
                "}"
            )

    def _select(self, mode: str):
        self._chosen = mode
        self._style_mode(self._quick_btn, mode == "quick")
        self._style_mode(self._deep_btn,  mode == "deep")

    def chosen_mode(self) -> str:
        return self._chosen


# ═══════════════════════════════════════════════════════════════════════════════
#  Fenetre principale Win98
# ═══════════════════════════════════════════════════════════════════════════════

class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Lumina — Data Recovery")
        self.setMinimumSize(800, 560)
        self.resize(1040, 680)

        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        # Widget central — silver base with raised outer bevel
        central = QWidget()
        central.setObjectName("LuminaCentral")
        central.setStyleSheet(
            "QWidget#LuminaCentral {"
            "  background-color: #C0C0C0;"
            "  border-top: 2px solid #FFFFFF;"
            "  border-left: 2px solid #FFFFFF;"
            "  border-bottom: 2px solid #808080;"
            "  border-right: 2px solid #808080;"
            "}"
        )
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(2, 2, 2, 2)
        root.setSpacing(0)

        # Barre de titre
        self._title_bar = TitleBar(self)
        root.addWidget(self._title_bar)

        # Separateur sous titre
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFixedHeight(2)
        sep.setStyleSheet("background-color: #808080; border: 0px;")
        root.addWidget(sep)

        # Corps : sidebar + contenu
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        self._sidebar = Sidebar()
        self._sidebar.nav_requested.connect(self._on_nav)
        body.addWidget(self._sidebar)

        # Separateur vertical
        vsep = QFrame()
        vsep.setFrameShape(QFrame.Shape.VLine)
        vsep.setFixedWidth(2)
        vsep.setStyleSheet("background-color: #808080; border: 0px;")
        body.addWidget(vsep)

        self._stack = QStackedWidget()
        self._stack.setStyleSheet("QStackedWidget { background-color: #C0C0C0; }")
        body.addWidget(self._stack, stretch=1)

        root.addLayout(body, stretch=1)

        # Barre de statut
        status_bar = QWidget()
        status_bar.setFixedHeight(18)
        status_bar.setStyleSheet("background-color: #C0C0C0; border-top: 1px solid #808080;")
        sb_row = QHBoxLayout(status_bar)
        sb_row.setContentsMargins(4, 0, 4, 0)
        sb_row.setSpacing(0)
        self._status_lbl = QLabel("Pret")
        self._status_lbl.setStyleSheet(
            "color: #000000; font-size: 10px; background: transparent;"
            "font-family: 'Work Sans', Arial;"
        )
        sb_row.addWidget(self._status_lbl)
        sb_row.addStretch()
        root.addWidget(status_bar)

        # ── Creer les ecrans ─────────────────────────────────────────────────
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

        # ── Connexions de signaux ─────────────────────────────────────────────
        self._home.disk_selected.connect(self._go_scan)
        self._home.history_scan_requested.connect(self._go_results)
        self._sd.disk_selected.connect(self._go_scan)
        self._scan.scan_finished.connect(self._go_results)
        self._scan.scan_cancelled.connect(self.show_home)
        self._results.new_scan_requested.connect(self.show_home)

        self.show_home()
        self._init_tray()

    # ── Icone de barre des taches ─────────────────────────────────────────────

    def _init_tray(self):
        self._tray = QSystemTrayIcon(self)

        pix = QPixmap(32, 32)
        pix.fill(QColor(_NAVY))
        p = QPainter(pix)
        p.setPen(QColor("#FFFFFF"))
        p.setFont(QFont("Work Sans", 16, QFont.Weight.Bold))
        p.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter, "L")
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
        if self._scan.is_scanning():
            self.hide()
            self._tray.showMessage(
                "Lumina",
                "Analyse en cours en arriere-plan. "
                "Utilisez 'Quitter Lumina' dans la barre systeme pour arreter.",
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
        self._status_lbl.setText("Pret")
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
        self._status_lbl.setText(f"Scan en cours : {disk.get('name', 'disque')}")
        self._fade_to(IDX_SCAN)

    def _go_results(self, files: list):
        self._results.load_results(files)
        self._sidebar.set_active(IDX_RESULTS)
        self._status_lbl.setText(f"{len(files)} fichier(s) trouve(s)")
        self._fade_to(IDX_RESULTS)

    # ── Transition de fondu ───────────────────────────────────────────────────

    def _fade_to(self, idx: int):
        if self._stack.currentIndex() == idx:
            return

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
