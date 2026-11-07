"""Indirizzo HTTPS pubblico per la Mini App di Telegram tramite Cloudflare Tunnel (senza account).

Il tunnel arriva a un secondo server su TUNNEL_PORT: main.py tratta tutto ciò che entra da lì come
remoto, quindi installazioni, UAC e abbinamento Telegram restano possibili solo dal PC.
"""
from __future__ import annotations
import logging
import os
import re
import subprocess
import threading
import time

TUNNEL_PORT = 8766
URL_RE = re.compile(r'https://[a-z0-9-]+\.trycloudflare\.com')

class Tunnel:
    def __init__(self, controller, app):
        self.ctrl = controller
        self.app = app
        self.url = ''
        self.proc = None
        self.server = None
        self.error = ''
        self.on_url = lambda url: None

    def wanted(self) -> bool:
        tg = self.ctrl.config.get('telegram', {})
        mac = getattr(self.ctrl, 'beacon', None)   # app per Mac collegata o codice in attesa
        return bool(tg.get('token') and tg.get('allowed_user_id') and tg.get('webapp', True)) or bool(mac and mac.wanted())

    def manual_url(self) -> str:
        url = str(self.ctrl.config.get('telegram', {}).get('webapp_url', '')).strip()
        return url if url.startswith('https://') else ''

    def start_server(self):
        if self.server: return
        import uvicorn
        # lifespan='off': bot e automazioni girano già nel server principale.
        self.server = uvicorn.Server(uvicorn.Config(self.app, host='127.0.0.1', port=TUNNEL_PORT, access_log=False,
                                                    log_level='error', log_config=None, lifespan='off'))
        threading.Thread(target=self.server.run, daemon=True, name='tunnel-api').start()

    def run(self, stop: threading.Event):
        import discovery
        while not stop.is_set():
            try:
                if not self.wanted():
                    self.set_url('')
                    stop.wait(5); continue
                manual = self.manual_url()
                if manual:  # es. Tailscale Funnel configurato a mano
                    self.start_server(); self.set_url(manual)
                    stop.wait(30); continue
                exe = discovery.find_exe('cloudflared.exe', ['cloudflared', 'Cloudflare\\cloudflared'])
                if not exe:
                    self.error = 'cloudflared non installato'
                    stop.wait(30); continue
                self.start_server()
                self.serve(exe, stop)
            except Exception:
                logging.exception('Tunnel Mini App')
                stop.wait(15)

    def serve(self, exe, stop):
        opts = dict(stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, text=True, errors='replace')
        if os.name == 'nt': opts['creationflags'] = subprocess.CREATE_NO_WINDOW
        self.proc = subprocess.Popen([exe, 'tunnel', '--no-autoupdate', '--url', f'http://127.0.0.1:{TUNNEL_PORT}'], **opts)
        threading.Thread(target=lambda: (stop.wait(), self.proc and self.proc.terminate()), daemon=True).start()
        for line in self.proc.stdout:
            m = URL_RE.search(line)
            if m: self.set_url(m.group(0)); self.error = ''
            if stop.is_set() or not self.wanted(): break
        try: self.proc.terminate()
        except OSError: pass
        self.proc = None
        self.set_url('')
        if not stop.is_set():
            self.error = 'tunnel interrotto, riavvio'
            stop.wait(10)

    def set_url(self, url):
        if url == self.url: return
        self.url = url
        if url: self.ctrl.log_event('App Telegram disponibile su ' + url)
        try: self.on_url(url)
        except Exception: logging.exception('Aggiornamento pulsante Mini App')

    def info(self):
        return {'url': self.url, 'error': self.error, 'wanted': self.wanted()}
