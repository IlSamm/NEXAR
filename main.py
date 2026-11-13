"""NEXAR - Windows agent + authenticated responsive web dashboard."""
import hmac
import logging
import os
from pathlib import Path
import threading
import re
import sys
import time
from contextlib import asynccontextmanager
from collections import defaultdict, deque

from fastapi import FastAPI, Header, HTTPException, Request, Depends
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
import psutil
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import uvicorn

import hashlib
import json
from urllib.parse import parse_qsl

from core import ROOT, ASSET_ROOT, CONFIG_FILE, DATA_DIR, FROZEN, INSTALL_DIR, MIGRATED_FROM, Control, json_load, start_rtss
from telegram_bot import TelegramBot
from tunnel import TUNNEL_PORT, Tunnel
import gateway
import beacon as beacon_mod
import control_plus
import remote_control
from updater import Updater
from version import VERSION

if not CONFIG_FILE.exists():
    import inizializza  # genera una chiave sicura sul primo avvio
config = json_load(CONFIG_FILE,{})
key = str(config.get('access_token',''))
if len(key) < 28 or key == 'GENERATO_DALL_INSTALLAZIONE':
    raise RuntimeError('Credenziale non sicura: esegui inizializza.py e configura access_token.')
controller = Control(config)
if MIGRATED_FROM: controller.log_event(f'Dati portati da {MIGRATED_FROM} a {DATA_DIR}')
updater = Updater(controller, INSTALL_DIR, DATA_DIR, FROZEN)
stop = threading.Event()
failures = defaultdict(deque)

tunnel = None
bridge = None
beacon = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global tunnel, bridge, beacon
    bot = TelegramBot(controller)
    controller.notify = bot.notify
    tunnel = Tunnel(controller, app)
    bot.tunnel = tunnel
    bot.updater = updater
    # App per Mac: il PC pubblica (cifrato) l'indirizzo del tunnel, che cambia a ogni avvio.
    beacon = beacon_mod.Beacon(controller.config, save=controller._save_config, get_url=lambda: tunnel.url,
                               info=lambda: {'bot': (getattr(controller, 'telegram_bot', None) or {}).get('username', ''), 'v': VERSION,
                                             # in casa l'app per Mac accende il PC da sola (Wake-on-LAN)
                                             'mac': (controller.state.get('inventory', {}).get('net') or {}).get('mac', ''),
                                             'bc': (controller.state.get('inventory', {}).get('net') or {}).get('broadcast', ''),
                                             # l'app su Umbrel segue così i cambi di indirizzo del PC
                                             'ip': (controller.state.get('inventory', {}).get('net') or {}).get('ip', '')})
    controller.beacon = beacon
    def on_url(url):
        bot.set_webapp(url); beacon.kick.set()
    tunnel.on_url = on_url
    threading.Thread(target=beacon.run,args=(stop,),daemon=True,name='mac-beacon').start()
    threading.Thread(target=controller.history.run,args=(stop,),daemon=True,name='history').start()
    threading.Thread(target=controller.planner.run,args=(stop,),daemon=True,name='schedules').start()
    threading.Thread(target=tunnel.run,args=(stop,),daemon=True,name='tunnel').start()
    bridge = gateway.Bridge(lambda: controller.config.get('gateway'), app)
    threading.Thread(target=bridge.run,args=(stop,),daemon=True,name='umbrel-bridge-loop').start()
    t1 = threading.Thread(target=bot.run,args=(stop,),daemon=True,name='telegram')
    t2 = threading.Thread(target=controller.auto_loop,args=(stop,),daemon=True,name='ai-auto')
    t3 = threading.Thread(target=controller.monitor_loop,args=(stop,),daemon=True,name='temperature-alerts')
    t4 = threading.Thread(target=controller.discover,daemon=True,name='discovery')
    t5 = threading.Thread(target=controller.power_loop,args=(stop,),daemon=True,name='power-plan')
    t6 = threading.Thread(target=updater.loop,args=(stop,),daemon=True,name='updater')
    t7 = threading.Thread(target=controller.fan_guard_loop,args=(stop,),daemon=True,name='fan-guard')
    t8 = threading.Thread(target=controller.boost_loop,args=(stop,),daemon=True,name='gaming-boost')
    t9 = threading.Thread(target=controller.optimize_loop,args=(stop,),daemon=True,name='auto-clean')
    threading.Thread(target=controller.net_loop,args=(stop,),daemon=True,name='auto-net').start()
    threading.Thread(target=controller.connections_loop,args=(stop,),daemon=True,name='connections').start()
    t1.start();t2.start();t3.start();t4.start();t5.start();t6.start();t7.start();t8.start();t9.start()
    updater.announce()
    # Avviso "PC acceso" solo dopo un avvio vero di Windows, non a ogni riapertura dell'app.
    import psutil
    # Il messaggio arriva quando sensori, ventole e luci sono collegati (o dopo 3 minuti, dicendo cosa manca).
    if time.time() - psutil.boot_time() < 900:
        threading.Thread(target=controller.boot_report,args=(bot.notify,lambda: bool(bot.webapp_url),stop),daemon=True,name='boot-report').start()
    yield
    stop.set()

app = FastAPI(title='NEXAR',docs_url=None,redoc_url=None,openapi_url=None,lifespan=lifespan)
app.mount('/assets',StaticFiles(directory=str(ASSET_ROOT/'web')),name='assets')

@app.middleware('http')
async def no_cache_and_security(request: Request, call_next):
    if is_bridge(request):
        # Porta aperta sulla rete di casa: risponde solo a Umbrel, e solo se il ponte è attivo.
        g = controller.config.get('gateway') or {}
        if not (g.get('enabled') and request.client and request.client.host == g.get('umbrel_ip')):
            return JSONResponse({'detail':'Accesso consentito solo da Umbrel'}, status_code=403)
    response = await call_next(request)
    if 'no-transform' not in response.headers.get('Cache-Control',''): response.headers['Cache-Control']='no-store'
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['X-Frame-Options']='DENY'
    response.headers['Referrer-Policy']='no-referrer'
    # La Mini App gira dentro Telegram: serve il suo script e il permesso di essere incorniciata da Telegram.
    response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self' https://telegram.org; style-src 'self'; img-src 'self' data: blob:; connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors https://web.telegram.org https://*.telegram.org"
    if is_tunnel(request): del response.headers['X-Frame-Options']
    return response

def is_tunnel(request: Request) -> bool:
    return (request.scope.get('server') or (None, 0))[1] == TUNNEL_PORT

def is_bridge(request: Request) -> bool:
    return (request.scope.get('server') or (None, 0))[1] == gateway.GATEWAY_PORT

def is_remote(request: Request) -> bool:
    """Tutto ciò che arriva dal tunnel è Internet, anche se il socket risulta 127.0.0.1."""
    return is_tunnel(request) or not request.client or request.client.host not in ('127.0.0.1','::1')

