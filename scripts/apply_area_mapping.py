"""
apply_area_mapping.py – Weist HA-Entities automatisch Floors/Areas zu.

Voraussetzung: Mosquitto MQTT Broker Add-on in HA installiert und
               MQTT-Integration eingerichtet (nur dann haben Entities
               eine unique_id und können der Entity-Registry zugewiesen werden).

Ablauf:
  1. Liest data/zone_area_mapping.json (bitte ha_floor + ha_area ausfüllen)
  2. Legt fehlende Floors und Areas in HA an
  3. Liest alle HA-Entities mit "nersingen"-Prefix
  4. Ermittelt die Zone aus dem cc600_adr-Attribut
  5. Weist jeder Entity die passende Area zu (via entity registry)

Aufruf:
  python3 scripts/apply_area_mapping.py --ha-url http://192.168.178.102:8123 --token <TOKEN>

  oder mit config_local.py:
  python3 scripts/apply_area_mapping.py
"""

import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error


# ─────────────────────────────────────────────────────────────────────────────
# HA API Helpers
# ─────────────────────────────────────────────────────────────────────────────

def ha_request(method: str, path: str, ha_url: str, token: str,
               body: dict | None = None) -> dict | list:
    """Führt einen HA REST API Call durch und gibt die JSON-Antwort zurück."""
    url = f"{ha_url.rstrip('/')}{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body_text = e.read().decode(errors="replace")
        raise RuntimeError(f"HA API {method} {path} → HTTP {e.code}: {body_text}") from e


# ─────────────────────────────────────────────────────────────────────────────
# Floor / Area Registry
# ─────────────────────────────────────────────────────────────────────────────

def get_or_create_floor(name: str, ha_url: str, token: str,
                         floor_cache: dict) -> str | None:
    """Gibt floor_id zurück. Legt Floor an falls nicht vorhanden."""
    if not name:
        return None
    if name in floor_cache:
        return floor_cache[name]
    try:
        resp = ha_request("POST", "/api/config/floor_registry", ha_url, token,
                          {"name": name})
        fid = resp.get("floor_id")
        floor_cache[name] = fid
        print(f"  Floor erstellt: '{name}' → {fid}")
        return fid
    except RuntimeError as e:
        print(f"  WARNUNG: Floor '{name}' konnte nicht erstellt werden: {e}")
        return None


