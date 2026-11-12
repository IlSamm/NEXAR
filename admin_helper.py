"""Operazioni da amministratore anche da lontano.

La finestra UAC compare sullo schermo protetto del PC: da remoto non si vede e non si può confermare.
Con UNA conferma fatta sul PC si crea un'attività "NEXAR Admin" con privilegi massimi. NEXAR le chiede solo azioni
di questo elenco chiuso: i comandi stanno in runner.ps1, in una cartella che può modificare solo un amministratore,
e la richiesta (un file dell'utente) porta soltanto nome dell'azione e parametri controllati. Non esegue mai testo
ricevuto dall'esterno: un programma qualsiasi non può usarla per ottenere i privilegi di amministratore.
"""
from __future__ import annotations
import json
import os
import secrets
import subprocess
import threading
import time
from pathlib import Path

TASK = 'NEXAR Admin'
LONG_ACTIONS = {'install': 900, 'fans': 180}
TIMEOUT = 120


def root() -> Path:
    # Direttamente sotto ProgramData: la cartella nasce da amministratore e un utente normale non può spostarla.
    return Path(os.environ.get('ProgramData') or r'C:\ProgramData') / 'NEXAR-Admin'


def q(value) -> str:
    return "'" + str(value).replace("'", "''") + "'"


RUNNER = r'''# NEXAR Admin: solo le azioni di questo elenco. La richiesta contiene dati, mai comandi.
$ErrorActionPreference = 'Stop'
$req = @@REQ@@
$res = @@RES@@
$exe = @@EXE@@
$clean = @{ @@CLEAN@@ }
$pkg = @{ @@PKG@@ }
$r = $null
function Reply($ok, $msg) {
  $id = ''
  if ($r) { $id = [string]$r.id }
  @{ id = $id; ok = [bool]$ok; message = [string]$msg } | ConvertTo-Json -Compress | Set-Content -LiteralPath $res -Encoding UTF8
}
try {
  if (-not (Test-Path -LiteralPath $req -PathType Leaf)) { exit 0 }
  $r = Get-Content -LiteralPath $req -Raw -Encoding UTF8 | ConvertFrom-Json
  Remove-Item -LiteralPath $req -Force
  $a = $r.args
  switch -CaseSensitive ([string]$r.action) {
    'ping' { }
    'clean' {
      foreach ($k in @($a.keys)) {
        $p = $clean[[string]$k]
        if (-not $p) { throw 'Voce di pulizia non prevista' }
        $wu = $p -like '*SoftwareDistribution*'
        if ($wu) { Stop-Service wuauserv,bits -Force -ErrorAction SilentlyContinue }
        Get-ChildItem -LiteralPath $p -Force -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
        if ($wu) { Start-Service bits,wuauserv -ErrorAction SilentlyContinue }
      }
    }
    'trim' { @@TRIM@@ }
    'startup' {
      $sub = [string]$a.sub
      if (@('Run', 'Run32', 'StartupFolder') -cnotcontains $sub) { throw 'Voce non prevista' }
      $name = [string]$a.name
      if (-not $name) { throw 'Voce non prevista' }
      $first = 3
      if ($a.enabled -eq $true) { $first = 2 }
      [byte[]]$value = @($first) + (@(0) * 11)
      $path = @@APPROVED@@ + '\' + $sub
      if (-not (Test-Path -LiteralPath $path)) { New-Item -Path $path -Force | Out-Null }
      Set-ItemProperty -LiteralPath $path -Name $name -Type Binary -Value $value
    }
    'firewall' {
      $ip = [System.Net.IPAddress]::Parse([string]$a.ip)
      $b = $ip.GetAddressBytes()
      $lan = ($b.Length -eq 4) -and (($b[0] -eq 10) -or (($b[0] -eq 192) -and ($b[1] -eq 168)) -or (($b[0] -eq 172) -and ($b[1] -ge 16) -and ($b[1] -le 31)))
      if (-not $lan) { throw 'Indirizzo non valido' }
      Remove-NetFirewallRule -DisplayName @@RULE@@ -ErrorAction SilentlyContinue
      New-NetFirewallRule -DisplayName @@RULE@@ -Direction Inbound -Action Allow -Protocol TCP -LocalPort @@PORT@@ -RemoteAddress $ip.ToString() -Program $exe -Profile Any | Out-Null
    }
    'wol' {
      $n = [string]$a.name
      $nic = Get-NetAdapter | Where-Object { $_.Name -ceq $n } | Select-Object -First 1
      if (-not $nic) { throw 'Scheda di rete non trovata' }
      Set-NetAdapterAdvancedProperty -Name $nic.Name -RegistryKeyword '*WakeOnMagicPacket' -RegistryValue 1 -ErrorAction SilentlyContinue
      Set-NetAdapterAdvancedProperty -Name $nic.Name -RegistryKeyword 'S5WakeOnLan' -RegistryValue 1 -ErrorAction SilentlyContinue
      Set-NetAdapterPowerManagement -Name $nic.Name -WakeOnMagicPacket Enabled -ErrorAction SilentlyContinue
      # Risparmio energetico Ethernet: a PC spento il collegamento dorme e il pacchetto magico non arriva.
      foreach ($k in '*EEE', 'EnableGreenEthernet', 'AdvancedEEE') { Set-NetAdapterAdvancedProperty -Name $nic.Name -RegistryKeyword $k -RegistryValue 0 -ErrorAction SilentlyContinue }
      $d = Get-PnpDevice -FriendlyName $nic.InterfaceDescription
      & powercfg.exe /deviceenablewake $d.FriendlyName
    }
    'install' {
      $id = $pkg[[string]$a.key]
      if (-not $id) { throw 'Programma non previsto' }
      & winget install --id $id --exact --source winget --silent --accept-source-agreements --accept-package-agreements --disable-interactivity | Out-Null
      if (@(0, -1978335189) -notcontains $LASTEXITCODE) { throw ('winget ha risposto ' + $LASTEXITCODE) }
    }
    'autostart' { @@AUTOSTART@@ }
    'autostart_off' { Unregister-ScheduledTask -TaskName @@AUTOTASK@@ -Confirm:$false -ErrorAction SilentlyContinue }
    'fans' {
      @@FANS@@
    }
    default { throw 'Azione non prevista' }
  }
  Reply $true 'ok'
} catch {
  Reply $false $_.Exception.Message
}
'''


