"""Windows PC ECO agent. Ventole AIO/BIOS mai comandate direttamente."""
from __future__ import annotations
import calendar
import ctypes
import hmac
import secrets
from datetime import datetime
import json
import logging
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import threading
import time
import sys
from collections import deque
import urllib.parse
from urllib.request import urlopen
import psutil
import energy_model
import gaming_boost
import fps as fps_meter
import pc_power
import procstop
import apps_remote
import screen_remote
import audio
import ai_watch
import remote_control
import gateway
import control_plus
import planner

FROZEN = getattr(sys, 'frozen', False)
INSTALL_DIR = Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parent
ASSET_ROOT = Path(getattr(sys, '_MEIPASS', str(INSTALL_DIR)))
# I dati dell'utente stanno fuori dalla cartella del programma: aggiornamenti e ricompilazioni non li toccano.
DATA_DIR = Path(os.environ.get('LOCALAPPDATA') or Path.home()) / 'NEXAR' if FROZEN else INSTALL_DIR
ROOT = DATA_DIR
CONFIG_FILE = DATA_DIR / 'config.json'
STATE_FILE = DATA_DIR / 'state.json'
LOG_FILE = DATA_DIR / 'nexar.log'

def migrate_data():
    """Primo avvio di NEXAR: porta config, stato e profili ventole dalla vecchia app PC ECO Control."""
    if not FROZEN or CONFIG_FILE.exists(): return None
    for old in (INSTALL_DIR, INSTALL_DIR.parent / 'PC-ECO-Control'):
        if (old / 'config.json').is_file():
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            for name in ('state.json', 'pc_eco.log', 'fan_profiles', 'config.json'):  # config per ultimo: segna la fine
                src = old / name
                if src.is_dir(): shutil.copytree(src, DATA_DIR / name, dirs_exist_ok=True)
                elif src.is_file(): shutil.copy2(src, DATA_DIR / ('nexar.log' if name == 'pc_eco.log' else name))
            return old
    return None

if FROZEN: DATA_DIR.mkdir(parents=True, exist_ok=True)
MIGRATED_FROM = migrate_data()
GUID = re.compile(r'[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}')
BALANCED = '381b4222-f694-41f0-9685-ff5bb260df2e'
FAN_SAFETY_TEMP = 80
FAN_SAFETY_TEMP_GPU = 78
FAN_OFF_LIMIT = 75      # ventole tutte spente: oltre questa temperatura tornano normali
FAN_GUARD_SECONDS = 2
FAN_VERIFY_SECONDS = 15  # tempo concesso a Fan Control per caricare un profilo prima di riprovare
FAN_PRESETS_MAX = 4  # profili ventole tuoi


def fans_mine_slow(custom):
    """Personalizzate con qualche ventola sotto il 50%: valgono le stesse protezioni di Silenziose (CPU calda → Normali)."""
    return any(isinstance(v, int) and v < 50 for v in (custom or {}).values())

FAN_SPACING = 3          # secondi minimi fra due profili mandati a Fan Control (due avvii insieme lo bloccano)

def windows_shutting_down():
    """True mentre Windows si spegne o si riavvia: in quei secondi NEXAR non deve toccare ventole e servizi."""
    if os.name != 'nt': return False
    try:
        import ctypes
        return bool(ctypes.windll.user32.GetSystemMetrics(0x2000))  # SM_SHUTTINGDOWN
    except Exception: return False
logging.basicConfig(filename=LOG_FILE, level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s', encoding='utf-8')

def weighted(played, key):
    """Media di tutte le partite di un gioco, pesata sulla durata (None se non c'è ancora)."""
    tot, secs = ((played or {}).get('w_' + key) or [0, 0])[:2]
    return round(tot / secs, 1) if secs else None

def start_rtss():
    """Apre RivaTuner (chiede lui il permesso di Windows): da lì arrivano gli FPS dei giochi."""
    exe = fps_meter.rtss_exe()
    if not exe: raise ValueError('RivaTuner non è installato: arriva insieme a MSI Afterburner')
    os.startfile(str(exe))
    return 'RivaTuner si apre: conferma la richiesta di Windows'

def epic_ref(game):
    """Riferimento del gioco nel launcher Epic (namespace:item:app), preso dal suo indirizzo di avvio."""
    m = re.match(r'com\.epicgames\.launcher://apps/([A-Za-z0-9%_.-]{1,200})\?', str((game or {}).get('launch') or ''))
    return m.group(1) if m else None

def store_page(gid, name, appid):
    """Pagina del gioco nel suo negozio: Steam per i giochi Steam (o trovati su Steam), Epic per quelli Epic."""
    if gid.startswith('epic-'):
        return {'store_url': 'https://store.epicgames.com/it/browse?' + urllib.parse.urlencode({'q': name, 'sortBy': 'relevancy', 'sortDir': 'DESC'}),
                'store_name': 'Epic'}
    if appid: return {'store_url': f'https://store.steampowered.com/app/{int(appid)}/', 'store_name': 'Steam'}
    return {'store_url': None, 'store_name': None}

def json_load(path: Path, default):
    try: return json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError): return default

def json_save(path: Path, val):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(val, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temp, path)

def cmd(args: list[str], timeout=15):
    opts = dict(capture_output=True, text=True, errors='replace', timeout=timeout)
    if os.name == 'nt': opts['creationflags'] = subprocess.CREATE_NO_WINDOW
    result = subprocess.run(args, **opts)
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout or 'Operazione fallita').strip()[:350])
    return result.stdout

def power(*args):
    if os.name != 'nt': raise RuntimeError('Modifica energia consentita solo su Windows')
    return cmd(['powercfg', *map(str,args)])

def get_guid():
    m = GUID.search(power('/getactivescheme'))
    if not m: raise RuntimeError('Profilo energetico di Windows non rilevato')
    return m.group(0).lower()

def valid_guid(x): return isinstance(x, str) and bool(GUID.fullmatch(x))

def float_num(x):
    try:
        if isinstance(x, (int, float)): return float(x)
        return float(re.search(r'-?\d+(?:[.,]\d+)?', str(x)).group(0).replace(',','.'))
    except (AttributeError, ValueError, TypeError): return None

def gpu_read():
    path = shutil.which('nvidia-smi')
    if not path and os.name == 'nt':
        guess = Path(os.environ.get('ProgramFiles', r'C:\Program Files')) / 'NVIDIA Corporation' / 'NVSMI' / 'nvidia-smi.exe'
        if guess.is_file(): path = str(guess)
    result = dict(load=None, temp=None, watts=None)
    if not path: return result
    try:
        txt = cmd([path, '--query-gpu=utilization.gpu,temperature.gpu,power.draw', '--format=csv,noheader,nounits'], 5)
        vals = [float_num(v.strip()) for v in txt.splitlines()[0].split(',')]
        if len(vals) >= 3: result = dict(zip(('load','temp','watts'), vals[:3]))
    except Exception as ex: logging.debug('nvidia-smi: %s',ex)
    return result

def collect_sensors(url: str):
    # URL di telemetria solo su loopback: nessun SSRF da configurazioni remote.
    if url not in ('http://127.0.0.1:8085/data.json', 'http://localhost:8085/data.json'):
        return {'cpu_temp':None,'fans':[],'cpu_power':None,'temp_ids':{},'temps':[]}
    try:
        with urlopen(url, timeout=0.6) as response:
            if int(response.headers.get('Content-Length', 0)) > 1_000_000: raise ValueError('JSON troppo grande')
            tree = json.loads(response.read(1_000_001))
    except Exception:
        return {'cpu_temp':None,'fans':[],'cpu_power':None,'temp_ids':{},'temps':[]}
    candidates, fans, cpu_power, gpu_ids = [], [], [], []
    def walk(node, trail):
        if isinstance(node, list):
            for n in node: walk(n, trail)
        if not isinstance(node, dict): return
        name = str(node.get('Text', node.get('Name','')))
        family = (' '.join(trail + [name])).lower()
        kind = str(node.get('Type','')).lower()
        value = float_num(node.get('Value'))
        sensor_id = str(node.get('SensorId','')).lower()
        if value is not None:
            if (kind == 'temperature' or '°c' in str(node.get('Value',''))) and (('cpu' in family or 'ryzen' in family or 'amdcpu' in sensor_id) and 'gpu' not in family):
                score = 0
                low = name.lower()
                if 'tctl' in low or 'tdie' in low: score += 10
                if 'package' in low: score += 7
                if 'core' in low: score += 4
                candidates.append((score, value, str(node.get('SensorId',''))))
            # Sensore della GPU per le curve delle ventole (Fan Control lo legge con lo stesso id).
            gm = re.match(r'/gpu-(nvidia|amd|intel)/\d+/temperature/', sensor_id)
            if gm and (kind == 'temperature' or '°c' in str(node.get('Value',''))):
                gpu_ids.append(({'nvidia': 0, 'amd': 1, 'intel': 2}[gm.group(1)], 'core' not in name.lower(), str(node.get('SensorId',''))))
            if (kind == 'fan' or 'rpm' in str(node.get('Value','')).lower()) and 0 <= value < 10000:
                if len(fans) < 12:
                    import discovery
                    fans.append({'name':name or 'Ventola', 'rpm':round(value), 'ctl':discovery.fan_control_id(str(node.get('SensorId','')))})
            # Potenza del processore: il sensore "Package" comprende core, cache e grafica integrata.
            if re.search(r'/(amd|intel)cpu/\d+/power/', sensor_id) and 'package' in name.lower() and 0 <= value < 500:
                cpu_power.append(value)
        for child in node.get('Children', []): walk(child, trail + [name])
    walk(tree, [])
    best = sorted(candidates, key=lambda c: c[0], reverse=True)[0] if candidates else None
    temp_ids = {k: v for k, v in (('cpu', best[2] if best else ''), ('gpu', sorted(gpu_ids)[0][2] if gpu_ids else '')) if v}
    try:
        import temps  # noqa: F401  (anche per PyInstaller)
        groups = temps.groups(tree)
    except Exception as ex:
        logging.debug('temperature: %s', ex); groups = []
    return {'cpu_temp': best[1] if best else None,'fans':fans,
            'cpu_power': cpu_power[0] if cpu_power else None, 'temp_ids': temp_ids, 'temps': groups}

HIGH_PERFORMANCE = '8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c'
USB_SUSPEND = ('2a737441-1930-4402-8d77-b2bebba308a3', '48e6b7a6-50f5-4782-a5d4-53bb8f07e226')
WIFI_SAVING = ('19cbb8fa-5279-450e-9fac-8a3d5fedd0c1', '12bbebe6-58d6-4636-95bb-3217ef867c1a')
# AI ECO regolabile: livelli pronti e singole voci (config['eco']).
ECO_DEFAULTS = {'level': 'balanced', 'turbo_off': True, 'park': 25, 'disk_idle': 10, 'pcie': True, 'usb': True, 'wifi': True,
                'leds_off': True, 'fans_quiet': True, 'sleep_idle': 0}
ECO_PRESETS = {
    'light':    {'turbo_off': False, 'cpu': 100, 'park': 50, 'disk_idle': 20, 'pcie': False, 'usb': True, 'wifi': False,
                 'leds_off': False, 'fans_quiet': False, 'monitor': 300, 'sleep_idle': 0},
    'balanced': {'turbo_off': True, 'cpu': 90, 'park': 25, 'disk_idle': 10, 'pcie': True, 'usb': True, 'wifi': True,
                 'leds_off': True, 'fans_quiet': True, 'monitor': 60, 'sleep_idle': 0},
    'max':      {'turbo_off': True, 'cpu': 60, 'park': 10, 'disk_idle': 5, 'pcie': True, 'usb': True, 'wifi': True,
                 'leds_off': True, 'fans_quiet': True, 'monitor': 30, 'sleep_idle': 20},
}
ECO_EXTRA = (('SUB_PROCESSOR', 'PERFBOOSTMODE', 0), ('SUB_PROCESSOR', 'PERFEPP', 80), ('SUB_PROCESSOR', 'CPMINCORES', 25),
             ('SUB_PCIEXPRESS', 'ASPM', 2), ('SUB_DISK', 'DISKIDLE', 600), (*USB_SUSPEND, 1), (*WIFI_SAVING, 3))
GAMING_EXTRA = (('SUB_PROCESSOR', 'PERFBOOSTMODE', 2), ('SUB_PROCESSOR', 'PERFEPP', 0), ('SUB_PCIEXPRESS', 'ASPM', 0),
                ('SUB_DISK', 'DISKIDLE', 0), (*USB_SUSPEND, 0), (*WIFI_SAVING, 0))
FAN_LEVEL_NAMES = {'off': 'spente', 'eco': 'silenziose', 'normal': 'normali', 'max': 'al massimo'}
MODES = {'eco': 'AI ECO', 'normal': 'Normale', 'gaming': 'Gaming'}
ARGB_HEADER_GUESS = 16
# Registro di Mystic Light (MSI Center): "ResetItem" vuol dire che ha appena riapplicato i suoi effetti
# a RAM e attacchi ARGB della scheda madre (avvio, schermo che si riaccende, uscita dalla sospensione).
MSI_LIGHT_LOG = Path(r'C:\Program Files (x86)\MSI\MSI Center\Log\MysticLight_Test\MysticLight.txt')
RGB_KEEP_EVERY = 1800  # anche senza segnali, ogni mezz'ora NEXAR rimette il suo stato dei LED
RGB_KEEP_OFF_EVERY = 600  # con i LED spenti ogni 10 minuti: chi li riaccende (MSI, firmware) viene corretto presto
RGB_OFF_SETTLE = (3, 10, 30)  # dopo uno spegnimento: secondi a cui i LED vengono rimessi spenti
RGB_QUIET_AFTER_USER = 15  # secondi dopo un comando dell'utente in cui il guardiano non tocca i LED
DEFAULT_PALETTE = ['#ffffff', '#ff0000', '#ff8a00', '#ffd400', '#2cff5a', '#00e5ff', '#1f6bff', '#8a3cff', '#ff3cc8']

def leds_estimate(ctl):
    """Zone fisse (RAM, GPU) hanno il numero vero; i connettori ARGB no: OpenRGB riporta solo la lunghezza
    impostata, non cosa è collegato, quindi si conta una ventola/striscia tipica. Tastiere e mouse wireless
    (tipo 5 e oltre) non sono alimentati dal PC."""
    if ctl.get('type', 0) >= 5: return 0
    return sum(z['leds_count'] if z['leds_min'] == z['leds_max'] else min(z['leds_count'], ARGB_HEADER_GUESS)
               for z in ctl.get('zones', []))