def get_or_create_area(name: str, floor_id: str | None,
                        ha_url: str, token: str, area_cache: dict) -> str | None:
    """Gibt area_id zurück. Legt Area an falls nicht vorhanden."""
    if not name:
        return None
    if name in area_cache:
        return area_cache[name]
    body: dict = {"name": name}
    if floor_id:
        body["floor_id"] = floor_id
    try:
        resp = ha_request("POST", "/api/config/area_registry", ha_url, token, body)
        aid = resp.get("area_id")
        area_cache[name] = aid
        print(f"  Area erstellt: '{name}' → {aid}")
        return aid
    except RuntimeError as e:
        print(f"  WARNUNG: Area '{name}' konnte nicht erstellt werden: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Entity Registry
# ─────────────────────────────────────────────────────────────────────────────

def assign_entity_area(entity_id: str, area_id: str,
                        ha_url: str, token: str) -> bool:
    """Weist einer Entity eine Area zu. Gibt True bei Erfolg zurück."""
    try:
        ha_request("PATCH",
                   f"/api/config/entity_registry/{entity_id}",
                   ha_url, token,
                   {"area_id": area_id})
        return True
    except RuntimeError as e:
        if "404" in str(e):
            # Entity nicht in Registry → hat keine unique_id → MQTT fehlt
            return False
        print(f"  WARNUNG: Entity {entity_id}: {e}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Hilfsfunktionen
# ─────────────────────────────────────────────────────────────────────────────

def zone_from_cc600_adr(cc600_adr: str) -> str:
    """Extrahiert die Zone aus der CC600-Adresse (erste 2 Ziffern nach '01')."""
    # Format: 01ZZKKKKPP → Zone = ZZ (Stellen 2-3, 0-indexed)
    if len(cc600_adr) >= 4:
        return cc600_adr[2:4]
    return ""


def load_config() -> tuple[str, str]:
    """Lädt HA_URL und HA_TOKEN aus config_local.py (Repository-Root)."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(os.path.dirname(script_dir), "config_local.py")
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"config_local.py nicht gefunden: {config_path}")
    ns: dict = {}
    with open(config_path) as f:
        exec(f.read(), ns)
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
    parser = argparse.ArgumentParser(description="HA-Entities Floors/Areas zuweisen")
    parser.add_argument("--ha-url", default=None, help="HA Basis-URL")
    parser.add_argument("--token", default=None, help="HA Long-Lived Access Token")
    parser.add_argument("--dry-run", action="store_true",
                        help="Nur ausgeben was passieren würde, nichts schreiben")
    args = parser.parse_args()

    # Credentials laden
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

    # Mapping-Datei laden
    mapping_path = find_mapping_file()
    with open(mapping_path, encoding="utf-8") as f:
        mapping = json.load(f)

    zones_config = {z["zone"]: z for z in mapping["zones"]}
    configured = [(z, c) for z, c in zones_config.items()
                  if c.get("ha_area") or c.get("ha_floor")]

    if not configured:
        print(
            "⚠️  Keine Zonen konfiguriert!\n"
            f"Bitte {mapping_path} öffnen und ha_floor/ha_area für jede Zone ausfüllen."
        )
        sys.exit(0)

    print(f"Konfigurierte Zonen: {[z for z, _ in configured]}")
    print(f"HA-URL: {ha_url}")
    if args.dry_run:
        print("DRY-RUN Modus – keine Änderungen werden vorgenommen\n")

    # ── Schritt 1: Floors und Areas anlegen ──────────────────────────────────
    print("\n── Floors und Areas anlegen ──────────────────────────────────────")
    floor_cache: dict[str, str] = {}
    area_cache:  dict[str, str] = {}

    # Bestehende Areas aus HA laden um Duplikate zu vermeiden
    try:
        existing_areas = ha_request("GET", "/api/config/area_registry", ha_url, token)
        for a in existing_areas:
            area_cache[a["name"]] = a["area_id"]
        print(f"  {len(area_cache)} bestehende Areas gefunden")
    except RuntimeError as e:
        print(f"  WARNUNG: Areas konnten nicht geladen werden: {e}")

    try:
        existing_floors = ha_request("GET", "/api/config/floor_registry", ha_url, token)
        for fl in existing_floors:
            floor_cache[fl["name"]] = fl["floor_id"]
        print(f"  {len(floor_cache)} bestehende Floors gefunden")
    except RuntimeError as e:
        print(f"  WARNUNG: Floors konnten nicht geladen werden: {e}")

    zone_to_area: dict[str, str] = {}
    for zone, cfg in zones_config.items():
        floor_name = cfg.get("ha_floor", "").strip()
        area_name  = cfg.get("ha_area", "").strip()
        if not area_name:
            continue
        if not args.dry_run:
            floor_id = get_or_create_floor(floor_name, ha_url, token, floor_cache) if floor_name else None
            area_id  = get_or_create_area(area_name, floor_id, ha_url, token, area_cache)
            if area_id:
                zone_to_area[zone] = area_id
        else:
            print(f"  [DRY-RUN] Zone {zone}: Floor='{floor_name}' Area='{area_name}'")

    # ── Schritt 2: Entities laden ─────────────────────────────────────────────
    print("\n── HA-Entities laden ─────────────────────────────────────────────")
    all_states = ha_request("GET", "/api/states", ha_url, token)
    nersingen = [s for s in all_states if "nersingen" in s["entity_id"]]
    print(f"  {len(nersingen)} nersingen-Entities gefunden")

    # ── Schritt 3: Entity-Registry Assignment ─────────────────────────────────
    print("\n── Areas zuweisen ────────────────────────────────────────────────")
    stats = {"ok": 0, "no_uid": 0, "no_zone": 0, "skipped": 0}
    no_uid_count = 0

    for state in nersingen:
        eid = state["entity_id"]
        attrs = state.get("attributes", {})
        cc600_adr = attrs.get("cc600_adr", "")

        if not cc600_adr:
            stats["no_zone"] += 1
            continue

        zone = zone_from_cc600_adr(cc600_adr)
        area_id = zone_to_area.get(zone)
        if not area_id:
            stats["skipped"] += 1
            continue

        if args.dry_run:
            zone_name = zones_config.get(zone, {}).get("ha_area", "?")
            print(f"  [DRY-RUN] {eid} → Zone {zone} → {zone_name}")
            stats["ok"] += 1
            continue

        ok = assign_entity_area(eid, area_id, ha_url, token)
        if ok:
            stats["ok"] += 1
        else:
            stats["no_uid"] += 1
            no_uid_count += 1

    print(f"\n── Ergebnis ───────────────────────────────────────────────────────")
    print(f"  Zugewiesen:           {stats['ok']}")
    print(f"  Kein cc600_adr:       {stats['no_zone']}")
    print(f"  Zone nicht gemappt:   {stats['skipped']}")
    if not args.dry_run:
        print(f"  Keine unique_id:      {stats['no_uid']}")

    if no_uid_count > 0:
        print(
            f"\n⚠️  {no_uid_count} Entities haben keine unique_id (404 vom Entity-Registry).\n"
            "   Das bedeutet: MQTT Discovery ist noch nicht aktiv.\n"
            "   Schritte:\n"
            "   1. HA → Add-ons → Mosquitto broker installieren\n"
            "   2. HA → Integrationen → MQTT hinzufügen\n"
            "   3. AppDaemon MQTT-Modus aktivieren (visuRAM_app.py)\n"
            "   4. Dieses Script erneut ausführen"
        )


if __name__ == "__main__":
    main()
