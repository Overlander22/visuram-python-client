"""
VisuRAM AppDaemon App – CC600 Gewächshaussteuerung → Home Assistant

Liest Sensordaten vom RAM GmbH CC600 via VisuRAM HTTP/JSON-Protokoll
und schreibt sie als MQTT-Discovery-Entities in Home Assistant.

Durch MQTT Discovery haben alle Entities eine unique_id und können in der
HA-UI bearbeitet, umbenannt und Bereichen/Ebenen zugewiesen werden.

Installation:
  1. AppDaemon Add-on in HA installieren
  2. Mosquitto MQTT Broker Add-on installieren + MQTT-Integration konfigurieren
  3. Diese Datei + visuram_client.py + cc600_channel_mapping.json nach
     /config/appdaemon/apps/visuRAM/ kopieren
  4. apps.yaml konfigurieren (siehe unten)
  5. AppDaemon neu starten

apps.yaml Beispiel:
  visuRAM:
    module: visuRAM_app
    class: VisuRAMApp
    visurampc_host: "192.168.178.83"
    interval: 20
"""

import json
import os
import sys
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
)

# MQTT-Basis-Topic für alle VisuRAM-Entities
MQTT_BASE      = "nersingen"
MQTT_AVAIL     = f"{MQTT_BASE}/available"
MQTT_DISCOVERY = "homeassistant"

# HA-Device-Info (erscheint in Geräte-Ansicht)
DEVICE_INFO = {
    "identifiers":    ["visuram_cc600_nersingen"],
    "name":           "CC600",
    "model":          "CC600 (Flora Toskana / Nersingen)",
    "manufacturer":   "RAM GmbH",
}


