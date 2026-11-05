"""App del PC da aprire a distanza (dalla dashboard o da Telegram): Claude, Codex e quelle che aggiungi tu.

L'elenco viene dal menu Start di Windows (Get-StartApps: programmi classici e app dello Store).
Si apre solo ciò che sta nell'elenco scelto dall'utente: da remoto non arriva mai un percorso arbitrario.
"""
import hashlib
import json
import logging
import os
import re
import subprocess
import threading
import time
from pathlib import Path

import psutil

MAX_PINNED = 24
CACHE_SECONDS = 600
SKIP = re.compile(r'uninstall|disinstalla|readme|leggimi|help|guida|manual|documentation|license|licenza|release notes|'
                  r'website|sito web|support|feedback|\(safe mode\)|debug|reset', re.I)
DEFAULT_PICKS = (re.compile(r'^claude$', re.I), re.compile(r'^codex$|openai\.codex', re.I))
# Nomi più chiari per app note (l'app di Codex nel menu Start si chiama "ChatGPT").
RENAME = ((re.compile(r'^OpenAI\.Codex_', re.I), 'Codex'),)
# Cartelle note di Windows dentro gli AppID dei programmi classici.
KNOWN = {'{6D809377-6AF0-444B-8957-A3773F02200E}': os.environ.get('ProgramW6432') or os.environ.get('ProgramFiles', r'C:\Program Files'),
         '{7C5A40EF-A0FB-4BFC-874A-C0F2E0B9FA8E}': os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)'),
         '{F38BF404-1D43-42F2-9305-67DE0B28FC23}': os.environ.get('WINDIR', r'C:\Windows'),
         '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}': str(Path(os.environ.get('WINDIR', r'C:\Windows')) / 'System32'),
         '{F1B32785-6FBA-4FCF-9D55-7B8E7F157091}': os.environ.get('LOCALAPPDATA', ''),
         '{3EB685DB-65F9-4CF6-A03A-E3EF65729F3D}': os.environ.get('APPDATA', '')}
_cache = {'at': 0.0, 'apps': []}
_lock = threading.Lock()
VALID_ID = re.compile(r'^[^"\r\n<>|]{1,300}$')


def app_key(app_id: str) -> str:
    return hashlib.sha1(app_id.encode('utf-8')).hexdigest()[:16]


def exe_for(app_id: str) -> str:
    """Per i programmi classici l'AppID è un percorso (anche con la cartella nota di Windows davanti)."""
    s = app_id
    for guid, folder in KNOWN.items():
        if s.upper().startswith(guid) and folder:
            s = folder + s[len(guid):]
            break
    return s if re.match(r'^[A-Za-z]:\\', s) and s.lower().endswith('.exe') and Path(s).is_file() else ''


def start_apps(force=False, runner=None):
    """Tutte le app del menu Start (nome + AppID), senza disinstallazioni e guide. In cache 10 minuti."""
    with _lock:
        if not force and _cache['apps'] and time.monotonic() - _cache['at'] < CACHE_SECONDS: return list(_cache['apps'])
    if runner is None:
        if os.name != 'nt': return []
        flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        r = subprocess.run(['powershell', '-NoProfile', '-Command',
                            '[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-StartApps | Select-Object Name,AppID | ConvertTo-Json -Compress'],
                           capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=40, creationflags=flags)
        out = r.stdout
    else: out = runner()
    try: raw = json.loads(out or '[]')
    except ValueError: raw = []
    raw = raw if isinstance(raw, list) else [raw]
    seen, apps = set(), []
    for a in raw:
        name, aid = str(a.get('Name') or '').strip(), str(a.get('AppID') or '').strip()
        if not name or not aid or SKIP.search(name) or not VALID_ID.match(aid) or aid.lower().startswith(('http:', 'https:')): continue
        if aid.lower().endswith(('.txt', '.pdf', '.html', '.htm', '.chm', '.url', '.rtf')): continue
        if aid in seen: continue
        seen.add(aid)
        name = next((n for rx, n in RENAME if rx.search(aid)), name)
        apps.append({'id': aid, 'name': name, 'key': app_key(aid), 'exe': exe_for(aid)})
    apps.sort(key=lambda a: a['name'].lower())
    with _lock: _cache.update(at=time.monotonic(), apps=apps)
    return list(apps)


