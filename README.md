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

Sensordaten (BildId=3, ~147 Werte pro Callback):
  POST /visuram/VisuRAM.aspx?...&WCFID=<n>   __CALLBACKID=__Page
  → sCONTEXT[OnGetAdviseData]ARG[F0{FeldID,Wert Unit}...NF{n}]

Alle 438 Kanäle (Parameterzeile, Branch feature/parameterzeile-polling):
  POST GlobalService  Context="Parameterzeile"  ARG="ID:x;adr0:CC600_ADR;..."
```

Detaillierte Protokolldokumentation: siehe Kommentare in `scripts/visuram_client.py`.

### Zwei Feld-Typen mit Werten (wichtig!)

Der GlobalCallback liefert **zwei** Arten von Feldern, die einen CC600-Wert tragen:

- `FeldXX_Feld` – reguläre Datenfelder/Schalter
- `ContainerXFeldY_Feld` – Datenfelder innerhalb eines Containers (u.a. **alle
  Raumtemperaturen**, Mitteltemperaturen, Schirm-/Lüftungs-Stellungen).
  Nur `ContainerXFeld1` trägt den Wert; `ContainerXFeld2` ist ein Analog-Balken
  (Füllstand-%) und wird ignoriert.

`parse_sensors` matcht beide: `(?:Feld\d+|Container\d+Feld\d+)_Feld`.

### cc600_adr-Struktur

`01` + `ZZ`(Zone, 2-stellig) + `KKKKK`(Kanal, 5-stellig) + `P`(1=W1, 2=W2).  
Beispiel `0102100011` → Zone 02, Kanal 10001, W1 (Raumtemp-Nord). Zone+Kanal sind
eindeutig, daher ist die cc600_adr auch aus dem Tooltip „ZZ Name KKKKK …" herleitbar.
Jeder JSON-Eintrag hält `feld_id_w1` UND `feld_id_w2`.

### Einheit „oC" → „°C" (HA-Gotcha)

VisuRAM liefert Temperaturen mit Einheit `oC` (Buchstabe o + C). Mit
`device_class=temperature` **lehnt Home Assistant** die MQTT-Discovery-Config
mit `oC` still ab → die Entity wird gar nicht angelegt. `visuRAM_app.py`
normalisiert daher `oC` → `°C` (`_UNIT_TO_HA`).

### Zeitwerte (Dauer vs. Uhrzeit)

VisuRAM liefert Zeitwerte als String mit Einheit `min:s` oder `h:min`. Die
Einheit sagt aber **nicht**, ob es eine Dauer oder eine Tageszeit ist (z.B.
„Gießdauer" kommt als `h:min`, ist aber eine Dauer). Klassifizierung in
`visuRAM_app.py`:

- **Dauer** → `device_class=duration`, Wert in **Sekunden** (+ `unit s`),
  Originalwert „15:00" als Attribut `anzeige`.
- **Uhrzeit** → reiner Text „10:15", genau wie vom CC600 geliefert. **Keine**
  Zeitzonen-/DST-Anpassung – der CC600 liefert bereits lokal. (`device_class=
  timestamp` würde in HA nach UTC wandeln → scheinbarer 2h-Versatz.)

Erkennung: optionales Feld **`wertart`** pro Kanal in
`cc600_channel_mapping.json` (`"dauer"` | `"uhrzeit"`) als Override; sonst
Heuristik (`min:s`→Dauer; Label enthält „dauer/laufzeit/anzahl/…"→Dauer;
sonst Uhrzeit). Nur Ausnahmen müssen via `wertart` gepflegt werden.

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
│   ├── visuRAM_app.py            # AppDaemon-App für Home Assistant (MQTT Discovery)
│   ├── area_mapping_app.py       # AppDaemon-App: Floors/Areas/Labels automatisch zuweisen
│   └── apps.yaml                 # AppDaemon-Konfiguration beider Apps
├── data/
│   ├── cc600_channel_mapping.json  # 486 CC600-Kanäle (438 Parameterzeile + 48 HTML) mit FeldID-Mapping
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
                  Gerät „CC600", Entities sensor.cc600_*
```

### Entity-Schema

| | Wert |
|---|---|
| **unique_id** | `cc600_{cc600_adr}` (W1) bzw. `cc600_{cc600_adr}_w2` (W2, nur wenn beschriftet) |
| **entity_id** | `sensor.cc600_<name-slug>`, z.B. `sensor.cc600_01_raumtemperatur` |
| **Gerät** | „CC600" (HA erzwingt `has_entity_name`-Verhalten → Entities erscheinen unter dem Gerät mit ihrem Kurznamen) |

**Naming (friendly):** `{zone}-{w1_label}` für W1, `{zone}-{desc}` für W2  
**Felder ohne Mapping** werden NICHT als Entity angelegt, sondern einmalig als
`WARNING` geloggt (Sicherheitsnetz für neue, noch nicht gemappte Sensoren).

### Deployment auf HA-Server

Dateien per `curl` aus GitHub (`main`) in das AppDaemon-Verzeichnis holen:

```bash
TOKEN="ghp_..."   # GitHub PAT (repo read)
BASE="https://api.github.com/repos/Overlander22/visuram-python-client/contents"
VDIR="/addon_configs/a0d7b954_appdaemon/apps/visuRAM"

for f in "appdaemon/visuRAM_app.py:$VDIR/visuRAM_app.py" \
         "appdaemon/area_mapping_app.py:$VDIR/area_mapping_app.py" \
         "scripts/visuram_client.py:$VDIR/visuram_client.py" \
         "scripts/apply_area_mapping.py:$VDIR/apply_area_mapping.py" \
         "data/cc600_channel_mapping.json:$VDIR/cc600_channel_mapping.json"; do
  src="${f%%:*}"; dst="${f##*:}"
  curl -fsSL -H "Authorization: token $TOKEN" -H "Accept: application/vnd.github.v3.raw" \
       -o "$dst" "$BASE/$src" && echo "OK $dst"
done
```

Danach **AppDaemon komplett neu starten** (Add-on-Restart, NICHT auf den
Hot-Reload verlassen – der lädt Hilfsmodule/JSON unzuverlässig nach):

```bash
ha addons restart a0d7b954_appdaemon
```

**Voraussetzung einmalig:** `websocket-client` als python_package im AppDaemon
(für `area_mapping_app`).

**Migration bei Prefix-/Geräte-Umbenennung:** Alte MQTT-Entities verschwinden
nur, wenn ihre retained Discovery-Topics geleert werden
(`homeassistant/sensor/<alte_unique_id>/config` mit leerem retained Payload).

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

89 Tests (Stand 03.06.2026).

---

## Branches

| Branch | Inhalt |
|---|---|
| `main` | BildId=3 Polling (Feld- + Container-Felder), MQTT Discovery, set_value-Service |
| `feature/parameterzeile-polling` | Alle 438 Kanäle via Parameterzeile-API (60s Intervall) |

---

## Lizenz

Privates Projekt – kein öffentlicher Einsatz vorgesehen.
