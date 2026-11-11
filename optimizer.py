"""Ottimizzazione del PC: spazio occupato da file inutili e pulizia, programmi all'avvio, dischi, RAM e rete.

Regole: mai documenti o file personali; solo cartelle di cache e temporanei che Windows e i programmi ricreano.
I file in uso vengono saltati; i temporanei solo se più vecchi di un giorno; le cache dei browser solo a browser chiuso.
"""
from __future__ import annotations
import ctypes
import fnmatch
import os
import shutil
import subprocess
import time
from pathlib import Path

import psutil

def _env(name, default=''):
    return Path(os.environ.get(name) or default)

LOCAL = _env('LOCALAPPDATA', Path.home() / 'AppData' / 'Local')
WINDIR = _env('WINDIR', r'C:\Windows')
DAY = 86400
# Pulizia rapida/automatica: mai cestino né cartelle di Windows (niente admin, niente perdite).
# Niente cache degli shader: i giochi la ricostruiscono a scatti nelle prime partite, si pulisce solo a mano.
SAFE_CLEAN = ('temp', 'thumbs', 'crash', 'browser')
BROWSERS = {'msedge.exe': LOCAL / 'Microsoft' / 'Edge' / 'User Data', 'chrome.exe': LOCAL / 'Google' / 'Chrome' / 'User Data',
            'brave.exe': LOCAL / 'BraveSoftware' / 'Brave-Browser' / 'User Data'}
BROWSER_CACHES = ('Cache', 'Code Cache', 'GPUCache', 'Service Worker/CacheStorage')

# Opera tiene la cache direttamente nella cartella del browser, senza profili.
OPERA = {'opera.exe': [LOCAL / 'Opera Software' / 'Opera GX Stable', LOCAL / 'Opera Software' / 'Opera Stable']}

def browser_dirs():
    out = []
    for root in BROWSERS.values():
        if not root.is_dir(): continue
        for profile in [p for p in root.iterdir() if p.is_dir() and (p.name == 'Default' or p.name.startswith('Profile '))]:
            out += [profile / c for c in BROWSER_CACHES]
    for roots in OPERA.values():
        out += [r / c for r in roots if r.is_dir() for c in BROWSER_CACHES]
    return out

def targets():
    """Cosa si può pulire. admin=True: serve la conferma da amministratore (solo dal PC)."""
    temp = _env('TEMP', LOCAL / 'Temp')
    return [
        {'key': 'temp', 'name': 'File temporanei', 'desc': 'Cartella Temp dell\'utente, file più vecchi di un giorno',
         'paths': [temp], 'min_age': DAY, 'skip': [temp / 'NEXAR']},
        {'key': 'shader', 'name': 'Cache shader dei giochi', 'optional': True,
         'desc': 'Solo se un gioco ha problemi grafici: dopo la pulizia i giochi scattano finché la ricostruiscono',
         'paths': [LOCAL / 'D3DSCache', LOCAL / 'NVIDIA' / 'DXCache', LOCAL / 'NVIDIA' / 'GLCache', LOCAL / 'AMD' / 'DxCache', LOCAL / 'AMD' / 'DxcCache']},
        {'key': 'thumbs', 'name': 'Anteprime delle immagini', 'desc': 'Miniature di Esplora file (quelle in uso restano)',
         'paths': [LOCAL / 'Microsoft' / 'Windows' / 'Explorer'], 'pattern': 'thumbcache_*.db'},
        {'key': 'crash', 'name': 'Rapporti di errore', 'desc': 'Dump dei crash e segnalazioni di Windows',
         'paths': [LOCAL / 'CrashDumps', LOCAL / 'Microsoft' / 'Windows' / 'WER' / 'ReportArchive', LOCAL / 'Microsoft' / 'Windows' / 'WER' / 'ReportQueue']},
        {'key': 'browser', 'name': 'Cache dei browser', 'desc': 'Edge, Chrome, Brave, Opera: pagine salvate (non password né cronologia)',
         'paths': browser_dirs(), 'needs_closed': list(BROWSERS) + list(OPERA)},
        {'key': 'wintemp', 'name': 'File temporanei di Windows', 'desc': 'C:\\Windows\\Temp', 'paths': [WINDIR / 'Temp'], 'admin': True},
        {'key': 'wupdate', 'name': 'Download di Windows Update', 'desc': 'Aggiornamenti già installati', 'paths': [WINDIR / 'SoftwareDistribution' / 'Download'], 'admin': True},
        {'key': 'recycle', 'name': 'Cestino', 'desc': 'Svuota il cestino: i file non si possono più recuperare', 'recycle': True},
    ]

