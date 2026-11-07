"""Accensione e spegnimento del PC: comandi di Windows, Wake-on-LAN e relay di accensione per Umbrel."""
from __future__ import annotations
import ctypes
import json
import os
import re
import socket
import subprocess
import threading
import time

ACTIONS = {'shutdown': 'Spegnimento', 'restart': 'Riavvio', 'sleep': 'Sospensione', 'hibernate': 'Ibernazione', 'lock': 'Blocco schermo'}
GRACE_SECONDS = 30   # Windows mostra l'avviso e si può ancora annullare
MAC = re.compile(r'^([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}$')

def _run(args):
    opts = dict(capture_output=True, text=True, errors='replace', timeout=15)
    if os.name == 'nt': opts['creationflags'] = subprocess.CREATE_NO_WINDOW
    r = subprocess.run(args, **opts)
    if r.returncode: raise RuntimeError((r.stderr or r.stdout or 'Comando non eseguito').strip()[:200])

def hibernate_available():
    if os.name != 'nt': return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'SYSTEM\CurrentControlSet\Control\Power') as k:
            return bool(winreg.QueryValueEx(k, 'HibernateEnabled')[0])
    except OSError: return False

def execute(kind):
    """Esegue subito l'azione. Spegnimento e riavvio lasciano 30 s di avviso annullabili."""
    if os.name != 'nt': raise RuntimeError('Disponibile solo su Windows')
    note = 'NEXAR: ' + ACTIONS[kind].lower() + ' richiesto da remoto.'
    if kind == 'shutdown': _run(['shutdown', '/s', '/t', str(GRACE_SECONDS), '/c', note])
    elif kind == 'restart': _run(['shutdown', '/r', '/t', str(GRACE_SECONDS), '/c', note])
    elif kind == 'lock': ctypes.windll.user32.LockWorkStation()
    elif kind in ('sleep', 'hibernate'):
        if kind == 'hibernate' and not hibernate_available(): raise RuntimeError('Ibernazione non attiva su questo PC')
        # Qualche secondo per rispondere a Telegram/dashboard prima che la rete si spenga.
        def later():
            time.sleep(4)
            ctypes.windll.powrprof.SetSuspendState(kind == 'hibernate', False, False)
        threading.Thread(target=later, daemon=True, name='suspend').start()
    else: raise ValueError('Azione non prevista')

def abort_windows_shutdown():
    try: _run(['shutdown', '/a']); return True
    except Exception: return False   # nessuno spegnimento di Windows in corso

def idle_seconds():
    """Secondi dall'ultimo uso di mouse o tastiera."""
    if os.name != 'nt': return 0
    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [('cbSize', ctypes.c_uint), ('dwTime', ctypes.c_uint)]
    info = LASTINPUTINFO(ctypes.sizeof(LASTINPUTINFO), 0)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)): return 0
    return max(0, (ctypes.windll.kernel32.GetTickCount() - info.dwTime) & 0xFFFFFFFF) / 1000

def magic_packet(mac: str) -> bytes:
    if not MAC.match(mac or ''): raise ValueError('Indirizzo MAC non valido')
    return b'\xff' * 6 + bytes.fromhex(re.sub('[:-]', '', mac)) * 16

def send_magic(mac, broadcast='255.255.255.255'):
    packet = magic_packet(mac)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for target in dict.fromkeys([broadcast, '255.255.255.255']):
            for port in (9, 7): s.sendto(packet, (target, port))

