"""Ricerca automatica dei programmi esterni: l'utente non deve scrivere percorsi a mano."""
from __future__ import annotations
import time
import ctypes
import json
import logging
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
from urllib.request import urlopen

LHM_URL = 'http://127.0.0.1:8085/data.json'
LHM_TASK = 'PC ECO Control - Sensori'
OPENRGB_TASK = 'PC ECO Control - RGB'
OPENRGB_PORT = 6742
RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
# Pacchetti ufficiali winget, installati solo quando l'utente preme "Installa".
WINGET = {
    'rgb': 'OpenRGB.OpenRGB',
    'fans': 'Rem0o.FanControl',
    'sensors': 'LibreHardwareMonitor.LibreHardwareMonitor',
    'tunnel': 'Cloudflare.cloudflared',
}
ECO_WORDS = ('eco', 'silent', 'silenzio', 'quiet', 'notte', 'night')
NORMAL_WORDS = ('normal', 'default', 'standard', 'game', 'gaming', 'base')

def _no_window():
    return {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}

def _roots():
    env = os.environ.get
    home = Path.home()
    roots = [env('ProgramFiles'), env('ProgramFiles(x86)'), env('ProgramW6432'), env('LOCALAPPDATA'),
             env('LOCALAPPDATA') and str(Path(env('LOCALAPPDATA')) / 'Programs'), env('APPDATA'),
             'C:\\Tools', str(home / 'Downloads'), str(home / 'Desktop'), str(home / 'OneDrive' / 'Desktop')]
    seen, out = set(), []
    for r in roots:
        if r and r.lower() not in seen and Path(r).is_dir():
            seen.add(r.lower()); out.append(Path(r))
    return out

def find_exe(name: str, folders: list[str]) -> str:
    """Cerca nel PATH, nelle cartelle di installazione note, nei pacchetti winget e nei download."""
    hit = shutil.which(name)
    if hit: return str(Path(hit).resolve())
    roots = _roots()
    for root in roots:
        for folder in folders:
            p = root / folder / name
            if p.is_file(): return str(p)
    local = os.environ.get('LOCALAPPDATA')
    if local:
        links = Path(local) / 'Microsoft' / 'WinGet' / 'Links' / name
        if links.is_file(): return str(links)
        pkgs = Path(local) / 'Microsoft' / 'WinGet' / 'Packages'
        if pkgs.is_dir():
            for pattern in (f'*/{name}', f'*/*/{name}', f'*/*/*/{name}'):
                for p in pkgs.glob(pattern): return str(p)
    # Ultima spiaggia: cartelle zip estratte in Download/Desktop (profondità limitata).
    for root in roots[-3:]:
        for pattern in (f'*/{name}', f'*/*/{name}'):
            for p in root.glob(pattern): return str(p)
    return ''

def find_openrgb(): return find_exe('OpenRGB.exe', ['OpenRGB', 'OpenRGB (Experimental)'])
def find_fancontrol(): return find_exe('FanControl.exe', ['FanControl', 'Fan Control'])
def find_lhm(): return find_exe('LibreHardwareMonitor.exe', ['LibreHardwareMonitor', 'Libre Hardware Monitor'])

def find_nvidia_smi():
    hit = shutil.which('nvidia-smi')
    if hit: return hit
    guess = Path(os.environ.get('ProgramFiles', r'C:\Program Files')) / 'NVIDIA Corporation' / 'NVSMI' / 'nvidia-smi.exe'
    return str(guess) if guess.is_file() else ''

def fancontrol_dirs(exe: str) -> list[Path]:
    base = Path(exe).parent
    return [base / 'Configurations', base]

def fancontrol_profiles(exe: str) -> list[str]:
    names = []
    for d in fancontrol_dirs(exe):
        if not d.is_dir(): continue
        for f in d.glob('*.json'):
            low = f.name.lower()
            if low == 'userconfig.json' or low.endswith(('.deps.json', '.runtimeconfig.json')): continue
            if f.name not in names: names.append(f.name)
    return sorted(names)

def guess_profiles(names: list[str]):
    if all(f in names for f in ('PCECO-Eco.json', 'PCECO-Normale.json')):
        return 'PCECO-Eco.json', 'PCECO-Normale.json'
    eco = next((n for n in names if any(w in n.lower() for w in ECO_WORDS)), '')
    normal = next((n for n in names if n != eco and any(w in n.lower() for w in NORMAL_WORDS)), '')
    if eco and not normal:
        others = [n for n in names if n != eco]
        if len(others) == 1: normal = others[0]
    return eco, normal

def sensors_online(url=LHM_URL) -> bool:
    try:
        with urlopen(url, timeout=1.0) as r: return r.status == 200
    except Exception: return False

def lhm_enable_webserver(exe: str) -> bool:
    """Accende il server web di LibreHardwareMonitor (porta 8085) e l'avvio ridotto a icona."""
    cfg = Path(exe).with_name('LibreHardwareMonitor.config')
    wanted = {'runWebServerMenuItem': 'true', 'listenerPort': '8085', 'startMinMenuItem': 'true',
              'minTrayMenuItem': 'true', 'minCloseMenuItem': 'true'}
    try:
        text = cfg.read_text(encoding='utf-8') if cfg.is_file() else \
            '<?xml version="1.0" encoding="utf-8"?>\n<configuration>\n  <appSettings>\n  </appSettings>\n</configuration>\n'
        if '<appSettings>' not in text and '<appSettings/>' not in text:
            text = text.replace('</configuration>', '  <appSettings>\n  </appSettings>\n</configuration>')
        text = text.replace('<appSettings/>', '<appSettings>\n  </appSettings>')
        for key, val in wanted.items():
            line = f'<add key="{key}" value="{val}" />'
            pattern = re.compile(r'<add\s+key="' + re.escape(key) + r'"\s+value="[^"]*"\s*/>')
            text = pattern.sub(line, text) if pattern.search(text) else text.replace('</appSettings>', f'    {line}\n  </appSettings>')
        cfg.write_text(text, encoding='utf-8')
        return True
    except OSError as ex:
        logging.warning('Config LibreHardwareMonitor non scrivibile: %s', ex)
        return False

