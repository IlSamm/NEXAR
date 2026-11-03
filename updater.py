"""Aggiornamenti automatici: l'app controlla le release di GitHub, scarica lo zip, ne verifica l'hash e si sostituisce.

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

def download(url, dest: Path):
    if not url.startswith('https://github.com/'): raise RuntimeError('Indirizzo di download non previsto')
    h = hashlib.sha256(); size = 0
    with urlopen(Request(url, headers={'User-Agent': HEADERS['User-Agent']}), timeout=60) as r, open(dest, 'wb') as f:
        while chunk := r.read(1 << 20):
            size += len(chunk)
            if size > MAX_ZIP: raise RuntimeError('Aggiornamento troppo grande')
            h.update(chunk); f.write(chunk)
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

SWAP = r'''$ErrorActionPreference = 'Continue'
$log = '{log}'
"$(Get-Date -Format s) aggiornamento {version}" | Out-File $log -Append -Encoding utf8
try {{ Wait-Process -Id {pid} -Timeout 90 -ErrorAction SilentlyContinue }} catch {{}}
Start-Sleep -Seconds 2
# Solo il programma: _internal viene rispecchiata, l'exe sostituito. Nient'altro nella cartella viene cancellato.
robocopy '{src}\_internal' '{dst}\_internal' /MIR /R:5 /W:2 /NFL /NDL /NJH /NJS | Out-Null
$rc = $LASTEXITCODE
Copy-Item -LiteralPath '{src}\NEXAR.exe' -Destination '{dst}\NEXAR.exe' -Force
"$(Get-Date -Format s) robocopy=$rc" | Out-File $log -Append -Encoding utf8
Start-Process -FilePath '{dst}\NEXAR.exe' -WorkingDirectory '{dst}'
'''

class Updater:
    def __init__(self, controller, install_dir: Path, data_dir: Path, frozen: bool):
        self.ctrl, self.install_dir, self.data_dir, self.frozen = controller, Path(install_dir), Path(data_dir), frozen
        self.lock = threading.Lock()
        self.info_state = {'current': VERSION, 'latest': None, 'available': False, 'status': 'idle', 'message': '',
                           'checked_at': None, 'notes': '', 'page': f'https://github.com/{REPO}/releases'}
        self.release = None
        self.exit_hooks = []   # la finestra desktop si registra qui per chiudersi bene prima della sostituzione

    def announce(self):
        """Dopo un aggiornamento riuscito avvisa su Telegram (da chiamare quando il bot è pronto)."""
        last = self.ctrl.state.get('last_version')
        if last == VERSION: return
        if last:
            self.ctrl.notify(f'✅ NEXAR aggiornato alla versione {VERSION}.')
            self.ctrl.log_event(f'Aggiornato da {last} a {VERSION}')
        from core import json_save, STATE_FILE
        with self.ctrl.lock:
            self.ctrl.state['last_version'] = VERSION
            json_save(STATE_FILE, self.ctrl.state)

    def auto(self):
        return bool(self.ctrl.config.get('updates', {}).get('auto', True))

    def info(self):
        with self.lock: return dict(self.info_state, auto=self.auto(), supported=self.frozen)

    def set_status(self, status, message=''):
        with self.lock: self.info_state.update(status=status, message=message)

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
        work = self.data_dir / 'updates'; work.mkdir(parents=True, exist_ok=True)
        zip_path = work / rel['name']
        self.set_status('downloading', 'Download in corso…')
        expected = fetch(rel['sha'], 4096).decode('ascii', 'replace').split()[0].lower()
        if download(rel['zip'], zip_path) != expected: raise RuntimeError('File scaricato danneggiato (hash diverso)')
        self.set_status('installing', 'Installazione…')
        src = safe_extract(zip_path, work / 'staging')
        script = work / 'swap.ps1'
        script.write_text(SWAP.format(pid=os.getpid(), src=src, dst=self.install_dir, log=self.data_dir / 'update.log',
                                      version=rel['tag']), encoding='utf-8-sig')
        spawn_detached(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-WindowStyle', 'Hidden', '-File', str(script)])
        self.ctrl.log_event(f'⬆️ Installazione NEXAR {rel["tag"]}: riavvio')
        self.ctrl.notify(f'⬆️ Installo NEXAR {rel["tag"].lstrip("v")}: torno online tra poco.')
        threading.Thread(target=self.exit_soon, daemon=True, name='update-exit').start()
        return f'Aggiornamento a {rel["tag"].lstrip("v")}: NEXAR si riavvia da solo'

    def exit_soon(self):
        time.sleep(3)  # lascia partire la risposta HTTP e l'avviso Telegram
        for hook in self.exit_hooks:
            try: hook()
            except Exception: logging.exception('Chiusura per aggiornamento')
        time.sleep(4)
        os._exit(0)

    def loop(self, stop: threading.Event):
        if stop.wait(90) or not self.frozen: return
        while True:
            try:
                info = self.check()
                if info['available'] and self.auto():
                    self.ctrl.notify(f'⬆️ Nuova versione NEXAR {info["latest"]}: la installo adesso.')
                    self.install()
                    return
            except Exception as ex:
                logging.warning('Controllo aggiornamenti: %s', ex)
                self.set_status('error', 'Controllo non riuscito: ' + str(ex)[:150])
            if stop.wait(CHECK_EVERY): return