def runner_text(request: Path, result: Path, exe: str, clean: dict, packages: dict, fans_script: str = '', trim: str = '',
                autostart: str = '', approved: str = '', rule: str = '', port: int = 0, autostart_task: str = '') -> str:
    table = lambda d: '; '.join(f'{q(k)} = {q(v)}' for k, v in d.items())
    fans = fans_script or "throw 'Fan Control non era presente: riattiva Amministratore da remoto sul PC'"
    values = {'@@REQ@@': q(request), '@@RES@@': q(result), '@@EXE@@': q(exe), '@@CLEAN@@': table(clean), '@@PKG@@': table(packages),
              '@@TRIM@@': trim, '@@APPROVED@@': q('HKLM:\\' + approved), '@@RULE@@': q(rule), '@@PORT@@': str(port),
              '@@AUTOSTART@@': autostart, '@@AUTOTASK@@': q(autostart_task), '@@FANS@@': fans}
    text = RUNNER
    for key, value in values.items(): text = text.replace(key, value)
    return text


def setup_script(folder: Path, runner: str, user: str) -> str:
    """Una sola conferma UAC: cartella protetta, runner e attività avviabile senza altre richieste."""
    file = folder / 'runner.ps1'
    args = f'--headless powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{file}"'
    return (f"$d={q(folder)};if(Test-Path -LiteralPath $d){{Remove-Item -LiteralPath $d -Recurse -Force}};"
            "New-Item -ItemType Directory -Path $d | Out-Null;"
            "& icacls.exe $d /inheritance:r /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' '*S-1-5-32-545:(OI)(CI)RX' | Out-Null;\n"
            f"$runner=@'\n{runner}\n'@\n"
            f"Set-Content -LiteralPath {q(file)} -Value $runner -Encoding UTF8;\n"
            f"$a=New-ScheduledTaskAction -Execute 'conhost.exe' -Argument {q(args)} -WorkingDirectory $d;"
            f"$p=New-ScheduledTaskPrincipal -UserId {q(user)} -RunLevel Highest -LogonType Interactive;"
            "$s=New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances Queue -ExecutionTimeLimit (New-TimeSpan -Hours 1);"
            f"Register-ScheduledTask -TaskName {q(TASK)} -Action $a -Principal $p -Settings $s -Force | Out-Null;")


def remove_script(folder: Path) -> str:
    return (f"Unregister-ScheduledTask -TaskName {q(TASK)} -Confirm:$false -ErrorAction SilentlyContinue;"
            f"Remove-Item -LiteralPath {q(folder)} -Recurse -Force -ErrorAction SilentlyContinue;")


def _no_window() -> dict:
    return {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}


class AdminHelper:
    def __init__(self, data_dir: Path, folder: Path | None = None, run_task=None, task_exists=None, sleep=time.sleep, clock=time.monotonic):
        self.request = Path(data_dir) / 'admin-request.json'
        self.folder = Path(folder) if folder else root()
        self.result = self.folder / 'result.json'
        self.run_task, self._task_exists, self.sleep, self.clock = run_task or self._start_task, task_exists, sleep, clock
        self.lock = threading.Lock()

    @staticmethod
    def _start_task() -> bool:
        return subprocess.run(['schtasks', '/run', '/tn', TASK], capture_output=True, **_no_window()).returncode == 0

    def active(self) -> bool:
        exists = self._task_exists
        if exists is None:
            import discovery
            exists = discovery.task_exists
        return (self.folder / 'runner.ps1').is_file() and bool(exists(TASK))

    def info(self) -> dict:
        return {'active': self.active()}

    def _read_result(self):
        try: return json.loads(self.result.read_text(encoding='utf-8-sig'))
        except (OSError, ValueError): return None

    def call(self, action: str, timeout: float | None = None, **args) -> bool:
        if not self.active(): raise RuntimeError('Attiva prima "Amministratore da remoto" dall\'app sul PC (Impostazioni → Sistema)')
        with self.lock:
            rid = secrets.token_hex(8)
            tmp = self.request.with_suffix('.tmp')
            tmp.write_text(json.dumps({'id': rid, 'action': action, 'args': args}), encoding='utf-8')
            os.replace(tmp, self.request)
            if not self.run_task(): raise RuntimeError('Attività "NEXAR Admin" non avviata')
            end = self.clock() + (timeout or LONG_ACTIONS.get(action, TIMEOUT))
            while self.clock() < end:
                out = self._read_result()
                if out and out.get('id') == rid:
                    if not out.get('ok'): raise RuntimeError(str(out.get('message') or 'Operazione non riuscita')[:200])
                    return True
                self.sleep(0.4)
        raise RuntimeError('L\'operazione da amministratore non ha risposto in tempo')
