"""
Unit-Tests für visuram_client.py

Ausführen:
    pip install -r requirements-dev.txt
    pytest tests/ -v

Oder mit Coverage-Report:
    pytest tests/ -v --cov=scripts --cov-report=term-missing
"""

import datetime
import re
import sys
import os

import pytest
import responses as resp_mock
import requests

# Pfad zum scripts-Ordner ergänzen
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from scripts.visuram_client import (
    service_password,
    decode_xml_names,
    parse_sensors,
    parse_status,
    build_get_rechte_arg,
    build_binitcall_arg,
    build_poll_arg,
    _build_arg,
    VisuRAMClient,
    VISURAMPC_HOST,
    VISURAMPC_PORT,
)


# ─────────────────────────────────────────────────────────────────────────────
# service_password
# ─────────────────────────────────────────────────────────────────────────────

class TestServicePassword:
    """Tagespasswort-Algorithmus (aus RAMServicePassword.dll reverse-engineered)."""

    def test_bekanntes_passwort_k2118(self):
        """K2118 – Passwort aus Live-Test am 02.06.2026 verifiziert."""
        # Im Live-Test wurde "#275" für 02.06.2026 ausgegeben
        result = service_password(2118, datetime.date(2026, 6, 2))
        assert result == "#275"

    def test_format_beginnt_mit_hash(self):
        pw = service_password(2118, datetime.date(2026, 6, 1))
        assert pw.startswith("#")

    def test_format_drei_zeichen_nach_hash(self):
        pw = service_password(2118, datetime.date(2026, 6, 1))
        assert len(pw) == 4  # "#" + 3 Zeichen

    def test_unterschiedliche_daten_unterschiedliche_passwörter(self):
        d1 = service_password(2118, datetime.date(2026, 6, 1))
        d2 = service_password(2118, datetime.date(2026, 6, 2))
        assert d1 != d2

    def test_unterschiedliche_k_nummern(self):
        p1 = service_password(2118, datetime.date(2026, 6, 1))
        p2 = service_password(1000, datetime.date(2026, 6, 1))
        assert p1 != p2

    def test_erste_ziffer_maximal_5(self):
        """Die erste Ziffer nach '#' ist immer ≤ 5 (Algorithmus-Eigenschaft)."""
        for day in range(1, 30):
            pw = service_password(2118, datetime.date(2026, 6, day))
            assert int(pw[1]) <= 5, f"Tag {day}: {pw}"


# ─────────────────────────────────────────────────────────────────────────────
# decode_xml_names
# ─────────────────────────────────────────────────────────────────────────────

class TestDecodeXmlNames:

    def test_eckige_klammern(self):
        assert decode_xml_names("ARG_x005B_WERT_x005D_") == "ARG[WERT]"

    def test_komma(self):
        assert decode_xml_names("A_x002C_B") == "A,B"

    def test_geschweifte_klammern(self):
        assert decode_xml_names("F0_x007B_Feld1_x002C_28_x007D_") == "F0{Feld1,28}"

    def test_kein_escape_unveraendert(self):
        assert decode_xml_names("CONTEXT[OnCycleTimer]") == "CONTEXT[OnCycleTimer]"

    def test_verschachtelter_ausdruck(self):
        raw = (
            "CONTEXT_x005B_OnGetAdviseData_x005D_"
            "ARG_x005B_F0_x007B_Feld33_Feld_x002C_1_x002C_4 m/s_x007D_NF_x007B_1_x007D__x005D_"
        )
        decoded = decode_xml_names(raw)
        assert "CONTEXT[OnGetAdviseData]" in decoded
        assert "F0{Feld33_Feld,1,4 m/s}" in decoded
        assert "NF{1}" in decoded


# ─────────────────────────────────────────────────────────────────────────────
# parse_sensors
# ─────────────────────────────────────────────────────────────────────────────

