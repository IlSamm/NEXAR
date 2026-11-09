"""Controllo remoto del PC: schermo dal vivo, mouse e tastiera.

Sicurezza:
- spento di partenza; si accende e il PIN si sceglie solo dal PC (dashboard locale);
- ogni sessione chiede il PIN (6 cifre, salvato come hash); 5 PIN sbagliati = blocco di 15 minuti;
- una sola sessione alla volta, che si chiude da sola dopo N minuti senza comandi;
- sul PC compare la scritta "Controllo remoto attivo" e su Telegram arriva un avviso a ogni sessione.

Trasporto: niente WebSocket (nessuna libreria in più). Il telefono chiede il fotogramma successivo e il PC
risponde appena lo schermo cambia (long polling); i comandi arrivano a gruppi con POST.
"""
import ctypes
import hashlib
import hmac
import io
import json
import logging
import struct
import os
import secrets
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from ctypes import wintypes

PIN_ITER = 200_000
MAX_FAILS, LOCK_SECONDS = 5, 900
IDLE_DEFAULT, IDLE_CHOICES = 10, (5, 10, 15, 30)
POLL_IDLE = 6            # nessuno chiede fotogrammi da 6 s: non si cattura (CPU a riposo)
# larghezza massima, qualità JPEG, sottocampionamento colore (2 = 4:2:0 leggero, 0 = 4:4:4: testo nitido senza aloni)
QUALITY = {'eco': (1280, 55, 2), 'balanced': (1920, 74, 2), 'sharp': (2560, 84, 0)}
FPS_CHOICES = (5, 10, 15, 20, 30)
FPS_DEFAULT = 20
MAX_EVENTS = 200

# ---------- PIN ----------
def pin_hash(pin: str, salt: bytes = None) -> str:
    salt = salt or secrets.token_bytes(16)
    return salt.hex() + '$' + hashlib.pbkdf2_hmac('sha256', pin.encode(), salt, PIN_ITER).hex()


def pin_ok(pin: str, stored: str) -> bool:
    try: salt, digest = stored.split('$', 1)
    except (AttributeError, ValueError): return False
    test = hashlib.pbkdf2_hmac('sha256', str(pin).encode(), bytes.fromhex(salt), PIN_ITER).hex()
    return hmac.compare_digest(test, digest)


class NeedPin(PermissionError):
    pass


def valid_pin(pin) -> bool:
    return isinstance(pin, str) and len(pin) == 6 and pin.isdigit() and len(set(pin)) > 1 and pin not in ('123456', '654321')


# ---------- Windows: DPI, schermi, cattura ----------
def _u32():
    return ctypes.windll.user32


class _Dpi:
    """Coordinate vere dei pixel (anche con lo zoom di Windows al 125-150%) solo in questo thread."""
    def __enter__(self):
        self.old = None
        if os.name == 'nt':
            try:
                f = _u32().SetThreadDpiAwarenessContext; f.restype = ctypes.c_void_p; f.argtypes = [ctypes.c_void_p]
                self.old = f(ctypes.c_void_p(-4))   # PER_MONITOR_AWARE_V2
            except (AttributeError, OSError): pass
        return self

    def __exit__(self, *a):
        if self.old:
            try: _u32().SetThreadDpiAwarenessContext(ctypes.c_void_p(self.old))
            except (AttributeError, OSError): pass


class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [('cbSize', wintypes.DWORD), ('rcMonitor', wintypes.RECT), ('rcWork', wintypes.RECT),
                ('dwFlags', wintypes.DWORD), ('szDevice', wintypes.WCHAR * 32)]


