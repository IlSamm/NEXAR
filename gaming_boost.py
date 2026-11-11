"""Gaming: libreria dei giochi installati, Gaming automatico quando parte un gioco e Gaming Boost.

Con la modalità Gaming NEXAR dà priorità al gioco, chiude o rallenta le app scelte dall'utente e prepara Windows
(Modalità gioco attiva, registrazione Xbox in background spenta, mouse senza accelerazione se richiesto).
Uscendo rimette tutto com'era, anche se nel frattempo NEXAR è stata riavviata (i valori originali sono salvati).

Niente viene chiuso senza che l'utente l'abbia scelto, e la chiusura è "gentile" (come la X della finestra):
se un programma chiede di salvare, resta aperto.
"""
from __future__ import annotations
import ctypes
import json
import logging
import os
import re
import subprocess
import threading
import time
from pathlib import Path

import psutil

GAME_FOLDERS = ('steamapps\\common', 'epic games', 'riot games', 'xboxgames', 'gog galaxy\\games', 'gog games',
                'ubisoft game launcher\\games', 'ea games', 'rockstar games')
# Eseguibili nelle cartelle dei giochi che non sono il gioco: launcher, crash reporter, anti-cheat, installer.
HELPER_HINTS = ('launcher', 'crashhandler', 'crashreport', 'riotclient', 'cefsubprocess', 'webhelper', 'easyanticheat',
                'battleye', 'beservice', 'updater', 'installer', 'setup', 'redist', 'dxsetup', 'uninst', 'vgc.exe', 'vgtray')
# A schermo intero ma non sono giochi (video, riunioni, presentazioni).
FULLSCREEN_SKIP = {'chrome.exe', 'msedge.exe', 'firefox.exe', 'brave.exe', 'opera.exe', 'vivaldi.exe', 'vlc.exe',
                   'mpc-hc64.exe', 'potplayermini64.exe', 'wmplayer.exe', 'microsoft.media.player.exe', 'video.ui.exe',
                   'powerpnt.exe', 'zoom.exe', 'ms-teams.exe', 'teams.exe', 'discord.exe', 'spotify.exe', 'chatgpt.exe',
                   'claude.exe', 'code.exe', 'photos.exe', 'netflix.exe', 'obs64.exe'}
# Mai toccati: sistema, NEXAR e gli strumenti che la fanno funzionare.
PROTECTED = {'system', 'registry', 'smss.exe', 'csrss.exe', 'wininit.exe', 'winlogon.exe', 'services.exe', 'lsass.exe',
             'svchost.exe', 'explorer.exe', 'dwm.exe', 'sihost.exe', 'fontdrvhost.exe', 'ctfmon.exe', 'searchhost.exe',
             'startmenuexperiencehost.exe', 'shellexperiencehost.exe', 'runtimebroker.exe', 'taskhostw.exe', 'conhost.exe',
             'audiodg.exe', 'nexar.exe', 'cloudflared.exe', 'openrgb.exe', 'fancontrol.exe', 'librehardwaremonitor.exe',
             'securityhealthsystray.exe', 'msmpeng.exe', 'nvcontainer.exe', 'nvdisplay.container.exe', 'textinputhost.exe',
             'applicationframehost.exe', 'lockapp.exe', 'widgets.exe', 'useroobebroker.exe', 'python.exe', 'pythonw.exe',
             'msedgewebview2.exe', 'nvidia share.exe', 'nvidia overlay.exe', 'gamebar.exe', 'gamebarftserver.exe',
             'steam.exe', 'steamwebhelper.exe', 'epicgameslauncher.exe', 'riotclientservices.exe', 'vgc.exe', 'vgtray.exe'}
TWEAKS = {
    # chiave: (descrizione, hive, percorso, nome, valore in Gaming, opzione che lo attiva)
    'game_mode': ('Modalità gioco di Windows', 'HKCU', r'Software\Microsoft\GameBar', 'AutoGameModeEnabled', 1, 'game_mode'),
    'no_dvr': ('Registrazione Xbox in background spenta', 'HKCU', r'System\GameConfigStore', 'GameDVR_Enabled', 0, 'no_dvr'),
    'no_capture': ('Acquisizione Game Bar spenta', 'HKCU', r'Software\Microsoft\Windows\CurrentVersion\GameDVR', 'AppCaptureEnabled', 0, 'no_dvr'),
}
OPTIONS = ('game_priority', 'game_mode', 'no_dvr', 'reopen', 'auto', 'mouse', 'stop_junk', 'eco_throttle', 'covers_online')
DEFAULTS = {'game_priority': True, 'game_mode': True, 'no_dvr': True, 'reopen': True, 'auto': True, 'mouse': False, 'apps': {}, 'hidden': [],
            'eco_apps': {}, 'stop_junk': True, 'eco_throttle': True, 'covers_online': True, 'per_game': {}}
