"""Più controllo sul PC: storico dal vivo per i grafici, rete, dischi, tasti multimediali, appunti e file condivisi.

- Storico: un campione ogni 5 secondi (15 minuti in memoria), così i grafici sono già pieni quando apri l'app,
  più le medie di ogni ora degli ultimi 30 giorni (salvate) per i grafici 24 ore / 7 giorni / 30 giorni.
- Appunti: testo dal telefono/Mac al PC e ritorno (solo testo, max 100.000 caratteri).
- File: una sola cartella, Download\\NEXAR. Da lontano si mandano file lì e si scaricano solo quelli che ci sono:
  nessun percorso arbitrario, niente sovrascritture, nulla viene aperto o eseguito.
"""
from __future__ import annotations
import ctypes
import os
import re
import threading
import time
from collections import deque
from pathlib import Path

import psutil

SAMPLE_EVERY = 5
HISTORY = 180                       # 15 minuti
TREND_KEEP = 30 * 24                # medie orarie: 30 giorni
TREND_AVG = ('cpu', 'gpu', 'ram', 'ct', 'gt', 'w')
RANGES = {'24h': (86400, 3600), '7d': (7 * 86400, 3600), '30d': (30 * 86400, 6 * 3600)}
MEDIA_KEYS = {'play': 0xB3, 'next': 0xB0, 'prev': 0xB1, 'stop': 0xB2}
MEDIA_TEXT = {'play': 'Play / pausa', 'next': 'Brano successivo', 'prev': 'Brano precedente', 'stop': 'Riproduzione fermata'}
CLIP_MAX = 100_000
UPLOAD_MAX = 2 * 1024 ** 3          # 2 GB (dal tunnel Cloudflare passano al massimo 100 MB per file)
BAD_NAME = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
RESERVED = {'con', 'prn', 'aux', 'nul', *(f'com{i}' for i in range(1, 10)), *(f'lpt{i}' for i in range(1, 10))}


# ---------- storico, rete e dischi ----------
class History:
    def __init__(self, telemetry, clock=time.time, counters=psutil.net_io_counters, trend=None, save=lambda: None):
        self.telemetry, self.clock, self.counters = telemetry, clock, counters
        self.samples = deque(maxlen=HISTORY)
        self.last_net = None
        self.lock = threading.Lock()
        self.trend = trend if trend is not None else []     # lista dello stato: si salva da sola
        self.save = save
        self.acc = None

    def net_rate(self):
        try: c = self.counters()
        except Exception: return None, None
        if c is None: return None, None      # nessuna scheda di rete
        now = self.clock()
        prev, self.last_net = self.last_net, (now, c.bytes_recv, c.bytes_sent)
        if not prev or now - prev[0] <= 0: return None, None
        dt = now - prev[0]
        return max(0, round((c.bytes_recv - prev[1]) / dt)), max(0, round((c.bytes_sent - prev[2]) / dt))

    def sample(self):
        t = self.telemetry()
        down, up = self.net_rate()
        s = {'t': int(self.clock()), 'cpu': t.get('cpu'), 'gpu': t.get('gpu'), 'ram': t.get('ram'),
             'ct': t.get('cpu_temp'), 'gt': t.get('gpu_temp'), 'w': (t.get('power') or {}).get('total'), 'down': down, 'up': up}
        with self.lock:
            self.samples.append(s)
            flushed = self._add_hour(s)
        if flushed: self.save()
        return s

    # ---------- medie orarie (24 ore, 7 e 30 giorni) ----------
    def _add_hour(self, s):
        h = s['t'] // 3600 * 3600
        flushed = False
        if self.acc and self.acc['h'] != h:
            self.trend.append(self._close(self.acc))
            del self.trend[:-TREND_KEEP]
            self.acc, flushed = None, True
        a = self.acc = self.acc or {'h': h, 'n': 0, 'sum': {}, 'cnt': {}, 'ctx': None, 'gtx': None}
        a['n'] += 1
        for k in TREND_AVG:
            v = s.get(k)
            if isinstance(v, (int, float)):
                a['sum'][k] = a['sum'].get(k, 0.0) + v; a['cnt'][k] = a['cnt'].get(k, 0) + 1
        for k, m in (('ct', 'ctx'), ('gt', 'gtx')):
            v = s.get(k)
            if isinstance(v, (int, float)): a[m] = v if a[m] is None else max(a[m], v)
        return flushed

    @staticmethod
    def _close(a):
        row = {'t': a['h'], 'n': a['n']}
        for k in TREND_AVG:
            if a['cnt'].get(k): row[k] = round(a['sum'][k] / a['cnt'][k], 1)
        for m in ('ctx', 'gtx'):
            if a[m] is not None: row[m] = round(a[m], 1)
        return row

    def range(self, name):
        """Punti per il grafico: media per ora (per 6 ore nei 30 giorni), con l'ora in corso."""
        span, step = RANGES[name]
        with self.lock:
            rows = list(self.trend) + ([self._close(self.acc)] if self.acc else [])
        since = self.clock() - span
        rows = [r for r in rows if r['t'] + 3600 > since]
        if step == 3600: return rows
        out, cur = [], None
        for r in rows:
            b = r['t'] // step * step
            if not cur or cur['t'] != b:
                cur = {'t': b, 'n': 0, '_w': {}}; out.append(cur)
            n = r.get('n', 1); cur['n'] += n
            for k in TREND_AVG:
                if k in r: cur['_w'].setdefault(k, [0.0, 0]); cur['_w'][k][0] += r[k] * n; cur['_w'][k][1] += n
            for m in ('ctx', 'gtx'):
                if m in r: cur[m] = max(cur.get(m, r[m]), r[m])
        for c in out:
            for k, (tot, n) in c.pop('_w').items(): c[k] = round(tot / n, 1)
        return out

    def latest(self):
        with self.lock: return dict(self.samples[-1]) if self.samples else {}

    def data(self):
        with self.lock: return list(self.samples)

    def run(self, stop):
        while not stop.is_set():
            try: self.sample()
            except Exception: pass
            stop.wait(SAMPLE_EVERY)