def telegram_user(init_data: str) -> int:
    """Verifica la firma della Mini App (docs Telegram: WebAppData) e restituisce l'id utente."""
    token = str(controller.config.get('telegram',{}).get('token',''))
    if not token or not init_data or len(init_data) > 4096: return 0
    fields = dict(parse_qsl(init_data, keep_blank_values=True))
    received = fields.pop('hash', '')
    check = '\n'.join(f'{k}={v}' for k, v in sorted(fields.items()))
    secret = hmac.new(b'WebAppData', token.encode(), hashlib.sha256).digest()
    if not received or not hmac.compare_digest(hmac.new(secret, check.encode(), hashlib.sha256).hexdigest(), received): return 0
    try:
        if time.time() - int(fields.get('auth_date', 0)) > 86400: return 0
        return int(json.loads(fields.get('user', '{}')).get('id', 0))
    except (ValueError, TypeError): return 0

def authorized(request: Request, x_pc_eco_key: str | None = Header(default=None), x_tg_init_data: str | None = Header(default=None)):
    ip = request.headers.get('cf-connecting-ip','tunnel') if is_tunnel(request) else (request.client.host if request.client else 'unknown')
    now=time.monotonic()
    q=failures[ip]
    while q and q[0]<now-60: q.popleft()
    if len(q)>15: raise HTTPException(429,'Troppi tentativi di accesso: riprova fra un minuto')
    allowed = int(controller.config.get('telegram',{}).get('allowed_user_id') or 0)
    if x_tg_init_data and allowed and telegram_user(x_tg_init_data) == allowed:
        q.clear(); return True
    if x_pc_eco_key and controller.devices.check(x_pc_eco_key):
        q.clear(); return True
    if not x_pc_eco_key or not hmac.compare_digest(x_pc_eco_key,key):
        q.append(now)
        raise HTTPException(401,'Chiave di accesso non valida')
    q.clear()
    return True

@app.get('/')
def index(): return FileResponse(ASSET_ROOT/'web'/'index.html',media_type='text/html')

@app.get('/manifest.webmanifest')
def manifest():
    # Safari → Archivio → Aggiungi al Dock: NEXAR si apre come app nella sua finestra.
    return JSONResponse({'name':'NEXAR','short_name':'NEXAR','start_url':'/','scope':'/','display':'standalone',
                         'background_color':'#090b0f','theme_color':'#090b0f',
                         'icons':[{'src':'/assets/icon-512.png','sizes':'512x512','type':'image/png','purpose':'any'}]},
                        media_type='application/manifest+json')

@app.get('/api/status',dependencies=[Depends(authorized)])
def status(request: Request):
    s = controller.status()
    s['webapp'] = tunnel.info() if tunnel else {'url':'','error':'','wanted':False}
    s['remote'] = is_remote(request)
    s['version'] = VERSION
    s['update'] = updater.info()
    return s

@app.get('/api/events',dependencies=[Depends(authorized)])
def events(): return {'events':controller.get_events()}

@app.get('/api/settings',dependencies=[Depends(authorized)])
def settings(): return controller.public_settings()

class Settings(BaseModel):
    eco_cpu_max_percent: int | None = None
    monitor_timeout_seconds: int | None = None
    restore_delay_seconds: int | None = None
    alerts_enabled: bool | None = None
    alerts_sensors: bool | None = None
    cpu_temp_alert: int | None = None
    gpu_temp_alert: int | None = None
    energy_price_cents: int | None = None
    psu_watts: int | None = None
    psu_class: str | None = None
    monitor_watts: int | None = None
    extra_watts: int | None = None
    gaming_fans: str | None = None
    anim_style: str | None = None

@app.get('/api/temps/history',dependencies=[Depends(authorized)])
def temps_history(ids: str = ''):
    want = [i for i in ids.split(',') if i][:40]
    return controller.temps_history(want or None)

@app.post('/api/settings',dependencies=[Depends(authorized)])
def save_settings(data: Settings):
    try:
        return {'ok':True,'settings':controller.update_settings(data.model_dump(exclude_unset=True))}
    except (ValueError,RuntimeError) as ex: raise HTTPException(400,str(ex))

class Mode(BaseModel):
    mode: str
@app.post('/api/mode',dependencies=[Depends(authorized)])
def mode(data: Mode):
    try: return {'ok':True,'message':controller.set_mode(data.mode),'status':controller.status()}
    except (ValueError, RuntimeError, OSError) as ex: raise HTTPException(400,str(ex))

class TelegramSetup(BaseModel):
    token: str

@app.post('/api/telegram/pair', dependencies=[Depends(authorized)])
def start_telegram_pair(payload: TelegramSetup, request: Request):
    # A token for an external bot may only be installed directly from Windows PC.
    if is_remote(request):
        raise HTTPException(403,'Configura il bot dalla dashboard sul PC Windows.')
    try: return {'ok':True,**controller.begin_telegram_pair(payload.token.strip())}
    except ValueError as ex: raise HTTPException(400,str(ex))

class Toggle(BaseModel):
    enabled: bool
@app.post('/api/auto',dependencies=[Depends(authorized)])
def auto(data: Toggle):
    return {'ok':True,'message':controller.set_auto(data.enabled)}

class Profile(BaseModel):
    profile: str
@app.post('/api/rgb',dependencies=[Depends(authorized)])
def rgb(data: Profile):
    if data.profile not in ('eco','normal'): raise HTTPException(400,'Profilo non valido')
    try: return {'ok':True,'message':controller.rgb_profile(data.profile=='eco')}
    except (RuntimeError,OSError,ValueError) as ex: raise HTTPException(400,str(ex))
@app.get('/api/rgb/devices',dependencies=[Depends(authorized)])
def rgb_devices():
    try: return {'devices':controller.rgb_devices()}
    except (RuntimeError,OSError) as ex: raise HTTPException(400,str(ex))

class RgbColor(BaseModel):
    color: str
    brightness: int = 100
    device: str | None = None
@app.post('/api/rgb/color',dependencies=[Depends(authorized)])
def rgb_color(data: RgbColor):
    try: return {'ok':True,'message':controller.rgb_color(data.color,data.brightness,data.device)}
    except (RuntimeError,OSError,ValueError) as ex: raise HTTPException(400,str(ex))

class Palette(BaseModel):
    colors: list[str]
@app.post('/api/rgb/palette',dependencies=[Depends(authorized)])
def rgb_palette(data: Palette):
    try: return {'ok':True,'palette':controller.set_rgb_palette(data.colors),'message':'Colori salvati'}
    except ValueError as ex: raise HTTPException(400,str(ex))

class FanLevel(BaseModel):
    profile: str
    keep_pump: bool | None = None
@app.post('/api/fans',dependencies=[Depends(authorized)])
def fans(data: FanLevel):
    if data.profile not in ('off','eco','normal','max'): raise HTTPException(400,'Profilo non valido')
    try: return {'ok':True,'message':controller.fans_level(data.profile,data.keep_pump)}
    except (RuntimeError,OSError,ValueError) as ex: raise HTTPException(400,str(ex))
def local_only(request: Request):
    # Solo ciò che deve per forza accadere davanti al PC: la prima conferma UAC e il token del bot.
    if is_remote(request):
        raise HTTPException(403,'Operazione disponibile solo dalla app sul PC Windows.')
    return True

