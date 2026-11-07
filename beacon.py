"""L'app NEXAR per Mac ritrova il PC ovunque sia.

L'indirizzo pubblico del PC (tunnel Cloudflare) cambia a ogni avvio di NEXAR. Il PC lo pubblica cifrato
su un canale segreto di ntfy.sh e l'app per Mac lo legge da lì:
- per il primo collegamento il canale e la chiave nascono dal codice di 8 caratteri (vale 10 minuti);
- dopo, il PC consegna all'app un segreto fisso, e l'indirizzo viene ripubblicato a ogni cambio e ogni 6 ore.
ntfy vede solo testo cifrato (HMAC-SHA256 come flusso + tag di autenticità). L'indirizzo da solo non basta:
per comandare il PC serve sempre il token del dispositivo collegato.
"""
from __future__ import annotations
import base64
import hashlib
import hmac
import json
import logging
import secrets
import threading
import time
import urllib.request

NTFY = 'https://ntfy.sh'
REPUBLISH = 6 * 3600          # ntfy tiene i messaggi 12 ore
CODE_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'


def _derive(secret: str, label: str) -> bytes:
    return hmac.new(secret.encode(), label.encode(), hashlib.sha256).digest()


def clean_code(code: str) -> str:
    return ''.join(ch for ch in str(code or '').upper() if ch in CODE_ALPHABET)


def pair_secret(code: str) -> str:
    return 'pair:' + clean_code(code)


def topic(secret: str) -> str:
    return 'nexar-' + _derive(secret, 'topic').hex()[:32]


def _stream(key: bytes, nonce: bytes, size: int) -> bytes:
    return b''.join(hmac.new(key, nonce + i.to_bytes(4, 'big'), hashlib.sha256).digest() for i in range((size + 31) // 32))


def seal(secret: str, obj: dict, nonce: bytes | None = None) -> str:
    data = json.dumps(obj, separators=(',', ':')).encode()
    nonce = nonce or secrets.token_bytes(16)
    ct = bytes(a ^ b for a, b in zip(data, _stream(_derive(secret, 'enc'), nonce, len(data))))
    tag = hmac.new(_derive(secret, 'mac'), nonce + ct, hashlib.sha256).digest()[:16]
    return base64.urlsafe_b64encode(nonce + ct + tag).decode().rstrip('=')


def unseal(secret: str, text: str) -> dict | None:
    try: raw = base64.urlsafe_b64decode(text + '=' * (-len(text) % 4))
    except (ValueError, TypeError): return None
    if len(raw) < 33: return None
    nonce, ct, tag = raw[:16], raw[16:-16], raw[-16:]
    if not hmac.compare_digest(tag, hmac.new(_derive(secret, 'mac'), nonce + ct, hashlib.sha256).digest()[:16]): return None
    try: return json.loads(bytes(a ^ b for a, b in zip(ct, _stream(_derive(secret, 'enc'), nonce, len(ct)))))
    except ValueError: return None


def _post(topic_name: str, message: str):
    req = urllib.request.Request(f'{NTFY}/{topic_name}', data=message.encode(), method='POST',
                                 headers={'Title': 'NEXAR', 'Firebase': 'no', 'User-Agent': 'NEXAR'})
    with urllib.request.urlopen(req, timeout=10) as r: r.read()


class Beacon:
    def __init__(self, config, save, get_url, info=lambda: {}, post=_post, clock=time.time):
        self.config, self.save, self.get_url, self.info, self.post, self.clock = config, save, get_url, info, post, clock
        self.kick = threading.Event()
        self.pending = None        # (codice pulito, scadenza)
        self.pending_sent = None   # (codice, indirizzo) già pubblicati
        self.sent = ('', 0.0)      # (indirizzo, quando)
        self.error = ''

    def secret(self) -> str:
        b = self.config.get('beacon') or {}
        if not b.get('secret'):
            b = {'secret': secrets.token_urlsafe(32)}
            self.config['beacon'] = b
            self.save()
        return b['secret']

    def code_waiting(self) -> bool:
        return bool(self.pending and self.clock() < self.pending[1])

    def wanted(self) -> bool:
        """Serve il tunnel: c'è un Mac collegato o un codice in attesa."""
        return bool(self.config.get('devices')) or self.code_waiting()

    def announce_code(self, code, ttl):
        self.pending = (clean_code(code), self.clock() + ttl)
        self.kick.set()

    def tick(self):
        url = self.get_url()
        if not url: return
        payload = {'url': url, 't': int(self.clock()), **self.info()}
        if self.code_waiting() and self.pending_sent != (self.pending[0], url):
            s = pair_secret(self.pending[0])
            self.post(topic(s), seal(s, payload))
            self.pending_sent = (self.pending[0], url)
        if self.config.get('devices') and (url != self.sent[0] or self.clock() - self.sent[1] > REPUBLISH):
            s = self.secret()
            self.post(topic(s), seal(s, payload))
            self.sent = (url, self.clock())

    def run(self, stop):
        while not stop.is_set():
            try:
                self.tick(); self.error = ''
            except Exception as ex:
                self.error = str(ex)[:120]
                logging.warning('Indirizzo per l\'app Mac non pubblicato: %s', ex)   # riprova al giro dopo
            self.kick.wait(15); self.kick.clear()