def task_restart(name: str) -> bool:
    """Riavvia un'attività di NEXAR senza UAC: la chiude (se gira) e la rilancia."""
    if os.name != 'nt' or not task_exists(name): return False
    subprocess.run(['schtasks', '/end', '/tn', name], capture_output=True, **_no_window())
    return subprocess.run(['schtasks', '/run', '/tn', name], capture_output=True, **_no_window()).returncode == 0

def process_running(exe_name: str) -> bool:
    import psutil
    low = exe_name.lower()
    for p in psutil.process_iter(['name']):
        try:
            if (p.info['name'] or '').lower() == low: return True
        except Exception: continue
    return False

def task_exists(name=LHM_TASK) -> bool:
    if os.name != 'nt': return False
    r = subprocess.run(['schtasks', '/query', '/tn', name], capture_output=True, **_no_window())
    return r.returncode == 0

def lhm_start(exe: str, allow_uac: bool) -> str:
    """Avvia i sensori con privilegi admin. Dopo la prima conferma UAC parte da solo a ogni accesso."""
    return elevated_task(LHM_TASK, exe, '', allow_uac)

def port_open(port: int) -> bool:
    try:
        with socket.create_connection(('127.0.0.1', port), 0.5): return True
    except OSError: return False

def openrgb_start(exe: str, allow_uac: bool) -> str:
    """Server OpenRGB come amministratore (serve per la RAM), ridotto a icona, a ogni accesso."""
    return elevated_task(OPENRGB_TASK, exe, '--server --startminimized', allow_uac)

def _q(s): return "'" + str(s).replace("'", "''") + "'"

def task_script(task: str, exe: str, args: str, at_logon=True, start=True) -> str:
    """Attività pianificata con privilegi massimi: dopo la prima conferma UAC parte senza chiedere più."""
    user = f"{os.environ.get('USERDOMAIN', '')}\\{os.environ.get('USERNAME', '')}".strip('\\')
    argument = f' -Argument {_q(args)}' if args else ''
    trigger = f"-Trigger (New-ScheduledTaskTrigger -AtLogOn -User {_q(user)}) " if at_logon else ''
    return (
        f"$a=New-ScheduledTaskAction -Execute {_q(exe)}{argument} -WorkingDirectory {_q(Path(exe).parent)};"
        f"$p=New-ScheduledTaskPrincipal -UserId {_q(user)} -RunLevel Highest -LogonType Interactive;"
        "$s=New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit 0;"
        f"Register-ScheduledTask -TaskName {_q(task)} -Action $a {trigger}-Principal $p -Settings $s -Force;"
        + (f"Start-ScheduledTask -TaskName {_q(task)};" if start else '')
    )

def script_file(script: str) -> Path:
    """Lo script admin va in un file .ps1 leggibile (in %TEMP%\\NEXAR): niente comandi codificati in base64,
    che gli antivirus associano ai malware."""
    folder = Path(os.environ.get('TEMP') or Path.home()) / 'NEXAR'
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f'nexar-admin-{os.getpid()}-{int(time.time() * 1000)}.ps1'
    path.write_text('# NEXAR: operazione da amministratore richiesta dall\'utente\n' + script, encoding='utf-8-sig')
    return path

def run_elevated(script: str, wait=False) -> bool:
    """Una sola richiesta UAC per tutto lo script PowerShell."""
    args = f'-NoProfile -ExecutionPolicy RemoteSigned -File "{script_file(script)}"'
    if not wait:
        return ctypes.windll.shell32.ShellExecuteW(None, 'runas', 'powershell.exe', args, None, 0) > 32
    # ShellExecuteEx per poter attendere la fine della copia dei profili.
    class SEI(ctypes.Structure):
        _fields_ = [('cbSize', ctypes.c_ulong), ('fMask', ctypes.c_ulong), ('hwnd', ctypes.c_void_p), ('lpVerb', ctypes.c_wchar_p),
                    ('lpFile', ctypes.c_wchar_p), ('lpParameters', ctypes.c_wchar_p), ('lpDirectory', ctypes.c_wchar_p),
                    ('nShow', ctypes.c_int), ('hInstApp', ctypes.c_void_p), ('lpIDList', ctypes.c_void_p), ('lpClass', ctypes.c_wchar_p),
                    ('hkeyClass', ctypes.c_void_p), ('dwHotKey', ctypes.c_ulong), ('hIcon', ctypes.c_void_p), ('hProcess', ctypes.c_void_p)]
    sei = SEI(cbSize=ctypes.sizeof(SEI), fMask=0x40, lpVerb='runas', lpFile='powershell.exe', lpParameters=args, nShow=0)
    if not ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(sei)): return False
    ctypes.windll.kernel32.WaitForSingleObject(sei.hProcess, 60000)
    ctypes.windll.kernel32.CloseHandle(sei.hProcess)
    return True

