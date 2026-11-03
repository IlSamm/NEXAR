"""NEXAR: finestra Windows con la stessa grafica della dashboard web (WebView2).

Chiudendo la finestra l'app resta vicino all'orologio: automazione AI, Telegram e Umbrel continuano.
"""
import base64
import logging
import os
import socket
import sys
import threading
import time

import pystray
import uvicorn
import webview

import main
from core import ASSET_ROOT
from tray import icon_image
from version import VERSION

controller = main.controller
config = controller.config

def port_open(port):
    try:
        with socket.create_connection(('127.0.0.1', port), 0.3): return True
    except OSError: return False

def start_api(port):
    # log_config=None: nell'exe senza console stdout è None e uvicorn andrebbe in crash.
    server = uvicorn.Server(uvicorn.Config(main.app, host='127.0.0.1', port=port, access_log=False,
                                           log_level='error', log_config=None))
    threading.Thread(target=server.run, daemon=True, name='NEXAR API').start()
    for _ in range(100):
        if server.started: break
        time.sleep(0.1)
    return server

def splash_html():
    """Schermata di caricamento con il logo, mostrata mentre il server interno parte."""
    logo = base64.b64encode((ASSET_ROOT / 'web' / 'logo.png').read_bytes()).decode()
    return SPLASH.replace('{LOGO}', logo).replace('{VERSION}', VERSION)

SPLASH = '''<!doctype html><html><head><meta charset="utf-8"><style>
html,body{margin:0;height:100%;background:#05070d;overflow:hidden;font-family:"Segoe UI Variable Display","Segoe UI",sans-serif}
body{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:22px;
 background:radial-gradient(600px 400px at 50% 45%,rgba(40,110,255,.18),transparent 70%),#05070d}
img{width:190px;height:190px;animation:pop .9s cubic-bezier(.2,.9,.2,1.2) both,glow 2.4s ease-in-out .9s infinite}
h1{margin:0;color:#eaf2ff;font-weight:800;font-size:34px;letter-spacing:.42em;padding-left:.42em;animation:fade .8s .35s both}
.bar{width:220px;height:3px;border-radius:3px;background:#122038;overflow:hidden;animation:fade .6s .6s both}
.bar i{display:block;width:40%;height:100%;border-radius:3px;background:linear-gradient(90deg,#1f6bff,#5ad1ff,#fff);animation:run 1.1s ease-in-out infinite}
small{color:#4f6a95;font-size:12px;letter-spacing:.2em;animation:fade .6s .8s both}
@keyframes pop{from{opacity:0;transform:scale(.6) rotate(-8deg)}to{opacity:1;transform:none}}
@keyframes glow{50%{filter:drop-shadow(0 0 26px rgba(70,140,255,.75)) brightness(1.12)}}
@keyframes fade{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
@keyframes run{from{transform:translateX(-110%)}to{transform:translateX(260%)}}
</style></head><body><img src="data:image/png;base64,{LOGO}" alt=""><h1>NEXAR</h1><div class="bar"><i></i></div><small>v{VERSION}</small></body></html>'''

def run():
    port = int(config.get('web', {}).get('port', 8765))
    url = f"http://127.0.0.1:{port}/#access={config.get('access_token', '')}"
    window = webview.create_window('NEXAR', html=splash_html(), width=1360, height=900, min_size=(1000, 680),
                                   background_color='#05070d', hidden='--minimized' in sys.argv)
    quitting = threading.Event()
    server = None

    def boot():
        nonlocal server
        started = time.monotonic()
        if not port_open(port): server = start_api(port)  # se l'agente è già attivo, apri solo la finestra
        time.sleep(max(0.0, 1.6 - (time.monotonic() - started)))  # il logo si vede almeno un attimo
        window.load_url(url)

    def on_closing():
        if quitting.is_set(): return True
        window.hide()  # resta attiva nell'area di notifica
        return False
    window.events.closing += on_closing

    def show(icon=None, item=None):
        window.show(); window.restore()
    def set_mode(mode):
        def cb(icon, item):
            try: controller.set_mode(mode)
            except Exception: logging.exception('Cambio modalità da icona')
        return cb
    def quit_app(icon=None, item=None):
        quitting.set()
        tray.stop()
        if server: server.should_exit = True
        window.destroy()

    tray = pystray.Icon('nexar', icon_image(), 'NEXAR', pystray.Menu(
        pystray.MenuItem('Apri NEXAR', show, default=True),
        pystray.MenuItem('🌙 AI ECO', set_mode('eco')),
        pystray.MenuItem('⚡ Normale', set_mode('normal')),
        pystray.MenuItem('🎮 Gaming', set_mode('gaming')),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem('Esci', quit_app),
    ))
    main.updater.exit_hooks.append(quit_app)  # l'aggiornamento chiude finestra e icona prima di sostituire i file
    tray.run_detached()
    webview.start(boot)
    if not quitting.is_set():  # finestra distrutta in altro modo
        tray.stop()
    if server: server.should_exit = True

if __name__ == '__main__':
    if os.name != 'nt':
        print('Questa applicazione è destinata a Windows.')
    run()
