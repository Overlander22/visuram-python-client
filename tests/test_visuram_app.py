"""
Unit-Tests für appdaemon/visuRAM_app.py

Die App läuft normalerweise nur in der AppDaemon-Laufzeit (sie importiert
`appdaemon.plugins.hass.hassapi` und erbt von `hass.Hass`). Für die Tests wird
diese Laufzeit durch einen minimalen Stub ersetzt, sodass die reine Logik
isoliert prüfbar ist:

  1. _fetch_html_feld_adrs() – TOOLTIPADR-Map (FeldID → cc600_adr) aus dem
     VisuRAM.aspx-HTML extrahieren (HTTP via `responses` gemockt).
  2. Warnungs-Unterdrückung in _push_sensors_mqtt() – es darf nur dann eine
     WARNING geloggt werden, wenn die cc600_adr eines ungemappten Felds wirklich
     neu ist (nicht für Analogsymbole oder Duplikate).

Ausführen:
    pip install -r requirements-dev.txt
    pytest tests/ -v
"""

import json
import os
import sys
import types

import pytest
import responses as resp_mock


# ── AppDaemon-Laufzeit stubben, BEVOR visuRAM_app importiert wird ─────────────
# visuRAM_app macht `import appdaemon.plugins.hass.hassapi as hass` und erbt von
# hass.Hass. Lokal ist AppDaemon nicht installiert → minimale Fake-Module, damit
# der Import gelingt und die Logik testbar ist.
def _install_appdaemon_stub() -> None:
    if "appdaemon.plugins.hass.hassapi" in sys.modules:
        return
    ad      = types.ModuleType("appdaemon")
    plugins = types.ModuleType("appdaemon.plugins")
    hass    = types.ModuleType("appdaemon.plugins.hass")
    hassapi = types.ModuleType("appdaemon.plugins.hass.hassapi")

    class Hass:  # minimaler Ersatz für die AppDaemon-Basisklasse
        pass

    hassapi.Hass = Hass
    ad.plugins   = plugins
    plugins.hass = hass
    hass.hassapi = hassapi
    sys.modules.update({
        "appdaemon":                       ad,
        "appdaemon.plugins":               plugins,
        "appdaemon.plugins.hass":          hass,
        "appdaemon.plugins.hass.hassapi":  hassapi,
    })


_install_appdaemon_stub()

# scripts/ + appdaemon/ auf den Pfad: visuRAM_app macht `from visuram_client
# import ...` (flacher Modulname, wie auf dem Server) und liegt selbst in appdaemon/.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "scripts"))
sys.path.insert(0, os.path.join(_ROOT, "appdaemon"))

import visuRAM_app  # noqa: E402


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_app():
    """
    VisuRAMApp-Instanz ohne AppDaemon-__init__ (per __new__). Alle benötigten
    Attribute werden im jeweiligen Test gesetzt. `log` sammelt (level, message).
    """
    app = visuRAM_app.VisuRAMApp.__new__(visuRAM_app.VisuRAMApp)
    logged: list[tuple[str, str]] = []
    app.log = lambda msg, level="INFO", **kw: logged.append((level, msg))
    app._logged = logged
    return app


def _warnings(app) -> list[str]:
    return [msg for level, msg in app._logged if level == "WARNING"]


_ASPX_URL = "http://testhost:80/visuram/VisuRAM.aspx"

# Realistisches HTML-Fragment mit InitFeld()-Aufrufen (inkl. trailing leerer Args).
_HTML_WITH_FIELDS = '''
<script>
  InitFeld("Feld45_Feld","TOOLTIPADR:0102420101;FELDART:Datenfeld;ART:1","","");
  InitFeld("Container2Feld1_Feld","TOOLTIPADR:0101422101;FELDART:Datenfeld","","");
  InitFeld("Container2Feld2_Feld","FELDART:Analogsymbol;ART:7","","");
</script>
'''


# ─────────────────────────────────────────────────────────────────────────────
# _fetch_html_feld_adrs
# ─────────────────────────────────────────────────────────────────────────────