def elevated_task(task: str, exe: str, args: str, allow_uac: bool) -> str:
    if task_exists(task):
        subprocess.run(['schtasks', '/run', '/tn', task], capture_output=True, **_no_window())
        return 'avviato'
    if not allow_uac: return 'serve conferma'
    return 'avviato' if run_elevated(task_script(task, exe, args)) else 'annullato'

# ---------- ventole ----------
FAN_TASKS = {'eco': 'PC ECO Control - Ventole ECO', 'normal': 'PC ECO Control - Ventole Normali',
             'off': 'PC ECO Control - Ventole Spente', 'off_pump': 'PC ECO Control - Ventole Spente Pompa',
             'max': 'PC ECO Control - Ventole Massimo',
             'manual_a': 'PC ECO Control - Ventole Manuale A', 'manual_b': 'PC ECO Control - Ventole Manuale B'}
FAN_FILES = {'eco': 'PCECO-Eco.json', 'normal': 'PCECO-Normale.json', 'off': 'PCECO-Spente.json',
             'off_pump': 'PCECO-Spente-Pompa.json', 'max': 'PCECO-Massimo.json',
             'manual_a': 'PCECO-Manuale-A.json', 'manual_b': 'PCECO-Manuale-B.json'}
# Regolazione di una ventola alla volta: NEXAR scrive uno dei due profili "Manuale" (A e B a turno, così Fan Control
# ricarica sempre) e lo fa caricare con la sua attività. Solo questi due file diventano modificabili dall'utente.
FAN_MANUAL = ('manual_a', 'manual_b')
# Velocità fissa per profilo; None = tutto al BIOS (eco: dalla configurazione, solo ventole del case).
FAN_LEVELS = {'off': 0, 'off_pump': 0, 'eco': None, 'normal': None, 'max': 100}
# Massimo e Spente valgono per OGNI ventola che Fan Control vede: case, radiatore, pompa, chipset e scheda video.
# "off_pump" è Spente con la pompa AIO al minimo. ECO resta solo sulle ventole del case.
ALL_FANS_LEVELS = ('max', 'off', 'off_pump')
PUMP_MIN_PERCENT = 40
FAN_PROFILES_VERSION = 3  # 2 = Massimo su tutte; 3 = Spente su tutte + variante con pompa al minimo
FAN_EXCLUDE = ('cpu', 'pump', 'aio', 'nvidia', 'gpu', 'chipset')

def user_sid() -> str:
    """SID dell'utente che usa NEXAR (per dargli la scrittura dei soli profili Manuale)."""
    if os.name != 'nt': return ''
    try:
        out = subprocess.run(['whoami', '/user', '/fo', 'csv', '/nh'], capture_output=True, text=True, timeout=10, **_no_window()).stdout
        m = re.search(r'"(S-1-5-[0-9-]+)"', out)
        return m.group(1) if m else ''
    except Exception: return ''

def fan_control_id(sensor_id: str) -> str:
    """Dal sensore RPM di LibreHardwareMonitor al controllo corrispondente in Fan Control."""
    m = re.match(r'^(/lpc/[^/]+)/\d+/fan/(\d+)$', sensor_id)
    if m: return f'{m.group(1)}/control/{m.group(2)}'
    return sensor_id.replace('/fan/', '/control/') if '/fan/' in sensor_id else ''

def is_pump(nick: str, ident: str) -> bool:
    return any(w in (nick + ' ' + ident).lower() for w in ('pump', 'pompa', 'aio'))

# Curva per una sola ventola: velocità (%) secondo la temperatura di CPU o GPU, eseguita da Fan Control.
CURVE_SAFE_AT, CURVE_SAFE_MIN = 80, 50   # a 80 °C ogni curva deve dare almeno il 50%
CURVE_PREFIX = 'NEXAR '

def curve_duty(points, temp: float) -> float:
    """La velocità che la curva comanda a questa temperatura (interpolata fra i punti)."""
    pts = sorted(points)
    if temp <= pts[0][0]: return pts[0][1]
    for (t0, d0), (t1, d1) in zip(pts, pts[1:]):
        if temp <= t1: return d0 + (d1 - d0) * (temp - t0) / (t1 - t0)
    return pts[-1][1]

def fan_curve_clean(curve, pump: bool = False) -> dict:
    """Controlla una curva arrivata dalla dashboard: 2–6 punti, temperature 20–100 °C in salita,
    velocità 0–100% mai in discesa, pompa mai sotto il minimo, e abbastanza forte quando scalda."""
    if not isinstance(curve, dict) or curve.get('src') not in ('cpu', 'gpu'): raise ValueError('Curva non valida')
    raw = curve.get('pts')
    if not isinstance(raw, list) or not 2 <= len(raw) <= 6: raise ValueError('La curva vuole da 2 a 6 punti')
    pts = []
    for p in raw:
        if not (isinstance(p, (list, tuple)) and len(p) == 2 and all(type(v) is int for v in p)): raise ValueError('Punto della curva non valido')
        t, d = p
        if not (20 <= t <= 100 and 0 <= d <= 100): raise ValueError('Temperature 20–100 °C, velocità 0–100%')
        pts.append([t, d])
    if any(b[0] <= a[0] for a, b in zip(pts, pts[1:])): raise ValueError('Le temperature devono salire da un punto al successivo')
    if any(b[1] < a[1] for a, b in zip(pts, pts[1:])): raise ValueError('La velocità non può scendere quando la temperatura sale')
    if pump and pts[0][1] < PUMP_MIN_PERCENT: raise ValueError(f'La pompa non scende sotto il {PUMP_MIN_PERCENT}%: raffredda il processore')
    if curve_duty(pts, CURVE_SAFE_AT) < CURVE_SAFE_MIN:
        raise ValueError(f'Troppo lenta quando scalda: a {CURVE_SAFE_AT} °C serve almeno il {CURVE_SAFE_MIN}%')
    return {'src': curve['src'], 'pts': pts}