class TestParseSensors:
    """Parst den GlobalCallback-Response-String (VisuRAM.aspx)."""

    def _make_raw(self, fields: list[tuple[str, str]]) -> str:
        """Hilfsfunktion: baut einen realistischen Raw-Callback-String."""
        parts = []
        for i, (name, val) in enumerate(fields):
            # Encode Komma in Wert
            val_enc = val.replace(",", "_x002C_")
            parts.append(
                f"F{i}_x007B_{name}_x002C_{val_enc}_x007D_"
            )
        nf = len(fields)
        body = "".join(parts) + f"NF_x007B_{nf}_x007D_"
        return f"sCONTEXT_x005B_OnGetAdviseData_x005D_ARG_x005B_{body}_x005D_"

    def test_einzelner_sensor(self):
        raw = self._make_raw([("Feld28_Feld", "28_x002C_4?oC")])
        sensors = parse_sensors(raw)
        assert "Feld28_Feld" in sensors
        assert sensors["Feld28_Feld"]["value"] == "28,4"
        assert sensors["Feld28_Feld"]["unit"] == "oC"

    def test_mehrere_sensoren(self):
        raw = self._make_raw([
            ("Feld28_Feld", "28_x002C_4?oC"),
            ("Feld33_Feld", "1_x002C_1?m/s"),
            ("Feld27_Feld", "62_x002C_0?klx"),
        ])
        sensors = parse_sensors(raw)
        assert len(sensors) == 3
        assert sensors["Feld33_Feld"]["value"] == "1,1"
        assert sensors["Feld33_Feld"]["unit"] == "m/s"

    def test_fragezeichen_wert_wird_uebersprungen(self):
        """Felder mit '?' als Wert (noch nicht von DataCom45 befüllt) ignorieren."""
        raw = self._make_raw([
            ("Feld28_Feld", "?"),
            ("Feld33_Feld", "1_x002C_1?m/s"),
        ])
        sensors = parse_sensors(raw)
        assert "Feld28_Feld" not in sensors
        assert "Feld33_Feld" in sensors

    def test_container_felder_werden_ignoriert(self):
        """ContainerXFeldY_Feld-Felder sind UI-State, keine Sensorwerte."""
        raw = self._make_raw([
            ("Container5Feld1_Feld", "28_x002C_4?oC"),
            ("Feld28_Feld", "28_x002C_4?oC"),
        ])
        sensors = parse_sensors(raw)
        assert "Container5Feld1_Feld" not in sensors
        assert "Feld28_Feld" in sensors

    def test_gif_felder_werden_ignoriert(self):
        """Symbol/Icon-Felder (~/Vorlagen/Symbole/Leer.gif) ignorieren."""
        raw = self._make_raw([
            ("Feld81_Feld", "~/Vorlagen/Symbole/Leer.gif_x002C_false_x002C_false"),
            ("Feld28_Feld", "28_x002C_4?oC"),
        ])
        sensors = parse_sensors(raw)
        assert "Feld81_Feld" not in sensors
        assert "Feld28_Feld" in sensors

    def test_leerer_response(self):
        """Leere oder ungültige Antwort gibt leeres Dict zurück."""
        assert parse_sensors("") == {}
        assert parse_sensors("sCONTEXT_x005B_OnGetAdviseData_x005D_ARG_x005B__x005D_") == {}

    def test_wert_mit_leerzeichen_als_trennzeichen(self):
        """Folge-Callbacks nutzen Leerzeichen statt '?' als Trennzeichen."""
        raw = self._make_raw([("Feld33_Feld", "0_x002C_9 m/s")])
        sensors = parse_sensors(raw)
        assert sensors["Feld33_Feld"]["value"] == "0,9"
        assert sensors["Feld33_Feld"]["unit"] == "m/s"

    def test_wert_ohne_einheit(self):
        """Felder ohne Einheit (z.B. numerische Zustände)."""
        raw = self._make_raw([("Feld93_Feld", "0")])
        sensors = parse_sensors(raw)
        assert sensors["Feld93_Feld"]["value"] == "0"
        assert sensors["Feld93_Feld"]["unit"] == ""


# ─────────────────────────────────────────────────────────────────────────────
# parse_status
# ─────────────────────────────────────────────────────────────────────────────

class TestParseStatus:

    def test_binitcall_antwort(self):
        raw = (
            '{"d":"CONTEXT_x005B_OnCycleTimer_x005D_BDONTWAIT_x005B_true_x005D_'
            'ARG_x005B_CURRENTBILDID:3;USER:;STOERCSS:Stoertaste_0_Static;'
            'CCZEIT: 02.06.26 13:11;BPB:true;BINITCALL:true;_x005D_"}'
        )
        status = parse_status(raw)
        assert status.get("CURRENTBILDID") == "3"
        assert status.get("BPB") == "true"
        assert status.get("BINITCALL") == "true"
        assert "13:11" in status.get("CCZEIT", "")

    def test_leere_antwort(self):
        assert parse_status("") == {}


# ─────────────────────────────────────────────────────────────────────────────
# sArg-Builder
# ─────────────────────────────────────────────────────────────────────────────

