#!/usr/bin/env python3
"""NEXAR su Umbrel. Solo libreria standard: gira sull'immagine python:alpine.

Due ruoli dello stesso file:
- "web":   la pagina dell'app, dietro al login di Umbrel. Apre la dashboard del PC (aggiunge lei il token) e,
           se il PC è spento, mostra il pulsante di accensione.
- "waker": sulla rete di casa, sempre acceso. Sveglia il PC (Wake-on-LAN) quando lo chiede l'app per Mac, il link
           del telefono, il bot Telegram o la pagina web.
"""
import base64
import hashlib
import hmac
import http.client
import http.server
import ipaddress
import json
import os
import re
import socket
import socketserver
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

DATA = os.environ.get('NEXAR_DATA', '/data')
CFG = os.path.join(DATA, 'config.json')
HERE = os.path.dirname(os.path.abspath(__file__))
WEB_PORT = int(os.environ.get('NEXAR_WEB_PORT', '8793'))
WAKER_PORT = int(os.environ.get('NEXAR_WAKER_PORT', '8794'))
WAKER_BIND = os.environ.get('NEXAR_WAKER_BIND', '172.17.0.1')          # solo verso i contenitori, mai sulla rete di casa
WAKER_HOST = os.environ.get('NEXAR_WAKER_HOST', 'host.docker.internal')
NTFY = os.environ.get('NEXAR_NTFY', 'https://ntfy.sh')
UA = {'User-Agent': 'NEXAR-Umbrel'}
MAC_RE = re.compile(r'^([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}$')
HOP = {'connection', 'keep-alive', 'proxy-authenticate', 'proxy-authorization', 'te', 'trailers', 'transfer-encoding', 'upgrade', 'host',
       'content-length', 'accept-encoding'}
MAX_BODY = 512 * 1024 * 1024


# ---------- configurazione ----------
def load():
    try:
        with open(CFG, encoding='utf-8') as f: return json.load(f)
    except (OSError, ValueError): return None


def save(cfg):
    os.makedirs(DATA, exist_ok=True)
    tmp = CFG + '.tmp'
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as f: json.dump(cfg, f)
    os.replace(tmp, CFG)


def forget():
    try: os.remove(CFG)
    except OSError: pass


def valid_ip(ip):
    try: a = ipaddress.ip_address(str(ip))
    except ValueError: return False
    return a.version == 4 and a.is_private and not a.is_loopback and not a.is_link_local


def parse_code(code):
    """Il codice generato da NEXAR sul PC. ValueError con un messaggio per chi lo incolla."""
    text = re.sub(r'\s', '', str(code or ''))
    if text.startswith('#pair='): text = text[6:]
    if not text.startswith('NEXAR1.'): raise ValueError('Codice non valido: copialo da NEXAR sul PC (Accensione → Collega Umbrel)')
    raw = text[7:]
    try: d = json.loads(base64.urlsafe_b64decode(raw + '=' * (-len(raw) % 4)))
    except ValueError: raise ValueError('Codice incompleto: copialo di nuovo') from None
    if not isinstance(d, dict): raise ValueError('Codice non valido')
    if not MAC_RE.match(str(d.get('pc_mac', ''))) or not valid_ip(d.get('pc_ip')): raise ValueError('Il codice non contiene i dati di rete del PC')
    if not d.get('wake_secret') or not d.get('token'): raise ValueError('Codice non valido')
    return {'name': str(d.get('name') or 'PC')[:60], 'pc_ip': d['pc_ip'], 'pc_mac': d['pc_mac'], 'broadcast': str(d.get('broadcast') or '255.255.255.255'),
            'pc_port': int(d.get('pc_port') or 8767), 'wake_secret': str(d['wake_secret']), 'token': str(d['token']),
            'bot_token': str(d.get('bot_token') or ''), 'user_id': int(d.get('user_id') or 0), 'paired_at': int(time.time())}


