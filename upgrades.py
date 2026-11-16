"""Programmi da aggiornare e riparazione di Windows.

- Aggiornamenti: winget dice quali programmi installati hanno una versione nuova; si aggiornano uno alla volta,
  solo quando l'utente preme il pulsante di quel programma, e solo se era nell'ultimo elenco (mai id inventati).
- Riparazione: DISM (ripara l'archivio dei componenti) e poi SFC (ripara i file di sistema), con una conferma UAC.
  Il risultato si legge dai file che lo script scrive nella cartella dati di NEXAR.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

ID_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._+-]{1,120}$')
NO_UPGRADE = (-1978335189, 0x8A15002B)      # nessun aggiornamento applicabile: è già a posto
FLAGS = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


def winget_exe() -> str | None:
    exe = shutil.which('winget')
    if exe: return exe
    p = Path(os.environ.get('LOCALAPPDATA', '')) / 'Microsoft' / 'WindowsApps' / 'winget.exe'
    return str(p) if p.is_file() else None


def _lines(text: str) -> list[str]:
    """Righe pulite: winget disegna la rotellina e le barre con \\r, conta solo quello dopo l'ultimo \\r."""
    return [line.split('\r')[-1].rstrip() for line in text.replace('\r\n', '\n').split('\n')]


def parse_table(text: str) -> list[dict]:
    """La tabella di `winget upgrade` in qualsiasi lingua: le colonne si ricavano dall'intestazione sopra la riga di trattini."""
    lines = _lines(text)
    for i in range(len(lines) - 1):
        dash = lines[i + 1].strip()
        if len(dash) >= 20 and set(dash) == {'-'}: break
    else: return []
    starts = [m.start() for m in re.finditer(r'\S+', lines[i])]
    if len(starts) < 4: return []
    out = []
    for line in lines[i + 2:]:
        if len(line) <= starts[3] or not line.strip(): break           # fine tabella (riga del totale o riga vuota)
        cut = lambda a, b=None: line[starts[a]:starts[b] if b is not None and b < len(starts) else None].strip()
        name, pid, cur, new = cut(0, 1), cut(1, 2), cut(2, 3), cut(3, 4)
        if not ID_RE.match(pid) or not new: break
        out.append({'name': name.rstrip('…').strip() or pid, 'id': pid, 'version': cur, 'available': new})
    return out


def list_upgrades(run=subprocess.run) -> list[dict]:
    exe = winget_exe()
    if not exe: raise RuntimeError('winget non c\'è: installa "Programma di installazione app" dal Microsoft Store')
    r = run([exe, 'upgrade', '--source', 'winget', '--accept-source-agreements', '--disable-interactivity'],
            capture_output=True, timeout=180, creationflags=FLAGS)
    text = (r.stdout or b'').decode('utf-8', 'replace') if isinstance(r.stdout, bytes) else (r.stdout or '')
    items = [x for x in parse_table(text) if 'nexar' not in x['id'].lower()]
    if not items and r.returncode not in (0, *NO_UPGRADE) and 'winget' in text.lower() and '---' not in text:
        raise RuntimeError('winget non ha risposto (' + str(r.returncode) + ')')
    return items


def upgrade(pkg_id: str, known: list[dict], run=subprocess.run) -> str:
    item = next((x for x in known or [] if x['id'] == pkg_id), None)
    if not item or not ID_RE.match(pkg_id): raise ValueError('Programma non nell\'elenco: aggiorna l\'elenco e riprova')
    exe = winget_exe()
    if not exe: raise RuntimeError('winget non disponibile')
    r = run([exe, 'upgrade', '--id', pkg_id, '--exact', '--source', 'winget', '--silent', '--accept-source-agreements',
             '--accept-package-agreements', '--disable-interactivity'], capture_output=True, timeout=1800, creationflags=FLAGS)
    if r.returncode in (0, *NO_UPGRADE): return f"{item['name']} aggiornato alla {item['available']}"
    text = (r.stdout or b'').decode('utf-8', 'replace') if isinstance(r.stdout, bytes) else (r.stdout or '')
    last = next((ln.strip() for ln in reversed(_lines(text)) if ln.strip() and not set(ln.strip()) <= set('-\\|/ █▒')), '')
    raise RuntimeError(f"{item['name']}: aggiornamento non riuscito" + (f' ({last[:140]})' if last else f' (codice {r.returncode})')
                       + '. Se è aperto, chiudilo e riprova.')


# ---------- riparazione di Windows ----------
def _q(s): return "'" + str(s).replace("'", "''") + "'"