# Scelte di un singolo gioco. None = come le impostazioni generali di Gaming; per le luci '' = non cambiarle.
PROFILE_DEFAULT = {'auto': True, 'fans': '', 'rgb': None, 'mouse': None}
GAME_ID = re.compile(r'[a-z]+-[A-Za-z0-9_-]{1,70}')
HIGH, BELOW = (psutil.HIGH_PRIORITY_CLASS, psutil.BELOW_NORMAL_PRIORITY_CLASS) if os.name == 'nt' else (-5, 5)
PROGRAMDATA = Path(os.environ.get('PROGRAMDATA', r'C:\ProgramData'))

def is_helper(name: str) -> bool:
    low = (name or '').lower()
    return any(h in low for h in HELPER_HINTS)

def is_game(exe: str, name: str = '') -> bool:
    low = (exe or '').lower()
    return any(f in low for f in GAME_FOLDERS) and not is_helper(name or os.path.basename(low))

def norm(path) -> str:
    return os.path.normcase(os.path.normpath(str(path))).rstrip('\\/') + os.sep

def pretty(name: str) -> str:
    base = re.sub(r'(?i)(-win64)?(-shipping)?\.exe$', '', name or '')
    return base.replace('_', ' ').strip() or name

# ---------------- libreria ----------------
STEAM_SKIP = re.compile(r'redistributable|steam linux runtime|proton|steamvr|soundtrack|dedicated server|\bsdk\b|steamworks', re.I)
# Steam salva le immagini con nomi diversi a seconda della versione: si prova il primo che c'è.
COVER_KINDS = {'header': ('header', 'library_header'), 'hero': ('library_hero',), 'logo': ('logo',),
               'capsule': ('library_600x900', 'library_capsule')}
# Programmi venduti su Steam che non sono giochi (sfondi animati, driver controller, scaling, audio, benchmark).
STEAM_SOFTWARE = {'431960', '1812620', '993090', '365670', '250820', '629520', '223850', '1840', '388080', '1254120',
                  '813780', '1070560', '1391110', '1628350', '2180100', '1493710', '228980'}

def _reg_value(root, path, name):
    import winreg
    try:
        with winreg.OpenKey(root, path) as k: return winreg.QueryValueEx(k, name)[0]
    except OSError: return None

def steam_root():
    if os.name != 'nt': return None
    import winreg
    p = _reg_value(winreg.HKEY_CURRENT_USER, r'Software\Valve\Steam', 'SteamPath')
    return Path(p) if p and Path(p).is_dir() else None

def _acf(text: str) -> dict:
    """Chiavi del primo livello di un file .acf/.vdf di Steam (le prime occorrenze vincono)."""
    out = {}
    for k, v in re.findall(r'^\s*"([^"]+)"\s+"([^"]*)"', text, re.M): out.setdefault(k, v)
    return out

def steam_library_paths(root: Path):
    paths = [root]
    try:
        text = (root / 'steamapps' / 'libraryfolders.vdf').read_text(encoding='utf-8', errors='replace')
        paths += [Path(p.replace('\\\\', '\\')) for p in re.findall(r'"path"\s+"([^"]+)"', text)]
    except OSError: pass
    return paths

def steam_image(appid: str, kind: str = 'header'):
    root = steam_root()
    if not root or not appid.isdigit() or kind not in COVER_KINDS: return None
    cache = root / 'appcache' / 'librarycache'
    ext = '.png' if kind == 'logo' else '.jpg'
    folder = cache / appid
    for name in COVER_KINDS[kind]:
        old = cache / f'{appid}_{name}{ext}'
        if old.is_file(): return old
        if folder.is_dir():
            for f in folder.rglob(name + ext): return f
    return None

def steam_games(root=None, skipped=None):
    """Giochi installati con Steam; in `skipped` finiscono le cartelle dei programmi che non sono giochi."""
    root = root or steam_root()
    out, seen = [], set()
    skipped = skipped if skipped is not None else []
    if not root: return out
    for lib in steam_library_paths(root):
        apps = lib / 'steamapps'
        if not apps.is_dir(): continue
        for m in apps.glob('appmanifest_*.acf'):
            try: a = _acf(m.read_text(encoding='utf-8', errors='replace'))
            except OSError: continue
            appid, name, inst = a.get('appid', ''), a.get('name', ''), a.get('installdir', '')
            if not appid.isdigit() or appid in seen or not name or not inst: continue
            folder = apps / 'common' / inst
            if appid in STEAM_SOFTWARE or STEAM_SKIP.search(name):
                skipped.append(str(folder)); continue
            if not int(a.get('StateFlags') or 0) & 4: continue   # 4 = installato del tutto
            if not folder.is_dir(): continue
            seen.add(appid)
            out.append({'id': 'steam-' + appid, 'name': name, 'store': 'Steam', 'dir': str(folder),
                        'size': int(a.get('SizeOnDisk') or 0), 'last': int(a.get('LastPlayed') or 0),
                        'launch': 'steam://rungameid/' + appid, 'cover': steam_image(appid) is not None})
    return out