def _files(t, now=None):
    """File eliminabili di un obiettivo (rispetta età minima, filtro nome e cartelle escluse)."""
    now = now or time.time()
    skip = [str(s).lower() for s in t.get('skip', [])]
    for root in t.get('paths', []):
        if not Path(root).is_dir(): continue
        for dirpath, dirnames, filenames in os.walk(root):
            if any(dirpath.lower().startswith(s) for s in skip):
                dirnames[:] = []; continue
            for f in filenames:
                if t.get('pattern') and not fnmatch.fnmatch(f.lower(), t['pattern']): continue
                p = os.path.join(dirpath, f)
                try:
                    st = os.stat(p)
                    if t.get('min_age') and now - st.st_mtime < t['min_age']: continue
                    yield p, st.st_size
                except OSError: continue

def recycle_size():
    if os.name != 'nt': return 0, 0
    class SHQUERYRBINFO(ctypes.Structure):
        _fields_ = [('cbSize', ctypes.c_ulong), ('i64Size', ctypes.c_longlong), ('i64NumItems', ctypes.c_longlong)]
    info = SHQUERYRBINFO(ctypes.sizeof(SHQUERYRBINFO), 0, 0)
    if ctypes.windll.shell32.SHQueryRecycleBinW(None, ctypes.byref(info)) != 0: return 0, 0
    return info.i64Size, info.i64NumItems

def browsers_open():
    names = {p.info['name'].lower() for p in psutil.process_iter(['name']) if p.info.get('name')}
    return sorted(n for n in list(BROWSERS) + list(OPERA) if n in names)

def analyze(limit_seconds=25):
    """Quanto spazio libererebbe ogni voce."""
    report, start, opened = [], time.monotonic(), browsers_open()
    for t in targets():
        item = {k: t.get(k) for k in ('key', 'name', 'desc')}
        item.update(admin=bool(t.get('admin')), permanent=bool(t.get('recycle')), optional=bool(t.get('optional')), bytes=0, files=0, note='')
        if t.get('recycle'):
            item['bytes'], item['files'] = recycle_size()
        else:
            for _, size in _files(t):
                item['bytes'] += size; item['files'] += 1
                if time.monotonic() - start > limit_seconds:
                    item['note'] = 'stima parziale'; break
        if t.get('needs_closed') and opened:
            item['note'] = 'chiudi ' + ', '.join(n.replace('.exe', '').capitalize() for n in opened) + ' per pulirla'
        report.append(item)
    return {'items': report, 'total': sum(i['bytes'] for i in report), 'at': time.strftime('%Y-%m-%dT%H:%M:%S')}

def _remove_empty_dirs(root):
    for dirpath, dirnames, filenames in os.walk(root, topdown=False):
        if dirpath != str(root):
            try: os.rmdir(dirpath)
            except OSError: pass

def clean(keys, run_elevated=None, allow_admin=False, admin=None):
    """Pulisce le voci scelte. Restituisce byte liberati e note. Le voci admin passano da run_elevated (UAC sul PC)."""
    freed, notes, wanted = 0, [], set(keys)
    known = {t['key']: t for t in targets()}
    if wanted - set(known): raise ValueError('Voce di pulizia sconosciuta')
    admin_paths, admin_keys = [], []
    for key in wanted:
        t = known[key]
        if t.get('recycle'):
            size, _ = recycle_size()
            if os.name == 'nt' and ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, 0x7) in (0, -2147418113):
                freed += size  # -2147418113 = cestino già vuoto
            continue
        if t.get('admin'):
            if not allow_admin and not admin: notes.append(f'{t["name"]}: attiva Amministratore da remoto sul PC')
            else: admin_paths += [str(p) for p in t['paths']]; admin_keys.append(key)
            continue
        if t.get('needs_closed') and browsers_open():
            notes.append(f'{t["name"]}: chiudi i browser e riprova'); continue
        for path, size in list(_files(t)):
            try: os.remove(path); freed += size
            except OSError: pass  # in uso: resta dov'è
        for root in t.get('paths', []):
            if Path(root).is_dir() and not t.get('pattern'): _remove_empty_dirs(root)
    if admin_paths and admin:
        before = sum(s for p in admin_paths for _, s in _files({'paths': [p]}))
        admin.call('clean', keys=admin_keys)
        freed += max(0, before - sum(s for p in admin_paths for _, s in _files({'paths': [p]})))
    elif admin_paths and run_elevated:
        before = sum(s for p in admin_paths for _, s in _files({'paths': [p]}))
        script = ''.join(f"Get-ChildItem -LiteralPath '{p}' -Force -ErrorAction SilentlyContinue | "
                         f"Remove-Item -Recurse -Force -ErrorAction SilentlyContinue;" for p in admin_paths)
        if run_elevated(script, wait=True):
            freed += max(0, before - sum(s for p in admin_paths for _, s in _files({'paths': [p]})))
        else: notes.append('Pulizia di Windows annullata (conferma amministratore)')
    return {'freed': freed, 'notes': notes}

