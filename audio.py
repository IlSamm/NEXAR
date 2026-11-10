"""Audio del PC: cuffie, casse e microfoni.

Con le API di Windows (Core Audio), senza programmi in più:
- dispositivi di uscita e di ingresso, quello predefinito, volume e muto;
- volume di ogni app (il mixer di Windows);
- il boost del microfono della scheda audio (+10/+20/+30 dB), dove il driver lo offre;
- niente abbassamento automatico degli altri suoni durante le chiamate.

Per andare OLTRE il 100% serve un filtro nel percorso audio di Windows: NEXAR usa Equalizer APO
(gratis, open source). Lo installa con un pulsante, dal file ufficiale controllato con l'impronta
SHA-256, e poi scrive solo il suo file nexar.txt: Equalizer APO lo rilegge da solo.
"""
import ctypes
import hashlib
import json
import os
import re
import threading
import time
import urllib.request
import uuid
from contextlib import contextmanager
from ctypes import POINTER, byref, c_float, c_uint, c_ulong, c_ushort, c_void_p, wintypes

RENDER, CAPTURE = 0, 1
MAX_BOOST = {'out': 18, 'in': 24}   # dB in più al massimo: oltre si sente solo distorsione
EQ_PRESETS = {
    'flat': '',
    'bass': 'GraphicEQ: 25 6; 40 6; 63 5; 100 4; 160 2; 250 0; 400 0; 630 0; 1000 0; 1600 0; 2500 0; 4000 0; 6300 0; 10000 0; 16000 0',
    'voice': 'GraphicEQ: 25 -12; 40 -10; 63 -8; 100 -5; 160 -2; 250 0; 400 0; 630 1; 1000 2; 1600 3; 2500 3; 4000 2; 6300 1; 10000 0; 16000 -1',
}
APO_CLSID = '{EACD2258-FCAC-4FF4-B36D-419E924A6D79}'
APO_SETUP = {   # file ufficiale su SourceForge, controllato prima di avviarlo
    'url': 'https://downloads.sourceforge.net/project/equalizerapo/1.4.2/EqualizerAPO-x64-1.4.2.exe',
    'name': 'EqualizerAPO-x64-1.4.2.exe', 'bytes': 11980366,
    'sha256': '7403be7427bbe1936a40dded082829b6e217fc4f5990fee5cba501f0ae055afa',
}
STOCK_CONFIG = ('Preamp: -6 dB', 'Include: example.txt')
FORM = {1: 'speakers', 2: 'line', 3: 'headphones', 4: 'mic', 5: 'headset', 6: 'handset', 7: 'digital', 8: 'spdif', 9: 'hdmi'}
_lock = threading.RLock()


# ---------------------------------------------------------------- COM con ctypes
class GUID(ctypes.Structure):
    _fields_ = [('d1', c_ulong), ('d2', c_ushort), ('d3', c_ushort), ('d4', ctypes.c_ubyte * 8)]


def _guid(s):
    return GUID.from_buffer_copy(uuid.UUID(s).bytes_le)


class PROPERTYKEY(ctypes.Structure):
    _fields_ = [('fmtid', GUID), ('pid', c_ulong)]


class PROPVARIANT(ctypes.Structure):
    _fields_ = [('vt', c_ushort), ('r1', c_ushort), ('r2', c_ushort), ('r3', c_ushort), ('p', c_void_p), ('p2', c_void_p)]


