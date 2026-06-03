"""
apply_area_mapping.py – Weist HA-Entities automatisch Floors, Areas und Labels zu.

Voraussetzung: Mosquitto MQTT Broker Add-on installiert + MQTT-Integration in HA
               konfiguriert, damit Entities eine unique_id haben und im Entity-Registry
               verwaltet werden können.

Ablauf:
  1. Liest data/zone_area_mapping.json  (bitte ha_floor, ha_area, ha_labels ausfüllen)
  2. Legt fehlende Floors, Areas und Labels in HA an  (Idempotent: vorhandene bleiben)
  3. Liest alle HA-Entities mit "nersingen"-Prefix
  4. Ermittelt die Zone aus dem Attribut "zone" (oder aus cc600_adr)
  5. Weist jeder Entity die passende Area + Labels zu

Aufruf:
  python3 scripts/apply_area_mapping.py
  python3 scripts/apply_area_mapping.py --dry-run    # nur ausgeben, nichts schreiben
  python3 scripts/apply_area_mapping.py --ha-url http://192.168.178.102:8123 --token <TOKEN>
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
import urllib.error
from typing import Any


# ─────────────────────────────────────────────────────────────────────────────
# HA REST API
# ─────────────────────────────────────────────────────────────────────────────

def ha_request(method: str, path: str, ha_url: str, token: str,
               body: dict | None = None) -> Any:
    """HTTP-Request gegen die HA REST API. Gibt geparste JSON-Antwort zurück."""
    url = f"{ha_url.rstrip('/')}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code} {method} {path}: {e.read().decode(errors='replace')}") from e


# ─────────────────────────────────────────────────────────────────────────────
# Registry-Helpers (alle idempotent: laden erst, legen nur an wenn fehlend)
# ─────────────────────────────────────────────────────────────────────────────

def load_existing_floors(ha_url: str, token: str) -> dict[str, str]:
    """Lädt alle vorhandenen Floors. Gibt {name → floor_id} zurück."""
    try:
        floors = ha_request("GET", "/api/config/floor_registry", ha_url, token)
        return {f["name"]: f["floor_id"] for f in floors}
    except RuntimeError as e:
        print(f"  WARNUNG: Floors konnten nicht geladen werden: {e}")
        return {}


def load_existing_areas(ha_url: str, token: str) -> dict[str, str]:
    """Lädt alle vorhandenen Areas. Gibt {name → area_id} zurück."""
    try:
        areas = ha_request("GET", "/api/config/area_registry", ha_url, token)
        return {a["name"]: a["area_id"] for a in areas}
    except RuntimeError as e:
        print(f"  WARNUNG: Areas konnten nicht geladen werden: {e}")
        return {}


def load_existing_labels(ha_url: str, token: str) -> dict[str, str]:
    """Lädt alle vorhandenen Labels. Gibt {name → label_id} zurück."""
    try:
        labels = ha_request("GET", "/api/config/label_registry", ha_url, token)
        return {l["name"]: l["label_id"] for l in labels}
    except RuntimeError as e:
        print(f"  WARNUNG: Labels konnten nicht geladen werden: {e}")
        return {}


def get_or_create_floor(name: str, ha_url: str, token: str,
                         cache: dict[str, str]) -> str | None:
    """Gibt floor_id zurück. Legt Floor an falls noch nicht vorhanden."""
    if not name:
        return None
    if name in cache:
        return cache[name]
    try:
        resp = ha_request("POST", "/api/config/floor_registry", ha_url, token, {"name": name})
        fid = resp["floor_id"]
        cache[name] = fid
        print(f"  [NEU] Floor: '{name}' → {fid}")
        return fid
    except RuntimeError as e:
        print(f"  WARNUNG: Floor '{name}' konnte nicht angelegt werden: {e}")
        return None


def get_or_create_area(name: str, floor_id: str | None,
                        ha_url: str, token: str, cache: dict[str, str]) -> str | None:
    """Gibt area_id zurück. Legt Area an falls noch nicht vorhanden."""
    if not name:
        return None
    if name in cache:
        return cache[name]
    body: dict = {"name": name}
    if floor_id:
        body["floor_id"] = floor_id
    try:
        resp = ha_request("POST", "/api/config/area_registry", ha_url, token, body)
        aid = resp["area_id"]
        cache[name] = aid
        print(f"  [NEU] Area: '{name}' (floor={floor_id or '–'}) → {aid}")
        return aid
    except RuntimeError as e:
        print(f"  WARNUNG: Area '{name}' konnte nicht angelegt werden: {e}")
        return None


def get_or_create_label(name: str, ha_url: str, token: str,
                         cache: dict[str, str]) -> str | None:
    """Gibt label_id zurück. Legt Label an falls noch nicht vorhanden."""
    if not name:
        return None
    if name in cache:
        return cache[name]
    try:
        resp = ha_request("POST", "/api/config/label_registry", ha_url, token, {"name": name})
        lid = resp["label_id"]
        cache[name] = lid
        print(f"  [NEU] Label: '{name}' → {lid}")
        return lid
    except RuntimeError as e:
        print(f"  WARNUNG: Label '{name}' konnte nicht angelegt werden: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Entity-Registry-Zuweisung
# ─────────────────────────────────────────────────────────────────────────────

def assign_entity(entity_id: str, area_id: str | None, label_ids: list[str],
                   ha_url: str, token: str) -> str:
    """
    Weist der Entity Area und/oder Labels zu.
    Labels werden gemergt (bestehende bleiben erhalten).

    Returns: "ok" | "no_uid" | "skip"
    """
    if not area_id and not label_ids:
        return "skip"

    # Aktuellen Registry-Eintrag lesen (prüft ob unique_id vorhanden)
    try:
        current = ha_request("GET", f"/api/config/entity_registry/{entity_id}",
                              ha_url, token)
    except RuntimeError as e:
        if "404" in str(e):
            return "no_uid"
        print(f"  WARNUNG: Registry-Lesen für {entity_id}: {e}")
        return "no_uid"

    patch: dict = {}

    # Area setzen (nur wenn nicht schon korrekt)
    if area_id and current.get("area_id") != area_id:
        patch["area_id"] = area_id

    # Labels mergen (neue hinzufügen, bestehende nicht entfernen)
    if label_ids:
        existing = set(current.get("labels", []))
        merged   = existing | set(label_ids)
        if merged != existing:
            patch["labels"] = sorted(merged)

    if not patch:
        return "ok"  # Bereits korrekt, nichts zu tun

    try:
        ha_request("PATCH", f"/api/config/entity_registry/{entity_id}",
                   ha_url, token, patch)
        return "ok"
    except RuntimeError as e:
        print(f"  WARNUNG: PATCH für {entity_id}: {e}")
        return "skip"


# ─────────────────────────────────────────────────────────────────────────────
# Hilfsfunktionen
# ─────────────────────────────────────────────────────────────────────────────

def zone_from_cc600_adr(cc600_adr: str) -> str:
    """
    Extrahiert die Zone aus der CC600-Adresse.

    Format: 01ZZKKKKPP  (10 Ziffern)
    Zone   = Stellen 2–3 (0-indiziert), z.B. "0101500311" → "01"
    """
    if len(cc600_adr) >= 4:
        return cc600_adr[2:4]
    return ""


def zone_from_entity_attrs(attrs: dict) -> str:
    """
    Liest Zone aus den Entity-Attributen.
    Bevorzugt 'zone'-Attribut, fällt zurück auf cc600_adr-Extraktion.
    """
    zone = attrs.get("zone", "")
    if zone:
        return str(zone).zfill(2)
    cc600_adr = attrs.get("cc600_adr", "")
    if cc600_adr:
        return zone_from_cc600_adr(str(cc600_adr))
    return ""


def load_config() -> tuple[str, str]:
    """Lädt HA_URL + HA_TOKEN aus config_local.py (Repository-Root)."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(os.path.dirname(script_dir), "config_local.py")
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"config_local.py nicht gefunden: {config_path}")
    ns: dict = {}
    with open(config_path) as f:
        exec(f.read(), ns)  # noqa: S102
    return ns.get("HA_URL", ""), ns.get("HA_TOKEN", "")


