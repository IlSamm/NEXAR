"""NEXAR: finestra Windows con la stessa grafica della dashboard web (WebView2).

Chiudendo la finestra l'app resta vicino all'orologio: automazione AI, Telegram e Umbrel continuano.
"""
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
from tray import icon_image

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
    """Sfondo scuro mentre il server interno parte: la N dipinta la disegna poi la dashboard."""
    return SPLASH

SPLASH = '''<!doctype html><html><head><meta charset="utf-8"><style>
html,body{margin:0;height:100%;background:#090b0f;overflow:hidden}
</style></head><body></body></html>'''

# ---------------- barra della finestra integrata nella dashboard ----------------
# La finestra resta una finestra Windows vera (bordi per ridimensionare, Snap, ombra, angoli
# arrotondati): togliamo solo la barra del titolo grigia e la dashboard disegna la sua.
if os.name == 'nt':
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    LRESULT = ctypes.c_ssize_t
    WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM)
    user32.CallWindowProcW.restype = LRESULT
    user32.CallWindowProcW.argtypes = [ctypes.c_void_p, wintypes.HWND, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM]
    user32.SetWindowLongPtrW.restype = ctypes.c_void_p
    user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
    user32.PostMessageW.argtypes = [wintypes.HWND, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM]
    user32.SendMessageW.restype = LRESULT
    user32.SendMessageW.argtypes = [wintypes.HWND, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM]
    user32.IsZoomed.argtypes = [wintypes.HWND]
    user32.ShowWindowAsync.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint]

WM_CLOSE, WM_NCCALCSIZE, WM_SYSCOMMAND, WM_APP_DRAG = 0x10, 0x83, 0x112, 0x8001
WM_WINDOWPOSCHANGING, WM_WINDOWPOSCHANGED = 0x46, 0x47
if os.name == 'nt':
    class WINDOWPOS(ctypes.Structure):
        _fields_ = [('hwnd', wintypes.HWND), ('after', wintypes.HWND), ('x', ctypes.c_int), ('y', ctypes.c_int),
                    ('cx', ctypes.c_int), ('cy', ctypes.c_int), ('flags', ctypes.c_uint)]
# SC_MOVE|HTCAPTION e SC_SIZE|WMSZ_*: gli stessi comandi che usa Windows trascinando la barra o il bordo
SC_DRAG = {'caption': 0xF012, 'top': 0xF003, 'topleft': 0xF004, 'topright': 0xF005}

def find_hwnd(title='NEXAR'):
    """Finestra principale di questo processo (anche se è ancora nascosta)."""
    found = []
    pid = os.getpid()
    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def cb(h, _):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(h, ctypes.byref(owner))
        if owner.value == pid:
            buf = ctypes.create_unicode_buffer(64)
            user32.GetWindowTextW(h, buf, 64)
            if buf.value == title: found.append(h)
        return True
    user32.EnumWindows(cb, 0)
    return found[0] if found else None