def epic_games(base=None):
    base = base or PROGRAMDATA / 'Epic' / 'EpicGamesLauncher' / 'Data' / 'Manifests'
    found = {}
    if not base.is_dir(): return []
    for f in base.glob('*.item'):
        try: j = json.loads(f.read_text(encoding='utf-8', errors='replace'))
        except (OSError, ValueError): continue
        app = str(j.get('AppName') or '')
        folder = Path(str(j.get('InstallLocation') or ''))
        if not app or j.get('bIsApplication') is False or 'games' not in (j.get('AppCategories') or []): continue
        if not str(j.get('InstallLocation') or '') or not folder.is_dir(): continue
        ns, item = j.get('CatalogNamespace') or '', j.get('CatalogItemId') or ''
        ref = f'{ns}%3A{item}%3A{app}' if ns and item else app
        exe = folder / str(j.get('LaunchExecutable') or '')
        found[app] = {'id': 'epic-' + re.sub(r'[^A-Za-z0-9_-]', '', app)[:60], 'name': str(j.get('DisplayName') or app),
                      'store': 'Epic', 'dir': str(folder), 'size': int(j.get('InstallSize') or 0), 'last': 0,
                      'launch': f'com.epicgames.launcher://apps/{ref}?action=launch&silent=true', 'cover': False,
                      'exe': str(exe) if j.get('LaunchExecutable') and exe.is_file() else ''}
    return list(found.values())

RIOT_PRODUCTS = {'valorant': ('VALORANT', 'valorant'), 'league of legends': ('League of Legends', 'league_of_legends')}

def riot_games(base=None):
    base = base or PROGRAMDATA / 'Riot Games'
    try: j = json.loads((base / 'RiotClientInstalls.json').read_text(encoding='utf-8', errors='replace'))
    except (OSError, ValueError): return []
    out = []
    for path, client in (j.get('associated_client') or {}).items():
        d = Path(path)
        folder = d.parent if d.name.lower() in ('live', 'pbe') else d
        prod = RIOT_PRODUCTS.get(folder.name.lower())
        client = client if Path(str(client)).is_file() else j.get('rc_default') or ''
        if not prod or not folder.is_dir() or not Path(str(client)).is_file(): continue
        # Il client di Riot tiene l'iscrizione anche dopo la disinstallazione: cartella vuota = gioco non installato.
        try:
            if not d.is_dir() or not any(d.iterdir()): continue
        except OSError: continue
        exes = sorted(d.glob('*.exe'), key=lambda x: -x.stat().st_size)
        out.append({'id': 'riot-' + prod[1], 'name': prod[0], 'store': 'Riot', 'dir': str(folder), 'size': 0, 'last': 0,
                    'launch': [str(client), f'--launch-product={prod[1]}', '--launch-patchline=live'], 'cover': False,
                    'exe': str(exes[0]) if exes else ''})
    return out

def gog_games():
    if os.name != 'nt': return []
    import winreg
    out = []
    try: key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\WOW6432Node\GOG.com\Games')
    except OSError: return out
    with key:
        for i in range(400):
            try: sub = winreg.EnumKey(key, i)
            except OSError: break
            try:
                with winreg.OpenKey(key, sub) as g:
                    name, exe, path = (winreg.QueryValueEx(g, n)[0] for n in ('gameName', 'exe', 'path'))
            except OSError: continue
            if Path(exe).is_file() and Path(path).is_dir():
                out.append({'id': 'gog-' + re.sub(r'\D', '', sub)[:20], 'name': name, 'store': 'GOG', 'dir': path,
                            'size': 0, 'last': 0, 'launch': [exe], 'cwd': path, 'cover': False, 'exe': exe})
    return out