def pin_gate(request: Request, x_admin_pin: str | None = Header(default=None)):
    """Da lontano le operazioni delicate chiedono il PIN del controllo remoto (stessi limiti di tentativi)."""
    if not is_remote(request): return True
    try: controller.remote.check_pin(x_admin_pin)
    except remote_control.NeedPin as ex: raise HTTPException(403,str(ex),headers={'X-Need-Pin':'1'})
    except PermissionError as ex: raise HTTPException(403,str(ex))
    return True

def elevator(request: Request):
    """Sul PC decide la finestra UAC (None); da lontano serve l'attività NEXAR Admin già attivata."""
    if not is_remote(request): return None
    if not controller.admin.active():
        raise HTTPException(409,'Attiva prima "Amministratore da remoto" dall\'app sul PC: Impostazioni → Sistema (una conferma sola).')
    return controller.admin

class AdminToggle(BaseModel):
    enabled: bool
@app.get('/api/admin',dependencies=[Depends(authorized)])
def admin_state(request: Request):
    return {**controller.admin.info(),'local':not is_remote(request),'supported':os.name=='nt' and bool(getattr(sys,'frozen',False))}
@app.post('/api/admin/setup',dependencies=[Depends(authorized),Depends(local_only)])
def admin_setup(data: AdminToggle):
    try: return {'ok':True,'message':controller.run_job('admin-setup',controller.admin_setup if data.enabled else controller.admin_remove)}
    except RuntimeError as ex: raise HTTPException(409,str(ex))

@app.post('/api/umbrel/link',dependencies=[Depends(authorized),Depends(pin_gate)])
def umbrel_link(request: Request):
    """Codice per l'app su Umbrel. Il ponte (e la sua regola del firewall) si prepara in background."""
    g = controller.config.get('gateway') or {}
    ip = gateway.guess_umbrel() or g.get('umbrel_ip','')
    if not ip: raise HTTPException(400,"umbrel.local non risponde: controlla che Umbrel sia acceso e nella stessa rete del PC.")
    remote = is_remote(request)
    if remote and not g.get('firewall') and not controller.admin.active():
        raise HTTPException(409,'Serve una conferma sul PC: premi Collega Umbrel dall\'app sul PC, oppure attiva Amministratore da remoto.')
    fw = (lambda: controller.admin.call('firewall',ip=ip)) if remote else None
    try: code = controller.umbrel_code()
    except RuntimeError as ex: raise HTTPException(400,str(ex))
    if not (g.get('enabled') and g.get('umbrel_ip')==ip):
        try: controller.run_job('umbrel-link',lambda: controller.gateway_setup(True,ip,fw))
        except RuntimeError: pass  # già in corso
    return {'code':code,'url':f'http://{ip}:{gateway.UMBREL_APP_PORT}/#pair={code}','firewall':bool(g.get('firewall'))}

@app.post('/api/discover',dependencies=[Depends(authorized),Depends(pin_gate)])
def discover(request: Request):
    # Da lontano nessuna finestra UAC: resterebbe lì sul PC ad aspettare qualcuno.
    uac = not is_remote(request)
    try: return {'ok':True,'message':controller.run_job('discover',lambda: controller.discover(allow_uac=uac) and 'Collegamenti aggiornati')}
    except RuntimeError as ex: raise HTTPException(409,str(ex))

class Install(BaseModel):
    key: str
@app.post('/api/install',dependencies=[Depends(authorized),Depends(pin_gate)])
def install(data: Install, request: Request):
    import discovery
    if data.key not in discovery.WINGET: raise HTTPException(400,'Programma non previsto')
    admin = elevator(request)
    def run():
        msg=discovery.winget_install(data.key,admin)
        controller.discover(allow_uac=admin is None)
        return msg
    try: return {'ok':True,'message':controller.run_job('install-'+data.key,run)}
    except RuntimeError as ex: raise HTTPException(409,str(ex))

@app.post('/api/autostart/fast',dependencies=[Depends(authorized),Depends(pin_gate)])
def autostart_fast(request: Request):
    import discovery
    admin = elevator(request)
    def run():
        msg = discovery.autostart_fast(admin)
        with controller.lock:
            controller.config['autostart'] = True
            from core import json_save
            json_save(CONFIG_FILE, controller.config)
        controller.discover()
        return msg
    try: return {'ok':True,'message':controller.run_job('autostart-fast',run)}
    except RuntimeError as ex: raise HTTPException(409,str(ex))

class FanOne(BaseModel):
    id: str
    percent: int | None = None
    curve: dict | None = None
@app.post('/api/fans/one',dependencies=[Depends(authorized)])
def fan_one(data: FanOne):
    try: return {'ok':True,'message':controller.fan_set(data.id,data.percent,data.curve)}
    except (RuntimeError,OSError,ValueError) as ex: raise HTTPException(400,str(ex))

class FanName(BaseModel):
    id: str
    name: str = ''
@app.post('/api/fans/name',dependencies=[Depends(authorized)])
def fan_name(data: FanName):
    try: return {'ok':True,'message':controller.fan_name(data.id,data.name)}
    except ValueError as ex: raise HTTPException(400,str(ex))

class FanPreset(BaseModel):
    action: str
    id: str = ''
    name: str = ''
@app.post('/api/fans/preset',dependencies=[Depends(authorized)])
def fan_preset(data: FanPreset):
    try:
        if data.action == 'save': msg = controller.fan_preset_save(data.name)
        elif data.action == 'apply': msg = controller.fan_preset_apply(data.id)
        elif data.action == 'delete': msg = controller.fan_preset_delete(data.id)
        else: raise ValueError('Azione non valida')
        return {'ok':True,'message':msg}
    except (RuntimeError,OSError,ValueError) as ex: raise HTTPException(400,str(ex))

@app.post('/api/fans/check',dependencies=[Depends(authorized)])
def fans_check():
    try: return {'ok':True,**controller.fans_check()}
    except (RuntimeError,OSError) as ex: raise HTTPException(400,str(ex))

@app.post('/api/fans/setup',dependencies=[Depends(authorized),Depends(pin_gate)])
def fans_setup(request: Request):
    admin = elevator(request)
    try: return {'ok':True,'message':controller.run_job('fans-setup',lambda: controller.setup_fans(admin))}
    except RuntimeError as ex: raise HTTPException(409,str(ex))

@app.post('/api/fancontrol/open',dependencies=[Depends(authorized)])
def fancontrol_open():
    exe=controller.config.get('fans',{}).get('fancontrol_exe','')
    if not exe or not Path(exe).is_file(): raise HTTPException(404,'Fan Control non trovato')
    os.startfile(exe)
    return {'ok':True,'message':'Fan Control aperto'}