# ---------- relay per Umbrel (o qualsiasi computer di casa sempre acceso) ----------
# Ascolta il bot SOLO mentre il PC non risponde al ping: quando il PC è acceso il bot lo gestisce l'app,
# così non si contendono i messaggi. Solo libreria standard: gira sull'immagine python:alpine.
RELAY = r'''
import json, os, socket, subprocess, time, urllib.parse, urllib.request
T = os.environ["BOT_TOKEN"]; U = int(os.environ["USER_ID"]); MAC = os.environ["PC_MAC"]
IP = os.environ["PC_IP"]; BC = os.environ.get("BROADCAST", "255.255.255.255")
def api(m, **p):
    d = urllib.parse.urlencode({k: (json.dumps(v) if isinstance(v, (dict, list)) else v) for k, v in p.items()}).encode()
    with urllib.request.urlopen("https://api.telegram.org/bot" + T + "/" + m, d, timeout=40) as r:
        return json.load(r).get("result")
def quiet(*a):
    return subprocess.call(list(a), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0
def alive():
    # Windows spesso blocca il ping: l'ARP invece risponde sempre quando il PC è acceso.
    if quiet("ping", "-c", "1", "-W", "1", IP): return True
    try: dev = subprocess.check_output(["ip", "route", "get", IP], text=True).split(" dev ")[1].split()[0]
    except Exception: return False
    return quiet("arping", "-c", "2", "-w", "3", "-I", dev, IP)
def wake():
    pkt = b"\xff" * 6 + bytes.fromhex(MAC.replace(":", "").replace("-", "")) * 16
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    for _ in range(3):
        for dst in (BC, "255.255.255.255"): s.sendto(pkt, (dst, 9))
        time.sleep(0.3)
    s.close()
KB = {"inline_keyboard": [[{"text": "⏻ Accendi il PC", "callback_data": "wake"}]]}
# App NEXAR per Mac: chiede l'accensione su un canale ntfy cifrato (stesso formato di beacon.py).
import base64, hashlib, hmac, threading
WS = os.environ.get("WAKE_SECRET", ""); NTFY = "https://ntfy.sh"
def _d(s, l): return hmac.new(s.encode(), l.encode(), hashlib.sha256).digest()
def _topic(s): return "nexar-" + _d(s, "topic").hex()[:32]
def _ks(k, n, size): return b"".join(hmac.new(k, n + i.to_bytes(4, "big"), hashlib.sha256).digest() for i in range((size + 31) // 32))
def seal(s, o):
    d = json.dumps(o, separators=(",", ":")).encode(); n = os.urandom(16)
    c = bytes(a ^ b for a, b in zip(d, _ks(_d(s, "enc"), n, len(d))))
    return base64.urlsafe_b64encode(n + c + hmac.new(_d(s, "mac"), n + c, hashlib.sha256).digest()[:16]).decode().rstrip("=")
def unseal(s, t):
    try: raw = base64.urlsafe_b64decode(t + "=" * (-len(t) % 4))
    except Exception: return None
    if len(raw) < 33: return None
    n, c, tag = raw[:16], raw[16:-16], raw[-16:]
    if not hmac.compare_digest(tag, hmac.new(_d(s, "mac"), n + c, hashlib.sha256).digest()[:16]): return None
    try: return json.loads(bytes(a ^ b for a, b in zip(c, _ks(_d(s, "enc"), n, len(c)))))
    except Exception: return None
def fresh(p, last, now):
    t = p.get("wake", 0) if isinstance(p, dict) else 0
    return isinstance(t, (int, float)) and t > last and abs(now - t) < 180
def mac_wake():
    sec, last = "wake:" + WS, time.time() - 60
    while True:
        try:
            req = urllib.request.Request(NTFY + "/" + _topic(sec) + "/json", headers={"User-Agent": "NEXAR-Umbrel"})
            with urllib.request.urlopen(req, timeout=120) as r:
                for line in r:
                    ev = json.loads(line)
                    p = unseal(sec, ev.get("message", "")) if ev.get("event") == "message" else None
                    if not fresh(p, last, time.time()): continue
                    last = p["wake"]; on = alive()
                    if not on: wake()
                    ack = urllib.request.Request(NTFY + "/" + _topic("ack:" + WS), data=seal("ack:" + WS, {"ack": last, "on": on}).encode(), headers={"User-Agent": "NEXAR-Umbrel", "Firebase": "no"})
                    urllib.request.urlopen(ack, timeout=10).read()
                    try: api("sendMessage", chat_id=U, text="⏻ Accensione chiesta dall'app NEXAR per Mac." if not on else "💻 L'app per Mac ha chiesto l'accensione, ma il PC è già acceso.")
                    except Exception: pass
        except Exception:
            time.sleep(10)
if WS: threading.Thread(target=mac_wake, daemon=True).start()
offset = None
while True:
    try:
        if alive():
            offset = None; time.sleep(15); continue
        # Il PC conferma ogni comando ricevuto prima di spegnersi: qui arrivano solo messaggi nuovi.
        for ev in api("getUpdates", offset=offset or 0, timeout=20, allowed_updates=["message", "callback_query"]):
            offset = ev["update_id"] + 1
            cb = ev.get("callback_query"); msg = ev.get("message") or (cb or {}).get("message") or {}
            who = (cb or msg).get("from", {}).get("id"); text = (cb or {}).get("data") or msg.get("text", "")
            if cb: api("answerCallbackQuery", callback_query_id=cb["id"])
            if who != U or (not cb and time.time() - msg.get("date", 0) > 300): continue
            if text.split("@")[0] in ("/accendi", "wake", "/wake"):
                wake(); api("sendMessage", chat_id=U, text="⏻ Segnale di accensione inviato. Ti scrivo appena il PC risponde.")
                for _ in range(36):
                    time.sleep(5)
                    if alive():
                        api("sendMessage", chat_id=U, text="🟢 PC acceso. Tra poco NEXAR riprende il controllo."); break
                else: api("sendMessage", chat_id=U, text="⚠️ Il PC non risponde. Controlla nel BIOS Wake on LAN / ErP disattivato.")
            else:
                api("sendMessage", chat_id=U, text="🔴 Il PC è spento.", reply_markup=KB)
    except Exception:
        time.sleep(10)
'''