def disks():
    out = []
    for p in psutil.disk_partitions(all=False):
        if 'cdrom' in p.opts or not p.fstype: continue
        try: u = psutil.disk_usage(p.mountpoint)
        except (PermissionError, OSError): continue
        out.append({'name': p.mountpoint.rstrip('\\') or p.mountpoint, 'total': u.total, 'used': u.used, 'free': u.free, 'percent': round(u.percent, 1)})
    return out


# ---------- tasti multimediali e brano in riproduzione ----------
BROWSERS = {'chrome.exe', 'msedge.exe', 'firefox.exe', 'brave.exe', 'opera.exe', 'opera_gx.exe'}


def now_playing(listing=None):
    """Cosa suona sul PC, dal titolo della finestra di Spotify o di una scheda YouTube (nessun permesso extra)."""
    if listing is None:
        import screen_remote
        try: listing = screen_remote.windows()
        except Exception: listing = []
    tube = None
    for w in listing:
        exe, title = (w.get('exe') or '').lower(), (w.get('title') or '').strip()
        if exe == 'spotify.exe' and ' - ' in title and not title.lower().startswith('spotify'):
            artist, _, song = title.partition(' - ')
            return {'app': 'Spotify', 'title': song.strip(), 'artist': artist.strip()}
        if exe in BROWSERS and ' - YouTube' in title and not tube:
            song = title.split(' - YouTube')[0].strip()
            song = song[song.index(') ') + 2:] if song.startswith('(') and ') ' in song else song   # "(3) Brano"
            if song: tube = {'app': 'YouTube', 'title': song, 'artist': ''}
    return tube


def media(action: str, press=None) -> str:
    if action not in MEDIA_KEYS: raise ValueError('Comando multimediale non previsto')
    if press is None:
        def press(vk):
            u = ctypes.windll.user32; u.keybd_event(vk, 0, 0, 0); u.keybd_event(vk, 0, 2, 0)
    press(MEDIA_KEYS[action])
    return MEDIA_TEXT[action]