@app.post('/api/autostart',dependencies=[Depends(authorized),Depends(pin_gate)])
def autostart(data: Toggle, request: Request):
    import discovery
    from core import json_save
    admin = controller.admin if is_remote(request) and controller.admin.active() else None
    with controller.lock:
        controller.config['autostart']=data.enabled
        json_save(CONFIG_FILE,controller.config)
    try:
        discovery.autostart_set(data.enabled)
        if not data.enabled: discovery.autostart_fast_off(admin)
    except OSError as ex: raise HTTPException(400,str(ex))
    try: controller.run_job('discover',controller.discover)
    except RuntimeError: pass  # una ricerca è già in corso e vedrà il nuovo valore
    return {'ok':True,'message':'Avvio con Windows '+('attivato' if data.enabled else 'disattivato')}

class PowerAction(BaseModel):
    action: str
    minutes: int = 0
    after_ai: bool = False
@app.post('/api/power',dependencies=[Depends(authorized)])
def pc_power_action(data: PowerAction):
    try: return {'ok':True,'message':controller.power_action(data.action,data.minutes,data.after_ai)}
    except (ValueError,RuntimeError,OSError) as ex: raise HTTPException(400,str(ex))

@app.get('/api/power/relay',dependencies=[Depends(authorized),Depends(pin_gate)])
def power_relay():
    # Contiene il token del bot: da lontano serve il PIN.
    try: return {'compose':controller.relay_compose(bridge=bool((controller.config.get('gateway') or {}).get('enabled')))}
    except (ValueError,RuntimeError) as ex: raise HTTPException(400,str(ex))

@app.get('/api/power/wake-link',dependencies=[Depends(authorized)])
def power_wake_link():
    # Solo accensione: chi comanda già il PC può averlo anche dal telefono.
    try: return {'url':controller.wake_link()}
    except RuntimeError as ex: raise HTTPException(400,str(ex))

# ---------- Mac e altri dispositivi tramite Umbrel + Tailscale ----------
@app.get('/api/gateway',dependencies=[Depends(authorized)])
def gateway_state(request: Request):
    info = controller.gateway_info(bridge)
    if is_remote(request): info.pop('umbrel_ip', None); info.pop('pc_ip', None)
    return {**info, 'local': not is_remote(request)}

@app.get('/api/gateway/guess',dependencies=[Depends(authorized)])
def gateway_guess(): return {'umbrel_ip': gateway.guess_umbrel()}

class GatewaySetup(BaseModel):
    enabled: bool
    umbrel_ip: str | None = None
@app.post('/api/gateway/setup',dependencies=[Depends(authorized),Depends(pin_gate)])
def gateway_setup(data: GatewaySetup, request: Request):
    admin = elevator(request) if data.enabled else None
    fw = (lambda: admin.call('firewall',ip=data.umbrel_ip or (controller.config.get('gateway') or {}).get('umbrel_ip',''))) if admin else None
    try: return {'ok':True,'message':controller.gateway_setup(data.enabled,data.umbrel_ip,fw),'gateway':controller.gateway_info(bridge)}
    except (ValueError,RuntimeError,OSError) as ex: raise HTTPException(400,str(ex))

@app.post('/api/devices/code',dependencies=[Depends(authorized),Depends(pin_gate)])
def device_code():
    code, ttl = controller.devices.new_code()
    if beacon: beacon.announce_code(code, ttl)
    return {'code':code,'seconds':ttl,'online':bool(tunnel and tunnel.url)}

class Pair(BaseModel):
    code: str
    name: str = ''
@app.post('/api/devices/pair')
def device_pair(data: Pair, request: Request):
    # Senza chiave (il dispositivo non ce l'ha ancora): stesso limite di tentativi dell'accesso.
    ip = request.headers.get('cf-connecting-ip','tunnel') if is_tunnel(request) else (request.client.host if request.client else 'unknown')
    now = time.monotonic(); q = failures[ip]
    while q and q[0]<now-60: q.popleft()
    if len(q)>15: raise HTTPException(429,'Troppi tentativi: riprova fra un minuto')
    try: token, name = controller.devices.pair(data.code, data.name)
    except PermissionError as ex:
        q.append(now); raise HTTPException(403,str(ex))
    q.clear()
    controller.log_event(f'🔗 Nuovo dispositivo collegato: {name}')
    controller.notify(f'🔗 Nuovo dispositivo collegato a NEXAR: {name}. Se non sei stato tu, toglilo da Collegamenti.')
    out = {'ok':True,'token':token,'name':name}
    if beacon: out['beacon'] = beacon.secret(); beacon.kick.set()
    return out

class DeviceId(BaseModel):
    id: str
@app.post('/api/devices/remove',dependencies=[Depends(authorized)])
def device_remove(data: DeviceId):
    try: controller.devices.remove(data.id)
    except ValueError as ex: raise HTTPException(404,str(ex))
    controller.log_event('🔗 Dispositivo scollegato')
    return {'ok':True,'message':'Dispositivo scollegato','devices':controller.devices.list()}

# ---------- più controllo: storico, media, appunti e cartella condivisa ----------
@app.get('/api/history',dependencies=[Depends(authorized)])
def live_history(range: str = '15m'):
    if range == '15m': return {'samples':controller.history.data(),'every':control_plus.SAMPLE_EVERY,'disks':control_plus.disks()}
    if range not in control_plus.RANGES: raise HTTPException(400,'Intervallo non previsto')
    return {'range':range,'step':control_plus.RANGES[range][1],'points':controller.history.range(range)}

@app.get('/api/media',dependencies=[Depends(authorized)])
def media_now():
    return {'playing':control_plus.now_playing()}

class MediaAction(BaseModel):
    action: str
@app.post('/api/media',dependencies=[Depends(authorized)])
def media_action(data: MediaAction):
    try: return {'ok':True,'message':control_plus.media(data.action)}
    except (ValueError,OSError) as ex: raise HTTPException(400,str(ex))

class Schedules(BaseModel):
    rules: list
@app.get('/api/schedules',dependencies=[Depends(authorized)])
def schedules_get():
    return controller.schedules()
@app.post('/api/schedules',dependencies=[Depends(authorized)])
def schedules_set(data: Schedules):
    try: return {'ok':True,**controller.set_schedules(data.rules)}
    except ValueError as ex: raise HTTPException(400,str(ex))

@app.get('/api/clipboard',dependencies=[Depends(authorized)])
def clipboard_read():
    try: return {'text':control_plus.clipboard_get()}
    except OSError as ex: raise HTTPException(409,str(ex))
class ClipText(BaseModel):
    text: str
@app.post('/api/clipboard',dependencies=[Depends(authorized)])
def clipboard_write(data: ClipText, request: Request):
    try: msg = control_plus.clipboard_set(data.text)
    except (ValueError,OSError) as ex: raise HTTPException(400,str(ex))
    if is_remote(request): controller.log_event('📋 Appunti del PC aggiornati da remoto')
    return {'ok':True,'message':msg}

@app.get('/api/files',dependencies=[Depends(authorized)])
def shared_files(request: Request):
    return {'files':control_plus.list_files(),'folder':'Download\\NEXAR' if is_remote(request) else str(control_plus.share_dir()),
            'max_remote':100*1024**2}
