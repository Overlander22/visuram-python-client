# VisuRAM AppDaemon App – Installationsanleitung

## Voraussetzungen
- Home Assistant mit AppDaemon Add-on
- VisuRAM-PC (192.168.178.83) im gleichen Netzwerk wie HA

## Installation

### 1. AppDaemon Add-on installieren
HA → Einstellungen → Add-ons → Add-on Store → **AppDaemon** suchen → Installieren

### 2. Dateien kopieren
Folgende Dateien nach `/addon_configs/a0d7b954_appdaemon/apps/visuRAM/` kopieren:
- `visuRAM_app.py` (diese Datei)
- `area_mapping_app.py` (Floors/Areas/Labels-Zuweisung)
- `visuram_client.py` (aus `../scripts/`)
- `apply_area_mapping.py` (aus `../scripts/`)
- `cc600_channel_mapping.json` (aus `../data/`)
- `zone_area_mapping.json` (aus `../data/`)

Bevorzugt per `curl` aus GitHub – siehe Abschnitt „Deployment auf HA-Server"
in der Haupt-`README.md`. `websocket-client` als python_package im AppDaemon
ist Voraussetzung für `area_mapping_app`.

### 3. apps.yaml konfigurieren
Inhalt von `apps.yaml` in `/addon_configs/a0d7b954_appdaemon/apps/apps.yaml` einfügen.

### 4. AppDaemon starten / neu starten
HA → Add-ons → AppDaemon → Starten. Nach einem Datei-Deploy **immer komplett
neu starten** (`ha addons restart a0d7b954_appdaemon`) – der Hot-Reload lädt
Hilfsmodule/JSON unzuverlässig nach.

### 5. Logs prüfen
HA → Add-ons → AppDaemon → Log – dort sollte erscheinen:
```
VisuRAM App startet – Host: 192.168.178.83:80, Intervall: 20s
GlobalCallback: ~147 Sensor-Werte empfangen
```
Erwartete `WARNING`s: `ContainerXFeld2_Feld` (Analog-Balken, keine echten
Messwerte) sowie wenige Duplikat-Felder – harmlos.

## Entities in HA
Nach dem ersten erfolgreichen Poll erscheinen die Entities unter dem Gerät
„CC600", z.B. `sensor.cc600_00_aussentemperatur`, `sensor.cc600_01_raumtemperatur`.