# ---------- programmi all'avvio (come Gestione attività: StartupApproved, reversibile) ----------
RUN = r'Software\Microsoft\Windows\CurrentVersion\Run'
APPROVED = r'Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved'

def startup_items():
    if os.name != 'nt': return []
    import winreg
    items = []
    def approved(hive, sub, name):
        try:
            with winreg.OpenKey(hive, APPROVED + '\\' + sub) as k:
                return winreg.QueryValueEx(k, name)[0][0] in (0x02, 0x06)
        except OSError: return True  # nessuna voce = attivo
    for hive, label, path, sub in ((winreg.HKEY_CURRENT_USER, 'utente', RUN, 'Run'),
                                   (winreg.HKEY_LOCAL_MACHINE, 'tutti gli utenti', RUN, 'Run'),
                                   (winreg.HKEY_LOCAL_MACHINE, 'tutti gli utenti', RUN.replace('Software', r'Software\WOW6432Node'), 'Run32')):
        try:
            with winreg.OpenKey(hive, path) as k:
                for i in range(winreg.QueryInfoKey(k)[1]):
                    name, cmd, _ = winreg.EnumValue(k, i)
                    items.append({'id': f'{"HKCU" if hive == winreg.HKEY_CURRENT_USER else "HKLM"}|{sub}|{name}', 'name': name,
                                  'command': str(cmd)[:200], 'scope': label, 'enabled': approved(hive, sub, name),
                                  'admin': hive != winreg.HKEY_CURRENT_USER})
        except OSError: continue
    folder = Path(os.environ.get('APPDATA', '')) / 'Microsoft' / 'Windows' / 'Start Menu' / 'Programs' / 'Startup'
    if folder.is_dir():
        for f in folder.iterdir():
            if f.suffix.lower() in ('.lnk', '.exe', '.bat', '.cmd', '.url'):
                items.append({'id': f'HKCU|StartupFolder|{f.name}', 'name': f.stem, 'command': str(f), 'scope': 'utente',
                              'enabled': approved(winreg.HKEY_CURRENT_USER, 'StartupFolder', f.name), 'admin': False})
    return sorted(items, key=lambda i: i['name'].lower())

def set_startup(item_id, enabled, run_elevated=None, admin=None):
    """Attiva/disattiva un programma all'avvio senza cancellarlo (si riattiva quando vuoi, come in Gestione attività)."""
    import winreg
    hive_name, sub, name = item_id.split('|', 2)
    if sub not in ('Run', 'Run32', 'StartupFolder') or hive_name not in ('HKCU', 'HKLM'): raise ValueError('Voce non valida')
    if not any(i['id'] == item_id for i in startup_items()): raise ValueError('Programma non trovato')
    data = bytes([0x02 if enabled else 0x03]) + bytes(11)
    if hive_name == 'HKCU':
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, APPROVED + '\\' + sub) as k:
            winreg.SetValueEx(k, name, 0, winreg.REG_BINARY, data)
        return True
    if admin: return admin.call('startup', sub=sub, name=name, enabled=bool(enabled))
    if not run_elevated: raise RuntimeError('Programma di sistema: attiva Amministratore da remoto sul PC')
    hexdata = ','.join(f'0x{b:02x}' for b in data)
    script = (f"$p='HKLM:\\{APPROVED}\\{sub}'; if(-not (Test-Path -LiteralPath $p)){{New-Item -Path $p -Force | Out-Null}}; "
              f"Set-ItemProperty -Path $p -Name '{name.replace(chr(39), chr(39) * 2)}' -Type Binary -Value ([byte[]]({hexdata}))")
    if not run_elevated(script, wait=True): raise RuntimeError('Conferma amministratore annullata')
    return True