@app.post('/api/files/upload',dependencies=[Depends(authorized)])
async def shared_upload(request: Request, name: str):
    try: clean = control_plus.safe_name(name)
    except ValueError as ex: raise HTTPException(400,str(ex))
    if int(request.headers.get('content-length') or 0) > control_plus.UPLOAD_MAX: raise HTTPException(413,'File troppo grande (max 2 GB)')
    folder = control_plus.share_dir(); part = folder / (clean + f'.{os.getpid()}.{time.time_ns()}.part'); size = 0
    try:
        with open(part,'wb') as f:
            async for chunk in request.stream():
                size += len(chunk)
                if size > control_plus.UPLOAD_MAX: raise HTTPException(413,'File troppo grande (max 2 GB)')
                f.write(chunk)
        target = control_plus.free_path(folder, clean); part.replace(target)
    except BaseException:
        part.unlink(missing_ok=True); raise
    controller.log_event(f'📥 File ricevuto: {target.name}')
    if is_remote(request): controller.notify(f'📥 File ricevuto su NEXAR: {target.name} (Download\\NEXAR)')
    return {'ok':True,'message':f'{target.name} salvato in Download\\NEXAR','name':target.name}
@app.get('/api/files/get',dependencies=[Depends(authorized)])
def shared_get(name: str):
    try: f = control_plus.shared_file(name)
    except (ValueError,FileNotFoundError) as ex: raise HTTPException(404,str(ex))
    return FileResponse(f, filename=f.name, headers={'Cache-Control':'no-store'})
@app.post('/api/files/open',dependencies=[Depends(authorized)])
def shared_open():
    os.startfile(str(control_plus.share_dir()))
    return {'ok':True,'message':'Cartella aperta'}

@app.post('/api/power/wol',dependencies=[Depends(authorized),Depends(pin_gate)])
def power_wol(request: Request):
    admin = elevator(request)
    try: return {'ok':True,'message':controller.run_job('wol',lambda: controller.wol_setup(admin))}
    except RuntimeError as ex: raise HTTPException(409,str(ex))

@app.post('/api/update/check',dependencies=[Depends(authorized)])
def update_check():
    try: return {'ok':True,'message':updater.check()['message'],'update':updater.info()}
    except Exception as ex: raise HTTPException(502,'Server degli aggiornamenti non raggiungibile: '+str(ex)[:150])

@app.post('/api/update/install',dependencies=[Depends(authorized)])
def update_install():
    try: return {'ok':True,'message':controller.run_job('update',updater.install)}
    except RuntimeError as ex: raise HTTPException(409,str(ex))

@app.get('/api/update',dependencies=[Depends(authorized)])
def update_state():
    # Letto spesso durante il download per la barra di avanzamento: niente sensori, solo lo stato dell'aggiornamento.
    return {'update':updater.info(),'job':controller.jobs.get('update')}

# ---------- ottimizzazione ----------
import optimizer
import gaming_boost

@app.get('/api/gaming',dependencies=[Depends(authorized)])
def gaming_info(refresh: bool = False):
    return controller.gaming_view(force=refresh)

class BoostSettings(BaseModel):
    game_priority: bool | None = None
    game_mode: bool | None = None
    no_dvr: bool | None = None
    reopen: bool | None = None
    auto: bool | None = None
    mouse: bool | None = None
    apps: dict[str, str] | None = None
    eco_apps: dict[str, str] | None = None
    stop_junk: bool | None = None
    eco_throttle: bool | None = None
    hidden: list[str] | None = None
    covers_online: bool | None = None
    fans: str | None = None
    rgb_color: str | None = None
@app.post('/api/gaming/settings',dependencies=[Depends(authorized)])
def gaming_settings(data: BoostSettings):
    try: return {'ok':True,'message':'Gaming salvato','settings':controller.save_boost_settings(data.model_dump(exclude_none=True))}
    except ValueError as ex: raise HTTPException(400,str(ex))

class GameLaunch(BaseModel):
    id: str
@app.post('/api/gaming/startup-junk',dependencies=[Depends(authorized)])
def gaming_startup_junk(request: Request):
    import discovery
    return {'ok':True,'message':controller.startup_junk_off(None if is_remote(request) else discovery.run_elevated)}

class AppId(BaseModel):
    id: str
class AppPin(BaseModel):
    id: str
    pinned: bool
@app.get('/api/apps',dependencies=[Depends(authorized)])
def apps_list(all: bool = False):
    return controller.apps_view(all)
@app.post('/api/apps/open',dependencies=[Depends(authorized)])
def apps_open(data: AppId):
    try: return {'ok':True,'message':controller.app_open(data.id)}
    except (ValueError,OSError) as ex: raise HTTPException(400,str(ex))
@app.post('/api/apps/close',dependencies=[Depends(authorized)])
def apps_close(data: AppId):
    try: return {'ok':True,'message':controller.app_close(data.id)}
    except (ValueError,OSError) as ex: raise HTTPException(400,str(ex))
@app.post('/api/apps/pin',dependencies=[Depends(authorized)])
def apps_pin(data: AppPin):
    try: return {'ok':True,'message':controller.app_pin(data.id,data.pinned)}
    except ValueError as ex: raise HTTPException(400,str(ex))
class ScreenAction(BaseModel):
    action: str
    id: int | None = None
    force: bool = False
class ScreenSettings(BaseModel):
    view: bool | None = None
    ai_alert: bool | None = None
@app.get('/api/screen/shot',dependencies=[Depends(authorized)])
def screen_shot(request: Request, mon: str | None = None, live: int = 0):
    which = None if mon is None else ('all' if mon == 'all' else int(mon) if mon.isdigit() else 0)
    try: jpg = controller.screen_shot('Telegram' if request.headers.get('x-tg-init-data') else 'dashboard', which, bool(live))
    except PermissionError as ex: raise HTTPException(403,str(ex))
    except RuntimeError as ex: raise HTTPException(409,str(ex))
    # Schermo uguale a prima: nessuna immagine da rimandare, l'anteprima dal vivo costa quasi niente.
    tag = '"' + hashlib.blake2b(jpg, digest_size=10).hexdigest() + '"'
    if request.headers.get('if-none-match') == tag: return Response(status_code=304, headers={'ETag':tag,'Cache-Control':'no-store'})
    return Response(jpg, media_type='image/jpeg', headers={'ETag':tag,'Cache-Control':'no-store'})
@app.get('/api/screen',dependencies=[Depends(authorized)])
def screen_info():
    return controller.screen_view()
@app.post('/api/screen/action',dependencies=[Depends(authorized)])
def screen_action(data: ScreenAction):
    try: return {'ok':True,'message':controller.screen_action(data.action,data.id,data.force)}
    except (ValueError,OSError,psutil.Error) as ex: raise HTTPException(400,str(ex))
@app.post('/api/screen/settings',dependencies=[Depends(authorized)])
def screen_settings(data: ScreenSettings):
    s = controller.set_screen_settings(data.view,data.ai_alert)
    return {'ok':True,'settings':s,'message':'Impostazioni schermo salvate'}

# ---------- audio: cuffie, casse, microfoni e app ----------
class AudioDevice(BaseModel):
    id: str
    volume: int | None = None
    mute: bool | None = None
    default: bool | None = None
