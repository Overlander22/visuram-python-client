"""
VisuRAM → Home Assistant Integration
CC600 Gewächshaussteuerung K2118 "Flora Toskana / Nersingen"

Stand: 30.05.2026 — Live-Test erfolgreich, Protokoll vollständig reverse-engineered

═══════════════════════════════════════════════════════════════════════════════
Protokoll (aus Firefox-Netzwerkanalyse + DLL-Decompilierung, verifiziert):
═══════════════════════════════════════════════════════════════════════════════

  POST /visuram/RAMService.asmx/GlobalService
  Content-Type: application/json; charset=utf-8
  Body: {"sArg": "<escaped>", "WCFID": <uint32>, "bEditMode": false}

  ARG-Format: Semikolon als Trennzeichen zwischen Key:Value-Paaren

  Pflicht-Sequenz beim Start (3 Schritte):
  ─────────────────────────────────────────
  1. OnGetRechte  (counter=0, BDONTWAIT=false)
     sArg: CONTEXT[OnGetRechte]BDONTWAIT[false]ARG[FREIGABE:3;]SERVICECOUNTER[0:ms]
     → Antwort: ARG[URECHT:2000;USER:;] — Session aktiv

  2. OnCycleTimer BINITCALL (counter=1, BDONTWAIT=true)
     sArg: CONTEXT[OnCycleTimer]BDONTWAIT[true]ARG[TRIGGERSERVERTIMER:false;BINITCALL:true;PKLKETTE:0;]SERVICECOUNTER[1:ms]
     → Antwort: ARG[CCZEIT:...; VDPATH:...; BINITCALL:true;] — Advise-Subscription etabliert

  3. OnCycleTimer normal (counter=2,3,…, BDONTWAIT=true)
     sArg: CONTEXT[OnCycleTimer]BDONTWAIT[true]ARG[TRIGGERSERVERTIMER:false;PKLKETTE:0;]SERVICECOUNTER[n:ms]
     → Antwort: sCONTEXT[OnGetAdviseData]ARG[F0{Name,Wert Unit}F1{...}NF{n}]
                oder: CONTEXT[OnCycleTimer]ARG[CURRENTBILDID:3;STOERCSS:...;] (noch keine Daten)

  WCFID: Server-vergeben beim Laden von VisuRAM.aspx (UInt32 WCF-Handle).
         NICHT frei wählbar — muss vom Server bezogen werden.
         Wird ungültig wenn kein Polling stattfindet → Server sendet BRELOAD:true.
         → Verbindung muss sekündlich gepolt werden um sie am Leben zu halten.

  BRELOAD: {"d":"...BRELOAD:true;MLDG:\"Die Kommunikation mit dem RAM Datenserver wurde entfernt!..."}
           → Verbindung tot, Neuverbindung nötig (connect() erneut aufrufen)

  Sensor-Encoding: _x005B_=[  _x005D_=]  _x007B_={  _x007D_=}  _x002C_=,
"""

import datetime
import logging
import re
import time

import requests

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# Konfiguration
# ─────────────────────────────────────────────
VISURAMPC_HOST = "192.168.178.83"   # Windows-PC mit VisuRAM/RAMService/DataCom45
VISURAMPC_PORT = 80
K_NUMMER       = 2118               # K2118 "Flora Toskana / Nersingen"
BILD_ID        = 3                  # VisuRAM-Bildschirm mit Sensorübersicht
POLL_INTERVAL  = 1.0                # Sekunden zwischen Polls (≤2s für stabile Verbindung)
RECONNECT_WAIT = 5.0                # Sekunden Pause nach Verbindungsabbruch

# ─────────────────────────────────────────────
# ServicePassword – exakt aus RAMServicePassword.dll
# ─────────────────────────────────────────────
_TBLE = [
    0, 49345, 49537, 320, 49921, 960, 640, 49729, 50689, 1728,
    1920, 51009, 1280, 50625, 50305, 1088, 52225, 3264, 3456, 52545,
    3840, 53185, 52865, 3648, 2560, 51905, 52097, 2880, 51457, 2496,
    2176, 51265, 55297, 6336, 6528, 55617, 6912, 56257, 55937, 6720,
    7680, 57025, 57217, 8000, 56577, 7616, 7296, 56385, 5120, 54465,
    54657, 5440, 55041, 6080, 5760, 54849, 53761, 4800, 4992, 54081,
    4352, 53697, 53377, 4160, 61441, 12480, 12672, 61761, 13056, 62401,
    62081, 12864, 13824, 63169, 63361, 14144, 62721, 13760, 13440, 62529,
    15360, 64705, 64897, 15680, 65281, 16320, 16000, 65089, 64001, 15040,
    15232, 64321, 14592, 63937, 63617, 14400, 10240, 59585, 59777, 10560,
    60161, 11200, 10880, 59969, 60929, 11968, 12160, 61249, 11520, 60865,
    60545, 11328, 58369, 9408, 9600, 58689, 9984, 59329, 59009, 9792,
    8704, 58049, 58241, 9024, 57601, 8640, 8320, 57409, 40961, 24768,
    24960, 41281, 25344, 41921, 41601, 25152, 26112, 42689, 42881, 26432,
    42241, 26048, 25728, 42049, 27648, 44225, 44417, 27968, 44801, 28608,
    28288, 44609, 43521, 27328, 27520, 43841, 26880, 43457, 43137, 26688,
    30720, 47297, 47489, 31040, 47873, 31680, 31360, 47681, 48641, 32448,
    32640, 48961, 32000, 48577, 48257, 31808, 46081, 29888, 30080, 46401,
    30464, 47041, 46721, 30272, 29184, 45761, 45953, 29504, 45313, 29120,
    28800, 45121, 20480, 37057, 37249, 20800, 37633, 21440, 21120, 37441,
    38401, 22208, 22400, 38721, 21760, 38337, 38017, 21568, 39937, 23744,
    23936, 40257, 24320, 40897, 40577, 24128, 23040, 39617, 39809, 23360,
    39169, 22976, 22656, 38977, 34817, 18624, 18816, 35137, 19200, 35777,
    35457, 19008, 19968, 36545, 36737, 20288, 36097, 19904, 19584, 35905,
    17408, 33985, 34177, 17728, 34561, 18368, 18048, 34369, 33281, 17088,
    17280, 33601, 16640, 33217, 32897, 16448,
]

