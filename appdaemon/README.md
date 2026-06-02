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
- `visuram_client.py` (aus `../scripts/`)
- `cc600_channel_mapping.json` (aus `../data/`)

```bash
# Via SSH in HA (Port 22222 mit SSH Add-on):
mkdir -p /config/appdaemon/apps/visuRAM
# Dateien hochladen (z.B. via scp oder HA File Editor)
```

### 3. apps.yaml konfigurieren
Inhalt von `apps.yaml` in `/config/appdaemon/apps/apps.yaml` einfügen.

### 4. AppDaemon starten
HA → Add-ons → AppDaemon → Starten

### 5. Logs prüfen
HA → Add-ons → AppDaemon → Log – dort sollte erscheinen:
```
VisuRAM App startet – Host: 192.168.178.83:80, Intervall: 20s
68 Sensor-Namen geladen
```

## Entities in HA
Nach dem ersten erfolgreichen Poll erscheinen die Entities unter:
`sensor.nersingen_feld28` (Außentemperatur), `sensor.nersingen_feld33` (Wind), etc.