def monitors() -> list:
    """Schermi collegati: [{'id', 'name', 'x', 'y', 'w', 'h', 'primary'}], il principale per primo."""
    if os.name != 'nt': return []
    out = []
    with _Dpi():
        u = _u32()
        proc = ctypes.WINFUNCTYPE(wintypes.BOOL, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)
        def cb(hmon, hdc, rect, data):
            mi = MONITORINFOEXW(); mi.cbSize = ctypes.sizeof(MONITORINFOEXW)
            u.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
            if u.GetMonitorInfoW(hmon, ctypes.byref(mi)):
                r = mi.rcMonitor
                out.append({'x': r.left, 'y': r.top, 'w': r.right - r.left, 'h': r.bottom - r.top, 'primary': bool(mi.dwFlags & 1),
                            'device': mi.szDevice})
            return 1
        u.EnumDisplayMonitors.argtypes = [ctypes.c_void_p, ctypes.c_void_p, proc, wintypes.LPARAM]
        u.EnumDisplayMonitors(None, None, proc(cb), 0)
    out.sort(key=lambda m: (not m['primary'], m['x'], m['y']))
    for i, m in enumerate(out):
        m['id'] = i
        m['name'] = f'Schermo {i + 1}' + (' (principale)' if m['primary'] else '') + f' · {m["w"]}×{m["h"]}'
    return out


def area(mon_id, mons):
    """Rettangolo da catturare: uno schermo o tutti insieme ('all')."""
    if not mons: return {'x': 0, 'y': 0, 'w': 1920, 'h': 1080}
    if mon_id == 'all':
        x0, y0 = min(m['x'] for m in mons), min(m['y'] for m in mons)
        x1, y1 = max(m['x'] + m['w'] for m in mons), max(m['y'] + m['h'] for m in mons)
        return {'x': x0, 'y': y0, 'w': x1 - x0, 'h': y1 - y0}
    m = next((m for m in mons if m['id'] == mon_id), mons[0])
    return {k: m[k] for k in ('x', 'y', 'w', 'h')}


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [('biSize', wintypes.DWORD), ('biWidth', wintypes.LONG), ('biHeight', wintypes.LONG), ('biPlanes', wintypes.WORD),
                ('biBitCount', wintypes.WORD), ('biCompression', wintypes.DWORD), ('biSizeImage', wintypes.DWORD),
                ('biXPelsPerMeter', wintypes.LONG), ('biYPelsPerMeter', wintypes.LONG), ('biClrUsed', wintypes.DWORD), ('biClrImportant', wintypes.DWORD)]


def grab(rect):
    """Solo la parte di schermo che serve (più veloce che fotografare tutti gli schermi). OSError se il PC è bloccato."""
    from PIL import Image
    x, y, w, h = rect['x'], rect['y'], rect['w'], rect['h']
    with _Dpi():
        u, g = _u32(), ctypes.windll.gdi32
        for f in (g.CreateCompatibleDC, g.CreateCompatibleBitmap, g.SelectObject, u.GetDC): f.restype = ctypes.c_void_p
        g.CreateCompatibleDC.argtypes = [ctypes.c_void_p]; g.CreateCompatibleBitmap.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
        g.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]; g.DeleteObject.argtypes = [ctypes.c_void_p]; g.DeleteDC.argtypes = [ctypes.c_void_p]
        g.BitBlt.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_void_p, ctypes.c_int, ctypes.c_int, wintypes.DWORD]
        g.GetDIBits.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT, wintypes.UINT, ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT]
        u.GetDC.argtypes = [ctypes.c_void_p]; u.ReleaseDC.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        screen = u.GetDC(None)
        if not screen: raise OSError('Schermo non disponibile')
        mem = g.CreateCompatibleDC(screen); bmp = g.CreateCompatibleBitmap(screen, w, h)
        try:
            old = g.SelectObject(mem, bmp)
            ok = g.BitBlt(mem, 0, 0, w, h, screen, x, y, 0x00CC0020)   # SRCCOPY
            g.SelectObject(mem, old)
            if not ok: raise OSError('Cattura non riuscita: PC bloccato?')
            bi = BITMAPINFOHEADER(); bi.biSize = ctypes.sizeof(BITMAPINFOHEADER); bi.biWidth = w; bi.biHeight = -h
            bi.biPlanes = 1; bi.biBitCount = 32
            buf = ctypes.create_string_buffer(w * h * 4)
            if not g.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(bi), 0): raise OSError('Cattura non riuscita')
        finally:
            g.DeleteObject(bmp); g.DeleteDC(mem); u.ReleaseDC(None, screen)
    return Image.frombuffer('RGB', (w, h), buf, 'raw', 'BGRX', 0, 1)


