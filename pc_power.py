"""Accensione e spegnimento del PC: comandi di Windows, Wake-on-LAN e relay di accensione per Umbrel."""
from __future__ import annotations
import ctypes
import json
import os
import re
import socket
import subprocess
import threading
import time

ACTIONS = {'shutdown': 'Spegnimento', 'restart': 'Riavvio', 'sleep': 'Sospensione', 'hibernate': 'Ibernazione', 'lock': 'Blocco schermo'}
GRACE_SECONDS = 30   # Windows mostra l'avviso e si può ancora annullare
MAC = re.compile(r'^([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}$')

def _run(args):
    opts = dict(capture_output=True, text=True, errors='replace', timeout=15)
    if os.name == 'nt': opts['creationflags'] = subprocess.CREATE_NO_WINDOW
    r = subprocess.run(args, **opts)
    if r.returncode: raise RuntimeError((r.stderr or r.stdout or 'Comando non eseguito').strip()[:200])

def hibernate_available():
    if os.name != 'nt': return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'SYSTEM\CurrentControlSet\Control\Power') as k:
            return bool(winreg.QueryValueEx(k, 'HibernateEnabled')[0])
    except OSError: return False

def execute(kind):
    """Esegue subito l'azione. Spegnimento e riavvio lasciano 30 s di avviso annullabili."""
    if os.name != 'nt': raise RuntimeError('Disponibile solo su Windows')
    note = 'NEXAR: ' + ACTIONS[kind].lower() + ' richiesto da remoto.'
    if kind == 'shutdown': _run(['shutdown', '/s', '/t', str(GRACE_SECONDS), '/c', note])
    elif kind == 'restart': _run(['shutdown', '/r', '/t', str(GRACE_SECONDS), '/c', note])
    elif kind == 'lock': ctypes.windll.user32.LockWorkStation()
    elif kind in ('sleep', 'hibernate'):
        if kind == 'hibernate' and not hibernate_available(): raise RuntimeError('Ibernazione non attiva su questo PC')
        # Qualche secondo per rispondere a Telegram/dashboard prima che la rete si spenga.
        def later():
            time.sleep(4)
            ctypes.windll.powrprof.SetSuspendState(kind == 'hibernate', False, False)
        threading.Thread(target=later, daemon=True, name='suspend').start()
    else: raise ValueError('Azione non prevista')

def abort_windows_shutdown():
    try: _run(['shutdown', '/a']); return True
    except Exception: return False   # nessuno spegnimento di Windows in corso

def idle_seconds():
    """Secondi dall'ultimo uso di mouse o tastiera."""
    if os.name != 'nt': return 0
    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [('cbSize', ctypes.c_uint), ('dwTime', ctypes.c_uint)]
    info = LASTINPUTINFO(ctypes.sizeof(LASTINPUTINFO), 0)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)): return 0
    return max(0, (ctypes.windll.kernel32.GetTickCount() - info.dwTime) & 0xFFFFFFFF) / 1000

def magic_packet(mac: str) -> bytes:
    if not MAC.match(mac or ''): raise ValueError('Indirizzo MAC non valido')
    return b'\xff' * 6 + bytes.fromhex(re.sub('[:-]', '', mac)) * 16

def send_magic(mac, broadcast='255.255.255.255'):
    packet = magic_packet(mac)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for target in dict.fromkeys([broadcast, '255.255.255.255']):
            for port in (9, 7): s.sendto(packet, (target, port))