IID = {
    'enum': '{A95664D2-9614-4F35-A746-DE8DB63617E6}', 'endpoint': '{5CDF2C82-841E-4546-9722-0CF74078229A}',
    'sessions': '{77AA99A0-1BD6-484F-8BC7-2C654C9A9B6F}', 'control2': '{BFB7FF88-7239-4FC9-8FA2-07C950BE9C6D}',
    'simple': '{87CE5498-68D6-44E5-9215-6DA47EF883D8}', 'topology': '{2A07407E-6497-4A18-9787-32F79BD0D98F}',
    'part': '{AE2DE0E4-5BCA-4F2D-AA46-5D13F8FDB3A9}', 'level': '{7FB7B48F-531D-44A2-BCB3-5AD5A134B3DC}',
    'policy': '{F8679F50-850A-41CF-9C72-430F290290C8}',
}
CLSID_ENUM = '{BCDE0395-E52F-467C-8E3D-C4579291692E}'
CLSID_POLICY = '{870AF99C-171D-4F9E-AF0D-E63DF40C2BC9}'
PK_NAME = ('{A45C254E-DF1C-4EFD-8020-67D146A850E0}', 14)      # "Cuffie (Realtek USB Audio)"
PK_DESC = ('{A45C254E-DF1C-4EFD-8020-67D146A850E0}', 2)       # "Cuffie"
PK_ADAPTER = ('{026E516E-B814-414B-83CD-856D6FEF4822}', 2)    # "Realtek USB Audio"
PK_FORM = ('{1DA5D803-D492-4EDD-8C23-E0C0FFEE7F0E}', 0)


def _vcall(p, idx, argtypes=(), *args, restype=ctypes.HRESULT):
    vtbl = ctypes.cast(c_void_p(p), POINTER(POINTER(c_void_p)))[0]
    return ctypes.WINFUNCTYPE(restype, c_void_p, *argtypes)(vtbl[idx])(p, *args)


class Com:
    """Un oggetto COM: si rilascia da solo."""
    def __init__(self, p): self.p = p

    def call(self, idx, argtypes=(), *args, restype=ctypes.HRESULT):
        return _vcall(self.p, idx, argtypes, *args, restype=restype)

    def out(self, idx, argtypes=(), *args):
        o = c_void_p(); self.call(idx, (*argtypes, POINTER(c_void_p)), *args, byref(o))
        if not o.value: raise OSError('oggetto audio vuoto')
        return Com(o.value)

    def qi(self, iid):
        return self.out(0, (POINTER(GUID),), byref(_guid(IID[iid])))

    def activate(self, iid):   # IMMDevice::Activate (per IPart::Activate vedi _part_activate)
        return self.out(3, (POINTER(GUID), c_ulong, c_void_p), byref(_guid(IID[iid])), 23, None)

    def release(self):
        if self.p:
            try: _vcall(self.p, 2, restype=c_ulong)
            except Exception: pass
            self.p = None

    __del__ = release


def _wstr(p):
    """Stringa allocata da COM: la legge e la libera."""
    if not p: return ''
    try: return ctypes.wstring_at(p)
    finally: ctypes.windll.ole32.CoTaskMemFree(c_void_p(p))


@contextmanager
def _com():
    if os.name != 'nt': raise RuntimeError("L'audio si controlla solo su Windows")
    with _lock:
        ctypes.windll.ole32.CoInitializeEx(None, 0)   # già fatto in questo thread: nessun problema
        yield


def _enumerator():
    o = c_void_p()
    ctypes.oledll.ole32.CoCreateInstance(byref(_guid(CLSID_ENUM)), None, 23, byref(_guid(IID['enum'])), byref(o))
    return Com(o.value)


def _prop(store, key):
    pk = PROPERTYKEY(_guid(key[0]), key[1]); pv = PROPVARIANT()
    try: store.call(5, (POINTER(PROPERTYKEY), POINTER(PROPVARIANT)), byref(pk), byref(pv))
    except OSError: return None
    try:
        if pv.vt == 31: return ctypes.wstring_at(pv.p) if pv.p else ''
        if pv.vt in (19, 3): return (pv.p or 0) & 0xFFFFFFFF
        return None
    finally: ctypes.windll.ole32.PropVariantClear(byref(pv))


def _dev_id(dev):
    p = c_void_p(); dev.call(5, (POINTER(c_void_p),), byref(p)); return _wstr(p.value)