def apply_fan_custom(prof: dict, custom: dict, temp_ids: dict) -> dict:
    """Applica a un profilo di Fan Control le regolazioni delle singole ventole:
    un numero = velocità fissa, un dizionario = curva sulla temperatura di CPU o GPU."""
    fc = prof.setdefault('FanControl', {})
    curves = [c for c in fc.get('FanCurves') or [] if not str(c.get('Name', '')).startswith(CURVE_PREFIX)]
    for ctl in fc.get('Controls', []):
        ident = str(ctl.get('Identifier', ''))
        v = custom.get(ident)
        if isinstance(v, int) and not isinstance(v, bool):
            ctl['Enable'] = ctl['ManualControl'] = True
            ctl['ManualControlValue'] = v
            ctl['SelectedFanCurve'] = None
        elif isinstance(v, dict):
            source = temp_ids.get(v.get('src'))
            if not source: raise RuntimeError('Sensore di temperatura non trovato: serve LibreHardwareMonitor acceso')
            name = CURVE_PREFIX + ident
            curves.append({'Name': name, 'IsHidden': False, 'CommandMode': 0,
                           'SelectedTempSource': {'Identifier': source},
                           'Points': [f'{t},{d}' for t, d in v['pts']],
                           'MaximumTemperature': 100, 'MinimumTemperature': 20, 'MaximumCommand': 100,
                           'HysteresisConfig': {'ResponseTimeUp': 2, 'ResponseTimeDown': 3, 'HysteresisValueUp': 2,
                                                'HysteresisValueDown': 3, 'IgnoreHysteresisAtLimits': True}})
            ctl['Enable'] = True
            ctl['ManualControl'] = False
            ctl['SelectedFanCurve'] = {'Name': name}
    fc['FanCurves'] = curves
    return prof

def live_fan_rpm() -> dict[str, float]:
    """RPM attuali da LibreHardwareMonitor, per id hardware e numero del connettore (es. 'nct6687dr/11')."""
    try:
        with urlopen(LHM_URL, timeout=2) as r: tree = json.loads(r.read(2_000_000))
    except Exception: return {}
    out = {}
    def walk(n):
        sid = str(n.get('SensorId', ''))
        m = re.match(r'/lpc/([^/]+)/\d+/fan/(\d+)$', sid)
        if m:
            try: out[f'{m.group(1)}/{m.group(2)}'] = float(str(n.get('Value', '0')).split()[0].replace(',', '.'))
            except ValueError: pass
        for ch in n.get('Children', []): walk(ch)
    walk(tree)
    return out

def build_fan_profiles(exe: str, eco_percent: int) -> tuple[dict[str, dict], list[str]]:
    """Un profilo per livello. Solo le ventole del case che girano davvero ricevono una velocità fissa
    (0% spente, ECO ridotta, 100% massimo); radiatore, pompa e GPU restano sempre al BIOS."""
    base_file = Path(exe).parent / 'Configurations' / 'userConfig.json'
    base = json.loads(base_file.read_text(encoding='utf-8-sig'))
    rpm = live_fan_rpm()
    profiles, chosen = {}, []
    for level, percent in dict(FAN_LEVELS, eco=eco_percent).items():
        prof = profiles[level] = json.loads(json.dumps(base))
        for ctl in prof.get('FanControl', {}).get('Controls', []):
            ident, nick = str(ctl.get('Identifier', '')), str(ctl.get('NickName', ''))
            m = re.match(r'/lpc/([^/]+)/control/(\d+)$', ident)
            case_fan = bool(m) and not any(w in (nick + ident).lower() for w in FAN_EXCLUDE) \
                and rpm.get(f'{m.group(1)}/{m.group(2)}', 0) > 200
            manual = percent is not None and (case_fan or level in ALL_FANS_LEVELS)
            ctl['Enable'] = ctl['ManualControl'] = manual
            if manual:
                ctl['ManualControlValue'] = PUMP_MIN_PERCENT if level == 'off_pump' and is_pump(nick, ident) else percent
                ctl['SelectedFanCurve'] = None
                if level == 'eco': chosen.append(nick)
    return profiles, chosen

def fancontrol_script(exe: str, staging: Path) -> str:
    dest = Path(exe).parent / 'Configurations'
    script = ''.join(f"Copy-Item -LiteralPath {_q(staging / f)} -Destination {_q(dest / f)} -Force;" for f in FAN_FILES.values())
    sid = user_sid()
    if sid:
        script += ''.join(f"& icacls.exe {_q(dest / FAN_FILES[k])} /grant {_q('*' + sid + ':(M)')} | Out-Null;" for k in FAN_MANUAL)
    for key, task in FAN_TASKS.items():
        script += task_script(task, exe, f'-c {FAN_FILES[key]}', at_logon=False, start=False)
    return script

def fancontrol_setup(exe: str, eco_percent: int, staging: Path, admin=None) -> list[str]:
    """Scrive i profili nella cartella protetta di Fan Control e crea le attività per cambiarli senza UAC."""
    profiles, chosen = build_fan_profiles(exe, eco_percent)
    if not chosen: raise RuntimeError('Nessuna ventola del case rilevata (servono i sensori collegati)')
    for k in FAN_MANUAL: profiles[k] = profiles['normal']
    staging.mkdir(parents=True, exist_ok=True)
    for level, prof in profiles.items():
        (staging / FAN_FILES[level]).write_text(json.dumps(prof, indent=2), encoding='utf-8')
    if admin:
        admin.call('fans')
        return chosen
    if not run_elevated(fancontrol_script(exe, staging), wait=True): raise RuntimeError('Conferma da amministratore annullata')
    return chosen