class VisuRAMApp(hass.Hass):
    """AppDaemon App: liest CC600-Sensordaten und schreibt sie via MQTT Discovery in HA."""

    # ── Initialisierung ──────────────────────────────────────────────────
    def initialize(self) -> None:
        host     = self.args.get("visurampc_host", VISURAMPC_HOST)
        port     = int(self.args.get("visurampc_port", VISURAMPC_PORT))
        interval = int(self.args.get("interval", 20))

        self.log(f"VisuRAM App startet – Host: {host}:{port}, Intervall: {interval}s")

        self._client = VisuRAMClient(host=host, port=port)
        self._field_names  = load_field_names()
        self._field_lookup = load_field_lookup()

        self.log(f"{len(self._field_names)} Sensor-Namen geladen")
        self.log(f"{len(self._field_lookup)} Kanal-Mappings geladen")

        # Einheiten → HA Device Class
        self._UNIT_TO_CLASS = {
            "oC":  "temperature",
            "°C":  "temperature",
            "m/s": "wind_speed",
            "W":   "power",
            "kW":  "power",
            "%":   "humidity",
        }

        # VisuRAM-Einheit → HA-gültige Einheit. KRITISCH: VisuRAM liefert "oC"
        # (Buchstabe o + C). Mit device_class=temperature lehnt HA "oC" als
        # ungültige Einheit ab und legt die Entity GAR NICHT an → alle
        # Temperaturen fehlten. HA verlangt "°C".
        self._UNIT_TO_HA = {
            "oC": "°C",
        }

        # Welche MQTT-Discovery-Configs wurden schon gepublisht?
        # Key: (unique_id, unit) – bei Einheitenänderung neu publizieren
        self._published_discovery: set[tuple[str, str]] = set()

        # FeldIDs ohne CC600-Mapping – einmalig warnen (statt jede 20s zu spammen)
        self._logged_unknown: set[str] = set()

        # MQTT Availability: "online" signalisieren
        self._mqtt_publish(MQTT_AVAIL, "online", retain=True)

        # Ersten Poll sofort, dann alle N Sekunden
        self.run_every(self._poll, "now", interval)

        # HA-Service zum Schalten registrieren
        self.register_service("visuram/set_value", self._handle_set_value)
        self.log("Service 'visuram/set_value' registriert")

    # ── Polling ──────────────────────────────────────────────────────────
    def _poll(self, kwargs) -> None:
        """Verbindet mit VisuRAM, liest Sensordaten, schreibt via MQTT in HA."""
        try:
            client = VisuRAMClient(
                host=self._client.base_url.split("//")[1].split(":")[0],
                port=int(self._client.base_url.split(":")[-1].split("/")[0]),
            )
            client.connect()

            sensors = dict(client._initial_sensors)
            client._initial_sensors = {}

            for _ in range(5):
                s = client.poll()
                if s:
                    sensors.update(s)

            if sensors:
                self._push_sensors_mqtt(sensors)
                self.log(f"{len(sensors)} Sensoren → MQTT", level="DEBUG")
            else:
                self.log("Keine Sensordaten empfangen", level="WARNING")

        except Exception as exc:
            self.log(f"Fehler beim Polling: {exc}\n{traceback.format_exc()}",
                     level="ERROR")

    # ── MQTT Entity Update ────────────────────────────────────────────────
    def _push_sensors_mqtt(self, sensors: dict) -> None:
        """
        Schreibt alle Sensoren via MQTT Discovery in HA.

        Für jede Entity:
          1. Discovery-Config publizieren (einmalig, mit retain)
          2. State publizieren (bei jedem Poll)

        Entity-ID-Schema in HA:
          sensor.cc600_{cc600_adr}       (W1-Wert)
          sensor.cc600_{cc600_adr}_w2    (W2-Wert)
        """
        for feld_id, sensor in sensors.items():
            value = sensor.get("value", "")
            unit  = sensor.get("unit", "")
            if not value:
                continue

            # cc600_adr + Typ ermitteln
            lookup_key = feld_id.replace("_Feld", "")
            entry = self._field_lookup.get(lookup_key)

            if entry:
                cc600_adr = entry["cc600_adr"]
                is_w2     = entry.get("is_w2", False)
                w2_label  = entry.get("w2_label", "")

                # W2-Entity überspringen wenn kein Label → kein sinnvoller Wert
                if is_w2 and not w2_label:
                    continue

                suffix    = "_w2" if is_w2 else ""
                unique_id = f"cc600_{cc600_adr}{suffix}"
                object_id = unique_id
            else:
                # Kein CC600-Mapping → KEINE Entity anlegen (würde sonst ohne Zone
                # in HA landen). Stattdessen einmalig warnen, damit ein wirklich
                # neuer, noch nicht gemappter Sensor auffällt und nicht still
                # verschwindet. Bekannte Fälle: Duplikat-Felder, die denselben
                # CC600-Kanal an einer zweiten Bildposition anzeigen.
                if feld_id not in self._logged_unknown:
                    self._logged_unknown.add(feld_id)
                    self.log(
                        f"FeldID ohne CC600-Mapping übersprungen: {feld_id!r} "
                        f"(Wert={value!r}). Falls echter Sensor: in "
                        "cc600_channel_mapping.json ergänzen.",
                        level="WARNING",
                    )
                continue

            friendly     = self._field_names.get(feld_id, feld_id)

            # Numerischen Wert extrahieren. Nicht-numerische Werte (Uhrzeiten
            # "06:23", Dauern "12:00", Texte "0 aus", Datum, Wochentag) als
            # reinen Text-Sensor behandeln: Sobald eine unit_of_measurement
            # gesetzt ist, verwirft HA nicht-numerische States → "unknown".
            try:
                state = str(float(value.replace(",", ".").split()[0]))
                is_numeric = True
            except (ValueError, IndexError):
                state = value
                is_numeric = False

            # Einheit + numerische device_class nur für numerische Werte.
            device_class = self._UNIT_TO_CLASS.get(unit) if is_numeric else None
            ha_unit      = self._UNIT_TO_HA.get(unit, unit) if is_numeric else ""

            state_topic = f"{MQTT_BASE}/sensor/{object_id}/state"
            attr_topic  = f"{MQTT_BASE}/sensor/{object_id}/attributes"

            # ── Discovery-Config (nur wenn neu oder Einheit geändert) ────
            discovery_key = (unique_id, unit)
            if discovery_key not in self._published_discovery:
                config: dict = {
                    "name":                 friendly,
                    "unique_id":            unique_id,
                    "object_id":            object_id,
                    "state_topic":          state_topic,
                    "availability_topic":   MQTT_AVAIL,
                    "json_attributes_topic": attr_topic,
                    "has_entity_name":      False,   # Gerätename NICHT voranstellen
                    "device":               DEVICE_INFO,
                }
                if ha_unit:
                    config["unit_of_measurement"] = ha_unit
                if device_class:
                    config["device_class"] = device_class

                self._mqtt_publish(
                    f"{MQTT_DISCOVERY}/sensor/{unique_id}/config",
                    json.dumps(config),
                    retain=True,
                )
                self._published_discovery.add(discovery_key)

            # ── State publizieren ────────────────────────────────────────
            self._mqtt_publish(state_topic, state, retain=False)

            # ── Attributes publizieren ───────────────────────────────────
            attrs: dict = {"source": "VisuRAM CC600", "feld_id": feld_id}
            if entry:
                attrs["cc600_adr"] = entry["cc600_adr"]
                attrs["zone"]      = entry.get("zone", "")
            # Roh-Einheit erhalten, wenn sie nicht als unit_of_measurement
            # dient (Text-Sensoren wie Uhrzeit "h:min", Dauer "min:s").
            if unit and not is_numeric:
                attrs["einheit"] = unit
            self._mqtt_publish(attr_topic, json.dumps(attrs), retain=False)

    # ── MQTT Helper ───────────────────────────────────────────────────────
    def _mqtt_publish(self, topic: str, payload: str,
                      retain: bool = False, qos: int = 1) -> None:
        """Publiziert eine MQTT-Nachricht via HA mqtt.publish Service."""
        try:
            self.call_service(
                "mqtt/publish",
                topic=topic,
                payload=payload,
                retain=retain,
                qos=qos,
            )
        except Exception as exc:
            self.log(f"MQTT publish fehlgeschlagen ({topic}): {exc}", level="ERROR")

    # ── Service-Handler: Schalten ────────────────────────────────────────
    def _handle_set_value(self, namespace: str, domain: str, service: str,
                          kwargs: dict) -> None:
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