def _default_id(en, flow, role=0):
    try: return _dev_id(en.out(4, (c_uint, c_uint), flow, role))
    except OSError: return ''


def _devices(en, flow):
    col = en.out(3, (c_uint, c_uint), flow, 1)   # solo quelli attivi
    n = c_uint(); col.call(3, (POINTER(c_uint),), byref(n))
    for i in range(n.value):
        try: yield col.out(4, (c_uint,), i)
        except OSError: continue


def _get(en, dev_id):
    if not isinstance(dev_id, str) or not dev_id.startswith('{'): raise ValueError('Dispositivo audio non valido')
    try: return en.out(5, (wintypes.LPCWSTR,), dev_id)
    except OSError: raise ValueError('Dispositivo audio non trovato: forse è stato scollegato')


def _volume(dev):
    v = dev.activate('endpoint'); f = c_float(); m = wintypes.BOOL()
    v.call(9, (POINTER(c_float),), byref(f)); v.call(15, (POINTER(wintypes.BOOL),), byref(m))
    return v, round(f.value * 100), bool(m.value)


def guid_of(dev_id):
    m = re.search(r'\}\.(\{[0-9a-fA-F-]{36}\})$', dev_id or '')
    return m.group(1).lower() if m else ''


# ---------------------------------------------------------------- boost del microfono (scheda audio)
BOOST_WORDS = ('boost', 'amplif', 'potenz', 'verst', 'aumento', 'accentuation', 'refuerzo')


def _part_activate(part, iid):   # IPart::Activate(dwClsContext, refiid, ppv)
    return part.out(13, (c_ulong, POINTER(GUID)), 23, byref(_guid(IID[iid])))


def _boost_level(dev):
    """Il controllo "Amplificazione microfono" della scheda audio, se c'è."""
    try:
        topo = dev.activate('topology')
        conn = topo.out(4, (c_uint,), 0)
        start = conn.out(8).qi('part')       # dall'altra parte: la scheda audio
    except OSError: return None
    seen, todo = set(), [start]
    while todo and len(seen) < 60:
        part = todo.pop()
        try:
            gid = c_void_p(); part.call(5, (POINTER(c_void_p),), byref(gid)); gid = _wstr(gid.value)
        except OSError: continue
        if gid in seen: continue
        seen.add(gid)
        name = c_void_p()
        try: part.call(3, (POINTER(c_void_p),), byref(name)); name = _wstr(name.value)
        except OSError: name = ''
        if any(w in name.lower() for w in BOOST_WORDS):
            try:
                lvl = _part_activate(part, 'level')
                lo, hi, step, cur = c_float(), c_float(), c_float(), c_float()
                lvl.call(4, (c_uint, POINTER(c_float), POINTER(c_float), POINTER(c_float)), 0, byref(lo), byref(hi), byref(step))
                lvl.call(5, (c_uint, POINTER(c_float)), 0, byref(cur))
                if hi.value > lo.value: return lvl, name, lo.value, hi.value, step.value or 10.0, cur.value
            except OSError: pass
        try:
            parts = part.out(10)             # parti a monte: per un microfono, verso la presa
            n = c_uint(); parts.call(3, (POINTER(c_uint),), byref(n))
            for i in range(min(n.value, 16)):
                try: todo.append(parts.out(4, (c_uint,), i))
                except OSError: pass
        except OSError: pass
    return None


# ---------------------------------------------------------------- Equalizer APO (oltre il 100%)
def apo_paths():
    """(cartella del programma, cartella delle impostazioni), o None se non è installato davvero."""
    if os.name != 'nt': return None
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\EqualizerAPO') as k:
            install = winreg.QueryValueEx(k, 'InstallPath')[0]
            try: cfg = winreg.QueryValueEx(k, 'ConfigPath')[0]
            except OSError: cfg = os.path.join(install, 'config')
    except OSError: return None
    if not os.path.isfile(os.path.join(install, 'EqualizerAPO.dll')): return None   # rimasta solo la cartella
    return install, cfg