# ---------- relay per Umbrel (o qualsiasi computer di casa sempre acceso) ----------
# Ascolta il bot SOLO mentre il PC non risponde al ping: quando il PC è acceso il bot lo gestisce l'app,
# così non si contendono i messaggi. Solo libreria standard: gira sull'immagine python:alpine.
RELAY = r'''
import json, os, socket, subprocess, time, urllib.parse, urllib.request
T = os.environ["BOT_TOKEN"]; U = int(os.environ["USER_ID"]); MAC = os.environ["PC_MAC"]
IP = os.environ["PC_IP"]; BC = os.environ.get("BROADCAST", "255.255.255.255")
def api(m, **p):
    d = urllib.parse.urlencode({k: (json.dumps(v) if isinstance(v, (dict, list)) else v) for k, v in p.items()}).encode()
    with urllib.request.urlopen("https://api.telegram.org/bot" + T + "/" + m, d, timeout=40) as r:
        return json.load(r).get("result")
def quiet(*a):
    return subprocess.call(list(a), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0
def alive():
    # Windows spesso blocca il ping: l'ARP invece risponde sempre quando il PC è acceso.
    if quiet("ping", "-c", "1", "-W", "1", IP): return True
    try: dev = subprocess.check_output(["ip", "route", "get", IP], text=True).split(" dev ")[1].split()[0]
    except Exception: return False
    return quiet("arping", "-c", "2", "-w", "3", "-I", dev, IP)
def wake():
    pkt = b"\xff" * 6 + bytes.fromhex(MAC.replace(":", "").replace("-", "")) * 16
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    for _ in range(3):
        for dst in (BC, "255.255.255.255"): s.sendto(pkt, (dst, 9))
        time.sleep(0.3)
    s.close()
KB = {"inline_keyboard": [[{"text": "⏻ Accendi il PC", "callback_data": "wake"}]]}
offset = None
while True:
    try:
        if alive():
            offset = None; time.sleep(15); continue
        # Il PC conferma ogni comando ricevuto prima di spegnersi: qui arrivano solo messaggi nuovi.
        for ev in api("getUpdates", offset=offset or 0, timeout=20, allowed_updates=["message", "callback_query"]):
            offset = ev["update_id"] + 1
            cb = ev.get("callback_query"); msg = ev.get("message") or (cb or {}).get("message") or {}
            who = (cb or msg).get("from", {}).get("id"); text = (cb or {}).get("data") or msg.get("text", "")
            if cb: api("answerCallbackQuery", callback_query_id=cb["id"])
            if who != U or (not cb and time.time() - msg.get("date", 0) > 300): continue
            if text.split("@")[0] in ("/accendi", "wake", "/wake"):
                wake(); api("sendMessage", chat_id=U, text="⏻ Segnale di accensione inviato. Ti scrivo appena il PC risponde.")
                for _ in range(36):
                    time.sleep(5)
                    if alive():
                        api("sendMessage", chat_id=U, text="🟢 PC acceso. Tra poco NEXAR riprende il controllo."); break
                else: api("sendMessage", chat_id=U, text="⚠️ Il PC non risponde. Controlla nel BIOS Wake on LAN / ErP disattivato.")
            else:
                api("sendMessage", chat_id=U, text="🔴 Il PC è spento.", reply_markup=KB)
    except Exception:
        time.sleep(10)
'''

def relay_compose(token, user_id, mac, ip, broadcast):
    if not (token and user_id): raise ValueError('Collega prima Telegram')
    magic_packet(mac)
    service = {
        'image': 'python:3.12-alpine', 'container_name': 'nexar-accensione', 'restart': 'unless-stopped',
        # La rete dell'host serve per il broadcast Wake-on-LAN nella rete di casa.
        'network_mode': 'host',
        'environment': {'BOT_TOKEN': token, 'USER_ID': str(user_id), 'PC_MAC': mac, 'PC_IP': ip, 'BROADCAST': broadcast},
        'command': ['python', '-u', '-c', RELAY.strip()],
    }
    # JSON è YAML valido; "$$" evita che Docker Compose interpreti eventuali "$".
    body = json.dumps({'services': {'nexar-accensione': service}}, ensure_ascii=False, indent=2).replace('$', '$$')
    return '# Stack Portainer/Umbrel: accende il PC da Telegram quando è spento. Contiene il token del bot: non condividerlo.\n' + body
