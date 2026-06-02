"""
VisuRAM AppDaemon App – CC600 Gewächshaussteuerung → Home Assistant

Pollt alle Kanäle aus cc600_channel_mapping.json direkt via Parameterzeile-API
(kein BildId-Advise-Subscribe). Schreibt Sensorwerte als HA-Entities.

Installation:
  1. AppDaemon Add-on in HA installieren
  2. Diese Datei + visuram_client.py + cc600_channel_mapping.json nach
     /config/appdaemon/apps/visuRAM/ kopieren
  3. apps.yaml konfigurieren (siehe unten)
  4. AppDaemon neu starten

apps.yaml Beispiel:
  visuRAM:
    module: visuRAM_app
    class: VisuRAMApp
    visurampc_host: "192.168.178.83"
    interval: 60        # Sekunden zwischen Poll-Zyklen
    batch_size: 20      # Kanäle pro Parameterzeile-Call
"""

import sys
import os
import traceback

import appdaemon.plugins.hass.hassapi as hass

sys.path.insert(0, os.path.dirname(__file__))

from visuram_client import (  # type: ignore
    VisuRAMClient,
    load_field_names,
    load_field_lookup,
    VISURAMPC_HOST,
    VISURAMPC_PORT,
)


class VisuRAMApp(hass.Hass):
    """AppDaemon App: pollt alle CC600-Kanäle via Parameterzeile und schreibt sie in HA."""

    # ── Initialisierung ──────────────────────────────────────────────────
    def initialize(self) -> None:
        host       = self.args.get("visurampc_host", VISURAMPC_HOST)
        port       = int(self.args.get("visurampc_port", VISURAMPC_PORT))
        interval   = int(self.args.get("interval", 60))
        self._batch_size = int(self.args.get("batch_size", 20))

        self.log(f"VisuRAM App startet – Host: {host}:{port}, "
                 f"Intervall: {interval}s, Batch: {self._batch_size}")

        self._client = VisuRAMClient(host=host, port=port)
        self._field_names  = load_field_names()
        self._field_lookup = load_field_lookup()

        # Kanal-Liste aus cc600_channel_mapping.json aufbauen
        self._poll_channels = self._build_poll_channels()
        self.log(f"{len(self._poll_channels)} Kanäle zum Pollen geladen "
                 f"(von {len(self._load_mapping())} gesamt)")

        # Einheiten → HA Device Class
        self._UNIT_TO_CLASS = {
            "oC": "temperature", "°C": "temperature",
            "m/s": "wind_speed",
            "W": "power", "kW": "power",
            "%": "humidity",
        }

        self.run_every(self._poll, "now", interval)

        # HA-Service zum Schalten registrieren
        self.register_service("visuram/set_value", self._handle_set_value)
        self.log("Service 'visuram/set_value' registriert")

    # ── Kanal-Liste aufbauen ─────────────────────────────────────────────
    def _load_mapping(self) -> list:
        import json
        script_dir = os.path.dirname(__file__)
        for path in [
            os.path.join(script_dir, "cc600_channel_mapping.json"),
            os.path.join(os.path.dirname(script_dir), "data", "cc600_channel_mapping.json"),
        ]:
            if os.path.exists(path):
                with open(path, encoding="utf-8") as f:
                    return json.load(f)
        self.log("cc600_channel_mapping.json nicht gefunden!", level="ERROR")
        return []

    def _build_poll_channels(self) -> list[dict]:
        """
        Gibt eine Liste aller zu pollenden Kanäle zurück.
        Kanäle mit  "poll": false  in der JSON werden übersprungen.

        Jeder Eintrag enthält:
          {cc600_adr, w1_entity, w2_entity, w1_friendly, w2_friendly}
        """
        channels = []
        for ch in self._load_mapping():
            if not ch.get("poll", True):
                continue

            adr        = ch.get("cc600_adr", "")
            desc       = ch.get("desc", "")
            w1_label   = ch.get("w1_label", "") or desc
            w2_label   = ch.get("w2_label", "")
            feld_id_w1 = ch.get("feld_id_w1")
            feld_id_w2 = ch.get("feld_id_w2")

            if not adr:
                continue

            # W1-Entity: FeldID-Name wenn vorhanden, sonst cc600_adr
            if feld_id_w1:
                w1_entity   = f"sensor.nersingen_{feld_id_w1.lower()}"
                w1_friendly = self._field_names.get(f"{feld_id_w1}_Feld", w1_label)
            else:
                w1_entity   = f"sensor.nersingen_{adr}"
                w1_friendly = w1_label or adr

            # W2-Entity: nur wenn w2_label vorhanden
            if feld_id_w2:
                w2_entity   = f"sensor.nersingen_{feld_id_w2.lower()}"
                w2_friendly = self._field_names.get(f"{feld_id_w2}_Feld", w2_label)
            elif w2_label:
                w2_entity   = f"sensor.nersingen_{adr}_w2"
                w2_friendly = w2_label
            else:
                w2_entity   = None
                w2_friendly = ""

            channels.append({
                "cc600_adr":   adr,
                "w1_entity":   w1_entity,
                "w1_friendly": w1_friendly,
                "w2_entity":   w2_entity,
                "w2_friendly": w2_friendly,
            })

        return channels

    # ── Polling ──────────────────────────────────────────────────────────
    def _poll(self, kwargs) -> None:
        """Liest alle CC600-Kanäle via Parameterzeile und schreibt HA-Entities."""
        try:
            host = self._client.base_url.split("//")[1].split(":")[0]
            port = int(self._client.base_url.split(":")[-1].split("/")[0])
            client = VisuRAMClient(host=host, port=port)
            client.connect_lightweight()

            total_pushed = 0
            # Kanäle in Batches aufteilen
            for i in range(0, len(self._poll_channels), self._batch_size):
                batch = self._poll_channels[i : i + self._batch_size]
                addrs = [ch["cc600_adr"] for ch in batch]
                results = client.fetch_channels_batch(addrs, batch_id=f"b{i}")

                for ch_meta, result in zip(batch, results):
                    n = self._push_channel(ch_meta, result)
                    total_pushed += n

            self.log(f"{total_pushed} Sensor-Entities aktualisiert "
                     f"({len(self._poll_channels)} Kanäle gepolt)", level="DEBUG")

        except Exception as exc:
            self.log(f"Fehler beim Polling: {exc}\n{traceback.format_exc()}",
                     level="ERROR")

    # ── HA Entity Update ─────────────────────────────────────────────────
    def _push_channel(self, ch_meta: dict, result: dict) -> int:
        """Schreibt W1 (und ggf. W2) eines Kanals als HA-Entity. Gibt Anzahl zurück."""
        pushed = 0

        def write(entity_id: str, value: str, unit: str, friendly: str) -> None:
            nonlocal pushed
            if not value:
                return
            try:
                state = str(float(value.replace(",", ".").split()[0]))
            except (ValueError, IndexError):
                state = value

            dc = self._UNIT_TO_CLASS.get(unit)
            attrs = {
                "friendly_name":       friendly,
                "unit_of_measurement": unit or None,
                "device_class":        dc,
                "source":              "VisuRAM CC600",
                "cc600_adr":           result["cc600_adr"],
            }
            attrs = {k: v for k, v in attrs.items() if v is not None}
            self.set_state(entity_id, state=state, attributes=attrs)
            pushed += 1

        write(ch_meta["w1_entity"], result["w1_value"], result["w1_unit"],
              ch_meta["w1_friendly"])

        if ch_meta["w2_entity"]:
            write(ch_meta["w2_entity"], result["w2_value"], result["w2_unit"],
                  ch_meta["w2_friendly"])

        return pushed

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