# ---------- cifratura del canale (uguale a beacon.py) ----------
def _d(s, l): return hmac.new(s.encode(), l.encode(), hashlib.sha256).digest()
def topic(s): return 'nexar-' + _d(s, 'topic').hex()[:32]
def _ks(k, n, size): return b''.join(hmac.new(k, n + i.to_bytes(4, 'big'), hashlib.sha256).digest() for i in range((size + 31) // 32))


def seal(s, o):
    d = json.dumps(o, separators=(',', ':')).encode(); n = os.urandom(16)
    c = bytes(a ^ b for a, b in zip(d, _ks(_d(s, 'enc'), n, len(d))))
    return base64.urlsafe_b64encode(n + c + hmac.new(_d(s, 'mac'), n + c, hashlib.sha256).digest()[:16]).decode().rstrip('=')


def unseal(s, t):
    try: raw = base64.urlsafe_b64decode(t + '=' * (-len(t) % 4))
    except (ValueError, TypeError): return None
    if len(raw) < 33: return None
    n, c, tag = raw[:16], raw[16:-16], raw[-16:]
    if not hmac.compare_digest(tag, hmac.new(_d(s, 'mac'), n + c, hashlib.sha256).digest()[:16]): return None
    try: return json.loads(bytes(a ^ b for a, b in zip(c, _ks(_d(s, 'enc'), n, len(c)))))
    except ValueError: return None


def fresh(p, last, now):
    t = p.get('wake', 0) if isinstance(p, dict) else 0
    return isinstance(t, (int, float)) and t > last and abs(now - t) < 180


def link_ok(ev, last, now):
    # Link del telefono: basta aprirlo. Vale solo se appena inviato, al massimo uno ogni 20 s.
    t = ev.get('time', 0)
    return isinstance(t, (int, float)) and abs(now - t) < 120 and now - last >= 20


# ---------- PC: acceso? svegliati ----------
def quiet(*a):
    try: return subprocess.call(list(a), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=8) == 0
    except (OSError, subprocess.TimeoutExpired): return False


def alive(ip):
    # Windows spesso blocca il ping: l'ARP invece risponde sempre quando il PC è acceso.
    if not ip: return False
    if quiet('ping', '-c', '1', '-W', '1', ip): return True
    try: dev = subprocess.check_output(['ip', 'route', 'get', ip], text=True, timeout=5).split(' dev ')[1].split()[0]
    except (OSError, IndexError, subprocess.SubprocessError): return False
    return quiet('arping', '-c', '2', '-w', '3', '-I', dev, ip)


def magic(mac): return b'\xff' * 6 + bytes.fromhex(re.sub('[:-]', '', mac)) * 16


def send_wake(cfg):
    pkt = magic(cfg['pc_mac'])
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for _ in range(3):
            for dst in dict.fromkeys((cfg.get('broadcast') or '255.255.255.255', '255.255.255.255')):
                for port in (9, 7): s.sendto(pkt, (dst, port))
            time.sleep(0.3)


# ---------- waker: sempre acceso sulla rete di casa ----------
class Waker:
    def __init__(self):
        self.last_page = 0.0

    def tg(self, cfg, method, **params):
        if not cfg.get('bot_token'): return None
        body = urllib.parse.urlencode({k: (json.dumps(v) if isinstance(v, (dict, list)) else v) for k, v in params.items()}).encode()
        with urllib.request.urlopen('https://api.telegram.org/bot' + cfg['bot_token'] + '/' + method, body, timeout=40) as r:
            return json.load(r).get('result')

    def tell(self, cfg, text):
        try: self.tg(cfg, 'sendMessage', chat_id=cfg.get('user_id'), text=text)
        except Exception: pass

    def channels(self):
        """Mac e link del telefono: la richiesta arriva cifrata su ntfy, quindi funziona da qualunque rete."""
        last, last_link = time.time() - 60, 0.0
        while True:
            cfg = load()
            if not cfg: time.sleep(5); continue
            ws = cfg['wake_secret']; sec, link = 'wake:' + ws, topic('link:' + ws)
            try:
                req = urllib.request.Request(NTFY + '/' + topic(sec) + ',' + link + '/json', headers=UA)
                with urllib.request.urlopen(req, timeout=120) as r:
                    for line in r:
                        cur = load()
                        if not cur or cur['wake_secret'] != ws: break
                        ev = json.loads(line)
                        if ev.get('event') != 'message': continue
                        now = time.time()
                        if ev.get('topic') == link:
                            if not link_ok(ev, last_link, now): continue
                            last_link = now; on = alive(cur['pc_ip'])
                            if not on: send_wake(cur)
                            self.tell(cur, '⏻ Accensione chiesta dal link del telefono.' if not on else "💻 Il link del telefono ha chiesto l'accensione, ma il PC è già acceso.")
                            continue
                        p = unseal(sec, ev.get('message', ''))
                        if not fresh(p, last, now): continue
                        last = p['wake']; on = alive(cur['pc_ip'])
                        if not on: send_wake(cur)
                        ack = urllib.request.Request(NTFY + '/' + topic('ack:' + ws), data=seal('ack:' + ws, {'ack': last, 'on': on}).encode(), headers={**UA, 'Firebase': 'no'})
                        urllib.request.urlopen(ack, timeout=10).read()
                        self.tell(cur, "⏻ Accensione chiesta dall'app NEXAR per Mac." if not on else "💻 L'app per Mac ha chiesto l'accensione, ma il PC è già acceso.")
            except Exception:
                time.sleep(10)

    def follow(self):
        """Se il router dà un altro indirizzo al PC, NEXAR lo pubblica cifrato e qui si aggiorna da solo."""
        while True:
            time.sleep(300)
            cfg = load()
            if not cfg: continue
            try:
                s = cfg['wake_secret']
                req = urllib.request.Request(NTFY + '/' + topic(s) + '/json?poll=1&since=12h', headers=UA)
                with urllib.request.urlopen(req, timeout=20) as r: lines = r.read().decode().splitlines()
                info = None
                for line in lines:
                    got = unseal(s, json.loads(line).get('message', ''))
                    if got: info = got
                if not info: continue
                ch = {}
                if valid_ip(info.get('ip')) and info['ip'] != cfg['pc_ip']: ch['pc_ip'] = info['ip']
                if MAC_RE.match(str(info.get('mac', ''))) and info['mac'] != cfg['pc_mac']: ch['pc_mac'] = info['mac']
                if ch and load() == cfg: save({**cfg, **ch}); print('Indirizzi del PC aggiornati', flush=True)
            except Exception:
                pass

    def telegram(self):
        """Con il PC spento risponde qui il bot; col PC acceso lo gestisce NEXAR, così non si contendono i messaggi."""
        offset = None
        kb = {'inline_keyboard': [[{'text': '⏻ Accendi il PC', 'callback_data': 'wake'}]]}
        while True:
            cfg = load()
            if not cfg or not cfg.get('bot_token'): time.sleep(30); continue
            try:
                if alive(cfg['pc_ip']):
                    offset = None; time.sleep(15); continue
                for ev in self.tg(cfg, 'getUpdates', offset=offset or 0, timeout=20, allowed_updates=['message', 'callback_query']) or []:
                    offset = ev['update_id'] + 1
                    cb = ev.get('callback_query'); msg = ev.get('message') or (cb or {}).get('message') or {}
                    who = (cb or msg).get('from', {}).get('id'); text = (cb or {}).get('data') or msg.get('text', '')
                    if cb: self.tg(cfg, 'answerCallbackQuery', callback_query_id=cb['id'])
                    if who != cfg.get('user_id') or (not cb and time.time() - msg.get('date', 0) > 300): continue
                    if text.split('@')[0] in ('/accendi', 'wake', '/wake'):
                        send_wake(cfg); self.tell(cfg, '⏻ Segnale di accensione inviato. Ti scrivo appena il PC risponde.')
                        for _ in range(36):
                            time.sleep(5)
                            if alive(cfg['pc_ip']): self.tell(cfg, '🟢 PC acceso. Tra poco NEXAR riprende il controllo.'); break
                        else: self.tell(cfg, '⚠️ Il PC non risponde. Controlla nel BIOS Wake on LAN / ErP disattivato.')
                    else:
                        self.tg(cfg, 'sendMessage', chat_id=cfg.get('user_id'), text='🔴 Il PC è spento.', reply_markup=kb)
            except Exception:
                time.sleep(10)

    def page_wake(self):
        cfg = load()
        if not cfg: return False
        if time.time() - self.last_page > 20:
            self.last_page = time.time(); send_wake(cfg)
        return True

    def serve(self):
        waker = self
        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a): pass
            def reply(self, obj, code=200):
                body = json.dumps(obj).encode()
                self.send_response(code); self.send_header('Content-Type', 'application/json'); self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)
            def do_GET(self):
                cfg = load()
                self.reply({'pc': bool(cfg and alive(cfg['pc_ip']))} if self.path == '/status' else {}, 200 if self.path == '/status' else 404)
            def do_POST(self):
                if self.path != '/wake': return self.reply({}, 404)
                self.reply({'ok': waker.page_wake()})
        while True:
            try: srv = Server((WAKER_BIND, WAKER_PORT), H); break
            except OSError as ex:
                print('Porta interna non disponibile, riprovo:', ex, flush=True); time.sleep(5)
        srv.serve_forever()

    def run(self):
        for fn in (self.channels, self.follow, self.telegram):
            threading.Thread(target=fn, daemon=True).start()
        print('NEXAR waker attivo', flush=True)
        self.serve()