class AudioBoost(BaseModel):
    id: str
    db: float | None = None
    eq: str | None = None
    hw: float | None = None
    bands: list[float] | None = None
class AudioApp(BaseModel):
    id: str
    volume: int | None = None
    mute: bool | None = None
def audio_errors(fn):
    try: return {'ok':True,'message':fn()}
    except ValueError as ex: raise HTTPException(400,str(ex))
    except (RuntimeError,OSError) as ex: raise HTTPException(409,str(ex))
def audio_here(request: Request):
    if is_remote(request): raise HTTPException(409,'Si fa dal PC: Windows chiede una conferma sullo schermo. Da lontano puoi usare il controllo remoto.')
@app.get('/api/audio',dependencies=[Depends(authorized)])
def audio_info():
    try: return controller.audio_view()
    except (RuntimeError,OSError) as ex: raise HTTPException(409,'Audio non disponibile: '+str(ex))
@app.post('/api/audio/device',dependencies=[Depends(authorized)])
def audio_device(data: AudioDevice):
    return audio_errors(lambda: controller.audio_device(data.id,data.volume,data.mute,data.default))
@app.post('/api/audio/boost',dependencies=[Depends(authorized)])
def audio_boost(data: AudioBoost):
    return audio_errors(lambda: controller.audio_boost(data.id,data.db,data.eq,data.hw,data.bands))
@app.get('/api/audio/levels',dependencies=[Depends(authorized)])
def audio_levels():
    try: return controller.audio_levels()
    except (RuntimeError,OSError) as ex: raise HTTPException(409,str(ex))
@app.post('/api/audio/mictest',dependencies=[Depends(authorized)])
def audio_mic_test(data: Toggle):
    return audio_errors(lambda: controller.audio_mic_test(data.enabled))
@app.post('/api/audio/app',dependencies=[Depends(authorized)])
def audio_app(data: AudioApp):
    return audio_errors(lambda: controller.audio_app(data.id,data.volume,data.mute))
@app.post('/api/audio/max',dependencies=[Depends(authorized)])
def audio_max():
    return audio_errors(controller.audio_max)
@app.post('/api/audio/ducking',dependencies=[Depends(authorized)])
def audio_ducking(data: Toggle):
    return audio_errors(lambda: controller.audio_ducking(data.enabled))
@app.post('/api/audio/install',dependencies=[Depends(authorized),Depends(audio_here)])
def audio_install():
    try: return {'ok':True,'setup':controller.audio_install(),'message':'Scarico l\'amplificatore…'}
    except ValueError as ex: raise HTTPException(400,str(ex))
@app.post('/api/audio/selector',dependencies=[Depends(authorized),Depends(audio_here)])
def audio_selector():
    return audio_errors(controller.audio_selector)

# ---------- controllo remoto: mouse, tastiera e schermo dal vivo ----------
class RemoteSetup(BaseModel):
    enabled: bool | None = None
    pin: str | None = None
    idle_minutes: int | None = None
class RemotePin(BaseModel):
    pin: str
class RemoteConfig(BaseModel):
    mon: int | str | None = None
    quality: str | None = None
    fps: int | None = None
class RemoteInput(BaseModel):
    events: list[dict]
def remote_errors(fn):
    try: return fn()
    except PermissionError as ex: raise HTTPException(403,str(ex))
    except ValueError as ex: raise HTTPException(400,str(ex))
@app.get('/api/remote',dependencies=[Depends(authorized)])
def remote_info(request: Request):
    return {**controller.remote.info(),'local':not is_remote(request)}
@app.post('/api/remote/setup',dependencies=[Depends(authorized),Depends(pin_gate)])
def remote_setup(data: RemoteSetup):
    return remote_errors(lambda: {'ok':True,'info':controller.remote_setup(data.enabled,data.pin,data.idle_minutes),'message':'Controllo remoto aggiornato'})
@app.post('/api/remote/off',dependencies=[Depends(authorized)])
def remote_off():
    return {'ok':True,'info':controller.remote_setup(enabled=False),'message':'Controllo remoto spento'}
@app.post('/api/remote/start',dependencies=[Depends(authorized)])
def remote_start(data: RemotePin, request: Request):
    who = 'Telegram' if request.headers.get('x-tg-init-data') else ('dashboard da Internet' if is_remote(request) else 'dashboard sul PC')
    return remote_errors(lambda: controller.remote.start(data.pin, who))
@app.post('/api/remote/end',dependencies=[Depends(authorized)])
def remote_end():
    return {'ok':True,'message':'Controllo terminato' if controller.remote.end(reason='terminato da te') else 'Nessun controllo attivo'}
@app.post('/api/remote/config',dependencies=[Depends(authorized)])
def remote_config(data: RemoteConfig, x_remote_session: str | None = Header(default=None)):
    mon = data.mon if data.mon in (None,'all') or isinstance(data.mon,int) else None
    return remote_errors(lambda: controller.remote.configure(x_remote_session, mon, data.quality, data.fps))
@app.get('/api/remote/frame',dependencies=[Depends(authorized)])
def remote_frame(v: int = 0, seq: int = 0, x_remote_session: str | None = Header(default=None)):
    meta, jpg = remote_errors(lambda: controller.remote.next(x_remote_session, v, seq))
    if jpg is None: return JSONResponse(meta)
    return Response(jpg, media_type='image/jpeg', headers={'X-Remote-Meta': json.dumps(meta), 'Cache-Control':'no-store'})
@app.get('/api/remote/stream',dependencies=[Depends(authorized)])
def remote_stream(x_remote_session: str | None = Header(default=None)):
    remote_errors(lambda: controller.remote.check(x_remote_session))
    # "no-transform": nessun proxy deve comprimere o trattenere il flusso.
    return StreamingResponse(controller.remote.stream(x_remote_session), media_type='application/octet-stream',
                             headers={'Cache-Control':'no-store, no-transform','X-Accel-Buffering':'no'})
@app.post('/api/remote/input',dependencies=[Depends(authorized)])
def remote_input(data: RemoteInput, x_remote_session: str | None = Header(default=None)):
    return {'ok':True,'done':remote_errors(lambda: controller.remote.input(x_remote_session, data.events))}

@app.get('/api/apps/icon/{key}',dependencies=[Depends(authorized)])
def apps_icon(key: str):
    dest = controller.app_icon(key)
    if not dest: raise HTTPException(404,'Nessuna icona')
    return FileResponse(dest, media_type='image/png', headers={'Cache-Control':'private, max-age=86400'})

@app.post('/api/gaming/launch',dependencies=[Depends(authorized)])
def gaming_launch(data: GameLaunch):
    try: return {'ok':True,'message':controller.launch_game(data.id)}
    except (ValueError,RuntimeError,OSError) as ex: raise HTTPException(400,str(ex))

@app.post('/api/gaming/quit',dependencies=[Depends(authorized)])
def gaming_quit():
    try: return {'ok':True,'message':controller.quit_game()}
    except (RuntimeError,OSError) as ex: raise HTTPException(400,str(ex))

