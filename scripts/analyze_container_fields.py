"""
Analysiert ContainerXFeldY-Felder aus dem VisuRAM.aspx HTML (BildId=3).

Holt das HTML live vom VisuRAM-PC, extrahiert alle InitFeld()-Aufrufe
für Container-Felder und ordnet sie per TOOLTIPADR einer CC600-Adresse,
Zone und Kanal zu.

Ausgabe: Tabelle mit ContainerID, FeldNr, TOOLTIPADR, cc600_adr, Zone, Kanal,
         plus Abgleich mit cc600_channel_mapping.json (bereits gemappt?).

Aufruf:
    python3 scripts/analyze_container_fields.py
"""

import json
import re
import sys
import os

import requests

HOST     = "192.168.178.83"
PORT     = 80
BILD_ID  = 3
BASE_URL = f"http://{HOST}:{PORT}/visuram"

# Aus cc600_adr (10 Stellen, z.B. "0102422101") Zone + Kanal ableiten.
# Format: 01 ZZ KKKKK P
#   ZZ    = Zone (2 Stellen, z.B. 01–05, 50, 91)
#   KKKKK = Kanal (5 Stellen)
#   P     = W1=1, W2=2 (letzte Stelle)
def decode_adr(adr: str) -> tuple[str, str, str]:
    """Gibt (zone, kanal, wert) zurück oder ('?','?','?') bei Fehler."""
    if len(adr) == 10 and adr.startswith("01"):
        zone  = adr[2:4]
        kanal = adr[4:9]
        wert  = adr[9]
        return zone, kanal, wert
    return "?", "?", "?"


def fetch_html() -> str:
    """Holt VisuRAM.aspx HTML (2-Schritt wie Browser/VisuRAMClient)."""
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:138.0) Gecko/20100101 Firefox/138.0",
    })
    url    = f"{BASE_URL}/VisuRAM.aspx"
    params = {"ClientY": 1080, "ClientX": 1920, "BodyX": 1854, "BildId": BILD_ID}

    # Schritt 1: WCFID holen
    r1 = session.get(url, params=params, timeout=10)
    r1.raise_for_status()
    m = re.search(r"'&WCFID=(\d+)&BildId=", r1.text)
    if not m:
        raise ValueError("WCFID nicht gefunden im HTML")
    wcfid = m.group(1)

    # Schritt 2: Mit WCFID abrufen → enthält InitFeld-Aufrufe
    r2 = session.get(url, params={**params, "WCFID": wcfid}, timeout=10)
    r2.raise_for_status()
    return r2.text


def parse_initfeld(html: str) -> list[dict]:
    """
    Extrahiert InitFeld()-Aufrufe aus dem HTML.

    Muster im HTML (JS):
        InitFeld("Feld42_Feld","TOOLTIPADR:0104123161;FELDART:Datenfeld;...");
        InitFeld("Container4Feld1_Feld","TOOLTIPADR:0101422101;FELDART:Datenfeld;...");
        InitFeld("Container4Feld2_Feld","FELDART:Analogsymbol;...");  ← kein TOOLTIPADR

    Gibt Liste von Dicts zurück mit:
      feld_id, container_nr, feld_nr, tooltip_adr, feldart, raw_params
    """
    results = []
    # Matcht sowohl FeldXX als auch ContainerXFeldY
    pattern = re.compile(
        r'InitFeld\s*\(\s*"((?:Feld\d+|Container\d+Feld\d+)_Feld)"\s*,\s*"([^"]*)"\s*\)'
    )
    for m in pattern.finditer(html):
        feld_id    = m.group(1)
        raw_params = m.group(2)

        # TOOLTIPADR extrahieren
        ta = re.search(r'TOOLTIPADR:([^;]+)', raw_params)
        tooltip_adr = ta.group(1).strip() if ta else ""

        # FELDART extrahieren
        fa = re.search(r'FELDART:([^;]+)', raw_params)
        feldart = fa.group(1).strip() if fa else ""

        # Container-Nummer und Feld-Nummer
        cm = re.match(r'Container(\d+)Feld(\d+)_Feld', feld_id)
        fm = re.match(r'Feld(\d+)_Feld', feld_id)

        entry = {
            "feld_id":     feld_id,
            "is_container": bool(cm),
            "container_nr": int(cm.group(1)) if cm else None,
            "feld_nr":      int(cm.group(2)) if cm else (int(fm.group(1)) if fm else None),
            "tooltip_adr":  tooltip_adr,
            "feldart":      feldart,
            "raw_params":   raw_params,
        }
        results.append(entry)

    return results