class TestArgBuilder:

    def test_get_rechte_arg_struktur(self):
        arg = build_get_rechte_arg(0)
        assert "CONTEXT_x005B_OnGetRechte_x005D_" in arg
        assert "BDONTWAIT_x005B_false_x005D_" in arg
        assert "FREIGABE:3;" in arg

    def test_binitcall_arg_trigger_true(self):
        """TRIGGERSERVERTIMER muss true sein (kritisch für DataCom45-Aktivierung)."""
        arg = build_binitcall_arg(1)
        assert "TRIGGERSERVERTIMER:true" in arg
        assert "BINITCALL:true" in arg
        assert "BDONTWAIT_x005B_true_x005D_" in arg

    def test_poll_arg_trigger_false(self):
        """Normale Polls senden TRIGGERSERVERTIMER:false."""
        arg = build_poll_arg(5)
        assert "TRIGGERSERVERTIMER:false" in arg
        assert "PKLKETTE:0" in arg

    def test_servicecounter_enthalten(self):
        arg = build_get_rechte_arg(42)
        assert "SERVICECOUNTER_x005B_42:" in arg


# ─────────────────────────────────────────────────────────────────────────────
# VisuRAMClient (HTTP-gemockt)
# ─────────────────────────────────────────────────────────────────────────────

BASE_URL = f"http://{VISURAMPC_HOST}:{VISURAMPC_PORT}/visuram"

# Minimales VisuRAM.aspx HTML mit WCFID=1234 eingebettet
_VISURAMASPX_HTML = (
    "<html><body>"
    "<input id='__VIEWSTATE' value='dummyviewstate' />"
    "<input id='__VIEWSTATEGENERATOR' value='07F87BCC' />"
    "location.href='./VisuRAM.aspx?ClientY=' + GetClientY() + "
    "'&WCFID=1234&BildId=3';;InitMsgBox(\"...\")"
    "</body></html>"
)

_ONGETRECHTE_RESP = (
    '{"d":"CONTEXT_x005B_OnGetRechte_x005D_BDONTWAIT_x005B_false_x005D_'
    'ARG_x005B_URECHT:2000;USER:;_x005D_SERVICECOUNTER_x005B_0:123_x005D_"}'
)

_BINITCALL_RESP_WITH_BPB = (
    '{"d":"CONTEXT_x005B_OnCycleTimer_x005D_BDONTWAIT_x005B_true_x005D_'
    'ARG_x005B_CURRENTBILDID:3;USER:;STOERCSS:Stoertaste_0_Static;'
    'CCZEIT: 02.06.26 13:00;BPB:true;BINITCALL:true;_x005D_'
    'SERVICECOUNTER_x005B_1:456_x005D_"}'
)

_GLOBAL_CALLBACK_RESP = (
    "sCONTEXT_x005B_OnGetAdviseData_x005D_"
    "ARG_x005B_"
    "F0_x007B_Feld28_Feld_x002C_28_x002C_4?oC_x007D_"
    "F1_x007B_Feld33_Feld_x002C_1_x002C_1?m/s_x007D_"
    "NF_x007B_2_x007D_"
    "_x005D_"
)

_CYCLETIMER_NO_BPB = (
    '{"d":"CONTEXT_x005B_OnCycleTimer_x005D_BDONTWAIT_x005B_true_x005D_'
    'ARG_x005B_USER:;STOERCSS:Stoertaste_0_Static;_x005D_'
    'SERVICECOUNTER_x005B_2:789_x005D_"}'
)


