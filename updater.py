"""Aggiornamenti: l'app controlla le release di GitHub e avvisa; quando l'utente preme Aggiorna scarica lo zip,
ne verifica l'hash e si sostituisce. Niente installazioni da sola.

Solo dall'exe (non da sorgente). I dati dell'utente stanno in %LOCALAPPDATA%\\NEXAR e non vengono toccati.
"""
from __future__ import annotations
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
import zipfile
from pathlib import Path
from urllib.request import Request, urlopen

from version import REPO, VERSION

API = f'https://api.github.com/repos/{REPO}/releases/latest'
ASSET = re.compile(r'^NEXAR-(\d+\.\d+\.\d+)-win64\.zip$')
CHECK_EVERY = 6 * 3600
MAX_ZIP = 400 * 1024 * 1024
HEADERS = {'User-Agent': 'NEXAR-updater', 'Accept': 'application/vnd.github+json'}

def parse(tag):
    m = re.fullmatch(r'v?(\d+)\.(\d+)\.(\d+)', str(tag or '').strip())
    return tuple(map(int, m.groups())) if m else None

def fetch(url, limit=2_000_000):
    with urlopen(Request(url, headers=HEADERS), timeout=25) as r:
        return r.read(limit)

def download(url, dest: Path, progress=None):
    """Scarica verificando dimensione e hash. progress(fatti, totale) a ogni blocco, per la barra nella dashboard."""
    if not url.startswith('https://github.com/'): raise RuntimeError('Indirizzo di download non previsto')
    h = hashlib.sha256(); size = 0
    with urlopen(Request(url, headers={'User-Agent': HEADERS['User-Agent']}), timeout=60) as r, open(dest, 'wb') as f:
        total = int(r.headers.get('Content-Length') or 0)
        if progress: progress(0, total)
        while chunk := r.read(256 * 1024):
            size += len(chunk)
            if size > MAX_ZIP: raise RuntimeError('Aggiornamento troppo grande')
            h.update(chunk); f.write(chunk)
            if progress: progress(size, total)
    return h.hexdigest()

def safe_extract(zip_path: Path, dest: Path):
    """Niente percorsi assoluti o con '..': lo zip non può scrivere fuori dalla cartella di appoggio."""
    if dest.exists(): shutil.rmtree(dest)
    with zipfile.ZipFile(zip_path) as z:
        for name in z.namelist():
            target = (dest / name).resolve()
            if not str(target).startswith(str(dest.resolve())): raise RuntimeError('Archivio non valido')
        z.extractall(dest)
    exe = next(dest.rglob('NEXAR.exe'), None)
    if not exe or not (exe.parent / '_internal').is_dir(): raise RuntimeError('Archivio senza NEXAR.exe')
    return exe.parent

CREATE_BREAKAWAY_FROM_JOB = 0x01000000

def spawn_detached(args):
    """Il sostituto deve sopravvivere alla chiusura di NEXAR. Se l'app gira dentro un job di Windows
    (avvio da terminale o da un'altra app), un figlio normale verrebbe chiuso insieme a lei: si esce dal job.
    Se il job non lo consente si ripiega su un processo staccato."""
    base = getattr(subprocess, 'CREATE_NO_WINDOW', 0) | getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)
    io = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
    try: return subprocess.Popen(args, creationflags=base | CREATE_BREAKAWAY_FROM_JOB, **io)
    except OSError: return subprocess.Popen(args, creationflags=base | getattr(subprocess, 'DETACHED_PROCESS', 0), **io)

# Script batch leggibile (niente PowerShell nascosto: gli antivirus lo considerano un segnale di malware).
SWAP = r'''@echo off
rem NEXAR {version}: attende la chiusura dell'app, sostituisce il programma e la riavvia.
rem Pause con ping: "timeout" si rifiuta di partire senza console (stdin rediretto) e non aspetterebbe.
rem Le redirezioni >> stanno davanti: "...=8>>file" verrebbe letto come handle 8 e la riga andrebbe persa.
>>"{log}" echo %date% %time% aggiornamento {version}
set /a n=0
:wait
tasklist /FI "PID eq {pid}" 2>nul | find "{pid}" >nul || goto copy
set /a n+=1
if %n% geq 90 goto copy
ping -n 2 127.0.0.1 >nul
goto wait
:copy
rem Altre copie di NEXAR rimaste aperte (una seconda finestra, o l'app bloccata in chiusura)
rem terrebbero bloccati i file e l'aggiornamento resterebbe a metà: si chiudono.
taskkill /F /IM {exe} >nul 2>&1
ping -n 3 127.0.0.1 >nul
rem Solo il programma: _internal viene rispecchiata, l'exe sostituito. Nient'altro nella cartella viene cancellato.
robocopy "{src}\_internal" "{dst}\_internal" /MIR /R:5 /W:2 /NFL /NDL /NJH /NJS >nul
set rc=%errorlevel%
set ok=no
set /a c=0
:exe
copy /y "{src}\{exe}" "{dst}\{exe}" >nul 2>&1
if not errorlevel 1 set ok=si& goto done
set /a c+=1
if %c% geq 15 goto done
ping -n 3 127.0.0.1 >nul
goto exe
:done
>>"{log}" echo %date% %time% robocopy=%rc% exe=%ok% attesa=%n%s
start "" /d "{dst}" "{dst}\{exe}"
'''

