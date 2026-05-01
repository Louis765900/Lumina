from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.core.settings import load_settings, save_settings, validate_settings


def needs_setup(settings: Mapping[str, Any]) -> bool:
    return not bool(settings.get("first_launch_done")) or not bool(
        settings.get("accepted_disclaimer")
    )


class SetupWizard(QDialog):
    def __init__(self, settings: Mapping[str, Any] | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self._initial = validate_settings(settings)
        self.setModal(True)
        self.setWindowTitle("Configuration Lumina")
        self.setMinimumWidth(480)
        self.setStyleSheet(
            "QDialog { background-color: #C0C0C0; }"
            "QLabel { font-family: 'Work Sans', Arial; background: transparent; }"
            "QLineEdit {"
            "  background-color: #FFFFFF; color: #000000;"
            "  border-top: 2px solid #808080; border-left: 2px solid #808080;"
            "  border-bottom: 2px solid #FFFFFF; border-right: 2px solid #FFFFFF;"
            "  padding: 3px 6px; font-size: 11px; font-family: 'Work Sans', Arial;"
            "}"
            "QCheckBox { color: #000000; font-size: 11px; font-family: 'Work Sans', Arial; }"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        card = QFrame()
        card.setStyleSheet("QFrame { background-color: #C0C0C0; }")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        title = QLabel("Bienvenue dans Lumina")
        title.setStyleSheet("color: #000000; font-size: 16px; font-weight: 800;")
        subtitle = QLabel(
            "Configurez les options essentielles avant votre premiere recuperation."
        )
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("color: #404040; font-size: 11px;")
        layout.addWidget(title)
        layout.addWidget(subtitle)

        sep = QFrame()
        sep.setFixedHeight(2)
        sep.setStyleSheet(
            "border-top: 1px solid #808080; border-bottom: 1px solid #FFFFFF;"
            "border-left: none; border-right: none;"
        )
        layout.addWidget(sep)

        layout.addWidget(self._field_label("Langue"))
        self.language_combo = QComboBox()
        self.language_combo.addItem("Francais", "fr")
        self.language_combo.addItem("English", "en")
        self._set_combo_value(self.language_combo, self._initial["language"])
        layout.addWidget(self.language_combo)

        layout.addWidget(self._field_label("Dossier de recuperation par defaut"))
        dir_row = QHBoxLayout()
        dir_row.setSpacing(6)
        self.recovery_dir_edit = QLineEdit(str(self._initial["default_recovery_dir"]))
        browse_btn = QPushButton("Parcourir")
        browse_btn.setCursor(Qt.CursorShape.ArrowCursor)
        browse_btn.setFixedWidth(80)
        browse_btn.clicked.connect(self._browse_recovery_dir)
        dir_row.addWidget(self.recovery_dir_edit, stretch=1)
        dir_row.addWidget(browse_btn)
        layout.addLayout(dir_row)

        layout.addWidget(self._field_label("Moteur de scan"))
        self.engine_combo = QComboBox()
        self.engine_combo.addItem("Auto", "auto")
        self.engine_combo.addItem("Natif rapide", "native")
        self.engine_combo.addItem("Python compatible", "python")
        self._set_combo_value(self.engine_combo, self._initial["scan_engine"])
        layout.addWidget(self.engine_combo)

        self.prefer_image_check = QCheckBox(
            "Toujours privilegier une image disque avant un scan profond"
        )
        self.prefer_image_check.setChecked(bool(self._initial["prefer_image_first"]))
        layout.addWidget(self.prefer_image_check)

        sep2 = QFrame()
        sep2.setFixedHeight(2)
        sep2.setStyleSheet(
            "border-top: 1px solid #808080; border-bottom: 1px solid #FFFFFF;"
            "border-left: none; border-right: none;"
        )
        layout.addWidget(sep2)

        disclaimer = QLabel(
            "Avertissement recuperation\n"
            "- Ne recuperez jamais vers le disque source.\n"
            "- La recuperation n'est jamais garantie.\n"
            "- Si les donnees sont importantes, creez d'abord une image disque."
        )
        disclaimer.setWordWrap(True)
        disclaimer.setStyleSheet(
            "color: #000000; font-size: 11px;"
            "background-color: #FFFFE0;"
            "border-top: 2px solid #808080; border-left: 2px solid #808080;"
            "border-bottom: 2px solid #FFFFFF; border-right: 2px solid #FFFFFF;"
            "padding: 8px;"
        )
        layout.addWidget(disclaimer)

        self.disclaimer_check = QCheckBox("J'ai compris et j'accepte cet avertissement")
        self.disclaimer_check.setChecked(bool(self._initial["accepted_disclaimer"]))
        self.disclaimer_check.toggled.connect(self._refresh_start_enabled)
        layout.addWidget(self.disclaimer_check)

        sep3 = QFrame()
        sep3.setFixedHeight(2)
        sep3.setStyleSheet(
            "border-top: 1px solid #808080; border-bottom: 1px solid #FFFFFF;"
            "border-left: none; border-right: none;"
        )
        layout.addWidget(sep3)

        actions = QHBoxLayout()
        actions.addStretch()
        quit_btn = QPushButton("Quitter")
        quit_btn.setCursor(Qt.CursorShape.ArrowCursor)
        quit_btn.setFixedSize(80, 26)
        quit_btn.clicked.connect(self.reject)

        self.start_btn = QPushButton("Continuer")
        self.start_btn.setCursor(Qt.CursorShape.ArrowCursor)
        self.start_btn.setFixedSize(100, 26)
        self.start_btn.clicked.connect(self.accept)
        actions.addWidget(quit_btn)
        actions.addWidget(self.start_btn)
        layout.addLayout(actions)

        root.addWidget(card)
        self._refresh_start_enabled()

    @staticmethod
    def _field_label(text: str) -> QLabel:
        label = QLabel(text.upper())
        label.setStyleSheet(
            "color: #000000; font-size: 10px; font-weight: 800; letter-spacing: 1px;"
            "background: transparent;"
        )
        return label

    @staticmethod
    def _set_combo_value(combo: QComboBox, value: str) -> None:
        idx = combo.findData(value)
        combo.setCurrentIndex(max(0, idx))

    def _browse_recovery_dir(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self,
            "Choisir le dossier de recuperation",
            self.recovery_dir_edit.text() or str(Path.home()),
        )
        if selected:
            self.recovery_dir_edit.setText(selected)

    def _refresh_start_enabled(self) -> None:
        self.start_btn.setEnabled(self.disclaimer_check.isChecked())

    def accept(self) -> None:
        if not self.disclaimer_check.isChecked():
            QMessageBox.warning(
                self,
                "Avertissement requis",
                "Vous devez accepter l'avertissement de recuperation pour continuer.",
            )
            return
        super().accept()

    def settings(self) -> dict[str, Any]:
        return validate_settings(
            {
                **self._initial,
                "language": self.language_combo.currentData(),
                "default_recovery_dir": self.recovery_dir_edit.text().strip(),
                "scan_engine": self.engine_combo.currentData(),
                "prefer_image_first": self.prefer_image_check.isChecked(),
                "accepted_disclaimer": True,
                "first_launch_done": True,
            }
        )


DialogFactory = Callable[[Mapping[str, Any], QWidget | None], Any]


def ensure_setup_complete(
    parent: QWidget | None = None,
    *,
    settings_file: str | Path | None = None,
    dialog_factory: DialogFactory | None = None,
) -> bool:
    current = load_settings(settings_file)
    if not needs_setup(current):
        return True

    factory = dialog_factory or SetupWizard
    dialog = factory(current, parent)
    result = dialog.exec()
    if result != QDialog.DialogCode.Accepted.value:
        return False

    save_settings(dialog.settings(), settings_file)
    return True