def apo_on(flow, guid):
    """Equalizer APO è attivo su questo dispositivo? (si sceglie una volta nella sua finestra dei dispositivi)"""
    if os.name != 'nt' or not guid: return False
    import winreg
    path = r'SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio\%s\%s\FxProperties' % ('Render' if flow == RENDER else 'Capture', guid)
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as k:
            i = 0
            while True:
                try: _, val, _ = winreg.EnumValue(k, i)
                except OSError: return False
                vals = val if isinstance(val, list) else [val]
                if any(isinstance(v, str) and APO_CLSID.lower() in v.lower() for v in vals): return True
                i += 1
    except OSError: return False


def apo_tool(paths=None):
    p = paths or apo_paths()
    if not p: return ''
    for exe in ('DeviceSelector.exe', 'Configurator.exe'):
        f = os.path.join(p[0], exe)
        if os.path.isfile(f): return f
    return ''


def apo_text(boosts: dict) -> str:
    """Il file nexar.txt: un blocco per ogni dispositivo amplificato."""
    out = ['# NEXAR · amplificatore audio. Lo riscrive NEXAR: le modifiche fatte a mano si perdono.']
    for guid, b in sorted(boosts.items()):
        db, eq = float(b.get('db') or 0), EQ_PRESETS.get(b.get('eq') or 'flat', '')
        if not re.fullmatch(r'\{[0-9a-f-]{36}\}', guid) or (db <= 0 and not eq): continue
        out += ['', f'Device: {guid}']
        if db > 0: out.append(f'Preamp: {db:g} dB')
        if eq: out.append(eq)
    out += ['', 'Device: all', '']
    return '\n'.join(out)


def _stock(lines):
    if lines[:2] != list(STOCK_CONFIG): return False
    for l in lines[2:]:
        if not l.startswith('GraphicEQ:'): return False
        try:
            if any(float(v.split()[1]) != 0 for v in l.split(':', 1)[1].split(';') if v.strip()): return False
        except (IndexError, ValueError): return False
    return True


def apo_write(boosts: dict, cfg_dir: str):
    """Scrive nexar.txt e si assicura che config.txt lo includa (una volta sola)."""
    with open(os.path.join(cfg_dir, 'nexar.txt'), 'w', encoding='utf-8') as h: h.write(apo_text(boosts))
    main = os.path.join(cfg_dir, 'config.txt')
    try:
        with open(main, encoding='utf-8-sig') as h: text = h.read()
    except OSError: text = ''
    if re.search(r'(?im)^\s*Include:\s*nexar\.txt\s*$', text): return
    lines = [l.strip() for l in text.splitlines() if l.strip() and not l.strip().startswith('#')]
    if not lines or _stock(lines):
        # la configurazione d'esempio abbassa tutto di 6 dB: la si mette da parte
        if text:
            with open(main + '.prima-di-nexar', 'w', encoding='utf-8') as h: h.write(text)
        new = 'Include: nexar.txt\n'
    else:
        new = text.rstrip('\n') + '\nInclude: nexar.txt\n'
    with open(main, 'w', encoding='utf-8') as h: h.write(new)


