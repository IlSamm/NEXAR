"""NEXAR da altri dispositivi (Mac) passando da Umbrel + Tailscale.

- Il PC ascolta anche sulla rete di casa (porta GATEWAY_PORT) ma accetta SOLO l'indirizzo di Umbrel;
  tutto ciò che arriva da lì vale come "da Internet": serve la chiave o un dispositivo collegato, e le
  operazioni da PC (installazioni, PIN, ...) restano bloccate.
- I dispositivi si collegano una volta con un codice di 8 caratteri generato sul PC (10 minuti, un solo uso).
  Sul PC si salva solo l'impronta del token, e ogni dispositivo si può togliere.
"""
import hashlib
import hmac
import ipaddress
import secrets
import socket
import time
from datetime import datetime

GATEWAY_PORT = 8767       # il PC, verso Umbrel
UMBREL_PORT = 8790        # il ponte su Umbrel, verso il Mac
UMBREL_APP_PORT = 8792    # l'app NEXAR installata dallo store di Umbrel
CODE_TTL = 600
CODE_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'   # niente 0/O e 1/I
MAX_DEVICES = 10
FIREWALL_RULE = 'NEXAR - ponte Umbrel'


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def valid_lan_ip(ip: str) -> bool:
    try: a = ipaddress.ip_address(str(ip).strip())
    except ValueError: return False
    return a.version == 4 and a.is_private and not a.is_loopback and not a.is_link_local


def guess_umbrel() -> str:
    """umbrel.local risponde in casa (mDNS): così l'indirizzo è già scritto."""
    try:
        ip = socket.gethostbyname('umbrel.local')
        return ip if valid_lan_ip(ip) else ''
    except OSError: return ''


def firewall_script(exe: str, umbrel_ip: str) -> str:
    q = lambda s: "'" + str(s).replace("'", "''") + "'"
    return (f"Remove-NetFirewallRule -DisplayName {q(FIREWALL_RULE)} -ErrorAction SilentlyContinue;"
            f"New-NetFirewallRule -DisplayName {q(FIREWALL_RULE)} -Direction Inbound -Action Allow -Protocol TCP "
            f"-LocalPort {GATEWAY_PORT} -RemoteAddress {q(umbrel_ip)} -Program {q(exe)} -Profile Any | Out-Null;")


class Bridge:
    """Secondo server sulla rete di casa, acceso solo quando il ponte è attivo (come quello del tunnel)."""
    def __init__(self, get_cfg, app, port=GATEWAY_PORT, host='0.0.0.0'):
        self.get_cfg, self.app, self.port, self.host = get_cfg, app, port, host
        self.server = None
        self.thread = None
        self.error = ''

    def wanted(self):
        c = self.get_cfg() or {}
        return bool(c.get('enabled') and valid_lan_ip(c.get('umbrel_ip', '')))

    def running(self):
        return bool(self.server and self.thread and self.thread.is_alive() and self.server.started)

    def start(self):
        import threading, uvicorn
        self.server = uvicorn.Server(uvicorn.Config(self.app, host=self.host, port=self.port, access_log=False,
                                                   log_level='error', log_config=None, lifespan='off'))
        self.thread = threading.Thread(target=self.server.run, daemon=True, name='umbrel-bridge')
        self.thread.start()

    def stop(self):
        if self.server: self.server.should_exit = True
        if self.thread: self.thread.join(5)
        self.server = self.thread = None

    def run(self, stop):
        while not stop.is_set():
            try:
                if self.wanted() and not self.running():
                    if self.thread and not self.thread.is_alive():
                        self.error = f'porta {self.port} occupata da un altro programma'; self.server = self.thread = None
                        stop.wait(30)
                    self.start()
                    stop.wait(3)
                    if self.running(): self.error = ''
                elif not self.wanted() and self.server:
                    self.stop()
            except Exception as ex:
                self.error = str(ex)[:120]
            stop.wait(5)
        self.stop()

    def info(self):
        return {'running': self.running(), 'error': self.error}


class Devices:
    """Codici di collegamento e dispositivi collegati (in config['devices'])."""
    def __init__(self, config, save, clock=time.time):
        self.config, self.save, self.clock = config, save, clock
        self.code = None          # (impronta, scadenza)
        self.seen = {}

    def list(self):
        return [{k: d.get(k) for k in ('id', 'name', 'added')} | {'last': self.seen.get(d['id']) or d.get('last')}
                for d in self.config.get('devices') or []]

    def new_code(self):
        raw = ''.join(secrets.choice(CODE_ALPHABET) for _ in range(8))
        self.code = (_hash(raw), self.clock() + CODE_TTL)
        return raw[:4] + '-' + raw[4:], CODE_TTL

    def pair(self, code, name):
        clean = ''.join(ch for ch in str(code or '').upper() if ch in CODE_ALPHABET)
        if not self.code or self.clock() > self.code[1]: raise PermissionError('Codice scaduto: generane uno nuovo sul PC')
        if len(clean) != 8 or not hmac.compare_digest(_hash(clean), self.code[0]): raise PermissionError('Codice sbagliato')
        self.code = None   # un solo uso
        devs = list(self.config.get('devices') or [])
        if len(devs) >= MAX_DEVICES: raise PermissionError(f'Al massimo {MAX_DEVICES} dispositivi: togline uno dal PC')
        token = secrets.token_urlsafe(36)
        name = (str(name or '').strip() or 'Dispositivo')[:40]
        devs.append({'id': secrets.token_hex(4), 'name': name, 'hash': _hash(token), 'added': datetime.now().isoformat(timespec='minutes')})
        self.config['devices'] = devs
        self.save()
        return token, name

    def issue(self, name, tag):
        """Token per un dispositivo che si collega senza codice a mano. Uno solo per ogni tag: rigenerarlo sostituisce il vecchio."""
        token = secrets.token_urlsafe(36)
        devs = [d for d in self.config.get('devices') or [] if d.get('tag') != tag]
        devs.append({'id': secrets.token_hex(4), 'name': name[:40], 'tag': tag, 'hash': _hash(token), 'added': datetime.now().isoformat(timespec='minutes')})
        self.config['devices'] = devs
        self.save()
        return token

    def check(self, token) -> bool:
        if not token or len(token) < 40: return False
        h = _hash(token)
        for d in self.config.get('devices') or []:
            if hmac.compare_digest(h, d.get('hash', '')):
                self.seen[d['id']] = datetime.now().isoformat(timespec='minutes')
                return True
        return False

    def remove(self, dev_id):
        devs = [d for d in self.config.get('devices') or [] if d.get('id') != dev_id]
        if len(devs) == len(self.config.get('devices') or []): raise ValueError('Dispositivo non trovato')
        self.config['devices'] = devs
        self.save()