def exe_icon(exe: str, dest: Path, size: int = 256):
    """Icona grande (256 px) dell'eseguibile del gioco, salvata come PNG: copertina per Epic, Riot e GOG
    senza scaricare niente da internet."""
    if os.name != 'nt' or not exe or not Path(exe).is_file(): return None
    from ctypes import wintypes
    from PIL import Image
    class ICONINFO(ctypes.Structure):
        _fields_ = [('fIcon', wintypes.BOOL), ('x', wintypes.DWORD), ('y', wintypes.DWORD), ('mask', wintypes.HBITMAP), ('color', wintypes.HBITMAP)]
    class BITMAP(ctypes.Structure):
        _fields_ = [('type', wintypes.LONG), ('w', wintypes.LONG), ('h', wintypes.LONG), ('wb', wintypes.LONG),
                    ('planes', wintypes.WORD), ('bpp', wintypes.WORD), ('bits', ctypes.c_void_p)]
    class BMI(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('w', wintypes.LONG), ('h', wintypes.LONG), ('planes', wintypes.WORD), ('bits', wintypes.WORD),
                    ('comp', wintypes.DWORD), ('img', wintypes.DWORD), ('xp', wintypes.LONG), ('yp', wintypes.LONG),
                    ('used', wintypes.DWORD), ('imp', wintypes.DWORD)]
    u32, g32, s32 = ctypes.WinDLL('user32'), ctypes.WinDLL('gdi32'), ctypes.WinDLL('shell32')
    s32.SHDefExtractIconW.argtypes = [wintypes.LPCWSTR, ctypes.c_int, wintypes.UINT, ctypes.POINTER(wintypes.HICON), ctypes.c_void_p, wintypes.UINT]
    u32.GetIconInfo.argtypes = [wintypes.HICON, ctypes.POINTER(ICONINFO)]
    g32.GetObjectW.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p]
    u32.GetDC.restype = wintypes.HDC; u32.GetDC.argtypes = [wintypes.HWND]
    u32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    g32.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT, ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT]
    g32.DeleteObject.argtypes = [wintypes.HANDLE]; u32.DestroyIcon.argtypes = [wintypes.HICON]
    hicon = wintypes.HICON()
    if s32.SHDefExtractIconW(str(exe), 0, 0, ctypes.byref(hicon), None, size) != 0 or not hicon: return None
    ii = ICONINFO(); u32.GetIconInfo(hicon, ctypes.byref(ii))
    try:
        bm = BITMAP(); g32.GetObjectW(ii.color, ctypes.sizeof(bm), ctypes.byref(bm))
        w, h = bm.w, bm.h
        if not 16 <= w <= 512 or not 16 <= h <= 512: return None
        bmi = BMI(size=40, w=w, h=-h, planes=1, bits=32)
        buf = ctypes.create_string_buffer(w * h * 4); dc = u32.GetDC(None)
        g32.GetDIBits(dc, ii.color, 0, h, buf, ctypes.byref(bmi), 0); u32.ReleaseDC(None, dc)
    finally:
        for b in (ii.color, ii.mask):
            if b: g32.DeleteObject(b)
        u32.DestroyIcon(hicon)
    img = Image.frombuffer('RGBA', (w, h), buf.raw, 'raw', 'BGRA', 0, 1)
    if img.getextrema()[3][1] == 0: img.putalpha(255)   # icone vecchie senza trasparenza
    img = img.crop(img.getbbox() or (0, 0, w, h))
    if max(img.size) < 64: return None                  # troppo piccola per fare da copertina
    dest.parent.mkdir(parents=True, exist_ok=True); img.save(dest, 'PNG')
    return dest

_lib_cache = {'at': 0.0, 'games': [], 'skipped': []}
_lib_lock = threading.Lock()

def library(force=False):
    """Giochi installati (Steam, Epic, Riot, GOG). Lettura solo dei file dei launcher, tenuta in cache 2 minuti."""
    with _lib_lock:
        if not force and time.monotonic() - _lib_cache['at'] < 120: return list(_lib_cache['games'])
        games, skipped = [], []
        for source in (lambda: steam_games(skipped=skipped), epic_games, riot_games, gog_games):
            try: games += source()
            except Exception: logging.exception('Libreria giochi')
        _lib_cache.update(at=time.monotonic(), games=games, skipped=skipped)
        return list(games)

def skipped_dirs():
    """Cartelle di Steam con programmi che non sono giochi (Wallpaper Engine, DSX…): mai Gaming per loro."""
    library()
    return list(_lib_cache['skipped'])

def launch(game: dict):
    """Avvia dal suo launcher: Steam/Epic con il loro link, Riot e GOG con il loro eseguibile."""
    how = game['launch']
    if isinstance(how, str):
        if not re.match(r'^(steam://rungameid/\d+|com\.epicgames\.launcher://apps/[A-Za-z0-9%_.-]+\?action=launch&silent=true)$', how):
            raise ValueError('Avvio non previsto')
        os.startfile(how)
    else:
        subprocess.Popen(how, cwd=game.get('cwd') or None, close_fds=True,
                         creationflags=getattr(subprocess, 'DETACHED_PROCESS', 0) | getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0))

# ---------------- processi ----------------
def foreground_window():
    """(PID della finestra in primo piano, è a schermo intero?)"""
    if os.name != 'nt': return None, False
    u = ctypes.windll.user32
    hwnd = u.GetForegroundWindow()
    if not hwnd: return None, False
    pid = ctypes.c_ulong()
    u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    class RECT(ctypes.Structure): _fields_ = [('l', ctypes.c_long), ('t', ctypes.c_long), ('r', ctypes.c_long), ('b', ctypes.c_long)]
    class MONITORINFO(ctypes.Structure): _fields_ = [('cbSize', ctypes.c_ulong), ('rcMonitor', RECT), ('rcWork', RECT), ('dwFlags', ctypes.c_ulong)]
    win, mi = RECT(), MONITORINFO(ctypes.sizeof(MONITORINFO))
    if not u.GetWindowRect(hwnd, ctypes.byref(win)) or not u.GetMonitorInfoW(u.MonitorFromWindow(hwnd, 2), ctypes.byref(mi)):
        return pid.value or None, False
    m = mi.rcMonitor
    return pid.value or None, (win.l, win.t, win.r, win.b) == (m.l, m.t, m.r, m.b)

