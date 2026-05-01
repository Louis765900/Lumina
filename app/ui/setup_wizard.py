from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QCursor
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
from app.ui.palette import (
    BG2 as _BG,
    MUTED as _MUTED,
    SUB as _SUB,
    TEXT as _TEXT,
)

# Wizard-specific overrides: solid/opaque values for a modal dialog context
_CARD   = "#1A1B2E"
_BORDER = "rgba(255,255,255,0.10)"
_HOVER  = "rgba(255,255,255,0.06)"


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
        self.setMinimumWidth(560)
        self.setStyleSheet(
            f"QDialog {{ background: {_BG}; }}"
            "QLabel { font-family: 'Inter', 'Segoe UI', Arial; }"
            "QComboBox, QLineEdit {"
            f"  background: rgba(255,255,255,0.04); color: {_TEXT};"
            f"  border: 1px solid {_BORDER}; border-radius: 8px;"
            "  padding: 7px 10px; font-size: 12px;"
            "}"
            "QCheckBox { color: #E2E8F0; font-size: 12px; }"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        card = QFrame()
        card.setStyleSheet(
            f"QFrame {{ background: {_CARD}; border: 1px solid {_BORDER};"
            " border-radius: 16px; }}"
        )
        layout = QVBoxLayout(card)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(16)

        title = QLabel("Bienvenue dans Lumina")
        title.setStyleSheet(f"color: {_TEXT}; font-size: 22px; font-weight: 800;")
        subtitle = QLabel(
            "Configurez les options essentielles avant votre première récupération."
        )
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet(f"color: {_SUB}; font-size: 12px;")
        layout.addWidget(title)
        layout.addWidget(subtitle)

        layout.addWidget(self._field_label("Langue"))
        self.language_combo = QComboBox()
        self.language_combo.addItem("Français", "fr")
        self.language_combo.addItem("English", "en")
        self._set_combo_value(self.language_combo, self._initial["language"])
        layout.addWidget(self.language_combo)

        layout.addWidget(self._field_label("Dossier de récupération par défaut"))
        dir_row = QHBoxLayout()
        dir_row.setSpacing(8)
        self.recovery_dir_edit = QLineEdit(str(self._initial["default_recovery_dir"]))
        browse_btn = QPushButton("Parcourir")
        browse_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        browse_btn.setFixedWidth(96)
        browse_btn.setStyleSheet(self._secondary_button_style())
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
            "Toujours privilégier une image disque avant un scan profond"
        )
        self.prefer_image_check.setChecked(bool(self._initial["prefer_image_first"]))
        layout.addWidget(self.prefer_image_check)

        disclaimer = QLabel(
            "Avertissement récupération\n"
            "- Ne récupérez jamais vers le disque source.\n"
            "- La récupération n'est jamais garantie.\n"
            "- Si les données sont importantes, créez d'abord une image disque."
        )
        disclaimer.setWordWrap(True)
        disclaimer.setStyleSheet(
            "color: #FDE68A; font-size: 12px; line-height: 1.5;"
            "background: rgba(245,158,11,0.10); border: 1px solid rgba(245,158,11,0.25);"
            "border-radius: 10px; padding: 12px;"
        )
        layout.addWidget(disclaimer)

        self.disclaimer_check = QCheckBox("J'ai compris et j'accepte cet avertissement")
        self.disclaimer_check.setChecked(bool(self._initial["accepted_disclaimer"]))
        self.disclaimer_check.toggled.connect(self._refresh_start_enabled)
        layout.addWidget(self.disclaimer_check)

        actions = QHBoxLayout()
        actions.addStretch()
        quit_btn = QPushButton("Quitter")
        quit_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        quit_btn.setFixedSize(92, 34)
        quit_btn.setStyleSheet(self._secondary_button_style())
        quit_btn.clicked.connect(self.reject)

        self.start_btn = QPushButton("Continuer")
        self.start_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.start_btn.setFixedSize(118, 34)
        self.start_btn.setStyleSheet(
            "QPushButton { background: #007AFF; color: white; border: none;"
            " border-radius: 8px; font-weight: 700; }"
            "QPushButton:hover { background: #005FCC; }"
            "QPushButton:disabled { background: rgba(100,116,139,0.35); color: #94A3B8; }"
        )
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
            f"color: {_MUTED}; font-size: 10px; font-weight: 800; letter-spacing: 1px;"
        )
        return label

    @staticmethod
    def _secondary_button_style() -> str:
        return (
            f"QPushButton {{ background: rgba(255,255,255,0.04); color: {_SUB};"
            f" border: 1px solid {_BORDER}; border-radius: 8px; font-weight: 600; }}"
            f"QPushButton:hover {{ background: {_HOVER}; color: {_TEXT}; }}"
        )

    @staticmethod
    def _set_combo_value(combo: QComboBox, value: str) -> None:
        idx = combo.findData(value)
        combo.setCurrentIndex(max(0, idx))

    def _browse_recovery_dir(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self,
            "Choisir le dossier de récupération",
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
                "Vous devez accepter l'avertissement de récupération pour continuer.",
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
