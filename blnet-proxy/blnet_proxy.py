#!/usr/bin/env python3
"""
BL-Net Proxy für BL-NET V2.19

WICHTIG: BL-Net erlaubt nur EINE aktive Session und sperrt nach ~30s Inaktivität.
Lösung:
  - Einmalig einloggen, Session wiederverwenden
  - Keepalive-Thread sendet alle 20s eine Minimalanfrage
  - _blnet_lock verhindert parallele HTTP-Anfragen ans BL-Net
  - Bei Session-Fehler: automatisch neu einloggen

Port: 8765 → http://localhost:8765/blnet
"""
import requests
import re
import json
import time
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

BLNET_URL = "http://192.168.178.150"
BLNET_PASSWORD = "mueller"
BLNET_NODE = 0
PROXY_PORT = 8765
POLL_INTERVAL = 120       # Sekunden zwischen vollständigen Abfragen
KEEPALIVE_INTERVAL = 20   # Sekunden zwischen Keepalive-Pings
REQUEST_TIMEOUT = 10
LOGIN_COOLDOWN = 600      # Sekunden warten nach fehlgeschlagenem Login

TAID_FILE = "/tmp/blnet_taid.txt"

# Globale Session
_session = requests.Session()
_session_valid = False
_last_login_attempt = 0
_blnet_lock = threading.Lock()   # Nur ein HTTP-Request ans BL-Net gleichzeitig


def _load_taid():
    """Gespeicherte TAID laden und in Session injizieren."""
    try:
        with open(TAID_FILE) as f:
            taid = f.read().strip()
        if taid:
            _session.cookies.set("TAID", taid, domain="192.168.178.150")
            print(f"[{time.strftime('%H:%M:%S')}] Gespeicherte TAID geladen: {taid}", flush=True)
            return taid
    except Exception:
        pass
    return None


def _save_taid(taid_header):
    """TAID für nächsten Start speichern."""
    try:
        val = re.sub(r'TAID=[""]?([^";\s]+)[""]?.*', r'\1', taid_header)
        with open(TAID_FILE, "w") as f:
            f.write(val)
    except Exception:
        pass


def _blnet_get_raw(path):
    """Interne HTTP-GET-Funktion (ohne Lock). Gibt (ok, text, session_error) zurück."""
    try:
        r = _session.get(f"{BLNET_URL}{path}", timeout=REQUEST_TIMEOUT)
        if "verweigert" in r.text:
            print(f"[{time.strftime('%H:%M:%S')}] VERWEIGERT bei {path}", flush=True)
            return False, r.text, True
        return True, r.text, False
    except requests.exceptions.ConnectionError as e:
        print(f"[{time.strftime('%H:%M:%S')}] ConnectionError bei {path}: {type(e).__name__}", flush=True)
        return False, "", True
    except Exception as e:
        print(f"[{time.strftime('%H:%M:%S')}] Exception bei {path}: {e}", flush=True)
        return False, str(e), False


def blnet_get(path):
    """GET mit Mutex-Schutz. Gibt (ok, text, session_error) zurück."""
    with _blnet_lock:
        return _blnet_get_raw(path)


def _login_raw():
    """Login ohne Lock (muss mit Lock aufgerufen werden). Gibt True bei Erfolg."""
    global _session_valid, _last_login_attempt
    try:
        r = _session.post(
            f"{BLNET_URL}/main.html",
            data={"blu": 1, "blp": BLNET_PASSWORD, "bll": "Login"},
            timeout=REQUEST_TIMEOUT
        )
        taid = r.headers.get("Set-Cookie")
        if taid:
            print(f"[{time.strftime('%H:%M:%S')}] Login OK — TAID: {taid}", flush=True)
            _save_taid(taid)
            _session_valid = True
            _last_login_attempt = 0
            return True
        else:
            print(f"[{time.strftime('%H:%M:%S')}] Login fehlgeschlagen (kein TAID) — {LOGIN_COOLDOWN}s Cooldown", flush=True)
            _session_valid = False
            return False
    except Exception as e:
        print(f"[{time.strftime('%H:%M:%S')}] Login-Fehler: {type(e).__name__} — {LOGIN_COOLDOWN}s Cooldown", flush=True)
        _session_valid = False
        return False


def ensure_logged_in():
    """Stellt sicher dass wir eingeloggt sind. Gibt True zurück wenn OK.
    Muss mit _blnet_lock aufgerufen werden."""
    global _session_valid, _last_login_attempt

    if _session_valid:
        return True

    elapsed = time.time() - _last_login_attempt
    if _last_login_attempt > 0 and elapsed < LOGIN_COOLDOWN:
        wait = int(LOGIN_COOLDOWN - elapsed)
        print(f"[{time.strftime('%H:%M:%S')}] Login-Cooldown: noch {wait}s warten", flush=True)
        return False

    _last_login_attempt = time.time()
    return _login_raw()


def parse_aktueller_wert(html):
    """'aktueller Wert: X' aus BL-Net Seite parsen."""
    html = html.replace("&deg;", "°").replace("&nbsp;", " ")
    m = re.search(r'aktueller Wert:\s*([^\s<]{1,20}(?:\s+[°%CkWhWlminAV][^<\s]{0,10})?)', html)
    return m.group(1).strip() if m else None