def user_apps():
    """App aperte dall'utente (un elemento per eseguibile), tra cui scegliere cosa chiudere o rallentare in Gaming."""
    me = psutil.Process().username() if os.name == 'nt' else None
    apps = {}
    for p in psutil.process_iter(['name', 'exe', 'username', 'memory_info']):
        try:
            name = (p.info['name'] or '').lower()
            if not name or name in PROTECTED or not p.info['exe'] or (me and p.info['username'] != me): continue
            if p.info['exe'].lower().startswith(os.environ.get('WINDIR', r'C:\Windows').lower()): continue
            a = apps.setdefault(name, {'name': name, 'exe': p.info['exe'], 'bytes': 0, 'count': 0, 'game': is_game(p.info['exe'], name)})
            a['bytes'] += p.info['memory_info'].rss; a['count'] += 1
        except (psutil.Error, AttributeError, TypeError): continue
    return sorted(apps.values(), key=lambda a: -a['bytes'])

def _reg(hive, path, name, value=None, delete=False):
    import winreg
    root = winreg.HKEY_CURRENT_USER if hive == 'HKCU' else winreg.HKEY_LOCAL_MACHINE
    if value is None and not delete:
        try:
            with winreg.OpenKey(root, path) as k: return winreg.QueryValueEx(k, name)[0]
        except OSError: return None
    with winreg.CreateKey(root, path) as k:
        if delete:
            try: winreg.DeleteValue(k, name)
            except OSError: pass
        else: winreg.SetValueEx(k, name, 0, winreg.REG_DWORD, int(value))

def mouse_accel(value=None):
    """Legge o imposta [soglia1, soglia2, accelerazione] del mouse (0,0,0 = movimento 1:1, come i giocatori)."""
    arr = (ctypes.c_int * 3)()
    u = ctypes.windll.user32
    if value is None:
        if not u.SystemParametersInfoW(3, 0, arr, 0): raise OSError('mouse non leggibile')   # SPI_GETMOUSE
        return list(arr)
    arr[:] = [int(v) for v in value]
    if not u.SystemParametersInfoW(4, 0, arr, 3): raise OSError('mouse non impostabile')    # SPI_SETMOUSE, salva e avvisa

