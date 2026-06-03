"""
AreaMappingApp – AppDaemon-App für automatisches HA Floor/Area/Label-Mapping

Läuft auf dem HA-Server als AppDaemon-App. Liest zone_area_mapping.json
aus dem gleichen Verzeichnis und weist alle nersingen-Entities den konfigurierten
Floors, Areas und Labels zu.

Wird automatisch beim AppDaemon-Start ausgeführt (nach startup_delay Sekunden).
Kann auch manuell via HA-Service ausgelöst werden: visuram/apply_area_mapping

Voraussetzung: websocket-client in AppDaemon installieren.
  → HA → Add-ons → AppDaemon → Konfiguration → System-Pakete:
    system_packages:
      - build-base   # (falls kompilierung nötig)
    python_packages:
      - websocket-client

apps.yaml Eintrag (in visuRAM/apps.yaml):
  area_mapping:
    module: area_mapping_app
    class: AreaMappingApp
    startup_delay: 30        # Sekunden nach AppDaemon-Start (wartet auf MQTT-Entities)
    # ha_url und ha_token werden automatisch aus AppDaemon-Konfig gelesen;
    # nur überschreiben wenn nötig:
    # ha_url: "http://192.168.178.102:8123"
    # ha_token: "eyJ..."
"""

import json
import os
import sys
import traceback

import appdaemon.plugins.hass.hassapi as hass

# apply_area_mapping.py liegt im gleichen Verzeichnis (AppDaemon apps/visuRAM/)
sys.path.insert(0, os.path.dirname(__file__))

from apply_area_mapping import (   # type: ignore
    HAWebSocket,
    load_area_name_to_id,
    load_floor_name_to_id,
    load_label_name_to_id,
    get_or_create_floor,
    get_or_create_area,
    get_or_create_label,
    assign_entity,
    zone_from_entity_attrs,
    ha_rest,
)


