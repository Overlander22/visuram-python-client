"""
apply_area_mapping.py – Weist HA-Entities automatisch Floors, Areas und Labels zu.

Voraussetzung:
  - Mosquitto MQTT Broker Add-on installiert + MQTT-Integration konfiguriert
  - pip install -r requirements.txt  (websocket-client)

Ablauf:
  1. Liest data/zone_area_mapping.json (ha_floor, ha_area, ha_labels pro Zone)
  2. Liest vorhandene Areas/Floors/Labels aus HA via Template-API
  3. Legt fehlende Floors, Areas, Labels via WebSocket an (idempotent)
  4. Liest alle HA-Entities mit "nersingen"-Prefix via REST
  5. Weist jeder Entity die passende Area + Labels via WebSocket zu

Aufruf:
  python3 scripts/apply_area_mapping.py
  python3 scripts/apply_area_mapping.py --dry-run    # Vorschau ohne Schreiben
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

import websocket  # pip install websocket-client


# ─────────────────────────────────────────────────────────────────────────────
# HA REST (nur für read-only Operationen: /api/states, /api/template)
# ─────────────────────────────────────────────────────────────────────────────

def ha_rest(method: str, path: str, ha_url: str, token: str,
            body: dict | None = None) -> Any:
    """REST-Request gegen die HA API."""
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


def ha_template(template_str: str, ha_url: str, token: str) -> str:
    """Rendert ein Jinja2-Template via POST /api/template. Gibt Rohtext zurück."""
    result = ha_rest("POST", "/api/template", ha_url, token, {"template": template_str})
    # HA gibt hier einen String zurück (nicht JSON-eingebettet)
    return result if isinstance(result, str) else json.dumps(result)


# ─────────────────────────────────────────────────────────────────────────────
# HA WebSocket (für Registry-Lesen + Schreiben)
# ─────────────────────────────────────────────────────────────────────────────

class HAWebSocket:
    """Einfacher synchroner HA WebSocket Client."""

    def __init__(self, ha_url: str, token: str):
        ws_url = ha_url.rstrip("/").replace("http://", "ws://").replace("https://", "wss://")
        ws_url += "/api/websocket"
        self._ws = websocket.create_connection(ws_url, timeout=15)
        self._msg_id = 0

        # Handshake: auth_required → auth → auth_ok
        auth_req = json.loads(self._ws.recv())
        if auth_req.get("type") != "auth_required":
            raise RuntimeError(f"Unerwartete WS-Antwort: {auth_req}")
        self._ws.send(json.dumps({"type": "auth", "access_token": token}))
        auth_resp = json.loads(self._ws.recv())
        if auth_resp.get("type") != "auth_ok":
            raise RuntimeError(f"WS-Auth fehlgeschlagen: {auth_resp}")

    def command(self, cmd_type: str, **kwargs) -> Any:
        """Sendet ein WS-Kommando und gibt das `result`-Feld zurück."""
        self._msg_id += 1
        msg = {"type": cmd_type, "id": self._msg_id, **kwargs}
        self._ws.send(json.dumps(msg))
        resp = json.loads(self._ws.recv())
        if not resp.get("success"):
            raise RuntimeError(f"WS {cmd_type} fehlgeschlagen: {resp.get('error')}")
        return resp.get("result")

    def close(self) -> None:
        try:
            self._ws.close()
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# Registry-Lesen (via Template-API)
# ─────────────────────────────────────────────────────────────────────────────

def load_area_name_to_id(ha_url: str, token: str) -> dict[str, str]:
    """Gibt {area_name: area_id} für alle Areas zurück."""
    ids   = json.loads(ha_template("{{ areas() | tojson }}", ha_url, token))
    names = json.loads(ha_template("{{ areas() | map('area_name') | list | tojson }}", ha_url, token))
    return {name: aid for name, aid in zip(names, ids) if name}


def load_floor_name_to_id(ha_url: str, token: str) -> dict[str, str]:
    """Gibt {floor_name: floor_id} für alle Floors zurück."""
    ids   = json.loads(ha_template("{{ floors() | tojson }}", ha_url, token))
    names = json.loads(ha_template("{{ floors() | map('floor_name') | list | tojson }}", ha_url, token))
    return {name: fid for name, fid in zip(names, ids) if name}


def load_label_name_to_id(ha_url: str, token: str) -> dict[str, str]:
    """Gibt {label_name: label_id} für alle Labels zurück."""
    ids   = json.loads(ha_template("{{ labels() | tojson }}", ha_url, token))
    names = json.loads(ha_template("{{ labels() | map('label_name') | list | tojson }}", ha_url, token))
    return {name: lid for name, lid in zip(names, ids) if name}


# ─────────────────────────────────────────────────────────────────────────────
# Registry-Schreiben (via WebSocket)
# ─────────────────────────────────────────────────────────────────────────────

def get_or_create_floor(name: str, ws: HAWebSocket,
                         cache: dict[str, str]) -> str | None:
    if not name:
        return None
    if name in cache:
        return cache[name]
    result = ws.command("config/floor_registry/create", name=name)
    fid = result["floor_id"]
    cache[name] = fid
    print(f"  [NEU] Floor: '{name}' → {fid}")
    return fid


def get_or_create_area(name: str, floor_id: str | None, ws: HAWebSocket,
                        cache: dict[str, str]) -> str | None:
    if not name:
        return None
    if name in cache:
        return cache[name]
    kwargs: dict = {"name": name}
    if floor_id:
        kwargs["floor_id"] = floor_id
    result = ws.command("config/area_registry/create", **kwargs)
    aid = result["area_id"]
    cache[name] = aid
    print(f"  [NEU] Area: '{name}' → {aid}")
    return aid


def get_or_create_label(name: str, ws: HAWebSocket,
                         cache: dict[str, str]) -> str | None:
    if not name:
        return None
    if name in cache:
        return cache[name]
    result = ws.command("config/label_registry/create", name=name)
    lid = result["label_id"]
    cache[name] = lid
    print(f"  [NEU] Label: '{name}' → {lid}")
    return lid


# ─────────────────────────────────────────────────────────────────────────────
# Entity-Zuweisung (via WebSocket)
# ─────────────────────────────────────────────────────────────────────────────

def assign_entity(entity_id: str, area_id: str | None, label_ids: list[str],
                   ws: HAWebSocket) -> str:
    """
    Weist Entity Area + Labels zu. Labels werden gemergt.
    Returns: "ok" | "no_uid" | "skip" | "no_change"
    """
    if not area_id and not label_ids:
        return "skip"

    # Aktuellen Registry-Eintrag via WS lesen
    try:
        current = ws.command("config/entity_registry/get", entity_id=entity_id)
    except RuntimeError as e:
        if "not found" in str(e).lower() or "unknown" in str(e).lower():
            return "no_uid"
        print(f"  WARNUNG: Registry-Lesen {entity_id}: {e}")
        return "no_uid"

    patch: dict = {}

    if area_id and current.get("area_id") != area_id:
        patch["area_id"] = area_id

    if label_ids:
        existing = set(current.get("labels", []))
        merged   = existing | set(label_ids)
        if merged != existing:
            patch["labels"] = sorted(merged)

    if not patch:
        return "no_change"

    try:
        ws.command("config/entity_registry/update", entity_id=entity_id, **patch)
        return "ok"
    except RuntimeError as e:
        print(f"  WARNUNG: Update {entity_id}: {e}")
        return "skip"


# ─────────────────────────────────────────────────────────────────────────────
# Hilfsfunktionen
# ─────────────────────────────────────────────────────────────────────────────

def zone_from_cc600_adr(cc600_adr: str) -> str:
    """Extrahiert Zone aus CC600-Adresse: 01ZZKKKKPP → ZZ."""
    if len(cc600_adr) >= 4:
        return cc600_adr[2:4]
    return ""


def zone_from_entity_attrs(attrs: dict) -> str:
    """Liest Zone aus Attributen. Bevorzugt 'zone', fällt zurück auf cc600_adr."""
    zone = attrs.get("zone", "")
    if zone:
        return str(zone).zfill(2)
    return zone_from_cc600_adr(str(attrs.get("cc600_adr", "")))


def load_config() -> tuple[str, str]:
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
    parser.add_argument("--ha-url",  default=None)
    parser.add_argument("--token",   default=None)
    parser.add_argument("--dry-run", action="store_true",
                        help="Nur ausgeben, nichts in HA schreiben")
    args = parser.parse_args()

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
        print(f"⚠️  Keine Zonen konfiguriert!\nBitte {mapping_path} ausfüllen.")
        sys.exit(0)

    print(f"HA-URL: {ha_url}")
    print(f"Konfigurierte Zonen: {sorted(configured)}")
    if args.dry_run:
        print("DRY-RUN – keine Änderungen werden vorgenommen\n")

    # ── Schritt 1: Vorhandene Registries aus HA lesen ─────────────────────────
    print("\n── Vorhandene Einträge aus HA laden ──────────────────────────────")
    floor_cache = load_floor_name_to_id(ha_url, token)
    area_cache  = load_area_name_to_id(ha_url, token)
    label_cache = load_label_name_to_id(ha_url, token)
    print(f"  Floors: {len(floor_cache)} | Areas: {len(area_cache)} | Labels: {len(label_cache)}")

    # ── Schritt 2: WebSocket-Verbindung aufbauen ──────────────────────────────
    ws: HAWebSocket | None = None
    if not args.dry_run:
        print("\n── WebSocket verbinden ───────────────────────────────────────────")
        try:
            ws = HAWebSocket(ha_url, token)
            print("  ✓ Verbunden")
        except Exception as e:
            print(f"  FEHLER: WebSocket-Verbindung fehlgeschlagen: {e}")
            sys.exit(1)

    # ── Schritt 3: Floors, Areas, Labels anlegen (nur fehlende) ──────────────
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
            zone_to_area[zone]   = area_name or None
            zone_to_labels[zone] = label_names
            continue

        assert ws is not None
        floor_id = get_or_create_floor(floor_name, ws, floor_cache) if floor_name else None
        area_id  = get_or_create_area(area_name, floor_id, ws, area_cache) if area_name else None
        label_ids = [
            lid for name in label_names
            if (lid := get_or_create_label(name, ws, label_cache)) is not None
        ]
        zone_to_area[zone]   = area_id
        zone_to_labels[zone] = label_ids

    # ── Schritt 4: Entities laden ─────────────────────────────────────────────
    print("\n── HA-Entities laden ─────────────────────────────────────────────")
    all_states = ha_rest("GET", "/api/states", ha_url, token)
    nersingen  = [s for s in all_states if s["entity_id"].startswith("sensor.cc600_")]
    print(f"  {len(nersingen)} CC600-Entities gefunden")

    # ── Schritt 5: Zuweisen ───────────────────────────────────────────────────
    print("\n── Area / Labels zuweisen ────────────────────────────────────────")
    stats: dict[str, int] = {"ok": 0, "no_change": 0, "no_uid": 0, "no_zone": 0, "skip": 0}

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

        assert ws is not None
        result = assign_entity(eid, area_id, label_ids, ws)
        stats[result] = stats.get(result, 0) + 1

    # ── Aufräumen ─────────────────────────────────────────────────────────────
    if ws:
        ws.close()

    # ── Ergebnis ──────────────────────────────────────────────────────────────
    print(f"\n── Ergebnis ───────────────────────────────────────────────────────")
    print(f"  Zugewiesen / aktualisiert:  {stats['ok']}")
    print(f"  Bereits korrekt (kein Patch):{stats.get('no_change', 0)}")
    print(f"  Keine Zone im Attribut:     {stats['no_zone']}")
    print(f"  Zone nicht konfiguriert:    {stats['skip']}")
    if not args.dry_run:
        print(f"  Keine unique_id (MQTT?):    {stats.get('no_uid', 0)}")

    if stats.get("no_uid", 0) > 0:
        print(
            f"\n⚠️  {stats['no_uid']} Entities ohne unique_id.\n"
            "   → MQTT Integration konfigurieren, AppDaemon neu starten,\n"
            "     dann dieses Script erneut ausführen."
        )


if __name__ == "__main__":
    main()