@app.get('/api/gaming/cover/{gid}/{kind}',dependencies=[Depends(authorized)])
def gaming_cover(gid: str, kind: str):
    # Solo immagini già sul PC: cache di Steam o icona dell'eseguibile del gioco. Nessuna richiesta a internet.
    if kind == 'icon':
        if not re.fullmatch(r'(epic|riot|gog|steam)-[A-Za-z0-9_-]{1,60}', gid): raise HTTPException(404,'Nessuna immagine')
        dest = DATA_DIR / 'icons' / f'{gid}.png'
        if not dest.is_file():
            g = controller.booster.find(gid)
            try: ok = g and gaming_boost.exe_icon(g.get('exe') or '', dest)
            except Exception: logging.exception('Icona del gioco'); ok = None
            if not ok: raise HTTPException(404,'Nessuna immagine')
        return FileResponse(dest, media_type='image/png', headers={'Cache-Control':'private, max-age=86400'})
    # Copertina scelta dall'utente, cache di Steam sul PC o immagine ufficiale di Steam scaricata una volta.
    if not re.fullmatch(r'[a-z]+-[A-Za-z0-9_-]{1,70}', gid) or kind not in gaming_boost.COVER_KINDS: raise HTTPException(404,'Nessuna immagine')
    try: path = controller.game_cover(gid, kind)
    except Exception: logging.exception('Copertina del gioco'); path = None
    if not path: raise HTTPException(404,'Nessuna immagine')
    media = 'image/png' if str(path).lower().endswith('.png') else 'image/jpeg'
    return FileResponse(path, media_type=media, headers={'Cache-Control':'private, max-age=86400'})

@app.post('/api/gaming/cover/{gid}',dependencies=[Depends(authorized)])
async def gaming_cover_set(gid: str, request: Request):
    data = await request.body()
    if len(data) > 12_000_000: raise HTTPException(413,'Immagine troppo grande (massimo 12 MB)')
    if not controller.booster.find(gid): raise HTTPException(404,'Gioco non trovato')
    try: controller.covers.set_custom(gid, data)
    except ValueError as ex: raise HTTPException(400,str(ex))
    return {'ok':True,'message':'Copertina cambiata','cv':controller.covers.version(gid)}

@app.delete('/api/gaming/cover/{gid}',dependencies=[Depends(authorized)])
def gaming_cover_reset(gid: str):
    try: controller.covers.remove_custom(gid)
    except ValueError as ex: raise HTTPException(400,str(ex))
    return {'ok':True,'message':'Copertina originale','cv':0}

@app.get('/api/gaming/game/{gid}',dependencies=[Depends(authorized)])
def gaming_game(gid: str):
    try: return controller.game_detail(gid)
    except ValueError as ex: raise HTTPException(404,str(ex))

class GameProfile(BaseModel):
    auto: bool | None = None
    fans: str | None = None
    rgb: str | None = None
    mouse: bool | None = None
@app.post('/api/gaming/game/{gid}/profile',dependencies=[Depends(authorized)])
def gaming_game_profile(gid: str, data: GameProfile):
    try: return {'ok':True,'message':'Salvato per questo gioco','profile':controller.save_game_profile(gid, data.model_dump(exclude_unset=True))}
    except ValueError as ex: raise HTTPException(400,str(ex))

@app.post('/api/gaming/game/{gid}/folder',dependencies=[Depends(authorized)])
def gaming_game_folder(gid: str):
    try: return {'ok':True,'message':controller.game_folder(gid)}
    except (ValueError,OSError) as ex: raise HTTPException(400,str(ex))

@app.post('/api/gaming/rtss',dependencies=[Depends(authorized)])
def gaming_rtss():
    try: return {'ok':True,'message':start_rtss()}
    except (ValueError,OSError) as ex: raise HTTPException(400,str(ex))

@app.post('/api/gaming/game/{gid}/verify',dependencies=[Depends(authorized)])
def gaming_game_verify(gid: str):
    try: return {'ok':True,'message':controller.game_verify(gid)}
    except (ValueError,OSError) as ex: raise HTTPException(400,str(ex))

@app.get('/api/eco',dependencies=[Depends(authorized)])
def eco_info():
    return controller.eco_info()

class EcoSettings(BaseModel):
    level: str | None = None
    turbo_off: bool | None = None
    pcie: bool | None = None
    usb: bool | None = None
    wifi: bool | None = None
    leds_off: bool | None = None
    fans_quiet: bool | None = None
    cpu: int | None = None
    park: int | None = None
    disk_idle: int | None = None
    monitor: int | None = None
    sleep_idle: int | None = None
@app.post('/api/eco',dependencies=[Depends(authorized)])
def eco_save(data: EcoSettings):
    try: r = controller.set_eco_settings(data.model_dump(exclude_none=True)); return {'ok':True,**r}
    except (ValueError,RuntimeError) as ex: raise HTTPException(400,str(ex))

@app.get('/api/stats',dependencies=[Depends(authorized)])
def stats():
    return controller.stats_summary()

@app.get('/api/optimize',dependencies=[Depends(authorized)])
def optimize_info():
    return {'report':getattr(controller,'optimize_report',None),'disks':optimizer.disks(),
            'memory':optimizer.memory_top(),'startup':optimizer.startup_items(),**controller.optimize_extra()}

def optimize_scan_job():
    controller.optimize_report = optimizer.analyze()
    return 'Analisi: ' + optimizer.human(controller.optimize_report['total']) + ' recuperabili'

@app.post('/api/optimize/scan',dependencies=[Depends(authorized)])
def optimize_scan():
    try: return {'ok':True,'message':controller.run_job('optimize-scan',optimize_scan_job)}
    except RuntimeError as ex: raise HTTPException(409,str(ex))

class CleanRequest(BaseModel):
    keys: list[str]
@app.post('/api/optimize/clean',dependencies=[Depends(authorized)])
def optimize_clean(data: CleanRequest, request: Request):
    import discovery
    remote = is_remote(request)
    needs_admin = any(t.get('admin') and t['key'] in data.keys for t in optimizer.targets())
    if remote and needs_admin: pin_gate(request, request.headers.get('x-admin-pin'))
    admin = controller.admin if remote and needs_admin and controller.admin.active() else None
    def job():
        res = optimizer.clean(data.keys, discovery.run_elevated, allow_admin=not remote, admin=admin)
        controller.record_clean(res['freed'], 'manuale')
        optimize_scan_job(); optimizer.mark_left(controller.optimize_report, res.get('items'))
        return 'Pulizia: liberati ' + optimizer.human(res['freed']) + ('. ' + ' · '.join(res['notes']) if res['notes'] else '')
    if not data.keys or set(data.keys) - {t['key'] for t in optimizer.targets()}: raise HTTPException(400,'Scegli cosa pulire')
    try: return {'ok':True,'message':controller.run_job('optimize-clean',job)}
    except RuntimeError as ex: raise HTTPException(409,str(ex))

class StartupToggle(BaseModel):
    id: str
    enabled: bool