def winget_install(section: str, admin=None) -> str:
    pkg = WINGET.get(section)
    if not pkg: raise ValueError('Nessun pacchetto da installare')
    if admin:
        admin.call('install', key=section)
        return pkg + ' installato'
    exe = shutil.which('winget')
    if not exe: raise RuntimeError('winget non disponibile: installa "Programma di installazione app" dal Microsoft Store')
    r = subprocess.run([exe, 'install', '--id', pkg, '--exact', '--source', 'winget', '--silent',
                        '--accept-source-agreements', '--accept-package-agreements', '--disable-interactivity'],
                       capture_output=True, text=True, errors='replace', timeout=900, **_no_window())
    if r.returncode not in (0, -1978335189):  # -1978335189 = già installato
        raise RuntimeError('Installazione non riuscita: ' + (r.stdout or r.stderr).strip().splitlines()[-1][:200])
    return pkg + ' installato'

def known_folder(csidl: int) -> Path | None:
    """Cartelle vere di Windows (il Desktop può stare in OneDrive)."""
    if os.name != 'nt': return None
    buf = ctypes.create_unicode_buffer(260)
    if ctypes.windll.shell32.SHGetFolderPathW(None, csidl, None, 0, buf) != 0: return None
    return Path(buf.value)

CSIDL_DESKTOPDIRECTORY, CSIDL_PROGRAMS, CSIDL_STARTUP = 0x10, 0x02, 0x07

def shortcut_script(exe: str, links: list[Path]) -> str:
    """Crea o corregge i collegamenti: esistenti ma rivolti a un altro exe (es. vecchia cartella) vengono aggiornati."""
    body = ''.join(
        f"$s=$w.CreateShortcut({_q(l)}); if($s.TargetPath -ne {_q(exe)}){{ $s.TargetPath={_q(exe)}; "
        f"$s.WorkingDirectory={_q(Path(exe).parent)}; $s.IconLocation={_q(str(exe) + ',0')}; $s.Description='NEXAR'; $s.Save(); "
        f"Write-Output {_q(l.name + '@' + l.parent.name)} }};" for l in links)
    return "$w=New-Object -ComObject WScript.Shell;" + body

def ensure_shortcuts(state: dict) -> list[str]:
    """Voce nel menu Start sempre presente; icona sul Desktop creata solo la prima volta (se la cancelli resta cancellata)."""
    if os.name != 'nt' or not getattr(sys, 'frozen', False): return []
    exe = sys.executable
    links = []
    start, desktop = known_folder(CSIDL_PROGRAMS), known_folder(CSIDL_DESKTOPDIRECTORY)
    if start: links.append(start / 'NEXAR.lnk')
    if desktop and (not state.get('desktop_shortcut') or (desktop / 'NEXAR.lnk').exists()):
        links.append(desktop / 'NEXAR.lnk')
    if not links: return []
    r = subprocess.run(['powershell', '-NoProfile', '-Command', shortcut_script(exe, links)], capture_output=True,
                       text=True, errors='replace', timeout=30, **_no_window())
    if desktop: state['desktop_shortcut'] = True
    return [x for x in r.stdout.split() if x]

def autostart_target():
    if getattr(sys, 'frozen', False): return f'"{sys.executable}" --minimized'
    pyw = Path(sys.executable).with_name('pythonw.exe')
    return f'"{pyw if pyw.is_file() else sys.executable}" "{Path(__file__).with_name("desktop.py")}" --minimized'

AUTOSTART_NAME, AUTOSTART_LEGACY = 'NEXAR', 'PC ECO Control'
AUTOSTART_TASK = 'NEXAR - Avvio'

# Avvio veloce: i programmi nell'elenco "Esecuzione automatica" partono quando Windows ha finito di caricare
# (con tanti programmi all'avvio anche 1-2 minuti dopo l'accesso). Un'attività pianificata "all'accesso" parte subito.
def autostart_task_ok() -> bool:
    if os.name != 'nt' or not getattr(sys, 'frozen', False): return False
    r = subprocess.run(['schtasks', '/query', '/tn', AUTOSTART_TASK, '/xml'], capture_output=True, **_no_window())
    if r.returncode != 0: return False
    raw = r.stdout
    text = raw.decode('utf-16', errors='replace') if raw[:2] in (b'\xff\xfe', b'\xfe\xff') else raw.decode('utf-8', errors='replace')
    return sys.executable.lower() in text.lower()

def autostart_task_script(exe: str) -> str:
    user = f"{os.environ.get('USERDOMAIN', '')}\\{os.environ.get('USERNAME', '')}".strip('\\')
    return (f"$a=New-ScheduledTaskAction -Execute {_q(exe)} -Argument '--minimized' -WorkingDirectory {_q(Path(exe).parent)};"
            f"$t=New-ScheduledTaskTrigger -AtLogOn -User {_q(user)};"
            f"$p=New-ScheduledTaskPrincipal -UserId {_q(user)} -RunLevel Limited -LogonType Interactive;"
            # priorità 4 = normale (quella predefinita delle attività rallenterebbe NEXAR)
            "$s=New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit 0 -Priority 4 -MultipleInstances IgnoreNew;"
            f"Register-ScheduledTask -TaskName {_q(AUTOSTART_TASK)} -Action $a -Trigger $t -Principal $p -Settings $s -Force;")