class WindowApi:
    """Comandi della barra disegnata dalla dashboard (window.pywebview.api.win_*)."""
    def __init__(self):
        self._window = None
        self._hwnd = None
        self._proc = None
        self._orig = None
        self._nested = 0

    def _attach(self, window):
        self._window = window
        if os.name != 'nt' or self._proc: return
        for _ in range(50):
            self._hwnd = find_hwnd()
            if self._hwnd: break
            time.sleep(0.1)
        if not self._hwnd: return
        hwnd = self._hwnd

        def proc(h, msg, wp, lp):
            if msg == WM_APP_DRAG:
                # Sul thread della finestra: solo qui si può togliere il mouse alla pagina web
                # e far partire lo spostamento/ridimensionamento nativo di Windows.
                # Solo se il tasto è ancora premuto: con un clic velocissimo Windows resterebbe
                # in "modalità sposta" con la finestra attaccata al cursore.
                button = 0x02 if user32.GetSystemMetrics(23) else 0x01  # SM_SWAPBUTTON: VK_RBUTTON / VK_LBUTTON
                if user32.GetAsyncKeyState(button) & 0x8000:
                    user32.ReleaseCapture()
                    user32.SendMessageW(h, WM_SYSCOMMAND, wp, 0)
                return 0
            if msg == WM_WINDOWPOSCHANGED:
                self._nested += 1
                try: return user32.CallWindowProcW(self._orig, h, msg, wp, lp)
                finally: self._nested -= 1
            if msg == WM_WINDOWPOSCHANGING and self._nested:
                # WinForms, dopo un ripristino, riaggiunge l'altezza della vecchia barra del titolo
                # (+31 px a ogni ingrandisci/riduci): blocca solo quel ridimensionamento interno.
                ctypes.cast(lp, ctypes.POINTER(WINDOWPOS)).contents.flags |= 0x1  # SWP_NOSIZE
            if msg == WM_NCCALCSIZE and wp:
                # Tieni i bordi invisibili per ridimensionare, togli solo la barra del titolo.
                rc = ctypes.cast(lp, ctypes.POINTER(wintypes.RECT)).contents
                top, left = rc.top, rc.left
                res = user32.CallWindowProcW(self._orig, h, msg, wp, lp)
                # Ingrandita: Windows allarga la finestra oltre lo schermo dello spessore del bordo.
                rc.top = top + ((rc.left - left) if user32.IsZoomed(h) else 0)
                return res
            return user32.CallWindowProcW(self._orig, h, msg, wp, lp)

        self._proc = WNDPROC(proc)  # riferimento tenuto vivo: Windows lo chiama per ogni messaggio
        self._orig = user32.SetWindowLongPtrW(hwnd, -4, ctypes.cast(self._proc, ctypes.c_void_p))
        # SWP_NOMOVE|SWP_NOSIZE|SWP_NOZORDER|SWP_NOACTIVATE|SWP_FRAMECHANGED: ricalcola il bordo adesso
        user32.SetWindowPos(hwnd, None, 0, 0, 0, 0, 0x1 | 0x2 | 0x4 | 0x10 | 0x20)

    def win_ready(self):
        return bool(self._hwnd and self._proc)

    def win_drag(self):
        # Trascinamento nativo: funzionano Snap, Aero Shake e il trascinamento tra schermi.
        if self._hwnd: user32.PostMessageW(self._hwnd, WM_APP_DRAG, SC_DRAG['caption'], 0)

    def win_resize(self, edge):
        if self._hwnd and edge in SC_DRAG and edge != 'caption' and not user32.IsZoomed(self._hwnd):
            user32.PostMessageW(self._hwnd, WM_APP_DRAG, SC_DRAG[edge], 0)

    def win_min(self):
        if self._hwnd: user32.ShowWindowAsync(self._hwnd, 6)  # SW_MINIMIZE

    def win_toggle_max(self):
        if not self._hwnd: return False
        zoomed = bool(user32.IsZoomed(self._hwnd))
        user32.ShowWindowAsync(self._hwnd, 9 if zoomed else 3)  # SW_RESTORE / SW_MAXIMIZE
        return not zoomed

    def win_close(self):
        # Come la X di Windows: la finestra si nasconde e NEXAR resta vicino all'orologio.
        if self._hwnd: user32.PostMessageW(self._hwnd, WM_CLOSE, 0, 0)

    def win_state(self):
        return {'max': bool(self._hwnd and user32.IsZoomed(self._hwnd))}

def run():
    port = int(config.get('web', {}).get('port', 8765))
    url = f"http://127.0.0.1:{port}/#access={config.get('access_token', '')}"
    api = WindowApi()
    window = webview.create_window('NEXAR', html=splash_html(), width=1360, height=900, min_size=(1000, 680),
                                   background_color='#090b0f', hidden='--minimized' in sys.argv, js_api=api)
    quitting = threading.Event()
    server = None

    def boot():
        nonlocal server
        try: api._attach(window)
        except Exception: logging.exception('Barra della finestra')  # resta la barra di Windows
        if not port_open(port): server = start_api(port)  # se l'agente è già attivo, apri solo la finestra
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