def fmt_duration(seconds) -> str:
    m = int(seconds // 60); h = m // 60
    return f'{h} h {m % 60} min' if h else f'{m} min'

class Booster:
    def __init__(self, config: dict, state=None, save=lambda: None, notify=lambda m: None, log=lambda m: None):
        self.config, self.notify, self.log = config, notify, log
        self.state = state if state is not None else {}
        self.save = save
        self.lock = threading.RLock()
        self.active = False
        self.saved_tweaks = {}     # chiave -> valore originale (None = non esisteva)
        self.saved_mouse = None
        self.boosted = {}          # pid -> (nome, priorità originale)
        self.lowered = {}
        self.closed = []           # app chiuse da riaprire: {name, exe, cmdline, cwd}
        self.game = ''
        self.running = None        # gioco aperto adesso (anche fuori da Gaming)
        self.seen_fg = set()       # PID passati in primo piano: un gioco vero lo è, un programma di sfondo no
        self.session = None

    # ---------- impostazioni ----------
    def settings(self):
        return {**DEFAULTS, **self.config.setdefault('gaming_boost', {})}

    def update_settings(self, new: dict):
        """Opzioni e scelte per app (close / lower / nessuna) salvate in config['gaming_boost']."""
        cur = self.config.setdefault('gaming_boost', {})
        for k in OPTIONS:
            if k in new:
                if type(new[k]) is not bool: raise ValueError(f'{k}: true/false')
                cur[k] = new[k]
        for key in ('apps', 'eco_apps'):   # scelte per app in Gaming e in AI ECO ("keep" = lascia anche se inutile)
            if key not in new: continue
            apps = new[key]
            if not isinstance(apps, dict) or len(apps) > 80: raise ValueError(key + ' non valido')
            clean = {}
            for name, act in apps.items():
                name = str(name).lower()
                if act not in ('close', 'lower', 'keep') or name in PROTECTED or not name.endswith('.exe') or len(name) > 80: continue
                clean[name] = act
            cur[key] = clean
        if 'hidden' in new:
            hidden = new['hidden']
            if not isinstance(hidden, list) or len(hidden) > 200: raise ValueError('hidden non valido')
            cur['hidden'] = sorted({str(h) for h in hidden if re.fullmatch(r'[a-z]+-[A-Za-z0-9_-]{1,70}', str(h))})
        return self.settings()

    # ---------- libreria ----------
    def games(self, force=False):
        played = self.state.get('games') or {}
        hidden = set(self.settings()['hidden'])
        out = []
        for g in library(force):
            p = played.get(g['id']) or {}
            out.append({**g, 'playtime': int(p.get('seconds', 0)), 'last': max(int(p.get('last', 0)), g['last']),
                        'sessions': int(p.get('sessions', 0)), 'hidden': g['id'] in hidden})
        return sorted(out, key=lambda g: (-g['last'], g['name'].lower()))

    # ---------- un gioco alla volta ----------
    def game_profile(self, gid):
        p = (self.settings().get('per_game') or {}).get(gid) or {}
        return {k: p.get(k, v) for k, v in PROFILE_DEFAULT.items()}

    def set_game_profile(self, gid, new: dict):
        if not isinstance(gid, str) or not GAME_ID.fullmatch(gid): raise ValueError('Gioco non valido')
        cur = self.game_profile(gid)
        if 'auto' in new:
            if type(new['auto']) is not bool: raise ValueError('auto: true/false')
            cur['auto'] = new['auto']
        if 'fans' in new:
            if new['fans'] not in ('', 'normal', 'max', None): raise ValueError('Ventole: normali o massimo')
            cur['fans'] = new['fans'] or ''
        if 'rgb' in new:
            v = new['rgb']
            if v is not None and v != '' and not re.fullmatch(r'#[0-9a-fA-F]{6}', str(v)): raise ValueError('Colore non valido')
            cur['rgb'] = v.lower() if v else v
        if 'mouse' in new:
            if new['mouse'] is not None and type(new['mouse']) is not bool: raise ValueError('mouse: true/false')
            cur['mouse'] = new['mouse']
        clean = {k: v for k, v in cur.items() if v != PROFILE_DEFAULT[k]}
        per = self.config.setdefault('gaming_boost', {}).setdefault('per_game', {})
        if clean: per[gid] = clean
        else: per.pop(gid, None)
        if len(per) > 300: raise ValueError('Troppi giochi personalizzati')
        return self.game_profile(gid)

    def game_mouse(self, want):
        """Mira precisa scelta per il gioco aperto: True la accende, False la toglie, None lascia la scelta generale."""
        if os.name != 'nt' or want is None: return ''
        with self.lock:
            if not self.active: return ''
            try:
                if want and not self.saved_mouse:
                    self.saved_mouse = mouse_accel(); mouse_accel([0, 0, 0]); note = 'mouse 1:1'
                elif not want and self.saved_mouse:
                    mouse_accel(self.saved_mouse); self.saved_mouse = None; note = 'mouse come sempre'
                else: return ''
            except OSError as ex:
                logging.warning('Mouse del gioco: %s', ex); return ''
            self.state['boost_saved'] = {**(self.state.get('boost_saved') or {}), 'mouse': self.saved_mouse}
        self.save()
        return note

    def find(self, gid):
        return next((g for g in library() if g['id'] == gid), None)

    def history(self):
        return list(self.state.get('gaming_history') or [])

    def info(self):
        with self.lock:
            return {'active': self.active, 'game': self.game, 'boosted': sorted({n for n, _ in self.boosted.values()}),
                    'lowered': sorted({n for n, _ in self.lowered.values()}), 'closed': [c['name'] for c in self.closed],
                    'tweaks': [TWEAKS[k][0] for k in self.saved_tweaks] + (['Mouse senza accelerazione'] if self.saved_mouse else []),
                    'running': {k: self.running[k] for k in ('id', 'name', 'store')} if self.running else None,
                    'session': self.session_view(), 'settings': self.settings()}

    # ---------- avvio / stop ----------
    def start(self):
        if os.name != 'nt': return 'Gaming Boost disponibile solo su Windows'
        s = self.settings(); notes = []
        with self.lock:
            if self.active: return 'Gaming Boost già attivo'
            self.active = True
            # Valori originali salvati: se NEXAR si chiude in Gaming, al riavvio si ripristinano quelli veri.
            saved = self.state.get('boost_saved') or {}
            for key, (label, hive, path, name, value, option) in TWEAKS.items():
                if not s.get(option): continue
                try:
                    self.saved_tweaks[key] = saved['tweaks'][key] if key in (saved.get('tweaks') or {}) else _reg(hive, path, name)
                    _reg(hive, path, name, value)
                except OSError as ex: logging.warning('Gaming Boost %s: %s', key, ex)
            if s.get('mouse'):
                try:
                    self.saved_mouse = saved.get('mouse') or mouse_accel()
                    mouse_accel([0, 0, 0])
                except OSError as ex: logging.warning('Gaming Boost mouse: %s', ex)
            self.state['boost_saved'] = {'tweaks': dict(self.saved_tweaks), 'mouse': self.saved_mouse}
            self.save()
            if self.saved_tweaks or self.saved_mouse: notes.append('Windows pronto per giocare')
            self.session = {'start': time.time(), 'last': time.time(), 'game': '', 'gid': '', 'wh': 0.0}
        closed = self.close_apps([n for n, act in s['apps'].items() if act == 'close'])
        if closed: notes.append('chiuse ' + ', '.join(closed))
        self.tick()
        msg = 'Gaming Boost attivo' + (': ' + '; '.join(notes) if notes else '')
        self.log(msg)
        return msg

    def close_apps(self, names):
        """Chiusura gentile (come la X): chi ha lavoro non salvato può rifiutarsi e resta aperto."""
        done = []
        for name in names:
            if name in PROTECTED: continue
            procs = [p for p in psutil.process_iter(['name', 'exe', 'cmdline', 'cwd']) if (p.info['name'] or '').lower() == name]
            if not procs: continue
            main = next((p for p in procs if p.info['cmdline'] and len(p.info['cmdline']) <= 2), procs[0])
            info = {'name': name, 'exe': main.info['exe'], 'cmdline': main.info['cmdline'] or [main.info['exe']], 'cwd': main.info['cwd']}
            subprocess.run(['taskkill', '/im', name], capture_output=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            gone, alive = psutil.wait_procs(procs, timeout=6)
            if not alive or len(gone) >= len(procs) / 2:
                with self.lock: self.closed.append(info)
                done.append(name.replace('.exe', ''))
        return done

    def tick(self):
        """Ogni pochi secondi: trova il gioco aperto; in Gaming dà priorità alta al gioco e bassa alle app scelte.
        Restituisce il gioco aperto (o None): serve anche al Gaming automatico."""
        s = self.settings()
        hidden = set(s['hidden'])
        games = library()
        dirs = [(norm(g['dir']), g) for g in games if g['id'] not in hidden]
        hidden_dirs = [norm(g['dir']) for g in games if g['id'] in hidden] + [norm(d) for d in skipped_dirs()]
        with self.lock: active = self.active
        fg, full_screen = foreground_window()
        if fg: self.seen_fg.add(fg)
        fg = fg if full_screen else None
        lower = {n for n, act in s['apps'].items() if act == 'lower'}
        found, alive = None, set()
        for p in psutil.process_iter(['name', 'exe']):
            try:
                alive.add(p.pid)
                name = (p.info['name'] or '').lower()
                exe = p.info['exe'] or ''
                if not name or name in PROTECTED: continue
                path = norm(exe) if exe else ''
                lib = next((g for d, g in dirs if path.startswith(d)), None) if path and not is_helper(name) else None
                # Conta solo se è passato in primo piano: i programmi di sfondo nelle cartelle dei giochi no.
                game = p.pid in self.seen_fg and (lib is not None or (is_game(exe, name) and not any(path.startswith(d) for d in hidden_dirs)))
                if not game: lib = None
                if game and (found is None or (lib and not found.get('store'))):
                    found = ({k: lib[k] for k in ('id', 'name', 'store')} if lib else {'id': 'proc-' + name[:-4], 'name': pretty(name), 'store': ''})
                if not active: continue
                full = p.pid == fg and name not in FULLSCREEN_SKIP
                if s['game_priority'] and (game or full) and p.pid not in self.boosted:
                    old = p.nice(); p.nice(HIGH)
                    with self.lock: self.boosted[p.pid] = (name, old)
                    if full and not game and not found: found = {'id': 'proc-' + name[:-4], 'name': pretty(name), 'store': ''}
                elif name in lower and p.pid not in self.lowered:
                    old = p.nice(); p.nice(BELOW)
                    with self.lock: self.lowered[p.pid] = (name, old)
            except (psutil.Error, OSError): continue
        self.seen_fg &= alive
        with self.lock:
            self.running = found
            if active and found:
                self.game = found['name']
                if self.session is not None and not self.session['gid']:
                    self.session.update(game=found['name'], gid=found['id'])
        return found

    # ---------- statistiche della sessione ----------
    def sample(self, t: dict):
        """Ogni pochi secondi in Gaming: temperature, carico e consumo per il riepilogo della partita."""
        with self.lock:
            s = self.session
            if s is None: return
            now = time.time(); dt = min(30.0, max(0.0, now - s['last'])); s['last'] = now
            for k in ('cpu_temp', 'gpu_temp', 'cpu', 'gpu'):
                v = t.get(k)
                if isinstance(v, (int, float)):
                    s['sum_' + k] = s.get('sum_' + k, 0.0) + v; s['n_' + k] = s.get('n_' + k, 0) + 1
                    s['max_' + k] = max(s.get('max_' + k, v), v)
            w = (t.get('power') or {}).get('total')
            if isinstance(w, (int, float)): s['wh'] += w * dt / 3600
            parts = s.setdefault('parts', {})
            for key, val in _part_maxima(t.get('temps')).items():
                parts[key] = max(parts.get(key, val), val)

    def session_view(self, s=None):
        s = s or self.session
        if not s: return None
        avg = lambda k: round(s['sum_' + k] / s['n_' + k], 1) if s.get('n_' + k) else None
        elapsed = int(time.time() - s['start'])
        return {'game': s['game'], 'gid': s['gid'], 'start': int(s['start']), 'elapsed': elapsed,
                'cpu_temp_max': s.get('max_cpu_temp'), 'gpu_temp_max': s.get('max_gpu_temp'),
                'parts_max': dict(s.get('parts') or {}),
                'cpu_temp_avg': avg('cpu_temp'), 'gpu_temp_avg': avg('gpu_temp'), 'cpu_avg': avg('cpu'), 'gpu_avg': avg('gpu'),
                'kwh': round(s['wh'] / 1000, 3), 'watts_avg': round(s['wh'] * 3600 / elapsed) if elapsed > 30 and s['wh'] else None}

    def finish_session(self):
        with self.lock:
            s, self.session = self.session, None
        v = self.session_view(s)
        if not v or v['elapsed'] < 60: return None
        price = float(self.config.get('energy', {}).get('price_eur_kwh', 0.30))
        v['cost'] = round(v['kwh'] * price, 2)
        self.state['gaming_history'] = ([v] + list(self.state.get('gaming_history') or []))[:30]
        if v['gid']:
            g = self.state.setdefault('games', {}).setdefault(v['gid'], {'seconds': 0, 'last': 0})
            g['seconds'] = int(g.get('seconds', 0)) + v['elapsed']; g['last'] = int(time.time())
            g['sessions'] = int(g.get('sessions', 0)) + 1
            g['kwh'] = round(float(g.get('kwh', 0)) + v['kwh'], 3); g['cost'] = round(float(g.get('cost', 0)) + v['cost'], 2)
            for k in ('cpu_temp_max', 'gpu_temp_max'):
                if v.get(k) is not None: g[k] = max(g.get(k) or 0, v[k])
            g['recent'] = ([{k: v[k] for k in v if k not in ('game', 'gid')}] + list(g.get('recent') or []))[:15]
        self.save()
        if v['game'] and v['elapsed'] >= 120:
            temps = ' · '.join(f'{n} max {v[k]:.0f}°C' for n, k in (('CPU', 'cpu_temp_max'), ('GPU', 'gpu_temp_max')) if v[k] is not None)
            self.notify(f"🎮 Partita finita: {v['game']} · {fmt_duration(v['elapsed'])}"
                        + (f'\n🌡 {temps}' if temps else '') + (f"\n🔌 {v['kwh']:.2f} kWh ({v['cost']:.2f} €)".replace('.', ',') if v['kwh'] else ''))
        return v

    def stop(self):
        with self.lock:
            if not self.active: return ''
            self.active = False
            tweaks, mouse = dict(self.saved_tweaks), self.saved_mouse
            boosted, lowered, closed = dict(self.boosted), dict(self.lowered), list(self.closed)
            self.saved_tweaks, self.saved_mouse, self.boosted, self.lowered, self.closed, self.game = {}, None, {}, {}, [], ''
        for key, old in tweaks.items():
            _, hive, path, name, _, _ = TWEAKS[key]
            try:
                if old is None: _reg(hive, path, name, delete=True)   # non c'era: si toglie
                else: _reg(hive, path, name, old)
            except OSError: pass
        if mouse:
            try: mouse_accel(mouse)
            except OSError: pass
        self.state.pop('boost_saved', None)
        for pid, (name, old) in {**boosted, **lowered}.items():
            try: psutil.Process(pid).nice(old)
            except (psutil.Error, OSError): pass
        reopened = []
        if self.settings()['reopen']:
            for app in closed:
                if any((p.info['name'] or '').lower() == app['name'] for p in psutil.process_iter(['name'])): continue
                try:
                    subprocess.Popen(app['cmdline'], cwd=app['cwd'] or None, close_fds=True,
                                     creationflags=getattr(subprocess, 'DETACHED_PROCESS', 0))
                    reopened.append(app['name'].replace('.exe', ''))
                except OSError: pass
        self.finish_session()
        self.save()
        msg = 'Gaming Boost spento: tutto come prima' + (' · riaperte ' + ', '.join(reopened) if reopened else '')
        self.log(msg)
        return msg

def _part_maxima(groups):
    """Dalle temperature del momento: il valore più alto di punto caldo GPU, VRM, RAM e dischi."""
    out = {}
    for g in groups or []:
        for r in g.get('rows') or []:
            v = r.get('value')
            if not isinstance(v, (int, float)): continue
            key = ('hotspot' if g['kind'] == 'gpu' and r.get('name') == 'Punto più caldo' else
                   'vrm' if g['kind'] == 'board' and 'VRM' in r.get('name', '') else
                   'ram' if g['kind'] == 'ram' else 'disk' if g['kind'] == 'disk' else None)
            if key: out[key] = max(out.get(key, v), round(v, 1))
    return out