class TestFetchHtmlFeldAdrs:
    """HTML-Analyse: FeldID → cc600_adr aus TOOLTIPADR."""

    @resp_mock.activate
    def test_extrahiert_tooltipadr_und_ignoriert_analogsymbol(self):
        # 1. Request liefert WCFID, 2. Request das HTML mit InitFeld-Aufrufen
        resp_mock.add(resp_mock.GET, _ASPX_URL,
                      body="var u='page.aspx'&WCFID=12345&BildId=3';", status=200)
        resp_mock.add(resp_mock.GET, _ASPX_URL,
                      body=_HTML_WITH_FIELDS, status=200)

        app = _make_app()
        result = app._fetch_html_feld_adrs("testhost", 80)

        # Datenfelder mit TOOLTIPADR kommen rein, Analogsymbol (ohne) nicht
        assert result == {
            "Feld45":         "0102420101",
            "Container2Feld1": "0101422101",
        }
        assert "Container2Feld2" not in result
        # Erfolgs-Log nennt die Anzahl
        assert any("2 FeldIDs" in m for lvl, m in app._logged)

    @resp_mock.activate
    def test_zwei_requests_abgesetzt(self):
        resp_mock.add(resp_mock.GET, _ASPX_URL,
                      body="'&WCFID=999&BildId=3", status=200)
        resp_mock.add(resp_mock.GET, _ASPX_URL,
                      body=_HTML_WITH_FIELDS, status=200)

        app = _make_app()
        app._fetch_html_feld_adrs("testhost", 80)

        # Schritt 1 (WCFID holen) + Schritt 2 (HTML mit WCFID) = 2 Calls
        assert len(resp_mock.calls) == 2
        assert "WCFID=999" in resp_mock.calls[1].request.url

    @resp_mock.activate
    def test_fehlende_wcfid_gibt_leere_map_und_warnt(self):
        resp_mock.add(resp_mock.GET, _ASPX_URL,
                      body="<html>kein wcfid hier</html>", status=200)

        app = _make_app()
        result = app._fetch_html_feld_adrs("testhost", 80)

        assert result == {}
        assert any("WCFID nicht gefunden" in w for w in _warnings(app))
        # nach fehlender WCFID wird der 2. Request gar nicht erst abgesetzt
        assert len(resp_mock.calls) == 1

    @resp_mock.activate
    def test_http_fehler_gibt_leere_map_und_warnt(self):
        resp_mock.add(resp_mock.GET, _ASPX_URL, body="boom", status=500)

        app = _make_app()
        result = app._fetch_html_feld_adrs("testhost", 80)

        assert result == {}
        assert any("fehlgeschlagen" in w for w in _warnings(app))


# ─────────────────────────────────────────────────────────────────────────────
# Warnungs-Unterdrückung in _push_sensors_mqtt
# ─────────────────────────────────────────────────────────────────────────────

class TestWarnungUnterdrueckung:
    """
    Nur ungemappte Felder werden übergeben → _push_sensors_mqtt durchläuft
    ausschließlich den else-Zweig (die Warnungs-Entscheidung). Der MQTT-Publish-
    Pfad (mapped) wird nicht berührt.
    """

    def _app(self):
        app = _make_app()
        app._adr_lookup      = {}            # keine cc600_adr gemappt → else-Zweig
        app._logged_unknown  = set()
        app._covered_adrs    = {"0102420101"}  # diese adr ist bereits abgedeckt
        app._html_adr_map = {
            "Feld99":          "0109999991",  # neue adr, NICHT abgedeckt
            "Feld45":          "0102420101",  # adr bereits abgedeckt (Duplikat)
            # "Container2Feld2" fehlt → Analogsymbol (kein TOOLTIPADR)
        }
        return app

    def test_neue_cc600_adr_loest_warnung_aus(self):
        app = self._app()
        app._push_sensors_mqtt({
            "Feld99_Feld": {"value": "12.3", "unit": "%"},
        })
        warnings = _warnings(app)
        assert len(warnings) == 1
        assert "Feld99" in warnings[0]
        assert "0109999991" in warnings[0]

    def test_analogsymbol_bleibt_still(self):
        app = self._app()
        app._push_sensors_mqtt({
            "Container2Feld2_Feld": {"value": "50", "unit": "%"},
        })
        assert _warnings(app) == []

    def test_duplikat_bereits_abgedeckter_adr_bleibt_still(self):
        app = self._app()
        app._push_sensors_mqtt({
            "Feld45_Feld": {"value": "5", "unit": ""},
        })
        assert _warnings(app) == []

    def test_gemischt_nur_echter_neuer_sensor_warnt(self):
        app = self._app()
        app._push_sensors_mqtt({
            "Feld99_Feld":          {"value": "12.3", "unit": "%"},   # neu  → warnt
            "Feld45_Feld":          {"value": "5",    "unit": ""},    # dup  → still
            "Container2Feld2_Feld": {"value": "50",   "unit": "%"},   # bar  → still
        })
        warnings = _warnings(app)
        assert len(warnings) == 1
        assert "Feld99" in warnings[0]

    def test_warnung_nur_einmal_ueber_mehrere_polls(self):
        app = self._app()
        sensors = {"Feld99_Feld": {"value": "12.3", "unit": "%"}}
        app._push_sensors_mqtt(sensors)
        app._push_sensors_mqtt(sensors)   # zweiter Poll
        app._push_sensors_mqtt(sensors)   # dritter Poll
        assert len(_warnings(app)) == 1   # Dedup via _logged_unknown

    def test_bereits_geloggtes_feld_warnt_nicht_erneut(self):
        app = self._app()
        app._logged_unknown = {"Feld99_Feld"}   # schon in vorheriger Runde geloggt
        app._push_sensors_mqtt({
            "Feld99_Feld": {"value": "12.3", "unit": "%"},
        })
        assert _warnings(app) == []

    def test_leerer_wert_wird_uebersprungen(self):
        app = self._app()
        app._push_sensors_mqtt({
            "Feld99_Feld": {"value": "", "unit": "%"},   # kein Wert → continue
        })
        assert _warnings(app) == []
        assert "Feld99_Feld" not in app._logged_unknown


