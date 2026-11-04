"""Gaming Boost: con la modalità Gaming NEXAR dà priorità al gioco, chiude o rallenta le app scelte dall'utente
e prepara Windows (Modalità gioco attiva, registrazione Xbox in background spenta). Uscendo rimette tutto com'era.

Niente viene chiuso senza che l'utente l'abbia scelto, e la chiusura è "gentile" (come la X della finestra):
se un programma chiede di salvare, resta aperto.
"""
from __future__ import annotations
import ctypes
import logging
import os
import subprocess
import threading
import time
from pathlib import Path

import psutil

GAME_FOLDERS = ('steamapps\\common', 'epic games', 'riot games', 'xboxgames', 'gog galaxy\\games', 'gog games',
                'ubisoft game launcher\\games', 'ea games', 'battle.net', 'rockstar games', 'minecraft')
# Mai toccati: sistema, NEXAR e gli strumenti che la fanno funzionare.
PROTECTED = {'system', 'registry', 'smss.exe', 'csrss.exe', 'wininit.exe', 'winlogon.exe', 'services.exe', 'lsass.exe',
             'svchost.exe', 'explorer.exe', 'dwm.exe', 'sihost.exe', 'fontdrvhost.exe', 'ctfmon.exe', 'searchhost.exe',
             'startmenuexperiencehost.exe', 'shellexperiencehost.exe', 'runtimebroker.exe', 'taskhostw.exe', 'conhost.exe',
             'audiodg.exe', 'nexar.exe', 'cloudflared.exe', 'openrgb.exe', 'fancontrol.exe', 'librehardwaremonitor.exe',
             'securityhealthsystray.exe', 'msmpeng.exe', 'nvcontainer.exe', 'nvdisplay.container.exe', 'textinputhost.exe',
             'applicationframehost.exe', 'lockapp.exe', 'widgets.exe', 'useroobebroker.exe', 'python.exe', 'pythonw.exe',
             'msedgewebview2.exe', 'nvidia share.exe', 'nvidia overlay.exe', 'gamebar.exe', 'gamebarftserver.exe'}
TWEAKS = {
    # chiave: (descrizione, hive, percorso, nome, valore in Gaming)
    'game_mode': ('Modalità gioco di Windows', 'HKCU', r'Software\Microsoft\GameBar', 'AutoGameModeEnabled', 1),
    'no_dvr': ('Registrazione Xbox in background spenta', 'HKCU', r'System\GameConfigStore', 'GameDVR_Enabled', 0),
    'no_capture': ('Acquisizione Game Bar spenta', 'HKCU', r'Software\Microsoft\Windows\CurrentVersion\GameDVR', 'AppCaptureEnabled', 0),
}
DEFAULTS = {'game_priority': True, 'game_mode': True, 'no_dvr': True, 'reopen': True, 'apps': {}}
HIGH, BELOW = (psutil.HIGH_PRIORITY_CLASS, psutil.BELOW_NORMAL_PRIORITY_CLASS) if os.name == 'nt' else (-5, 5)

def is_game(exe: str) -> bool:
    low = (exe or '').lower()
    return any(f in low for f in GAME_FOLDERS)

def foreground_fullscreen_pid():
    """PID dell'app a schermo intero in primo piano (quasi sempre il gioco)."""
    if os.name != 'nt': return None
    u = ctypes.windll.user32
    hwnd = u.GetForegroundWindow()
    if not hwnd: return None
    class RECT(ctypes.Structure): _fields_ = [('l', ctypes.c_long), ('t', ctypes.c_long), ('r', ctypes.c_long), ('b', ctypes.c_long)]
    class MONITORINFO(ctypes.Structure): _fields_ = [('cbSize', ctypes.c_ulong), ('rcMonitor', RECT), ('rcWork', RECT), ('dwFlags', ctypes.c_ulong)]
    win, mi = RECT(), MONITORINFO(ctypes.sizeof(MONITORINFO))
    if not u.GetWindowRect(hwnd, ctypes.byref(win)) or not u.GetMonitorInfoW(u.MonitorFromWindow(hwnd, 2), ctypes.byref(mi)): return None
    m = mi.rcMonitor
    if (win.l, win.t, win.r, win.b) != (m.l, m.t, m.r, m.b): return None
    pid = ctypes.c_ulong()
    u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value or None