def autostart_legacy_off():
    """Con l'avvio veloce attivo, niente seconda partenza dall'elenco di Windows."""
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            for name in (AUTOSTART_NAME, AUTOSTART_LEGACY):
                try: winreg.DeleteValue(k, name)
                except FileNotFoundError: pass
    except OSError as ex: logging.info('Avvio dal registro non tolto: %s', ex)
    link = startup_link()
    if link:
        try: link.unlink()
        except (FileNotFoundError, OSError): pass

def autostart_fast(admin=None) -> str:
    """Una conferma amministratore: NEXAR parte appena accedi a Windows."""
    if not getattr(sys, 'frozen', False): raise RuntimeError('Si attiva dall\'app installata')
    if admin: admin.call('autostart')
    elif not run_elevated(autostart_task_script(sys.executable), wait=True): raise RuntimeError('Conferma amministratore annullata')
    if not autostart_task_ok(): raise RuntimeError('Attività di avvio non creata')
    autostart_legacy_off()
    return 'Avvio veloce attivo: NEXAR parte appena accedi a Windows'

def autostart_fast_off(admin=None):
    if os.name == 'nt' and task_exists(AUTOSTART_TASK):
        if admin: admin.call('autostart_off'); return
        run_elevated(f"Unregister-ScheduledTask -TaskName {_q(AUTOSTART_TASK)} -Confirm:$false", wait=True)

def startup_link() -> Path | None:
    folder = known_folder(CSIDL_STARTUP)
    return folder / 'NEXAR.lnk' if folder else None

def autostart_get() -> bool:
    """Attivo solo se punta a questo programma (attività all'accesso, registro o cartella Esecuzione automatica)."""
    if os.name != 'nt': return False
    if autostart_task_ok(): return True
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            if winreg.QueryValueEx(k, AUTOSTART_NAME)[0] == autostart_target(): return True
    except OSError: pass
    link = startup_link()
    return bool(getattr(sys, 'frozen', False) and link and link.is_file())

def _startup_link_set(enable: bool):
    """Riserva: se il registro non si lascia scrivere, collegamento in Esecuzione automatica."""
    link = startup_link()
    if not link: raise OSError('Cartella Esecuzione automatica non trovata')
    if not enable:
        try: link.unlink()
        except FileNotFoundError: pass
        return
    exe = sys.executable
    ps = (f"$w=New-Object -ComObject WScript.Shell; $s=$w.CreateShortcut({_q(link)}); $s.TargetPath={_q(exe)}; $s.Arguments='--minimized';"
          f" $s.WorkingDirectory={_q(Path(exe).parent)}; $s.IconLocation={_q(str(exe) + ',0')}; $s.Description='NEXAR'; $s.Save()")
    subprocess.run(['powershell', '-NoProfile', '-Command', ps], capture_output=True, text=True, errors='replace', timeout=30, **_no_window())
    if not link.is_file(): raise OSError('Collegamento di avvio non creato')

def autostart_set(enable: bool):
    if os.name != 'nt': return
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            if enable: winreg.SetValueEx(k, AUTOSTART_NAME, 0, winreg.REG_SZ, autostart_target())
            for name in ((AUTOSTART_LEGACY,) if enable else (AUTOSTART_NAME, AUTOSTART_LEGACY)):
                try: winreg.DeleteValue(k, name)
                except FileNotFoundError: pass
        if not enable and getattr(sys, 'frozen', False): _startup_link_set(False)
    except OSError as ex:
        if not getattr(sys, 'frozen', False): raise
        logging.warning('Avvio con Windows nel registro non riuscito (%s): uso la cartella Esecuzione automatica', ex)
        _startup_link_set(enable)

def _keep(path):
    """Un percorso inserito a mano e ancora valido ha la precedenza sulla ricerca."""
    return path if isinstance(path, str) and path and Path(path).is_file() else ''

def item(key, name, level, detail, install=False):
    return {'key': key, 'name': name, 'level': level, 'detail': detail, 'install': install}