class AreaMappingApp(hass.Hass):
    """Weist nersingen-Entities automatisch HA-Floors, -Areas und -Labels zu."""

    # ── Initialisierung ──────────────────────────────────────────────────
    def initialize(self) -> None:
        delay = int(self.args.get("startup_delay", 30))
        self.log(f"AreaMappingApp startet – Mapping läuft in {delay}s")

        # Einmalig nach startup_delay ausführen
        self.run_in(self._apply_mapping, delay)

        # Service zum manuellen Auslösen aus HA (z.B. nach Mapping-Änderung)
        self.register_service("visuram/apply_area_mapping", self._apply_mapping)
        self.log("Service 'visuram/apply_area_mapping' registriert")

    # ── Haupt-Logik ──────────────────────────────────────────────────────
    def _apply_mapping(self, kwargs) -> None:
        """Liest zone_area_mapping.json und weist alle Entities zu."""
        try:
            ha_url, ha_token = self._get_ha_credentials()
            if not ha_url or not ha_token:
                self.log("HA URL oder Token fehlt – Mapping übersprungen", level="ERROR")
                return

            mapping_path = self._find_mapping_file()
            if not mapping_path:
                self.log("zone_area_mapping.json nicht gefunden", level="ERROR")
                return

            with open(mapping_path, encoding="utf-8") as f:
                mapping = json.load(f)

            zones_config = {z["zone"]: z for z in mapping["zones"]}
            configured   = {z: c for z, c in zones_config.items()
                            if c.get("ha_area") or c.get("ha_floor") or c.get("ha_labels")}

            if not configured:
                self.log("Keine Zonen in zone_area_mapping.json konfiguriert", level="WARNING")
                return

            self.log(f"Starte Mapping für Zonen: {sorted(configured)}")

            # ── Schritt 1: Vorhandenes aus HA laden ──────────────────────
            floor_cache = load_floor_name_to_id(ha_url, ha_token)
            area_cache  = load_area_name_to_id(ha_url, ha_token)
            label_cache = load_label_name_to_id(ha_url, ha_token)
            self.log(f"HA: {len(floor_cache)} Floors, {len(area_cache)} Areas, {len(label_cache)} Labels")

            # ── Schritt 2: WebSocket für Schreiboperationen ───────────────
            ws = HAWebSocket(ha_url, ha_token)

            # ── Schritt 3: Zonen → IDs auflösen (ggf. anlegen) ───────────
            zone_to_area:   dict[str, str | None] = {}
            zone_to_labels: dict[str, list[str]]  = {}

            for zone, cfg in zones_config.items():
                floor_name  = cfg.get("ha_floor", "").strip()
                area_name   = cfg.get("ha_area",  "").strip()
                label_names = [l.strip() for l in cfg.get("ha_labels", []) if l.strip()]

                if not area_name and not label_names:
                    zone_to_area[zone]   = None
                    zone_to_labels[zone] = []
                    continue

                floor_id  = get_or_create_floor(floor_name, ws, floor_cache) if floor_name else None
                area_id   = get_or_create_area(area_name, floor_id, ws, area_cache) if area_name else None
                label_ids = [
                    lid for name in label_names
                    if (lid := get_or_create_label(name, ws, label_cache)) is not None
                ]
                zone_to_area[zone]   = area_id
                zone_to_labels[zone] = label_ids

            # ── Schritt 4: CC600-Entities laden ──────────────────────────────
            all_states = ha_rest("GET", "/api/states", ha_url, ha_token)
            cc600_ents = [s for s in all_states if s["entity_id"].startswith("sensor.cc600_")]
            self.log(f"{len(cc600_ents)} CC600-Entities gefunden")

            # ── Schritt 5: Zuweisungen durchführen ────────────────────────
            stats: dict[str, int] = {"ok": 0, "no_change": 0, "no_uid": 0, "no_zone": 0, "skip": 0}

            for state in cc600_ents:
                eid   = state["entity_id"]
                attrs = state.get("attributes", {})
                zone  = zone_from_entity_attrs(attrs)

                if not zone:
                    stats["no_zone"] += 1
                    continue

                area_id   = zone_to_area.get(zone)
                label_ids = zone_to_labels.get(zone, [])
                result    = assign_entity(eid, area_id, label_ids, ws)
                stats[result] = stats.get(result, 0) + 1

            ws.close()

            self.log(
                f"Mapping abgeschlossen – "
                f"OK: {stats['ok']}, "
                f"Unverändert: {stats.get('no_change', 0)}, "
                f"Kein unique_id: {stats.get('no_uid', 0)}, "
                f"Keine Zone: {stats['no_zone']}"
            )

            if stats.get("no_uid", 0) > 0:
                self.log(
                    f"{stats['no_uid']} Entities ohne unique_id – "
                    "MQTT Integration aktiv?",
                    level="WARNING",
                )

        except Exception as exc:
            self.log(
                f"Fehler beim Area-Mapping: {exc}\n{traceback.format_exc()}",
                level="ERROR",
            )

    # ── Hilfsmethoden ────────────────────────────────────────────────────
    def _get_ha_credentials(self) -> tuple[str, str]:
        """
        Ermittelt HA-URL und Token.

        Reihenfolge:
          1. apps.yaml-Args (expliziter Override)
          2. AppDaemon-Plugin-Config (verschiedene Pfade je nach AD-Version)
          3. SUPERVISOR_TOKEN Umgebungsvariable (Standard für alle HA-Add-ons)
        """
        import os

        ha_url   = self.args.get("ha_url",   "")
        ha_token = self.args.get("ha_token", "")

        # Versuch 2: AppDaemon-interne Plugin-Config (Pfad variiert je nach AD-Version)
        if not ha_url or not ha_token:
            for get_cfg in [
                lambda: self.AD.plugins.plugins["HASS"].config,
                lambda: self.AD.plugins["HASS"].config,
                lambda: self.AD.config["plugins"]["HASS"],
            ]:
                try:
                    cfg      = get_cfg()
                    ha_url   = ha_url   or cfg.get("ha_url", "")
                    ha_token = ha_token or cfg.get("ha_key", "")
                    if ha_url and ha_token:
                        break
                except Exception:
                    continue

        # Versuch 3: Supervisor-Token (in jedem HA-Add-on als Umgebungsvariable verfügbar)
        if not ha_token:
            supervisor_token = os.environ.get("SUPERVISOR_TOKEN", "")
            if supervisor_token:
                ha_token = supervisor_token
                ha_url   = ha_url or "http://supervisor/core"
                self.log("Nutze SUPERVISOR_TOKEN für HA-Zugriff")

        if not ha_url or not ha_token:
            self.log(
                "Kein HA-Token gefunden. Bitte ha_url + ha_token in apps.yaml eintragen.",
                level="ERROR"
            )

        return ha_url.rstrip("/"), ha_token

    def _find_mapping_file(self) -> str | None:
        """Sucht zone_area_mapping.json im gleichen Verzeichnis wie diese Datei."""
        candidates = [
            os.path.join(os.path.dirname(__file__), "zone_area_mapping.json"),
        ]
        for c in candidates:
            if os.path.exists(c):
                return c
        return None