class Control:
    def __init__(self, config):
        self.config = config
        self.state = json_load(STATE_FILE, {})
        self.lock = threading.RLock()
        self.last_message = 'Pronto. Nessuna modalità applicata in questa sessione.'
        self.auto_last = False
        self.auto_idle = None
        self.manual_override = False
        self.started = datetime.now().isoformat(timespec='seconds')
        self.notify = lambda message: None
        self.events = deque(maxlen=80)
        self.temp_hist = deque(maxlen=1440)   # una fotografia di tutte le temperature al minuto, ultime 24 ore
        self.temp_hist_at = 0.0
        self.temp_alert = {}
        self.cache_time = 0.0
        self.cached_telemetry = None
        self.auto_previous_enabled = False
        self.auto_eco_owned = False
        self.telegram_pair = None
        self.integrations = []
        self.discover_lock = threading.Lock()
        self.msi_log_pos = None
        self.rgb_kept_at = 0.0
        # Un comando LED alla volta: il guardiano non deve mai riaccendere mentre si spegne (o viceversa).
        self.rgb_lock = threading.RLock()
        self.fan_lock = threading.Lock()
        # Un cambio di modalità alla volta. Luci e ventole si applicano FUORI da self.lock: prima set_mode teneva
        # self.lock e aspettava rgb_lock, mentre lo spegnimento LED teneva rgb_lock e aspettava self.lock → NEXAR bloccato.
        self.mode_lock = threading.RLock()
        self.fan_sent = (-1e9, '')  # (quando, profilo) dell'ultimo profilo mandato a Fan Control
        self.rgb_user_at = -1e9
        self.jobs = {}
        self.disk_prev = None
        self.video_timeout = (0.0, None)
        self.screen_off_at = 0.0
        self.power_plan = None
        self.booster = gaming_boost.Booster(config, state=self.state, save=self.save_state,
                                            notify=lambda m: self.notify(m), log=lambda m: self.log_event(m))
        import game_covers
        self.covers = game_covers.Covers(DATA_DIR / 'covers', online=lambda: bool(self.booster.settings().get('covers_online', True)),
                                         local=gaming_boost.steam_image)
        self.game_applied = None       # gioco a cui è già stato applicato il suo profilo in questa partita
        self.live_fps = None           # FPS del gioco adesso (da RivaTuner), None se non misurati
        self.stopper = procstop.Stopper()
        self.ai_watch = ai_watch.AiWatch()
        import admin_helper
        self.admin = admin_helper.AdminHelper(DATA_DIR)
        self.audio_mic = audio.MicTest()
        self.audio_setup = audio.Installer(str(DATA_DIR / 'downloads'), log=self.log_event)
        self.remote = remote_control.Remote(lambda: self.config.get('remote_control') or {},
                                            notify=lambda m: self.notify(m), log=lambda m: self.log_event(m))
        self.devices = gateway.Devices(self.config, save=lambda: self._save_config())
        # Grafici già pieni quando si apre l'app; medie orarie degli ultimi 30 giorni salvate nello stato.
        self.history = control_plus.History(self.telemetry, trend=self.state.setdefault('trend', []), save=self.save_state)
        self.planner = planner.Planner(lambda: self.config.get('schedules') or [], self.state.setdefault('schedule_runs', {}),
                                       self.save_state, self.run_scheduled, lock=self.lock)
        self.gaming_owned = False      # Gaming acceso da NEXAR perché è partito un gioco
        self.gaming_prev = 'normal'
        self.gaming_declined = False   # l'utente è uscito da Gaming a gioco aperto: non riattivarlo
        self.game_gone = None
        self.launch_grace = 0.0

    def save_state(self):
        with self.lock: json_save(STATE_FILE, self.state)

    # ---------- AI ECO regolabile ----------
    def eco_settings(self):
        e = {**ECO_DEFAULTS, **self.config.get('eco', {})}
        e['cpu'] = int(self.config.get('eco_cpu_max_percent', 90)); e['monitor'] = int(self.config.get('monitor_timeout_seconds', 60))
        return e

    def eco_power_extra(self):
        e = self.eco_settings()
        return (('SUB_PROCESSOR', 'PERFBOOSTMODE', 0 if e['turbo_off'] else 2), ('SUB_PROCESSOR', 'PERFEPP', 85 if e['turbo_off'] else 50),
                ('SUB_PROCESSOR', 'CPMINCORES', int(e['park'])), ('SUB_PCIEXPRESS', 'ASPM', 2 if e['pcie'] else 0),
                ('SUB_DISK', 'DISKIDLE', int(e['disk_idle']) * 60), (*USB_SUSPEND, 1 if e['usb'] else 0), (*WIFI_SAVING, 3 if e['wifi'] else 0))

    def set_eco_settings(self, new):
        """Un livello pronto (light/balanced/max) o singole voci; se AI ECO è attiva si applica subito."""
        if not isinstance(new, dict): raise ValueError('Impostazioni AI ECO non valide')
        if 'level' in new:
            if new['level'] not in ECO_PRESETS: raise ValueError('Livello: light, balanced o max')
            vals = dict(ECO_PRESETS[new['level']]); level = new['level']
        else:
            vals, level = {}, 'custom'
            for k in ('turbo_off', 'pcie', 'usb', 'wifi', 'leds_off', 'fans_quiet'):
                if k in new:
                    if type(new[k]) is not bool: raise ValueError(f'{k}: true/false')
                    vals[k] = new[k]
            for k, lo, hi in (('cpu', 50, 100), ('park', 5, 100), ('disk_idle', 0, 60), ('monitor', 30, 3600), ('sleep_idle', 0, 240)):
                if k in new:
                    if type(new[k]) is not int or not lo <= new[k] <= hi: raise ValueError(f'{k}: {lo}–{hi}')
                    vals[k] = new[k]
            if not vals: raise ValueError('Niente da cambiare')
        with self.lock:
            eco = self.config.setdefault('eco', {})
            for k, v in vals.items():
                if k == 'cpu': self.config['eco_cpu_max_percent'] = v
                elif k == 'monitor': self.config['monitor_timeout_seconds'] = v
                else: eco[k] = v
            eco['level'] = level
            json_save(CONFIG_FILE, self.config)
        applied = ''
        if self.mode() == 'eco':
            try: self.set_mode('eco', manual=False, quiet=True); applied = ' · applicato subito'
            except Exception as ex: applied = ' · non applicato: ' + str(ex)[:80]
        names = {'light': 'Leggero', 'balanced': 'Bilanciato', 'max': 'Massimo', 'custom': 'Personalizzato'}
        self.log_event('AI ECO: profilo ' + names[level] + applied)
        return {'settings': self.eco_settings(), 'message': 'AI ECO ' + names[level] + applied}

    def eco_info(self):
        st = self.state.get('stats', {})
        avg = {m: round(wh / (st.get('modes', {}).get(m, 0) / 3600)) for m, wh in (st.get('mode_wh') or {}).items()
               if st.get('modes', {}).get(m, 0) > 600}
        return {'settings': self.eco_settings(), 'presets': ECO_PRESETS, 'avg_w': avg,
                'price_eur_kwh': float(self.config.get('energy', {}).get('price_eur_kwh', 0.30))}

    def eco_sleep_check(self, now_idle=None):
        """Sospensione automatica: in AI ECO, con Codex/Claude fermi e nessuno al PC da N minuti."""
        minutes = int(self.eco_settings().get('sleep_idle') or 0)
        if not minutes or self.mode() != 'eco' or self.booster.active or self.power_plan: return False
        idle = pc_power.idle_seconds() if now_idle is None else now_idle
        if idle < 60: self.eco_slept = False; return False
        if getattr(self, 'eco_slept', False) or idle < minutes * 60 or any(self.processes().values()): return False
        self.eco_slept = True
        self.notify(f'💤 AI ECO: l’AI ha finito e il PC è inattivo da {minutes} minuti, lo metto in sospensione.')
        self.log_event('AI ECO: sospensione automatica')
        self.power_action('sleep')
        return True

    # ---------- Ottimizza: storico e pulizia automatica ----------
    def record_clean(self, freed, kind):
        """Ogni pulizia finisce nello storico: la pagina mostra quanto spazio NEXAR ha liberato in tutto."""
        with self.lock:
            h = self.state.setdefault('optimize_history', [])
            h.insert(0, {'at': int(time.time()), 'freed': int(freed), 'kind': kind}); del h[30:]
            self.state['optimize_freed_total'] = int(self.state.get('optimize_freed_total', 0)) + int(freed)
            if kind == 'automatica': self.state['optimize_last_auto'] = int(time.time())
            json_save(STATE_FILE, self.state)

    NET_EVERY = 3600   # prova automatica della rete: una volta all'ora
    NET_KEEP = 336     # due settimane di prove orarie

    def record_net(self, n, auto=False):
        """Ogni prova della rete finisce nello storico (internet, router, DNS): la pagina ne disegna l'andamento."""
        def ms(x): return (x or {}).get('ms') if isinstance(x, dict) else None
        row = {'at': int(n.get('at') or time.time()), 'ms': ms(n.get('internet')), 'router': ms(n.get('router')),
               'dns': n.get('dns_ms'), 'loss': (n.get('internet') or {}).get('loss'), 'q': n.get('quality'), 'auto': bool(auto)}
        with self.lock:
            self.net_report = n
            h = self.state.setdefault('net_history', [])
            h.append(row); del h[:-self.NET_KEEP]
            json_save(STATE_FILE, self.state)
        return row

    def net_alert(self, row):
        """Avviso (Telegram e notifica) quando internet cade o diventa molto più lento del solito.
        Una volta ogni 6 ore al massimo, e un messaggio quando torna normale."""
        hist = [r for r in (self.state.get('net_history') or [])[:-1] if r.get('ms') is not None][-24:]
        usual = sorted(r['ms'] for r in hist)[len(hist) // 2] if len(hist) >= 3 else None
        bad = (row.get('q') == 'offline' and 'internet non raggiungibile') or \
              (usual is not None and row.get('ms') is not None and row['ms'] >= max(80, usual * 3) and
               f"internet a {row['ms']} ms (di solito {usual} ms)") or \
              ((row.get('loss') or 0) >= 50 and f"{row['loss']}% di pacchetti persi")
        now = time.time()
        if bad:
            if now - float(self.state.get('net_alert_at') or 0) < 6 * 3600: return None
            msg = '📶 Rete: ' + bad
            with self.lock: self.state['net_alert_at'] = now; self.state['net_alert_open'] = True; json_save(STATE_FILE, self.state)
        elif self.state.get('net_alert_open'):
            msg = f"📶 Rete di nuovo a posto: internet {row.get('ms')} ms"
            with self.lock: self.state['net_alert_open'] = False; json_save(STATE_FILE, self.state)
        else: return None
        self.log_event(msg); self.notify(msg)
        return msg

    def set_net_auto(self, enabled):
        with self.lock:
            self.config.setdefault('optimize', {})['net_auto'] = bool(enabled)
            json_save(CONFIG_FILE, self.config)
        return 'Prova della rete automatica ' + ('attiva: una volta all\'ora, con avviso se peggiora' if enabled else 'spenta')

    def net_loop(self, stop_event):
        """Prova della rete ogni ora (se attiva), mai mentre si gioca: tiene lo storico e avvisa se peggiora."""
        import optimizer
        while not stop_event.wait(60):
            try:
                if not self.config.get('optimize', {}).get('net_auto', True) or self.booster.active: continue
                last = max([r.get('at', 0) for r in (self.state.get('net_history') or []) if r.get('auto')] or [0])
                if time.time() - last < self.NET_EVERY: continue
                self.net_alert(self.record_net(optimizer.network_check(), auto=True))
            except Exception: logging.exception('Prova della rete automatica')

    def optimize_extra(self):
        o = self.config.get('optimize', {})
        last = int(self.state.get('optimize_last_auto') or 0)
        return {'history': list(self.state.get('optimize_history') or [])[:12], 'freed_total': int(self.state.get('optimize_freed_total', 0)),
                'auto': bool(o.get('auto')), 'auto_last': last or None, 'auto_next': (last + 7 * 86400) if o.get('auto') and last else None,
                'large': getattr(self, 'large_report', None), 'health': getattr(self, 'disk_report', None), 'net': getattr(self, 'net_report', None),
                'net_history': list(self.state.get('net_history') or [])[-168:], 'net_auto': bool(o.get('net_auto', True))}

    def set_optimize_auto(self, enabled):
        with self.lock:
            self.config.setdefault('optimize', {})['auto'] = bool(enabled)
            json_save(CONFIG_FILE, self.config)
        return 'Pulizia automatica ' + ('attiva: una volta a settimana, quando il PC è tranquillo' if enabled else 'spenta')

    def optimize_loop(self, stop_event):
        """Pulizia automatica (se attiva): una volta a settimana, con il PC poco carico e mai durante il Gaming."""
        import optimizer
        while not stop_event.wait(1800):
            try:
                if not self.config.get('optimize', {}).get('auto') or self.booster.active: continue
                if time.time() - int(self.state.get('optimize_last_auto') or 0) < 7 * 86400: continue
                if psutil.cpu_percent(interval=2) > 35: continue
                res = optimizer.clean(optimizer.SAFE_CLEAN)
                self.record_clean(res['freed'], 'automatica')
                msg = '🧹 Pulizia automatica della settimana: liberati ' + optimizer.human(res['freed'])
                self.log_event(msg); self.notify(msg)
            except Exception: logging.exception('Pulizia automatica')

    def boost_loop(self, stop_event):
        """Ogni 5 s: trova il gioco aperto, accende/spegne Gaming da solo (se attivo) e cura le priorità.
        Se NEXAR riparte in Gaming riattiva il boost."""
        while not stop_event.wait(5):
            try:
                gaming = self.mode() == 'gaming'
                if gaming and not self.booster.active: self.booster.start()
                elif not gaming and self.booster.active: self.booster.stop()
                game = self.booster.tick() if os.name == 'nt' else None
                if self.booster.active:
                    t = dict(self.telemetry())
                    t['fps'] = self.live_fps = fps_meter.game_fps(self.booster.game_pids, self.booster.fg_pid) if game else None
                    self.booster.sample(t)
                else: self.live_fps = None
                if self.booster.active and game and game.get('id') != self.game_applied:
                    self.game_applied = game['id']
                    try: self.apply_game_profile(game)
                    except Exception: logging.exception('Profilo del gioco')
                elif not self.booster.active: self.game_applied = None
                self.auto_gaming(game, gaming)
            except Exception: logging.exception('Gaming Boost')
            try: self.stopper_tick()
            except Exception: logging.exception('Programmi inutili')

    def auto_gaming(self, game, gaming):
        now = time.monotonic()
        if game:
            self.game_gone = None
            if (self.booster.settings()['auto'] and self.booster.game_profile(game.get('id', ''))['auto']
                    and not gaming and not self.gaming_owned and not self.gaming_declined):
                self.gaming_prev = self.mode() or 'normal'
                self.gaming_owned = True
                self.set_mode('gaming', manual=False, reason=game['name'])
            return
        self.gaming_declined = False
        if not self.gaming_owned or now < self.launch_grace: return
        if self.game_gone is None: self.game_gone = now
        elif now - self.game_gone >= 20:   # gioco chiuso da 20 s: si torna a com'era prima
            self.gaming_owned, self.game_gone = False, None
            if gaming: self.set_mode(self.gaming_prev if self.gaming_prev in MODES and self.gaming_prev != 'gaming' else 'normal', manual=False)

    def stopper_tick(self):
        """Gaming e AI ECO: chiude i programmi inutili (anche se ripartono) e in AI ECO mette lo sfondo in risparmio."""
        if os.name != 'nt': return []
        s, mode = self.booster.settings(), self.mode()
        rules = s.get('eco_apps') if mode == 'eco' else s.get('apps') if mode == 'gaming' else {}
        spare = self.config.get('auto_detect', {}).get('process_names') or []
        closed = self.stopper.tick(mode, rules or {}, bool(s.get('stop_junk', True)), bool(s.get('eco_throttle', True)), spare=spare)
        if closed:
            self.log_event(('AI ECO' if mode == 'eco' else 'Gaming') + ': fermati ' + ', '.join(n.replace('.exe', '') for n in closed))
        return closed

    def startup_junk(self):
        import optimizer
        try: return procstop.startup_junk(optimizer.startup_items())
        except Exception: return []

    def startup_junk_off(self, elevate=None):
        """Toglie dall'avvio di Windows i programmi inutili (si possono riattivare da Ottimizza → Avvio)."""
        import optimizer
        done = []
        for it in self.startup_junk():
            if it['admin'] and not elevate: continue
            try: optimizer.set_startup(it['id'], False, elevate); done.append(it['name'])
            except (ValueError, RuntimeError, OSError) as ex: logging.info('Avvio %s: %s', it['name'], ex)
        msg = ('Tolti dall\'avvio: ' + ', '.join(done)) if done else 'Niente da togliere dall\'avvio'
        self.log_event(msg)
        return msg

    # ---------- app del PC da aprire a distanza ----------
    def remote_apps(self):
        cfg = self.config.setdefault('remote_apps', None)
        if cfg is None:   # prima volta: Claude e Codex, se installati
            cfg = apps_remote.defaults(apps_remote.start_apps())
            with self.lock: self.config['remote_apps'] = cfg; json_save(CONFIG_FILE, self.config)
        return [a for a in cfg if isinstance(a, dict) and a.get('id')]

    def apps_view(self, all_apps=False):
        every = apps_remote.start_apps()
        names = apps_remote.running_names()
        pinned = []
        for p in self.remote_apps():
            a = apps_remote.find(p['id'], every) or {'id': p['id'], 'name': p.get('name', 'App'), 'exe': '', 'key': apps_remote.app_key(p['id'])}
            pinned.append({'id': a['id'], 'name': a['name'], 'key': a['key'], 'running': apps_remote.is_running(a, names),
                           'closable': bool(a.get('exe')), 'missing': apps_remote.find(p['id'], every) is None})
        out = {'pinned': pinned}
        if all_apps:
            ids = {p['id'] for p in pinned}
            out['available'] = [{'id': a['id'], 'name': a['name'], 'key': a['key'], 'pinned': a['id'] in ids} for a in every]
        return out

    def app_pin(self, app_id, pinned):
        """Aggiunge o toglie un'app: solo app del menu Start di questo PC, niente percorsi scritti a mano."""
        cur = self.remote_apps()
        if pinned:
            a = apps_remote.find(app_id)
            if not a: raise ValueError('App non trovata sul PC')
            if any(p['id'] == app_id for p in cur): return 'Già nell\'elenco'
            if len(cur) >= apps_remote.MAX_PINNED: raise ValueError(f'Al massimo {apps_remote.MAX_PINNED} app')
            cur = cur + [{'id': a['id'], 'name': a['name']}]; msg = a['name'] + ' aggiunta'
        else:
            cur = [p for p in cur if p['id'] != app_id]; msg = 'App tolta'
        with self.lock: self.config['remote_apps'] = cur; json_save(CONFIG_FILE, self.config)
        return msg

    def app_open(self, app_id):
        p = next((p for p in self.remote_apps() if p['id'] == app_id), None)
        if not p: raise ValueError('Aggiungi prima l\'app all\'elenco')
        apps_remote.launch(app_id)
        name = (apps_remote.find(app_id) or p).get('name', 'App')
        self.log_event('Aperta da remoto: ' + name)
        return 'Apro ' + name

    def app_close(self, app_id):
        if not any(p['id'] == app_id for p in self.remote_apps()): raise ValueError('App non nell\'elenco')
        a = apps_remote.find(app_id)
        if not a: raise ValueError('App non trovata')
        apps_remote.close(a)
        self.log_event('Chiusa da remoto: ' + a['name'])
        return 'Chiudo ' + a['name']

    def app_icon(self, key):
        if not re.fullmatch(r'[0-9a-f]{16}', key): return None
        dest = DATA_DIR / 'icons' / f'app-{key}.png'
        if dest.is_file(): return dest
        a = next((a for a in apps_remote.start_apps() if a['key'] == key), None)
        return dest if a and apps_remote.icon_png(a, dest) else None

    # ---------- schermo del PC visto da lontano ----------
    def screen_settings(self):
        s = self.config.get('screen') or {}
        return {'view': bool(s.get('view', True)), 'ai_alert': bool(s.get('ai_alert', True))}

    def set_screen_settings(self, view=None, ai_alert=None):
        with self.lock:
            s = self.config.setdefault('screen', {})
            if view is not None: s['view'] = bool(view)
            if ai_alert is not None: s['ai_alert'] = bool(ai_alert)
            json_save(CONFIG_FILE, self.config)
        if ai_alert is False: self.ai_watch.reset()
        return self.screen_settings()

    def screen_shot(self, who='dashboard', mon=None, live=False):
        """mon=None: tutti gli schermi insieme (Telegram); altrimenti uno solo, o 'all', per la dashboard."""
        if not self.screen_settings()['view']: raise PermissionError('Vedere lo schermo da remoto è disattivato (Accensione e app → Schermo)')
        jpg = screen_remote.capture() if mon is None else screen_remote.snapshot(mon, live)
        now = time.monotonic()
        if now - getattr(self, 'screen_logged', -1e9) > 300:   # una riga nel registro, non una per ogni aggiornamento
            self.screen_logged = now
            self.log_event('🖥 Schermo visto da remoto (' + who + ')')
        return jpg

    # ---------- audio: cuffie, casse, microfoni, app ----------
    def _audio_boosts(self):
        return (self.config.get('audio') or {}).get('boosts') or {}

    def audio_view(self):
        o = audio.overview(self._audio_boosts())
        o['setup'] = self.audio_setup.info()
        return o

    def audio_device(self, dev_id, volume=None, mute=None, default=None):
        if volume is not None and not 0 <= volume <= 100: raise ValueError('Volume tra 0 e 100')
        if volume is not None or mute is not None: audio.set_device(dev_id, volume, mute)
        if default: audio.set_default(dev_id); return 'Ora l\'audio passa da qui'
        return 'Fatto'

    def audio_boost(self, dev_id, db=None, eq=None, hw=None, bands=None):
        guid = audio.guid_of(dev_id)
        if not guid: raise ValueError('Dispositivo audio non valido')
        if hw is not None:
            got = audio.set_hw_boost(dev_id, hw)
            return f'Boost della scheda audio: +{got:g} dB'
        flow = 'in' if dev_id.startswith('{0.0.1.') else 'out'
        if db is not None and not 0 <= db <= audio.MAX_BOOST[flow]: raise ValueError(f'Amplificazione tra 0 e +{audio.MAX_BOOST[flow]} dB')
        if eq is not None and eq not in audio.EQ_PRESETS: raise ValueError('Suono non previsto')
        if bands is not None:
            if len(bands) != len(audio.BANDS) or any(not -audio.EQ_LIMIT <= float(x) <= audio.EQ_LIMIT for x in bands):
                raise ValueError(f'Equalizzatore: {len(audio.BANDS)} bande tra -{audio.EQ_LIMIT} e +{audio.EQ_LIMIT} dB')
            eq = 'custom'
        with self.lock:
            boosts = self.config.setdefault('audio', {}).setdefault('boosts', {})
            b = boosts.setdefault(guid, {'db': 0, 'eq': 'flat'})
            if db is not None: b['db'] = round(float(db), 1)
            if eq is not None: b['eq'] = eq
            if bands is not None: b['bands'] = [round(float(x), 1) for x in bands]
            if b['eq'] != 'custom': b.pop('bands', None)
            elif not any(b.get('bands') or []): b['eq'] = 'flat'; b.pop('bands', None)
            if not b['db'] and b['eq'] == 'flat': boosts.pop(guid, None)
            json_save(CONFIG_FILE, self.config)
            snapshot = {k: dict(v) for k, v in boosts.items()}
        paths = audio.apo_paths()
        if not paths: return "Salvato: si sente appena installi l'amplificatore"
        try: audio.apo_write(snapshot, paths[1])
        except OSError as ex: raise RuntimeError("Non riesco a scrivere le impostazioni dell'amplificatore: " + str(ex))
        return 'Amplificazione aggiornata'

    def audio_app(self, app_id, volume=None, mute=None):
        if volume is not None and not 0 <= volume <= 100: raise ValueError('Volume tra 0 e 100')
        audio.set_app(str(app_id).lower(), volume, mute)
        return 'Fatto'

    def audio_levels(self):
        lv = audio.levels()
        lv['mic_test'] = self.audio_mic.active(); lv['mic_error'] = self.audio_mic.error
        return lv

    def audio_mic_test(self, on):
        if on: self.audio_mic.start(); return 'Parla: la barra del microfono si muove'
        self.audio_mic.stop(); return 'Prova del microfono finita'

    def audio_max(self):
        audio.max_all()
        self.log_event('🔊 Audio: tutto al massimo')
        return 'Cuffie, microfono e app al 100%'

    def audio_ducking(self, on):
        audio.set_ducking(bool(on))
        return 'Durante le chiamate Windows abbassa gli altri suoni' if on else 'Durante le chiamate il volume non si abbassa più'

    def audio_install(self):
        if audio.apo_paths(): raise ValueError("L'amplificatore è già installato")
        return self.audio_setup.start()

    def audio_selector(self):
        audio.open_selector()
        return 'Sul PC si è aperta la finestra: spunta cuffie e microfono, OK, poi riavvia il PC'

    def screen_view(self):
        try: mons = [{k: m[k] for k in ('id', 'x', 'y', 'w', 'h', 'primary')} for m in remote_control.monitors()]
        except Exception: mons = []
        return {'settings': self.screen_settings(), 'windows': screen_remote.windows(), 'ai_busy': self.ai_watch.busy(), 'monitors': mons}

    def screen_action(self, action, win_id=None, force=False):
        if action == 'close':
            if type(win_id) is not int: raise ValueError('Finestra non valida')
            msg = screen_remote.close_window(win_id, force)
        elif action in screen_remote.VOLUME_KEYS: msg = screen_remote.volume(action)
        elif action == 'monitor_off': msg = screen_remote.monitor_off()
        elif action == 'lock': msg = self.power_action('lock')
        else: raise ValueError('Azione non prevista')
        self.log_event('🖥 ' + msg)
        return msg

    # ---------- controllo remoto (mouse e tastiera) ----------
    def remote_setup(self, enabled=None, pin=None, idle_minutes=None):
        """Solo dal PC: accende/spegne il controllo, sceglie il PIN e dopo quanto chiudere la sessione."""
        with self.lock:
            rc = dict(self.config.get('remote_control') or {})
            if pin is not None:
                if not remote_control.valid_pin(pin): raise ValueError('Il PIN deve avere 6 cifre, non tutte uguali e non 123456')
                rc['pin_hash'] = remote_control.pin_hash(pin)
            if idle_minutes is not None:
                if idle_minutes not in remote_control.IDLE_CHOICES: raise ValueError('Durata non prevista')
                rc['idle_minutes'] = idle_minutes
            if enabled is not None:
                if enabled and not rc.get('pin_hash'): raise ValueError('Scegli prima il PIN')
                rc['enabled'] = bool(enabled)
            self.config['remote_control'] = rc
            json_save(CONFIG_FILE, self.config)
        if enabled is False: self.remote.end(reason='controllo spento')
        if pin is not None: self.remote.end(reason='PIN cambiato')
        self.log_event('🖱 Controllo remoto: ' + ('acceso' if rc.get('enabled') else 'spento') + (' · PIN aggiornato' if pin is not None else ''))
        return self.remote.info()

    # ---------- ponte Umbrel + dispositivi collegati (Mac) ----------
    def _save_config(self):
        with self.lock: json_save(CONFIG_FILE, self.config)

    def gateway_info(self, bridge=None):
        g = self.config.get('gateway') or {}
        net = self.state.get('inventory', {}).get('net') or {}
        return {'enabled': bool(g.get('enabled')), 'umbrel_ip': g.get('umbrel_ip', ''), 'pc_ip': net.get('ip', ''),
                'pc_port': gateway.GATEWAY_PORT, 'port': gateway.UMBREL_PORT, 'firewall': bool(g.get('firewall')),
                'wol': bool(net.get('mac')), **(bridge.info() if bridge else {'running': False, 'error': ''}),
                'devices': self.devices.list()}

    def gateway_setup(self, enabled, umbrel_ip=None, firewall=None):
        """Solo dal PC. Attivando chiede una volta i permessi per la regola del firewall (solo l'IP di Umbrel)."""
        g = dict(self.config.get('gateway') or {})
        if umbrel_ip is not None:
            umbrel_ip = str(umbrel_ip).strip()
            if not gateway.valid_lan_ip(umbrel_ip): raise ValueError('Indirizzo di Umbrel non valido (es. 192.168.0.50)')
            if umbrel_ip != g.get('umbrel_ip'): g['firewall'] = False
            g['umbrel_ip'] = umbrel_ip
        if enabled and not g.get('umbrel_ip'): raise ValueError("Scrivi prima l'indirizzo di Umbrel")
        if enabled and not g.get('firewall'):
            run = firewall or (lambda: __import__('discovery').run_elevated(gateway.firewall_script(sys.executable, g['umbrel_ip']), wait=True))
            if not run(): raise RuntimeError('Conferma amministratore annullata: senza la regola del firewall Umbrel non raggiunge il PC')
            g['firewall'] = True
        g['enabled'] = bool(enabled)
        with self.lock:
            self.config['gateway'] = g
            json_save(CONFIG_FILE, self.config)
        self.log_event('🍎 Ponte Umbrel ' + ('attivo verso ' + g['umbrel_ip'] if enabled else 'spento'))
        return 'Ponte attivo: ora Umbrel può raggiungere NEXAR' if enabled else 'Ponte spento'

    def relay_compose(self, bridge=False):
        net = self.state.get('inventory', {}).get('net') or {}
        tg = self.config.get('telegram', {})
        # Il relay ascolta anche le richieste di accensione dell'app per Mac (canale cifrato).
        wake = self.beacon.secret() if getattr(self, 'beacon', None) else ''
        if bridge:
            return pc_power.relay_compose(tg.get('token') if net.get('mac') else None, tg.get('allowed_user_id'), net.get('mac', ''),
                                          net.get('ip', ''), net.get('broadcast', '255.255.255.255'),
                                          bridge={'pc_port': gateway.GATEWAY_PORT, 'port': gateway.UMBREL_PORT}, wake_secret=wake)
        if not net.get('mac'): raise RuntimeError('Scheda di rete via cavo non trovata: premi "Cerca di nuovo" in Collegamenti')
        return pc_power.relay_compose(tg.get('token'), tg.get('allowed_user_id'), net['mac'], net.get('ip', ''), net.get('broadcast', '255.255.255.255'), wake_secret=wake)

    def admin_setup(self):
        """Una conferma UAC sul PC: da quel momento le azioni da amministratore funzionano anche da lontano."""
        import discovery
        if not discovery.run_elevated(self.admin_script(), wait=True):
            raise RuntimeError('Conferma amministratore annullata')
        if not self.admin.active(): raise RuntimeError('Attività NEXAR Admin non creata')
        self.log_event('🛡 Amministratore da remoto attivato')
        return 'Amministratore da remoto attivo'

    def admin_script(self):
        import admin_helper, discovery, optimizer
        folder = admin_helper.root()
        exe = sys.executable
        fan_exe = self.config.get('fans', {}).get('fancontrol_exe') or discovery.find_fancontrol()
        clean = {t['key']: str(t['paths'][0]) for t in optimizer.targets() if t.get('admin')}
        runner = admin_helper.runner_text(
            DATA_DIR / 'admin-request.json', folder / 'result.json', exe, clean, discovery.WINGET,
            fans_script=discovery.fancontrol_script(fan_exe, ROOT / 'fan_profiles') if fan_exe else '',
            trim=optimizer.TRIM_SCRIPT, autostart=discovery.autostart_task_script(exe), approved=optimizer.APPROVED,
            rule=gateway.FIREWALL_RULE, port=gateway.GATEWAY_PORT, autostart_task=discovery.AUTOSTART_TASK,
            apps=discovery.close_apps_table())
        user = f"{os.environ.get('USERDOMAIN', '')}\\{os.environ.get('USERNAME', '')}".strip('\\')
        return admin_helper.setup_script(folder, runner, user)

    def admin_remove(self):
        import admin_helper, discovery
        if not discovery.run_elevated(admin_helper.remove_script(admin_helper.root()), wait=True):
            raise RuntimeError('Conferma amministratore annullata')
        self.log_event('🛡 Amministratore da remoto disattivato')
        return 'Amministratore da remoto disattivato'

    def umbrel_code(self):
        """Codice da incollare una volta nell'app NEXAR su Umbrel: accensione, bot e accesso alla dashboard."""
        import base64
        net = self.state.get('inventory', {}).get('net') or {}
        if not net.get('mac') or not net.get('ip'): raise RuntimeError('Scheda di rete via cavo del PC non trovata: premi "Cerca di nuovo" in Collegamenti')
        b = getattr(self, 'beacon', None)
        if not b: raise RuntimeError('Collegamento non disponibile')
        tg = self.config.get('telegram', {})
        data = {'v': 1, 'name': socket.gethostname(), 'pc_ip': net['ip'], 'pc_mac': net['mac'], 'broadcast': net.get('broadcast') or '255.255.255.255',
                'pc_port': gateway.GATEWAY_PORT, 'wake_secret': b.secret(), 'token': self.devices.issue('Umbrel', tag='umbrel'),
                'bot_token': tg.get('token') or '', 'user_id': tg.get('allowed_user_id') or 0}
        b.kick.set()
        self.log_event('🏠 Codice per l\'app su Umbrel generato')
        return 'NEXAR1.' + base64.urlsafe_b64encode(json.dumps(data, separators=(',', ':')).encode()).decode().rstrip('=')

    def wake_link(self):
        """Link di accensione per il telefono: aprirlo pubblica un messaggio su ntfy che il relay su Umbrel ascolta."""
        import beacon as beacon_mod
        b = getattr(self, 'beacon', None)
        if not b: raise RuntimeError('Accensione dal telefono non disponibile')
        return beacon_mod.NTFY + '/' + beacon_mod.topic('link:' + b.secret()) + '/trigger'

    def ai_names(self):
        return {str(n).lower() for n in self.config.get('auto_detect', {}).get('process_names') or ['codex.exe', 'claude.exe']}

    def ai_done_check(self, now=None, idle=None):
        """Codex o Claude hanno finito un lavoro lungo e non sei al PC: avviso su Telegram (con il pulsante per vedere lo schermo)."""
        if not self.screen_settings()['ai_alert']: return []
        done = self.ai_watch.tick(self.ai_names(), now=now)
        if not done: return []
        away = (pc_power.idle_seconds() if idle is None else idle) >= ai_watch.AWAY_SECONDS
        out = []
        for app, worked in done:
            name = {'codex': 'Codex', 'claude': 'Claude'}.get(Path(app).stem.lower(), Path(app).stem)
            msg = f'✅ {name} ha finito: lavorava da {max(1, round(worked / 60))} min.'
            self.log_event(msg)
            if away: self.notify(msg + ' Tocca 🖥 Vedi schermo per controllare.')
            out.append(msg)
        return out

    def quit_game(self):
        """Dalla scheda del gioco: chiude il gioco (es. Fortnite) e, se era in Gaming, torna alla modalità normale."""
        if os.name != 'nt': raise RuntimeError('Disponibile solo su Windows')
        name = self.booster.quit_game()
        notes = [f'{name} chiuso'] if name else ['Nessun gioco aperto']
        if self.mode() == 'gaming': notes.append(self.set_mode('normal'))
        msg = ' · '.join(n for n in notes if n)
        self.log_event('🎮 ' + msg)
        return msg

    def launch_game(self, gid):
        if os.name != 'nt': raise RuntimeError('Disponibile solo su Windows')
        game = self.booster.find(str(gid))
        if not game: raise ValueError('Gioco non trovato: aggiorna la libreria')
        notes = []
        if self.mode() != 'gaming':
            self.gaming_prev = self.mode() or 'normal'
            notes.append(self.set_mode('gaming', manual=False, reason=game['name'], quiet=True))
            self.gaming_owned = True
        # Il launcher può aggiornare il gioco prima di aprirlo: 3 minuti di pazienza prima di tornare indietro.
        self.launch_grace = time.monotonic() + 180
        gaming_boost.launch(game)
        msg = f"Avvio {game['name']} da {game['store']}"
        self.log_event(msg)
        return msg

    def gaming_view(self, force=False):
        cfg = self.config
        per = self.booster.settings().get('per_game') or {}
        played = self.state.get('games') or {}
        return {'boost': self.booster.info(), 'games': [dict({k: g[k] for k in ('id', 'name', 'store', 'size', 'last', 'playtime', 'sessions', 'cover', 'hidden')},
                                                             icon=bool(g.get('exe')), cv=self.covers.version(g['id']), custom=g['id'] in per,
                                                             fps=weighted(played.get(g['id']), 'fps_avg'), fps_low=weighted(played.get(g['id']), 'fps_low'),
                                                             cpu_t=weighted(played.get(g['id']), 'cpu_temp_avg'), gpu_t=weighted(played.get(g['id']), 'gpu_temp_avg'))
                                                        for g in self.booster.games(force)],
                'fps': {'source': fps_meter.status(), 'live': getattr(self, 'live_fps', None)},
                'history': self.booster.history()[:12], 'apps': gaming_boost.user_apps()[:40],
                'fans': cfg.get('fans', {}).get('gaming_level', 'normal'), 'fans_enabled': bool(cfg.get('fans', {}).get('enabled')),
                'rgb_color': cfg.get('rgb', {}).get('gaming_color', ''), 'rgb_enabled': bool(cfg.get('rgb', {}).get('enabled')),
                'palette': self.rgb_palette(), 'junk': procstop.JUNK, 'stopper': self.stopper.info(),
                'startup_junk': self.startup_junk()}

    # ---------- un gioco alla volta: scheda, profilo, copertina ----------
    def apply_game_profile(self, game):
        """Quando parte un gioco in Gaming: ventole, luci e mouse scelti solo per lui."""
        p = self.booster.game_profile(game['id']); notes = []
        fans = self.config.get('fans', {})
        if p['fans'] and fans.get('enabled') and p['fans'] != fans.get('gaming_level', 'normal'):
            notes.append(self.fans_level(p['fans']))
        rgb = self.config.get('rgb', {})
        if rgb.get('enabled') and p['rgb']:
            notes.append(self.rgb_color(p['rgb'], int(rgb.get('brightness', 100)), remember=False))
            self.state['rgb_gaming'] = True; self.save_state()
        elif rgb.get('enabled') and p['rgb'] == '' and self.state.get('rgb_gaming'):
            notes.append(self.rgb_mode('normal'))
        notes.append(self.booster.game_mouse(p['mouse']))
        notes = [n for n in notes if n]
        if notes: self.log_event(f"Profilo di {game['name']}: " + ' · '.join(notes))
        return notes

    def game_detail(self, gid):
        g = next((x for x in self.booster.games() if x['id'] == gid), None)
        if not g: raise ValueError('Gioco non trovato: aggiorna la libreria')
        lib = self.booster.find(gid) or {}
        played = (self.state.get('games') or {}).get(gid) or {}
        recent = played.get('recent') or [h for h in self.booster.history() if h.get('gid') == gid]
        appid = gid[6:] if gid.startswith('steam-') else (self.covers.meta()['appids'].get(gid) or None)
        running = (self.booster.running or {}).get('id') == gid
        tmax = lambda k: played.get(k) or max((h[k] for h in recent if h.get(k) is not None), default=None)
        return {'id': gid, 'name': g['name'], 'store': g['store'], 'size': g.get('size') or 0, 'dir': lib.get('dir', ''),
                'last': g.get('last') or 0, 'hidden': g['hidden'], 'running': running, 'icon': bool(lib.get('exe')),
                'appid': appid, 'steam': gid.startswith('steam-'), 'cv': self.covers.version(gid),
                'verify': 'Steam' if gid.startswith('steam-') else 'Epic' if epic_ref(lib) else None,
                **store_page(gid, g['name'], appid),
                'custom_cover': self.covers.custom(gid).is_file(),
                'stats': {'seconds': g.get('playtime') or 0, 'sessions': int(played.get('sessions') or len(recent)),
                          'kwh': played.get('kwh') or round(sum(h.get('kwh') or 0 for h in recent), 3),
                          'cost': played.get('cost') or round(sum(h.get('cost') or 0 for h in recent), 2),
                          'cpu_temp_max': tmax('cpu_temp_max'), 'gpu_temp_max': tmax('gpu_temp_max'),
                          'fps_avg': weighted(played, 'fps_avg'), 'fps_low': weighted(played, 'fps_low'), 'fps_max': played.get('fps_max'),
                          'fps_best': played.get('fps_best'), 'cpu_temp_avg': weighted(played, 'cpu_temp_avg'),
                          'gpu_temp_avg': weighted(played, 'gpu_temp_avg'), 'gpu_avg': weighted(played, 'gpu_avg'),
                          'watts_avg': weighted(played, 'watts_avg')},
                'fps_source': fps_meter.status()['state'],
                'recent': recent[:15], 'profile': self.booster.game_profile(gid)}

    def save_game_profile(self, gid, new):
        with self.lock:
            p = self.booster.set_game_profile(gid, new)
            json_save(CONFIG_FILE, self.config)
        if self.booster.active and (self.booster.running or {}).get('id') == gid:
            self.game_applied = None   # si riapplica al prossimo giro, anche a partita in corso
        return p

    def game_folder(self, gid):
        g = self.booster.find(gid)
        if not g or not Path(g.get('dir') or '').is_dir(): raise ValueError('Cartella del gioco non trovata')
        os.startfile(g['dir'])
        return 'Cartella di ' + g['name'] + ' aperta sul PC'

    def game_verify(self, gid):
        g = self.booster.find(gid)
        m = re.fullmatch(r'steam-(\d{1,10})', str(gid))
        ref = epic_ref(g) if g and not m else None
        if not g or not (m or ref): raise ValueError('Il controllo dei file si fa per i giochi di Steam ed Epic')
        if ref:
            os.startfile(f'com.epicgames.launcher://apps/{ref}?action=verify')
            self.log_event('Epic controlla i file di ' + g['name'])
            return 'Il launcher Epic controlla i file di ' + g['name'] + ': guarda la sua finestra sul PC'
        os.startfile('steam://validate/' + m.group(1))
        self.log_event('Steam controlla i file di ' + g['name'])
        return 'Steam controlla i file di ' + g['name'] + ': guarda la finestra di Steam sul PC'

    def game_cover(self, gid, kind):
        g = self.booster.find(gid)
        return self.covers.path(g, kind) if g else None

    def save_boost_settings(self, new):
        new = dict(new)
        fans, color = new.pop('fans', None), new.pop('rgb_color', None)
        if fans is not None and fans not in ('normal', 'max'): raise ValueError('Ventole in Gaming: normal o max')
        if color is not None and color != '' and not re.fullmatch(r'#[0-9a-fA-F]{6}', str(color)): raise ValueError('Colore non valido')
        with self.lock:
            s = self.booster.update_settings(new)
            if fans is not None: self.config.setdefault('fans', {})['gaming_level'] = fans
            if color is not None: self.config.setdefault('rgb', {})['gaming_color'] = color.lower()
            json_save(CONFIG_FILE, self.config)
        return s

    def begin_telegram_pair(self, token):
        """Call from authenticated loopback UI only; keep ephemeral code in memory."""
        if not isinstance(token, str) or not re.fullmatch(r'[0-9]{6,14}:[A-Za-z0-9_-]{25,}', token):
            raise ValueError('Token del bot non valido. Copialo da @BotFather.')
        from urllib.parse import urlencode
        from urllib.request import Request, urlopen
        from urllib.error import URLError
        url = 'https://api.telegram.org/bot' + token + '/getMe'
        try:
            with urlopen(Request(url, data=b'', method='POST'), timeout=9) as r:
                result=json.loads(r.read(200000))
            if not result.get('ok') or not result.get('result',{}).get('is_bot'):
                raise ValueError('Telegram non ha riconosciuto il bot')
        except (OSError, TimeoutError, ValueError) as ex:
            # Never include URL/token in exception or log messages.
            raise ValueError('Bot non verificabile. Controlla token e connessione Internet.') from None
        code=secrets.token_hex(5).upper()
        with self.lock:
            self.config.setdefault('telegram',{})['token']=token
            self.config['telegram']['allowed_user_id']=0
            self.telegram_pair={'code':code,'until':time.monotonic()+600}
            json_save(CONFIG_FILE,self.config)
            self.log_event('Telegram: token bot verificato; attendo codice di abbinamento')
        return {'code':code,'bot_username':result['result'].get('username',''), 'expires_minutes':10}

    def telegram_pair_pending(self):
        with self.lock:
            p=self.telegram_pair
            return bool(p and time.monotonic()<p['until'] and not self.config.get('telegram',{}).get('allowed_user_id'))

    def accept_telegram_pair(self, incoming, user_id):
        with self.lock:
            p=self.telegram_pair
            if not p or time.monotonic()>=p['until'] or not isinstance(incoming,str):
                return False
            if not hmac.compare_digest(incoming.upper(),p['code']): return False
            if not isinstance(user_id,int) or user_id<=0: return False
            self.config['telegram']['allowed_user_id']=user_id
            self.telegram_pair=None
            json_save(CONFIG_FILE,self.config)
            self.log_event('Telegram: dispositivo personale abbinato correttamente')
            return True

    def mode(self):
        if os.name != 'nt': return 'demo'
        try:
            current = get_guid()
            return next((m for m in ('eco','gaming') if current == self.state.get(m+'_guid')), 'normal')
        except Exception: return 'unknown'

    def ensure_plan(self, mode='eco'):
        """Piano Windows dedicato: AI ECO clona Bilanciato, Gaming clona Prestazioni elevate (o Bilanciato se manca)."""
        guid = self.state.get(mode+'_guid')
        listing = power('/list').lower()
        if valid_guid(guid) and guid in listing: return guid
        source = HIGH_PERFORMANCE if mode == 'gaming' and HIGH_PERFORMANCE in listing else BALANCED
        match = GUID.search(power('/duplicatescheme', source))
        if not match: raise RuntimeError('Impossibile clonare il profilo Windows')
        guid = match.group(0).lower()
        power('/changename', guid, 'PC ECO Control - '+MODES[mode])
        self.state[mode+'_guid'] = guid
        json_save(STATE_FILE, self.state)
        return guid

    def apply_power(self, mode):
        if mode is True or mode is False: mode = 'eco' if mode else 'normal'
        current = get_guid()
        ours = {self.state.get('eco_guid'), self.state.get('gaming_guid')} - {None}
        if mode == 'normal':
            # Se Windows è già fuori dai piani PC ECO, non cambiare il piano scelto a mano dall'utente.
            if current not in ours: return
            guid = self.state.get('normal_guid',BALANCED)
            if not valid_guid(guid) or guid in ours: guid = BALANCED
            power('/setactive',guid)
            return
        guid = self.ensure_plan(mode)
        if current not in ours:
            self.state['normal_guid'] = current
            json_save(STATE_FILE, self.state)
        if mode == 'eco':
            max_cpu = int(self.config.get('eco_cpu_max_percent',90))
            timeout = int(self.config.get('monitor_timeout_seconds',60))
            if not 50 <= max_cpu <= 100 or not 30 <= timeout <= 3600:
                raise ValueError('Impostazioni CPU / monitor fuori intervallo')
            min_cpu, parking = 5, None
        else:
            # Gaming: CPU sempre pronta (nessun limite, core non parcheggiati) e monitor mai spento.
            max_cpu, min_cpu, timeout, parking = 100, 100, 0, 100
        power('/setacvalueindex', guid, 'SUB_PROCESSOR', 'PROCTHROTTLEMAX',max_cpu)
        power('/setacvalueindex', guid, 'SUB_PROCESSOR', 'PROCTHROTTLEMIN',min_cpu)
        if parking is not None:
            try: power('/setacvalueindex', guid, 'SUB_PROCESSOR', 'CPMINCORES',parking)
            except RuntimeError: pass  # impostazione nascosta su alcuni PC
        # Risparmio vero in AI ECO (turbo spento, PCIe/USB/Wi-Fi a risparmio, dischi meccanici fermi dopo 10 min);
        # in Gaming il contrario. Alcune voci mancano su certi PC: si saltano.
        for sub, setting, value in (self.eco_power_extra() if mode == 'eco' else GAMING_EXTRA):
            try: power('/setacvalueindex', guid, sub, setting, value)
            except RuntimeError: pass
        power('/setacvalueindex', guid, 'SUB_VIDEO', 'VIDEOIDLE',timeout)
        power('/setacvalueindex', guid, 'SUB_SLEEP', 'STANDBYIDLE',0)
        power('/setacvalueindex', guid, 'SUB_SLEEP', 'HIBERNATEIDLE',0)
        power('/setactive',guid)

    CONN_RETRY = 120   # secondi fra due tentativi sullo stesso collegamento

    def fans_key_now(self):
        """Il profilo NEXAR che Fan Control dovrebbe avere caricato adesso (livello scelto o regolazione a mano)."""
        import discovery
        level = self.state.get('fans_level') or 'normal'
        if self.state.get('fans_custom') and self.state.get('fans_slot') in discovery.FAN_MANUAL: return self.state['fans_slot']
        if level == 'off': return 'off_pump' if self.state.get('fans_pump') else 'off'
        return level if level in discovery.FAN_TASKS else 'normal'

    def fans_task_now(self):
        """L'attività di Fan Control che rimette le ventole come le avevi lasciate."""
        import discovery
        return discovery.FAN_TASKS[self.fans_key_now()]

    def fans_keep(self):
        """Controllo automatico (ogni 2 minuti): se Fan Control ha caricato un profilo NEXAR diverso da quello scelto,
        glielo rimanda. Un profilo dell'utente (non PCECO-) non si tocca."""
        import discovery
        cfg = self.config.get('fans', {})
        exe = cfg.get('fancontrol_exe', '')
        if not cfg.get('enabled') or not exe or windows_shutting_down(): return ''
        if time.monotonic() - self.fan_sent[0] < 60: return ''  # appena mandato: lo sta caricando
        key = self.fans_key_now()
        want, loaded = discovery.FAN_FILES[key], discovery.fancontrol_config_loaded(exe)
        if not loaded.startswith('PCECO-') or loaded == want or not discovery.fancontrol_running(): return ''
        if not discovery.task_exists(discovery.FAN_TASKS[key]): return ''
        self.fan_send(key)
        msg = f'Ventole: Fan Control aveva {loaded}, rimesso {want}'
        self.log_event(msg)
        return msg

    def fans_check(self, repair=True, wait=15, sleep=time.sleep):
        """Pulsante "Controlla ventole": verifica Fan Control, profili, attività e profilo caricato; ripara ciò che
        si può senza conferme (rimanda il profilo). Se i profili vanno rifatti lo dice (serve una conferma UAC)."""
        import discovery
        cfg = self.config.get('fans', {})
        exe = cfg.get('fancontrol_exe', '')
        items = []
        def add(ok, text): items.append({'ok': ok if ok is None else bool(ok), 'text': text})
        if not cfg.get('enabled') or not exe or not Path(exe).is_file():
            add(False, 'Fan Control non collegato: collegalo dalla pagina Collegamenti')
            return {'items': items, 'setup': False, 'message': 'Fan Control non collegato'}
        running = discovery.fancontrol_running()
        add(running, 'Fan Control acceso' + (' (servizio)' if discovery.process_running('FanControl.Service.exe') else '') if running
            else 'Fan Control spento: lo riavvio con il profilo scelto')
        folder = discovery.fancontrol_config_dir(exe)
        files = [k for k, f in discovery.FAN_FILES.items() if not any((d / f).is_file() for d in discovery.fancontrol_dirs(exe))]
        tasks = [k for k, t in discovery.FAN_TASKS.items() if not discovery.task_exists(t)]
        self.fans_ready_cache = (0.0, False)
        outdated = self.fans_profiles_outdated()
        setup = bool(files or tasks or outdated)
        add(not setup, f'Profili NEXAR in {folder}' if not setup else
            'Profili da rifare' + (f' (mancano {len(files)} file)' if files else '') + (f' (mancano {len(tasks)} attività)' if tasks else '') +
            (' (versione vecchia)' if outdated and not files and not tasks else '') + ': premi "Rifai profili" (una conferma)')
        key = self.fans_key_now()
        want = discovery.FAN_FILES[key]
        loaded = discovery.fancontrol_config_loaded(exe)
        fixed = ''
        if repair and (loaded != want or not running) and key not in tasks and (want not in [discovery.FAN_FILES[k] for k in files]):
            try:
                self.fan_send(key, sleep=sleep)
                for _ in range(wait):
                    sleep(1)
                    loaded = discovery.fancontrol_config_loaded(exe)
                    if loaded == want: break
                fixed = 'rimandato'
            except RuntimeError as ex: add(False, str(ex))
        name = FAN_LEVEL_NAMES.get(self.state.get('fans_level') or 'normal', '')
        if self.fan_sent[1]: add(None, f'Ultimo profilo mandato da NEXAR: {self.fan_sent[1]} alle {getattr(self, "fan_sent_at", "?")}')
        if loaded == want: add(True, f'Profilo caricato: {want} ({name})' + (' · rimesso adesso' if fixed else ''))
        elif loaded: add(False, f'Fan Control ha {loaded}, NEXAR vuole {want}' + (': rimandato ma non caricato. Apri Fan Control e controlla che non mostri errori' if fixed else ''))
        else: add(None, 'Profilo caricato non leggibile (Fan Control senza file CACHE)')
        duty = [f for f in collect_sensors(self.config.get('sensors', {}).get('libre_hardware_monitor', '')).get('fans') or [] if f.get('rpm', 0) > 0]
        add(bool(duty), f'{len(duty)} ventole in movimento' if duty else 'Nessuna ventola in movimento adesso')
        bad = [i for i in items if i['ok'] is False]
        msg = 'Ventole a posto' if not bad else bad[0]['text']
        self.log_event('Controllo ventole: ' + msg)
        return {'items': items, 'setup': setup, 'message': msg}

    def connections_check(self, tries, age, now=None):
        """Sensori, Fan Control e OpenRGB devono funzionare senza premere "Collega".
        All'accensione partono prima che la rete sia pronta: il server dei sensori resta spento e va riavviato.
        Restituisce lo stato di ognuno (True = collegato)."""
        import discovery
        now = time.monotonic() if now is None else now
        def due(k): return now - tries.get(k, -1e9) >= self.CONN_RETRY
        state = {}
        if discovery.find_lhm():
            ok = discovery.sensors_online()
            if not ok and age >= 45 and due('sensors') and discovery.task_exists(discovery.LHM_TASK):
                tries['sensors'] = now
                discovery.lhm_enable_webserver(discovery.find_lhm())
                discovery.task_restart(discovery.LHM_TASK)
                logging.info('Collegamenti: sensori riavviati')
            state['sensors'] = ok
        fans = self.config.get('fans', {})
        if fans.get('enabled') and Path(fans.get('fancontrol_exe', '')).is_file():
            # Prima guardava solo la finestra FanControl.exe: col servizio di Fan Control 285 la finestra è chiusa,
            # NEXAR lo credeva spento e ogni 2 minuti ricaricava il profilo (le regolazioni a mano saltavano).
            ok = discovery.fancontrol_running()
            if ok:
                try: self.fans_keep()
                except Exception: logging.exception('Controllo profilo ventole')
            task = self.fans_task_now()
            if not ok and due('fans') and discovery.task_exists(task) and not windows_shutting_down():
                tries['fans'] = now
                cmd(['schtasks', '/run', '/tn', task], 15)
                logging.info('Collegamenti: Fan Control avviato (%s)', task)
            state['fans'] = ok
        rgb = self.config.get('rgb', {})
        if rgb.get('enabled') and rgb.get('openrgb_exe'):
            ok = discovery.port_open(discovery.OPENRGB_PORT)
            if not ok and age >= 20 and due('rgb') and discovery.task_exists(discovery.OPENRGB_TASK) \
                    and discovery.openrgb_service().get('status') not in ('running', 'start_pending'):
                tries['rgb'] = now
                discovery.task_restart(discovery.OPENRGB_TASK)
                logging.info('Collegamenti: OpenRGB riavviato')
            state['rgb'] = ok
        if self.config.get('conflicts', {}).get('auto_close', True) and not windows_shutting_down():
            try:
                if discovery.conflicts_running(): self.apps_close(auto=True)
            except Exception: logging.exception('Chiusura delle app in conflitto')
        self.refresh_integrations(state)
        return state

    # ---------- altre app che comandano ventole e luci ----------
    def apps_close(self, keys=None, auto=False):
        """Chiude le app in conflitto (tutte, o quelle scelte). Quelle avviate come amministratore le chiude
        NEXAR Admin. Restituisce il messaggio per l'utente."""
        import discovery, psutil
        running = discovery.conflicts_running()
        keys = [k for k in (keys if keys is not None else list(running)) if k in running]
        if not keys: return 'Nessuna app in conflitto aperta'
        closed, denied = [], []
        for k in keys:
            ok = True
            for pid in running[k]:
                try: psutil.Process(pid).kill()
                except psutil.NoSuchProcess: pass
                except (psutil.AccessDenied, OSError): ok = False
            (closed if ok else denied).append(k)
        why = ''
        if denied:
            if self.admin.active() and self.admin.current():
                try: self.admin.call('close_apps', keys=denied); closed += denied; denied = []
                except RuntimeError as ex: why = str(ex)
            else: why = 'avviate come amministratore: premi "Sistema" nella pagina Luci (una conferma)'
        self.apps_cache = (0.0, None)
        label = lambda ks: ', '.join(discovery.app_label(k)[0] for k in ks)
        if closed:
            now, at = datetime.now().strftime('%H:%M'), time.monotonic()
            with self.lock:
                seen = self.state.setdefault('apps_closed', {})
                for k in closed: seen[k] = now
                json_save(STATE_FILE, self.state)
            logged = getattr(self, 'apps_logged', {})
            fresh = [k for k in closed if not auto or at - logged.get(k, -1e9) > 1800]
            for k in closed: logged[k] = at
            self.apps_logged = logged
            if fresh: self.log_event('Chiuse perché comandavano ventole o luci insieme a NEXAR: ' + label(fresh))
        if denied:
            if not auto: raise RuntimeError(f'Non chiuse: {label(denied)} ({why})')
            if time.monotonic() - getattr(self, 'apps_warned', -1e9) > 1800:  # controllo ogni minuto: avviso ogni mezz'ora
                self.apps_warned = time.monotonic()
                logging.warning('App in conflitto non chiuse (%s): %s', label(denied), why)
        return 'Chiuse: ' + label(closed)

    def apps_fix_needed(self):
        """Una conferma da amministratore sistema tutto: Fan Control nascosto, OpenRGB in una copia sola, NEXAR Admin aggiornato."""
        import discovery
        at, need = getattr(self, 'apps_fix_cache', (0.0, None))
        if need is None or time.monotonic() - at > 60:
            need = []
            if self.fans_tasks_outdated(): need.append('fans')
            if discovery.openrgb_service() and discovery.task_exists(discovery.OPENRGB_TASK): need.append('openrgb')
            if self.admin.active() and not self.admin.current(): need.append('admin')
            self.apps_fix_cache = (time.monotonic(), need)
        return need

    def fans_tasks_outdated(self):
        import discovery
        cfg = self.config.get('fans', {})
        return bool(cfg.get('enabled')) and int(cfg.get('tasks_version', 1)) < discovery.FAN_TASKS_VERSION

    def apps_fix_script(self):
        """Il pezzo da amministratore che va insieme ai profili ventole: OpenRGB in una copia sola e NEXAR Admin aggiornato."""
        import discovery
        return discovery.openrgb_fix_script() + (self.admin_script() if self.admin.active() else '')

    def apps_fix(self):
        """Pulsante "Sistema": una sola conferma UAC sul PC."""
        import discovery
        fans = self.config.get('fans', {})
        if fans.get('enabled') and (fans.get('fancontrol_exe') or discovery.find_fancontrol()):
            msg = self.setup_fans()
        else:
            script = self.apps_fix_script()
            if script and not discovery.run_elevated(script, wait=True): raise RuntimeError('Conferma da amministratore annullata')
            msg = 'OpenRGB sistemato'
        self.apps_fix_cache = (0.0, None)
        try: self.apps_close(auto=True)
        except Exception: logging.exception('Chiusura delle app in conflitto')
        return msg

    def apps_info(self):
        """Per la dashboard (cache 10 s: la chiede ogni 4 s)."""
        import discovery
        at, info = getattr(self, 'apps_cache', (0.0, None))
        if info is None or time.monotonic() - at > 10:
            running = discovery.conflicts_running()
            closed = self.state.get('apps_closed') or {}
            rows = []
            for k in dict.fromkeys([*running, *closed]):
                name, what = discovery.app_label(k)
                rows.append({'key': k, 'name': name, 'what': what, 'running': k in running, 'closed_at': closed.get(k, '')})
            svc = discovery.openrgb_service()
            info = {'apps': rows, 'openrgb_service': svc.get('status', ''),
                    'msi_center': discovery.process_running('LEDKeeper2.exe') or discovery.process_running('MSI.CentralServer.exe')}
            self.apps_cache = (time.monotonic(), info)
        return dict(info, auto_close=bool(self.config.get('conflicts', {}).get('auto_close', True)), fix=self.apps_fix_needed(),
                    admin=self.admin.active())

    def set_apps_auto(self, on):
        with self.lock:
            self.config.setdefault('conflicts', {})['auto_close'] = bool(on); json_save(CONFIG_FILE, self.config)
        return 'Chiusura automatica ' + ('attiva' if on else 'spenta')

    CONN_OK = {'sensors': 'Temperature e RPM collegati', 'rgb': 'Server RGB collegato', 'fans': None}

    def refresh_integrations(self, online):
        """La pagina Collegamenti segue lo stato vero: niente "Avvio in corso…" rimasto lì dall'accensione."""
        with self.lock:
            out = []
            for it in self.integrations or []:
                it = dict(it); k = it.get('key')
                if k in online and online[k] and it.get('level') == 'warn' and self.CONN_OK.get(k):
                    it.update(level='ok', detail=self.CONN_OK[k])
                elif k == 'sensors' and k in online and not online[k] and it.get('level') == 'ok':
                    it.update(level='warn', detail='Sensori non raggiungibili: li riavvio da solo')
                out.append(it)
            self.integrations = out

    def connections_loop(self, stop_event):
        """Ogni 15 s nei primi 10 minuti (l'accensione), poi ogni minuto."""
        t0, tries = time.monotonic(), {}
        while not stop_event.wait(15 if time.monotonic() - t0 < 600 else 60):
            try: self.connections_check(tries, time.monotonic() - t0)
            except Exception: logging.exception('Collegamenti automatici')

    def boot_report(self, notify, webapp=lambda: True, stop_event=None, wait=180, step=10):
        """Dopo l'accensione: aspetta che tutto sia collegato (massimo 3 minuti) e lo dice su Telegram."""
        import discovery
        names = {'sensors': 'sensori', 'fans': 'ventole', 'rgb': 'luci'}
        t0 = time.monotonic(); state = {}
        while True:
            try: state = self.connections_state()
            except Exception: state = {}
            if (all(state.values()) and webapp()) or time.monotonic() - t0 >= wait: break
            if (stop_event.wait(step) if stop_event else time.sleep(step)): return None
        good = [names[k] for k, v in state.items() if v]
        bad = [names[k] for k, v in state.items() if not v]
        msg = '🟢 PC acceso. NEXAR è attivo' + (' · collegati: ' + ', '.join(good) if good else '')
        if bad: msg += ' · ⚠️ non ancora pronti: ' + ', '.join(bad) + ' (riprovo da solo)'
        notify(msg)
        return msg

    def connections_state(self):
        """Solo lettura: cosa risponde adesso."""
        import discovery
        st = {}
        if discovery.find_lhm(): st['sensors'] = discovery.sensors_online()
        fans = self.config.get('fans', {})
        if fans.get('enabled') and Path(fans.get('fancontrol_exe', '')).is_file(): st['fans'] = discovery.fancontrol_running()
        rgb = self.config.get('rgb', {})
        if rgb.get('enabled') and rgb.get('openrgb_exe'): st['rgb'] = discovery.port_open(discovery.OPENRGB_PORT)
        return st

    def discover(self, allow_uac=False):
        """Ricerca automatica di OpenRGB, Fan Control, sensori e GPU; salva i percorsi trovati."""
        import discovery
        if not self.discover_lock.acquire(blocking=False): return self.integrations
        try:
            with self.lock:
                config = json.loads(json.dumps(self.config))
                state = dict(self.state)
            report = discovery.autoconfigure(config, state, allow_uac)
            inventory = discovery.hardware_inventory()
            if config.get('rgb', {}).get('enabled') and discovery.port_open(discovery.OPENRGB_PORT):
                try: self.count_leds()
                except Exception as ex: logging.info('Conteggio LED: %s', ex)
            with self.lock:
                for section in ('rgb', 'fans', 'sensors', 'auto_detect'):
                    self.config[section] = config.get(section, {})
                self.state.update({k: v for k, v in state.items() if k != 'rgb_leds'})  # appena contati sopra
                if inventory: self.state['inventory'] = inventory
                # Nomi dei componenti rilevati da Windows: riempiono solo i campi vuoti, quelli scritti a mano restano.
                hw = self.config.setdefault('hardware', {})
                for k, v in (inventory or {}).get('hardware', {}).items():
                    if v and not hw.get(k): hw[k] = v
                json_save(CONFIG_FILE, self.config)
                json_save(STATE_FILE, self.state)
                self.integrations = report
                self.cached_telemetry = None
            missing = [r['name'] for r in report if r['level'] != 'ok']
            self.log_event('Collegamenti verificati' + (': da completare ' + ', '.join(missing) if missing else ': tutto collegato'))
            return report
        finally:
            self.discover_lock.release()

    def rgb_profile(self, eco, by='user'):
        """by: 'user' (pulsante, bot, programmazione) o 'mode' (AI ECO). Cambiando modalità si riaccendono
        solo i LED spenti da ECO: quelli spenti a mano restano spenti."""
        cfg = self.config.get('rgb',{})
        exe = Path(cfg.get('openrgb_exe',''))
        if not cfg.get('enabled') or not exe.is_file(): return 'RGB: OpenRGB non trovato'
        eco_p, normal_p = cfg.get('eco_profile',''), cfg.get('normal_profile','')
        if eco_p and normal_p:
            profile = Path(eco_p if eco else normal_p)
            if not profile.is_file() or profile.suffix.lower() != '.orp':
                raise RuntimeError('OpenRGB: profilo .orp non trovato')
            cmd([str(exe), '--profile', str(profile)], 90)
            return 'RGB: profilo '+('AI ECO' if eco else 'Normale')+' applicato'
        if not eco and not self.state.get('rgb_saved'): return 'RGB: già acceso'
        self.rgb_user_at = time.monotonic()
        with self.lock:
            # Stato voluto fissato subito: anche se il guardiano dei LED scatta adesso, sa che vanno spenti.
            saved = self.state.get('rgb_saved') if self.state.get('rgb_off') else None
            if eco: self.state.update(rgb_off=True, rgb_off_by=by); json_save(STATE_FILE, self.state)
        stamp = self.rgb_user_at
        def run():
            import openrgb_sdk
            try:
                with self.rgb_lock:
                    self.openrgb_ready()
                    if eco:
                        snaps, done = openrgb_sdk.all_off(saved, exclude=self.rgb_excluded())
                        with self.lock:
                            if self.state.get('rgb_off'): self.state['rgb_saved'] = snaps; json_save(STATE_FILE, self.state)
                    else:
                        done = openrgb_sdk.all_restore(self.state.get('rgb_saved') or {}, cfg.get('normal_color', '#ffffff'), self.rgb_excluded())
                        with self.lock:
                            self.state.update(rgb_off=False); self.state.pop('rgb_saved', None); self.state.pop('rgb_off_by', None)
                            json_save(STATE_FILE, self.state)
                self.log_event('RGB ' + ('spenti' if eco else 'riaccesi') + ': ' + (', '.join(done) or 'nessun dispositivo'))
                if eco: self.rgb_settle(stamp)
            except Exception as ex:
                self.log_event('OpenRGB non raggiungibile: ' + str(ex)[:200])
        # Il primo avvio del server richiede qualche secondo: non bloccare la finestra.
        threading.Thread(target=run, daemon=True, name='openrgb').start()
        return 'RGB: ' + ('spegnimento LED' if eco else 'riaccensione LED') + ' in corso'

    def rgb_settle(self, stamp, sleep=time.sleep):
        """Subito dopo lo spegnimento qualcuno può rimettere il suo effetto (MSI Center sincronizza la RAM, firmware
        che riparte): i LED vengono rimessi spenti qualche volta nei secondi successivi. Si ferma se l'utente
        nel frattempo ha dato un altro comando o li ha riaccesi."""
        import openrgb_sdk
        waited = 0
        for at in RGB_OFF_SETTLE:
            sleep(at - waited); waited = at
            with self.rgb_lock:
                if self.rgb_user_at != stamp or not self.state.get('rgb_off'): return
                snaps, _ = openrgb_sdk.all_off(self.state.get('rgb_saved'), exclude=self.rgb_excluded())
                with self.lock:
                    if self.state.get('rgb_off'): self.state['rgb_saved'] = snaps; json_save(STATE_FILE, self.state)

    def msi_lights_restore(self):
        """La 1.0.68 poteva mettere in pausa le luci di MSI Center per spegnere l'ARCTIC. Provato sul PC: alla ripresa
        il driver di MSI a volte resta bloccato per minuti, quindi la funzione è stata tolta. Chi l'aveva attivata
        ritrova MSI Center acceso, con l'attività "Luci MSI riprendi" già creata allora (nessuna richiesta UAC)."""
        import discovery
        if discovery.msi_lights_ready() and discovery.msi_lights_run('resume'):
            self.log_event('Luci MSI: MSI Center rimesso in funzione, l\'ARCTIC torna al suo effetto')
        with self.lock:
            self.state.pop('rgb_msi_paused', None); self.config.get('rgb', {}).pop('msi_off', None)
            json_save(STATE_FILE, self.state); json_save(CONFIG_FILE, self.config)

    def openrgb_ready(self):
        """Il server OpenRGB tiene vivi i dispositivi (es. Corsair Lighting Node) dopo il comando."""
        import discovery
        if discovery.port_open(discovery.OPENRGB_PORT): return
        exe = self.config.get('rgb', {}).get('openrgb_exe', '')
        if not exe or not Path(exe).is_file(): raise RuntimeError('OpenRGB non trovato')
        discovery.openrgb_start(exe, allow_uac=False)
        for _ in range(30):
            if discovery.port_open(discovery.OPENRGB_PORT): break
            time.sleep(1)
        else: raise RuntimeError('Server OpenRGB non avviato: premi "Collega" nella pagina Collegamenti')
        time.sleep(3)  # rilevamento dispositivi

    def rgb_excluded(self):
        """Controller lasciati al firmware: OpenRGB 1.1 spegne la MSI MS-7E62 ma non le ridà colore."""
        return tuple(self.config.get('rgb', {}).get('exclude', []))

    def rgb_palette(self):
        return list(self.config.get('rgb', {}).get('palette') or DEFAULT_PALETTE)

    def set_rgb_palette(self, colors):
        """Colori salvati dall'utente (al massimo 18), mostrati nella dashboard e nel bot."""
        if not isinstance(colors, list) or len(colors) > 18 or not all(isinstance(c, str) and re.fullmatch(r'#[0-9a-fA-F]{6}', c) for c in colors):
            raise ValueError('Palette: fino a 18 colori #RRGGBB')
        colors = list(dict.fromkeys(c.lower() for c in colors))
        with self.lock:
            self.config.setdefault('rgb', {})['palette'] = colors
            json_save(CONFIG_FILE, self.config)
        return colors

    def rgb_devices(self):
        import openrgb_sdk
        self.openrgb_ready()
        colors = self.config.get('rgb', {}).get('device_colors', {})
        with openrgb_sdk.Client() as c:
            allc = c.controllers()
        ctls = [(k, x) for k, x in zip(openrgb_sdk.keys(allc), allc) if x['name'] not in self.rgb_excluded()]
        self.store_leds([x for _, x in ctls])
        return [{'key': k, 'name': x['name'], 'type': x['type'], 'leds': leds_estimate(x),
                 'color': openrgb_sdk.lookup(colors, k, x) or ''} for k, x in ctls]

    def count_leds(self):
        import openrgb_sdk
        with openrgb_sdk.Client() as c: self.store_leds(c.controllers())

    def store_leds(self, ctls):
        """LED alimentati dal PC: servono alla stima del consumo dell'illuminazione."""
        total = sum(leds_estimate(x) for x in ctls)
        with self.lock:
            if total and self.state.get('rgb_leds') != total:
                self.state['rgb_leds'] = total; json_save(STATE_FILE, self.state)

    def rgb_color(self, color, brightness=100, device=None, remember=True, quiet=False):
        with self.rgb_lock:
            if not quiet: self.rgb_user_at = time.monotonic()
            return self._rgb_color(color, brightness, device, remember, quiet)

    def _rgb_color(self, color, brightness, device, remember, quiet):
        """Un colore per tutti i dispositivi (device=None) o per uno solo; luminosità 0-100%."""
        import openrgb_sdk
        if not isinstance(color, str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', color): raise ValueError('Colore non valido')
        if type(brightness) is not int or not 0 <= brightness <= 100: raise ValueError('Luminosità 0–100')
        scaled = '#' + ''.join(f'{round(int(color[i:i+2], 16) * brightness / 100):02x}' for i in (1, 3, 5))
        self.openrgb_ready()
        done = []
        with openrgb_sdk.Client() as c:
            allc = c.controllers()
            for k, x in zip(openrgb_sdk.keys(allc), allc):
                if (device and device not in (k, openrgb_sdk.legacy_key(x))) or x['name'] in self.rgb_excluded(): continue
                if openrgb_sdk.leds_set(c, x, openrgb_sdk.color(scaled), allow_off_mode=False):
                    done.append(x['name']); hit = (k, x['name'], sum(y['name'] == x['name'] for y in allc) == 1, openrgb_sdk.legacy_key(x))
            c.controllers()
        if not done: raise RuntimeError('Nessun dispositivo accetta un colore fisso')
        with self.lock:
            rgb = self.config.setdefault('rgb', {})
            if remember:   # i colori temporanei (Gaming) non diventano il colore normale
                rgb['brightness'] = brightness
                if device:   # salvato con la chiave stabile; quella vecchia "indice:nome" sparisce
                    dc = rgb.setdefault('device_colors', {})
                    for d in [d for d in dc if d == hit[3] or (hit[2] and d.partition(':')[0].isdigit() and d.partition(':')[2] == hit[1])]:
                        dc.pop(d)
                    dc[hit[0]] = color
                else: rgb.update(normal_color=color, device_colors={})
                json_save(CONFIG_FILE, self.config)
                self.state.pop('rgb_gaming', None)
            # I LED sono di nuovo accesi con colori scelti: il prossimo ECO salverà questi.
            # Il guardiano (quiet) rimette solo i colori: non cambia mai lo stato acceso/spento.
            if not quiet:
                self.state.update(rgb_off=False); self.state.pop('rgb_saved', None); self.state.pop('rgb_off_by', None)
                json_save(STATE_FILE, self.state)
        msg = 'Colore ' + color.upper() + f' ({brightness}%) su ' + ', '.join(dict.fromkeys(done))
        if not quiet: self.log_event('RGB: ' + msg)
        return msg

    def rgb_watch(self, stop_event):
        """Ogni 3 s: se MSI Center ha appena riacceso le luci (schermo riacceso, avvio, sospensione) NEXAR le rimette
        come le aveva lasciate. Controlla solo la dimensione del registro di MSI: non costa nulla."""
        wall = time.time()
        while not stop_event.wait(3):
            # Un salto dell'orologio oltre 60 s vuol dire che il PC era in sospensione.
            resumed = time.time() - wall > 60; wall = time.time()
            try: self.rgb_keep(resumed)
            except Exception as ex: logging.info('LED: stato non rimesso (%s)', ex)

    def msi_light_reset(self):
        """True se Mystic Light ha riapplicato i suoi effetti dall'ultima volta (righe "ResetItem" nuove nel suo registro)."""
        try: size = MSI_LIGHT_LOG.stat().st_size
        except OSError: return False
        last, self.msi_log_pos = self.msi_log_pos, size
        if last is None or size == last: return False
        if size < last: return True  # registro ricominciato da capo
        try:
            with open(MSI_LIGHT_LOG, 'rb') as f:
                f.seek(max(last, size - 262144)); return b'ResetItem' in f.read()
        except OSError: return False

    def rgb_keep(self, resumed=False):
        """MSI Center (sincronizzazione Mystic Light) rimette i suoi effetti sulla RAM all'avvio, quando lo schermo
        si riaccende e dopo la sospensione: NEXAR rimette il suo stato (spenti, oppure i colori scelti)."""
        if self.state.get('rgb_msi_paused') or self.config.get('rgb', {}).get('msi_off'): self.msi_lights_restore()
        rgb = self.config.get('rgb', {})
        if not rgb.get('enabled') or (rgb.get('eco_profile') and rgb.get('normal_profile')): return ''
        import discovery
        now = time.monotonic()
        if now - self.rgb_user_at < RGB_QUIET_AFTER_USER: return ''  # comando appena dato: lo gestisce lui
        every = RGB_KEEP_OFF_EVERY if self.state.get('rgb_off') else RGB_KEEP_EVERY
        try: changed = MSI_LIGHT_LOG.stat().st_size != self.msi_log_pos
        except OSError: changed = False
        if not (changed or resumed or now - self.rgb_kept_at >= every): return ''
        if not discovery.port_open(discovery.OPENRGB_PORT): return ''
        if not self.rgb_lock.acquire(blocking=False): return ''  # un comando LED è in corso
        try:
            if now - self.rgb_user_at < RGB_QUIET_AFTER_USER: return ''
            reset = self.msi_light_reset()
            if not (reset or resumed or now - self.rgb_kept_at >= every): return ''
            self.rgb_kept_at = now
            return self._rgb_keep(rgb, reset, resumed)
        finally: self.rgb_lock.release()

    def _rgb_keep(self, rgb, reset, resumed):
        import openrgb_sdk
        why = 'MSI Center ha rimesso i suoi effetti' if reset else ('uscita dalla sospensione' if resumed else '')
        if self.state.get('rgb_off'):
            snaps, done = openrgb_sdk.all_off(self.state.get('rgb_saved'), exclude=self.rgb_excluded())
            with self.lock:
                if self.state.get('rgb_off'): self.state['rgb_saved'] = snaps; json_save(STATE_FILE, self.state)
            msg = 'LED rimessi spenti: ' + ', '.join(done)
        elif rgb.get('normal_color') and not self.state.get('rgb_gaming') and not self.state.get('rgb_saved'):
            bright = int(rgb.get('brightness', 100))
            msg = self.rgb_color(rgb['normal_color'], bright, remember=False, quiet=True)
            for dev, c in (rgb.get('device_colors') or {}).items():
                try: self.rgb_color(c, bright, dev, remember=False, quiet=True)
                except Exception: pass
        else: return ''
        if why: self.log_event(f'RGB ({why}): {msg}')
        return msg

    def fans_profile(self, eco):
        return self.fans_level('eco' if eco else 'normal')

    def fans_profiles_outdated(self):
        """Profili creati da una versione precedente (es. Massimo solo sulle ventole del case): vanno rigenerati."""
        import discovery
        return int(self.config.get('fans',{}).get('profiles_version',1)) < discovery.FAN_PROFILES_VERSION

    def fans_levels_ready(self):
        """Profili Spente/Massimo presenti: dopo l'aggiornamento serve un nuovo "Configura" (una conferma UAC)."""
        import discovery
        at, ready = getattr(self, 'fans_ready_cache', (0.0, False))
        if time.monotonic() - at > 60:  # schtasks è lento: la dashboard chiede lo stato ogni 4 secondi
            ready = all(discovery.task_exists(discovery.FAN_TASKS[k]) for k in ('off', 'off_pump', 'max'))
            self.fans_ready_cache = (time.monotonic(), ready)
        return ready

    def fans_level(self, level, keep_pump=None):
        """off (tutte ferme, pompa al minimo se keep_pump), eco (case più lente), normal (BIOS) o max (tutte al 100%)."""
        import discovery
        if level not in FAN_LEVEL_NAMES: raise ValueError('Livello ventole non valido')
        cfg = self.config.get('fans',{})
        if not cfg.get('enabled'): return 'Ventole: gestione automatica BIOS (AIO protetto)'
        if level == 'off':
            if keep_pump is None: keep_pump = bool(cfg.get('keep_pump', True))
            elif bool(keep_pump) != cfg.get('keep_pump'):
                with self.lock: self.config.setdefault('fans',{})['keep_pump'] = bool(keep_pump); json_save(CONFIG_FILE, self.config)
        profile = 'off_pump' if level == 'off' and keep_pump else level
        exe = Path(cfg.get('fancontrol_exe',''))
        name = cfg.get(level+'_profile') if level in ('eco','normal') else discovery.FAN_FILES[profile]
        if not exe.is_file() or not isinstance(name,str) or not name or Path(name).name != name or not name.lower().endswith('.json'):
            raise RuntimeError('Fan Control: eseguibile o profilo non valido')
        task = discovery.FAN_TASKS[profile]
        if profile in ('off','off_pump','max') and (not discovery.task_exists(task) or self.fans_profiles_outdated()):
            raise RuntimeError('Profilo "'+FAN_LEVEL_NAMES[level]+'" da aggiornare: sul PC premi "Aggiorna profili" nella pagina Ventole')
        if not any((d / name).is_file() for d in discovery.fancontrol_dirs(str(exe))):
            raise RuntimeError('Fan Control: profilo '+name+' assente')
        if name == discovery.FAN_FILES[profile] and discovery.task_exists(task):
            # Fan Control gira come amministratore: lo raggiungiamo con l'attività già autorizzata.
            self.fan_send(profile)
            with self.lock:
                # Un livello scelto azzera le regolazioni fatte a mano sulle singole ventole.
                self.state.update(fans_level=level, fans_pump=bool(level == 'off' and keep_pump), fans_eco=level in ('eco','off'), fans_custom={})
                self.state.pop('fans_preset', None); self.state.pop('fans_mine', None)
                json_save(STATE_FILE, self.state)
            detail = {'normal': ' (BIOS)', 'max': ' (tutte: case, radiatore, pompa e scheda video al 100%)',
                      'off': ' (tutte ferme' + (f', pompa e radiatore AIO al {discovery.PUMP_MIN_PERCENT}%' if keep_pump else ', anche la pompa') +
                             '; tornano normali da sole se CPU o GPU arrivano a 75 °C)',
                      'eco': ' (solo case, radiatore e pompa al BIOS)'}
            return 'Ventole: ' + FAN_LEVEL_NAMES[level] + detail[level]
        opts = dict(cwd=str(exe.parent), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if os.name == 'nt': opts['creationflags'] = subprocess.CREATE_NO_WINDOW
        subprocess.Popen([str(exe),'-c',name,'-m'],**opts)
        return 'Ventole: richiesto profilo '+name+' (AIO escluso nei profili utente)'

    def fan_rows(self, fans):
        """Ventole con nome chiaro (o quello dato dall'utente) e quali mostrare: quelle che hanno girato almeno
        una volta restano in elenco anche da ferme (Spente, GPU a 0 RPM al minimo); i connettori vuoti no."""
        seen = set(self.state.get('fans_seen') or [])
        new = {f.get('ctl') or f['name'] for f in fans if f.get('rpm', 0) > 0} - seen
        if new:
            seen |= new
            with self.lock: self.state['fans_seen'] = sorted(seen); json_save(STATE_FILE, self.state)
        names = self.config.get('fans', {}).get('names') or {}
        custom = self.state.get('fans_custom') or {}
        cooler = str(self.config.get('hardware', {}).get('cooler', '')).lower()
        aio = any(w in cooler for w in ('liquid', 'aio', 'water', 'kraken', 'h100', 'h115', 'h150', 'lf ii', 'lf iii'))
        pump_used = any('pump' in f['name'].lower() and (f.get('ctl') or f['name']) in seen for f in fans)
        out = []
        for f in fans:
            key, low = f.get('ctl') or f['name'], f['name'].lower()
            num = re.search(r'#?\s*(\d+)\s*$', f['name'])
            if 'pump' in low: kind, label = 'pump', 'Pompa AIO'
            elif re.match(r'cpu\s*(opt\s*)?fan', low):
                kind = 'aio' if aio and not pump_used else 'cpu'
                label = 'Radiatore AIO + pompa' if kind == 'aio' else ('Radiatore AIO' if aio else 'Ventola CPU')
            elif low.startswith('system fan'): kind, label = 'case', 'Ventola case ' + (num.group(1) if num else '')
            elif 'gpu' in low or '/gpu' in key or 'nvapi' in key.lower(): kind, label = 'gpu', 'Scheda video · ventola ' + (num.group(1) if num else '')
            elif 'chipset' in low: kind, label = 'chipset', 'Ventola chipset'
            elif 'ez' in low and 'connect' in low: kind, label = 'other', 'EZ Conn (connettore extra)'
            else: kind, label = 'other', f['name']
            out.append(dict(f, key=key, kind=kind, label=names.get(key) or label.strip(), auto_label=label.strip(),
                            show=key in seen or kind == 'gpu' or key in custom))
        return out

    def fan_name(self, key, name):
        """Nome scelto dall'utente per una ventola (vuoto = torna quello automatico)."""
        if not isinstance(key, str) or not 1 <= len(key) <= 90: raise ValueError('Ventola non valida')
        name = re.sub(r'\s+', ' ', str(name or '')).strip()
        if len(name) > 32: raise ValueError('Nome troppo lungo: massimo 32 caratteri')
        with self.lock:
            names = self.config.setdefault('fans', {}).setdefault('names', {})
            if name: names[key] = name
            else: names.pop(key, None)
            json_save(CONFIG_FILE, self.config)
            self.cached_telemetry = None
        return 'Nome salvato' if name else 'Nome automatico'

    def fan_send(self, key, sleep=time.sleep):
        """Manda a Fan Control un profilo (attività già autorizzata) e controlla che lo carichi davvero.
        Le ventole "impallate" dopo un cambio: due avvii troppo vicini, oppure l'attività di prima ancora aperta
        (Windows ignora un'attività che sta già girando). Ora: uno alla volta, chiusa e rilanciata, e verificata."""
        import discovery
        exe = self.config.get('fans', {}).get('fancontrol_exe', '')
        want = discovery.FAN_FILES[key]
        with self.fan_lock:
            wait = FAN_SPACING - (time.monotonic() - self.fan_sent[0])
            if wait > 0: sleep(wait)
            if not discovery.task_restart(discovery.FAN_TASKS[key]): raise RuntimeError('Fan Control: attività non avviata')
            self.fan_sent = stamp = (time.monotonic(), want)
            self.fan_sent_at = datetime.now().strftime('%H:%M:%S')
            logging.info('Ventole: mandato %s a Fan Control', want)
        if not discovery.fancontrol_config_loaded(exe): return  # versione di Fan Control senza CACHE: niente verifica
        def verify():
            for attempt in (1, 2):
                for _ in range(FAN_VERIFY_SECONDS):
                    sleep(1)
                    if self.fan_sent != stamp and self.fan_sent[1] != want: return  # nel frattempo scelto altro
                    if discovery.fancontrol_config_loaded(exe) == want: return
                if attempt == 1:
                    logging.info('Fan Control non ha caricato %s: nuovo tentativo', want)
                    with self.fan_lock: discovery.task_restart(discovery.FAN_TASKS[key])
            self.log_event(f'⚠ Ventole: Fan Control non ha caricato il profilo {want}. Aprilo e controlla che il servizio sia acceso.')
        threading.Thread(target=verify, daemon=True, name='fan-verify').start()

    def fans_manual_ready(self):
        """Profili "Manuale" creati e scrivibili: serve aver premuto Configura/Aggiorna profili da questa versione."""
        import discovery
        exe = Path(self.config.get('fans', {}).get('fancontrol_exe', ''))
        f = discovery.fancontrol_config_dir(str(exe)) / discovery.FAN_FILES['manual_a']
        at, ready = getattr(self, 'fans_manual_cache', (0.0, False))
        if time.monotonic() - at > 60:
            ready = f.is_file() and os.access(f, os.W_OK) and discovery.task_exists(discovery.FAN_TASKS['manual_a'])
            self.fans_manual_cache = (time.monotonic(), ready)
        return ready

    def fan_set(self, ident, percent, curve=None):
        """Una sola ventola a velocità fissa (0–100%), con una curva sulla temperatura (curve) o di nuovo
        come il profilo scelto (entrambi None). Le altre restano come il livello attuale."""
        import discovery
        cfg = self.config.get('fans', {})
        if not cfg.get('enabled'): raise RuntimeError('Gestione ventole non attiva')
        if not isinstance(ident, str) or not re.fullmatch(r'/[A-Za-z0-9_/-]{3,80}', ident): raise ValueError('Ventola non valida')
        if percent is not None and (type(percent) is not int or not 0 <= percent <= 100): raise ValueError('Velocità 0–100%')
        if percent is not None and curve is not None: raise ValueError('Scegli velocità fissa oppure curva')
        exe = Path(cfg.get('fancontrol_exe', ''))
        folder = discovery.fancontrol_config_dir(str(exe))
        if not self.fans_manual_ready():
            self.fans_manual_cache = (0.0, False)
            raise RuntimeError('Per regolare le singole ventole premi "Aggiorna profili" nella pagina Ventole (una conferma)')
        level = self.state.get('fans_level') or 'normal'
        profile = ('off_pump' if self.state.get('fans_pump') else 'off') if level == 'off' else level
        base = folder / discovery.FAN_FILES.get(profile, discovery.FAN_FILES['normal'])
        prof = json.loads(base.read_text(encoding='utf-8-sig'))
        ctls = prof.get('FanControl', {}).get('Controls', [])
        target = next((c for c in ctls if str(c.get('Identifier', '')) == ident), None)
        if not target: raise ValueError('Questa ventola non è regolabile da Fan Control')
        name = str(target.get('NickName') or 'Ventola')
        kind = next((f['kind'] for f in self.fan_rows(collect_sensors(self.config.get('sensors', {}).get('libre_hardware_monitor', '')).get('fans') or [])
                     if f['key'] == ident), '')
        pumpish = discovery.is_pump(name, ident) or kind == 'aio'  # AIO su CPU_FAN: pompa e ventole sullo stesso cavo
        if percent is not None and pumpish and percent < discovery.PUMP_MIN_PERCENT:
            raise ValueError(f'La pompa non scende sotto il {discovery.PUMP_MIN_PERCENT}%: raffredda il processore')
        if curve is not None:
            curve = discovery.fan_curve_clean(curve, pumpish)
            if curve['src'] not in ('cpu', 'gpu') and self.sensor_name(curve['src']) == curve['src']:
                raise ValueError('Sensore non trovato: serve LibreHardwareMonitor acceso')
        custom = {k: v for k, v in (self.state.get('fans_custom') or {}).items() if isinstance(v, (int, dict))}
        value = curve if curve is not None else percent
        if value is None: custom.pop(ident, None)
        else: custom[ident] = value
        slot = self.fan_custom_send(prof, custom)
        with self.lock:
            # Cambiata una ventola: non è più esattamente il profilo tuo che avevi scelto.
            self.state.update(fans_custom=custom, fans_slot=slot); self.state.pop('fans_preset', None)
            if self.state.get('fans_mine'):
                # In Personalizzate la modifica è la modalità stessa: resta salvata per la prossima volta.
                self.config.setdefault('fans', {})['mine'] = {'custom': json.loads(json.dumps(custom))}
                self.state['fans_eco'] = fans_mine_slow(custom)
                json_save(CONFIG_FILE, self.config)
            json_save(STATE_FILE, self.state)
        nice = (self.config.get('fans', {}).get('names') or {}).get(ident) or name.replace('CPU Fan', 'Radiatore').replace('Pump Fan', 'Pompa').replace('System Fan', 'Ventola case')
        msg = f'{nice}: ' + (f'{percent}% fisso' if percent is not None else
                             f"curva sulla temperatura {self.sensor_name(curve['src'])}" if curve is not None else 'torna al profilo ' + FAN_LEVEL_NAMES.get(level, level))
        self.log_event('Ventole · ' + msg)
        return msg

    def fan_custom_send(self, prof, custom):
        """Profilo del livello + regolazioni a mano, scritto in uno dei due file Manuale (a turno) e mandato a Fan Control."""
        import discovery
        folder = discovery.fancontrol_config_dir(self.config.get('fans', {}).get('fancontrol_exe', ''))
        temp_ids = collect_sensors(self.config.get('sensors', {}).get('libre_hardware_monitor', '')).get('temp_ids') or {}
        discovery.apply_fan_custom(prof, custom, temp_ids)
        slot = 'manual_b' if self.state.get('fans_slot') == 'manual_a' else 'manual_a'
        with self.fan_lock:  # A e B a turno: non riscrivere il file mentre Fan Control lo sta caricando
            (folder / discovery.FAN_FILES[slot]).write_text(json.dumps(prof, indent=2), encoding='utf-8')
        self.fan_send(slot)
        return slot

    # ---------- profili tuoi: una combinazione di velocità salvata, accanto a Spente/Silenziose/Normali/Massimo ----------
    def fan_presets(self):
        return [p for p in self.config.get('fans', {}).get('presets') or [] if isinstance(p, dict) and p.get('id')]

    def fan_preset_save(self, name):
        """Salva le ventole come sono adesso (livello di partenza + quelle regolate a mano) con un nome.
        Con un nome già usato lo aggiorna."""
        name = re.sub(r'\s+', ' ', str(name or '')).strip()
        if not 1 <= len(name) <= 20: raise ValueError('Nome del profilo: da 1 a 20 caratteri')
        custom = {k: v for k, v in (self.state.get('fans_custom') or {}).items() if isinstance(v, (int, dict))}
        if not custom: raise ValueError("Prima regola almeno una ventola: toccala nell'elenco qui sotto e scegli la velocità")
        level = self.state.get('fans_level') or 'normal'
        with self.lock:
            presets = self.config.setdefault('fans', {}).setdefault('presets', [])
            same = next((p for p in presets if str(p.get('name', '')).lower() == name.lower()), None)
            if not same and len(presets) >= FAN_PRESETS_MAX:
                raise ValueError(f'Al massimo {FAN_PRESETS_MAX} profili tuoi: eliminane uno prima')
            p = same or {'id': 'p' + secrets.token_hex(4)}
            p.update(name=name, base=level, pump=bool(self.state.get('fans_pump')), custom=json.loads(json.dumps(custom)))
            if not same: presets.append(p)
            json_save(CONFIG_FILE, self.config)
            self.state['fans_preset'] = p['id']; json_save(STATE_FILE, self.state)
        msg = f'Profilo ventole "{name}" ' + ('aggiornato' if same else 'salvato')
        self.log_event(msg)
        return msg

    def fan_preset_apply(self, pid):
        import discovery
        p = next((p for p in self.fan_presets() if p['id'] == pid), None)
        if not p: raise ValueError('Profilo non trovato')
        cfg = self.config.get('fans', {})
        if not cfg.get('enabled'): raise RuntimeError('Gestione ventole non attiva')
        if not self.fans_manual_ready():
            self.fans_manual_cache = (0.0, False)
            raise RuntimeError('Per usare i tuoi profili premi "Aggiorna profili" nella pagina Ventole (una conferma)')
        base = p.get('base') if p.get('base') in FAN_LEVEL_NAMES else 'normal'
        pump = bool(base == 'off' and p.get('pump'))
        custom = {k: v for k, v in (p.get('custom') or {}).items() if isinstance(v, (int, dict))}
        slot = self.fan_custom_send(self.fan_base_profile(base, pump), custom)
        with self.lock:
            self.state.update(fans_level=base, fans_pump=pump, fans_eco=base in ('eco', 'off'), fans_custom=custom,
                              fans_slot=slot, fans_preset=p['id'])
            self.state.pop('fans_mine', None)
            json_save(STATE_FILE, self.state)
        msg = f'Ventole: profilo "{p["name"]}"'
        self.log_event(msg)
        return msg

    def fan_base_profile(self, level, pump):
        """Il profilo NEXAR del livello (Spente con o senza pompa, Silenziose, Normali, Massimo) letto dal file."""
        import discovery
        profile = ('off_pump' if pump else 'off') if level == 'off' else level
        folder = discovery.fancontrol_config_dir(self.config.get('fans', {}).get('fancontrol_exe', ''))
        return json.loads((folder / discovery.FAN_FILES.get(profile, discovery.FAN_FILES['normal'])).read_text(encoding='utf-8-sig'))

    def fans_reapply(self):
        """Dopo "Rifai profili": Fan Control ha ancora in memoria il profilo vecchio. Gli rimanda la scelta di adesso
        (profilo tuo, regolazioni a mano o livello) letta dai file nuovi."""
        if self.state.get('fans_mine'): return self.fans_mine()
        pid = self.state.get('fans_preset')
        if pid and any(p['id'] == pid for p in self.fan_presets()): return self.fan_preset_apply(pid)
        level = self.state.get('fans_level') or 'normal'
        level = level if level in FAN_LEVEL_NAMES else 'normal'
        pump = bool(self.state.get('fans_pump'))
        custom = {k: v for k, v in (self.state.get('fans_custom') or {}).items() if isinstance(v, (int, dict))}
        if custom and self.fans_manual_ready():
            slot = self.fan_custom_send(self.fan_base_profile(level, pump), custom)
            with self.lock: self.state['fans_slot'] = slot; json_save(STATE_FILE, self.state)
            return 'Ventole: regolazioni a mano rimesse'
        return self.fans_level(level, keep_pump=pump if level == 'off' else None)

    # ---------- Personalizzate: la quinta scelta accanto a Spente/Silenziose/Normali/Massimo, decisa da te ----------
    def fans_mine_saved(self):
        m = self.config.get('fans', {}).get('mine') or {}
        return {k: v for k, v in (m.get('custom') or {}).items() if isinstance(v, (int, dict))}

    def fans_mine(self, percent=None):
        """Senza percent rimette le velocità salvate in Personalizzate; con percent porta tutte le ventole a quella
        velocità (pompa e radiatore AIO mai sotto il minimo) e la salva. Le ventole non regolate seguono Normali."""
        import discovery
        if not self.config.get('fans', {}).get('enabled'): raise RuntimeError('Gestione ventole non attiva')
        if percent is not None and (type(percent) is not int or not 0 <= percent <= 100): raise ValueError('Velocità 0–100%')
        if not self.fans_manual_ready():
            self.fans_manual_cache = (0.0, False)
            raise RuntimeError('Per Personalizzate premi "Rifai profili" nella pagina Temperature (una conferma)')
        prof = self.fan_base_profile('normal', False)
        if percent is None:
            # La prima volta parte da come hai già regolato le ventole a mano.
            custom = self.fans_mine_saved() or {k: v for k, v in (self.state.get('fans_custom') or {}).items() if isinstance(v, (int, dict))}
        else:
            nick = {str(c.get('Identifier', '')): str(c.get('NickName') or '') for c in prof.get('FanControl', {}).get('Controls', [])}
            rows = [f for f in self.fan_rows(collect_sensors(self.config.get('sensors', {}).get('libre_hardware_monitor', '')).get('fans') or [])
                    if f.get('show') and f['key'] in nick]
            if not rows: raise RuntimeError('Nessuna ventola letta: serve LibreHardwareMonitor acceso')
            low = lambda f: discovery.is_pump(nick[f['key']], f['key']) or f['kind'] in ('aio', 'pump', 'cpu')
            custom = {f['key']: max(percent, discovery.PUMP_MIN_PERCENT) if low(f) else percent for f in rows}
        slot = self.fan_custom_send(prof, custom)
        with self.lock:
            self.config.setdefault('fans', {})['mine'] = {'custom': json.loads(json.dumps(custom))}
            json_save(CONFIG_FILE, self.config)
            self.state.update(fans_level='normal', fans_pump=False, fans_eco=fans_mine_slow(custom), fans_custom=custom,
                              fans_slot=slot, fans_mine=True)
            self.state.pop('fans_preset', None)
            json_save(STATE_FILE, self.state)
        msg = ('Ventole personalizzate: ' + (f'tutte al {percent}%' + (f' (pompa e radiatore AIO almeno al {discovery.PUMP_MIN_PERCENT}%)' if percent < discovery.PUMP_MIN_PERCENT else '')
               if percent is not None else f'{len(custom)} regolate da te' if custom else 'tocca una ventola per sceglierne la velocità'))
        self.log_event(msg)
        return msg

    def fan_preset_delete(self, pid):
        """Toglie il profilo dall'elenco; le ventole restano come sono adesso."""
        with self.lock:
            presets = self.config.setdefault('fans', {}).get('presets') or []
            p = next((p for p in presets if p.get('id') == pid), None)
            if not p: raise ValueError('Profilo non trovato')
            presets.remove(p); json_save(CONFIG_FILE, self.config)
            if self.state.get('fans_preset') == pid: self.state.pop('fans_preset', None); json_save(STATE_FILE, self.state)
        return f'Profilo "{p.get("name", "")}" eliminato'

    def fan_guard_loop(self, stop_event):
        """Con le ventole spente (anche radiatore e pompa) la CPU può scaldare in pochi secondi:
        temperature ogni 2 s e ritorno al profilo normale a 75 °C o se i sensori smettono di rispondere."""
        blind = 0
        while not stop_event.wait(FAN_GUARD_SECONDS):
            slow = any(isinstance(v, int) and v < 30 for v in (self.state.get('fans_custom') or {}).values())
            if self.state.get('fans_level') != 'off' and not slow:
                blind = 0; continue
            if windows_shutting_down(): blind = 0; continue  # i sensori si chiudono: non è un guasto
            try:
                cpu = collect_sensors(self.config.get('sensors',{}).get('libre_hardware_monitor',''))['cpu_temp']
                gpu = gpu_read()['temp']
                blind = blind + 1 if cpu is None else 0
                hot = [f'{n} a {v:.0f}°C' for n, v in (('CPU', cpu), ('GPU', gpu)) if v is not None and v >= FAN_OFF_LIMIT]
                if hot or blind >= 3:
                    why = ', '.join(hot) if hot else 'sensori di temperatura non raggiungibili'
                    msg = self.fans_level('normal')
                    self.log_event(f'🌡 Ventole spente: {why}. {msg}')
                    self.notify(f'🌡 Ventole riaccese: {why}.')
                    blind = 0
            except Exception:
                logging.exception('Guardia ventole spente')

    def run_job(self, name, fn):
        """Lavori lunghi (winget, UAC) in background: la dashboard ne legge lo stato da status()['jobs']."""
        with self.lock:
            if self.jobs.get(name, {}).get('state') == 'running': raise RuntimeError('Operazione già in corso')
            self.jobs[name] = {'state': 'running', 'message': '', 'at': time.time()}
        def work():
            try: result = {'state': 'ok', 'message': str(fn() or 'Completato')}
            except Exception as ex: result = {'state': 'error', 'message': str(ex)[:300]}
            with self.lock: self.jobs[name] = dict(result, at=time.time())
            self.log_event(result['message'])
        threading.Thread(target=work, daemon=True, name='job-' + name).start()
        return 'Operazione avviata'

    def setup_fans(self, admin=None):
        """Crea i profili ventole PC ECO (una conferma UAC) e li collega."""
        import discovery
        cfg = self.config.get('fans', {})
        exe = cfg.get('fancontrol_exe') or discovery.find_fancontrol()
        if not exe: raise RuntimeError('Fan Control non trovato')
        percent = int(cfg.get('eco_percent', 40))
        chosen = discovery.fancontrol_setup(exe, percent, ROOT / 'fan_profiles', admin, extra='' if admin else self.apps_fix_script())
        self.fans_ready_cache = (0.0, False)
        with self.lock:
            self.config.setdefault('fans', {}).update(eco_profile=discovery.FAN_FILES['eco'], normal_profile=discovery.FAN_FILES['normal'],
                                                      profiles_version=discovery.FAN_PROFILES_VERSION,
                                                      **({} if admin and not self.admin.current() else {'tasks_version': discovery.FAN_TASKS_VERSION}))
            json_save(CONFIG_FILE, self.config)
        self.apps_fix_cache = (0.0, None)
        self.fans_manual_cache = (0.0, False)
        self.discover()
        try: self.fans_reapply()
        except Exception as ex: logging.warning('Ventole: scelta non rimandata dopo i profili nuovi (%s)', ex)
        msg = f'Ventole configurate: ECO porta al {percent}% ' + ', '.join(chosen) + ' (radiatore e pompa esclusi)'
        self.log_event(msg)
        return msg

    def set_mode(self, value, manual=True, reason='', quiet=False):
        if value not in MODES: raise ValueError('Modalità sconosciuta')
        with self.mode_lock:
            with self.lock:
                # Se powercfg fallisce non modificare luci o ventole.
                self.apply_power(value)
                if manual:
                    self.manual_override = True
                    # Scelta dell'utente: il Gaming automatico non la contraddice finché il gioco resta aperto.
                    self.gaming_declined = value != 'gaming' and bool(self.booster.running)
                    self.gaming_owned = False
            notes = ['Energia: '+MODES[value]]
            fans = {'eco':'eco' if self.eco_settings()['fans_quiet'] else 'normal','normal':'normal','gaming':self.config.get('fans',{}).get('gaming_level','normal')}[value]
            # Personalizzate è una scelta tua: AI ECO e Normale non la toccano (Gaming solo se gli hai dato un livello suo).
            mine = self.state.get('fans_mine') and not (value == 'gaming' and fans != 'normal')
            fan_cb = (lambda: 'Ventole: restano personalizzate') if mine else (lambda: self.fans_level(fans))
            # Gaming Boost: parte con Gaming e rimette tutto com'era quando si passa ad altra modalità.
            boost = (lambda: self.booster.start()) if value == 'gaming' else (lambda: self.booster.stop())
            for cb in (lambda: self.rgb_mode(value), fan_cb, boost):
                try:
                    note = cb()
                    if note: notes.append(note)
                except Exception as ex: notes.append('Integrazione non applicata: '+str(ex))
            self.last_message = ' · '.join(notes)
            self.log_event(self.last_message)
            if not manual and not quiet:
                title = {'eco': '🌙 AI ECO attivata automaticamente', 'gaming': '🎮 Gaming attivato' + (': ' + reason if reason else ''),
                         'normal': '⚡ Profilo normale ripristinato'}[value]
                self.notify(title+'\n'+self.last_message[:270])
            return self.last_message

    def rgb_mode(self, value):
        """Luci per modalità: ECO le spegne, Gaming usa il suo colore (se scelto), uscendo torna il colore normale."""
        rgb = self.config.get('rgb', {})
        gaming_color = rgb.get('gaming_color') if rgb.get('enabled') else ''
        notes = []
        if self.state.get('rgb_gaming') and value != 'gaming':
            try:
                bright = int(rgb.get('brightness', 100))
                notes.append(self.rgb_color(rgb.get('normal_color', '#ffffff'), bright, remember=False))
                for dev, c in (rgb.get('device_colors') or {}).items():
                    try: self.rgb_color(c, bright, dev, remember=False)
                    except RuntimeError: pass  # dispositivo non più collegato (pad, tastiera senza fili)
            finally:
                self.state.pop('rgb_gaming', None); self.save_state()
        if value == 'gaming' and gaming_color:
            msg = self.rgb_color(gaming_color, int(rgb.get('brightness', 100)), remember=False)
            self.state['rgb_gaming'] = True; self.save_state()
            return 'Luci Gaming: ' + msg
        eco_off = value == 'eco' and self.eco_settings()['leds_off']
        if eco_off: note = self.rgb_profile(True, by='mode')
        elif notes or self.state.get('rgb_off_by') == 'user': note = ''  # spenti a mano: restano spenti
        else: note = self.rgb_profile(False)
        return ' · '.join(n for n in notes + [note] if n)

    def set_auto(self, enable):
        with self.lock:
            self.config.setdefault('auto_detect',{})['enabled'] = bool(enable)
            self.manual_override = False
            json_save(CONFIG_FILE,self.config)
            self.last_message = 'Rilevamento processi '+('attivato' if enable else 'disattivato')
            self.auto_previous_enabled = bool(enable)
            self.auto_eco_owned = False
            self.log_event(self.last_message)
            return self.last_message

    def screen_off(self):
        if os.name != 'nt': raise RuntimeError('Solo Windows')
        ctypes.windll.user32.SendMessageW(0xFFFF, 0x0112, 0xF170, 2)
        self.screen_off_at = time.monotonic()
        return 'Comando spegnimento monitor inviato'

    def display_on(self):
        """Monitor acceso se mouse/tastiera sono stati usati prima che scattasse lo spegnimento di Windows."""
        if os.name != 'nt': return True
        idle = pc_power.idle_seconds()
        if self.screen_off_at and idle >= time.monotonic() - self.screen_off_at: return False
        at, timeout = self.video_timeout
        if timeout is None or time.monotonic() - at > 120:
            try:
                # Valori in ordine: minimo, massimo, incremento, corrente CA, corrente CC.
                values = re.findall(r'0x([0-9a-fA-F]{8})', power('/q', 'SCHEME_CURRENT', 'SUB_VIDEO', 'VIDEOIDLE'))
                timeout = int(values[-2], 16) if len(values) >= 2 else 0
            except Exception: timeout = 0
            self.video_timeout = (time.monotonic(), timeout)
        return not timeout or idle < timeout

    def disks_busy(self):
        """Frazione di tempo in cui ogni disco ha lavorato dall'ultima lettura (PhysicalDriveN → 'N')."""
        try: now = (time.monotonic(), psutil.disk_io_counters(perdisk=True))
        except Exception: return {}
        prev, self.disk_prev = self.disk_prev, now
        if not prev: return {}
        ms = (now[0] - prev[0]) * 1000 or 1
        out = {}
        for name, c in now[1].items():
            old = prev[1].get(name)
            if old and name.lower().startswith('physicaldrive'):
                out[name[13:]] = min(1.0, max(0.0, (c.read_time + c.write_time - old.read_time - old.write_time) / ms))
        return out

    # ---------- accensione / spegnimento ----------
    def power_action(self, kind, minutes=0, after_ai=False):
        if kind == 'cancel': return self.cancel_power()
        if kind not in pc_power.ACTIONS: raise ValueError('Azione non prevista')
        if type(minutes) is not int or not 0 <= minutes <= 720: raise ValueError('Minuti 0–720')
        label = pc_power.ACTIONS[kind]
        if after_ai or minutes:
            if kind not in ('shutdown', 'sleep', 'hibernate'): raise ValueError('Programmabili: spegnimento, sospensione, ibernazione')
            if kind == 'hibernate' and not pc_power.hibernate_available(): raise RuntimeError('Ibernazione non attiva su questo PC')
            with self.lock:
                self.power_plan = {'action': kind, 'label': label, 'after_ai': bool(after_ai), 'idle_since': None,
                                   'at': None if after_ai else time.time() + minutes * 60}
            msg = label + (' quando Codex e Claude hanno finito' if after_ai else f' tra {minutes} minuti')
            self.log_event('⏻ Programmato: ' + msg)
            return msg + ' (programmato)'
        pc_power.execute(kind)
        with self.lock:
            # Spegnimento e riavvio restano annullabili per qualche secondo: la dashboard mostra il conto alla rovescia.
            self.power_plan = {'action': kind, 'label': label, 'after_ai': False, 'idle_since': None, 'started': True,
                               'at': time.time() + pc_power.GRACE_SECONDS} if kind in ('shutdown', 'restart') else None
        msg = label + (f' tra {pc_power.GRACE_SECONDS} secondi' if kind in ('shutdown', 'restart') else ' in corso')
        self.log_event('⏻ ' + msg)
        return msg

    def cancel_power(self):
        with self.lock: plan, self.power_plan = self.power_plan, None
        aborted = pc_power.abort_windows_shutdown()
        if not plan and not aborted: return 'Nessuno spegnimento in programma'
        self.log_event('⏻ Spegnimento annullato')
        return 'Annullato: il PC resta acceso'

    def power_loop(self, stop_event):
        while not stop_event.wait(5):
            try:
                with self.lock: plan = dict(self.power_plan) if self.power_plan else None
                if not plan: continue
                if plan.get('started'):
                    # Il PC è ancora acceso un minuto dopo: lo spegnimento è stato annullato dal PC.
                    if time.time() > plan['at'] + 60:
                        with self.lock: self.power_plan = None
                    continue
                if plan['after_ai']:
                    idle = plan['idle_since']
                    if any(self.processes().values()): idle = None
                    elif idle is None: idle = time.time()
                    with self.lock:
                        if self.power_plan: self.power_plan['idle_since'] = idle
                    due = idle is not None and time.time() - idle >= 120
                else: due = time.time() >= plan['at']
                if due:
                    with self.lock: self.power_plan = None
                    msg = self.power_action(plan['action'])
                    self.notify('⏻ ' + msg + ('. Scrivi /annulla per fermarlo.' if plan['action'] == 'shutdown' else ''))
            except Exception as ex:
                logging.exception('Spegnimento programmato')
                with self.lock: self.power_plan = None
                self.notify('⚠️ Spegnimento programmato non eseguito: ' + str(ex)[:200])

    # ---------- azioni programmate ----------
    def schedules(self):
        return {'rules': self.planner.view(), 'actions': planner.ACTIONS}

    def set_schedules(self, rules):
        clean = planner.clean_rules(rules)
        with self.lock:
            self.config['schedules'] = clean
            runs = self.state.setdefault('schedule_runs', {})
            for k in [k for k in runs if k not in {r['id'] for r in clean}]: runs.pop(k, None)
        self._save_config(); self.save_state()
        self.log_event(f'⏰ Azioni programmate: {sum(r["enabled"] for r in clean)} attive')
        return self.schedules()

    def run_scheduled(self, rule, left):
        a = rule['action']
        try:
            if a in planner.POWER:
                minutes = max(1, round(left / 60))
                msg = self.power_action(a, minutes)
                self.notify(f'⏰ {planner.describe(rule)}\n{msg}. Scrivi /annulla per fermarlo.')
                return
            if a in MODES: msg = self.set_mode(a, manual=True)
            elif a == 'monitor_off': msg = screen_remote.monitor_off()
            elif a == 'lock': msg = self.power_action('lock')
            else: msg = self.rgb_profile(a == 'leds_off')
            self.log_event('⏰ ' + planner.ACTIONS[a] + ' (programmata)')
            self.notify(f'⏰ {planner.describe(rule)}\n{str(msg)[:250]}')
        except Exception as ex:
            logging.exception('Azione programmata')
            self.notify(f'⚠️ Azione programmata non eseguita ({planner.ACTIONS[a]}): {str(ex)[:200]}')

    def pc_info(self):
        with self.lock: plan = dict(self.power_plan) if self.power_plan else None
        if plan: plan['seconds_left'] = None if plan['at'] is None else max(0, round(plan['at'] - time.time()))
        boot = psutil.boot_time()
        return {'uptime_s': round(time.time() - boot), 'boot': datetime.fromtimestamp(boot).isoformat(timespec='minutes'),
                'pending': plan, 'hibernate': pc_power.hibernate_available(),
                'net': self.state.get('inventory', {}).get('net')}

    def wol_setup(self, admin=None):
        import discovery
        net = self.state.get('inventory', {}).get('net') or {}
        if not net.get('name'): raise RuntimeError('Scheda di rete via cavo non trovata')
        if admin: admin.call('wol', name=net['name'])
        elif not discovery.run_elevated(discovery.wol_enable_script(net['name']), wait=True): raise RuntimeError('Conferma amministratore annullata')
        inv = discovery.hardware_inventory()
        if inv:
            with self.lock: self.state['inventory'] = inv; json_save(STATE_FILE, self.state)
        return 'Wake-on-LAN attivato su ' + net['name']

    def log_event(self, message):
        record = {'at':datetime.now().isoformat(timespec='seconds'), 'message':str(message)[:400]}
        self.events.appendleft(record)
        logging.info('%s', message)

    # ---------- tutte le temperature: nome, storico, avvisi ----------
    def sensor_name(self, sid):
        if sid in ('cpu', 'gpu'): return sid.upper()
        import temps
        for g, r in temps.all_rows((self.cached_telemetry or {}).get('temps') or self.telemetry().get('temps')):
            if r['id'] == sid:
                short = {'cpu': 'CPU', 'gpu': 'GPU', 'board': 'scheda madre', 'ram': 'RAM', 'disk': ''}.get(g['kind'], '')
                return f"{r['name']} ({short})" if short and short not in r['name'] else r['name']
        return sid

    def temps_track(self, t, now=None):
        """Una volta al minuto mette da parte tutte le temperature (24 ore, solo in memoria)."""
        import temps
        now = time.time() if now is None else now
        if now - self.temp_hist_at < 55: return
        snap = {r['id']: r['value'] for _, r in temps.all_rows(t.get('temps'))}
        if not snap: return
        self.temp_hist_at = now
        self.temp_hist.append((int(now), snap))

    def temps_history(self, ids=None):
        hist = list(self.temp_hist)
        keys = list(ids) if ids else sorted({k for _, s in hist for k in s})
        return {'t': [ts for ts, _ in hist], 's': {k: [s.get(k) for _, s in hist] for k in keys[:40]}}

    def temps_alerts(self, t):
        """Avviso su Telegram se un sensore qualsiasi (dischi, VRM, punto più caldo della GPU…) supera il suo limite.
        CPU e GPU principali hanno già le loro soglie, qui non si ripetono."""
        import temps
        if not self.config.get('alerts', {}).get('sensors', True): self.temp_alert.clear(); return
        for g, r in temps.all_rows(t.get('temps')):
            if (g['kind'] == 'cpu' and r['name'] == 'Processore') or (g['kind'] == 'gpu' and r['name'] == 'Chip' and g['name'] != 'Grafica integrata'):
                continue
            a = self.temp_alert.setdefault(r['id'], {'on': False, 'at': 0.0})
            label = r['name'] if g['kind'] == 'disk' else f"{g['name']} · {r['name']}"
            if r['value'] >= r['crit'] and not a['on']:
                a['on'] = True
                if time.monotonic() - a['at'] > 1200:
                    a['at'] = time.monotonic()
                    msg = f"⚠️ Temperatura alta: {label} {r['value']:.0f}°C (limite {r['crit']:.0f}°C)."
                    self.log_event(msg); self.notify(msg)
            elif r['value'] <= r['crit'] - 6 and a['on']:
                a['on'] = False
                msg = f"✅ {label} rientrata: {r['value']:.0f}°C."
                self.log_event(msg); self.notify(msg)

    def get_events(self):
        with self.lock:
            return list(self.events)

    def public_settings(self):
        with self.lock:
            return {
                'eco_cpu_max_percent':int(self.config.get('eco_cpu_max_percent',90)),
                'monitor_timeout_seconds':int(self.config.get('monitor_timeout_seconds',60)),
                'auto_enabled':bool(self.config.get('auto_detect',{}).get('enabled')),
                'restore_delay_seconds':int(self.config.get('auto_detect',{}).get('restore_delay_seconds',180)),
                'alerts_enabled':bool(self.config.get('alerts',{}).get('enabled',True)),
                'alerts_sensors':bool(self.config.get('alerts',{}).get('sensors',True)),
                'cpu_temp_alert':int(self.config.get('alerts',{}).get('cpu_temp',87)),
                'gpu_temp_alert':int(self.config.get('alerts',{}).get('gpu_temp',82)),
                'energy_price_cents':round(float(self.config.get('energy',{}).get('price_eur_kwh',0.30))*100),
                'psu_watts':int(self.config.get('energy',{}).get('psu_watts',750)),
                'psu_class':str(self.config.get('energy',{}).get('psu_class','gold')),
                'monitor_watts':int(self.config.get('energy',{}).get('monitor_watts',0)),
                'extra_watts':int(self.config.get('energy',{}).get('extra_watts',6)),
                'gaming_fans':str(self.config.get('fans',{}).get('gaming_level','normal')),
                'anim_style':str(self.config.get('ui',{}).get('anim_style','liquid')),
            }

    def update_settings(self, new):
        if not isinstance(new, dict): raise ValueError('Impostazioni non valide')
        allowed = {
            'eco_cpu_max_percent':(50,100),
            'monitor_timeout_seconds':(30,3600),
            'restore_delay_seconds':(30,7200),
            'cpu_temp_alert':(70,99),
            'gpu_temp_alert':(60,94),
            'energy_price_cents':(5,100),
            'psu_watts':(300,1600),
            'monitor_watts':(0,200),
            'extra_watts':(0,60),
        }
        for field, (low, high) in allowed.items():
            if field in new and (type(new[field]) is not int or not low <= new[field] <= high):
                raise ValueError(f'{field}: valore ammesso {low}–{high}')
        if 'gaming_fans' in new and new['gaming_fans'] not in ('normal','max'):
            raise ValueError('gaming_fans: normal o max')
        if 'anim_style' in new and new['anim_style'] not in ('liquid','discreet','off'):
            raise ValueError('Animazioni: liquid, discreet o off')
        if 'psu_class' in new and new['psu_class'] not in energy_model.PSU_CLASSES:
            raise ValueError('psu_class: ' + ', '.join(energy_model.PSU_CLASSES))
        for flag in ('alerts_enabled', 'alerts_sensors'):
            if flag in new and type(new[flag]) is not bool: raise ValueError(f'{flag} deve essere true/false')
        with self.lock:
            if 'eco_cpu_max_percent' in new: self.config['eco_cpu_max_percent']=new['eco_cpu_max_percent']
            if 'monitor_timeout_seconds' in new: self.config['monitor_timeout_seconds']=new['monitor_timeout_seconds']
            if 'restore_delay_seconds' in new: self.config.setdefault('auto_detect',{})['restore_delay_seconds']=new['restore_delay_seconds']
            if 'alerts_enabled' in new: self.config.setdefault('alerts',{})['enabled']=new['alerts_enabled']
            if 'alerts_sensors' in new: self.config.setdefault('alerts',{})['sensors']=new['alerts_sensors']
            if 'cpu_temp_alert' in new: self.config.setdefault('alerts',{})['cpu_temp']=new['cpu_temp_alert']
            if 'gpu_temp_alert' in new: self.config.setdefault('alerts',{})['gpu_temp']=new['gpu_temp_alert']
            if 'energy_price_cents' in new: self.config.setdefault('energy',{})['price_eur_kwh']=new['energy_price_cents']/100
            if 'gaming_fans' in new: self.config.setdefault('fans',{})['gaming_level']=new['gaming_fans']
            if 'anim_style' in new: self.config.setdefault('ui',{})['anim_style']=new['anim_style']
            for field in ('psu_watts','psu_class','monitor_watts','extra_watts'):
                if field in new: self.config.setdefault('energy',{})[field]=new[field]
            self.cached_telemetry=None
            json_save(CONFIG_FILE,self.config)
            self.last_message='Impostazioni salvate. Le modifiche energetiche si applicano al prossimo cambio modalità.'
            self.log_event(self.last_message)
            return self.public_settings()

    def telemetry(self):
        # Due client (Umbrel/PC) e bot non devono saturare nvidia-smi.
        now=time.monotonic()
        with self.lock:
            if self.cached_telemetry is not None and now-self.cache_time < 3:
                return dict(self.cached_telemetry)
            gpu=gpu_read()
            sensors=collect_sensors(self.config.get('sensors',{}).get('libre_hardware_monitor',''))
            mem=psutil.virtual_memory()
            telemetry={
                'cpu':round(psutil.cpu_percent(interval=None),1),
                'cpu_temp':sensors['cpu_temp'],
                'gpu':gpu['load'], 'gpu_temp':gpu['temp'], 'gpu_watts':gpu['watts'],
                'ram':round(mem.percent,1),'ram_used':round(mem.used/1024**3,1),
                'ram_total':round(mem.total/1024**3,1), 'fans':self.fan_rows(sensors['fans']),
                'cpu_power':sensors.get('cpu_power'), 'temps':sensors.get('temps') or [],
            }
            rgb=self.config.get('rgb',{})
            telemetry['power']=energy_model.estimate({
                'cpu_w':sensors.get('cpu_power'), 'gpu_w':gpu['watts'], 'cpu_load':telemetry['cpu'], 'gpu_load':gpu['load'],
                'fans':sensors['fans'], 'disks_busy':self.disks_busy(), 'display_on':self.display_on(),
                'rgb':{'leds':self.state.get('rgb_leds',40) if rgb.get('enabled') else 0, 'color':rgb.get('normal_color','#ffffff'),
                       'brightness':int(rgb.get('brightness',100)), 'off':bool(self.state.get('rgb_off'))},
            }, self.config.get('energy',{}), self.config.get('hardware',{}), self.state.get('inventory',{}))
            self.cached_telemetry=telemetry
            self.cache_time=now
            return dict(telemetry)

    def processes(self):
        names = {str(x.info.get('name') or '').lower() for x in psutil.process_iter(['name'])}
        wanted = [str(n).lower() for n in self.config.get('auto_detect',{}).get('process_names') or ['codex.exe','claude.exe']]
        return {Path(n).stem: n in names for n in wanted}

    def status(self):
        t=self.telemetry()
        t.update({
            'connected':True,'mode':self.mode(),
            'rgb_enabled':bool(self.config.get('rgb',{}).get('enabled')),
            'fans_enabled':bool(self.config.get('fans',{}).get('enabled')),
            'auto_enabled':bool(self.config.get('auto_detect',{}).get('enabled')),
            'processes':self.processes(), 'message':self.last_message,
            'hardware':self.config.get('hardware',{}), 'sensor_connected':t['cpu_temp'] is not None,
            'telegram_enabled': bool(self.config.get('telegram',{}).get('token') and self.config.get('telegram',{}).get('allowed_user_id')
                                     and not getattr(self,'telegram_bot',{}).get('error')),
            'telegram_bot': dict(getattr(self,'telegram_bot',{}) or {}),
            'updated_at':datetime.now().isoformat(timespec='seconds'),
            'started_at':self.started,'alerts_enabled':self.config.get('alerts',{}).get('enabled',True),
            'monitor_timeout_seconds':int(self.config.get('monitor_timeout_seconds',60)),
            'eco_cpu_max_percent':int(self.config.get('eco_cpu_max_percent',90)),
            'integrations':self.integrations,
            'jobs':dict(self.jobs),
            'energy':self.energy_summary(),
            'rgb_color':self.config.get('rgb',{}).get('normal_color','#ffffff'),
            'rgb_brightness':int(self.config.get('rgb',{}).get('brightness',100)),
            'rgb_off':bool(self.state.get('rgb_off')),
            'rgb_palette':self.rgb_palette(),
            'boost':self.booster.info(),'fps':self.live_fps,
            'anim_style':self.config.get('ui',{}).get('anim_style','liquid'),
            'rgb_excluded':list(self.rgb_excluded()),
            'fans_eco':bool(self.state.get('fans_eco')),
            'fans_level':self.state.get('fans_level') or ('eco' if self.state.get('fans_eco') else 'normal'),
            'fans_levels_ready':self.fans_levels_ready() if self.config.get('fans',{}).get('enabled') else False,
            'fans_manual_ready':self.fans_manual_ready() if self.config.get('fans',{}).get('enabled') else False,
            'fans_custom':dict(self.state.get('fans_custom') or {}),
            'fans_presets':[{'id':p['id'],'name':p.get('name',''),'base':p.get('base','normal'),'n':len(p.get('custom') or {})} for p in self.fan_presets()],
            'fans_preset':self.state.get('fans_preset') or '',
            'fans_mine':bool(self.state.get('fans_mine')),
            'apps':self.apps_info(),
            'fans_mine_n':len(self.fans_mine_saved()),
            'fans_profiles_outdated':self.fans_profiles_outdated() if self.config.get('fans',{}).get('enabled') else False,
            'pc':self.pc_info(),
            'live':self.history.latest(),
        })
        return t

    def auto_loop(self, stop_event):
        # Le aperture permanenti di terminali/editor non provano che il lavoro AI sia in corso.
        while not stop_event.wait(10):
            if not self.config.get('auto_detect',{}).get('enabled'):
                self.auto_last=False
                self.auto_idle=None
                self.auto_eco_owned=False
                continue
            try:
                running=any(self.processes().values())
                if running:
                    if not self.auto_last and not self.manual_override:
                        if self.mode()=='normal':  # mai sopra una sessione Gaming
                            self.set_mode('eco',manual=False)
                            self.auto_eco_owned=True
                    self.auto_idle=None
                else:
                    if self.auto_last and self.auto_eco_owned:
                        self.auto_idle=time.monotonic()
                    if self.auto_idle is not None and self.auto_eco_owned and not self.manual_override:
                        delay=max(30,int(self.config['auto_detect'].get('restore_delay_seconds',180)))
                        if time.monotonic()-self.auto_idle>=delay:
                            if self.mode()=='eco': self.set_mode('normal',manual=False)
                            self.auto_idle=None
                            self.auto_eco_owned=False
                self.auto_last=running
            except Exception: logging.exception('Auto rilevamento')

    def add_energy(self, watts, seconds, t=None, mode=None):
        today=datetime.now().strftime('%Y-%m-%d')
        with self.lock:
            e=self.state.setdefault('energy',{})
            if e.get('day')!=today: e.update(day=today, day_wh=0.0)
            if e.get('month')!=today[:7]: e.update(month=today[:7], month_wh=0.0)
            wh=watts*seconds/3600
            e['day_wh']+=wh; e['month_wh']+=wh
            self.add_stats(today, wh, watts, seconds, t or {}, mode)
            if time.monotonic()-getattr(self,'energy_saved',0)>60:
                json_save(STATE_FILE,self.state); self.energy_saved=time.monotonic()

    def add_stats(self, today, wh, watts, seconds, t, mode):
        """Storico permanente: totali da sempre, giorno per giorno (oltre un anno), mese per mese e record."""
        price=float(self.config.get('energy',{}).get('price_eur_kwh',0.30))
        st=self.state.setdefault('stats',{})
        if not st.get('since'):
            # Prima volta: si parte dal consumo del mese già contato, per non ricominciare da zero.
            e=self.state.get('energy',{})
            seed=float(e.get('month_wh',0.0))-wh if e.get('month')==today[:7] else 0.0
            st.update(since=today, total_wh=max(0.0,seed), total_cost=max(0.0,seed)/1000*price, on_s=0.0, modes={})
        cost=wh/1000*price
        st['total_wh']=st.get('total_wh',0.0)+wh; st['total_cost']=st.get('total_cost',0.0)+cost; st['on_s']=st.get('on_s',0.0)+seconds
        if mode:
            ms=st.setdefault('modes',{}); ms[mode]=ms.get(mode,0.0)+seconds
            mw=st.setdefault('mode_wh',{}); mw[mode]=mw.get(mode,0.0)+wh
        d=st.setdefault('days',{}).setdefault(today,{'wh':0.0,'cost':0.0,'s':0.0,'peak':0.0})
        d['wh']+=wh; d['cost']+=cost; d['s']+=seconds; d['peak']=max(d['peak'],round(watts,1))
        if mode: d[mode]=d.get(mode,0.0)+seconds
        for k in ('cpu_temp','gpu_temp'):
            v=t.get(k)
            if isinstance(v,(int,float)): d[k]=max(d.get(k,0),round(v,1))
        m=st.setdefault('months',{}).setdefault(today[:7],{'wh':0.0,'cost':0.0,'s':0.0})
        m['wh']+=wh; m['cost']+=cost; m['s']+=seconds
        rec=st.setdefault('records',{})
        for key,val in (('peak_w',watts),('cpu_temp',t.get('cpu_temp')),('gpu_temp',t.get('gpu_temp')),('day_wh',d['wh'])):
            if isinstance(val,(int,float)) and val>rec.get(key,{}).get('v',-1): rec[key]={'v':round(val,1),'at':today}
        if len(st['days'])>420:
            for k in sorted(st['days'])[:-400]: st['days'].pop(k,None)

    def stats_summary(self):
        """Riepilogo per la pagina Consumi e il bot: totali, medie, record, ultimi 30 giorni e 12 mesi."""
        with self.lock: st=json.loads(json.dumps(self.state.get('stats',{})))
        price=float(self.config.get('energy',{}).get('price_eur_kwh',0.30))
        days=st.get('days',{}); n=max(1,len(days))
        kwh=st.get('total_wh',0.0)/1000; on_h=st.get('on_s',0.0)/3600
        last30=[{'day':k,'kwh':round(v['wh']/1000,3),'cost':round(v['cost'],2),'hours':round(v['s']/3600,1),'peak':v.get('peak'),
                 'cpu_temp':v.get('cpu_temp'),'gpu_temp':v.get('gpu_temp'),
                 'modes':{m:round(v.get(m,0)/3600,1) for m in ('eco','normal','gaming') if v.get(m)}} for k,v in sorted(days.items())[-30:]]
        months=[{'month':k,'kwh':round(v['wh']/1000,2),'cost':round(v['cost'],2),'hours':round(v['s']/3600,1)} for k,v in sorted(st.get('months',{}).items())[-12:]]
        games=self.state.get('games') or {}
        return {'since':st.get('since'),'price_eur_kwh':price,
                'total_kwh':round(kwh,2),'total_cost':round(st.get('total_cost',0.0),2),'co2_kg':round(kwh*0.26,1),
                'on_hours':round(on_h,1),'avg_w':round(st.get('total_wh',0.0)/on_h) if on_h>0.05 else None,
                'avg_day_kwh':round(kwh/n,2),'avg_day_cost':round(st.get('total_cost',0.0)/n,2),'days_count':len(days),
                'year_cost':round(st.get('total_cost',0.0)/n*365,0) if len(days)>=3 else None,
                'modes':{m:round(v/3600,1) for m,v in (st.get('modes') or {}).items()},
                'gaming_hours':round(sum(int(g.get('seconds',0)) for g in games.values())/3600,1),
                'freed_total':int(self.state.get('optimize_freed_total',0)),
                'records':st.get('records',{}),'days':last30,'months':months}

    def energy_summary(self):
        price=float(self.config.get('energy',{}).get('price_eur_kwh',0.30))
        today=datetime.now().strftime('%Y-%m-%d')
        with self.lock: e=dict(self.state.get('energy',{}))
        day=e.get('day_wh',0.0)/1000 if e.get('day')==today else 0.0
        month=e.get('month_wh',0.0)/1000 if e.get('month')==today[:7] else 0.0
        # Proiezione a fine mese dalla media dei giorni già trascorsi.
        now=datetime.now()
        days=calendar.monthrange(now.year,now.month)[1]
        elapsed=now.day-1+(now.hour*60+now.minute)/1440
        forecast=month/elapsed*days if elapsed>=1 else None
        return {'today_kwh':round(day,3),'month_kwh':round(month,2),'price_eur_kwh':price,
                'today_cost':round(day*price,2),'month_cost':round(month*price,2),
                'forecast_kwh':round(forecast,1) if forecast else None,'forecast_cost':round(forecast*price,2) if forecast else None}

    def monitor_loop(self, stop_event):
        active={'cpu':False,'gpu':False}
        cooldown={'cpu':0.0,'gpu':0.0}
        last=time.monotonic()
        threading.Thread(target=self.rgb_watch, args=(stop_event,), daemon=True, name='led-keeper').start()
        while not stop_event.wait(12):
            try:
                t=self.telemetry()
                now=time.monotonic()
                if t.get('power'): self.add_energy(t['power']['total'], min(60.0, now-last), t, self.mode())
                try: self.eco_sleep_check()
                except Exception: logging.exception('Sospensione AI ECO')
                try: self.ai_done_check()
                except Exception: logging.exception('Fine lavoro AI')
                last=now
                try: self.temps_track(t)
                except Exception: logging.exception('Storico temperature')
                # Protezione sempre attiva (anche ad avvisi spenti): CPU calda con ventole case rallentate.
                # Con le ventole del case spente conta anche la GPU, che scarica il calore dentro il case.
                hot = [f'{n.upper()} a {t[n+"_temp"]:.0f}°C' for n, limit in (('cpu', FAN_SAFETY_TEMP), ('gpu', FAN_SAFETY_TEMP_GPU))
                       if (t.get(n+'_temp') or 0) >= limit and (n == 'cpu' or self.state.get('fans_level') == 'off')]
                if self.state.get('fans_eco') and hot:
                    msg=self.fans_level('normal')
                    self.log_event(f'🌡 {", ".join(hot)}: {msg}')
                    self.notify(f'🌡 {", ".join(hot)}: ventole riportate al profilo normale.')
                if not self.config.get('alerts',{}).get('enabled',True):
                    active={'cpu':False,'gpu':False}
                    continue
                try: self.temps_alerts(t)
                except Exception: logging.exception('Avvisi sensori')
                hw=self.config.get('hardware',{})
                for name,label in [('cpu',('CPU '+hw.get('cpu','')).strip()),('gpu',('GPU '+hw.get('gpu','')).strip())]:
                    val=t.get(name+'_temp')
                    if val is None: continue
                    limit=float(self.config.get('alerts',{}).get(name+'_temp',87 if name=='cpu' else 82))
                    if val >= limit and not active[name]:
                        active[name]=True
                        if time.monotonic()-cooldown[name]>1200:
                            msg=f'⚠️ Temperatura alta: {label} {val:.0f}°C (soglia {limit:.0f}°C). Controlla il raffreddamento.'
                            self.log_event(msg)
                            self.notify(msg)
                            cooldown[name]=time.monotonic()
                    elif val <= limit-6 and active[name]:
                        active[name]=False
                        msg=f'✅ Temperatura {label} rientrata: {val:.0f}°C.'
                        self.log_event(msg)
                        self.notify(msg)
            except Exception:
                logging.exception('Monitor termico')