def _runas(exe, args='', hidden=False, wait=True):
    """Avvia con la finestra di conferma di Windows (UAC). False se l'utente dice di no."""
    class SEI(ctypes.Structure):
        _fields_ = [('cbSize', wintypes.DWORD), ('fMask', c_ulong), ('hwnd', wintypes.HWND), ('lpVerb', wintypes.LPCWSTR),
                    ('lpFile', wintypes.LPCWSTR), ('lpParameters', wintypes.LPCWSTR), ('lpDirectory', wintypes.LPCWSTR),
                    ('nShow', ctypes.c_int), ('hInstApp', wintypes.HINSTANCE), ('lpIDList', c_void_p), ('lpClass', wintypes.LPCWSTR),
                    ('hkeyClass', wintypes.HKEY), ('dwHotKey', wintypes.DWORD), ('hIcon', wintypes.HANDLE), ('hProcess', wintypes.HANDLE)]
    s = SEI(); s.cbSize = ctypes.sizeof(SEI); s.fMask = 0x40; s.lpVerb = 'runas'; s.lpFile = exe; s.lpParameters = args
    s.nShow = 0 if hidden else 1
    if not ctypes.windll.shell32.ShellExecuteExW(byref(s)): return False
    if wait and s.hProcess:
        ctypes.windll.kernel32.WaitForSingleObject(s.hProcess, 15 * 60 * 1000)
    if s.hProcess: ctypes.windll.kernel32.CloseHandle(s.hProcess)
    return True


class Installer:
    """Scarica e installa Equalizer APO in un thread; la dashboard legge lo stato."""
    def __init__(self, folder, log=print, fetch=None, runas=None):
        self.folder, self.log = folder, log
        self.fetch, self.runas = fetch or self._fetch, runas or _runas
        self.state = {'step': 'idle', 'pct': 0, 'error': ''}
        self.thread = None

    def info(self): return dict(self.state)

    def start(self):
        if self.thread and self.thread.is_alive(): return self.info()
        self.state = {'step': 'download', 'pct': 0, 'error': ''}
        self.thread = threading.Thread(target=self._run, daemon=True, name='audio-amp-setup'); self.thread.start()
        return self.info()

    def _fetch(self, url, dest):
        req = urllib.request.Request(url, headers={'User-Agent': 'NEXAR'})
        with urllib.request.urlopen(req, timeout=60) as r, open(dest, 'wb') as f:
            got = 0
            while True:
                b = r.read(1 << 16)
                if not b: break
                f.write(b); got += len(b); self.state['pct'] = min(99, got * 100 // APO_SETUP['bytes'])

    def _run(self):
        try:
            os.makedirs(self.folder, exist_ok=True)
            dest = os.path.join(self.folder, APO_SETUP['name'])
            ok = os.path.isfile(dest) and os.path.getsize(dest) == APO_SETUP['bytes'] and _sha(dest) == APO_SETUP['sha256']
            if not ok:
                for i in range(3):
                    try: self.fetch(APO_SETUP['url'], dest); break
                    except OSError as ex:
                        if i == 2: raise RuntimeError('Download non riuscito: controlla la connessione e riprova') from ex
                        time.sleep(3)
                if os.path.getsize(dest) != APO_SETUP['bytes'] or _sha(dest) != APO_SETUP['sha256']:
                    os.remove(dest); raise RuntimeError('Il file scaricato non è quello ufficiale: non lo avvio')
            self.state.update(step='install', pct=100)
            # una conferma sola: installazione silenziosa e poi la finestra per scegliere cuffie e microfono
            pf = os.environ.get('ProgramW6432') or os.environ.get('ProgramFiles') or r'C:\Program Files'
            sel = os.path.join(pf, 'EqualizerAPO')
            cmd = (f'/c "start "" /wait "{dest}" /S & if exist "{sel}\\DeviceSelector.exe" (start "" "{sel}\\DeviceSelector.exe") '
                   f'else if exist "{sel}\\Configurator.exe" (start "" "{sel}\\Configurator.exe")"')
            if not self.runas(os.path.join(os.environ.get('SystemRoot', r'C:\Windows'), 'System32', 'cmd.exe'), cmd, True):
                raise RuntimeError('Installazione annullata: serve il sì nella finestra di Windows')
            self.state.update(step='select')
            self.log('🔊 Amplificatore audio installato (Equalizer APO)')
        except Exception as ex:
            self.state.update(step='error', error=str(ex))


def _sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''): h.update(b)
    return h.hexdigest()