def repair_script(folder: Path) -> str:
    """DISM poi SFC, nascosti; l'avanzamento va nei file di testo e alla fine result.json con i codici di uscita."""
    f = _q(folder)
    return (f"$o={f};New-Item -ItemType Directory -Force -Path $o | Out-Null;"
            "Remove-Item -LiteralPath (Join-Path $o 'result.json') -Force -ErrorAction SilentlyContinue;"
            "Set-Content -LiteralPath (Join-Path $o 'phase.txt') -Value 'dism';"
            "$d=Start-Process dism.exe -ArgumentList '/Online','/Cleanup-Image','/RestoreHealth','/English' -Wait -PassThru -WindowStyle Hidden "
            "-RedirectStandardOutput (Join-Path $o 'dism.txt');"
            "Set-Content -LiteralPath (Join-Path $o 'phase.txt') -Value 'sfc';"
            "$s=Start-Process sfc.exe -ArgumentList '/scannow' -Wait -PassThru -WindowStyle Hidden "
            "-RedirectStandardOutput (Join-Path $o 'sfc.txt');"
            "@{dism=$d.ExitCode;sfc=$s.ExitCode;at=[DateTimeOffset]::UtcNow.ToUnixTimeSeconds()} | ConvertTo-Json -Compress | "
            "Set-Content -LiteralPath (Join-Path $o 'result.json') -Encoding UTF8;"
            "Set-Content -LiteralPath (Join-Path $o 'phase.txt') -Value 'done'")


def _read(p: Path) -> str:
    try: raw = p.read_bytes()
    except OSError: return ''
    if raw[:2] in (b'\xff\xfe', b'\xfe\xff') or raw[1:2] == b'\x00':   # SFC scrive in UTF-16 quando l'uscita va su file
        return raw.decode('utf-16', 'replace')
    return raw.decode('utf-8', 'replace')


def _percent(text: str):
    found = re.findall(r'(\d{1,3}(?:[.,]\d)?)\s*%', text)
    return min(100.0, float(found[-1].replace(',', '.'))) if found else None


def _last_line(text: str) -> str:
    lines = [ln.strip() for ln in _lines(text) if ln.strip() and not re.fullmatch(r'[\[\]=\s\d.,%-]*', ln.strip())]
    return lines[-1][:220] if lines else ''


def repair_progress(folder: Path) -> dict:
    phase = _read(folder / 'phase.txt').strip() or 'start'
    file = folder / ('dism.txt' if phase == 'dism' else 'sfc.txt')
    return {'phase': phase, 'percent': _percent(_read(file)) if phase in ('dism', 'sfc') else None}


def repair_result(folder: Path) -> dict | None:
    try: res = json.loads(_read(folder / 'result.json').lstrip('﻿'))
    except ValueError: return None
    sfc = _last_line(_read(folder / 'sfc.txt'))
    dism_ok = res.get('dism') == 0
    # SFC: 0 = nessun problema o riparato; altri codici = qualcosa non si è riparato o il controllo non è partito
    sfc_ok = res.get('sfc') == 0
    return {'at': int(res.get('at') or time.time()), 'ok': dism_ok and sfc_ok, 'dism': res.get('dism'), 'sfc': res.get('sfc'),
            'dism_text': _last_line(_read(folder / 'dism.txt')), 'sfc_text': sfc}


# ---------- memoria in standby ----------
STANDBY_CS = r'''using System; using System.Runtime.InteropServices;
public static class NexarMem {
  [StructLayout(LayoutKind.Sequential, Pack = 4)] struct TP { public int Count; public long Luid; public int Attr; }
  [DllImport("advapi32.dll", SetLastError = true)] static extern bool OpenProcessToken(IntPtr h, int a, out IntPtr t);
  [DllImport("advapi32.dll", SetLastError = true)] static extern bool LookupPrivilegeValue(string s, string n, out long l);
  [DllImport("advapi32.dll", SetLastError = true)] static extern bool AdjustTokenPrivileges(IntPtr t, bool d, ref TP n, int l, IntPtr p, IntPtr r);
  [DllImport("kernel32.dll")] static extern IntPtr GetCurrentProcess();
  [DllImport("ntdll.dll")] static extern int NtSetSystemInformation(int c, ref int i, int l);
  public static int Purge() {
    IntPtr t; OpenProcessToken(GetCurrentProcess(), 0x28, out t);
    TP tp = new TP(); tp.Count = 1; tp.Attr = 2; LookupPrivilegeValue(null, "SeProfileSingleProcessPrivilege", out tp.Luid);
    AdjustTokenPrivileges(t, false, ref tp, 0, IntPtr.Zero, IntPtr.Zero);
    int cmd = 4; return NtSetSystemInformation(80, ref cmd, 4);
  }
}'''


def standby_script(out_file: Path) -> str:
    """Svuota la lista in standby (la cache di file usati di recente che Windows tiene in RAM). Serve l'amministratore."""
    return ("$code=@'\n" + STANDBY_CS + "\n'@\nAdd-Type -TypeDefinition $code\n"
            f"Set-Content -LiteralPath {_q(out_file)} -Value ([NexarMem]::Purge())\n")
