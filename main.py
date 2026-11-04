"""NEXAR - Windows agent + authenticated responsive web dashboard."""
import hmac
import logging
import os
from pathlib import Path
import threading
import time
from contextlib import asynccontextmanager
from collections import defaultdict, deque

from fastapi import FastAPI, Header, HTTPException, Request, Depends
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import uvicorn

import hashlib
import json
from urllib.parse import parse_qsl

from core import ROOT, ASSET_ROOT, CONFIG_FILE, DATA_DIR, FROZEN, INSTALL_DIR, MIGRATED_FROM, Control, json_load
from telegram_bot import TelegramBot
from tunnel import TUNNEL_PORT, Tunnel
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

@asynccontextmanager
async def lifespan(app: FastAPI):
    global tunnel
    bot = TelegramBot(controller)
    controller.notify = bot.notify
    tunnel = Tunnel(controller, app)
    bot.tunnel = tunnel
    bot.updater = updater
    tunnel.on_url = bot.set_webapp
    threading.Thread(target=tunnel.run,args=(stop,),daemon=True,name='tunnel').start()
    t1 = threading.Thread(target=bot.run,args=(stop,),daemon=True,name='telegram')
    t2 = threading.Thread(target=controller.auto_loop,args=(stop,),daemon=True,name='ai-auto')
    t3 = threading.Thread(target=controller.monitor_loop,args=(stop,),daemon=True,name='temperature-alerts')
    t4 = threading.Thread(target=controller.discover,daemon=True,name='discovery')
    t5 = threading.Thread(target=controller.power_loop,args=(stop,),daemon=True,name='power-plan')
    t6 = threading.Thread(target=updater.loop,args=(stop,),daemon=True,name='updater')
    t7 = threading.Thread(target=controller.fan_guard_loop,args=(stop,),daemon=True,name='fan-guard')
    t1.start();t2.start();t3.start();t4.start();t5.start();t6.start();t7.start()
    updater.announce()
    # Avviso "PC acceso" solo dopo un avvio vero di Windows, non a ogni riapertura dell'app.
    import psutil
    if time.time() - psutil.boot_time() < 900: bot.notify('🟢 PC acceso. NEXAR è attivo.')
    yield
    stop.set()

app = FastAPI(title='NEXAR',docs_url=None,redoc_url=None,openapi_url=None,lifespan=lifespan)
app.mount('/assets',StaticFiles(directory=str(ASSET_ROOT/'web')),name='assets')

@app.middleware('http')
async def no_cache_and_security(request: Request, call_next):
    response = await call_next(request)
    response.headers['Cache-Control']='no-store'
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['X-Frame-Options']='DENY'
    response.headers['Referrer-Policy']='no-referrer'
    # La Mini App gira dentro Telegram: serve il suo script e il permesso di essere incorniciata da Telegram.
    response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self' https://telegram.org; style-src 'self'; img-src 'self' data:; connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors https://web.telegram.org https://*.telegram.org"
    if is_tunnel(request): del response.headers['X-Frame-Options']
    return response

def is_tunnel(request: Request) -> bool:
    return (request.scope.get('server') or (None, 0))[1] == TUNNEL_PORT

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
    if not x_pc_eco_key or not hmac.compare_digest(x_pc_eco_key,key):
        q.append(now)
        raise HTTPException(401,'Chiave di accesso non valida')
    q.clear()
    return True

@app.get('/')
def index(): return FileResponse(ASSET_ROOT/'web'/'index.html',media_type='text/html')

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
    cpu_temp_alert: int | None = None
    gpu_temp_alert: int | None = None
    energy_price_cents: int | None = None
    psu_watts: int | None = None
    psu_class: str | None = None
    monitor_watts: int | None = None
    extra_watts: int | None = None
    gaming_fans: str | None = None

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
    # Installazioni e richieste UAC compaiono sullo schermo del PC: mai da Umbrel o dal telefono.
    if is_remote(request):
        raise HTTPException(403,'Operazione disponibile solo dalla app sul PC Windows.')
    return True

@app.post('/api/discover',dependencies=[Depends(authorized),Depends(local_only)])
def discover():
    try: return {'ok':True,'message':controller.run_job('discover',lambda: controller.discover(allow_uac=True) and 'Collegamenti aggiornati')}
    except RuntimeError as ex: raise HTTPException(409,str(ex))

class Install(BaseModel):
    key: str
