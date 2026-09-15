#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLIENT_DESKTOP_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
DESKTOP_DIR="${XDG_DESKTOP_DIR:-$HOME/Desktop}"
SHORTCUT="$DESKTOP_DIR/SHARE Client.desktop"
ICON_PATH="$CLIENT_DESKTOP_DIR/src/share_desktop/assets/icons/share-client-idle.png"

mkdir -p "$DESKTOP_DIR"

cat > "$SHORTCUT" <<EOF2
[Desktop Entry]
Type=Application
Name=SHARE Client
Comment=Launch the SHARE Client desktop prototype
Exec=bash "$CLIENT_DESKTOP_DIR/scripts/run-share-client.sh"
Terminal=false
Categories=Utility;Development;
StartupNotify=true
Icon=$ICON_PATH
EOF2

chmod +x "$SHORTCUT" 2>/dev/null || true

if command -v gio >/dev/null 2>&1; then
  gio set "$SHORTCUT" metadata::trusted true 2>/dev/null || true
fi

printf 'Created desktop launcher: %s\n' "$SHORTCUT"
printf 'If Ubuntu opens it as text, right-click it and choose "Allow Launching".\n'