def _get_kennung(s: str, m: int) -> str:
    b = [ord(c) for c in s]
    n = 0
    for i in range(4):
        n = (n * m + b[i] % m) & 0xFFFFFFFF
    return str((n * 3) & 0xFFFFFFFF).zfill(9)

def service_password(k_nummer: int, d: datetime.date) -> str:
    """Tagespasswort für K<k_nummer> – aus RAMServicePassword.dll (CRC16-Variante)."""
    kx = format(k_nummer, '04x')
    s  = kx + d.strftime('%Y%m%d') + kx
    pw = "".join(_get_kennung(s[i*4:(i+1)*4], 199) for i in range(len(s) // 4))
    n  = 0
    for c in pw:
        n = (_TBLE[(n ^ ord(c)) & 0xFF] ^ (n >> 8)) & 0xFFFF
    t = str(n).zfill(3)[-3:]
    if ord(t[0]) > ord('5'):
        t = chr(ord(t[0]) - 5) + t[1:]
    return "#" + t

# ─────────────────────────────────────────────
# sArg-Builder
# ─────────────────────────────────────────────
def _ms() -> int:
    return int(time.time() * 1000)

def _build_arg(context: str, bdontwait: bool, arg_body: str, counter: int) -> str:
    """Baut einen vollständigen sArg-String zusammen (XML-Name-escaped)."""
    bw = "true" if bdontwait else "false"
    return (
        f"CONTEXT_x005B_{context}_x005D_"
        f"BDONTWAIT_x005B_{bw}_x005D_"
        f"ARG_x005B_{arg_body}_x005D_"
        f"SERVICECOUNTER_x005B_{counter}:{_ms()}_x005D_"
    )

def build_get_rechte_arg(counter: int) -> str:
    """Schritt 1: Session-Initialisierung, holt User-Rechte."""
    return _build_arg("OnGetRechte", bdontwait=False, arg_body="FREIGABE:3;", counter=counter)

def build_binitcall_arg(counter: int) -> str:
    """Schritt 2: Advise-Subscription aufbauen (BINITCALL:true).
    TRIGGERSERVERTIMER:true ist entscheidend – der Browser sendet ebenfalls true,
    dadurch liefert DataCom45 sofort Sensordaten und der Server setzt BPB:true.
    """
    return _build_arg(
        "OnCycleTimer", bdontwait=True,
        arg_body="TRIGGERSERVERTIMER:true;BINITCALL:true;PKLKETTE:0;",
        counter=counter,
    )

def build_poll_arg(counter: int) -> str:
    """Schritt 3+: Normaler Sensor-Poll (Heartbeat, löst ggf. BPB:true aus)."""
    return _build_arg(
        "OnCycleTimer", bdontwait=True,
        arg_body="TRIGGERSERVERTIMER:false;PKLKETTE:0;",
        counter=counter,
    )

def build_set_value_arg(
    feld_id: str,
    cc600_adr: str,
    w1: str,
    w2: str = "",
    counter: int = 99,
) -> str:
    """
    Schreibbefehl: setzt einen CC600-Wert via ChangeCCValue.

    Gefunden in Bedienen.js::ChangeCCValue() – ruft GlobalService mit
    Context 'OnChangeCCValue' auf. ARG verwendet { } als Trenner.

    Protokoll (aus Bedienen.js-Analyse, 02.06.2026):
      Context:  OnChangeCCValue
      ARG:      FUNCTION{ChangeCCValue}
                ADR{CC600-ADRESSE}
                W1{NEUER-WERT}
                W2{OPTIONALER-WERT-2}
                BHGRAMM{false}
                ID{FeldXX_Feld}
                EINHEIT{false}
                DONTCHECKRECH{true}
                ADVISEID{FeldXX}

    Args:
        feld_id:    FeldID ohne Suffix, z.B. 'Feld79'
        cc600_adr:  CC600-Kanaladresse, z.B. '0191112101' (Pumpe Ring)
        w1:         Neuer Wert für W1, z.B. '1' (ein) oder '0' (aus)
        w2:         Optionaler zweiter Wert (meist leer)
        counter:    ServiceCounter (sollte aktuellen session-counter nutzen)
    """
    # Innere Key-Value-Paare nutzen { } als Trenner (nicht [ ] wie die äußeren)
    def kv(key: str, val: str) -> str:
        return f"{key.upper()}_x007B_{val}_x007D_"

    inner = (
        kv("function", "ChangeCCValue") +
        kv("adr",      cc600_adr) +
        kv("w1",       w1) +
        kv("w2",       w2) +
        kv("bhgramm",  "false") +
        kv("id",       f"{feld_id}_Feld") +
        kv("einheit",  "false") +
        kv("dontcheckrech", "true") +
        kv("adviseid", feld_id)
    )
    return _build_arg("OnChangeCCValue", bdontwait=True, arg_body=inner, counter=counter)

# ─────────────────────────────────────────────
# Antwort-Parsing
# ─────────────────────────────────────────────
def decode_xml_names(s: str) -> str:
    """_xNNNN_ → Zeichen."""
    return re.sub(r'_x([0-9A-Fa-f]{4})_',
                  lambda m: chr(int(m.group(1), 16)), s)

def parse_sensors(raw: str) -> dict[str, dict]:
    """
    Parst Sensordaten aus einem GlobalCallback-Response.

    Format (HAR-Analyse 02.06.2026):
      sCONTEXT[OnGetAdviseData]ARG[F0{FeldID,Wert?Einheit}F1{...}NF{n}]

    Trennzeichen zwischen Wert und Einheit: '?' (beim ersten BINITCALL-Callback)
    oder ' ' (Leerzeichen, bei nachfolgenden Callbacks).
    Felder mit Wert '?' (noch nicht von DataCom45 befüllt) werden übersprungen.
    Nur 'FeldXX_Feld'-Felder werden zurückgegeben (keine Container-/Symbol-Felder).
    """
    decoded = decode_xml_names(raw)
    sensors: dict[str, dict] = {}
    for m in re.finditer(r'F\d+\{(Feld\d+_Feld),([^}]*)\}', decoded):
        name  = m.group(1)
        inner = m.group(2).strip()
        if not inner or inner == '?':
            continue
        # Symbol/Icon-Felder (z.B. ~/Vorlagen/Symbole/Leer.gif) ignorieren
        if '.gif' in inner:
            continue
        # Trennzeichen '?' (erster Callback) oder ' ' (Folge-Callbacks)
        sep = '?' if '?' in inner else ' '
        parts = inner.split(sep, 1)
        value = parts[0].strip()
        unit  = parts[1].strip() if len(parts) > 1 else ""
        if value:
            sensors[name] = {"name": name, "value": value, "unit": unit}
    return sensors

def parse_parameterzeile_batch(raw: str, addrs: list[str]) -> list[dict]:
    """
    Parst eine Parameterzeile-Batch-Antwort (ein oder mehrere Kanäle).

    Request-Format: ARG[ID:xxx;adr0:XXXXXXXXXX;adr1:YYYYYYYYYY;...]
    Response-Format pro Index i:
      ADRTXT{i}:Zone Name ;W1TXT{i}:Label;W2TXT{i}:Label;
      W1{i}:  value unit  ;W2{i}:  value unit  ;W12_{i}:n;

    Gibt eine Liste zurück (eine Eintrag je Adresse) mit:
      {cc600_adr, w1_value, w1_unit, w2_value, w2_unit, w1_label, w2_label}
    Einträge mit leerem w1_value UND leerem w2_value werden übersprungen.
    """
    decoded = decode_xml_names(raw)
    results = []

    for i, adr in enumerate(addrs):
        # W1-Wert: W1{i}:value unit; — kein Unterstrich vor dem Index
        # W12_{i}: ist das "Anzahl W-Werte"-Feld → kein Konflikt wegen Unterstrich
        w1_m   = re.search(rf';W1{i}:([^;]+);', decoded)
        w2_m   = re.search(rf';W2{i}:([^;]+);', decoded)
        w1lbl  = re.search(rf'W1TXT{i}:([^;]+);', decoded)
        w2lbl  = re.search(rf'W2TXT{i}:([^;]+);', decoded)

        def _split(s: str) -> tuple[str, str]:
            s = s.strip()
            if not s:
                return "", ""
            parts = s.split()
            return parts[0], " ".join(parts[1:]) if len(parts) > 1 else ""

        w1_value, w1_unit = _split(w1_m.group(1) if w1_m else "")
        w2_value, w2_unit = _split(w2_m.group(1) if w2_m else "")

        # Gif/Icon-Felder → leere Werte (Liste muss gleich lang wie addrs bleiben)
        if ".gif" in w1_value:
            w1_value, w1_unit = "", ""
        if ".gif" in w2_value:
            w2_value, w2_unit = "", ""

        results.append({
            "cc600_adr": adr,
            "w1_value":  w1_value,
            "w1_unit":   w1_unit,
            "w2_value":  w2_value,
            "w2_unit":   w2_unit,
            "w1_label":  (w1lbl.group(1).strip() if w1lbl else ""),
            "w2_label":  (w2lbl.group(1).strip() if w2lbl else ""),
        })

    return results


def parse_status(raw: str) -> dict[str, str]:
    """Parst Status-Felder (CURRENTBILDID, CCZEIT, STOERCSS, …) aus OnCycleTimer-Antwort."""
    decoded = decode_xml_names(raw)
    status: dict[str, str] = {}
    m = re.search(r'ARG\[([^\]]*)\]', decoded)
    if m:
        for item in m.group(1).split(';'):
            item = item.strip()
            if ':' in item:
                k, v = item.split(':', 1)
                status[k.strip()] = v.strip()
    return status

# ─────────────────────────────────────────────
# Haupt-Client-Klasse
# ─────────────────────────────────────────────
class VisuRAMClient:
    """
    Persistente VisuRAM-Verbindung mit automatischem Reconnect.

    Die Verbindung (WCFID) wird vom Server beim Laden von VisuRAM.aspx vergeben
    und bleibt nur solange gültig wie gepolt wird (≤ ~2 Sekunden Pause).
    Bei BRELOAD-Fehler wird automatisch neu verbunden.

    Verwendung:
        client = VisuRAMClient()
        client.run_loop(callback=my_callback)   # blockierend, mit auto-reconnect

    Oder manuell:
        client.connect()
        while True:
            sensors = client.poll()
            time.sleep(1)
    """

    def __init__(
        self,
        host: str = VISURAMPC_HOST,
        port: int = VISURAMPC_PORT,
        bild_id: int = BILD_ID,
    ):
        self.base_url  = f"http://{host}:{port}/visuram"
        self.bild_id   = bild_id
        self.session   = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:138.0) Gecko/20100101 Firefox/138.0",
            "Accept":     "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
        })
        self.wcfid: int | None = None  # wird vom Server beim ersten VisuRAM.aspx-Aufruf vergeben
        self.viewstate = ""   # ASP.NET ViewState aus VisuRAM.aspx – für GlobalCallback
        self.counter   = 0
        self._connected = False
        self._trigger_counter = 0  # Anzahl verbleibender TRIGGER:true Polls nach connect()

    # ── Leichtgewichtiger Connect (nur für Parameterzeile-Polling) ───────
    def connect_lightweight(self) -> None:
        """
        Minimaler Verbindungsaufbau für Parameterzeile-Polling:
          1. VisuRAM.aspx laden → WCFID ermitteln
          2. OnGetRechte → Session validieren (URECHT:2000)

        Kein BINITCALL, kein BildId-Advise-Subscribe.
        Reicht für Parameterzeile-Calls und ChangeCCValue.
        """
        self._connected = False
        self.counter = 0
        self._register_session()
        raw = self._post(build_get_rechte_arg(self.counter))
        decoded = decode_xml_names(raw)
        if "URECHT" not in decoded:
            raise ConnectionError(f"OnGetRechte fehlgeschlagen: {raw[:200]}")
        self.counter = 1
        self._connected = True
        self._initial_sensors = {}

    def fetch_channels_batch(
        self,
        addrs: list[str],
        batch_id: str = "batch",
    ) -> list[dict]:
        """
        Liest eine Gruppe von CC600-Kanälen via Parameterzeile in einem Call.

        Args:
            addrs:    Liste von CC600-Adressen (max. ~30 pro Batch empfohlen)
            batch_id: Beliebige ID-Kennung für den ARG (nur für Logging)

        Returns:
            Liste von Dicts mit {cc600_adr, w1_value, w1_unit, w2_value, w2_unit,
                                  w1_label, w2_label}
        """
        if not addrs:
            return []
        arg_body = (
            f"ID:{batch_id};"
            + "".join(f"adr{i}:{adr};" for i, adr in enumerate(addrs))
        )
        s_arg = _build_arg("Parameterzeile", bdontwait=True,
                           arg_body=arg_body, counter=self.counter)
        self.counter += 1
        raw = self._post(s_arg)
        return parse_parameterzeile_batch(raw, addrs)

    # ── Verbindungsaufbau (BildId-Subscription) ──────────────────────────
    def connect(self) -> None:
        """
        Vollständiger Verbindungsaufbau:
          0. VisuRAM.aspx laden → WCFID ermitteln
          1. OnGetRechte       → Session validieren (URECHT:2000)
          2. BINITCALL         → Advise-Subscription starten (CCZEIT erscheint)
        """
        logger.info("Verbinde mit VisuRAM (%s) …", self.base_url)
        self._connected = False
        self.counter = 0

        # 0 – Session bei VisuRAM.aspx registrieren (WCFID bleibt über Reconnects gleich)
        self._register_session()
        logger.info("WCFID: %d", self.wcfid)

        # 1 – OnGetRechte
        raw = self._post(build_get_rechte_arg(self.counter))
        decoded = decode_xml_names(raw)
        if "URECHT" not in decoded:
            raise ConnectionError(f"OnGetRechte fehlgeschlagen: {raw[:200]}")
        logger.info("OnGetRechte ✓  (%s)", decoded[decoded.find("URECHT"):decoded.find("URECHT")+20])
        self.counter = 1

        # 2 – BINITCALL
        raw = self._post(build_binitcall_arg(self.counter))
        decoded = decode_xml_names(raw)
        if "BRELOAD" in decoded:
            raise ConnectionError(f"BINITCALL fehlgeschlagen (BRELOAD): {raw[:200]}")
        if "CCZEIT" in decoded:
            logger.info("BINITCALL ✓  CC600-Uhr: %s", parse_status(raw).get("CCZEIT", "?"))
        else:
            logger.info("BINITCALL ✓  (CCZEIT nicht sichtbar – ggf. Browser konkurriert)")
        self.counter = 2
        self._connected = True
        self._trigger_counter = 3  # erste 3 Polls mit TRIGGERSERVERTIMER:true (wie Browser)
        self._initial_sensors: dict = {}  # Sensor-Snapshot aus BINITCALL-Callback

        # BPB:true in BINITCALL-Antwort → DataCom45 hat sofort Daten bereit.
        # Browser ruft GlobalCallback unmittelbar auf – wir auch.
        if "BPB:true" in decoded:
            logger.info("BPB:true nach BINITCALL – rufe GlobalCallback sofort …")
            self._initial_sensors = self._global_callback(binitcall=True)

        logger.info("Verbindung erfolgreich. Beginne Polling …")

    # ── Einzelner Poll ────────────────────────────────────────────────────
    def poll(self) -> dict[str, dict]:
        """
        Einzelner Poll-Zyklus via GlobalService (CycleTimer).
        Bei BPB:true ruft er automatisch GlobalCallback auf und gibt die Sensordaten zurück.
        Gibt leeres Dict zurück wenn keine neuen Daten.
        Wirft ConnectionError bei BRELOAD.
        """
        if not self._connected:
            raise RuntimeError("Nicht verbunden – connect() zuerst aufrufen")

        # Die ersten Polls nach connect() senden TRIGGERSERVERTIMER:true
        # (wie der Browser) um DataCom45 zum Liefern von Sensordaten zu veranlassen.
        trigger = self._trigger_counter > 0
        if trigger:
            self._trigger_counter -= 1
        s_arg = _build_arg(
            "OnCycleTimer", bdontwait=True,
            arg_body=f"TRIGGERSERVERTIMER:{'true' if trigger else 'false'};PKLKETTE:0;",
            counter=self.counter,
        )
        raw = self._post(s_arg)
        self.counter += 1

        if "BRELOAD" in raw:
            self._connected = False
            raise ConnectionError("Verbindung unterbrochen (BRELOAD) – Neuverbindung nötig")

        decoded = decode_xml_names(raw)
        if "BPB:true" in decoded:
            return self._global_callback(binitcall=False)

        return {}  # kein BPB → keine neuen Sensordaten

    # ── Kontinuierlicher Loop ──────────────────────────────────────────────
    def run_loop(
        self,
        callback,
        interval: float = POLL_INTERVAL,
        reconnect_wait: float = RECONNECT_WAIT,
    ) -> None:
        """
        Blockierender Poll-Loop mit automatischem Reconnect.

        callback(sensors: dict) wird bei jedem Poll mit Sensordaten aufgerufen.
        Bei leerem Dict (Zwischen-Tick ohne neue Daten) wird callback NICHT aufgerufen.
        """
        while True:
            try:
                if not self._connected:
                    self.connect()
                    # Initiale Sensordaten aus BINITCALL-Callback sofort weitergeben
                    if self._initial_sensors:
                        callback(self._initial_sensors)
                        self._initial_sensors = {}

                sensors = self.poll()
                if sensors:
                    callback(sensors)

                time.sleep(interval)

            except ConnectionError as exc:
                logger.warning("Verbindungsfehler: %s – Neuverbindung in %.0fs …", exc, reconnect_wait)
                self._connected = False
                time.sleep(reconnect_wait)

            except requests.RequestException as exc:
                logger.warning("HTTP-Fehler: %s – Neuverbindung in %.0fs …", exc, reconnect_wait)
                self._connected = False
                time.sleep(reconnect_wait)

    # ── Schreiben / Schalten ──────────────────────────────────────────────
    def _ensure_write_auth(self, cc600_adr: str, password: str) -> None:
        """
        Stellt sicher, dass die Session Schreibrechte hat (Aendern1-Bit, 0x0002).

        Ablauf (aus Kennwort.js analysiert, 02.06.2026):
          1. OnGetRechte mit ADR:<adresse> → prüft ob User bereits eingeloggt
          2. Falls uRecht == 0 oder kein User: OnLogin mit KENNWORT:<pw>;ADR:<adresse>
             → Server setzt Aendern1-Bit in uRecht

        Wird pro Session nur einmal gebraucht; danach haben alle folgenden
        ChangeCCValue-Calls die nötige Berechtigung.
        """
        # Schritt 1: Rechte abfragen
        raw = self._post(_build_arg(
            "OnGetRechte", bdontwait=False,
            arg_body=f"ADR:{cc600_adr};",
            counter=self.counter,
        ))
        self.counter += 1
        decoded = decode_xml_names(raw)

        # Wenn uRecht > 0 und User gesetzt: Session hat bereits Schreibrechte
        status = parse_status(raw)
        u_recht_hex = status.get("URECHT", "0")
        try:
            u_recht = int(u_recht_hex, 16)
        except ValueError:
            u_recht = 0

        AENDERN1 = 0x0002
        if u_recht & AENDERN1:
            logger.debug("Schreibrechte bereits vorhanden (uRecht=0x%X)", u_recht)
            return

        # Schritt 2: Einloggen mit Passwort
        logger.info("Schreibrechte fehlen – sende OnLogin mit Passwort …")
        raw2 = self._post(_build_arg(
            "OnLogin", bdontwait=False,
            arg_body=f"KENNWORT:{password};ADR:{cc600_adr};",
            counter=self.counter,
        ))
        self.counter += 1
        decoded2 = decode_xml_names(raw2)
        status2 = parse_status(raw2)
        u_recht2_hex = status2.get("URECHT", "0")
        try:
            u_recht2 = int(u_recht2_hex, 16)
        except ValueError:
            u_recht2 = 0

        if u_recht2 & AENDERN1:
            logger.info("OnLogin erfolgreich – Schreibrechte erhalten (uRecht=0x%X)", u_recht2)
        else:
            raise PermissionError(
                f"OnLogin gescheitert – Schreibrechte nicht erhalten "
                f"(uRecht=0x{u_recht2:04X}). Passwort korrekt?"
            )

    def set_value(self, feld_id: str, cc600_adr: str, w1: str, w2: str = "",
                  password: str = "1111") -> str:
        """
        Setzt einen CC600-Wert über ChangeCCValue (Context: OnChangeCCValue).

        Für Ein/Aus-Schalter (Magnetventile, Pumpen):
            w1 = "1" (ein/an) oder "0" (aus)
        Für Zeitwerte:
            w1 = "5:00" (min:s) etc.
        Für Temperaturwerte:
            w1 = "25,0" (Komma als Dezimaltrenner wie CC600-Konvention)

        Gibt die rohe Server-Antwort zurück. Bei Erfolg enthält sie
        CONTEXT[OnChangeCCValue] mit aktualisierten Feldwerten.

        Hinweis zu W1/W2:
            Für Kanäle mit zwei Werten (z.B. Gießdauer/Handstart):
              - w1 = Gießdauer, z.B. "12:00" (min:s)
              - w2 = Handstart-Status:
                  "0"  = Aus (manuell gesperrt)
                  "1"  = Automatik (CC600-Steuerungslogik greift)
                  "2"  = Manuell Ein (Ventil öffnen, unabhängig von CC600)
                  ⚠️  Live verifiziert 02.06.2026: nur w2="2" öffnet das Ventil!
            Für einfache Schalter (Pumpen etc.):
              - w1 = "2" (ein) oder "0" (aus), w2 = "" (leer) – noch zu testen
            Werte werden OHNE Einheit übergeben (bEinheit=false).

        Raises:
            RuntimeError:    Nicht verbunden.
            PermissionError: Login-Passwort falsch oder Rechte fehlen.
        """
        if not self._connected:
            raise RuntimeError("Nicht verbunden – connect() zuerst aufrufen")

        # Schreibrechte sicherstellen (einmalig pro Session)
        self._ensure_write_auth(cc600_adr, password)

        s_arg = build_set_value_arg(
            feld_id=feld_id,
            cc600_adr=cc600_adr,
            w1=w1,
            w2=w2,
            counter=self.counter,
        )
        self.counter += 1
        raw = self._post(s_arg)
        decoded = decode_xml_names(raw)
        logger.info("set_value(%s, w1=%r, w2=%r) → %s", feld_id, w1, w2, decoded[:150])
        return decoded

    # ── Interna ────────────────────────────────────────────────────────────
    def _register_session(self) -> None:
        """
        Initialisiert die VisuRAM-Session in zwei Schritten – genau wie ein Browser:

        Schritt 1: GET ohne WCFID → Server vergibt frische WCFID (z.B. 2984)
        Schritt 2: GET MIT dieser WCFID → Server registriert BildId=3 für die Session
                   und setzt intern CURRENTBILDID. Erst dann liefert der Server beim
                   BINITCALL das CURRENTBILDID-Flag – und DataCom45 weiß welche Felder
                   er abonnieren soll.

        Erkenntnisse aus HAR-Analyse (02.06.2026): Browser sendet immer die gespeicherte
        WCFID aus der vorherigen Session mit. Da wir keine gespeicherte haben, simulieren
        wir das mit dem Zwei-Schritt-Verfahren.
        """
        url = f"{self.base_url}/VisuRAM.aspx"
        base_params = {"ClientY": 1080, "ClientX": 1920, "BodyX": 1854,
                       "BildId": self.bild_id}

        # Schritt 1: GET ohne WCFID – Server vergibt frische WCFID
        resp1 = self.session.get(url, params=base_params, timeout=10)
        resp1.raise_for_status()
        m = re.search(r"'&WCFID=(\d+)&BildId=", resp1.text)
        if not m:
            raise ValueError(
                "Server-WCFID nicht im VisuRAM.aspx-HTML gefunden.\n"
                "Prüfe ob der VisuRAM-PC erreichbar ist und der RAMService läuft."
            )
        self.wcfid = int(m.group(1))
        logger.debug("Schritt 1: Server vergab WCFID %d", self.wcfid)

        # Schritt 2: GET MIT der vergebenen WCFID – registriert BildId=3 für diese Session
        resp2 = self.session.get(url, params={**base_params, "WCFID": self.wcfid},
                                 timeout=10)
        resp2.raise_for_status()

        # ViewState und WCFID aus Schritt-2-Response (diese ist maßgeblich)
        m_vs = re.search(r'id="__VIEWSTATE"\s+value="([^"]+)"', resp2.text)
        self.viewstate = m_vs.group(1) if m_vs else ""

        m2 = re.search(r"'&WCFID=(\d+)&BildId=", resp2.text)
        if m2:
            wcfid2 = int(m2.group(1))
            logger.debug("Schritt 2: Server bestätigte/vergab WCFID %d", wcfid2)
            self.wcfid = wcfid2

    def _global_callback(self, binitcall: bool = False) -> dict[str, dict]:
        """
        ASP.NET WebForms Callback an VisuRAM.aspx – liefert aktuelle Sensordaten.

        Entscheidend: WCFID muss in der URL stehen (nicht nur im Body).
        Der Server identifiziert die DataCom45-Subscription über die WCFID in der URL.
        Das __VIEWSTATEGENERATOR-Feld ist eine statische Prüfsumme der Seitenstruktur.

        Protokoll (aus HAR-Analyse 02.06.2026):
          POST VisuRAM.aspx?ClientY=...&WCFID=<n>&BildId=3
          __CALLBACKID=__Page
          __CALLBACKPARAM=CONTEXT_x005B_OnGetAdviseData_x005D_ARG_x005B_[BINITCALL:true;]_x005D_
          __VIEWSTATE=<aus _register_session()>
          __VIEWSTATEGENERATOR=07F87BCC

        Antwort: sCONTEXT[OnGetAdviseData]ARG[F0{FeldID,Wert?Einheit}...NF{n}]
        """
        inner = "BINITCALL:true;" if binitcall else ""
        param = (
            f"CONTEXT_x005B_OnGetAdviseData_x005D_"
            f"ARG_x005B_{inner}_x005D_"
        )
        url = f"{self.base_url}/VisuRAM.aspx"
        resp = self.session.post(
            url,
            params={"ClientY": 1080, "ClientX": 1920, "BodyX": 1854,
                    "BildId": self.bild_id, "WCFID": self.wcfid},
            data={
                "__CALLBACKID":        "__Page",
                "__CALLBACKPARAM":     param,
                "__VIEWSTATE":         self.viewstate,
                "__VIEWSTATEGENERATOR": "07F87BCC",
                "__EVENTTARGET":       "",
                "__EVENTARGUMENT":     "",
            },
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer":      f"{self.base_url}/VisuRAM.aspx",
            },
            timeout=10,
        )
        resp.raise_for_status()
        sensors = parse_sensors(resp.text)
        if sensors:
            logger.info("GlobalCallback: %d Sensor-Werte empfangen", len(sensors))
        else:
            logger.debug("GlobalCallback: keine neuen Werte (nF=0 oder alle '?')")
        return sensors

    def _post(self, s_arg: str) -> str:
        url     = f"{self.base_url}/RAMService.asmx/GlobalService"
        payload = {"sArg": s_arg, "WCFID": self.wcfid, "bEditMode": False}
        resp    = self.session.post(
            url, json=payload,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Referer": f"{self.base_url}/VisuRAM.aspx",
            },
            timeout=10,
        )
        resp.raise_for_status()
        return resp.text


