"""Programmi inutili fermati in Gaming e in AI ECO.

- "Chiudi": il programma viene chiuso e, se riparte mentre la modalità è attiva, richiuso.
- "Rallenta": priorità bassa e modalità efficienza di Windows (EcoQoS), come in Gestione attività.
- In AI ECO anche tutto ciò che gira in sfondo senza finestra va in modalità efficienza.
Uscendo dalla modalità le priorità tornano come prima. Sistema, NEXAR, driver e collegamenti non si toccano mai.
"""
import ctypes
import logging
import os
import subprocess
import time
from ctypes import wintypes

import psutil

from gaming_boost import PROTECTED, is_game

# Programmi di sfondo che non servono mentre giochi o risparmi: aggiornamenti, assistenti, overlay, webcam virtuali.
JUNK = {
    'browser_assistant.exe': 'assistente del browser Opera',
    'gjagent.exe': 'aggiornamenti Gaijin',
    'overwolf.exe': 'Overwolf', 'overwolfbrowser.exe': 'Overwolf', 'overwolfhelper.exe': 'Overwolf', 'overwolfhelper64.exe': 'Overwolf',
    'overwolftray.exe': 'Overwolf',
    'manycam.exe': 'webcam virtuale ManyCam', 'snap camera.exe': 'webcam virtuale Snap Camera',
    'quick-look.exe': 'anteprime Insta360',
    'adobearm.exe': 'aggiornamenti Adobe', 'ccxprocess.exe': 'Adobe Creative Cloud', 'adobecollabsync.exe': 'Adobe Acrobat',
    'acrotray.exe': 'Adobe Acrobat', 'jusched.exe': 'aggiornamenti Java', 'ituneshelper.exe': 'iTunes',
    'phoneexperiencehost.exe': 'Collegamento al telefono', 'yourphone.exe': 'Collegamento al telefono',
    'cortana.exe': 'Cortana', 'skypebackgroundhost.exe': 'Skype in sfondo',
    'googlecrashhandler.exe': 'segnalazioni errori Google', 'googlecrashhandler64.exe': 'segnalazioni errori Google',
}
# Mai rallentati in AI ECO anche se senza finestra: audio, input, rete e i programmi che NEXAR usa.
NEVER_THROTTLE = PROTECTED | {'nvidia broadcast.exe', 'ds4windows.exe', 'dsx.exe', 'windscribe.exe', 'windscribeservice.exe',
                              'hass.agent.net10.exe', 'hass.agent.exe', 'voicemeeter.exe', 'wavelink.exe',
                              # AI ECO parte proprio mentre lavorano Codex e Claude: loro e i loro strumenti restano veloci.
                              'codex.exe', 'claude.exe', 'node.exe', 'git.exe', 'bash.exe', 'pwsh.exe', 'powershell.exe',
                              'cmd.exe', 'windowsterminal.exe', 'openconsole.exe', 'code.exe', 'rg.exe'}
IDLE = psutil.IDLE_PRIORITY_CLASS if os.name == 'nt' else 19
RECLOSE_SECONDS = 20


class _PPT(ctypes.Structure):
    _fields_ = [('Version', wintypes.ULONG), ('ControlMask', wintypes.ULONG), ('StateMask', wintypes.ULONG)]


def efficiency(pid: int, on: bool) -> bool:
    """Modalità efficienza di Windows 11 (EcoQoS): il processo gira sui core più lenti e a frequenza bassa."""
    if os.name != 'nt': return False
    k32 = ctypes.WinDLL('kernel32', use_last_error=True)
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k32.SetProcessInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    h = k32.OpenProcess(0x0200, False, pid)   # PROCESS_SET_INFORMATION
    if not h: return False
    try:
        st = _PPT(1, 1 if on else 0, 1 if on else 0)   # spento = Windows torna a decidere da solo
        return bool(k32.SetProcessInformation(h, 4, ctypes.byref(st), ctypes.sizeof(st)))   # ProcessPowerThrottling
    finally:
        k32.CloseHandle(h)


def visible_pids() -> set:
    """Processi con almeno una finestra visibile: quelli si stanno usando, non si rallentano."""
    if os.name != 'nt': return set()
    u = ctypes.windll.user32
    out = set()
    proc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def cb(h, _):
        if u.IsWindowVisible(h) and u.GetWindowTextLengthW(h):
            pid = wintypes.DWORD(); u.GetWindowThreadProcessId(h, ctypes.byref(pid)); out.add(pid.value)
        return True
    u.EnumWindows(proc(cb), 0)
    return out


