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
import subprocess
import threading
import time
import sys
from collections import deque
from urllib.request import urlopen
import psutil
import energy_model
import gaming_boost
import pc_power

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
logging.basicConfig(filename=LOG_FILE, level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s', encoding='utf-8')

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
        return {'cpu_temp':None,'fans':[],'cpu_power':None}
    try:
        with urlopen(url, timeout=0.6) as response:
            if int(response.headers.get('Content-Length', 0)) > 1_000_000: raise ValueError('JSON troppo grande')
            tree = json.loads(response.read(1_000_001))
    except Exception:
        return {'cpu_temp':None,'fans':[],'cpu_power':None}
    candidates, fans, cpu_power = [], [], []
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
                candidates.append((score, value))
            if (kind == 'fan' or 'rpm' in str(node.get('Value','')).lower()) and 0 <= value < 10000:
                if len(fans) < 12:
                    import discovery
                    fans.append({'name':name or 'Ventola', 'rpm':round(value), 'ctl':discovery.fan_control_id(str(node.get('SensorId','')))})
            # Potenza del processore: il sensore "Package" comprende core, cache e grafica integrata.
            if re.search(r'/(amd|intel)cpu/\d+/power/', sensor_id) and 'package' in name.lower() and 0 <= value < 500:
                cpu_power.append(value)
        for child in node.get('Children', []): walk(child, trail + [name])
    walk(tree, [])
    return {'cpu_temp': sorted(candidates, reverse=True)[0][1] if candidates else None,'fans':fans,
            'cpu_power': cpu_power[0] if cpu_power else None}

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
        self.cache_time = 0.0
        self.cached_telemetry = None
        self.auto_previous_enabled = False
        self.auto_eco_owned = False
        self.telegram_pair = None
        self.integrations = []
        self.discover_lock = threading.Lock()
        self.jobs = {}
        self.disk_prev = None
        self.video_timeout = (0.0, None)
        self.screen_off_at = 0.0
        self.power_plan = None
        self.booster = gaming_boost.Booster(config, state=self.state, save=self.save_state,
                                            notify=lambda m: self.notify(m), log=lambda m: self.log_event(m))
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

    def optimize_extra(self):
        o = self.config.get('optimize', {})
        last = int(self.state.get('optimize_last_auto') or 0)
        return {'history': list(self.state.get('optimize_history') or [])[:12], 'freed_total': int(self.state.get('optimize_freed_total', 0)),
                'auto': bool(o.get('auto')), 'auto_last': last or None, 'auto_next': (last + 7 * 86400) if o.get('auto') and last else None,
                'large': getattr(self, 'large_report', None), 'health': getattr(self, 'disk_report', None), 'net': getattr(self, 'net_report', None)}

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
                if self.booster.active: self.booster.sample(self.telemetry())
                self.auto_gaming(game, gaming)
            except Exception: logging.exception('Gaming Boost')

    def auto_gaming(self, game, gaming):
        now = time.monotonic()
        if game:
            self.game_gone = None
            if (self.booster.settings()['auto'] and not gaming and not self.gaming_owned and not self.gaming_declined):
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
        return {'boost': self.booster.info(), 'games': [dict({k: g[k] for k in ('id', 'name', 'store', 'size', 'last', 'playtime', 'cover', 'hidden')},
                                                             icon=bool(g.get('exe')))
                                                        for g in self.booster.games(force)],
                'history': self.booster.history()[:12], 'apps': gaming_boost.user_apps()[:40],
                'fans': cfg.get('fans', {}).get('gaming_level', 'normal'), 'fans_enabled': bool(cfg.get('fans', {}).get('enabled')),
                'rgb_color': cfg.get('rgb', {}).get('gaming_color', ''), 'rgb_enabled': bool(cfg.get('rgb', {}).get('enabled')),
                'palette': self.rgb_palette()}

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

    def rgb_profile(self, eco):
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
        def run():
            import openrgb_sdk
            try:
                self.openrgb_ready()
                if eco:
                    saved = self.state.get('rgb_saved') if self.state.get('rgb_off') else None
                    snaps, done = openrgb_sdk.all_off(saved, exclude=self.rgb_excluded())
                    with self.lock:
                        self.state.update(rgb_saved=snaps, rgb_off=True); json_save(STATE_FILE, self.state)
                else:
                    done = openrgb_sdk.all_restore(self.state['rgb_saved'], cfg.get('normal_color', '#ffffff'), self.rgb_excluded())
                    with self.lock:
                        self.state.update(rgb_off=False); self.state.pop('rgb_saved', None); json_save(STATE_FILE, self.state)
                self.log_event('RGB ' + ('spenti' if eco else 'riaccesi') + ': ' + (', '.join(done) or 'nessun dispositivo'))
            except Exception as ex:
                self.log_event('OpenRGB non raggiungibile: ' + str(ex)[:200])
        # Il primo avvio del server richiede qualche secondo: non bloccare la finestra.
        threading.Thread(target=run, daemon=True, name='openrgb').start()
        return 'RGB: ' + ('spegnimento LED' if eco else 'riaccensione LED') + ' in corso'

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
            ctls = [x for x in c.controllers() if x['name'] not in self.rgb_excluded()]
        self.store_leds(ctls)
        return [{'key': openrgb_sdk.key(x), 'name': x['name'], 'type': x['type'], 'leds': leds_estimate(x),
                 'color': colors.get(openrgb_sdk.key(x), '')} for x in ctls]

    def count_leds(self):
        import openrgb_sdk
        with openrgb_sdk.Client() as c: self.store_leds(c.controllers())

    def store_leds(self, ctls):
        """LED alimentati dal PC: servono alla stima del consumo dell'illuminazione."""
        total = sum(leds_estimate(x) for x in ctls)
        with self.lock:
            if total and self.state.get('rgb_leds') != total:
                self.state['rgb_leds'] = total; json_save(STATE_FILE, self.state)

    def rgb_color(self, color, brightness=100, device=None, remember=True):
        """Un colore per tutti i dispositivi (device=None) o per uno solo; luminosità 0-100%."""
        import openrgb_sdk
        if not isinstance(color, str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', color): raise ValueError('Colore non valido')
        if type(brightness) is not int or not 0 <= brightness <= 100: raise ValueError('Luminosità 0–100')
        scaled = '#' + ''.join(f'{round(int(color[i:i+2], 16) * brightness / 100):02x}' for i in (1, 3, 5))
        self.openrgb_ready()
        done = []
        with openrgb_sdk.Client() as c:
            for x in c.controllers():
                if (device and openrgb_sdk.key(x) != device) or x['name'] in self.rgb_excluded(): continue
                if openrgb_sdk.leds_set(c, x, openrgb_sdk.color(scaled), allow_off_mode=False): done.append(x['name'])
            c.controllers()
        if not done: raise RuntimeError('Nessun dispositivo accetta un colore fisso')
        with self.lock:
            rgb = self.config.setdefault('rgb', {})
            if remember:   # i colori temporanei (Gaming) non diventano il colore normale
                rgb['brightness'] = brightness
                if device: rgb.setdefault('device_colors', {})[device] = color
                else: rgb.update(normal_color=color, device_colors={})
                json_save(CONFIG_FILE, self.config)
                self.state.pop('rgb_gaming', None)
            # I LED sono di nuovo accesi con colori scelti: il prossimo ECO salverà questi.
            self.state.update(rgb_off=False); self.state.pop('rgb_saved', None); json_save(STATE_FILE, self.state)
        msg = 'Colore ' + color.upper() + f' ({brightness}%) su ' + ', '.join(dict.fromkeys(done))
        self.log_event('RGB: ' + msg)
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
        if not any((d / name).is_file() for d in (exe.parent / 'Configurations', exe.parent)):
            raise RuntimeError('Fan Control: profilo '+name+' assente')
        if name == discovery.FAN_FILES[profile] and discovery.task_exists(task):
            # Fan Control gira come amministratore: lo raggiungiamo con l'attività già autorizzata.
            cmd(['schtasks', '/run', '/tn', task], 15)
            with self.lock:
                # Un livello scelto azzera le regolazioni fatte a mano sulle singole ventole.
                self.state.update(fans_level=level, fans_pump=bool(level == 'off' and keep_pump), fans_eco=level in ('eco','off'), fans_custom={})
                json_save(STATE_FILE, self.state)
            detail = {'normal': ' (BIOS)', 'max': ' (tutte: case, radiatore, pompa e scheda video al 100%)',
                      'off': ' (tutte ferme' + (f', pompa al {discovery.PUMP_MIN_PERCENT}%' if keep_pump else ', anche la pompa') +
                             '; tornano normali da sole se CPU o GPU arrivano a 75 °C)',
                      'eco': ' (solo case, radiatore e pompa al BIOS)'}
            return 'Ventole: ' + FAN_LEVEL_NAMES[level] + detail[level]
        opts = dict(cwd=str(exe.parent), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if os.name == 'nt': opts['creationflags'] = subprocess.CREATE_NO_WINDOW
        subprocess.Popen([str(exe),'-c',name],**opts)
        return 'Ventole: richiesto profilo '+name+' (AIO escluso nei profili utente)'

    def fans_manual_ready(self):
        """Profili "Manuale" creati e scrivibili: serve aver premuto Configura/Aggiorna profili da questa versione."""
        import discovery
        exe = Path(self.config.get('fans', {}).get('fancontrol_exe', ''))
        f = exe.parent / 'Configurations' / discovery.FAN_FILES['manual_a']
        at, ready = getattr(self, 'fans_manual_cache', (0.0, False))
        if time.monotonic() - at > 60:
            ready = f.is_file() and os.access(f, os.W_OK) and discovery.task_exists(discovery.FAN_TASKS['manual_a'])
            self.fans_manual_cache = (time.monotonic(), ready)
        return ready

    def fan_set(self, ident, percent):
        """Una sola ventola a velocità fissa (0–100%) o di nuovo come il profilo scelto (percent None).
        Le altre restano come il livello attuale (Spente/ECO/Normale/Massimo)."""
        import discovery
        cfg = self.config.get('fans', {})
        if not cfg.get('enabled'): raise RuntimeError('Gestione ventole non attiva')
        if not isinstance(ident, str) or not re.fullmatch(r'/[A-Za-z0-9_/-]{3,80}', ident): raise ValueError('Ventola non valida')
        if percent is not None and (type(percent) is not int or not 0 <= percent <= 100): raise ValueError('Velocità 0–100%')
        exe = Path(cfg.get('fancontrol_exe', ''))
        folder = exe.parent / 'Configurations'
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
        if percent is not None and discovery.is_pump(name, ident) and percent < discovery.PUMP_MIN_PERCENT:
            raise ValueError(f'La pompa non scende sotto il {discovery.PUMP_MIN_PERCENT}%: raffredda il processore')
        custom = {k: v for k, v in (self.state.get('fans_custom') or {}).items() if isinstance(v, int)}
        if percent is None: custom.pop(ident, None)
        else: custom[ident] = percent
        for ctl in ctls:
            v = custom.get(str(ctl.get('Identifier', '')))
            if v is not None:
                ctl['Enable'] = ctl['ManualControl'] = True
                ctl['ManualControlValue'] = v
                ctl['SelectedFanCurve'] = None
        slot = 'manual_b' if self.state.get('fans_slot') == 'manual_a' else 'manual_a'
        (folder / discovery.FAN_FILES[slot]).write_text(json.dumps(prof, indent=2), encoding='utf-8')
        cmd(['schtasks', '/run', '/tn', discovery.FAN_TASKS[slot]], 15)
        with self.lock:
            self.state.update(fans_custom=custom, fans_slot=slot); json_save(STATE_FILE, self.state)
        nice = name.replace('CPU Fan', 'Radiatore').replace('Pump Fan', 'Pompa').replace('System Fan', 'Ventola case')
        msg = f'{nice}: ' + (f'{percent}% fisso' if percent is not None else 'torna al profilo ' + FAN_LEVEL_NAMES.get(level, level))
        self.log_event('Ventole · ' + msg)
        return msg

    def fan_guard_loop(self, stop_event):
        """Con le ventole spente (anche radiatore e pompa) la CPU può scaldare in pochi secondi:
        temperature ogni 2 s e ritorno al profilo normale a 75 °C o se i sensori smettono di rispondere."""
        blind = 0
        while not stop_event.wait(FAN_GUARD_SECONDS):
            slow = any(isinstance(v, int) and v < 30 for v in (self.state.get('fans_custom') or {}).values())
            if self.state.get('fans_level') != 'off' and not slow:
                blind = 0; continue
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

    def setup_fans(self):
        """Crea i profili ventole PC ECO (una conferma UAC) e li collega."""
        import discovery
        cfg = self.config.get('fans', {})
        exe = cfg.get('fancontrol_exe') or discovery.find_fancontrol()
        if not exe: raise RuntimeError('Fan Control non trovato')
        percent = int(cfg.get('eco_percent', 40))
        chosen = discovery.fancontrol_setup(exe, percent, ROOT / 'fan_profiles')
        self.fans_ready_cache = (0.0, False)
        with self.lock:
            self.config.setdefault('fans', {}).update(eco_profile=discovery.FAN_FILES['eco'], normal_profile=discovery.FAN_FILES['normal'],
                                                      profiles_version=discovery.FAN_PROFILES_VERSION)
            json_save(CONFIG_FILE, self.config)
        self.discover()
        msg = f'Ventole configurate: ECO porta al {percent}% ' + ', '.join(chosen) + ' (radiatore e pompa esclusi)'
        self.log_event(msg)
        return msg

    def set_mode(self, value, manual=True, reason='', quiet=False):
        if value not in MODES: raise ValueError('Modalità sconosciuta')
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
            # Gaming Boost: parte con Gaming e rimette tutto com'era quando si passa ad altra modalità.
            boost = (lambda: self.booster.start()) if value == 'gaming' else (lambda: self.booster.stop())
            for cb in (lambda: self.rgb_mode(value), lambda: self.fans_level(fans), boost):
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
                for dev, c in (rgb.get('device_colors') or {}).items(): self.rgb_color(c, bright, dev, remember=False)
            finally:
                self.state.pop('rgb_gaming', None); self.save_state()
        if value == 'gaming' and gaming_color:
            msg = self.rgb_color(gaming_color, int(rgb.get('brightness', 100)), remember=False)
            self.state['rgb_gaming'] = True; self.save_state()
            return 'Luci Gaming: ' + msg
        eco_off = value == 'eco' and self.eco_settings()['leds_off']
        note = self.rgb_profile(eco_off) if eco_off or not notes else ''
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

    def pc_info(self):
        with self.lock: plan = dict(self.power_plan) if self.power_plan else None
        if plan: plan['seconds_left'] = None if plan['at'] is None else max(0, round(plan['at'] - time.time()))
        boot = psutil.boot_time()
        return {'uptime_s': round(time.time() - boot), 'boot': datetime.fromtimestamp(boot).isoformat(timespec='minutes'),
                'pending': plan, 'hibernate': pc_power.hibernate_available(),
                'net': self.state.get('inventory', {}).get('net')}

    def relay_compose(self):
        net = self.state.get('inventory', {}).get('net') or {}
        tg = self.config.get('telegram', {})
        if not net.get('mac'): raise RuntimeError('Scheda di rete via cavo non trovata: premi "Cerca di nuovo" in Collegamenti')
        return pc_power.relay_compose(tg.get('token'), tg.get('allowed_user_id'), net['mac'], net.get('ip', ''), net.get('broadcast', '255.255.255.255'))

    def wol_setup(self):
        import discovery
        net = self.state.get('inventory', {}).get('net') or {}
        if not net.get('name'): raise RuntimeError('Scheda di rete via cavo non trovata')
        if not discovery.run_elevated(discovery.wol_enable_script(net['name']), wait=True): raise RuntimeError('Conferma amministratore annullata')
        inv = discovery.hardware_inventory()
        if inv:
            with self.lock: self.state['inventory'] = inv; json_save(STATE_FILE, self.state)
        return 'Wake-on-LAN attivato su ' + net['name']

    def log_event(self, message):
        record = {'at':datetime.now().isoformat(timespec='seconds'), 'message':str(message)[:400]}
        self.events.appendleft(record)
        logging.info('%s', message)

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
        if 'alerts_enabled' in new and type(new['alerts_enabled']) is not bool:
            raise ValueError('alerts_enabled deve essere true/false')
        with self.lock:
            if 'eco_cpu_max_percent' in new: self.config['eco_cpu_max_percent']=new['eco_cpu_max_percent']
            if 'monitor_timeout_seconds' in new: self.config['monitor_timeout_seconds']=new['monitor_timeout_seconds']
            if 'restore_delay_seconds' in new: self.config.setdefault('auto_detect',{})['restore_delay_seconds']=new['restore_delay_seconds']
            if 'alerts_enabled' in new: self.config.setdefault('alerts',{})['enabled']=new['alerts_enabled']
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
                'ram_total':round(mem.total/1024**3,1), 'fans':sensors['fans'],
                'cpu_power':sensors.get('cpu_power'),
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
            'boost':self.booster.info(),
            'anim_style':self.config.get('ui',{}).get('anim_style','liquid'),
            'rgb_excluded':list(self.rgb_excluded()),
            'fans_eco':bool(self.state.get('fans_eco')),
            'fans_level':self.state.get('fans_level') or ('eco' if self.state.get('fans_eco') else 'normal'),
            'fans_levels_ready':self.fans_levels_ready() if self.config.get('fans',{}).get('enabled') else False,
            'fans_manual_ready':self.fans_manual_ready() if self.config.get('fans',{}).get('enabled') else False,
            'fans_custom':dict(self.state.get('fans_custom') or {}),
            'fans_profiles_outdated':self.fans_profiles_outdated() if self.config.get('fans',{}).get('enabled') else False,
            'pc':self.pc_info(),
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
        while not stop_event.wait(12):
            try:
                t=self.telemetry()
                now=time.monotonic()
                if t.get('power'): self.add_energy(t['power']['total'], min(60.0, now-last), t, self.mode())
                try: self.eco_sleep_check()
                except Exception: logging.exception('Sospensione AI ECO')
                last=now
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