def open_selector():
    tool = apo_tool()
    if not tool: raise RuntimeError("L'amplificatore non è installato")
    if not _runas(tool, wait=False): raise RuntimeError('Annullato: serve il sì nella finestra di Windows')


# ---------------------------------------------------------------- abbassamento durante le chiamate
def ducking():
    """True se Windows abbassa gli altri suoni durante le chiamate (è così di serie)."""
    if os.name != 'nt': return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Multimedia\Audio') as k:
            return winreg.QueryValueEx(k, 'UserDuckingPreference')[0] != 3
    except OSError: return True


def set_ducking(on: bool):
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Multimedia\Audio') as k:
        winreg.SetValueEx(k, 'UserDuckingPreference', 0, winreg.REG_DWORD, 1 if on else 3)


# ---------------------------------------------------------------- quello che vede la dashboard
def overview(boosts=None) -> dict:
    boosts = boosts or {}
    apo = apo_paths()
    res = {'out': [], 'in': [], 'apps': [], 'ducking': ducking(),
           'apo': {'installed': bool(apo), 'tool': bool(apo_tool(apo)) if apo else False}}
    with _com():
        en = _enumerator()
        for flow, key in ((RENDER, 'out'), (CAPTURE, 'in')):
            default, comm = _default_id(en, flow, 0), _default_id(en, flow, 2)
            for dev in _devices(en, flow):
                try:
                    did = _dev_id(dev); store = dev.out(4, (c_uint,), 0)
                    _, vol, mute = _volume(dev)
                except OSError: continue
                g = guid_of(did); b = boosts.get(g) or {}
                d = {'id': did, 'name': _prop(store, PK_DESC) or _prop(store, PK_NAME) or 'Dispositivo audio',
                     'adapter': _prop(store, PK_ADAPTER) or '', 'kind': FORM.get(_prop(store, PK_FORM) or 0, 'other'),
                     'default': did == default, 'comm': did == comm, 'volume': vol, 'mute': mute,
                     'boost': {'db': float(b.get('db') or 0), 'eq': b.get('eq') or 'flat', 'max': MAX_BOOST[key],
                               'ready': bool(apo) and apo_on(flow, g)}}
                if flow == CAPTURE:
                    hw = _boost_level(dev)
                    if hw: d['hw'] = {'name': hw[1], 'min': hw[2], 'max': hw[3], 'step': hw[4], 'db': round(hw[5], 1)}
                res[key].append(d)
            res[key].sort(key=lambda d: (not d['default'], d['name'].lower()))
        try: res['apps'] = _apps(en)
        except OSError: res['apps'] = []
    return res


def _sessions(en):
    it = en.out(4, (c_uint, c_uint), RENDER, 0).activate('sessions').out(5)
    n = c_uint(); it.call(3, (POINTER(c_uint),), byref(n))
    for i in range(n.value):
        try:
            ctl = it.out(4, (c_uint,), i).qi('control2')
            st = c_uint(); ctl.call(3, (POINTER(c_uint),), byref(st))
            if st.value == 2: continue                               # sessione finita
            pid = c_ulong(); ctl.call(14, (POINTER(c_ulong),), byref(pid))
            system = ctl.call(15, restype=ctypes.c_long) == 0
            yield ctl, st.value, pid.value, system
        except OSError: continue


def _app_key(pid, system):
    if system: return 'system', 'Suoni di sistema'
    import psutil
    try: exe = psutil.Process(pid).name()
    except Exception: return None, None
    return exe.lower(), _pretty(exe)


def _apps(en):
    apps = {}
    for ctl, st, pid, system in _sessions(en):
        key, name = _app_key(pid, system)
        if not key: continue
        try:
            vol = ctl.qi('simple'); f = c_float(); m = wintypes.BOOL()
            vol.call(4, (POINTER(c_float),), byref(f)); vol.call(6, (POINTER(wintypes.BOOL),), byref(m))
        except OSError: continue
        a = apps.setdefault(key, {'id': key, 'name': name, 'volume': 0, 'mute': True, 'active': False})
        a['volume'] = max(a['volume'], round(f.value * 100)); a['mute'] = a['mute'] and bool(m.value)
        a['active'] = a['active'] or st == 1
    return sorted(apps.values(), key=lambda a: (a['id'] == 'system', not a['active'], a['name'].lower()))