def cursor_pos():
    pt = wintypes.POINT()
    with _Dpi():
        if not _u32().GetCursorPos(ctypes.byref(pt)): return None
    return pt.x, pt.y


def encode(img, quality_key):
    """Ridimensiona e comprime. Restituisce (jpeg, impronta) per non rimandare fotogrammi uguali."""
    from PIL import Image
    width, q, sub = QUALITY.get(quality_key, QUALITY['balanced'])
    if img.width > width:
        f = img.width / width
        # riduzione intera (2560 → 1280) molto più veloce; altrimenti filtro con antialiasing
        img = img.reduce(int(f)) if f == int(f) else img.resize((width, max(1, round(img.height * width / img.width))), Image.BILINEAR)
    buf = io.BytesIO(); img.save(buf, 'JPEG', quality=q, subsampling=sub)
    jpg = buf.getvalue()
    # lo stesso schermo dà sempre lo stesso JPEG: l'impronta del file (piccolo) basta e costa poco
    return jpg, hashlib.blake2b(jpg, digest_size=12).digest(), img.size


def pack(meta: dict, jpg: bytes | None = None) -> bytes:
    """Un messaggio del flusso continuo: lunghezze (meta, immagine), meta JSON, JPEG."""
    m = json.dumps(meta, separators=(',', ':')).encode()
    return struct.pack('>II', len(m), len(jpg or b'')) + m + (jpg or b'')


