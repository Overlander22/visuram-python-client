"""
Unit-Tests für scripts/apply_area_mapping.py

Testet alle Pure Functions und Hilfsfunktionen ohne echte HA-Verbindung.
HTTP-abhängige Funktionen (ha_request, get_or_create_*) werden via
unittest.mock.patch isoliert.

Ausführen:
    pytest tests/test_apply_area_mapping.py -v
"""

import json
import sys
import os
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from scripts.apply_area_mapping import (
    zone_from_cc600_adr,
    zone_from_entity_attrs,
    get_or_create_floor,
    get_or_create_area,
    get_or_create_label,
    assign_entity,
    load_existing_floors,
    load_existing_areas,
    load_existing_labels,
    find_mapping_file,
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

    def test_kurze_adresse_gibt_leer_zurueck(self):
        assert zone_from_cc600_adr("01") == ""
        assert zone_from_cc600_adr("")   == ""

    def test_zone_04(self):
        assert zone_from_cc600_adr("0104112211") == "04"


# ─────────────────────────────────────────────────────────────────────────────
# zone_from_entity_attrs
# ─────────────────────────────────────────────────────────────────────────────

class TestZoneFromEntityAttrs:

    def test_zone_attribut_hat_vorrang(self):
        attrs = {"zone": "01", "cc600_adr": "0102000001"}
        assert zone_from_entity_attrs(attrs) == "01"

    def test_zone_attribut_wird_auf_2_stellen_aufgefüllt(self):
        attrs = {"zone": "1"}  # Zone ohne führende Null
        assert zone_from_entity_attrs(attrs) == "01"

    def test_fallback_auf_cc600_adr(self):
        attrs = {"cc600_adr": "0103500111"}
        assert zone_from_entity_attrs(attrs) == "03"

    def test_leere_attrs_geben_leer(self):
        assert zone_from_entity_attrs({}) == ""

    def test_zone_00_string(self):
        attrs = {"zone": "00"}
        assert zone_from_entity_attrs(attrs) == "00"


# ─────────────────────────────────────────────────────────────────────────────
# get_or_create_floor (Idempotenz)
# ─────────────────────────────────────────────────────────────────────────────

class TestGetOrCreateFloor:

    def test_gibt_existing_id_aus_cache(self):
        cache = {"Erdgeschoss": "floor_eg_01"}
        result = get_or_create_floor("Erdgeschoss", "http://ha", "token", cache)
        assert result == "floor_eg_01"

    def test_legt_neuen_floor_an(self):
        cache = {}
        with patch("scripts.apply_area_mapping.ha_request") as mock_req:
            mock_req.return_value = {"floor_id": "floor_new_01"}
            result = get_or_create_floor("Neues Stockwerk", "http://ha", "tok", cache)
        assert result == "floor_new_01"
        assert cache["Neues Stockwerk"] == "floor_new_01"

    def test_leerer_name_gibt_none(self):
        result = get_or_create_floor("", "http://ha", "tok", {})
        assert result is None

    def test_kein_ha_request_wenn_im_cache(self):
        cache = {"Floor": "fid"}
        with patch("scripts.apply_area_mapping.ha_request") as mock_req:
            get_or_create_floor("Floor", "http://ha", "tok", cache)
            mock_req.assert_not_called()

    def test_fehler_gibt_none(self):
        cache = {}
        with patch("scripts.apply_area_mapping.ha_request", side_effect=RuntimeError("HTTP 500")):
            result = get_or_create_floor("Broken", "http://ha", "tok", cache)
        assert result is None
        assert "Broken" not in cache


# ─────────────────────────────────────────────────────────────────────────────
# get_or_create_area (Idempotenz)
# ─────────────────────────────────────────────────────────────────────────────

class TestGetOrCreateArea:

    def test_gibt_existing_id_aus_cache(self):
        cache = {"Gewächshaus 01": "area_gw01"}
        result = get_or_create_area("Gewächshaus 01", None, "http://ha", "tok", cache)
        assert result == "area_gw01"

    def test_legt_neue_area_an(self):
        cache = {}
        with patch("scripts.apply_area_mapping.ha_request") as mock_req:
            mock_req.return_value = {"area_id": "area_new"}
            result = get_or_create_area("Neue Area", "floor_01", "http://ha", "tok", cache)
        assert result == "area_new"
        assert cache["Neue Area"] == "area_new"

    def test_floor_id_wird_im_body_uebergeben(self):
        cache = {}
        with patch("scripts.apply_area_mapping.ha_request") as mock_req:
            mock_req.return_value = {"area_id": "aid"}
            get_or_create_area("Test", "fid_01", "http://ha", "tok", cache)
        # ha_request(method, path, ha_url, token, body) → body ist Arg 4 (Index 4)
        _, _, _, _, body = mock_req.call_args[0]
        assert body["floor_id"] == "fid_01"

    def test_ohne_floor_kein_floor_id_im_body(self):
        cache = {}
        with patch("scripts.apply_area_mapping.ha_request") as mock_req:
            mock_req.return_value = {"area_id": "aid"}
            get_or_create_area("Test", None, "http://ha", "tok", cache)
        _, _, _, _, body = mock_req.call_args[0]
        assert "floor_id" not in body

    def test_leerer_name_gibt_none(self):
        result = get_or_create_area("", None, "http://ha", "tok", {})
        assert result is None


# ─────────────────────────────────────────────────────────────────────────────
# get_or_create_label (Idempotenz)
# ─────────────────────────────────────────────────────────────────────────────

class TestGetOrCreateLabel:

    def test_gibt_existing_id_aus_cache(self):
        cache = {"Sensoren": "label_sens"}
        result = get_or_create_label("Sensoren", "http://ha", "tok", cache)
        assert result == "label_sens"

    def test_legt_neues_label_an(self):
        cache = {}
        with patch("scripts.apply_area_mapping.ha_request") as mock_req:
            mock_req.return_value = {"label_id": "label_new"}
            result = get_or_create_label("Neues Label", "http://ha", "tok", cache)
        assert result == "label_new"
        assert cache["Neues Label"] == "label_new"

    def test_leerer_name_gibt_none(self):
        result = get_or_create_label("", "http://ha", "tok", {})
        assert result is None

    def test_fehler_gibt_none(self):
        cache = {}
        with patch("scripts.apply_area_mapping.ha_request", side_effect=RuntimeError("500")):
            result = get_or_create_label("Broken", "http://ha", "tok", cache)
        assert result is None


# ─────────────────────────────────────────────────────────────────────────────
# assign_entity
# ─────────────────────────────────────────────────────────────────────────────

class TestAssignEntity:

    def _make_mock(self, current_area=None, current_labels=None):
        """Erstellt ha_request-Mock der GET + PATCH simuliert."""
        current = {"area_id": current_area, "labels": current_labels or []}
        mock = MagicMock(return_value=current)
        return mock

    def test_setzt_area(self):
        with patch("scripts.apply_area_mapping.ha_request") as mock_req:
            mock_req.return_value = {"area_id": None, "labels": []}
            result = assign_entity("sensor.x", "area_01", [], "http://ha", "tok")
        assert result == "ok"
        # PATCH: ha_request(method, path, ha_url, token, body) → body ist Arg 4 (Index 4)
        patch_call = [c for c in mock_req.call_args_list if c[0][0] == "PATCH"]
        assert patch_call
        assert patch_call[0][0][4]["area_id"] == "area_01"

    def test_mergt_labels(self):
        with patch("scripts.apply_area_mapping.ha_request") as mock_req:
            mock_req.return_value = {"area_id": None, "labels": ["label_existing"]}
            assign_entity("sensor.x", None, ["label_new"], "http://ha", "tok")
        patch_call = [c for c in mock_req.call_args_list if c[0][0] == "PATCH"]
        labels = set(patch_call[0][0][4]["labels"])
        assert "label_existing" in labels
        assert "label_new" in labels

    def test_kein_patch_wenn_bereits_korrekt(self):
        with patch("scripts.apply_area_mapping.ha_request") as mock_req:
            mock_req.return_value = {"area_id": "area_01", "labels": ["lbl"]}
            result = assign_entity("sensor.x", "area_01", ["lbl"], "http://ha", "tok")
        assert result == "ok"
        patch_calls = [c for c in mock_req.call_args_list if c[0][0] == "PATCH"]
        assert len(patch_calls) == 0

    def test_no_uid_bei_404(self):
        with patch("scripts.apply_area_mapping.ha_request",
                   side_effect=RuntimeError("HTTP 404")):
            result = assign_entity("sensor.x", "area_01", [], "http://ha", "tok")
        assert result == "no_uid"

    def test_skip_wenn_keine_area_und_keine_labels(self):
        with patch("scripts.apply_area_mapping.ha_request") as mock_req:
            result = assign_entity("sensor.x", None, [], "http://ha", "tok")
        assert result == "skip"
        mock_req.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# load_existing_* (lädt von HA)
# ─────────────────────────────────────────────────────────────────────────────

class TestLoadExisting:

    def test_load_floors(self):
        with patch("scripts.apply_area_mapping.ha_request") as mock_req:
            mock_req.return_value = [
                {"floor_id": "fid_01", "name": "EG"},
                {"floor_id": "fid_02", "name": "OG"},
            ]
            result = load_existing_floors("http://ha", "tok")
        assert result == {"EG": "fid_01", "OG": "fid_02"}

    def test_load_areas(self):
        with patch("scripts.apply_area_mapping.ha_request") as mock_req:
            mock_req.return_value = [{"area_id": "aid_01", "name": "GW 1"}]
            result = load_existing_areas("http://ha", "tok")
        assert result == {"GW 1": "aid_01"}

    def test_load_labels(self):
        with patch("scripts.apply_area_mapping.ha_request") as mock_req:
            mock_req.return_value = [{"label_id": "lid_01", "name": "Sensor"}]
            result = load_existing_labels("http://ha", "tok")
        assert result == {"Sensor": "lid_01"}

    def test_fehler_gibt_leeres_dict(self):
        with patch("scripts.apply_area_mapping.ha_request",
                   side_effect=RuntimeError("Netzwerkfehler")):
            assert load_existing_floors("http://ha", "tok") == {}
            assert load_existing_areas("http://ha", "tok") == {}
            assert load_existing_labels("http://ha", "tok") == {}


# ─────────────────────────────────────────────────────────────────────────────
# find_mapping_file
# ─────────────────────────────────────────────────────────────────────────────

class TestFindMappingFile:

    def test_findet_datei_im_data_ordner(self):
        """Die echte zone_area_mapping.json muss im Repo existieren."""
        path = find_mapping_file()
        assert os.path.exists(path)
        assert path.endswith("zone_area_mapping.json")

    def test_datei_ist_valides_json(self):
        path = find_mapping_file()
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        assert "zones" in data
        assert isinstance(data["zones"], list)
        assert len(data["zones"]) == 8  # Zonen 00, 01, 02, 03, 04, 05, 50, 91

    def test_alle_zonen_haben_ha_labels_feld(self):
        path = find_mapping_file()
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        for zone in data["zones"]:
            assert "ha_labels" in zone, f"Zone {zone['zone']} fehlt ha_labels"
            assert isinstance(zone["ha_labels"], list)
