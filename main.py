"""
Lumina - Data Recovery v1.0.0
Point d'entrée : vérification des droits admin + bootstrap Qt.
"""

import os
import sys
import traceback

from app.core.platform import is_admin, request_elevation


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


# ── Point d'entrée ───────────────────────────────────────────────────────────

def main():
    from PyQt6.QtWidgets import QApplication, QMessageBox

    app = QApplication(sys.argv)
    app.setApplicationName("Lumina")
    app.setApplicationVersion("1.0.0")
    app.setOrganizationName("Lumina Data Recovery")
    app.setQuitOnLastWindowClosed(False)

    # Charger la feuille de style
    qss_path = os.path.join(os.path.dirname(__file__), "app", "ui", "styles.qss")
    try:
        with open(qss_path, "r", encoding="utf-8") as f:
            app.setStyleSheet(f.read())
    except FileNotFoundError:
        app.setStyleSheet("QWidget { background-color: #0D0E1A; color: #FFFFFF; }")

    # Vérification des droits administrateur (root sur POSIX)
    if not is_admin():
        msg = QMessageBox()
        msg.setWindowTitle("Droits insuffisants — Lumina")
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setText(
            "<b style='font-size:14px;'>Lumina nécessite les droits Administrateur</b>"
        )
        msg.setInformativeText(
            "La lecture des disques bruts est une opération privilégiée.<br><br>"
            "Cliquez sur <b>Relancer</b> pour obtenir l'invite UAC (Windows) "
            "ou la fenêtre d'élévation (macOS) automatiquement. "
            "Sur Linux, redémarrez via <code>sudo</code>."
        )
        relaunch = msg.addButton("↑  Relancer en Admin", QMessageBox.ButtonRole.AcceptRole)
        msg.addButton("Quitter", QMessageBox.ButtonRole.RejectRole)
        msg.setDefaultButton(relaunch)
        msg.exec()

        if msg.clickedButton() == relaunch:
            params = " ".join(f'"{a}"' for a in sys.argv)
            request_elevation(params)
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