# ---------- Windows: mouse e tastiera ----------
ULONG_PTR = ctypes.c_size_t


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [('dx', wintypes.LONG), ('dy', wintypes.LONG), ('mouseData', wintypes.DWORD), ('dwFlags', wintypes.DWORD),
                ('time', wintypes.DWORD), ('dwExtraInfo', ULONG_PTR)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [('wVk', wintypes.WORD), ('wScan', wintypes.WORD), ('dwFlags', wintypes.DWORD), ('time', wintypes.DWORD), ('dwExtraInfo', ULONG_PTR)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [('uMsg', wintypes.DWORD), ('wParamL', wintypes.WORD), ('wParamH', wintypes.WORD)]


class _INPUTU(ctypes.Union):
    _fields_ = [('mi', MOUSEINPUT), ('ki', KEYBDINPUT), ('hi', HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [('type', wintypes.DWORD), ('u', _INPUTU)]


BUTTONS = {'left': (0x0002, 0x0004), 'right': (0x0008, 0x0010), 'middle': (0x0020, 0x0040)}
KEYS = {'enter': 0x0D, 'esc': 0x1B, 'tab': 0x09, 'backspace': 0x08, 'delete': 0x2E, 'space': 0x20, 'left': 0x25, 'up': 0x26,
        'right': 0x27, 'down': 0x28, 'home': 0x24, 'end': 0x23, 'pageup': 0x21, 'pagedown': 0x22, 'insert': 0x2D, 'win': 0x5B,
        'ctrl': 0x11, 'alt': 0x12, 'shift': 0x10, 'menu': 0x5D, 'printscreen': 0x2C, 'capslock': 0x14,
        **{f'f{i}': 0x6F + i for i in range(1, 13)}, **{chr(c).lower(): c for c in range(0x41, 0x5B)}, **{str(d): 0x30 + d for d in range(10)}}
EXTENDED = {0x25, 0x26, 0x27, 0x28, 0x24, 0x23, 0x21, 0x22, 0x2D, 0x2E, 0x5B, 0x5D}
MODS = ('ctrl', 'alt', 'shift', 'win')


class Injector:
    """Trasforma i comandi del telefono in mouse e tastiera veri (SendInput). send/move sostituibili nei test."""
    def __init__(self, send=None, move=None):
        self._send, self._move = send, move

    def send(self, inputs):
        if self._send: return self._send(inputs)
        arr = (INPUT * len(inputs))(*inputs)
        _u32().SendInput(len(inputs), arr, ctypes.sizeof(INPUT))

    def move(self, x, y):
        if self._move: return self._move(x, y)
        with _Dpi(): _u32().SetCursorPos(int(x), int(y))

    @staticmethod
    def mouse(flags, data=0):
        i = INPUT(type=0); i.u.mi = MOUSEINPUT(0, 0, data & 0xFFFFFFFF, flags, 0, 0); return i

    @staticmethod
    def key(vk=0, up=False, scan=0, unicode=False):
        flags = (0x0002 if up else 0) | (0x0004 if unicode else 0) | (0x0001 if vk in EXTENDED and not unicode else 0)
        i = INPUT(type=1); i.u.ki = KEYBDINPUT(vk, scan, flags, 0, 0); return i

    def button(self, name, down):
        self.send([self.mouse(BUTTONS[name][0 if down else 1])])

    def click(self, name, count=1):
        seq = []
        for _ in range(count): seq += [self.mouse(BUTTONS[name][0]), self.mouse(BUTTONS[name][1])]
        self.send(seq)

    def wheel(self, dy=0, dx=0):
        seq = []
        if dy: seq.append(self.mouse(0x0800, int(dy)))
        if dx: seq.append(self.mouse(0x1000, int(dx)))
        if seq: self.send(seq)

    def combo(self, name, mods=()):
        vk = KEYS[name]
        mvk = [KEYS[m] for m in MODS if m in mods]
        seq = [self.key(m) for m in mvk] + [self.key(vk), self.key(vk, up=True)] + [self.key(m, up=True) for m in reversed(mvk)]
        self.send(seq)

    def text(self, s):
        seq = []
        for ch in s[:2000]:
            if ch in '\r\n': seq += [self.key(0x0D), self.key(0x0D, up=True)]; continue
            if ch == '\t': seq += [self.key(0x09), self.key(0x09, up=True)]; continue
            data = ch.encode('utf-16-le')
            for j in range(0, len(data), 2):
                cu = int.from_bytes(data[j:j + 2], 'little')
                seq += [self.key(scan=cu, unicode=True), self.key(scan=cu, unicode=True, up=True)]
        if seq: self.send(seq)


def to_screen(nx, ny, rect):
    """Coordinate del telefono (0–1 sull'immagine) → pixel veri dello schermo scelto."""
    nx, ny = min(1.0, max(0.0, float(nx))), min(1.0, max(0.0, float(ny)))
    return rect['x'] + round(nx * (rect['w'] - 1)), rect['y'] + round(ny * (rect['h'] - 1))


# ---------- scritta sul PC ----------
WS_EX = 0x00000008 | 0x00000080 | 0x00080000 | 0x00000020 | 0x08000000   # in primo piano, strumento, trasparente, non attivabile
_overlay_text = ['']
_overlay_proc = None


class Overlay:
    """Piccola scritta rossa in alto sullo schermo del PC finché il controllo remoto è attivo (i clic la attraversano)."""
    def __init__(self):
        self.hwnd, self.thread = None, None

    def show(self, text):
        if os.name != 'nt' or self.thread: return
        _overlay_text[0] = text
        self.thread = threading.Thread(target=self._run, daemon=True, name='remote-overlay'); self.thread.start()

    def hide(self):
        h = self.hwnd
        if h:
            try: _u32().PostMessageW(wintypes.HWND(h), 0x0010, 0, 0)   # WM_CLOSE
            except OSError: pass

    def _run(self):
        try:
            with _Dpi(): self._loop()
        except Exception: logging.exception('Scritta controllo remoto')
        finally: self.hwnd, self.thread = None, None

    def _loop(self):
        global _overlay_proc
        u = ctypes.WinDLL('user32', use_last_error=True); g = ctypes.WinDLL('gdi32')
        LRESULT = ctypes.c_ssize_t
        WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
        u.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]; u.DefWindowProcW.restype = LRESULT

        class PAINTSTRUCT(ctypes.Structure):
            _fields_ = [('hdc', ctypes.c_void_p), ('fErase', wintypes.BOOL), ('rcPaint', wintypes.RECT), ('fRestore', wintypes.BOOL),
                        ('fIncUpdate', wintypes.BOOL), ('rgbReserved', ctypes.c_byte * 32)]

        class WNDCLASSW(ctypes.Structure):
            _fields_ = [('style', wintypes.UINT), ('lpfnWndProc', WNDPROC), ('cbClsExtra', ctypes.c_int), ('cbWndExtra', ctypes.c_int),
                        ('hInstance', ctypes.c_void_p), ('hIcon', ctypes.c_void_p), ('hCursor', ctypes.c_void_p), ('hbrBackground', ctypes.c_void_p),
                        ('lpszMenuName', wintypes.LPCWSTR), ('lpszClassName', wintypes.LPCWSTR)]

        dpi = 96
        try: dpi = u.GetDpiForSystem() or 96
        except AttributeError: pass
        sc = dpi / 96
        u.BeginPaint.restype = ctypes.c_void_p; u.BeginPaint.argtypes = [wintypes.HWND, ctypes.c_void_p]
        u.EndPaint.argtypes = [wintypes.HWND, ctypes.c_void_p]; u.FillRect.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
        u.DrawTextW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR, ctypes.c_int, ctypes.c_void_p, wintypes.UINT]
        g.CreateSolidBrush.restype = ctypes.c_void_p; g.CreateFontW.restype = ctypes.c_void_p
        g.CreateFontW.argtypes = [ctypes.c_int] * 5 + [wintypes.DWORD] * 8 + [wintypes.LPCWSTR]
        g.SelectObject.restype = ctypes.c_void_p; g.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        g.DeleteObject.argtypes = [ctypes.c_void_p]; g.SetBkMode.argtypes = [ctypes.c_void_p, ctypes.c_int]
        g.SetTextColor.argtypes = [ctypes.c_void_p, wintypes.DWORD]

        def proc(h, m, w, l):
            if m == 0x000F:   # WM_PAINT
                ps = PAINTSTRUCT(); hdc = u.BeginPaint(h, ctypes.byref(ps))
                rc = wintypes.RECT(); u.GetClientRect(h, ctypes.byref(rc))
                br = g.CreateSolidBrush(0x002626DC); u.FillRect(hdc, ctypes.byref(rc), br); g.DeleteObject(br)
                g.SetBkMode(hdc, 1); g.SetTextColor(hdc, 0x00FFFFFF)
                font = g.CreateFontW(-int(15 * sc), 0, 0, 0, 600, 0, 0, 0, 0, 0, 0, 5, 0, 'Segoe UI')
                old = g.SelectObject(hdc, font)
                u.DrawTextW(hdc, _overlay_text[0], -1, ctypes.byref(rc), 0x25)   # centro, una riga
                g.SelectObject(hdc, old); g.DeleteObject(font); u.EndPaint(h, ctypes.byref(ps))
                return 0
            if m == 0x0010: u.DestroyWindow(h); return 0          # WM_CLOSE
            if m == 0x0002: u.PostQuitMessage(0); return 0        # WM_DESTROY
            return u.DefWindowProcW(h, m, w, l)

        if _overlay_proc is None:
            _overlay_proc = WNDPROC(proc)
            wc = WNDCLASSW(); wc.lpfnWndProc = _overlay_proc; wc.lpszClassName = 'NexarRemoteOverlay'
            k32 = ctypes.windll.kernel32; k32.GetModuleHandleW.restype = ctypes.c_void_p
            wc.hInstance = k32.GetModuleHandleW(None)
            u.RegisterClassW(ctypes.byref(wc))
        w, h = int(340 * sc), int(34 * sc)
        x, y = (u.GetSystemMetrics(0) - w) // 2, int(8 * sc)
        u.CreateWindowExW.restype = wintypes.HWND
        u.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_int, ctypes.c_int,
                                      ctypes.c_int, ctypes.c_int, wintypes.HWND, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
        hwnd = u.CreateWindowExW(WS_EX, 'NexarRemoteOverlay', 'NEXAR', 0x80000000, x, y, w, h, None, None, None, None)
        if not hwnd: return
        self.hwnd = hwnd
        u.SetLayeredWindowAttributes(hwnd, 0, 235, 2)
        g.CreateRoundRectRgn.restype = ctypes.c_void_p
        u.SetWindowRgn.argtypes = [wintypes.HWND, ctypes.c_void_p, wintypes.BOOL]
        u.SetWindowRgn(hwnd, g.CreateRoundRectRgn(0, 0, w + 1, h + 1, h, h), True)
        u.ShowWindow(hwnd, 4)   # senza rubare il focus
        msg = wintypes.MSG()
        while u.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            u.TranslateMessage(ctypes.byref(msg)); u.DispatchMessageW(ctypes.byref(msg))


# ---------- sessione ----------
class Remote:
    def __init__(self, get_cfg, notify=lambda m: None, log=lambda m: None, injector=None, overlay=None,
                 grabber=None, mons=None, cursor=None, clock=time.monotonic):
        self.get_cfg, self.notify, self.log, self.clock = get_cfg, notify, log, clock
        self.inj = injector or Injector()
        self.overlay = overlay or Overlay()
        self._grab, self._mons, self._cursor = grabber or grab, mons or monitors, cursor or cursor_pos
        self.lock = threading.Lock()
        self.cond = threading.Condition(self.lock)
        self.session = None
        self.fails, self.locked_until = 0, 0.0
        self.frame = None          # (seq, jpeg, size)
        self.version, self.cursor, self.state = 0, None, 'ok'
        self.seq = 0             # numero dei fotogrammi: non torna mai indietro
        self.thread = None

    # impostazioni (dal PC)
    def cfg(self):
        c = self.get_cfg() or {}
        return {'enabled': bool(c.get('enabled')), 'pin_set': bool(c.get('pin_hash')),
                'idle_minutes': int(c.get('idle_minutes') or IDLE_DEFAULT)}

    def info(self):
        s = self.session
        out = self.cfg()
        out['locked_for'] = max(0, round(self.locked_until - self.clock())) if self.locked_until > self.clock() else 0
        out['active'] = bool(s)
        if s: out['session'] = {'who': s['who'], 'since_s': round(self.clock() - s['started']), 'idle_s': round(self.clock() - s['last_input'])}
        return out

    def check_pin(self, pin):
        """PIN unico: controllo remoto e operazioni protette contano gli stessi tentativi.
        NeedPin = si può chiedere (di nuovo) il PIN; PermissionError semplice = inutile riprovare ora."""
        c = self.get_cfg() or {}
        if not c.get('pin_hash'): raise PermissionError('Scegli prima il PIN dal PC')
        now = self.clock()
        if self.locked_until > now:
            raise PermissionError(f'Troppi PIN sbagliati: riprova tra {max(1, round((self.locked_until - now) / 60))} min')
        if not pin: raise NeedPin('Serve il PIN')
        if not pin_ok(str(pin), c['pin_hash']):
            self.fails += 1
            if self.fails >= MAX_FAILS:
                self.fails, self.locked_until = 0, now + LOCK_SECONDS
                self.notify(f'⚠️ NEXAR: {MAX_FAILS} PIN sbagliati. Bloccato per 15 minuti. Se non eri tu, cambia il PIN dal PC.')
                self.log('🖱 PIN bloccato: troppi tentativi sbagliati')
                raise PermissionError('Troppi PIN sbagliati: bloccato per 15 minuti')
            raise NeedPin(f'PIN sbagliato ({MAX_FAILS - self.fails} tentativi rimasti)')
        self.fails = 0

    # avvio con PIN
    def start(self, pin, who='dashboard'):
        c = self.get_cfg() or {}
        if not c.get('enabled'): raise PermissionError('Controllo remoto spento: accendilo da Schermo → Controllo e privacy')
        self.check_pin(str(pin or '') or '-')
        now = self.clock()
        if self.session: self.end(reason='sostituita da una nuova sessione', quiet=True)
        mons = self._mons()
        token = secrets.token_urlsafe(32)
        with self.cond:
            self.session = {'token': token, 'who': who, 'started': now, 'last_input': now, 'last_poll': now,
                            'mon': 0, 'quality': 'balanced', 'fps': FPS_DEFAULT, 'mons': mons, 'rect': area(0, mons)}
            self.frame, self.state = None, 'ok'
            self.version += 1
        self.thread = threading.Thread(target=self._capture_loop, args=(token,), daemon=True, name='remote-capture'); self.thread.start()
        self.overlay.show('🖱  Controllo remoto attivo  ·  NEXAR')
        self.notify(f'🖱 Controllo remoto del PC iniziato ({who}). Se non sei tu: sul PC apri NEXAR → Schermo → Termina e cambia il PIN.')
        self.log(f'🖱 Controllo remoto iniziato ({who})')
        return {'token': token, 'monitors': [{k: m[k] for k in ('id', 'name', 'w', 'h', 'primary')} for m in mons],
                'idle_minutes': self.cfg()['idle_minutes']}

    def check(self, token):
        s = self.session
        if not s or not token or not hmac.compare_digest(s['token'], str(token)): raise PermissionError('Sessione di controllo scaduta: inserisci di nuovo il PIN')
        if self.clock() - s['last_input'] > self.cfg()['idle_minutes'] * 60:
            self.end(reason='nessun comando per troppo tempo'); raise PermissionError('Sessione chiusa per inattività')
        return s

    def end(self, token=None, reason='terminato', quiet=False):
        with self.cond:
            s = self.session
            if not s or (token is not None and not hmac.compare_digest(s['token'], str(token))): return False
            self.session = None; self.version += 1; self.cond.notify_all()
        self.overlay.hide()
        mins = max(1, round((self.clock() - s['started']) / 60))
        self.log(f'🖱 Controllo remoto terminato: {reason}')
        if not quiet: self.notify(f'🖱 Controllo remoto terminato ({reason}, {mins} min).')
        return True

    # impostazioni della sessione
    def configure(self, token, mon=None, quality=None, fps=None):
        s = self.check(token)
        with self.cond:
            if mon is not None:
                if mon != 'all' and not any(m['id'] == mon for m in s['mons']): raise ValueError('Schermo non trovato')
                s['mon'], s['rect'] = mon, area(mon, s['mons'])
            if quality is not None:
                if quality not in QUALITY: raise ValueError('Qualità non prevista')
                s['quality'] = quality
            if fps is not None:
                if fps not in FPS_CHOICES: raise ValueError('Fotogrammi non previsti')
                s['fps'] = fps
            self.frame = None; self.version += 1; self.cond.notify_all()
        return {'mon': s['mon'], 'quality': s['quality'], 'fps': s['fps']}

    # fotogrammi
    def _capture_loop(self, token):
        # Cattura e compressione in parallelo: mentre si fotografa lo schermo, il fotogramma precedente
        # viene compresso in un altro thread (PIL e GDI lasciano libero il GIL). Quasi il doppio dei fps.
        pool = ThreadPoolExecutor(1, thread_name_prefix='remote-encode')
        try: self._capture(token, pool)
        finally: pool.shutdown(wait=False)

    def _capture(self, token, pool):
        last_mark, last_cur, job, warm = None, None, None, None
        while True:
            s = self.session
            if not s or s['token'] != token: return
            if self.clock() - s['last_input'] > self.cfg()['idle_minutes'] * 60:
                self.end(token, 'nessun comando per troppo tempo'); return
            if self.clock() - s['last_poll'] > POLL_IDLE: job = None; time.sleep(0.3); continue
            t0 = time.monotonic()
            rect, quality = s['rect'], s['quality']
            key = (s['mon'], quality)
            try:
                img = self._grab(rect)
                state = 'ok'
            except OSError:
                img, state = None, 'locked'
            done = (key, job[1].result()) if job and job[0] == key else None
            if img is None: job = None
            elif warm != key:
                # primo fotogramma (o schermo/qualità appena cambiati): subito, senza aspettare il giro dopo
                done, job, warm = (key, encode(img, quality)), None, key
            else: job = (key, pool.submit(encode, img, quality))
            changed = False
            with self.cond:
                if self.session is not s: return
                if state != self.state: self.state, changed = state, True
                if done and done[0] == key:          # scartato se nel frattempo è cambiato schermo o qualità
                    jpg, mark, size = done[1]
                    if mark != last_mark or self.frame is None:
                        last_mark = mark
                        self.seq += 1; self.frame = (self.seq, jpg, size); changed = True
                cur = self._cursor()
                if cur and cur != last_cur:
                    last_cur = cur
                    self.cursor = (round((cur[0] - rect['x']) / max(1, rect['w']), 4), round((cur[1] - rect['y']) / max(1, rect['h']), 4))
                    changed = True
                if changed: self.version += 1; self.cond.notify_all()
            time.sleep(max(0.0, 1 / max(1, s['fps']) - (time.monotonic() - t0)) if state == 'ok' else 1.0)

    def next(self, token, have_v=0, have_seq=0, timeout=2.5):
        """Long polling: torna appena c'è qualcosa di nuovo (fotogramma, puntatore, PC bloccato) o dopo timeout."""
        s = self.check(token)
        s['last_poll'] = self.clock()
        with self.cond:
            self.cond.wait_for(lambda: self.version > have_v or self.session is not s, timeout=timeout)
            if self.session is not s: raise PermissionError('Sessione di controllo terminata')
            meta = {'v': self.version, 'cursor': self.cursor, 'state': self.state, 'mon': s['mon'], 'quality': s['quality'], 'fps': s['fps']}
            f = self.frame
            if f and f[0] != have_seq:
                meta.update(seq=f[0], w=f[2][0], h=f[2][1])
                return meta, f[1]
            return meta, None

    def stream(self, token):
        """Flusso continuo per la dashboard: un messaggio appena cambia qualcosa, senza una richiesta per fotogramma.
        Se il telefono è lento i fotogrammi intermedi si saltano da soli: si manda sempre l'ultimo."""
        have_v, have_seq = 0, 0
        while True:
            try: meta, jpg = self.next(token, have_v, have_seq)
            except PermissionError as ex:
                yield pack({'end': str(ex)}); return
            have_v = meta['v']
            if jpg is not None: have_seq = meta['seq']
            yield pack(meta, jpg)

    # comandi
    def input(self, token, events):
        s = self.check(token)
        if not isinstance(events, list) or len(events) > MAX_EVENTS: raise ValueError('Comandi non validi')
        rect = s['rect']
        done = 0
        for e in events:
            if not isinstance(e, dict): continue
            t = e.get('t')
            if t == 'alive': pass
            elif t == 'move': self.inj.move(*to_screen(e.get('x', 0), e.get('y', 0), rect))
            elif t in ('down', 'up', 'click'):
                b = e.get('b', 'left')
                if b not in BUTTONS: raise ValueError('Tasto del mouse non previsto')
                if 'x' in e: self.inj.move(*to_screen(e['x'], e.get('y', 0), rect))
                if t == 'click': self.inj.click(b, min(3, max(1, int(e.get('n', 1)))))
                else: self.inj.button(b, t == 'down')
            elif t == 'wheel':
                if 'x' in e: self.inj.move(*to_screen(e['x'], e.get('y', 0), rect))
                self.inj.wheel(max(-2400, min(2400, int(e.get('dy', 0)))), max(-2400, min(2400, int(e.get('dx', 0)))))
            elif t == 'key':
                k, mods = str(e.get('k', '')).lower(), [m for m in e.get('mods') or [] if m in MODS]
                if k not in KEYS: raise ValueError('Tasto non previsto: ' + k[:20])
                self.inj.combo(k, mods)
            elif t == 'text':
                txt = e.get('s')
                if not isinstance(txt, str): raise ValueError('Testo non valido')
                self.inj.text(txt)
            else: raise ValueError('Comando non previsto')
            done += 1
        s['last_input'] = self.clock()
        return done
