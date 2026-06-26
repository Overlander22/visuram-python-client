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
import re
import sys
import traceback

import appdaemon.plugins.hass.hassapi as hass

# Zeitwert-Muster "MM:SS" / "HH:MM" – erkennt Dauern/Uhrzeiten auch dann, wenn
# VisuRAM keine Einheit (min:s/h:min) mitliefert (kommt bei einzelnen Feldern vor).
_TIME_RE = re.compile(r"^\d+:\d{2}$")

# Label-Stichwörter, die einen Zeitwert als DAUER (statt Uhrzeit) ausweisen.
# Greift nur, wenn im JSON kein explizites "wertart" gepflegt ist.
_DAUER_HINTS = ("dauer", "laufzeit", "anzahl", "einschaltdauer", "zeitintervall")

# Schalter-Enums: FELDART:Schalter (Drehschalter) sendet im Stream nur die nackte
# Zahl (0/1/2) – der Enum-Text steckt in der Schalter-Grafik, NICHT im Datenstrom.
# Wir leiten den Text aus der Stufenzahl ab (aus CSSSTUFEN im HTML erkannt).
# Belegung von HP bestätigt (04.06.2026):
#   2-stufig → 0=Aus, 1=Ein     (z.B. Sturmschutz manuell)
#   3-stufig → 0=Aus, 1=Auto, 2=Ein  (z.B. Bereg/Handstart-Drehschalter)
_SWITCH_ENUMS: dict[int, dict[str, str]] = {
    2: {"0": "Aus", "1": "Ein"},
    3: {"0": "Aus", "1": "Auto", "2": "Ein"},
}

# visuram_client.py liegt im gleichen Verzeichnis
sys.path.insert(0, os.path.dirname(__file__))