def read_all_data():
    """Alle Daten lesen — benötigt und hält _blnet_lock für die gesamte Dauer.
    Liest UVR1611 (CAN-Knoten 1) digitale Ausgangszustände."""
    global _session_valid

    result = {
        "timestamp": time.time(),
        "timestamp_human": time.strftime("%Y-%m-%d %H:%M:%S"),
        "sensors": {},
        "switches": {},
        "error": None
    }

    with _blnet_lock:
        if not ensure_logged_in():
            result["error"] = "Nicht eingeloggt — warte auf Cooldown"
            return result

        # Digitale Ausgänge des UVR1611 (CAN-Knoten 1) über d_ein lesen
        for i in range(1, 17):
            ok, html, sess_err = _blnet_get_raw(f"/d_ein.htm?blaE={i}&blaF=1")
            if not ok:
                if sess_err:
                    _session_valid = False
                    result["error"] = "Session abgelaufen"
                    print(f"[{time.strftime('%H:%M:%S')}] Session abgelaufen bei digital {i}", flush=True)
                    return result
                continue
            wert = parse_aktueller_wert(html)
            if wert in ("AN", "AUS"):
                result["switches"][f"digital_{i:02d}"] = {
                    "name": f"Ausgang {i}",
                    "state": "on" if wert == "AN" else "off",
                    "entity_id": f"binary_sensor.blnet_ausgang_{i:02d}"
                }
            time.sleep(0.1)

    print(f"[{time.strftime('%H:%M:%S')}] Sensoren: {len(result['sensors'])}, "
          f"Schalter: {len(result['switches'])}", flush=True)
    return result


def switch_output(output_num, state):
    """Ausgang schalten. Bei Session-Fehler: einmalig neu einloggen und nochmal."""
    global _session_valid

    bla_s = "1" if state == "on" else "0"
    path = f"/d_aus.htm?bldA={output_num}&blaS={bla_s}"

    with _blnet_lock:
        for attempt in range(2):
            if not ensure_logged_in():
                return {"success": False, "error": "Nicht eingeloggt — Login-Cooldown"}

            ok, html, sess_err = _blnet_get_raw(path)
            if ok:
                print(f"[{time.strftime('%H:%M:%S')}] Ausgang {output_num} -> {state.upper()}", flush=True)
                return {"success": True, "output": output_num, "state": state}

            if sess_err:
                _session_valid = False
                if attempt == 0:
                    print(f"[{time.strftime('%H:%M:%S')}] Session abgelaufen beim Schalten, Re-Login...", flush=True)
                    continue
                return {"success": False, "error": "Session abgelaufen nach Re-Login"}
            else:
                return {"success": False, "error": f"BL-Net Fehler"}

    return {"success": False, "error": "Unbekannter Fehler"}


def keepalive_loop():
    """Sendet alle 20s einen minimalen Request um die Session am Leben zu halten."""
    global _session_valid
    while True:
        time.sleep(KEEPALIVE_INTERVAL)
        if not _session_valid:
            continue
        # Warte auf Lock (poll_loop könnte gerade lesen)
        ok, _, sess_err = blnet_get("/a_ein.htm?blaE=1")
        if not ok and sess_err:
            _session_valid = False
            print(f"[{time.strftime('%H:%M:%S')}] Keepalive: Session abgelaufen", flush=True)


# Cache
_cache = {"data": None, "last_update": 0}
_cache_lock = threading.Lock()


def poll_loop():
    while True:
        time.sleep(POLL_INTERVAL)  # Erst schlafen, dann lesen (Startup hat schon gelesen)
        try:
            data = read_all_data()
            with _cache_lock:
                _cache["data"] = data
                _cache["last_update"] = time.time()
        except Exception as e:
            print(f"Poll-Fehler: {e}", flush=True)


class ProxyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/blnet":
            with _cache_lock:
                data = _cache["data"] or {"error": "Noch keine Daten"}
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(data, ensure_ascii=False, indent=2).encode())
        elif self.path.startswith("/blnet/raw?path="):
            # Diagnose: beliebige BL-Net Seite über Proxy lesen
            from urllib.parse import unquote
            blpath = unquote(self.path[len("/blnet/raw?path="):])
            ok, html, _ = blnet_get(blpath)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=iso-8859-1")
            self.end_headers()
            self.wfile.write(html.encode("iso-8859-1", errors="replace"))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == "/blnet/switch":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            try:
                payload = json.loads(body)
                output = int(payload.get("output", 7))
                state = payload.get("state", "off")
                if state not in ("on", "off"):
                    raise ValueError(f"Ungültiger state: {state}")
                result = switch_output(output, state)
            except Exception as e:
                result = {"success": False, "error": str(e)}
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(result).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass


if __name__ == "__main__":
    print(f"BL-Net Proxy startet (Port {PROXY_PORT})", flush=True)
    print(f"BL-Net: {BLNET_URL}, Intervall: {POLL_INTERVAL}s, Keepalive: {KEEPALIVE_INTERVAL}s", flush=True)

    # Beim Start: keine alte TAID laden — immer frisch einloggen.
    # Alte Session vom vorherigen Proxy-Lauf kann noch 30s aktiv sein.
    # Wir warten 35s damit die alte Session definitiv abläuft, dann loggen wir ein.
    print(f"[{time.strftime('%H:%M:%S')}] Warte 60s (alte Session ablaufen lassen)...", flush=True)
    time.sleep(60)

    # Erster Datenabruf (beinhaltet Login)
    data = read_all_data()
    with _cache_lock:
        _cache["data"] = data

    # Keepalive-Thread
    ka = threading.Thread(target=keepalive_loop, daemon=True)
    ka.start()

    # Poll-Thread
    t = threading.Thread(target=poll_loop, daemon=True)
    t.start()

    server = HTTPServer(("0.0.0.0", PROXY_PORT), ProxyHandler)
    print(f"API bereit: http://localhost:{PROXY_PORT}/blnet", flush=True)
    server.serve_forever()
