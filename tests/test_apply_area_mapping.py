"""
Unit-Tests für scripts/apply_area_mapping.py

Testet Pure Functions und HTTP/WebSocket-abhängige Funktionen via Mocking.

Ausführen:
    pytest tests/test_apply_area_mapping.py -v
"""

import json
import sys
import os
from unittest.mock import patch, MagicMock, call

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from scripts.apply_area_mapping import (
    zone_from_cc600_adr,
    zone_from_entity_attrs,
    get_or_create_floor,
    get_or_create_area,
    get_or_create_label,
    assign_entity,
    load_area_name_to_id,
    load_floor_name_to_id,
    load_label_name_to_id,
    find_mapping_file,
    HAWebSocket,
)


# ─────────────────────────────────────────────────────────────────────────────
# zone_from_cc600_adr
# ─────────────────────────────────────────────────────────────────────────────

class TestZoneFromCc600Adr:
    """CC600-Adresse Format: 01ZZKKKKPP → Zone = ZZ (Stellen 2–3)."""

    def test_zone_01(self):
        assert zone_from_cc600_adr("0101500311") == "01"

    def test_zone_00(self):
        assert zone_from_cc600_adr("0100000001") == "00"

    def test_zone_50(self):
        assert zone_from_cc600_adr("0150502002") == "50"

    def test_zone_91(self):
        assert zone_from_cc600_adr("0191112102") == "91"

    def test_zone_02(self):
        assert zone_from_cc600_adr("0102100001") == "02"

    def test_kurze_adresse_gibt_leer(self):
        assert zone_from_cc600_adr("01") == ""
        assert zone_from_cc600_adr("") == ""

    def test_zone_04(self):
        assert zone_from_cc600_adr("0104112211") == "04"


# ─────────────────────────────────────────────────────────────────────────────
# zone_from_entity_attrs
# ─────────────────────────────────────────────────────────────────────────────

class TestZoneFromEntityAttrs:

    def test_zone_attribut_hat_vorrang(self):
        attrs = {"zone": "01", "cc600_adr": "0102000001"}
        assert zone_from_entity_attrs(attrs) == "01"

    def test_zone_attribut_wird_aufgefüllt(self):
        assert zone_from_entity_attrs({"zone": "1"}) == "01"

    def test_fallback_auf_cc600_adr(self):
        assert zone_from_entity_attrs({"cc600_adr": "0103500111"}) == "03"

    def test_leere_attrs_geben_leer(self):
        assert zone_from_entity_attrs({}) == ""

    def test_zone_50(self):
        assert zone_from_entity_attrs({"zone": "50"}) == "50"


# ─────────────────────────────────────────────────────────────────────────────
# Fixture: Mock WebSocket
# ─────────────────────────────────────────────────────────────────────────────

def make_ws_mock(command_results: dict | None = None) -> MagicMock:
    """Erstellt einen HAWebSocket-Mock. command_results: {cmd_type: return_value}"""
    ws = MagicMock(spec=HAWebSocket)
    if command_results:
        def side_effect(cmd_type, **kwargs):
            if cmd_type in command_results:
                return command_results[cmd_type]
            raise RuntimeError(f"Unbekannter WS-Befehl im Mock: {cmd_type}")
        ws.command.side_effect = side_effect
    return ws


# ─────────────────────────────────────────────────────────────────────────────
# get_or_create_floor
# ─────────────────────────────────────────────────────────────────────────────

class TestGetOrCreateFloor:

    def test_gibt_existierende_id_aus_cache(self):
        ws = make_ws_mock()
        cache = {"Gewächshaus": "fid_gw"}
        assert get_or_create_floor("Gewächshaus", ws, cache) == "fid_gw"
        ws.command.assert_not_called()

    def test_legt_neuen_floor_an(self):
        ws = make_ws_mock({"config/floor_registry/create": {"floor_id": "fid_new"}})
        cache = {}
        result = get_or_create_floor("Neues Stockwerk", ws, cache)
        assert result == "fid_new"
        assert cache["Neues Stockwerk"] == "fid_new"

    def test_leerer_name_gibt_none(self):
        ws = make_ws_mock()
        assert get_or_create_floor("", ws, {}) is None
        ws.command.assert_not_called()

    def test_ws_create_mit_korrektem_cmd(self):
        ws = make_ws_mock({"config/floor_registry/create": {"floor_id": "fid"}})
        get_or_create_floor("Test", ws, {})
        ws.command.assert_called_once_with("config/floor_registry/create", name="Test")


# ─────────────────────────────────────────────────────────────────────────────
# get_or_create_area
# ─────────────────────────────────────────────────────────────────────────────

class TestGetOrCreateArea:

    def test_gibt_existierende_id_aus_cache(self):
        ws = make_ws_mock()
        cache = {"Abteil 1": "area_01"}
        assert get_or_create_area("Abteil 1", None, ws, cache) == "area_01"
        ws.command.assert_not_called()

    def test_legt_neue_area_mit_floor_an(self):
        ws = make_ws_mock({"config/area_registry/create": {"area_id": "area_new"}})
        cache = {}
        result = get_or_create_area("Neue Area", "fid_01", ws, cache)
        assert result == "area_new"
        ws.command.assert_called_once_with(
            "config/area_registry/create", name="Neue Area", floor_id="fid_01"
        )

    def test_legt_area_ohne_floor_an(self):
        ws = make_ws_mock({"config/area_registry/create": {"area_id": "area_nof"}})
        cache = {}
        get_or_create_area("Ohne Floor", None, ws, cache)
        ws.command.assert_called_once_with("config/area_registry/create", name="Ohne Floor")

    def test_leerer_name_gibt_none(self):
        assert get_or_create_area("", None, make_ws_mock(), {}) is None