@app.post('/api/install',dependencies=[Depends(authorized),Depends(local_only)])
def install(data: Install):
    import discovery
    if data.key not in discovery.WINGET: raise HTTPException(400,'Programma non previsto')
    def run():
        msg=discovery.winget_install(data.key)
        controller.discover(allow_uac=True)
        return msg
    try: return {'ok':True,'message':controller.run_job('install-'+data.key,run)}
    except RuntimeError as ex: raise HTTPException(409,str(ex))

@app.post('/api/fans/setup',dependencies=[Depends(authorized),Depends(local_only)])
def fans_setup():
    try: return {'ok':True,'message':controller.run_job('fans-setup',controller.setup_fans)}
    except RuntimeError as ex: raise HTTPException(409,str(ex))

@app.post('/api/fancontrol/open',dependencies=[Depends(authorized),Depends(local_only)])
def fancontrol_open():
    exe=controller.config.get('fans',{}).get('fancontrol_exe','')
    if not exe or not Path(exe).is_file(): raise HTTPException(404,'Fan Control non trovato')
    os.startfile(exe)
    return {'ok':True,'message':'Fan Control aperto'}

@app.post('/api/autostart',dependencies=[Depends(authorized),Depends(local_only)])
def autostart(data: Toggle):
    import discovery
    from core import json_save
    with controller.lock:
        controller.config['autostart']=data.enabled
        json_save(CONFIG_FILE,controller.config)
    try: discovery.autostart_set(data.enabled)
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

@app.get('/api/power/relay',dependencies=[Depends(authorized),Depends(local_only)])
def power_relay():
    # Contiene il token del bot: solo dalla app sul PC.
    try: return {'compose':controller.relay_compose()}
    except (ValueError,RuntimeError) as ex: raise HTTPException(400,str(ex))

@app.post('/api/power/wol',dependencies=[Depends(authorized),Depends(local_only)])
def power_wol():
    try: return {'ok':True,'message':controller.run_job('wol',controller.wol_setup)}
    except RuntimeError as ex: raise HTTPException(409,str(ex))

@app.post('/api/update/check',dependencies=[Depends(authorized)])
def update_check():
    try: return {'ok':True,'message':updater.check()['message'],'update':updater.info()}
    except Exception as ex: raise HTTPException(502,'GitHub non raggiungibile: '+str(ex)[:150])

@app.post('/api/update/install',dependencies=[Depends(authorized)])
def update_install():
    try: return {'ok':True,'message':controller.run_job('update',updater.install)}
    except RuntimeError as ex: raise HTTPException(409,str(ex))

@app.post('/api/update/auto',dependencies=[Depends(authorized)])
def update_auto(data: Toggle):
    from core import json_save
    with controller.lock:
        controller.config.setdefault('updates',{})['auto']=data.enabled
        json_save(CONFIG_FILE,controller.config)
    return {'ok':True,'message':'Aggiornamenti automatici '+('attivi' if data.enabled else 'disattivati')}

# ---------- ottimizzazione ----------
import optimizer

@app.get('/api/optimize',dependencies=[Depends(authorized)])
def optimize_info():
    return {'report':getattr(controller,'optimize_report',None),'disks':optimizer.disks(),
            'memory':optimizer.memory_top(),'startup':optimizer.startup_items()}

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
    remote = is_remote(request)  # la conferma amministratore compare sullo schermo del PC: da remoto solo pulizie utente
    def job():
        res = optimizer.clean(data.keys, discovery.run_elevated, allow_admin=not remote)
        optimize_scan_job()
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
        optimizer.set_startup(data.id, data.enabled, None if is_remote(request) else discovery.run_elevated)
        name = data.id.split('|',2)[-1]
        controller.log_event(f'Avvio di Windows: {name} ' + ('attivato' if data.enabled else 'disattivato'))
        return {'ok':True,'message':f'{name}: ' + ('parte con Windows' if data.enabled else 'non parte più con Windows')}
    except (ValueError,RuntimeError,OSError) as ex: raise HTTPException(400,str(ex))

@app.post('/api/optimize/dns',dependencies=[Depends(authorized)])
def optimize_dns():
    try: return {'ok':True,'message':optimizer.flush_dns()}
    except (RuntimeError,OSError) as ex: raise HTTPException(400,str(ex))

@app.post('/api/optimize/trim',dependencies=[Depends(authorized),Depends(local_only)])
def optimize_trim():
    import discovery
    def job():
        if not discovery.run_elevated(optimizer.TRIM_SCRIPT, wait=True): raise RuntimeError('Conferma amministratore annullata')
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