class Updater:
    def __init__(self, controller, install_dir: Path, data_dir: Path, frozen: bool):
        self.ctrl, self.install_dir, self.data_dir, self.frozen = controller, Path(install_dir), Path(data_dir), frozen
        self.lock = threading.Lock()
        self.info_state = {'current': VERSION, 'latest': None, 'available': False, 'status': 'idle', 'message': '',
                           'checked_at': None, 'notes': '', 'page': f'https://github.com/{REPO}/releases',
                           'progress': None}
        self.release = None
        self.told = None       # versione già segnalata su Telegram (una volta sola)
        self.exit_hooks = []   # la finestra desktop si registra qui per chiudersi bene prima della sostituzione

    def announce(self):
        """Dopo un aggiornamento riuscito avvisa su Telegram (da chiamare quando il bot è pronto)."""
        last = self.ctrl.state.get('last_version')
        if last == VERSION: return
        if last:
            with self.lock: self.info_state['updated'] = {'from': last, 'at': time.time()}
            self.ctrl.notify(f'✅ NEXAR aggiornato alla versione {VERSION}.')
            self.ctrl.log_event(f'Aggiornato da {last} a {VERSION}')
        from core import json_save, STATE_FILE
        with self.ctrl.lock:
            self.ctrl.state['last_version'] = VERSION
            json_save(STATE_FILE, self.ctrl.state)

    def info(self):
        with self.lock: return dict(self.info_state, supported=self.frozen)

    def set_status(self, status, message='', progress=None):
        with self.lock: self.info_state.update(status=status, message=message, progress=progress)

    def _progress(self, done, total):
        with self.lock: self.info_state['progress'] = {'done': done, 'total': total}

    def check(self):
        data = json.loads(fetch(API))
        tag, latest = data.get('tag_name'), parse(data.get('tag_name'))
        assets = {a.get('name'): a.get('browser_download_url', '') for a in data.get('assets', [])}
        zip_name = next((n for n in assets if ASSET.match(n or '')), None)
        available = bool(latest and latest > parse(VERSION) and zip_name and zip_name + '.sha256' in assets)
        with self.lock:
            self.release = {'tag': tag, 'zip': assets.get(zip_name), 'sha': assets.get(f'{zip_name}.sha256'), 'name': zip_name} if available else None
            self.info_state.update(latest=(tag or '').lstrip('v') or None, available=available, checked_at=time.strftime('%Y-%m-%dT%H:%M:%S'),
                                   notes=str(data.get('body') or '')[:1500], status='idle',
                                   message=f'Disponibile la versione {tag.lstrip("v")}' if available else 'NEXAR è aggiornato')
        return self.info()

    def install(self):
        """Scarica, verifica e avvia la sostituzione: l'app si chiude e riparte da sola con la nuova versione."""
        if not self.frozen: raise RuntimeError('Gli aggiornamenti si installano solo dall\'app compilata')
        with self.lock: rel = self.release
        if not rel: raise RuntimeError('Nessun aggiornamento disponibile')
        try: return self._install(rel)
        except Exception as ex:
            self.set_status('error', 'Aggiornamento non riuscito: ' + str(ex)[:150])
            raise

    def _install(self, rel):
        work = self.data_dir / 'updates'; work.mkdir(parents=True, exist_ok=True)
        zip_path = work / rel['name']
        self.set_status('downloading', 'Download in corso…', {'done': 0, 'total': 0})
        expected = fetch(rel['sha'], 4096).decode('ascii', 'replace').split()[0].lower()
        if download(rel['zip'], zip_path, self._progress) != expected: raise RuntimeError('File scaricato danneggiato (hash diverso)')
        self.set_status('installing', 'Installazione…')
        src = safe_extract(zip_path, work / 'staging')
        script = work / 'swap.cmd'
        # cmd legge i .bat nella codepage OEM della console.
        script.write_text(SWAP.format(pid=os.getpid(), src=src, dst=self.install_dir, log=self.data_dir / 'update.log', exe='NEXAR.exe',
                                      version=rel['tag']), encoding='oem' if os.name == 'nt' else 'ascii', errors='replace')
        spawn_detached(['cmd.exe', '/d', '/c', str(script)])
        self.ctrl.log_event(f'⬆️ Installazione NEXAR {rel["tag"]}: riavvio')
        self.ctrl.notify(f'⬆️ Installo NEXAR {rel["tag"].lstrip("v")}: torno online tra poco.')
        self.set_status('restarting', 'Riavvio di NEXAR…')
        threading.Thread(target=self.exit_soon, daemon=True, name='update-exit').start()
        return f'Aggiornamento a {rel["tag"].lstrip("v")}: NEXAR si riavvia da solo'

    def exit_soon(self):
        time.sleep(3)  # lascia partire la risposta HTTP e l'avviso Telegram
        for hook in self.exit_hooks:
            # Ognuno con un limite: una finestra che non si chiude non deve bloccare l'aggiornamento.
            t = threading.Thread(target=self._run_hook, args=(hook,), daemon=True, name='update-exit-hook')
            t.start(); t.join(5)
        time.sleep(2)
        os._exit(0)

    @staticmethod
    def _run_hook(hook):
        try: hook()
        except Exception: logging.exception('Chiusura per aggiornamento')

    def loop(self, stop: threading.Event):
        # Solo controllo e avviso: l'installazione parte quando l'utente preme Aggiorna nella dashboard.
        if stop.wait(20) or not self.frozen: return
        while True:
            try:
                info = self.check()
                if info['available'] and self.told != info['latest']:
                    self.told = info['latest']
                    self.ctrl.notify(f'⬆️ È disponibile NEXAR {info["latest"]}: apri NEXAR e premi Aggiorna quando vuoi.')
            except Exception as ex:
                logging.warning('Controllo aggiornamenti: %s', ex)
                self.set_status('error', 'Controllo non riuscito: ' + str(ex)[:150])
            if stop.wait(CHECK_EVERY): return
