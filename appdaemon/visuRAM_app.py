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
    load_field_lookup,
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

        self._field_lookup = load_field_lookup()
        self.log(f"{len(self._field_lookup)} Kanal-Mappings für Service geladen")

        # Einheiten → HA Device Class
        self._UNIT_TO_CLASS = {
            "oC": "temperature", "°C": "temperature",
            "m/s": "wind_speed",
            "W": "power", "kW": "power",
            "%": "humidity",
        }

        # Ersten Poll sofort, dann alle N Sekunden
        self.run_every(self._poll, "now", interval)

        # HA-Service zum Schalten registrieren
        self.register_service("visuram/set_value", self._handle_set_value)
        self.log("Service 'visuram/set_value' registriert")

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
        """Schreibt alle Sensoren als HA-Entities.

        Entity-ID-Schema: sensor.nersingen_{cc600_adr}         (W1-Wert)
                          sensor.nersingen_{cc600_adr}_w2      (W2-Wert)
        Fallback (kein Mapping): sensor.nersingen_{feld_id_lower}
        """
        for feld_id, sensor in sensors.items():
            value = sensor.get("value", "")
            unit  = sensor.get("unit", "")
            if not value:
                continue

            # cc600_adr aus Lookup ermitteln
            # feld_id kommt als "Feld92_Feld" → Lookup-Key ist "Feld92"
            lookup_key = feld_id.replace("_Feld", "")
            entry = self._field_lookup.get(lookup_key)

            if entry:
                cc600_adr = entry["cc600_adr"]
                is_w2     = entry.get("is_w2", False)
                w2_label  = entry.get("w2_label", "")

                # W2-Entity überspringen wenn kein w2_label → kein sinnvoller Wert
                if is_w2 and not w2_label:
                    continue

                suffix    = "_w2" if is_w2 else ""
                entity_id = f"sensor.nersingen_{cc600_adr}{suffix}"
            else:
                # Fallback für Felder ohne Mapping-Eintrag
                entity_id = f"sensor.nersingen_{feld_id.lower().replace('_feld', '')}"

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
                "cc600_adr":           entry["cc600_adr"] if entry else None,
            }
            # None-Werte entfernen
            attributes = {k: v for k, v in attributes.items() if v is not None}

            self.set_state(entity_id, state=state, attributes=attributes)

    # ── Service-Handler: Schalten ────────────────────────────────────────
    def _handle_set_value(self, namespace: str, domain: str, service: str, kwargs: dict) -> None:
        """
        HA-Service 'visuram/set_value' – setzt einen CC600-Kanalwert.

        Pflichtparameter:
          feld_id   – FeldID, z.B. 'Feld92' (cc600_adr wird automatisch ermittelt)

        Optionale Parameter:
          w1        – W1-Wert, z.B. '12:00' (Gießdauer) oder '2' (Handstart ein)
          w2        – W2-Wert, z.B. '2' (Handstart ein), '0' (aus), '1' (Automatik)
          password  – Schreibpasswort, Standard: '1111'
          cc600_adr – CC600-Adresse (überschreibt Mapping-Lookup)

        Beispiel für Beregnungs-Handstart ein:
          service: visuram/set_value
          data:
            feld_id: "Feld92"
            w1: "12:00"
            w2: "2"
        """
        feld_id   = kwargs.get("feld_id")
        w1        = str(kwargs.get("w1", ""))
        w2        = str(kwargs.get("w2", ""))
        password  = str(kwargs.get("password", "1111"))
        cc600_adr = kwargs.get("cc600_adr")

        if not feld_id:
            self.log("visuram/set_value: Pflichtparameter 'feld_id' fehlt", level="ERROR")
            return

        if not cc600_adr:
            entry = self._field_lookup.get(feld_id)
            if not entry:
                self.log(
                    f"visuram/set_value: Kein CC600-Mapping für feld_id={feld_id!r}. "
                    "Bitte 'cc600_adr' explizit übergeben.",
                    level="ERROR",
                )
                return
            cc600_adr = entry["cc600_adr"]

        host = self._client.base_url.split("//")[1].split(":")[0]
        port = int(self._client.base_url.split(":")[-1].split("/")[0])

        self.log(f"set_value: {feld_id} adr={cc600_adr} w1={w1!r} w2={w2!r}")
        try:
            client = VisuRAMClient(host=host, port=port)
            client.connect()
            result = client.set_value(
                feld_id=feld_id,
                cc600_adr=cc600_adr,
                w1=w1,
                w2=w2,
                password=password,
            )
            self.log(f"set_value OK – {result[:120]}")
        except Exception as exc:
            self.log(
                f"set_value({feld_id}) FEHLER: {exc}\n{traceback.format_exc()}",
                level="ERROR",
            )