def find_mapping_file() -> str:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(os.path.dirname(script_dir), "data", "zone_area_mapping.json"),
        os.path.join(script_dir, "zone_area_mapping.json"),
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    raise FileNotFoundError("zone_area_mapping.json nicht gefunden")


# ─────────────────────────────────────────────────────────────────────────────
# Hauptprogramm
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="HA-Entities Floors/Areas/Labels zuweisen (idempotent)"
    )
    parser.add_argument("--ha-url",   default=None)
    parser.add_argument("--token",    default=None)
    parser.add_argument("--dry-run",  action="store_true",
                        help="Nur ausgeben, nichts in HA schreiben")
    args = parser.parse_args()

    # Credentials
    if args.ha_url and args.token:
        ha_url, token = args.ha_url, args.token
    else:
        try:
            ha_url, token = load_config()
        except FileNotFoundError as e:
            print(f"FEHLER: {e}\nBitte --ha-url und --token angeben.")
            sys.exit(1)

    if not ha_url or not token:
        print("FEHLER: HA_URL oder HA_TOKEN fehlt.")
        sys.exit(1)

    # Mapping laden
    mapping_path = find_mapping_file()
    with open(mapping_path, encoding="utf-8") as f:
        mapping = json.load(f)

    zones_config = {z["zone"]: z for z in mapping["zones"]}
    configured   = {z: c for z, c in zones_config.items()
                    if c.get("ha_area") or c.get("ha_floor") or c.get("ha_labels")}

    if not configured:
        print(
            "⚠️  Keine Zonen konfiguriert!\n"
            f"Bitte {mapping_path} öffnen und ha_floor/ha_area/ha_labels ausfüllen."
        )
        sys.exit(0)

    print(f"HA-URL: {ha_url}")
    print(f"Konfigurierte Zonen: {sorted(configured)}")
    if args.dry_run:
        print("DRY-RUN – keine Änderungen werden vorgenommen\n")

    # ── Schritt 1: Vorhandene Einträge laden ──────────────────────────────────
    print("\n── Bestehende Einträge in HA laden ───────────────────────────────")
    floor_cache = {} if args.dry_run else load_existing_floors(ha_url, token)
    area_cache  = {} if args.dry_run else load_existing_areas(ha_url, token)
    label_cache = {} if args.dry_run else load_existing_labels(ha_url, token)
    print(f"  Floors: {len(floor_cache)} | Areas: {len(area_cache)} | Labels: {len(label_cache)}")

    # ── Schritt 2: Floors, Areas, Labels anlegen ──────────────────────────────
    print("\n── Floors / Areas / Labels anlegen (nur fehlende) ────────────────")
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

        if args.dry_run:
            print(f"  Zone {zone}: Floor='{floor_name}' Area='{area_name}' Labels={label_names}")
            zone_to_area[zone]   = f"dry_run_{zone}"
            zone_to_labels[zone] = label_names
            continue

        floor_id = get_or_create_floor(floor_name, ha_url, token, floor_cache) if floor_name else None
        area_id  = get_or_create_area(area_name, floor_id, ha_url, token, area_cache) if area_name else None
        label_ids = [
            lid for name in label_names
            if (lid := get_or_create_label(name, ha_url, token, label_cache)) is not None
        ]
        zone_to_area[zone]   = area_id
        zone_to_labels[zone] = label_ids

    # ── Schritt 3: Entities laden ─────────────────────────────────────────────
    print("\n── HA-Entities laden ─────────────────────────────────────────────")
    all_states = ha_request("GET", "/api/states", ha_url, token)
    nersingen  = [s for s in all_states if "nersingen" in s["entity_id"]]
    print(f"  {len(nersingen)} nersingen-Entities gefunden")

    # ── Schritt 4: Zuweisen ───────────────────────────────────────────────────
    print("\n── Area / Labels zuweisen ────────────────────────────────────────")
    stats: dict[str, int] = {"ok": 0, "already_ok": 0, "no_uid": 0, "no_zone": 0, "skip": 0}

    for state in nersingen:
        eid   = state["entity_id"]
        attrs = state.get("attributes", {})
        zone  = zone_from_entity_attrs(attrs)

        if not zone:
            stats["no_zone"] += 1
            continue

        area_id   = zone_to_area.get(zone)
        label_ids = zone_to_labels.get(zone, [])

        if args.dry_run:
            if area_id or label_ids:
                cfg = zones_config.get(zone, {})
                print(f"  {eid} → Zone {zone} → Area='{cfg.get('ha_area','')}' Labels={cfg.get('ha_labels',[])}")
                stats["ok"] += 1
            else:
                stats["skip"] += 1
            continue

        result = assign_entity(eid, area_id, label_ids, ha_url, token)
        if result == "ok":
            stats["ok"] += 1
        elif result == "no_uid":
            stats["no_uid"] += 1
        elif result == "already_ok":
            stats["already_ok"] += 1
        else:
            stats["skip"] += 1

    # ── Ergebnis ──────────────────────────────────────────────────────────────
    print(f"\n── Ergebnis ───────────────────────────────────────────────────────")
    print(f"  Zugewiesen / aktualisiert: {stats['ok']}")
    print(f"  Bereits korrekt:           {stats.get('already_ok', 0)}")
    print(f"  Keine Zone im Attribut:    {stats['no_zone']}")
    print(f"  Zone nicht konfiguriert:   {stats['skip']}")
    if not args.dry_run:
        print(f"  Keine unique_id (MQTT?):   {stats['no_uid']}")

    if stats["no_uid"] > 0:
        print(
            f"\n⚠️  {stats['no_uid']} Entities haben keine unique_id.\n"
            "   → HA → Einstellungen → Geräte & Dienste → MQTT konfigurieren,\n"
            "     dann AppDaemon neu starten und dieses Script erneut ausführen."
        )


if __name__ == "__main__":
    main()
