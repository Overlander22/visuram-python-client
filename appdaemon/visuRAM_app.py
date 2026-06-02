"""
VisuRAM AppDaemon App – CC600 Gewächshaussteuerung → Home Assistant

Liest Sensordaten vom RAM GmbH CC600 via VisuRAM HTTP/JSON-Protokoll
und schreibt sie als Sensor-Entities in Home Assistant.

Installation:
  1. AppDaemon Add-on in HA installieren
  2. Diese Datei + visuram_client.py nach /config/appdaemon/apps/visuRAM/ kopieren
  3. apps.yaml konfigurieren (siehe unten)
  4. AppDaemon neu starten

apps.yaml Beispiel:
  visuRAM:
    module: visuRAM_app
    class: VisuRAMApp
    visurampc_host: "192.168.178.83"
    interval: 20
"""

import sys
import os
import traceback

import appdaemon.plugins.hass.hassapi as hass

# visuram_client.py liegt im gleichen Verzeichnis
sys.path.insert(0, os.path.dirname(__file__))

from visuram_client import (  # type: ignore
    VisuRAMClient,
    load_field_names,
    VISURAMPC_HOST,
    VISURAMPC_PORT,
    BILD_ID,
)


class VisuRAMApp(hass.Hass):
    """AppDaemon App: liest CC600-Sensordaten und schreibt sie in HA."""

    # ── Initialisierung ──────────────────────────────────────────────────
    def initialize(self) -> None:
        host     = self.args.get("visurampc_host", VISURAMPC_HOST)
        port     = int(self.args.get("visurampc_port", VISURAMPC_PORT))
        interval = int(self.args.get("interval", 20))

        self.log(f"VisuRAM App startet – Host: {host}:{port}, Intervall: {interval}s")

        self._client = VisuRAMClient(host=host, port=port)
        self._field_names = load_field_names()
        self.log(f"{len(self._field_names)} Sensor-Namen geladen")

        # Einheiten → HA Device Class
        self._UNIT_TO_CLASS = {
            "oC": "temperature", "°C": "temperature",
            "m/s": "wind_speed",
            "W": "power", "kW": "power",
            "%": "humidity",
        }

        # Ersten Poll sofort, dann alle N Sekunden
        self.run_every(self._poll, "now", interval)

    # ── Polling ──────────────────────────────────────────────────────────
    def _poll(self, kwargs) -> None:
        """Stellt Verbindung her, liest Sensordaten, schreibt HA-Entities."""
        try:
            # Stateless: jedes Mal neue Session (vermeidet VisuRAM-Ruhemodus)
            client = VisuRAMClient(
                host=self._client.base_url.split("//")[1].split(":")[0],
                port=int(self._client.base_url.split(":")[-1].split("/")[0]),
            )
            client.connect()

            # Initiale Sensordaten direkt nach BINITCALL
            sensors = dict(client._initial_sensors)
            client._initial_sensors = {}

            # Ein Polling-Zyklus für BPB-Updates
            for _ in range(5):
                s = client.poll()
                if s:
                    sensors.update(s)

            if sensors:
                self._push_sensors(sensors)
                self.log(f"{len(sensors)} Sensoren → HA", level="DEBUG")
            else:
                self.log("Keine Sensordaten empfangen", level="WARNING")

        except Exception as exc:
            self.log(f"Fehler beim Polling: {exc}\n{traceback.format_exc()}",
                     level="ERROR")

    # ── HA Entity Update ─────────────────────────────────────────────────
    def _push_sensors(self, sensors: dict) -> None:
        """Schreibt alle Sensoren als HA-Entities."""
        for feld_id, sensor in sensors.items():
            value = sensor.get("value", "")
            unit  = sensor.get("unit", "")
            if not value:
                continue

            entity_id    = f"sensor.nersingen_{feld_id.lower().replace('_feld', '')}"
            friendly     = self._field_names.get(feld_id, feld_id)
            device_class = self._UNIT_TO_CLASS.get(unit)

            # Numerischen Wert extrahieren
            try:
                state = str(float(value.replace(",", ".").split()[0]))
            except (ValueError, IndexError):
                state = value

            attributes = {
                "friendly_name":       friendly,
                "unit_of_measurement": unit or None,
                "device_class":        device_class,
                "source":              "VisuRAM CC600",
                "feld_id":             feld_id,
            }
            # None-Werte entfernen
            attributes = {k: v for k, v in attributes.items() if v is not None}

            self.set_state(entity_id, state=state, attributes=attributes)
