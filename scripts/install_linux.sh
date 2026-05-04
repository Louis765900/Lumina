#!/usr/bin/env bash
# Install a Lumina build (produced by `python scripts/build.py`)
# into a Linux system. Idempotent: re-running upgrades the install.

set -euo pipefail

INSTALL_DIR="/opt/lumina"
BIN_LINK="/usr/local/bin/lumina"
DESKTOP_FILE="/usr/share/applications/lumina.desktop"
ICON_TARGET_DIR="/usr/share/icons/hicolor/256x256/apps"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="$REPO_ROOT/dist/lumina"
DESKTOP_SRC="$REPO_ROOT/assets/lumina.desktop"
ICON_SRC="$REPO_ROOT/assets/lumina.png"

if [[ ! -d "$BUILD_DIR" ]]; then
    echo "[install] dist/lumina/ not found. Run: python scripts/build.py" >&2
    exit 1
fi
if [[ ! -f "$DESKTOP_SRC" ]]; then
    echo "[install] $DESKTOP_SRC missing — create assets/lumina.desktop first." >&2
    exit 1
fi

if [[ "${EUID}" -ne 0 ]]; then
    echo "[install] elevating with sudo…"
    exec sudo bash "$0" "$@"
fi

echo "[install] copying $BUILD_DIR → $INSTALL_DIR"
rm -rf "$INSTALL_DIR"
mkdir -p "$INSTALL_DIR"
cp -r "$BUILD_DIR/." "$INSTALL_DIR/"
chmod +x "$INSTALL_DIR/lumina" || true

echo "[install] symlink $BIN_LINK → $INSTALL_DIR/lumina"
ln -sf "$INSTALL_DIR/lumina" "$BIN_LINK"

echo "[install] desktop entry $DESKTOP_FILE"
install -Dm 0644 "$DESKTOP_SRC" "$DESKTOP_FILE"

if [[ -f "$ICON_SRC" ]]; then
    echo "[install] icon $ICON_TARGET_DIR/lumina.png"
    install -Dm 0644 "$ICON_SRC" "$ICON_TARGET_DIR/lumina.png"
fi

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database /usr/share/applications || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1 && [[ -f "$ICON_SRC" ]]; then
    gtk-update-icon-cache /usr/share/icons/hicolor || true
fi

cat <<EOF

[done] Lumina installed to $INSTALL_DIR
       launch via:   lumina
       uninstall:    sudo rm -rf $INSTALL_DIR $BIN_LINK $DESKTOP_FILE
EOF
