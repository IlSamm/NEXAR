"""Lo schermo del PC visto da lontano: foto dello schermo, finestre aperte, volume e schermo spento.

Niente controllo di mouse e tastiera: si guarda e si fanno solo poche azioni sicure.
"""
import ctypes
import io
import os
import time
from ctypes import wintypes

import psutil

PROTECTED = {'explorer.exe', 'dwm.exe', 'csrss.exe', 'winlogon.exe', 'lsass.exe', 'services.exe', 'svchost.exe',
             'sihost.exe', 'shellexperiencehost.exe', 'startmenuexperiencehost.exe', 'searchhost.exe',
             'textinputhost.exe', 'applicationframehost.exe', 'lockapp.exe', 'logonui.exe', 'nexar.exe'}
VOLUME_KEYS = {'up': 0xAF, 'down': 0xAE, 'mute': 0xAD}
VOLUME_STEP = 5           # ogni tasto volume di Windows = 2%: 5 tocchi = 10%
MAX_WIDTH = 2400


def capture(max_width=MAX_WIDTH, quality=72, grab=None) -> bytes:
    """Foto di tutti gli schermi in JPEG. Errore chiaro se il PC è bloccato o lo schermo è spento."""
    from PIL import Image
    try:
        if grab: img = grab()
        else:
            from PIL import ImageGrab
            img = ImageGrab.grab(all_screens=True)
    except OSError:
        raise RuntimeError('Schermo non disponibile: il PC è bloccato o in sospensione')
    img = img.convert('RGB')
    if img.getbbox() is None: raise RuntimeError('Schermo nero: il PC è bloccato o lo schermo è spento')
    if img.width > max_width:
        img = img.resize((max_width, max(1, round(img.height * max_width / img.width))), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, 'JPEG', quality=quality, optimize=True)
    return buf.getvalue()


def snapshot(mon=0, live=False, grab=None, mons=None) -> bytes:
    """Un solo schermo: più nitido e molto più veloce della foto di tutti gli schermi insieme.
    live: più leggera, per l'anteprima dal vivo; altrimenti massima qualità."""
    from PIL import Image
    import remote_control
    mons = remote_control.monitors() if mons is None else mons
    try: img = (grab or remote_control.grab)(remote_control.area(mon, mons))
    except OSError:
        raise RuntimeError('Schermo non disponibile: il PC è bloccato o in sospensione')
    img = img.convert('RGB')
    if img.getbbox() is None: raise RuntimeError('Schermo nero: il PC è bloccato o lo schermo è spento')
    width, quality, sub = (1920, 74, 2) if live else (2560, 86, 0)
    if img.width > width:
        size = (width, max(1, round(img.height * width / img.width)))
        img = img.resize(size, Image.BILINEAR if live else Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, 'JPEG', quality=quality, subsampling=sub, optimize=not live)
    return buf.getvalue()


def _user32():
    return ctypes.windll.user32


def windows(me=None) -> list:
    """Finestre aperte come nella barra delle applicazioni: titolo, programma e se non risponde."""
    if os.name != 'nt': return []
    u, me = _user32(), os.getpid() if me is None else me
    dwm = ctypes.windll.dwmapi
    out = []
    proc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

    def cb(h, _):
        try:
            if not u.IsWindowVisible(h) or u.GetWindow(h, 4) or not u.GetWindowTextLengthW(h): return True   # 4 = GW_OWNER
            if u.GetWindowLongW(h, -20) & 0x80: return True                                                 # finestre-strumento
            cloaked = wintypes.DWORD()
            if dwm.DwmGetWindowAttribute(h, 14, ctypes.byref(cloaked), 4) == 0 and cloaked.value: return True  # nascoste (app Store)
            n = u.GetWindowTextLengthW(h); buf = ctypes.create_unicode_buffer(n + 1); u.GetWindowTextW(h, buf, n + 1)
            pid = wintypes.DWORD(); u.GetWindowThreadProcessId(h, ctypes.byref(pid))
            if pid.value == me: return True
            try: exe = psutil.Process(pid.value).name()
            except psutil.Error: exe = ''
            if exe.lower() in PROTECTED or buf.value == 'Program Manager': return True
            out.append({'id': int(h or 0), 'title': buf.value[:120], 'exe': exe, 'pid': pid.value,
                        'hung': bool(u.IsHungAppWindow(h)), 'min': bool(u.IsIconic(h))})
        except Exception: pass
        return True
    u.EnumWindows(proc(cb), 0)
    return out


def close_window(win_id: int, force=False, listing=None, kill=None, post=None) -> str:
    """Chiude una finestra della lista: gentile (come la X) o, se è bloccata, chiude il programma."""
    w = next((w for w in (windows() if listing is None else listing) if w['id'] == win_id), None)
    if not w: raise ValueError('Finestra non trovata (forse è già chiusa)')
    if (w['exe'] or '').lower() in PROTECTED: raise ValueError('Questa finestra non si chiude da qui')
    if force:
        (kill or (lambda pid: psutil.Process(pid).kill()))(w['pid'])
        return f'Chiuso {w["exe"] or w["title"]}'
    (post or (lambda h: _user32().PostMessageW(wintypes.HWND(h), 0x0010, 0, 0)))(win_id)   # WM_CLOSE
    return f'Chiudo «{w["title"][:60]}»'