def user_apps():
    """App aperte dall'utente (un elemento per eseguibile), tra cui scegliere cosa chiudere o rallentare in Gaming."""
    me = psutil.Process().username() if os.name == 'nt' else None
    apps = {}
    for p in psutil.process_iter(['name', 'exe', 'username', 'memory_info']):
        try:
            name = (p.info['name'] or '').lower()
            if not name or name in PROTECTED or not p.info['exe'] or (me and p.info['username'] != me): continue
            if p.info['exe'].lower().startswith(os.environ.get('WINDIR', r'C:\Windows').lower()): continue
            a = apps.setdefault(name, {'name': name, 'exe': p.info['exe'], 'bytes': 0, 'count': 0, 'game': is_game(p.info['exe'])})
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

class Booster:
    def __init__(self, config: dict, notify=lambda m: None, log=lambda m: None):
        self.config, self.notify, self.log = config, notify, log
        self.lock = threading.RLock()
        self.active = False
        self.saved_tweaks = {}     # chiave -> valore originale (None = non esisteva)
        self.boosted = {}          # pid -> (nome, priorità originale)
        self.lowered = {}
        self.closed = []           # app chiuse da riaprire: {name, exe, cmdline, cwd}
        self.game = ''

    def settings(self):
        return {**DEFAULTS, **self.config.setdefault('gaming_boost', {})}

    def update_settings(self, new: dict):
        """Opzioni e scelte per app (close / lower / nessuna) salvate in config['gaming_boost']."""
        cur = self.config.setdefault('gaming_boost', {})
        for k in ('game_priority', 'game_mode', 'no_dvr', 'reopen'):
            if k in new:
                if type(new[k]) is not bool: raise ValueError(f'{k}: true/false')
                cur[k] = new[k]
        if 'apps' in new:
            apps = new['apps']
            if not isinstance(apps, dict) or len(apps) > 80: raise ValueError('apps non valido')
            clean = {}
            for name, act in apps.items():
                name = str(name).lower()
                if act not in ('close', 'lower') or name in PROTECTED or not name.endswith('.exe') or len(name) > 80: continue
                clean[name] = act
            cur['apps'] = clean
        return self.settings()

    def info(self):
        with self.lock:
            return {'active': self.active, 'game': self.game, 'boosted': sorted({n for n, _ in self.boosted.values()}),
                    'lowered': sorted({n for n, _ in self.lowered.values()}), 'closed': [c['name'] for c in self.closed],
                    'tweaks': [TWEAKS[k][0] for k in self.saved_tweaks], 'settings': self.settings()}

    def start(self):
        if os.name != 'nt': return 'Gaming Boost disponibile solo su Windows'
        s = self.settings(); notes = []
        with self.lock:
            if self.active: return 'Gaming Boost già attivo'
            self.active = True
            for key, (label, hive, path, name, value) in TWEAKS.items():
                if not s.get('game_mode' if key == 'game_mode' else 'no_dvr'): continue
                try:
                    self.saved_tweaks[key] = _reg(hive, path, name)
                    _reg(hive, path, name, value)
                except OSError as ex: logging.warning('Gaming Boost %s: %s', key, ex)
            if self.saved_tweaks: notes.append('Windows pronto per giocare')
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
        """Ogni pochi secondi in Gaming: priorità alta al gioco, bassa alle app scelte (anche se riaperte)."""
        s = self.settings()
        with self.lock:
            if not self.active: return
        fg = foreground_fullscreen_pid()
        lower = {n for n, act in s['apps'].items() if act == 'lower'}
        for p in psutil.process_iter(['name', 'exe']):
            try:
                name = (p.info['name'] or '').lower()
                if name in PROTECTED: continue
                if s['game_priority'] and (is_game(p.info['exe']) or p.pid == fg) and p.pid not in self.boosted:
                    old = p.nice(); p.nice(HIGH)
                    with self.lock: self.boosted[p.pid] = (name, old); self.game = name.replace('.exe', '')
                elif name in lower and p.pid not in self.lowered:
                    old = p.nice(); p.nice(BELOW)
                    with self.lock: self.lowered[p.pid] = (name, old)
            except (psutil.Error, OSError): continue

    def stop(self):
        with self.lock:
            if not self.active: return ''
            self.active = False
            tweaks, boosted, lowered, closed = dict(self.saved_tweaks), dict(self.boosted), dict(self.lowered), list(self.closed)
            self.saved_tweaks, self.boosted, self.lowered, self.closed, self.game = {}, {}, {}, [], ''
        for key, old in tweaks.items():
            _, hive, path, name, _ = TWEAKS[key]
            try:
                if old is None: _reg(hive, path, name, delete=True)   # non c'era: si toglie
                else: _reg(hive, path, name, old)
            except OSError: pass
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
        msg = 'Gaming Boost spento: tutto come prima' + (' · riaperte ' + ', '.join(reopened) if reopened else '')
        self.log(msg)
        return msg