# ---------- appunti (solo testo) ----------
CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002


def _clip_api():
    from ctypes import wintypes
    u, k = ctypes.windll.user32, ctypes.windll.kernel32
    u.OpenClipboard.argtypes = [wintypes.HWND]; u.OpenClipboard.restype = wintypes.BOOL
    u.GetClipboardData.argtypes = [wintypes.UINT]; u.GetClipboardData.restype = wintypes.HANDLE
    u.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]; u.SetClipboardData.restype = wintypes.HANDLE
    k.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]; k.GlobalAlloc.restype = wintypes.HGLOBAL
    k.GlobalLock.argtypes = [wintypes.HGLOBAL]; k.GlobalLock.restype = ctypes.c_void_p
    k.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    k.GlobalFree.argtypes = [wintypes.HGLOBAL]
    return u, k


def _open_clipboard(u):
    for _ in range(10):           # un altro programma può tenerli occupati per un attimo
        if u.OpenClipboard(None): return True
        time.sleep(0.05)
    raise OSError('Appunti del PC occupati da un altro programma: riprova')


def clipboard_get() -> str:
    if os.name != 'nt': raise OSError('Appunti disponibili solo su Windows')
    u, k = _clip_api()
    _open_clipboard(u)
    try:
        h = u.GetClipboardData(CF_UNICODETEXT)
        if not h: return ''
        p = k.GlobalLock(h)
        try: return (ctypes.wstring_at(p) if p else '')[:CLIP_MAX]
        finally: k.GlobalUnlock(h)
    finally: u.CloseClipboard()


def clipboard_set(text: str) -> str:
    if os.name != 'nt': raise OSError('Appunti disponibili solo su Windows')
    text = str(text or '')
    if len(text) > CLIP_MAX: raise ValueError('Testo troppo lungo per gli appunti')
    u, k = _clip_api()
    data = (text + '\0').encode('utf-16-le')
    h = k.GlobalAlloc(GMEM_MOVEABLE, len(data))
    if not h: raise OSError('Memoria per gli appunti non disponibile')
    p = k.GlobalLock(h); ctypes.memmove(p, data, len(data)); k.GlobalUnlock(h)
    _open_clipboard(u)
    try:
        u.EmptyClipboard()
        if not u.SetClipboardData(CF_UNICODETEXT, h):
            k.GlobalFree(h); raise OSError('Appunti non aggiornati')
    finally: u.CloseClipboard()
    return f'Copiato negli appunti del PC ({len(text)} caratteri)'


# ---------- cartella condivisa ----------
def share_dir() -> Path:
    d = Path.home() / 'Downloads' / 'NEXAR'
    d.mkdir(parents=True, exist_ok=True)
    return d


def safe_name(name: str) -> str:
    name = BAD_NAME.sub('_', os.path.basename(str(name or '').replace('\\', '/'))).strip(' .')
    stem = name.split('.')[0].lower()
    if not name or stem in RESERVED: raise ValueError('Nome del file non valido')
    return name[:150]


def free_path(folder: Path, name: str) -> Path:
    target = folder / name
    stem, dot, ext = name.rpartition('.') if '.' in name.strip('.') else (name, '', '')
    i = 2
    while target.exists():
        target = folder / (f'{stem} ({i}).{ext}' if dot else f'{name} ({i})'); i += 1
    return target


def list_files(folder: Path | None = None):
    folder = folder or share_dir()
    items = []
    for f in folder.iterdir():
        if not f.is_file() or f.name.endswith('.part'): continue
        st = f.stat()
        items.append({'name': f.name, 'size': st.st_size, 'mtime': int(st.st_mtime)})
    return sorted(items, key=lambda x: -x['mtime'])[:200]


def shared_file(name: str, folder: Path | None = None) -> Path:
    folder = (folder or share_dir()).resolve()
    f = (folder / safe_name(name)).resolve()
    if f.parent != folder or not f.is_file(): raise FileNotFoundError('File non trovato nella cartella NEXAR')
    return f
