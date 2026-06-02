# VisuRAM Python Client

Python-Client für die RAM GmbH VisuRAM-Gewächshaussteuerung (CC600).  
Reverse-engineered HTTP/JSON-Protokoll für **lokale Netzwerkintegration** – primär als Datenquelle für Home Assistant.

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

Sensordaten:
  POST /visuram/VisuRAM.aspx?...&WCFID=<n>   __CALLBACKID=__Page
  → sCONTEXT[OnGetAdviseData]ARG[F0{FeldID,Wert Unit}...NF{n}]
```

Detaillierte Protokolldokumentation: siehe Kommentare in `scripts/visuram_client.py`.

---

## Installation

```bash
pip install -r requirements.txt
```

**Voraussetzung:** Python 3.10+, Netzwerkzugang zum VisuRAM-PC.

---

## Schnellstart

```python
from scripts.visuram_client import VisuRAMClient

def on_sensors(sensors):
    for name, s in sensors.items():
        print(f"{name}: {s['value']} {s['unit']}")

client = VisuRAMClient(host="192.168.178.83")
client.run_loop(callback=on_sensors, interval=20.0)
```

---

## Projektstruktur

```
visuram_python_client/
├── scripts/
│   └── visuram_client.py    # Haupt-Client (Session, Polling, Parsing)
├── tests/                   # Unit-Tests (geplant)
├── data/                    # Sensor-Mapping, Konfigurationen
├── requirements.txt
└── README.md
```

---

## Offene Punkte / Roadmap

- [ ] Sensor-Mapping FeldID → Lesbare Namen
- [ ] Home Assistant REST API Push
- [ ] Write/Control: Magnetventile & Pumpen schalten
- [ ] Dynamische Sensor-Discovery
- [ ] Polling-Intervall optimieren (Ziel: ~20s stateless)

---

## Lizenz

Privates Projekt – kein öffentlicher Einsatz vorgesehen.