# ─────────────────────────────────────────────
# Sensor-Mapping aus cc600_channel_mapping.json
# ─────────────────────────────────────────────

def load_field_lookup(mapping_path: str | None = None) -> dict[str, dict]:
    """
    Lädt cc600_channel_mapping.json und gibt ein Dict zurück:
      { "Feld92": {"cc600_adr": "0101500311", "w1_label": "...", "w2_label": "..."},
        "Feld91": {"cc600_adr": "0101500612", ...}, ... }

    Schlüssel: FeldID ohne '_Feld'-Suffix (z.B. 'Feld92').
    Wird von set_value() verwendet um cc600_adr aus FeldID abzuleiten.
    """
    import json, os

    if mapping_path is None:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        candidates = [
            os.path.join(script_dir, "cc600_channel_mapping.json"),
            os.path.join(os.path.dirname(script_dir), "data", "cc600_channel_mapping.json"),
        ]
        for candidate in candidates:
            if os.path.exists(candidate):
                mapping_path = candidate
                break
        if mapping_path is None:
            mapping_path = candidates[0]

    if not os.path.exists(mapping_path):
        logger.warning("cc600_channel_mapping.json nicht gefunden: %s", mapping_path)
        return {}

    with open(mapping_path, encoding="utf-8") as f:
        channels = json.load(f)

    lookup: dict[str, dict] = {}
    for ch in channels:
        cc600_adr = ch.get("cc600_adr", "")
        if not cc600_adr:
            continue
        info = {
            "cc600_adr": cc600_adr,
            "w1_label":  ch.get("w1_label", ""),
            "w2_label":  ch.get("w2_label", ""),
            "desc":      ch.get("desc", ""),
        }
        if ch.get("feld_id_w1"):
            lookup[ch["feld_id_w1"]] = info
        if ch.get("feld_id_w2"):
            lookup[ch["feld_id_w2"]] = info

    logger.debug("Field-Lookup geladen: %d Einträge", len(lookup))
    return lookup