# ---------- dischi, memoria, rete ----------
def disks():
    out = []
    for part in psutil.disk_partitions(all=False):
        if 'cdrom' in part.opts or not part.fstype: continue
        try: u = shutil.disk_usage(part.mountpoint)
        except OSError: continue
        out.append({'drive': part.mountpoint.rstrip('\\'), 'total': u.total, 'used': u.used, 'free': u.free,
                    'percent': round(u.used / u.total * 100, 1) if u.total else 0})
    return out

def memory_top(n=8):
    procs = {}
    for p in psutil.process_iter(['name', 'memory_info']):
        try:
            name = p.info['name'] or '?'; rss = p.info['memory_info'].rss
            procs[name] = procs.get(name, 0) + rss  # Chrome & co. hanno molti processi: si sommano
        except (psutil.Error, AttributeError): continue
    vm = psutil.virtual_memory()
    top = sorted(procs.items(), key=lambda x: -x[1])[:n]
    return {'used': vm.used, 'total': vm.total, 'percent': vm.percent, 'top': [{'name': k, 'bytes': v} for k, v in top]}

def flush_dns():
    flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    r = subprocess.run(['ipconfig', '/flushdns'], capture_output=True, text=True, errors='replace', timeout=20, creationflags=flags)
    if r.returncode: raise RuntimeError('Svuotamento DNS non riuscito')
    return 'Cache DNS svuotata'

TRIM_SCRIPT = ("Get-Volume | Where-Object { $_.DriveType -eq 'Fixed' -and $_.DriveLetter } | "
               "ForEach-Object { Optimize-Volume -DriveLetter $_.DriveLetter -ReTrim -ErrorAction SilentlyContinue }")

def human(b):
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if b < 1024 or unit == 'TB': return f'{b:.0f} {unit}' if unit in ('B', 'KB') else f'{b:.1f} {unit}'.replace('.', ',')
        b /= 1024

# ---------- programmi pesanti adesso (CPU e RAM, per nome) ----------
NEVER_CLOSE = {'system', 'registry', 'smss.exe', 'csrss.exe', 'wininit.exe', 'winlogon.exe', 'services.exe', 'lsass.exe',
               'svchost.exe', 'explorer.exe', 'dwm.exe', 'sihost.exe', 'fontdrvhost.exe', 'ctfmon.exe', 'searchhost.exe',
               'startmenuexperiencehost.exe', 'shellexperiencehost.exe', 'runtimebroker.exe', 'taskhostw.exe', 'conhost.exe',
               'audiodg.exe', 'nexar.exe', 'msmpeng.exe', 'memcompression', 'system idle process', 'msedgewebview2.exe',
               'textinputhost.exe', 'securityhealthservice.exe', 'spoolsv.exe', 'wudfhost.exe', 'lsaiso.exe', 'secure system',
               'openrgb.exe', 'fancontrol.exe', 'librehardwaremonitor.exe', 'cloudflared.exe'}
_cpu_seen = {}