@resp_mock.activate
class TestVisuRAMClientConnect:

    def _register_mocks(self, binitcall_resp=_BINITCALL_RESP_WITH_BPB):
        """Registriert die Standard-Mock-Responses für einen kompletten Session-Aufbau."""
        # Schritt 1: GET ohne WCFID
        resp_mock.add(resp_mock.GET, f"{BASE_URL}/VisuRAM.aspx",
                      body=_VISURAMASPX_HTML, status=200,
                      content_type="text/html; charset=utf-8")
        # Schritt 2: GET mit WCFID=1234
        resp_mock.add(resp_mock.GET, f"{BASE_URL}/VisuRAM.aspx",
                      body=_VISURAMASPX_HTML, status=200,
                      content_type="text/html; charset=utf-8")
        # OnGetRechte
        resp_mock.add(resp_mock.POST, f"{BASE_URL}/RAMService.asmx/GlobalService",
                      body=_ONGETRECHTE_RESP, status=200,
                      content_type="application/json; charset=utf-8")
        # BINITCALL
        resp_mock.add(resp_mock.POST, f"{BASE_URL}/RAMService.asmx/GlobalService",
                      body=binitcall_resp, status=200,
                      content_type="application/json; charset=utf-8")
        # GlobalCallback (binitcall=True)
        resp_mock.add(resp_mock.POST, f"{BASE_URL}/VisuRAM.aspx",
                      body=_GLOBAL_CALLBACK_RESP, status=200,
                      content_type="text/html; charset=utf-8")

    def test_connect_setzt_wcfid(self):
        self._register_mocks()
        client = VisuRAMClient()
        client.connect()
        assert client.wcfid == 1234

    def test_connect_liefert_initiale_sensoren(self):
        self._register_mocks()
        client = VisuRAMClient()
        client.connect()
        assert len(client._initial_sensors) == 2
        assert "Feld28_Feld" in client._initial_sensors
        assert client._initial_sensors["Feld28_Feld"]["value"] == "28,4"

    def test_connect_setzt_trigger_counter(self):
        self._register_mocks()
        client = VisuRAMClient()
        client.connect()
        assert client._trigger_counter == 3

    def test_connect_ohne_bpb_keine_initialen_sensoren(self):
        binitcall_ohne_bpb = (
            '{"d":"CONTEXT_x005B_OnCycleTimer_x005D_BDONTWAIT_x005B_true_x005D_'
            'ARG_x005B_USER:;CCZEIT: 02.06.26 13:00;_x005D_"}'
        )
        self._register_mocks(binitcall_resp=binitcall_ohne_bpb)
        client = VisuRAMClient()
        client.connect()
        assert client._initial_sensors == {}

    def test_poll_ohne_bpb_gibt_leeres_dict(self):
        self._register_mocks()
        client = VisuRAMClient()
        client.connect()
        # Poll ohne BPB
        resp_mock.add(resp_mock.POST, f"{BASE_URL}/RAMService.asmx/GlobalService",
                      body=_CYCLETIMER_NO_BPB, status=200,
                      content_type="application/json; charset=utf-8")
        result = client.poll()
        assert result == {}

    def test_poll_mit_bpb_ruft_global_callback_auf(self):
        self._register_mocks()
        client = VisuRAMClient()
        client.connect()
        # Poll mit BPB:true
        cycletimer_with_bpb = (
            '{"d":"CONTEXT_x005B_OnCycleTimer_x005D_BDONTWAIT_x005B_true_x005D_'
            'ARG_x005B_BPB:true;USER:;_x005D_SERVICECOUNTER_x005B_3:111_x005D_"}'
        )
        resp_mock.add(resp_mock.POST, f"{BASE_URL}/RAMService.asmx/GlobalService",
                      body=cycletimer_with_bpb, status=200,
                      content_type="application/json; charset=utf-8")
        resp_mock.add(resp_mock.POST, f"{BASE_URL}/VisuRAM.aspx",
                      body=_GLOBAL_CALLBACK_RESP, status=200,
                      content_type="text/html; charset=utf-8")
        result = client.poll()
        assert "Feld28_Feld" in result
        assert result["Feld33_Feld"]["unit"] == "m/s"


# ─────────────────────────────────────────────────────────────────────────────
# build_set_value_arg / set_value
# ─────────────────────────────────────────────────────────────────────────────

from scripts.visuram_client import build_set_value_arg