def plan(rules: dict, junk_on: bool) -> dict:
    """Cosa fare di ogni programma: i noti inutili si chiudono (se l'opzione è attiva), le scelte dell'utente vincono."""
    out = {n: 'close' for n in JUNK} if junk_on else {}
    for name, act in (rules or {}).items():
        if act == 'keep': out.pop(name, None)
        elif act in ('close', 'lower'): out[name] = act
    return {n: a for n, a in out.items() if n not in PROTECTED}


class Stopper:
    def __init__(self):
        self.mode = None
        self.throttled = {}      # pid -> (nome, priorità originale)
        self.last_close = {}     # nome -> quando l'ho chiuso l'ultima volta
        self.stopped = set()     # nomi fermati in questa modalità (per la pagina)
        self.me = None

    def info(self):
        return {'mode': self.mode, 'stopped': sorted(self.stopped), 'throttled': len(self.throttled)}

    def release(self):
        """Fuori da Gaming/AI ECO: priorità ed efficienza come prima."""
        for pid, (name, old) in list(self.throttled.items()):
            try:
                efficiency(pid, False)
                psutil.Process(pid).nice(old)
            except (psutil.Error, OSError): pass
        self.throttled.clear(); self.stopped.clear(); self.mode = None

    def _throttle(self, p, name):
        if p.pid in self.throttled: return
        try:
            old = p.nice()
            if old in (psutil.HIGH_PRIORITY_CLASS, psutil.REALTIME_PRIORITY_CLASS): return   # qualcuno l'ha voluto veloce
            p.nice(IDLE if self.mode == 'eco' else psutil.BELOW_NORMAL_PRIORITY_CLASS)
            efficiency(p.pid, True)
            self.throttled[p.pid] = (name, old)
        except (psutil.Error, OSError): pass

    def tick(self, mode, rules, junk_on=True, throttle_bg=True, now=None, closer=None, spare=()):
        """Una passata (ogni 5 s). Restituisce i programmi appena chiusi. spare = da non rallentare mai."""
        now = time.monotonic() if now is None else now
        spare = {s.lower() for s in spare}
        if mode not in ('eco', 'gaming'):
            if self.mode: self.release()
            return []
        if mode != self.mode:
            self.release(); self.mode = mode
        todo = plan(rules, junk_on)
        if self.me is None:
            try: self.me = psutil.Process().username()
            except psutil.Error: self.me = ''
        shown = visible_pids() if mode == 'eco' and throttle_bg else set()
        mine = os.getpid()
        to_close, alive = {}, set()
        for p in psutil.process_iter(['name', 'username', 'exe']):
            try:
                alive.add(p.pid)
                name = (p.info['name'] or '').lower()
                if not name.endswith('.exe') or name in PROTECTED or p.pid == mine: continue
                if self.me and p.info['username'] != self.me: continue
                exe = p.info['exe'] or ''
                if exe.lower().startswith(os.environ.get('WINDIR', r'C:\Windows').lower()): continue
                act = todo.get(name)
                if act == 'close':
                    if is_game(exe, name) and name not in JUNK: continue          # mai il gioco
                    to_close.setdefault(name, []).append(p)
                elif act == 'lower':
                    if mode == 'eco': self._throttle(p, name)                     # in Gaming lo fa già il Boost
                elif mode == 'eco' and throttle_bg and name not in NEVER_THROTTLE and name not in spare and p.pid not in shown \
                        and (rules or {}).get(name) != 'keep' and not is_game(exe, name):
                    self._throttle(p, name)
            except (psutil.Error, OSError): continue
        for pid in [k for k in self.throttled if k not in alive]: self.throttled.pop(pid, None)
        closed = []
        for name, procs in to_close.items():
            if now - self.last_close.get(name, -1e9) < RECLOSE_SECONDS: continue
            self.last_close[name] = now
            if (closer or close)(name, procs, force=name in JUNK):
                closed.append(name); self.stopped.add(name)
        return closed


def close(name, procs, force=False):
    """Chiusura gentile; i programmi noti come inutili, se non rispondono, vengono chiusi del tutto."""
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    subprocess.run(['taskkill', '/im', name], capture_output=True, creationflags=flags)
    gone, alive = psutil.wait_procs(procs, timeout=4)
    if alive and force:
        subprocess.run(['taskkill', '/f', '/im', name], capture_output=True, creationflags=flags)
        gone, alive = psutil.wait_procs(alive, timeout=3)
    if alive: logging.info('Non chiuso: %s', name)
    return not alive


def startup_junk(items):
    """Programmi inutili che partono da soli con Windows: si possono togliere dall'avvio (si riattivano quando vuoi)."""
    out = []
    for it in items or []:
        cmd = str(it.get('command', '')).lower()
        hit = next((n for n in JUNK if n in cmd), None)
        if hit and it.get('enabled'): out.append({'id': it['id'], 'name': it['name'], 'why': JUNK[hit], 'admin': it.get('admin', False)})
    return out