def _pretty(exe):
    n = re.sub(r'\.exe$', '', exe, flags=re.I)
    n = re.sub(r'(?i)([-_ ]?(win64|win32|x64|x86|shipping))+$', '', n)    # FortniteClient-Win64-Shipping
    n = re.sub(r'(?<=[a-z])Client$', '', n) or n
    known = {'msedge': 'Microsoft Edge', 'chrome': 'Google Chrome', 'firefox': 'Firefox', 'spotify': 'Spotify', 'discord': 'Discord',
             'steam': 'Steam', 'steamwebhelper': 'Steam', 'vlc': 'VLC', 'teams': 'Teams', 'ms-teams': 'Teams', 'zoom': 'Zoom'}
    return known.get(n.lower(), n[:1].upper() + n[1:])


# ---------------------------------------------------------------- comandi
def set_device(dev_id, volume=None, mute=None):
    with _com():
        v, _, _ = _volume(_get(_enumerator(), dev_id))
        if volume is not None: v.call(7, (c_float, c_void_p), max(0.0, min(1.0, volume / 100)), None)
        if mute is not None: v.call(14, (wintypes.BOOL, c_void_p), bool(mute), None)


def set_default(dev_id):
    """Predefinito per tutto: giochi, musica e chiamate."""
    with _com():
        _get(_enumerator(), dev_id)
        o = c_void_p()
        ctypes.oledll.ole32.CoCreateInstance(byref(_guid(CLSID_POLICY)), None, 23, byref(_guid(IID['policy'])), byref(o))
        pol = Com(o.value)
        for role in (0, 1, 2): pol.call(13, (wintypes.LPCWSTR, c_uint), dev_id, role)


def set_hw_boost(dev_id, db):
    with _com():
        hw = _boost_level(_get(_enumerator(), dev_id))
        if not hw: raise ValueError('Questo microfono non ha il boost della scheda audio')
        lvl, _, lo, hi, step, _ = hw
        db = max(lo, min(hi, lo + round((float(db) - lo) / step) * step))
        lvl.call(7, (c_float, c_void_p), db, None)
        return db


def set_app(app_id, volume=None, mute=None):
    done = 0
    with _com():
        for ctl, _, pid, system in _sessions(_enumerator()):
            if _app_key(pid, system)[0] != app_id: continue
            try:
                vol = ctl.qi('simple')
                if volume is not None: vol.call(3, (c_float, c_void_p), max(0.0, min(1.0, volume / 100)), None)
                if mute is not None: vol.call(5, (wintypes.BOOL, c_void_p), bool(mute), None)
                done += 1
            except OSError: continue
    if not done: raise ValueError("Quest'app non sta usando l'audio")
    return done


def max_all():
    """Tutto al massimo senza amplificare: dispositivi predefiniti al 100%, senza muto, e ogni app al 100%."""
    with _com():
        en = _enumerator()
        for flow in (RENDER, CAPTURE):
            try:
                v, _, _ = _volume(en.out(4, (c_uint, c_uint), flow, 0))
                v.call(7, (c_float, c_void_p), 1.0, None); v.call(14, (wintypes.BOOL, c_void_p), False, None)
            except OSError: pass
        for ctl, *_ in _sessions(en):
            try:
                vol = ctl.qi('simple'); vol.call(3, (c_float, c_void_p), 1.0, None); vol.call(5, (wintypes.BOOL, c_void_p), False, None)
            except OSError: pass


if __name__ == '__main__':
    print(json.dumps(overview(), indent=1, ensure_ascii=False))