@app.post('/api/optimize/startup',dependencies=[Depends(authorized)])
def optimize_startup(data: StartupToggle, request: Request):
    import discovery
    try:
        remote = is_remote(request)
        system = data.id.startswith('HKLM|')
        if remote and system: pin_gate(request, request.headers.get('x-admin-pin'))
        optimizer.set_startup(data.id, data.enabled, None if remote else discovery.run_elevated, elevator(request) if remote and system else None)
        name = data.id.split('|',2)[-1]
        controller.log_event(f'Avvio di Windows: {name} ' + ('attivato' if data.enabled else 'disattivato'))
        return {'ok':True,'message':f'{name}: ' + ('parte con Windows' if data.enabled else 'non parte più con Windows')}
    except (ValueError,RuntimeError,OSError) as ex: raise HTTPException(400,str(ex))

QUICK_CLEAN = optimizer.SAFE_CLEAN

@app.post('/api/optimize/quick',dependencies=[Depends(authorized)])
def optimize_quick():
    """Ottimizza ora: pulizia sicura + cache DNS in un clic, poi nuova analisi per il punteggio."""
    def job():
        res = optimizer.clean(QUICK_CLEAN)
        controller.record_clean(res['freed'], 'rapida')
        left = res.get('items')
        try: optimizer.flush_dns(); dns = ' · DNS svuotata'
        except (RuntimeError,OSError): dns = ''
        optimize_scan_job(); optimizer.mark_left(controller.optimize_report, left)
        return 'Ottimizzazione fatta: liberati ' + optimizer.human(res['freed']) + dns + ('. ' + ' · '.join(res['notes']) if res['notes'] else '')
    try: return {'ok':True,'message':controller.run_job('optimize-clean',job)}
    except RuntimeError as ex: raise HTTPException(409,str(ex))

@app.post('/api/optimize/dns',dependencies=[Depends(authorized)])
def optimize_dns():
    try: return {'ok':True,'message':optimizer.flush_dns()}
    except (RuntimeError,OSError) as ex: raise HTTPException(400,str(ex))

@app.get('/api/optimize/processes',dependencies=[Depends(authorized)])
def optimize_processes():
    return optimizer.processes()

class AppName(BaseModel):
    name: str
@app.post('/api/optimize/close',dependencies=[Depends(authorized)])
def optimize_close(data: AppName):
    try:
        msg = optimizer.close_app(data.name); controller.log_event('Ottimizza: ' + msg)
        return {'ok':True,'message':msg}
    except (ValueError,OSError) as ex: raise HTTPException(400,str(ex))

def optimize_large_job():
    controller.large_report = optimizer.large_files()
    r = controller.large_report
    return f"File grandi: {r['count']} file, {optimizer.human(r['total'])}"
@app.post('/api/optimize/large/scan',dependencies=[Depends(authorized)])
def optimize_large_scan():
    try: return {'ok':True,'message':controller.run_job('optimize-large',optimize_large_job)}
    except RuntimeError as ex: raise HTTPException(409,str(ex))

class FilePath(BaseModel):
    path: str
def known_large(path):
    # Solo file trovati dall'ultima ricerca: niente percorsi arbitrari dal browser.
    files = (getattr(controller,'large_report',None) or {}).get('files') or []
    f = next((f for f in files if f['path'] == path), None)
    if not f or not os.path.isfile(path): raise HTTPException(404,'File non trovato: ripeti la ricerca')
    return f
@app.post('/api/optimize/large/reveal',dependencies=[Depends(authorized)])
def optimize_large_reveal(data: FilePath):
    known_large(data.path); optimizer.reveal(data.path)
    return {'ok':True,'message':'Cartella aperta sul PC'}
@app.post('/api/optimize/large/recycle',dependencies=[Depends(authorized),Depends(pin_gate)])
def optimize_large_recycle(data: FilePath):
    f = known_large(data.path)
    try: optimizer.to_recycle_bin(data.path)
    except (RuntimeError,OSError) as ex: raise HTTPException(400,str(ex))
    rep = controller.large_report
    rep['files'] = [x for x in rep['files'] if x['path'] != data.path]; rep['total'] -= f['bytes']; rep['count'] -= 1
    controller.log_event(f"Nel Cestino: {f['name']} ({optimizer.human(f['bytes'])})")
    return {'ok':True,'message':f"{f['name']} spostato nel Cestino (recuperabile)"}

def optimize_health_job():
    controller.disk_report = {'at': int(time.time()), 'disks': optimizer.disk_health()}
    bad = [d['name'] for d in controller.disk_report['disks'] if not d['ok']]
    return ('Dischi da controllare: ' + ', '.join(bad)) if bad else f"Dischi in salute ({len(controller.disk_report['disks'])})"
@app.post('/api/optimize/health',dependencies=[Depends(authorized)])
def optimize_health():
    try: return {'ok':True,'message':controller.run_job('optimize-health',optimize_health_job)}
    except RuntimeError as ex: raise HTTPException(409,str(ex))

def optimize_net_job():
    n = optimizer.network_check()
    controller.net_alert(controller.record_net(n))
    return f"Rete {n['quality']}: internet {n['internet'].get('ms') or '—'} ms"
@app.post('/api/optimize/net',dependencies=[Depends(authorized)])
def optimize_net():
    try: return {'ok':True,'message':controller.run_job('optimize-net',optimize_net_job)}
    except RuntimeError as ex: raise HTTPException(409,str(ex))

class AutoClean(BaseModel):
    enabled: bool
@app.post('/api/optimize/auto',dependencies=[Depends(authorized)])
def optimize_auto(data: AutoClean):
    return {'ok':True,'message':controller.set_optimize_auto(data.enabled)}
@app.post('/api/optimize/net/auto',dependencies=[Depends(authorized)])
def optimize_net_auto(data: AutoClean):
    return {'ok':True,'message':controller.set_net_auto(data.enabled)}

@app.post('/api/optimize/trim',dependencies=[Depends(authorized),Depends(pin_gate)])
def optimize_trim(request: Request):
    import discovery
    admin = elevator(request)
    def job():
        if admin: admin.call('trim')
        elif not discovery.run_elevated(optimizer.TRIM_SCRIPT, wait=True): raise RuntimeError('Conferma amministratore annullata')
        return 'SSD ottimizzati (TRIM eseguito)'
    try: return {'ok':True,'message':controller.run_job('trim',job)}
    except RuntimeError as ex: raise HTTPException(409,str(ex))

@app.post('/api/screen',dependencies=[Depends(authorized)])
def screen():
    try: return {'ok':True,'message':controller.screen_off()}
    except (RuntimeError,OSError) as ex: raise HTTPException(400,str(ex))

if __name__=='__main__':
    host=config.get('web',{}).get('host','127.0.0.1')
    if host not in ('0.0.0.0','127.0.0.1'): raise RuntimeError('Host consentito: 127.0.0.1 o 0.0.0.0')
    port=int(config.get('web',{}).get('port',8765))
    if not 1024<=port<=65535: raise RuntimeError('Porta non valida')
    logging.info('Dashboard Windows su %s:%s',host,port)
    uvicorn.run(app,host=host,port=port,access_log=False,log_level='warning',proxy_headers=False)