def autoconfigure(config: dict, state: dict, allow_uac=False) -> list[dict]:
    """Rileva tutto, aggiorna config sul posto e restituisce lo stato di ogni collegamento."""
    report = []

    rgb = config.setdefault('rgb', {})
    exe = _keep(rgb.get('openrgb_exe')) or find_openrgb()
    if exe:
        rgb['openrgb_exe'] = exe
        rgb['enabled'] = True
        custom = rgb.get('eco_profile') and rgb.get('normal_profile')
        if custom or port_open(OPENRGB_PORT):
            report.append(item('rgb', 'OpenRGB', 'ok', 'Profili personali' if custom else
                               'ECO spegne tutti i LED (RAM, GPU, scheda madre, ventole), Normale li riaccende'))
        else:
            allow = allow_uac or not state.get('openrgb_uac_asked')
            result = openrgb_start(exe, allow)
            if result != 'serve conferma': state['openrgb_uac_asked'] = True
            report.append(item('rgb', 'OpenRGB', 'warn', {'avviato': 'Avvio del server RGB in corso…',
                'annullato': 'Premi "Collega" e conferma come amministratore (serve per la RAM)',
                'serve conferma': 'Premi "Collega" e conferma come amministratore (serve per la RAM)'}[result]))
    else:
        rgb['enabled'] = False
        report.append(item('rgb', 'OpenRGB', 'missing', 'Non installato: LED non controllabili', True))

    fans = config.setdefault('fans', {})
    exe = _keep(fans.get('fancontrol_exe')) or find_fancontrol()
    if exe:
        fans['fancontrol_exe'] = exe
        names = fancontrol_profiles(exe)
        eco, normal = fans.get('eco_profile', ''), fans.get('normal_profile', '')
        if eco not in names or normal not in names:
            eco, normal = guess_profiles(names)
        if eco and normal:
            fans.update({'enabled': True, 'eco_profile': eco, 'normal_profile': normal})
            report.append(item('fans', 'Fan Control', 'ok', f'ECO: {eco} · Normale: {normal}'))
        else:
            fans['enabled'] = False
            report.append(item('fans', 'Fan Control', 'warn',
                'Trovato. Premi "Configura": ECO abbassa solo le ventole del case, radiatore e pompa restano al BIOS'))
    else:
        fans['enabled'] = False
        report.append(item('fans', 'Fan Control', 'missing', 'Non installato: ventole gestite dal BIOS', True))

    exe = find_lhm()
    config.setdefault('sensors', {})['libre_hardware_monitor'] = LHM_URL
    if sensors_online():
        report.append(item('sensors', 'Sensori CPU (LibreHardwareMonitor)', 'ok', 'Temperature e RPM collegati'))
    elif exe:
        lhm_enable_webserver(exe)
        allow = allow_uac or not state.get('lhm_uac_asked')
        result = lhm_start(exe, allow)
        if result != 'serve conferma': state['lhm_uac_asked'] = True
        detail = {'avviato': 'Avvio in corso…', 'annullato': 'Avvio annullato: premi "Collega" e conferma come amministratore',
                  'serve conferma': 'Premi "Collega" e conferma come amministratore'}[result]
        report.append(item('sensors', 'Sensori CPU (LibreHardwareMonitor)', 'warn', detail))
    else:
        report.append(item('sensors', 'Sensori CPU (LibreHardwareMonitor)', 'missing',
                           'Non installato: temperatura CPU non disponibile', True))

    smi = find_nvidia_smi()
    report.append(item('gpu', 'GPU NVIDIA', 'ok' if smi else 'missing',
                       'Temperatura e watt GPU collegati' if smi else 'nvidia-smi non trovato (driver NVIDIA?)'))

    procs = config.setdefault('auto_detect', {}).setdefault('process_names', ['codex.exe', 'claude.exe'])
    report.append(item('ai', 'Codex / Claude', 'ok', 'Rilevamento automatico: ' + ', '.join(procs)))

    tg = config.get('telegram', {})
    if not (tg.get('token') and tg.get('allowed_user_id')):
        report.append(item('tunnel', 'App Telegram', 'warn', 'Collega prima il bot in Impostazioni → Telegram'))
    elif find_exe('cloudflared.exe', ['cloudflared', 'Cloudflare\\cloudflared']) or str(tg.get('webapp_url', '')).startswith('https://'):
        report.append(item('tunnel', 'App Telegram', 'ok', 'Pulsante "Apri app" nel bot, funziona anche fuori casa'))
    else:
        report.append(item('tunnel', 'App Telegram', 'missing', 'Serve Cloudflare Tunnel per aprire la dashboard dentro Telegram', True))

    if os.name == 'nt':
        # Solo il programma installato si iscrive all'avvio: una copia di prova non deve prenderne il posto.
        wanted, err = config.get('autostart', True), ''
        fast = wanted and autostart_task_ok()
        if fast: autostart_legacy_off()
        elif wanted and getattr(sys, 'frozen', False) and not autostart_get():
            try: autostart_set(True)
            except OSError as ex: err = str(ex)[:120]; logging.warning('Avvio automatico: %s', ex)
        on = autostart_get()
        why = ('Disattivato: accendilo qui sotto' if not wanted else 'Non riuscito: ' + err if err
               else 'Si attiva dall\'app installata' if not getattr(sys, 'frozen', False) else 'Non attivo')
        if fast: report.append(item('autostart', 'Avvio con Windows', 'ok', 'Parte subito, appena accedi a Windows'))
        elif on:
            report.append(item('autostart', 'Avvio con Windows', 'warn',
                               'Parte 1–2 minuti dopo l\'accesso: premi Avvio veloce (una conferma amministratore)'))
            report[-1]['fast'] = True
        else: report.append(item('autostart', 'Avvio con Windows', 'warn', why))
        try:
            made = ensure_shortcuts(state)
            if made: logging.info('Icone NEXAR create/aggiornate: %s', ', '.join(made))
        except (OSError, subprocess.TimeoutExpired) as ex: logging.warning('Icone Desktop/Start: %s', ex)
    logging.info('Collegamenti: %s', json.dumps([(r['key'], r['level']) for r in report]))
    return report

