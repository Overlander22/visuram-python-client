#!/bin/sh
# ─────────────────────────────────────────────────────────────────────────────
# Git-basiertes Deploy der VisuRAM-AppDaemon-Integration auf den HA-Server.
#
# Zieht den aktuellen Stand von origin/main aus GitHub in einen lokalen Klon auf
# dem HA-Server und kopiert die deploybaren Dateien ins AppDaemon-Verzeichnis,
# danach Add-on-Neustart. Damit ist garantiert immer der GitHub-Stand live.
#
# Auf dem HA-Server ausführen (SSH/Terminal-Add-on):
#     sh /config/visuram_repo/deploy/ha_pull_deploy.sh
#
# Erst-Setup (einmalig):
#     git clone https://github.com/Overlander22/visuram-python-client.git /config/visuram_repo
#
# apps.yaml wird BEWUSST nicht synchronisiert (umgebungsspezifische Konfig);
# bei Änderungen separat abgleichen.
# ─────────────────────────────────────────────────────────────────────────────
set -eu

REPO="${REPO:-/config/visuram_repo}"
ADDON="a0d7b954_appdaemon"
VDIR="/addon_configs/${ADDON}/apps/visuRAM"

echo ">> git fetch + hard reset auf origin/main ($REPO)"
git -C "$REPO" fetch --quiet origin main
git -C "$REPO" reset --hard --quiet origin/main
REV="$(git -C "$REPO" rev-parse --short HEAD)"

echo ">> kopiere deploybare Dateien nach $VDIR (Stand $REV)"
cp "$REPO/appdaemon/visuRAM_app.py"        "$VDIR/visuRAM_app.py"
cp "$REPO/appdaemon/area_mapping_app.py"   "$VDIR/area_mapping_app.py"
cp "$REPO/scripts/visuram_client.py"       "$VDIR/visuram_client.py"
cp "$REPO/scripts/apply_area_mapping.py"   "$VDIR/apply_area_mapping.py"
cp "$REPO/data/cc600_channel_mapping.json" "$VDIR/cc600_channel_mapping.json"
cp "$REPO/data/zone_area_mapping.json"     "$VDIR/zone_area_mapping.json"

echo ">> AppDaemon-Add-on neu starten"
ha apps restart "$ADDON"   # 'ha addons' ist deprecated -> 'ha apps'
echo ">> Deploy fertig – origin/main @ $REV ist live"
