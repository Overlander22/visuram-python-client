# VisuRAM Python Client

Python-Client für die RAM GmbH VisuRAM-Gewächshaussteuerung (CC600).  
Reverse-engineered HTTP/JSON-Protokoll für **lokale Netzwerkintegration** – primär als Datenquelle für Home Assistant via MQTT Discovery.

---

## Hintergrund

Die Anlage **K2118 „Flora Toskana / Nersingen"** nutzt einen CC600-Steuerungscomputer (Baujahr 2003), der über RS-232 an einen Windows-PC angebunden ist. Auf diesem PC laufen:

- **DataCom45** – liest RS-232-Daten vom CC600
- **RAMService** (IIS/ASP.NET) – Web-Service-Bridge
- **VisuRAM** – Browser-basierte Visualisierung

Dieses Projekt greift über das vollständig reverse-engineerte HTTP/JSON-Protokoll direkt auf den RAMService zu.

---

## Protokoll (Kurzübersicht)

```
Session-Aufbau (3 Schritte):
  1. GET  /visuram/VisuRAM.aspx          → WCFID holen (2-stufig)
  2. POST /visuram/RAMService.asmx/GlobalService  OnGetRechte  → URECHT:2000
  3. POST /visuram/RAMService.asmx/GlobalService  BINITCALL    → BPB:true

Sensordaten (BildId=3, 77 Kanäle):
  POST /visuram/VisuRAM.aspx?...&WCFID=<n>   __CALLBACKID=__Page
  → sCONTEXT[OnGetAdviseData]ARG[F0{FeldID,Wert Unit}...NF{n}]

Alle 438 Kanäle (Parameterzeile, Branch feature/parameterzeile-polling):
  POST GlobalService  Context="Parameterzeile"  ARG="ID:x;adr0:CC600_ADR;..."
```

Detaillierte Protokolldokumentation: siehe Kommentare in `scripts/visuram_client.py`.

---

## Installation

```bash
pip install -r requirements.txt         # Laufzeit
pip install -r requirements-dev.txt     # Entwicklung + Tests
```

**Voraussetzung:** Python 3.10+, Netzwerkzugang zum VisuRAM-PC (192.168.178.83).

---

## Projektstruktur

```
visuram_python_client/
├── scripts/
│   ├── visuram_client.py         # CC600-Client: Session, Polling, Parsing, Mapping
│   └── apply_area_mapping.py     # HA-Script: Floors/Areas/Labels zuweisen (lokal ausführen)
├── appdaemon/
│   └── visuRAM_app.py            # AppDaemon-App für Home Assistant (MQTT Discovery)
├── data/
│   ├── cc600_channel_mapping.json  # 438 CC600-Kanäle mit Beschreibungen + FeldID-Mapping
│   ├── all_cc600_channels.json     # Rohdaten aus HAR-Analyse
│   ├── field_mapping.json          # FeldID → CC600-Adresse Mapping
│   └── zone_area_mapping.json      # Zonen → HA Floors/Areas/Labels (ausfüllen!)
├── tests/
│   ├── test_visuram_client.py      # Unit-Tests für visuram_client.py
│   └── test_apply_area_mapping.py  # Unit-Tests für apply_area_mapping.py
├── requirements.txt
├── requirements-dev.txt
└── README.md
```

---

## Home Assistant Integration

### Architektur

```
CC600 ──RS-232──► VisuRAM-PC (Windows)
                       │  HTTP/JSON
                       ▼
                  AppDaemon (N150)
                       │  MQTT Discovery
                       ▼
                  Home Assistant (N150)
                  sensor.nersingen_{cc600_adr}
```

### Entity-Schema

| Entity-ID | Beschreibung |
|---|---|
| `sensor.nersingen_{cc600_adr}` | W1-Wert eines CC600-Kanals |
| `sensor.nersingen_{cc600_adr}_w2` | W2-Wert (nur wenn beschriftet) |

**Naming:** `{zone}-{w1_label}` für W1, `{zone}-{desc}` für W2  
**Unique-ID:** via MQTT Discovery → Entities sind im HA Entity-Registry  
**Gerät:** „CC600 Nersingen (Flora Toskana)" in HA-Geräteansicht

### Deployment auf HA-Server

```bash
TOKEN="ghp_..."   # GitHub PAT (repo read)
BASE="https://api.github.com/repos/Overlander22/visuram-python-client/contents"
DEST="/addon_configs/a0d7b954_appdaemon/apps/visuRAM"

curl -H "Authorization: token $TOKEN" -H "Accept: application/vnd.github.v3.raw" \
  -Lo $DEST/visuRAM_app.py $BASE/appdaemon/visuRAM_app.py

curl -H "Authorization: token $TOKEN" -H "Accept: application/vnd.github.v3.raw" \
  -Lo $DEST/visuram_client.py $BASE/scripts/visuram_client.py
```

AppDaemon neu starten → Entities erscheinen in HA mit unique_id.

### Floors / Areas / Labels zuweisen

1. `data/zone_area_mapping.json` öffnen und `ha_floor`, `ha_area`, `ha_labels` pro Zone ausfüllen
2. Lokal ausführen:
   ```bash
   python3 scripts/apply_area_mapping.py
   python3 scripts/apply_area_mapping.py --dry-run   # Vorschau
   ```

Das Script ist **idempotent**: legt nur an was fehlt, ändert nichts Vorhandenes außer neue Labels hinzufügen.

### Service: CC600-Kanal schreiben

```yaml
service: visuram/set_value
data:
  feld_id: "Feld92"      # W1: Gießdauer
  w1: "12:00"
  w2: "2"                # 0=aus, 1=Automatik, 2=Manuell Ein
```

---

## Tests

```bash
pytest tests/ -v
pytest tests/ -v --cov=scripts --cov-report=term-missing
```

91 Tests (Stand 03.06.2026).

---

## Branches

| Branch | Inhalt |
|---|---|
| `main` | BildId=3 Polling (77 Kanäle), MQTT Discovery, set_value-Service |
| `feature/parameterzeile-polling` | Alle 438 Kanäle via Parameterzeile-API (60s Intervall) |

---

## Lizenz

Privates Projekt – kein öffentlicher Einsatz vorgesehen.