def volume(action: str, press=None) -> str:
    if action not in VOLUME_KEYS: raise ValueError('Azione volume non prevista')
    def key(vk):
        u = _user32(); u.keybd_event(vk, 0, 0, 0); u.keybd_event(vk, 0, 2, 0)
    press = press or key
    for _ in range(1 if action == 'mute' else VOLUME_STEP):
        press(VOLUME_KEYS[action]); time.sleep(0.01)
    return {'up': 'Volume +10', 'down': 'Volume −10', 'mute': 'Audio muto / riattivato'}[action]


OFF_DELAY = 0.8              # aspetta che il clic (e il rilascio del mouse) sia finito, sennò li riaccende subito
# Secondi dopo lo spegnimento in cui si ricontrolla: un monitor che va in standby a volte si «stacca e riattacca»
# (DisplayPort/HDMI), un mouse che vibra sul tavolo o un controller collegato muovono l'input di Windows e lo
# riaccendono. Se l'utente non ha davvero toccato niente, gli schermi vengono rispenti.
OFF_RECHECK = (2.0, 5.0, 10.0, 20.0, 35.0)
MOVE_PX = 25                 # movimento del mouse che conta come «lo sto usando» (sotto è vibrazione)


def _idle_seconds():
    class LII(ctypes.Structure):
        _fields_ = [('cbSize', ctypes.c_uint), ('dwTime', ctypes.c_uint)]
    info = LII(ctypes.sizeof(LII), 0)
    if not _user32().GetLastInputInfo(ctypes.byref(info)): return 0.0
    return ((ctypes.windll.kernel32.GetTickCount() - info.dwTime) & 0xFFFFFFFF) / 1000


def _post_off():
    # SendMessageTimeout e non PostMessage: arriva a tutte le finestre anche se una è bloccata, e non si accoda dietro
    # a un gioco che non risponde. 2 = spento.
    res = wintypes.DWORD()
    u = _user32()
    if not u.SendMessageTimeoutW(wintypes.HWND(0xFFFF), 0x0112, 0xF170, 2, 0x0002, 1500, ctypes.byref(res)):
        u.PostMessageW(wintypes.HWND(0xFFFF), 0x0112, 0xF170, 2)   # WM_SYSCOMMAND, SC_MONITORPOWER


def _cursor():
    pt = wintypes.POINT()
    return (pt.x, pt.y) if _user32().GetCursorPos(ctypes.byref(pt)) else None


def _keys_down():
    """Un tasto della tastiera o del mouse premuto adesso (Maiusc, lettere, clic...)."""
    u = _user32()
    return any(u.GetAsyncKeyState(vk) & 0x8000 for vk in (1, 2, 4, *range(8, 0xFF)) if vk not in (0x5B, 0x5C))


class Touch:
    """Capisce se l'utente ha davvero usato il PC dopo lo spegnimento: il mouse spostato di parecchio o un tasto
    premuto. Un mouse che vibra, un controller o un monitor che si riattacca non contano."""
    def __init__(self, cursor=None, keys=None):
        self.cursor, self.keys = cursor or _cursor, keys or _keys_down
        self.start, self.hit = self.cursor(), False

    def __call__(self):
        if self.hit: return True
        try:
            now = self.cursor()
            moved = bool(self.start and now) and max(abs(now[0] - self.start[0]), abs(now[1] - self.start[1])) >= MOVE_PX
            self.hit = moved or self.keys()
        except Exception: self.hit = False
        return self.hit


def off_sequence(send, touched=None, sleep=time.sleep, delay=OFF_DELAY, recheck=OFF_RECHECK, step=0.25) -> int:
    """Spegne e per mezzo minuto tiene d'occhio mouse e tastiera: se l'utente li usa davvero gli schermi restano accesi,
    altrimenti a ogni controllo vengono rispenti (anche se si erano già riaccesi da soli). Ritorna quanti comandi ha
    mandato."""
    sleep(delay)
    touched = touched or Touch()
    send(); sent, waited = 1, 0.0
    for at in recheck:
        while waited < at:                     # controlla spesso: un tasto premuto dura poco
            sleep(step); waited += step
            if touched(): return sent
        send(); sent += 1
    return sent


def monitor_off(send=None, touched=None, start=None) -> str:
    """Spegne gli schermi (si riaccendono muovendo il mouse). Non blocca: la sequenza gira in un thread a parte."""
    import logging
    import threading
    def job():
        try:
            n = off_sequence(send or _post_off, touched)
            logging.info('Schermi spenti (%d %s)', n, 'comando' if n == 1 else 'comandi: si erano riaccesi o nessuno li ha toccati')
        except Exception: logging.exception('Spegnimento schermi')
    (start or (lambda f: threading.Thread(target=f, daemon=True, name='monitor-off').start()))(job)
    return 'Schermi spenti'
