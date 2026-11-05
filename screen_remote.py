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


def monitor_off(send=None) -> str:
    """Spegne gli schermi (si riaccendono muovendo il mouse): meno consumo mentre l'AI lavora."""
    send = send or (lambda: _user32().PostMessageW(wintypes.HWND(0xFFFF), 0x0112, 0xF170, 2))  # SC_MONITORPOWER
    send()
    return 'Schermi spenti'