# ─────────────────────────────────────────────────────────────────────────────
# get_or_create_label
# ─────────────────────────────────────────────────────────────────────────────

class TestGetOrCreateLabel:

    def test_gibt_existierendes_label_aus_cache(self):
        ws = make_ws_mock()
        cache = {"Bewässerung": "lbl_bew"}
        assert get_or_create_label("Bewässerung", ws, cache) == "lbl_bew"
        ws.command.assert_not_called()

    def test_legt_neues_label_an(self):
        ws = make_ws_mock({"config/label_registry/create": {"label_id": "lbl_new"}})
        cache = {}
        result = get_or_create_label("Neues Label", ws, cache)
        assert result == "lbl_new"
        assert cache["Neues Label"] == "lbl_new"

    def test_leerer_name_gibt_none(self):
        assert get_or_create_label("", make_ws_mock(), {}) is None


# ─────────────────────────────────────────────────────────────────────────────
# assign_entity
# ─────────────────────────────────────────────────────────────────────────────

class TestAssignEntity:

    def _ws_with_current(self, area_id=None, labels=None):
        current = {"area_id": area_id, "labels": labels or []}
        ws = MagicMock(spec=HAWebSocket)
        ws.command.return_value = current
        return ws

    def test_setzt_area(self):
        ws = self._ws_with_current(area_id=None)
        result = assign_entity("sensor.x", "area_01", [], ws)
        assert result == "ok"
        update_call = ws.command.call_args_list[1]  # [0]=get, [1]=update
        assert update_call[1]["area_id"] == "area_01"

    def test_mergt_labels(self):
        ws = self._ws_with_current(labels=["existing_lbl"])
        assign_entity("sensor.x", None, ["new_lbl"], ws)
        update_call = ws.command.call_args_list[1]
        assert set(update_call[1]["labels"]) == {"existing_lbl", "new_lbl"}

    def test_kein_update_wenn_bereits_korrekt(self):
        ws = self._ws_with_current(area_id="area_01", labels=["lbl"])
        result = assign_entity("sensor.x", "area_01", ["lbl"], ws)
        assert result == "no_change"
        assert ws.command.call_count == 1  # Nur GET, kein UPDATE

    def test_skip_wenn_nichts_zuzuweisen(self):
        ws = MagicMock(spec=HAWebSocket)
        result = assign_entity("sensor.x", None, [], ws)
        assert result == "skip"
        ws.command.assert_not_called()

    def test_no_uid_bei_entity_not_found(self):
        ws = MagicMock(spec=HAWebSocket)
        ws.command.side_effect = RuntimeError("Entity not found")
        result = assign_entity("sensor.x", "area_01", [], ws)
        assert result == "no_uid"


# ─────────────────────────────────────────────────────────────────────────────
# load_*_name_to_id (Template-API)
# ─────────────────────────────────────────────────────────────────────────────

class TestLoadNameToId:

    def _patch_template(self, responses: list[str]):
        """Mock ha_template() der der Reihe nach verschiedene Antworten gibt."""
        return patch(
            "scripts.apply_area_mapping.ha_template",
            side_effect=responses,
        )

    def test_load_areas(self):
        with self._patch_template([
            '["abteil_1", "wetter"]',          # areas()
            '["Abteil 1", "Wetter"]',           # area_name mapping
        ]):
            result = load_area_name_to_id("http://ha", "tok")
        assert result == {"Abteil 1": "abteil_1", "Wetter": "wetter"}

    def test_load_floors(self):
        with self._patch_template([
            '["gewachshaus", "aussen"]',
            '["Gewächshaus", "Außen"]',
        ]):
            result = load_floor_name_to_id("http://ha", "tok")
        assert result == {"Gewächshaus": "gewachshaus", "Außen": "aussen"}

    def test_load_labels(self):
        with self._patch_template([
            '["bewasserung"]',
            '["Bewässerung"]',
        ]):
            result = load_label_name_to_id("http://ha", "tok")
        assert result == {"Bewässerung": "bewasserung"}

    def test_leere_registry(self):
        with self._patch_template(['[]', '[]']):
            assert load_area_name_to_id("http://ha", "tok") == {}


# ─────────────────────────────────────────────────────────────────────────────
# find_mapping_file
# ─────────────────────────────────────────────────────────────────────────────

class TestFindMappingFile:

    def test_findet_datei(self):
        path = find_mapping_file()
        assert os.path.exists(path)
        assert path.endswith("zone_area_mapping.json")

    def test_datei_ist_valides_json_mit_zones(self):
        path = find_mapping_file()
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        assert "zones" in data
        assert len(data["zones"]) == 8

    def test_alle_zonen_haben_ha_labels_feld(self):
        path = find_mapping_file()
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        for zone in data["zones"]:
            assert "ha_labels" in zone, f"Zone {zone['zone']} fehlt ha_labels"
            assert isinstance(zone["ha_labels"], list)

    def test_ha_reference_vorhanden(self):
        path = find_mapping_file()
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        assert "_ha_reference" in data
        ref = data["_ha_reference"]
        assert len(ref["areas"]) > 0
        assert len(ref["floors"]) > 0