def load_field_names(mapping_path: str | None = None) -> dict[str, str]:
    """
    Lädt cc600_channel_mapping.json und gibt ein Dict zurück:
      { "Feld28_Feld": "Außentemperatur",
        "Feld33_Feld": "Windgeschwindigkeit / Richtung", ... }

    Args:
        mapping_path: Pfad zur JSON-Datei. Wird automatisch gefunden wenn None.
    """
    import json, os

    if mapping_path is None:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        # Suchreihenfolge:
        # 1. Gleiches Verzeichnis wie dieses Script (AppDaemon-Deployment)
        # 2. ../data/ relativ zum Script-Verzeichnis (Repository-Struktur)
        candidates = [
            os.path.join(script_dir, "cc600_channel_mapping.json"),
            os.path.join(os.path.dirname(script_dir), "data", "cc600_channel_mapping.json"),
        ]
        for candidate in candidates:
            if os.path.exists(candidate):
                mapping_path = candidate
                break
        if mapping_path is None:
            mapping_path = candidates[0]  # Für Fehlermeldung

    if not os.path.exists(mapping_path):
        logger.warning("cc600_channel_mapping.json nicht gefunden: %s", mapping_path)
        return {}

    with open(mapping_path, encoding="utf-8") as f:
        channels = json.load(f)

    names: dict[str, str] = {}
    for ch in channels:
        desc       = ch.get("desc", "").strip()
        w1_label   = ch.get("w1_label", "").strip()
        w2_label   = ch.get("w2_label", "").strip()
        feld_id_w1 = ch.get("feld_id_w1")
        feld_id_w2 = ch.get("feld_id_w2")
        zone       = ch.get("zone", "")
        kanal      = ch.get("kanal", "")

        # W1-Feld: Beschreibung = w1_label (oder desc wenn kürzer/besser)
        if feld_id_w1:
            label = w1_label or desc or f"{zone}.{kanal}"
            names[f"{feld_id_w1}_Feld"] = label

        # W2-Feld: Beschreibung = "Hauptname / w2_label"
        if feld_id_w2:
            if w2_label:
                label = f"{w1_label or desc} / {w2_label}".strip(" /")
            else:
                label = w1_label or desc or f"{zone}.{kanal} W2"
            names[f"{feld_id_w2}_Feld"] = label

    logger.debug("Feld-Namen geladen: %d Einträge", len(names))
    return names