# ---------- inventario per la stima dei consumi e l'accensione a distanza ----------
INVENTORY_PS = r"""
$ErrorActionPreference='SilentlyContinue'
$dimms=@(Get-CimInstance Win32_PhysicalMemory).Count
$disks=@(Get-PhysicalDisk | ForEach-Object { [pscustomobject]@{id=[string]$_.DeviceId;name=$_.FriendlyName;media=[string]$_.MediaType;bus=[string]$_.BusType} })
$nic=Get-NetAdapter -Physical | Where-Object { $_.Status -eq 'Up' -and $_.MediaType -eq '802.3' } | Select-Object -First 1
$net=$null
if($nic){
 $ip=Get-NetIPAddress -InterfaceIndex $nic.ifIndex -AddressFamily IPv4 | Select-Object -First 1
 $adv=@{}; Get-NetAdapterAdvancedProperty -Name $nic.Name | ForEach-Object { $adv[$_.RegistryKeyword]=[string]$_.RegistryValue }
 $net=[pscustomobject]@{name=$nic.Name;desc=$nic.InterfaceDescription;mac=$nic.MacAddress;ip=$ip.IPAddress;prefix=[int]$ip.PrefixLength;
  magic=$adv['*WakeOnMagicPacket'];s5=$adv['S5WakeOnLan']}
}
$cpu=(Get-CimInstance Win32_Processor | Select-Object -First 1).Name
$gpus=@(Get-CimInstance Win32_VideoController | ForEach-Object { $_.Name })
$mb=Get-CimInstance Win32_BaseBoard
[pscustomobject]@{dimms=$dimms;disks=$disks;net=$net;cpu=$cpu;gpus=$gpus;board_vendor=$mb.Manufacturer;board=$mb.Product} | ConvertTo-Json -Depth 4 -Compress
"""
VIRTUAL_GPU = ('basic display', 'basic render', 'virtual', 'parsec', 'remote', 'citrix', 'vmware', 'hyper-v', 'idd', 'meta ')
VENDORS = {'micro-star': 'MSI', 'asustek': 'ASUS', 'gigabyte': 'Gigabyte', 'asrock': 'ASRock', 'biostar': 'Biostar', 'nzxt': 'NZXT'}

def pick_gpu(names) -> str:
    """Scheda video vera: niente adattatori virtuali; una dedicata vince sulla grafica integrata."""
    real = [n.strip() for n in names or [] if n and not any(v in n.lower() for v in VIRTUAL_GPU)]
    dedicated = [n for n in real if re.search(r'nvidia|geforce|rtx|gtx|radeon rx|radeon pro|arc a|arc b', n, re.I)]
    return (dedicated or real or [''])[0]

def board_name(vendor, product) -> str:
    short = next((v for k, v in VENDORS.items() if k in (vendor or '').lower()), (vendor or '').split(' ')[0])
    product = (product or '').strip()
    return f'{short} {product}'.strip() if product and short.lower() not in product.lower() else product

def disk_kind(d: dict) -> str:
    name, media, bus = (d.get('name') or '').upper(), (d.get('media') or '').upper(), (d.get('bus') or '').upper()
    if bus == 'NVME': return 'nvme'
    if media == 'SSD' or 'SSD' in name: return 'ssd'
    if media == 'HDD': return 'hdd'
    # Molti dischi meccanici SATA (es. WD Green) non dichiarano il tipo.
    return 'hdd' if bus in ('SATA', 'SAS', 'ATA') else 'ssd'

def broadcast_of(ip: str, prefix: int) -> str:
    import ipaddress
    try: return str(ipaddress.ip_network(f'{ip}/{prefix}', strict=False).broadcast_address)
    except ValueError: return '255.255.255.255'

def hardware_inventory() -> dict:
    if os.name != 'nt': return {}
    try:
        out = subprocess.run(['powershell', '-NoProfile', '-Command', INVENTORY_PS], capture_output=True, text=True,
                             errors='replace', timeout=40, **_no_window()).stdout
        raw = json.loads(out.strip() or '{}')
    except (OSError, ValueError, subprocess.TimeoutExpired) as ex:
        logging.warning('Inventario hardware: %s', ex); return {}
    disks = raw.get('disks') or []
    if isinstance(disks, dict): disks = [disks]
    inv = {'dimms': int(raw.get('dimms') or 0),
           'disks': [{'id': d.get('id'), 'name': d.get('name'), 'kind': disk_kind(d)} for d in disks]}
    net = raw.get('net')
    if net and net.get('mac'):
        inv['net'] = {'name': net.get('name'), 'desc': net.get('desc'), 'mac': net['mac'].replace('-', ':').upper(),
                      'ip': net.get('ip') or '', 'broadcast': broadcast_of(net.get('ip') or '', net.get('prefix') or 24),
                      # Valori registro del driver: 1 = attivo; None = il driver non espone l'opzione.
                      'wol_magic': None if net.get('magic') is None else net.get('magic') == '1',
                      'wol_shutdown': None if net.get('s5') is None else net.get('s5') == '1'}
    gpus = raw.get('gpus') or []
    cpu = re.sub(r'\s+', ' ', str(raw.get('cpu') or '')).strip()
    inv['hardware'] = {'cpu': re.sub(r'\s+\d+-Core Processor$|\(R\)|\(TM\)', '', cpu).strip(),
                       'gpu': pick_gpu([gpus] if isinstance(gpus, str) else gpus),
                       'motherboard': board_name(raw.get('board_vendor'), raw.get('board'))}
    return inv

def wol_enable_script(adapter: str) -> str:
    """Attiva Wake-on-LAN sulla scheda di rete (anche da spento, se il driver lo prevede)."""
    a = _q(adapter)
    return (f"Set-NetAdapterAdvancedProperty -Name {a} -RegistryKeyword '*WakeOnMagicPacket' -RegistryValue 1 -ErrorAction SilentlyContinue;"
            f"Set-NetAdapterAdvancedProperty -Name {a} -RegistryKeyword 'S5WakeOnLan' -RegistryValue 1 -ErrorAction SilentlyContinue;"
            f"Set-NetAdapterPowerManagement -Name {a} -WakeOnMagicPacket Enabled -ErrorAction SilentlyContinue;"
            f"$d=Get-PnpDevice -FriendlyName (Get-NetAdapter -Name {a}).InterfaceDescription; powercfg /deviceenablewake $d.FriendlyName")