def find(app_id: str, apps=None):
    return next((a for a in (apps if apps is not None else start_apps()) if a['id'] == app_id), None)


def running_names() -> set:
    out = set()
    for p in psutil.process_iter(['name']):
        try: out.add((p.info['name'] or '').lower())
        except psutil.Error: continue
    return out


def is_running(app: dict, names=None) -> bool:
    exe = app.get('exe') or ''
    if exe: return Path(exe).name.lower() in (names if names is not None else running_names())
    # App dello Store: si riconosce dal nome del pacchetto nei processi (es. Claude → claude.exe).
    base = re.sub(r'[^a-z0-9]', '', app.get('name', '').lower())
    return bool(base) and any(re.sub(r'[^a-z0-9]', '', n[:-4]) == base for n in (names if names is not None else running_names()) if n.endswith('.exe'))


def launch(app_id: str, popen=subprocess.Popen):
    """Apre l'app come dal menu Start: shell:AppsFolder vale per i programmi classici e per quelli dello Store."""
    if not VALID_ID.match(app_id or ''): raise ValueError('App non valida')
    popen(['explorer.exe', 'shell:AppsFolder\\' + app_id], close_fds=True)


def close(app: dict) -> bool:
    exe = app.get('exe') or ''
    name = Path(exe).name if exe else ''
    if not name: raise ValueError('Questa app si chiude dal PC')
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    subprocess.run(['taskkill', '/im', name], capture_output=True, creationflags=flags)
    return True


def defaults(apps) -> list:
    """Primo avvio: Claude e Codex se ci sono."""
    out = []
    for rx in DEFAULT_PICKS:
        hit = next((a for a in apps if rx.search(a['name']) or rx.search(a['id'])), None)
        if hit: out.append({'id': hit['id'], 'name': hit['name']})
    return out


def store_logo(app_id: str):
    """Logo di un'app dello Store: dal suo pacchetto (AppxManifest), la versione più grande disponibile."""
    if '!' not in app_id or os.name != 'nt': return None
    fam = app_id.split('!')[0]
    if not re.fullmatch(r'[A-Za-z0-9._-]{3,120}', fam): return None
    ps = (f"$p=Get-AppxPackage | Where-Object PackageFamilyName -eq '{fam}' | Select-Object -First 1; if($p){{ $p.InstallLocation;"
          "$m=[xml](Get-Content -LiteralPath (Join-Path $p.InstallLocation 'AppxManifest.xml'));"
          "foreach($a in $m.Package.Applications.Application){ $v=$a.VisualElements; $v.Square44x44Logo; $v.Square150x150Logo; $m.Package.Properties.Logo } }")
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    r = subprocess.run(['powershell', '-NoProfile', '-Command', ps], capture_output=True, text=True, errors='replace', timeout=30, creationflags=flags)
    lines = [l.strip() for l in r.stdout.splitlines() if l.strip()]
    if len(lines) < 2: return None
    root, best = Path(lines[0]), None
    for rel in lines[1:]:
        base = root / rel
        try: cands = list(base.parent.glob(base.stem + '*' + base.suffix)) + ([base] if base.is_file() else [])
        except OSError: continue
        for c in cands:
            low = c.name.lower()
            if 'contrast' in low: continue
            size = c.stat().st_size
            if best is None or size > best[0]: best = (size, c)
    return best[1] if best else None


def icon_png(app: dict, dest: Path) -> bool:
    exe = app.get('exe') or ''
    try:
        if exe:
            import gaming_boost
            return bool(gaming_boost.exe_icon(exe, dest))
        logo = store_logo(app.get('id', ''))
        if not logo: return False
        from PIL import Image
        img = Image.open(logo).convert('RGBA')
        img = img.crop(img.getbbox() or (0, 0, *img.size))
        dest.parent.mkdir(parents=True, exist_ok=True)
        img.save(dest)
        return True
    except Exception:
        logging.exception('Icona app')
        return False