# ─────────────────────────────────────────────────────────────────────────────
# Adr-basierte Auflösung (Option B): feld_id → cc600_adr (live HTML) → Entity
# ─────────────────────────────────────────────────────────────────────────────

def _make_full_app(adr_lookup, html_adr_map):
    """App mit MQTT-Recorder + Einheiten-Dicts für den vollständigen Push-Pfad."""
    app = _make_app()
    app._adr_lookup   = adr_lookup
    app._html_adr_map = html_adr_map
    app._covered_adrs = set(adr_lookup)
    app._logged_unknown    = set()
    app._published_discovery = set()
    app._UNIT_TO_CLASS = {"oC": "temperature", "°C": "temperature"}
    app._REAL_UNITS    = {"%", "oC", "°C", "klx", "klxh", "m/s", "K", "K/K", "d"}
    app._UNIT_TO_HA    = {"oC": "°C"}
    published: list[tuple] = []
    app._mqtt_publish = lambda topic, payload, retain=False, qos=1: published.append(
        (topic, payload, retain))
    app._published = published
    return app


def _entry(uid, label, is_w2=False, zone="01"):
    return {"unique_id": uid, "base_adr": uid.replace("cc600_", "").replace("_w2", ""),
            "is_w2": is_w2, "label": label, "zone": zone, "wertart": ""}


class TestAdrResolution:
    """Der Wert einer FeldID landet bei der Entity ihrer cc600_adr (Live-HTML)."""

    def test_w1_wert_landet_bei_richtiger_entity(self):
        app = _make_full_app(
            adr_lookup={"0101123162": _entry("cc600_0101123162", "01-Wind Lee")},
            html_adr_map={"Feld12": "0101123162"},
        )
        app._push_sensors_mqtt({"Feld12_Feld": {"value": "12,0", "unit": "m/s"}})

        states = [p for p in app._published if p[0].endswith("/state")]
        assert ("nersingen/sensor/cc600_0101123162/state", "12.0", False) in states
        # Discovery-Config trägt das adr-basierte Label
        cfgs = [json.loads(p[1]) for p in app._published if p[0].endswith("/config")]
        assert any(c["name"] == "01-Wind Lee"
                   and c["unique_id"] == "cc600_0101123162"
                   and c.get("unit_of_measurement") == "m/s" for c in cfgs)

    def test_drift_immunitaet_andere_feldid_gleiche_adr(self):
        # Selbe cc600_adr, aber VisuRAM hat sie umnummeriert (Feld999 statt Feld12)
        app = _make_full_app(
            adr_lookup={"0101123162": _entry("cc600_0101123162", "01-Wind Lee")},
            html_adr_map={"Feld999": "0101123162"},
        )
        app._push_sensors_mqtt({"Feld999_Feld": {"value": "12,0", "unit": "m/s"}})
        states = [p[0] for p in app._published if p[0].endswith("/state")]
        # Trotz anderer FeldID landet der Wert bei derselben Entity
        assert "nersingen/sensor/cc600_0101123162/state" in states

    def test_w2_entity_wird_aus_w2_adr_erzeugt(self):
        app = _make_full_app(
            adr_lookup={"0101122102": _entry("cc600_0101122101_w2",
                                             "01-D-Lüftg: Stellung-West", is_w2=True)},
            html_adr_map={"FeldX": "0101122102"},
        )
        app._push_sensors_mqtt({"FeldX_Feld": {"value": "0,0", "unit": "%"}})
        states = [p[0] for p in app._published if p[0].endswith("/state")]
        assert "nersingen/sensor/cc600_0101122101_w2/state" in states

    def test_feldid_ohne_html_adr_erzeugt_keine_entity(self):
        # Feld ohne TOOLTIPADR (Analogsymbol) → nicht im html_adr_map → still
        app = _make_full_app(
            adr_lookup={"0101123162": _entry("cc600_0101123162", "01-Wind Lee")},
            html_adr_map={},
        )
        app._push_sensors_mqtt({"Container9Feld2_Feld": {"value": "50", "unit": "%"}})
        assert [p for p in app._published if p[0].endswith("/state")] == []
        assert _warnings(app) == []