from visuram_client import (  # type: ignore
    VisuRAMClient,
    load_field_names,
    load_field_lookup,
    load_adr_lookup,
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
        self._field_lookup = load_field_lookup()   # feld_id→entry (nur noch set_value)
        self._adr_lookup   = load_adr_lookup()     # cc600_adr→Entity (Lesepfad, drift-immun)

        self.log(f"{len(self._field_names)} Sensor-Namen geladen")
        self.log(f"{len(self._adr_lookup)} Adress-Mappings geladen")

        # TOOLTIPADR-Lookup aus VisuRAM.aspx HTML: feld_id → cc600_adr (LIVE-Wahrheit).
        # Damit ist die Zuordnung immun gegen FeldID-Umnummerierungen (BildID 3):
        # feld_id → cc600_adr (hier, live) → Entity (self._adr_lookup, stabil).
        # Felder ohne TOOLTIPADR (Analogsymbol) sind nicht enthalten.
        self._html_adr_map: dict[str, str] = self._fetch_html_feld_adrs(host, port)
        # cc600_adrs die eine Entity haben (= Schlüssel des Adr-Lookups). Für die
        # Warnlogik: nur echte neue, ungemappte cc600_adr sollen warnen.
        self._covered_adrs: set[str] = set(self._adr_lookup.keys())

        # Einheiten → HA Device Class.
        # Bewusst OHNE "m/s"→wind_speed (HA würde sonst auf km/h umrechnen) und
        # OHNE "%"→humidity: die CC600-%-Werte sind Stellungen/Einschaltdauern,
        # KEINE Luftfeuchte. Mit device_class=humidity bekämen sie ein falsches
        # Feuchte-Symbol/-Statistik.
        self._UNIT_TO_CLASS = {
            "oC":  "temperature",
            "°C":  "temperature",
        }

        # Physikalische Einheiten → bleiben numerisch (mit unit_of_measurement).
        # Jede ANDERE nicht-leere "Einheit" ist in Wahrheit eine Enumeration/
        # ein Status-Text (z.B. "0 aus", "2 ein", "1 Mo", "6 W" = Himmelsricht.).
        # Solche Werte werden als Text "<Zahl> <Text>" publiziert (sonst zeigt
        # HA "0.0" mit Pseudo-Einheit "aus"). Zeit-Einheiten (min:s/h:min)
        # werden separat behandelt.
        self._REAL_UNITS = {"%", "oC", "°C", "klx", "klxh", "m/s", "K", "K/K", "d"}

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

        # Schalten: AppDaemon-internen Service + HA-Event-Listener registrieren.
        # Der register_service ist NUR AppDaemon-intern (taucht nicht in HA auf);
        # für HA-getriebene Steuerung (Automationen/Buttons/REST) lauschen wir auf
        # das HA-Event 'visuram_set_value' (POST /api/events/visuram_set_value).
        self.register_service("visuram/set_value", self._handle_set_value)
        self.listen_event(self._handle_set_value_event, "visuram_set_value")
        self.log("Schalten registriert: AppDaemon-Service + HA-Event 'visuram_set_value'")

    # ── HTML-Analyse ──────────────────────────────────────────────────────
    def _fetch_html_feld_adrs(self, host: str, port: int) -> dict[str, str]:
        """
        Lädt VisuRAM.aspx einmalig beim Start und extrahiert für jede FeldID
        die TOOLTIPADR (= cc600_adr) aus dem InitFeld()-Aufruf im JavaScript.

        Felder ohne TOOLTIPADR (FELDART:Analogsymbol) sind im Ergebnis nicht
        enthalten – sie können damit lautlos übersprungen werden.

        Gibt dict zurück: { "ContainerXFeldY" → "0102422101", "FeldXX" → ... }

        Nebenbei wird self._switch_enums befüllt: cc600_adr → {wert: text} für
        FELDART:Schalter-Felder (Drehschalter), die im Stream nur die Zahl liefern.
        """
        import requests as _req
        self._switch_enums: dict[str, dict] = {}
        try:
            session = _req.Session()
            session.headers.update({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:138.0) "
                              "Gecko/20100101 Firefox/138.0",
            })
            url    = f"http://{host}:{port}/visuram/VisuRAM.aspx"
            params = {"ClientY": 1080, "ClientX": 1920, "BodyX": 1854,
                      "BildId": 3}

            r1 = session.get(url, params=params, timeout=10)
            r1.raise_for_status()
            m = re.search(r"'&WCFID=(\d+)&BildId=", r1.text)
            if not m:
                self.log("HTML-Analyse: WCFID nicht gefunden", level="WARNING")
                return {}
            r2 = session.get(url, params={**params, "WCFID": m.group(1)},
                             timeout=10)
            r2.raise_for_status()

            result: dict[str, str] = {}
            for fm in re.finditer(
                r'InitFeld\("([^"]+_Feld)",\s*"([^"]*?)"', r2.text
            ):
                fid    = fm.group(1).replace("_Feld", "")
                params = fm.group(2)
                ta = re.search(r"TOOLTIPADR:([^;]+)", params)
                if not ta:
                    continue
                adr = ta.group(1).strip()
                result[fid] = adr
                # Schalter (Drehschalter): nur Zahl im Stream → Enum-Map nach
                # Stufenzahl (Anzahl Stufen in CSSSTUFEN, getrennt durch '|').
                if "FELDART:Schalter" in params:
                    css = re.search(r"CSSSTUFEN:([^;]+)", params)
                    nst = len([x for x in css.group(1).split("|") if x]) if css else 0
                    if nst in _SWITCH_ENUMS:
                        self._switch_enums[adr] = _SWITCH_ENUMS[nst]

            self.log(
                f"HTML-Analyse: {len(result)} FeldIDs mit TOOLTIPADR, "
                f"{len(self._switch_enums)} Schalter-Enums geladen"
            )
            return result

        except Exception as exc:
            self.log(f"HTML-Analyse fehlgeschlagen: {exc}", level="WARNING")
            return {}

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

            # feld_id → cc600_adr LIVE aus dem HTML auflösen (immun gegen FeldID-
            # Umnummerierung in BildID 3!), dann per STABILER Adresse die Ziel-
            # Entity nachschlagen. So landet der Wert immer bei der richtigen Entity,
            # egal welche FeldID VisuRAM dem Kanal aktuell zugewiesen hat.
            cc600_adr = self._html_adr_map.get(feld_id.replace("_Feld", ""))
            entry     = self._adr_lookup.get(cc600_adr) if cc600_adr else None

            if entry:
                unique_id = entry["unique_id"]
                object_id = unique_id
            else:
                # Kein Eintrag → KEINE Entity. Einmalig warnen, aber nur wenn es eine
                # echte neue, ungemappte cc600_adr ist (nicht für Analogsymbole ohne
                # TOOLTIPADR und nicht für bereits abgedeckte Adressen).
                if feld_id not in self._logged_unknown:
                    self._logged_unknown.add(feld_id)
                    if cc600_adr and cc600_adr not in self._covered_adrs:
                        self.log(
                            f"Unbekannter Sensor: {feld_id!r} "
                            f"(cc600_adr={cc600_adr}, Wert={value!r}). "
                            "In cc600_channel_mapping.json ergänzen.",
                            level="WARNING",
                        )
                    # else: Analogsymbol (kein TOOLTIPADR) → still
                continue

            friendly     = entry["label"]

            # State + Typ bestimmen. VisuRAM liefert Zeitwerte als String mit
            # Einheit "min:s" oder "h:min". Die Einheit allein sagt aber NICHT,
            # ob es eine Dauer oder eine Tageszeit ist (z.B. "Gießdauer" kommt
            # als h:min, ist aber eine Dauer). Klassifizierung daher per
            # JSON-Override "wertart" bzw. Label-Heuristik (_time_kind):
            #   Dauer   → device_class=duration, Wert in Sekunden (+ unit s)
            #   Uhrzeit → reiner Text "10:15" (CC600 liefert bereits lokal,
            #             KEINE Zeitzonen-/DST-Anpassung; device_class=timestamp
            #             würde in HA nach UTC wandeln → 2h-Versatz).
            # Alles andere: numerisch (mit Einheit) oder reiner Text.
            device_class = None
            ha_unit      = ""
            state        = value
            anzeige      = None  # menschenlesbarer Originalwert ("15:00"/"06:23")

            switch_map = self._switch_enums.get(cc600_adr)
            if switch_map is not None:
                # Schalter (Drehschalter): nackte Zahl → "Zahl Text", konsistent zu
                # den textführenden Datenfeld-Enums ("0 aus"). Text aus Schaltertyp.
                key = value.strip().split(".")[0].split(",")[0]
                txt = switch_map.get(key)
                if txt:
                    state = f"{value} {txt}"
            elif unit in ("min:s", "h:min") or _TIME_RE.match(value.strip()):
                # Zeitwert – auch wenn die Einheit fehlt (Muster "MM:SS"/"HH:MM").
                if self._time_kind(entry, friendly, unit) == "dauer":
                    secs = self._time_to_seconds(value, unit)
                    if secs is not None:
                        state, device_class, ha_unit, anzeige = str(secs), "duration", "s", value
                    else:
                        state = value  # unparsebar → Text
                # else: Uhrzeit → state bleibt der Original-String (Text)
            elif unit and unit not in self._REAL_UNITS:
                # Enumeration/Status/Himmelsrichtung → Text "<Zahl> <Text>",
                # z.B. "0 aus", "2 ein", "1 Mo", "6 W". Keine Einheit/device_class.
                state = f"{value} {unit}".strip()
            else:
                try:
                    state        = str(float(value.replace(",", ".").split()[0]))
                    device_class = self._UNIT_TO_CLASS.get(unit)
                    ha_unit      = self._UNIT_TO_HA.get(unit, unit)
                except (ValueError, IndexError):
                    state = value  # nicht-numerischer Text → Sensor ohne Einheit

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
            # retain=True: nach einem HA-Core-Neustart haben die Sensoren sofort
            # wieder ihren letzten Wert (statt ~bis zum nächsten Poll 'unknown' zu
            # sein) – sonst sind davon abhängige Bedienelemente (select/number)
            # kurzzeitig leer/unavailable.
            self._mqtt_publish(state_topic, state, retain=True)

            # ── Attributes publizieren ───────────────────────────────────
            attrs: dict = {"source": "VisuRAM CC600", "feld_id": feld_id,
                           "cc600_adr": cc600_adr, "zone": entry.get("zone", "")}
            # Menschenlesbaren Originalwert mitgeben (z.B. "15:00" zur Dauer in
            # Sekunden, "06:23" zur Uhrzeit) bzw. Roh-Einheit bei Text-Sensoren.
            if anzeige is not None:
                attrs["anzeige"] = anzeige
            elif unit and not ha_unit:
                attrs["einheit"] = unit
            self._mqtt_publish(attr_topic, json.dumps(attrs), retain=True)

    # ── Zeit-Konvertierung ────────────────────────────────────────────────
    @staticmethod
    def _time_kind(entry: dict | None, label: str, unit: str) -> str:
        """Klassifiziert einen Zeitwert als 'dauer' oder 'uhrzeit'.

        Priorität:
          1. Explizites JSON-Override `wertart` ('dauer' | 'uhrzeit')
          2. Einheit 'min:s' → immer Dauer
          3. Label-Heuristik (_DAUER_HINTS) → Dauer, sonst Uhrzeit
        """
        if entry:
            wa = entry.get("wertart")
            if wa in ("dauer", "uhrzeit"):
                return wa
        if unit == "min:s":
            return "dauer"
        lbl = label.lower()
        if any(h in lbl for h in _DAUER_HINTS):
            return "dauer"
        return "uhrzeit"

    @staticmethod
    def _time_to_seconds(value: str, unit: str):
        """Zeit-String → Gesamtsekunden (int) oder None.
        'min:s' interpretiert als MM:SS, 'h:min' als HH:MM."""
        try:
            a, b = value.strip().split(":")
            a, b = int(a), int(b)
        except (ValueError, AttributeError):
            return None
        return a * 3600 + b * 60 if unit == "h:min" else a * 60 + b

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

    # ── Schreib-Freigabe (Allowlist, Default-Deny) ───────────────────────
    def _is_writable(self, cc600_adr: str | None) -> bool:
        """True nur, wenn die cc600_adr im Mapping explizit als 'rw' freigegeben ist.
        Fehlender Eintrag oder 'ro' → False (Default-Deny: nichts versehentlich schreiben)."""
        entry = self._adr_lookup.get(cc600_adr) if cc600_adr else None
        return bool(entry) and entry.get("zugriff") == "rw"

    # ── Schreib-Antwort auswerten + Nutzer-Rückmeldung ───────────────────
    @staticmethod
    def _unescape(s: str) -> str:
        """\\uXXXX-Escapes, HTML-Tags und HTML-Entities (&nbsp; etc.) bereinigen."""
        import html as _html
        s = re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), s)
        s = re.sub(r"<[^>]+>", "", s)
        return _html.unescape(s).replace("\xa0", " ").strip()

    def _parse_change_response(self, raw: str) -> dict:
        """
        Wertet die OnChangeCCValue-Antwort aus.

        Rückgabe: {"mldg": <Ablehnungstext|None>, "w1": <best. W1>, "w2": <best. W2>}
        Eine nicht-leere MLDG = CC600 hat die Eingabe ABGELEHNT (Plausibilität);
        der Wert wurde dann NICHT übernommen (Antwort kommt trotzdem als HTTP 200).
        """
        def field(name: str) -> str:
            m = re.search(rf"{name}\{{(.*?)\}}", raw, re.S)
            return self._unescape(m.group(1)) if m else ""
        rowinfo = field("ROWINFO")
        w1 = re.search(r"W1:([^;]*)", rowinfo)
        w2 = re.search(r"W2:([^;]*)", rowinfo)
        return {
            "mldg": field("MLDG") or None,
            "w1": w1.group(1).strip() if w1 else "",
            "w2": w2.group(1).strip() if w2 else "",
        }

    def _notify_user(self, title: str, message: str, nid: str = "visuram_set_value") -> None:
        """Persistent Notification in HA – sichtbar für den Nutzer, der geschaltet hat."""
        try:
            self.call_service("persistent_notification/create",
                              title=title, message=message, notification_id=nid)
        except Exception as exc:
            self.log(f"persistent_notification fehlgeschlagen: {exc}", level="WARNING")

    @staticmethod
    def _normalize_decimal(value):
        """CC600-Komma-Dezimalwerte gegen HAs Native-Type-Parsing absichern.

        HA rendert das number-Template zu z.B. "17,0". Bei aktivierten
        *native template types* deutet HA diese Zeichenkette als Python-Tupel
        ``(17, 0)`` (das Komma ist Tupel-Syntax) und liefert sie via Event als
        Liste ``[17, 0]``. Ohne Korrektur würde ``str([17, 0])`` = "[17, 0]" an
        den CC600 gehen → Ablehnung "Wert 1: Eingabe fehlerhaft". Hier wird die
        Komma-Dezimale wieder zusammengesetzt (``[17, 0]`` → "17,0"); andere
        Werttypen bleiben unverändert.
        """
        if isinstance(value, (list, tuple)):
            return ",".join(str(v) for v in value)
        return value

    def _current_raw_value(self, client, adr: str) -> str:
        """Aktueller CC600-Roh-Wert (ohne Einheit) einer Adresse aus dem letzten
        GlobalCallback – um beim Schreiben den jeweils anderen Arbeitswert zu erhalten."""
        rev = {a: f for f, a in self._html_adr_map.items()}
        feld = rev.get(adr)
        if not feld:
            return ""
        s = (getattr(client, "_initial_sensors", {}) or {}).get(f"{feld}_Feld") or {}
        return str(s.get("value", ""))

    # ── Schalten: Einstiegspunkte (AppDaemon-Service + HA-Event) ─────────
    def _handle_set_value(self, namespace: str, domain: str, service: str,
                          kwargs: dict) -> None:
        """AppDaemon-interner Service-Aufruf 'visuram/set_value'."""
        self._do_set_value(kwargs or {})

    def _handle_set_value_event(self, event_name: str, data: dict, kwargs: dict) -> None:
        """HA-Event 'visuram_set_value' (aus Automationen/Skripten/REST feuerbar)."""
        self._do_set_value(data or {})

    def _do_set_value(self, kwargs: dict) -> None:
        """
        Setzt einen CC600-Kanalwert (Kern-Logik für Service UND Event).

        Einfacher Aufruf (empfohlen):
          cc600_adr | feld_id  – Ziel-Punkt (Entity-Adresse), z.B. '0102510112'
          value                – neuer Wert in CC600-Format, z.B. '2', '15:00', '25,0'
        Der Service leitet Kanal-Basis + Arbeitswert-Slot (W1/W2) aus der letzten Stelle
        der Adresse ab, ERHÄLT den jeweils anderen Arbeitswert und prüft die Schreib-
        Freigabe am Ziel-Punkt (Allowlist, Default-Deny).

        Expertenmodus (überschreibt value): explizite w1/w2 (cc600_adr = Kanal-Basis).

        Rückmeldung an den Nutzer:
          - CC600 lehnt ab (Plausibilität, MLDG) → WARNING + Persistent Notification.
          - Erfolg → sofortiger Poll, damit der neue Wert ohne Poll-Lag in HA erscheint.
        """
        feld_id   = kwargs.get("feld_id")
        cc600_adr = kwargs.get("cc600_adr")
        value     = self._normalize_decimal(kwargs.get("value"))
        w1_in     = self._normalize_decimal(kwargs.get("w1"))
        w2_in     = self._normalize_decimal(kwargs.get("w2"))
        password  = str(kwargs.get("password", "1111"))

        # Ziel-Punkt (Entity-Adresse) bestimmen
        target = cc600_adr
        if not target and feld_id:
            target = self._html_adr_map.get(feld_id.replace("_Feld", ""))
            if not target:
                entry = self._field_lookup.get(feld_id)
                target = entry["cc600_adr"] if entry else None
        if not target:
            self.log("visuram/set_value: 'cc600_adr' oder gültige 'feld_id' nötig",
                     level="ERROR")
            return

        # Schreib-Freigabe am ZIEL-PUNKT prüfen (Default-Deny)
        if not self._is_writable(target):
            z = (self._adr_lookup.get(target) or {}).get("zugriff", "unbekannt")
            msg = (f"Schreiben auf {target} ist nicht freigegeben (zugriff={z}). "
                   "Nur als 'rw' markierte Kanäle sind schreibbar.")
            self.log(f"visuram/set_value ABGELEHNT: {msg}", level="WARNING")
            self._notify_user("VisuRAM: Schreiben gesperrt", msg,
                              nid=f"visuram_setvalue_{target}")
            return

        host = self._client.base_url.split("//")[1].split(":")[0]
        port = int(self._client.base_url.split(":")[-1].split("/")[0])

        try:
            client = VisuRAMClient(host=host, port=port)
            client.connect()

            # Schreibparameter bestimmen
            if w1_in is not None or w2_in is not None:
                # Expertenmodus: explizite Arbeitswerte, target = Kanal-Basis
                ch_adr, w1, w2 = target, str(w1_in or ""), str(w2_in or "")
            else:
                if value is None:
                    self.log("visuram/set_value: 'value' (oder w1/w2) fehlt", level="ERROR")
                    self._notify_user("VisuRAM: Schreibfehler",
                                      f"{target}: kein Wert angegeben",
                                      nid=f"visuram_setvalue_{target}")
                    return
                # Kanal-Basis (W1-Form) + Slot aus letzter Stelle (P) ableiten
                p         = target[-1]
                ch_adr    = target[:-1] + "1"
                other_adr = ch_adr if p == "2" else (target[:-1] + "2")
                other     = self._current_raw_value(client, other_adr)
                # Sicherheit: existiert ein Geschwister-Arbeitswert, konnten wir ihn
                # aber nicht lesen → abbrechen, um ihn nicht zu überschreiben.
                if not other and other_adr in self._adr_lookup:
                    msg = (f"Anderer Arbeitswert ({other_adr}) nicht lesbar – Schreiben "
                           "abgebrochen, um ihn nicht zu überschreiben.")
                    self.log(f"set_value: {msg}", level="WARNING")
                    self._notify_user("VisuRAM: Schreiben abgebrochen",
                                      f"{target}: {msg}", nid=f"visuram_setvalue_{target}")
                    return
                w1, w2 = (other, str(value)) if p == "2" else (str(value), other)

            if not feld_id:
                feld_id = {a: f for f, a in self._html_adr_map.items()}.get(target, "")

            self.log(f"set_value: ziel={target} kanal={ch_adr} w1={w1!r} w2={w2!r}")
            result = client.set_value(feld_id=feld_id, cc600_adr=ch_adr,
                                      w1=w1, w2=w2, password=password)
            info = self._parse_change_response(result)

            if info["mldg"]:
                # CC600 hat abgelehnt (Plausibilität) – Wert NICHT übernommen
                self.log(f"set_value ABGELEHNT vom CC600: {info['mldg']} "
                         f"(W1={info['w1']!r} W2={info['w2']!r})", level="WARNING")
                self._notify_user(
                    "VisuRAM: Schreiben abgelehnt",
                    f"{target}: {info['mldg']} – der Wert wurde NICHT übernommen.",
                    nid=f"visuram_setvalue_{target}")
            else:
                self.log(f"set_value OK – ziel={target} W1={info['w1']!r} W2={info['w2']!r}")
                # Sofortiges Refresh: neuer Wert ohne Poll-Lag in HA sichtbar
                self.run_in(self._poll, 1)
        except Exception as exc:
            self.log(f"set_value({target}) FEHLER: {exc}\n{traceback.format_exc()}",
                     level="ERROR")
            self._notify_user("VisuRAM: Schreibfehler", f"{target}: {exc}",
                              nid=f"visuram_setvalue_{target}")
