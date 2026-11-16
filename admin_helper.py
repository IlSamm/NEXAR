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
LONG_ACTIONS = {'install': 900, 'fans': 180, 'msi_light': 45}
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
$apps = @{ @@APPS@@ }
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
    'msi_light' {
      # Luci della scheda MSI (dove c'è l'ARCTIC) con il programma ufficiale di MSI, solo spente o un colore fisso
      $style = [string]$a.style
      if (@('Steady') -cnotcontains $style) { throw 'Effetto non previsto' }
      $c = @([int]$a.r, [int]$a.g, [int]$a.b)
      foreach ($v in $c) { if ($v -lt 0 -or $v -gt 255) { throw 'Colore non valido' } }
      $m = Join-Path $PSScriptRoot 'msi'
      if (-not (Test-Path -LiteralPath (Join-Path $m 'MysticLight_SDK_x64.dll') -PathType Leaf)) { throw 'Manca il programma MSI per le luci: premi Sistema adesso' }
      if (-not ('NexarMsi' -as [type])) { Add-Type -TypeDefinition @@MSICS@@ }
      $code = [NexarMsi]::Run($m, $style, [uint32]$c[0], [uint32]$c[1], [uint32]$c[2], 25000)
      if ($code -eq -998) { throw 'Programma MSI per le luci non caricato: premi Sistema adesso' }
      if ($code -eq -999) { throw 'MSI non risponde: in Mystic Light togli la sincronizzazione della scheda madre e premi Applica' }
      if ($code -ne 0) { throw ('Le luci MSI non accettano comandi (codice ' + $code + '): MSI Center si è bloccato, riavvia il PC') }
    }
    'close_apps' {
      foreach ($k in @($a.keys)) {
        if ([string]$k -ceq 'openrgb_extra') {
          if ((Get-Service OpenRGB -ErrorAction SilentlyContinue).Status -eq 'Running') {
            Get-Process -Name OpenRGB -ErrorAction SilentlyContinue | Where-Object { $_.SessionId -ne 0 } | Stop-Process -Force -ErrorAction SilentlyContinue
          }
          continue
        }
        $names = $apps[[string]$k]
        if (-not $names) { throw 'App non prevista' }
        foreach ($n in $names.Split('|')) { Get-Process -Name $n -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue }
      }
    }
    default { throw 'Azione non prevista' }
  }
  Reply $true 'ok'
} catch {
  Reply $false $_.Exception.Message
}
'''


# Chiamate al programma ufficiale di MSI (Mystic Light SDK) in un thread a parte: se MSI non risponde il runner
# non resta appeso (succede con scheda madre e RAM sincronizzate in Mystic Light).
MSI_CS = r"""using System; using System.Runtime.InteropServices; using System.Threading;
public static class NexarMsi {
  [DllImport("kernel32", CharSet = CharSet.Unicode, SetLastError = true)] static extern bool SetDllDirectory(string p);
  [DllImport("MysticLight_SDK_x64.dll")] static extern int MLAPI_Initialize();
  [DllImport("MysticLight_SDK_x64.dll")] static extern int MLAPI_SetLedStyle([MarshalAs(UnmanagedType.BStr)] string type, uint index, [MarshalAs(UnmanagedType.BStr)] string style);
  [DllImport("MysticLight_SDK_x64.dll")] static extern int MLAPI_SetLedColor([MarshalAs(UnmanagedType.BStr)] string type, uint index, uint r, uint g, uint b);
  public static int Run(string dir, string style, uint r, uint g, uint b, int ms) {
    int code = -999;
    Thread t = new Thread(() => {
      try {
        SetDllDirectory(dir);
        int c = MLAPI_Initialize();
        if (c == 0) c = MLAPI_SetLedStyle("MSI_MB", 0, style);
        if (c == 0 && style == "Steady") c = MLAPI_SetLedColor("MSI_MB", 0, r, g, b);
        code = c;
      } catch (Exception) { code = -998; }
    });
    t.IsBackground = true; t.Start();
    return t.Join(ms) ? code : -999;
  }
}"""

MSI_SDK_URL = 'https://download.msi.com/uti_exe/Mystic_light_SDK.zip'


def msi_sdk_script() -> str:
    """Nella conferma da amministratore: scarica il programma ufficiale di MSI per le luci e lo tiene nella cartella
    protetta di NEXAR Admin, solo se è firmato da MSI. Senza rete non blocca il resto."""
    return ("try{[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12;"
            "$m=Join-Path $d 'msi';New-Item -ItemType Directory -Force -Path $m | Out-Null;$z=Join-Path $m 'sdk.zip';$x=Join-Path $m 'x';"
            f"Invoke-WebRequest -Uri {q(MSI_SDK_URL)} -OutFile $z -UseBasicParsing;Expand-Archive -LiteralPath $z -DestinationPath $x -Force;"
            "$f=Get-ChildItem -LiteralPath $x -Recurse -Filter 'MysticLight_SDK_x64.dll' | Select-Object -First 1;"
            "$s=Get-AuthenticodeSignature -LiteralPath $f.FullName;"
            "if($s.Status -eq 'Valid' -and $s.SignerCertificate.Subject -like '*MICRO-STAR INTERNATIONAL*'){Copy-Item -LiteralPath $f.FullName -Destination (Join-Path $m 'MysticLight_SDK_x64.dll') -Force};"
            "Remove-Item -LiteralPath $z,$x -Recurse -Force -ErrorAction SilentlyContinue}catch{};")


def runner_text(request: Path, result: Path, exe: str, clean: dict, packages: dict, fans_script: str = '', trim: str = '',
                autostart: str = '', approved: str = '', rule: str = '', port: int = 0, autostart_task: str = '', apps: dict | None = None) -> str:
    table = lambda d: '; '.join(f'{q(k)} = {q(v)}' for k, v in d.items())
    fans = fans_script or "throw 'Fan Control non era presente: riattiva Amministratore da remoto sul PC'"
    values = {'@@REQ@@': q(request), '@@RES@@': q(result), '@@EXE@@': q(exe), '@@CLEAN@@': table(clean), '@@PKG@@': table(packages),
              '@@TRIM@@': trim, '@@APPROVED@@': q('HKLM:\\' + approved), '@@RULE@@': q(rule), '@@PORT@@': str(port),
              '@@AUTOSTART@@': autostart, '@@AUTOTASK@@': q(autostart_task), '@@FANS@@': fans, '@@APPS@@': table(apps or {}), '@@MSICS@@': q(MSI_CS)}
    text = RUNNER
    for key, value in values.items(): text = text.replace(key, value)
    return text


def setup_script(folder: Path, runner: str, user: str, extra: str = '') -> str:
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
            f"Register-ScheduledTask -TaskName {q(TASK)} -Action $a -Principal $p -Settings $s -Force | Out-Null;" + extra)


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

    def has(self, name: str) -> bool:
        return (self.folder / name).is_file()

    def info(self) -> dict:
        return {'active': self.active()}

    def current(self) -> bool:
        """Il runner sa fare le azioni di questa versione (creato da una NEXAR vecchia: va rifatto con una conferma)."""
        try: return "'msi_light'" in (self.folder / 'runner.ps1').read_text(encoding='utf-8-sig')
        except OSError: return False

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