def processes(n=12):
    """I programmi che pesano di più ora: CPU (% di tutto il processore) e RAM, sommati per nome."""
    cores = psutil.cpu_count() or 1
    me = psutil.Process().username() if os.name == 'nt' else None
    agg, now, alive = {}, time.monotonic(), set()
    for p in psutil.process_iter(['name', 'memory_info', 'username', 'cpu_times']):
        try:
            alive.add(p.pid)
            name = p.info['name'] or '?'
            if name.lower() in ('system idle process', 'idle'): continue
            t = p.info['cpu_times']; total = (t.user + t.system) if t else 0.0
            prev = _cpu_seen.get(p.pid)
            cpu = max(0.0, (total - prev[0]) / max(0.5, now - prev[1]) * 100 / cores) if prev else 0.0
            _cpu_seen[p.pid] = (total, now)
            a = agg.setdefault(name, {'name': name, 'cpu': 0.0, 'bytes': 0, 'count': 0, 'mine': False})
            a['cpu'] += cpu; a['bytes'] += p.info['memory_info'].rss if p.info['memory_info'] else 0; a['count'] += 1
            a['mine'] = a['mine'] or (bool(me) and p.info['username'] == me)
        except (psutil.Error, AttributeError, TypeError): continue
    for pid in list(_cpu_seen):
        if pid not in alive: _cpu_seen.pop(pid, None)
    for a in agg.values():
        a['cpu'] = round(a['cpu'], 1); a['closable'] = a['mine'] and a['name'].lower() not in NEVER_CLOSE
    vm = psutil.virtual_memory()
    return {'cpu_total': psutil.cpu_percent(None), 'ram': {'used': vm.used, 'total': vm.total, 'percent': vm.percent},
            'by_cpu': sorted(agg.values(), key=lambda a: -a['cpu'])[:n], 'by_ram': sorted(agg.values(), key=lambda a: -a['bytes'])[:n],
            'count': sum(a['count'] for a in agg.values())}

def close_app(name: str):
    """Chiusura gentile (come la X): un programma con lavoro non salvato può chiedere di salvare e restare aperto."""
    name = str(name)
    if not name.lower().endswith('.exe') or name.lower() in NEVER_CLOSE or any(c in name for c in '\\/:*?"<>|'):
        raise ValueError('Questo programma non si può chiudere da qui')
    procs = [p for p in psutil.process_iter(['name']) if (p.info['name'] or '').lower() == name.lower()]
    if not procs: return f'{name[:-4]} non è più aperto'
    subprocess.run(['taskkill', '/im', name], capture_output=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    gone, alive = psutil.wait_procs(procs, timeout=6)
    return f'{name[:-4]} chiuso' if not alive else f'{name[:-4]}: chiesto di chiudersi (potrebbe chiedere di salvare)'

# ---------- file grandi nelle cartelle personali (solo elenco: si apre la cartella o si sposta nel Cestino) ----------
SKIP_DIRS = {'appdata', 'node_modules', '.git', '$recycle.bin', 'windows', '.venv', 'venv', '__pycache__', 'steamapps', 'program files'}
CLOUD_ONLY = 0x400000 | 0x40000 | 0x1000   # OneDrive "solo online": non occupano spazio sul disco

def personal_folders():
    home = Path.home(); out = []
    for base in [home] + [Path(os.environ[k]) for k in ('OneDrive', 'OneDriveConsumer') if os.environ.get(k)]:
        for sub in ('Downloads', 'Desktop', 'Documents', 'Videos', 'Pictures', 'Music', 'Documenti', 'Immagini', 'Video', 'Musica'):
            d = base / sub
            try:
                if d.is_dir() and d.resolve() not in {x.resolve() for x in out}: out.append(d)
            except OSError: continue
    return out

def large_files(min_bytes=300 * 2**20, limit=40, budget=20.0, roots=None):
    found, start = [], time.monotonic()
    def walk(d, depth):
        if depth > 7 or time.monotonic() - start > budget: return
        try: entries = list(os.scandir(d))
        except OSError: return
        for e in entries:
            try:
                if e.is_symlink(): continue
                if e.is_dir(follow_symlinks=False):
                    if e.name.lower() not in SKIP_DIRS and not e.name.startswith('.'): walk(e.path, depth + 1)
                    continue
                st = e.stat(follow_symlinks=False)
                if st.st_size < min_bytes or getattr(st, 'st_file_attributes', 0) & CLOUD_ONLY: continue
                found.append({'path': e.path, 'name': e.name, 'folder': str(Path(e.path).parent), 'bytes': st.st_size,
                              'mtime': int(st.st_mtime), 'kind': Path(e.name).suffix.lower().lstrip('.')})
            except OSError: continue
    for root in roots or personal_folders(): walk(str(root), 0)
    found.sort(key=lambda f: -f['bytes'])
    return {'files': found[:limit], 'total': sum(f['bytes'] for f in found), 'count': len(found), 'at': int(time.time()),
            'partial': time.monotonic() - start > budget}

def to_recycle_bin(path: str):
    """Sposta nel Cestino (recuperabile), come Elimina in Esplora file."""
    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [('hwnd', ctypes.c_void_p), ('wFunc', ctypes.c_uint), ('pFrom', ctypes.c_wchar_p), ('pTo', ctypes.c_wchar_p),
                    ('fFlags', ctypes.c_ushort), ('fAnyOperationsAborted', ctypes.c_int), ('hNameMappings', ctypes.c_void_p),
                    ('lpszProgressTitle', ctypes.c_wchar_p)]
    # FO_DELETE con ALLOWUNDO (Cestino), senza finestre: NOCONFIRMATION, SILENT, NOERRORUI
    op = SHFILEOPSTRUCTW(None, 3, path + '\0', None, 0x40 | 0x10 | 0x4 | 0x400, 0, None, None)
    if ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op)) or op.fAnyOperationsAborted or os.path.exists(path):
        raise RuntimeError('Non sono riuscito a spostarlo nel Cestino (forse è aperto)')

