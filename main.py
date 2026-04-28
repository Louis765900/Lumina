"""
Lumina - Data Recovery  v2.0
Point d'entrée : vérification des droits admin + bootstrap Qt.
"""

import ctypes
import os
import sys
import traceback


# ── Gestionnaire d'exception global ─────────────────────────────────────────

def _global_exception_handler(exc_type, exc_value, exc_tb):
    try:
        desktop = os.path.join(os.path.expanduser("~"), "Desktop")
        log_path = os.path.join(desktop, "lumina_crash.log")
        with open(log_path, "w", encoding="utf-8") as f:
            traceback.print_exception(exc_type, exc_value, exc_tb, file=f)
    except Exception:
        pass


sys.excepthook = _global_exception_handler


# ── Helpers admin ────────────────────────────────────────────────────────────

def _is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _request_elevation():
    params = " ".join(f'"{a}"' for a in sys.argv)
    ctypes.windll.shell32.ShellExecuteW(
        None, "runas", sys.executable, params, None, 1
    )


# ── Point d'entrée ───────────────────────────────────────────────────────────

def main():
    from PyQt6.QtWidgets import QApplication, QMessageBox

    app = QApplication(sys.argv)
    app.setApplicationName("Lumina")
    app.setApplicationVersion("2.0.0")
    app.setOrganizationName("Lumina Data Recovery")
    app.setQuitOnLastWindowClosed(False)

    # Charger la feuille de style
    qss_path = os.path.join(os.path.dirname(__file__), "app", "ui", "styles.qss")
    try:
        with open(qss_path, "r", encoding="utf-8") as f:
            app.setStyleSheet(f.read())
    except FileNotFoundError:
        app.setStyleSheet("QWidget { background-color: #0D0E1A; color: #FFFFFF; }")

    # Vérification des droits administrateur
    if not _is_admin():
        msg = QMessageBox()
        msg.setWindowTitle("Droits insuffisants — Lumina")
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setText(
            "<b style='font-size:14px;'>Lumina nécessite les droits Administrateur</b>"
        )
        msg.setInformativeText(
            "La lecture des disques bruts (PhysicalDrive) est une opération "
            "privilégiée sous Windows.<br><br>"
            "Cliquez sur <b>Relancer</b> pour obtenir l'invite UAC automatiquement."
        )
        relaunch = msg.addButton("↑  Relancer en Admin", QMessageBox.ButtonRole.AcceptRole)
        msg.addButton("Quitter", QMessageBox.ButtonRole.RejectRole)
        msg.setDefaultButton(relaunch)
        msg.exec()

        if msg.clickedButton() == relaunch:
            _request_elevation()
        sys.exit(0)

    from app.ui.setup_wizard import ensure_setup_complete

    if not ensure_setup_complete():
        sys.exit(0)

    # Lancer la fenêtre principale
    from app.ui.main_window import MainWindow
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