# ─────────────────────────────────────────────
# Home Assistant REST API Push
# ─────────────────────────────────────────────

def push_to_ha(sensors: dict,
               ha_url: str,
               ha_token: str,
               field_mapping: dict | None = None) -> None:
    """
    Schreibt Sensordaten via HA REST API in Home Assistant.

    Jedes Feld wird als Sensor-Entity angelegt:
      POST /api/states/sensor.nersingen_<feld_id_lower>

    Args:
        sensors:       Dict von parse_sensors() → {FeldID: {name, value, unit}}
        ha_url:        HA-Basis-URL, z.B. "http://192.168.178.102:8123"
        ha_token:      Long-Lived Access Token aus HA
        field_mapping: Optional – Dict {FeldID: "Lesbarer Name"} für friendly_name
    """
    headers = {
        "Authorization": f"Bearer {ha_token}",
        "Content-Type":  "application/json",
    }

    # Einheiten → HA Device Class Mapping
    UNIT_TO_DEVICE_CLASS = {
        "oC": ("temperature",    "°C"),
        "°C": ("temperature",    "°C"),
        "klx": (None,            "klx"),
        "klxh": (None,           "klxh"),
        "m/s": ("wind_speed",    "m/s"),
        "W":   ("power",         "W"),
        "kW":  ("power",         "kW"),
        "%":   ("humidity",      "%"),
    }

    pushed = 0
    errors = 0
    for feld_id, sensor in sensors.items():
        value = sensor.get("value", "")
        unit  = sensor.get("unit", "")
        if not value:
            continue

        entity_id = f"sensor.nersingen_{feld_id.lower().replace('_feld', '')}"
        friendly  = (field_mapping or {}).get(feld_id, feld_id)

        device_class, ha_unit = UNIT_TO_DEVICE_CLASS.get(unit, (None, unit))

        # Numerischen Wert extrahieren (Komma → Punkt)
        try:
            num_value = float(value.replace(",", ".").split()[0])
            state = str(num_value)
        except (ValueError, IndexError):
            state = value  # Text-Wert (z.B. "0 aus")

        payload = {
            "state": state,
            "attributes": {
                "friendly_name":      friendly,
                "unit_of_measurement": ha_unit,
                "device_class":       device_class,
                "source":             "VisuRAM CC600",
                "feld_id":            feld_id,
            },
        }
        # None-Werte aus Attributen entfernen
        payload["attributes"] = {k: v for k, v in payload["attributes"].items()
                                  if v is not None}

        try:
            resp = requests.post(
                f"{ha_url}/api/states/{entity_id}",
                headers=headers, json=payload, timeout=5,
            )
            resp.raise_for_status()
            pushed += 1
        except requests.RequestException as e:
            logger.warning("HA Push fehlgeschlagen für %s: %s", entity_id, e)
            errors += 1

    if pushed:
        logger.info("HA Push: %d Entities aktualisiert (%d Fehler)", pushed, errors)