# ---------- ponte su Umbrel per il Mac (via Tailscale) ----------
# Il Mac apre http://umbrel:8790 (nome Tailscale di Umbrel): il ponte inoltra tutto al PC sulla rete di casa.
# Se il PC è spento risponde con una pagina "Accendi il PC" (Wake-on-LAN) e si ricarica da sola quando NEXAR torna.
# Accetta solo indirizzi Tailscale (100.64.0.0/10) e della rete di casa. Solo libreria standard.
BRIDGE = r'''
import http.client, http.server, ipaddress, json, os, socket, socketserver, subprocess, time
IP = os.environ["PC_IP"]; PORT = int(os.environ.get("PC_PORT", "8767")); MAC = os.environ.get("PC_MAC", "")
BC = os.environ.get("BROADCAST", "255.255.255.255"); LISTEN = int(os.environ.get("GW_PORT", "8790"))
NETS = [ipaddress.ip_network(n) for n in ("100.64.0.0/10", "127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fd7a:115c:a1e0::/48", "::1/128")]
HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailers", "transfer-encoding", "upgrade", "host", "content-length"}
LAST = [0.0]
def quiet(*a):
    return subprocess.call(list(a), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0
def app_up():
    try: socket.create_connection((IP, PORT), 1.5).close(); return True
    except OSError: return False
def pc_up():
    if quiet("ping", "-c", "1", "-W", "1", IP): return True
    try: dev = subprocess.check_output(["ip", "route", "get", IP], text=True).split(" dev ")[1].split()[0]
    except Exception: return False
    return quiet("arping", "-c", "2", "-w", "3", "-I", dev, IP)
def wake():
    pkt = b"\xff" * 6 + bytes.fromhex(MAC.replace(":", "").replace("-", "")) * 16
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    for _ in range(3):
        for dst in (BC, "255.255.255.255"): s.sendto(pkt, (dst, 9))
        time.sleep(0.3)
    s.close()
PAGE = """<!doctype html><html lang="it"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#090b0f"><title>NEXAR</title><style>
body{margin:0;min-height:100vh;display:grid;place-items:center;background:#090b0f;color:#e8edf5;font:16px -apple-system,system-ui,sans-serif}
main{text-align:center;padding:24px;max-width:360px}h1{font-size:28px;letter-spacing:.08em;margin:0 0 6px}h1 span{color:#38bdf8}
p{color:#94a3b8;line-height:1.5}button{margin-top:18px;border:0;border-radius:14px;padding:14px 26px;font:600 16px inherit;background:#22c55e;color:#04130a;cursor:pointer}
button:disabled{opacity:.5}.dot{display:inline-block;width:10px;height:10px;border-radius:50%;background:#ef4444;margin-right:8px}
</style></head><body><main><h1>NEX<span>AR</span></h1><p id="s"><i class="dot"></i>Controllo il PC…</p>
<button id="b" hidden>⏻ Accendi il PC</button><p id="n"></p></main><script>
var b=document.getElementById("b"),s=document.getElementById("s"),n=document.getElementById("n");
function st(){fetch("/__nexar/status").then(function(r){return r.json()}).then(function(j){
 if(j.app){location.reload();return}
 s.innerHTML='<i class="dot"></i>'+(j.pc?"Il PC è acceso ma NEXAR non risponde: aprilo sul PC.":"Il PC è spento.");
 b.hidden=j.pc||!j.wake}).catch(function(){s.textContent="Umbrel non risponde."})}
b.onclick=function(){b.disabled=true;n.textContent="Segnale inviato, attendo che il PC si accenda…";
 fetch("/__nexar/wake",{method:"POST"}).finally(function(){setTimeout(function(){b.disabled=false},20000)})};
st();setInterval(st,4000);
</script></body></html>""".encode()
class H(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self, *a): pass
    def allowed(self):
        try: a = ipaddress.ip_address(self.client_address[0])
        except ValueError: return False
        if a.version == 6 and a.ipv4_mapped: a = a.ipv4_mapped
        return any(a in n for n in NETS if n.version == a.version)
    def out(self, code, body, ctype):
        self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store"); self.end_headers()
        if self.command != "HEAD": self.wfile.write(body)
    def any(self):
        if not self.allowed(): return self.out(403, "Solo da Tailscale o dalla rete di casa".encode(), "text/plain; charset=utf-8")
        size = int(self.headers.get("Content-Length") or 0)
        if size > 8000000: return self.out(413, b"{}", "application/json")
        body = self.rfile.read(size) if size else None
        if self.path == "/__nexar/status":
            up = app_up()
            return self.out(200, json.dumps({"app": up, "pc": up or pc_up(), "wake": bool(MAC)}).encode(), "application/json")
        if self.path == "/__nexar/wake" and self.command == "POST":
            if not MAC: return self.out(400, b"{}", "application/json")
            if time.time() - LAST[0] > 20: LAST[0] = time.time(); wake()
            return self.out(200, b'{"ok":true}', "application/json")
        try:
            c = http.client.HTTPConnection(IP, PORT, timeout=30)
            head = {k: v for k, v in self.headers.items() if k.lower() not in HOP}
            head["Host"] = IP + ":" + str(PORT)
            c.request(self.command, self.path, body=body, headers=head)
            r = c.getresponse(); data = r.read(); c.close()
        except OSError:
            if self.path.startswith("/api/"):
                return self.out(503, json.dumps({"detail": "Il PC è spento o NEXAR non è aperto", "off": True}).encode(), "application/json")
            return self.out(503, PAGE, "text/html; charset=utf-8")
        self.send_response(r.status)
        for k, v in r.getheaders():
            if k.lower() not in HOP: self.send_header(k, v)
        self.send_header("Content-Length", str(len(data))); self.end_headers()
        if self.command != "HEAD": self.wfile.write(data)
    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = any
class S(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True; allow_reuse_address = True
if __name__ == "__main__":
    srv = S(("0.0.0.0", LISTEN), H)
    try: nets = subprocess.check_output(["ip", "-4", "-o", "addr"], text=True)
    except Exception: nets = "?"
    print("NEXAR ponte in ascolto sulla porta", LISTEN, "-> PC", IP + ":" + str(PORT), "| PC raggiungibile:", app_up(), flush=True)
    print("Reti viste dal ponte:", " ".join(l.split()[1] + "=" + l.split()[3] for l in nets.splitlines() if len(l.split()) > 3), flush=True)
    srv.serve_forever()
'''