# ---------- web: dietro al login di Umbrel ----------
class Limited:
    """Corpo della richiesta inoltrato a pezzi, senza leggere oltre la sua lunghezza."""
    def __init__(self, f, size): self.f, self.left = f, size
    def read(self, n=-1):
        if self.left <= 0: return b''
        n = self.left if n < 0 else min(n, self.left)
        data = self.f.read(n); self.left -= len(data)
        return data


def waker_call(method, path):
    c = http.client.HTTPConnection(WAKER_HOST, WAKER_PORT, timeout=12)
    try:
        c.request(method, path); r = c.getresponse()
        return json.loads(r.read() or b'{}')
    finally: c.close()


def app_up(cfg):
    try:
        with socket.create_connection((cfg['pc_ip'], cfg['pc_port']), 1.5): return True
    except OSError: return False


PAGE = open(os.path.join(HERE, 'page.html'), encoding='utf-8').read().encode() if os.path.exists(os.path.join(HERE, 'page.html')) else b'NEXAR'


class Web(http.server.BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    timeout = 120

    def log_message(self, *a): pass

    def out(self, code, body, ctype, cache='no-store'):
        self.send_response(code); self.send_header('Content-Type', ctype); self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', cache); self.end_headers()
        if self.command != 'HEAD': self.wfile.write(body)

    def json(self, obj, code=200): self.out(code, json.dumps(obj).encode(), 'application/json')

    def body(self, limit=16384):
        size = int(self.headers.get('Content-Length') or 0)
        if size > limit: raise ValueError('Dati troppo lunghi')
        return self.rfile.read(size) if size else b''

    def own(self, path, cfg):
        """Le pagine e i comandi dell'app stessa. True se la richiesta è stata gestita."""
        if path == '/__nexar/status':
            up = bool(cfg and app_up(cfg))
            pc = up
            if cfg and not up:
                try: pc = bool(waker_call('GET', '/status').get('pc'))
                except Exception: pc = False
            self.json({'paired': bool(cfg), 'app': up, 'pc': pc, 'name': (cfg or {}).get('name', ''), 'telegram': bool((cfg or {}).get('bot_token'))})
        elif path == '/__nexar/proxy.js':
            self.out(200, b'window.NEXAR_PROXY=1;\n', 'text/javascript')
        elif path == '/__nexar/icon.png':
            try:
                with open(os.path.join(HERE, 'icon.png'), 'rb') as f: self.out(200, f.read(), 'image/png', 'max-age=86400')
            except OSError: self.out(404, b'', 'image/png')
        elif path == '/__nexar/pair' and self.command == 'POST':
            try:
                code = json.loads(self.body() or b'{}').get('code')
                new = parse_code(code)
            except ValueError as ex: return self.json({'detail': str(ex)}, 400) or True
            save(new)
            self.json({'ok': True, 'name': new['name']})
        elif path == '/__nexar/unpair' and self.command == 'POST':
            forget(); self.json({'ok': True})
        elif path == '/__nexar/wake' and self.command == 'POST':
            if not cfg: return self.json({'detail': 'Collega prima il PC'}, 400) or True
            try: self.json({'ok': bool(waker_call('POST', '/wake').get('ok'))})
            except Exception: self.json({'detail': 'Servizio di accensione non attivo: riavvia NEXAR su Umbrel'}, 502)
        elif path == '/__nexar/setup':
            self.out(200, PAGE, 'text/html; charset=utf-8')
        else:
            return False
        return True

    def down(self, path):
        if path.startswith('/api/'): return self.json({'detail': 'Il PC è spento o NEXAR non è aperto', 'off': True}, 503)
        self.out(503, PAGE, 'text/html; charset=utf-8')

    def proxy(self, cfg):
        size = int(self.headers.get('Content-Length') or 0)
        if size > MAX_BODY: return self.json({'detail': 'File troppo grande'}, 413)
        head = {k: v for k, v in self.headers.items() if k.lower() not in HOP and k.lower() != 'x-pc-eco-key'}
        head['Host'] = f"{cfg['pc_ip']}:{cfg['pc_port']}"
        head['X-PC-ECO-Key'] = cfg['token']
        if size: head['Content-Length'] = str(size)
        stream = self.path.startswith('/api/remote/stream')
        c = http.client.HTTPConnection(cfg['pc_ip'], cfg['pc_port'], timeout=70 if stream else 60)
        try:
            try:
                c.request(self.command, self.path, body=Limited(self.rfile, size) if size else None, headers=head, encode_chunked=False)
                r = c.getresponse()
            except OSError:
                self.close_connection = True
                return self.down(self.path.split('?')[0])
            ctype = r.getheader('Content-Type', '')
            if ctype.startswith('text/html'):
                data = r.read().replace(b'<head>', b'<head><script src="/__nexar/proxy.js"></script>', 1)
                self.send_response(r.status)
                for k, v in r.getheaders():
                    if k.lower() not in HOP: self.send_header(k, v)
                self.send_header('Content-Length', str(len(data))); self.end_headers()
                if self.command != 'HEAD': self.wfile.write(data)
                return
            self.send_response(r.status)
            for k, v in r.getheaders():
                if k.lower() not in HOP: self.send_header(k, v)
            length = r.getheader('Content-Length')
            chunked = length is None and r.status not in (204, 304) and self.command != 'HEAD'
            if length is not None: self.send_header('Content-Length', length)
            elif chunked: self.send_header('Transfer-Encoding', 'chunked')
            else: self.send_header('Content-Length', '0')
            self.end_headers()
            if self.command == 'HEAD': return
            try:
                while True:
                    # read1: consegna subito ciò che è arrivato, altrimenti il flusso dello schermo si fermerebbe qui
                    piece = r.read1(65536)
                    if not piece: break
                    if chunked: self.wfile.write(b'%x\r\n' % len(piece) + piece + b'\r\n')
                    else: self.wfile.write(piece)
                    self.wfile.flush()
                if chunked: self.wfile.write(b'0\r\n\r\n')
            except (OSError, http.client.HTTPException):
                self.close_connection = True        # il PC o il browser hanno chiuso: la dashboard si ricollega
        finally:
            c.close()

    def any(self):
        path = self.path.split('?')[0]
        cfg = load()
        if path.startswith('/__nexar/') and self.own(path, cfg): return
        if not cfg:
            if path.startswith('/api/'): return self.json({'detail': 'Collega prima il PC', 'off': True}, 503)
            return self.out(200, PAGE, 'text/html; charset=utf-8')
        self.proxy(cfg)

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = any


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main():
    role = sys.argv[1] if len(sys.argv) > 1 else 'web'
    os.makedirs(DATA, exist_ok=True)
    if role == 'waker': return Waker().run()
    print('NEXAR web sulla porta', WEB_PORT, flush=True)
    Server(('0.0.0.0', WEB_PORT), Web).serve_forever()


if __name__ == '__main__':
    main()