# ─────────────────────────────────────────────
# Standalone-Test / Hauptprogramm
# ─────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%H:%M:%S",
    )

    # Optionale lokale Konfiguration laden (config_local.py)
    HA_URL   = None
    HA_TOKEN = None
    try:
        import sys, os
        sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
        from config_local import HA_URL, HA_TOKEN  # type: ignore
        print(f"HA-URL: {HA_URL}")
    except ImportError:
        print("Kein config_local.py gefunden – kein HA-Push.")

    pwd = service_password(K_NUMMER, datetime.date.today())
    print(f"Tagespasswort K{K_NUMMER}: {pwd}\n")

    # Sensor-Namen laden
    field_names = load_field_names()
    if field_names:
        print(f"{len(field_names)} Sensor-Namen geladen\n")

    def on_sensors(sensors: dict) -> None:
        print(f"{'─'*60}")
        print(f"{len(sensors)} Sensoren empfangen:")
        for k, v in sorted(sensors.items()):
            name = field_names.get(k, k)
            print(f"  {name:45s} = {v['value']:>12s}  {v['unit']}")
        # HA Push wenn konfiguriert
        if HA_URL and HA_TOKEN:
            push_to_ha(sensors, HA_URL, HA_TOKEN, field_mapping=field_names)

    client = VisuRAMClient()
    client.run_loop(on_sensors, interval=POLL_INTERVAL)