def relay_compose(token, user_id, mac, ip, broadcast, bridge=None, wake_secret=''):
    """Stack per Umbrel: accensione da Telegram (se c'è il bot) e, se chiesto, il ponte per il Mac.
    bridge = {'pc_port': 8767, 'port': 8790}."""
    services = {}
    if token and user_id:
        magic_packet(mac)
        services['nexar-accensione'] = {
            'image': 'python:3.12-alpine', 'container_name': 'nexar-accensione', 'restart': 'unless-stopped',
            # La rete dell'host serve per il broadcast Wake-on-LAN nella rete di casa.
            'network_mode': 'host',
            'environment': {'BOT_TOKEN': token, 'USER_ID': str(user_id), 'PC_MAC': mac, 'PC_IP': ip, 'BROADCAST': broadcast,
                            **({'WAKE_SECRET': wake_secret} if wake_secret else {})},
            'command': ['python', '-u', '-c', RELAY.strip()],
        }
    if bridge is not None:
        if not ip: raise ValueError('Indirizzo del PC nella rete di casa non trovato: premi "Cerca di nuovo" in Collegamenti')
        if mac: magic_packet(mac)
        services['nexar-ponte'] = {
            'image': 'python:3.12-alpine', 'container_name': 'nexar-ponte', 'restart': 'unless-stopped',
            # Rete dell'host: Tailscale su Umbrel arriva direttamente qui, e il Wake-on-LAN esce in casa.
            'network_mode': 'host',
            'environment': {'PC_IP': ip, 'PC_PORT': str(bridge.get('pc_port', 8767)), 'PC_MAC': mac or '',
                            'BROADCAST': broadcast, 'GW_PORT': str(bridge.get('port', 8790))},
            'command': ['python', '-u', '-c', BRIDGE.strip()],
        }
    if not services: raise ValueError('Collega prima Telegram')
    # JSON è YAML valido; "$$" evita che Docker Compose interpreti eventuali "$".
    body = json.dumps({'services': services}, ensure_ascii=False, indent=2).replace('$', '$$')
    parts = [x for x, on in (('accensione da Telegram', 'nexar-accensione' in services), ('ponte per il Mac', 'nexar-ponte' in services)) if on]
    head = '# Stack Portainer/Umbrel per NEXAR: ' + ' + '.join(parts) + '.'
    if 'nexar-accensione' in services: head += ' Contiene il token del bot: non condividerlo.'
    return head + '\n' + body