def reveal(path: str):
    subprocess.Popen(['explorer.exe', '/select,', os.path.normpath(path)])

# ---------- salute dei dischi (SMART di Windows) ----------
DISK_PS = ("$r=@(); foreach($d in Get-PhysicalDisk){ $c=$null; try{ $c=$d | Get-StorageReliabilityCounter -ErrorAction Stop }catch{}; "
           "$r += [pscustomobject]@{name=$d.FriendlyName; media=[string]$d.MediaType; bus=[string]$d.BusType; health=[string]$d.HealthStatus; "
           "status=[string]($d.OperationalStatus -join ','); size=[int64]$d.Size; temp=$(if($c){$c.Temperature}else{$null}); "
           "wear=$(if($c){$c.Wear}else{$null}); hours=$(if($c){$c.PowerOnHours}else{$null})} }; $r | ConvertTo-Json -Compress")

def disk_health():
    import json as _json
    flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    r = subprocess.run(['powershell', '-NoProfile', '-Command', DISK_PS], capture_output=True, text=True, errors='replace',
                       timeout=40, creationflags=flags)
    try: data = _json.loads(r.stdout or '[]')
    except ValueError: return []
    data = data if isinstance(data, list) else [data]
    for d in data:
        d['media'] = {'SSD': 'SSD', 'HDD': 'HDD'}.get(d.get('media'), 'Disco')
        d['ok'] = d.get('health') == 'Healthy'
    return data

# ---------- rete: latenza verso router, internet e DNS ----------
def _ping(host, count=4):
    import re as _re
    flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    r = subprocess.run(['ping', '-n', str(count), '-w', '1000', host], capture_output=True, text=True, errors='replace',
                       timeout=count * 2 + 5, creationflags=flags)
    times = [int(x) for x in _re.findall(r'[=<](\d+)\s*ms\b', r.stdout)]
    return {'host': host, 'ms': round(sum(times) / len(times)) if times else None, 'loss': round((count - len(times)) / count * 100)}

def default_gateway():
    flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    r = subprocess.run(['powershell', '-NoProfile', '-Command',
                        "(Get-NetRoute -DestinationPrefix '0.0.0.0/0' | Sort-Object RouteMetric | Select-Object -First 1).NextHop"],
                       capture_output=True, text=True, errors='replace', timeout=20, creationflags=flags)
    gw = (r.stdout or '').strip()
    return gw if gw and gw != '0.0.0.0' else None

def network_check():
    import socket
    from concurrent.futures import ThreadPoolExecutor
    gw = default_gateway()
    hosts = ([('router', gw)] if gw else []) + [('internet', '1.1.1.1'), ('google', '8.8.8.8')]
    with ThreadPoolExecutor(4) as ex: res = dict(zip([k for k, _ in hosts], ex.map(lambda h: _ping(h[1]), hosts)))
    t = time.perf_counter()
    try: socket.getaddrinfo('www.microsoft.com', 443); dns = round((time.perf_counter() - t) * 1000)
    except OSError: dns = None
    net = res.get('internet') or {}
    ms = net.get('ms')
    quality = ('offline' if ms is None else 'ottima' if ms < 25 and not net['loss']
               else 'buona' if ms < 60 and net['loss'] <= 25 else 'lenta')
    return {'at': int(time.time()), 'router': res.get('router'), 'internet': net, 'google': res.get('google'), 'dns_ms': dns, 'quality': quality}