class TestBuildSetValueArg:
    """Schreibbefehl-Builder (ChangeCCValue → OnChangeCCValue)."""

    def test_context_ist_on_change_cc_value(self):
        arg = build_set_value_arg("Feld79", "0191112101", "1")
        decoded = decode_xml_names(arg)
        assert "CONTEXT[OnChangeCCValue]" in decoded

    def test_adr_enthalten(self):
        arg = build_set_value_arg("Feld79", "0191112101", "1")
        decoded = decode_xml_names(arg)
        assert "ADR{0191112101}" in decoded

    def test_w1_enthalten(self):
        arg = build_set_value_arg("Feld79", "0191112101", "1")
        decoded = decode_xml_names(arg)
        assert "W1{1}" in decoded

    def test_w1_aus(self):
        arg = build_set_value_arg("Feld79", "0191112101", "0")
        decoded = decode_xml_names(arg)
        assert "W1{0}" in decoded
        assert "W1{1}" not in decoded

    def test_feld_id_enthalten(self):
        arg = build_set_value_arg("Feld79", "0191112101", "1")
        decoded = decode_xml_names(arg)
        assert "ID{Feld79_Feld}" in decoded
        assert "ADVISEID{Feld79}" in decoded

    def test_dontcheckrech_true(self):
        """Permission-Check wird umgangen (wir haben URECHT:2000)."""
        arg = build_set_value_arg("Feld79", "0191112101", "1")
        decoded = decode_xml_names(arg)
        assert "DONTCHECKRECH{true}" in decoded

    def test_function_name_in_arg(self):
        arg = build_set_value_arg("Feld79", "0191112101", "1")
        decoded = decode_xml_names(arg)
        assert "FUNCTION{ChangeCCValue}" in decoded

    def test_bdontwait_true(self):
        arg = build_set_value_arg("Feld79", "0191112101", "1")
        decoded = decode_xml_names(arg)
        assert "BDONTWAIT[true]" in decoded

    def test_w2_leer_standardmaessig(self):
        arg = build_set_value_arg("Feld79", "0191112101", "1")
        decoded = decode_xml_names(arg)
        assert "W2{}" in decoded

    def test_w2_optional_setzbar(self):
        arg = build_set_value_arg("Feld79", "0191112101", "5:00", "0")
        decoded = decode_xml_names(arg)
        assert "W1{5:00}" in decoded
        assert "W2{0}" in decoded


@resp_mock.activate
class TestVisuRAMClientSetValue:

    def _register_connect_mocks(self):
        resp_mock.add(resp_mock.GET, f"{BASE_URL}/VisuRAM.aspx",
                      body=_VISURAMASPX_HTML, status=200, content_type="text/html; charset=utf-8")
        resp_mock.add(resp_mock.GET, f"{BASE_URL}/VisuRAM.aspx",
                      body=_VISURAMASPX_HTML, status=200, content_type="text/html; charset=utf-8")
        resp_mock.add(resp_mock.POST, f"{BASE_URL}/RAMService.asmx/GlobalService",
                      body=_ONGETRECHTE_RESP, status=200, content_type="application/json; charset=utf-8")
        resp_mock.add(resp_mock.POST, f"{BASE_URL}/RAMService.asmx/GlobalService",
                      body=_BINITCALL_RESP_WITH_BPB, status=200, content_type="application/json; charset=utf-8")
        resp_mock.add(resp_mock.POST, f"{BASE_URL}/VisuRAM.aspx",
                      body=_GLOBAL_CALLBACK_RESP, status=200, content_type="text/html; charset=utf-8")

    def test_set_value_sendet_on_change_cc_value(self):
        self._register_connect_mocks()
        set_resp = (
            '{"d":"CONTEXT_x005B_OnChangeCCValue_x005D_BDONTWAIT_x005B_true_x005D_'
            'ARG_x005B_MLDG_x007B__x007D_ROWINFO_x007B_1_x007D_EINHEIT_x007B_false_x007D_'
            'ID_x007B_Feld79_Feld_x007D_W12_x007B_1_x007D__x005D_"}'
        )
        resp_mock.add(resp_mock.POST, f"{BASE_URL}/RAMService.asmx/GlobalService",
                      body=set_resp, status=200, content_type="application/json; charset=utf-8")
        client = VisuRAMClient()
        client.connect()
        result = client.set_value("Feld79", "0191112101", "1")
        assert "OnChangeCCValue" in result

    def test_set_value_wirft_fehler_ohne_verbindung(self):
        client = VisuRAMClient()
        with pytest.raises(RuntimeError, match="connect"):
            client.set_value("Feld79", "0191112101", "1")


class TestHandstartValues:
    """Verifiziert CC600 Handstart-Werte (live getestet 02.06.2026)."""

    def test_handstart_manuell_ein_ist_2(self):
        """w2='2' = Manuell Ein – öffnet Ventil unabhängig von CC600-Logik."""
        arg = build_set_value_arg("Feld92", "0101500311", w1="12:00", w2="2")
        decoded = decode_xml_names(arg)
        assert "W2{2}" in decoded
        assert "W1{12:00}" in decoded

    def test_handstart_aus_ist_0(self):
        """w2='0' = Aus – Ventil schließen."""
        arg = build_set_value_arg("Feld92", "0101500311", w1="12:00", w2="0")
        decoded = decode_xml_names(arg)
        assert "W2{0}" in decoded

    def test_handstart_auto_ist_1(self):
        """w2='1' = Automatik – CC600-Steuerungslogik greift."""
        arg = build_set_value_arg("Feld92", "0101500311", w1="12:00", w2="1")
        decoded = decode_xml_names(arg)
        assert "W2{1}" in decoded