def load_existing_mappings() -> dict[str, dict]:
    """Lädt cc600_channel_mapping.json → Dict: feld_id → channel info."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(os.path.dirname(script_dir), "data", "cc600_channel_mapping.json"),
        os.path.join(script_dir, "cc600_channel_mapping.json"),
    ]
    for path in candidates:
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                channels = json.load(f)
            lookup = {}
            for ch in channels:
                for key in ("feld_id_w1", "feld_id_w2"):
                    fid = ch.get(key)
                    if fid:
                        lookup[fid] = ch
            return lookup
    return {}


def main():
    print("Lade VisuRAM.aspx HTML …")
    html = fetch_html()
    print(f"HTML erhalten ({len(html):,} Zeichen)\n")

    entries     = parse_initfeld(html)
    existing    = load_existing_mappings()

    container_entries = [e for e in entries if e["is_container"]]
    normal_entries    = [e for e in entries if not e["is_container"]]

    print(f"InitFeld-Aufrufe gesamt: {len(entries)}")
    print(f"  Normale FeldXX:        {len(normal_entries)}")
    print(f"  ContainerX:            {len(container_entries)}")
    print()

    # ── Container-Felder: vollständige Tabelle ────────────────────────────
    print("=" * 100)
    print(f"{'ContainerFeld':<32} {'TOOLTIPADR':<12} {'Feldart':<14} {'Zone':<5} {'Kanal':<7} {'W':<3} {'Status'}")
    print("=" * 100)

    unmapped_feld1 = []

    for e in sorted(container_entries, key=lambda x: (x["container_nr"], x["feld_nr"])):
        fid      = e["feld_id"]
        fid_nosx = fid.replace("_Feld", "")  # ohne _Feld-Suffix für Lookup
        ta       = e["tooltip_adr"]
        feldart  = e["feldart"]
        zone, kanal, wert = decode_adr(ta) if ta else ("–", "–", "–")

        already = existing.get(fid_nosx)
        if already:
            status = f"✓ gemappt → {already.get('ha_label_w1') or already.get('desc', '')}"
        elif ta:
            status = "← FEHLT im Mapping"
            if e["feld_nr"] == 1:
                unmapped_feld1.append(e)
        else:
            status = "(kein TOOLTIPADR – Anzeigesymbol)"

        print(f"  {fid_nosx:<30} {ta or '—':<12} {feldart:<14} {zone:<5} {kanal:<7} {wert:<3} {status}")

    # ── Zusammenfassung: fehlende Feld1-Container ─────────────────────────
    if unmapped_feld1:
        print()
        print("=" * 100)
        print("FEHLENDE ContainerXFeld1 MIT TOOLTIPADR (echte Sensoren ohne Mapping):")
        print()
        for e in unmapped_feld1:
            fid  = e["feld_id"].replace("_Feld", "")
            ta   = e["tooltip_adr"]
            zone, kanal, wert = decode_adr(ta)
            print(f"  {fid:<30} TOOLTIPADR={ta}  Zone={zone}  Kanal={kanal}  W={wert}")
            print(f"    → cc600_adr wäre: {ta}")
            print(f"    → Weitere Params: {e['raw_params'][:120]}")
            print()

    # ── Alle Params für die 5 unbekannten Container ausgeben ──────────────
    unknown_containers = {12, 16, 25, 26, 27}
    interesting = [e for e in container_entries if e["container_nr"] in unknown_containers]
    if interesting:
        print("=" * 100)
        print("DETAIL-AUSGABE für Container 12/16/25/26/27 (vollständige InitFeld-Parameter):")
        print()
        for e in sorted(interesting, key=lambda x: (x["container_nr"], x["feld_nr"])):
            print(f"  {e['feld_id']:<35} → {e['raw_params']}")
        print()


if __name__ == "__main__":
    main()
