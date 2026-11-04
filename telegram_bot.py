"""Bot long-polling: no port forwarding required, only approved private user."""
import html
import json
import queue
import logging
import threading
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

COLORS = {'bianco': '#ffffff', 'rosso': '#ff2a2a', 'arancione': '#ff8a00', 'giallo': '#ffd400', 'verde': '#2cff5a',
          'azzurro': '#00e5ff', 'blu': '#1f6bff', 'viola': '#8a3cff', 'rosa': '#ff3cc8'}
COLOR_EMOJI = {'bianco': '⚪', 'rosso': '🔴', 'arancione': '🟠', 'giallo': '🟡', 'verde': '🟢', 'azzurro': '🩵', 'blu': '🔵', 'viola': '🟣', 'rosa': '🩷'}
COMMANDS = [('menu', 'Pannello di controllo'), ('status', 'Stato del PC'), ('consumo', 'Consumo ed energia'),
            ('eco', 'Attiva AI ECO'), ('normal', 'Modalità normale'), ('gaming', 'Modalità Gaming'), ('luci', 'LED e colori'),
            ('colore', 'Colore LED, es. /colore blu o /colore #ff8800'), ('salva', 'Salva un colore, es. /salva #ff8800'),
            ('ventole', 'Profili ventole'),
            ('screen', 'Spegni il monitor'), ('auto', 'Automazione Codex/Claude'), ('accensione', 'Spegni, riavvia, sospendi, timer'),
            ('spegni', 'Spegni il PC'), ('sospendi', 'Metti il PC in sospensione'), ('annulla', 'Annulla lo spegnimento'),
            ('accendi', 'Accendi il PC (relay su Umbrel)'), ('aggiorna', 'Versione e aggiornamenti'), ('app', 'Apri la dashboard')]
POWER_ASK = {'shutdown': '⏻ Spegnere il PC?\nCodex e Claude verranno chiusi.', 'restart': '🔄 Riavviare il PC?',
             'sleep': '🌙 Mettere il PC in sospensione?\nConsuma 2–5 W e si risveglia con Wake-on-LAN.',
             'hibernate': '💤 Ibernare il PC?'}

def nearest_emoji(hex_color):
    rgb = lambda h: tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))
    target = rgb(hex_color)
    name = min(COLORS, key=lambda n: sum((a - b) ** 2 for a, b in zip(rgb(COLORS[n]), target)))
    return COLOR_EMOJI[name]

def duration(seconds):
    h, m = divmod(int(seconds) // 60, 60)
    return f'{h // 24} g {h % 24} h' if h >= 24 else (f'{h} h {m} min' if h else f'{m} min')

class TelegramBot:
    def __init__(self, controller):
        self.ctrl = controller
        cfg = controller.config.get('telegram',{})
        # Vuoto finché run() non ha verificato il token con getMe (nome del bot, comandi vecchi saltati).
        self.token = ''
        self.user_id = int(cfg.get('allowed_user_id') or 0)
        self.offset = None
        self.notifications = queue.Queue(maxsize=40)
        self.webapp_url = ''
        self.menu_synced = None
        self.tunnel = None
        self.updater = None
        self.bad_token = ''
        controller.telegram_bot = {'username': '', 'error': ''}

    def reject_token(self):
        self.bad_token = self.token
        self.ctrl.telegram_bot = {'username': '', 'error': 'Token non più valido: in Impostazioni → Telegram incolla quello attuale del tuo bot (@BotFather → /token).'}
        logging.warning('Telegram: token rifiutato (401)')

    def identify(self):
        """Chi è il bot (es. @NexarPc_Bot) e, la prima volta, nome e descrizioni NEXAR nel profilo del bot."""
        try: me = self.call('getMe', {})
        except HTTPError as ex:
            if ex.code in (401, 404): self.reject_token(); return False
            raise
        self.bad_token = ''
        self.ctrl.telegram_bot = {'username': me.get('username', ''), 'error': ''}
        branded = self.ctrl.state.get('bot_branded')
        if branded != me.get('username'):
            for method, payload in (('setMyName', {'name': 'NEXAR'}),
                                    ('setMyShortDescription', {'short_description': 'Controlla il tuo PC: consumi, AI ECO, Gaming, LED, ventole e accensione.'}),
                                    ('setMyDescription', {'description': 'NEXAR · il tuo PC Windows sotto controllo.\n\nConsumo reale alla presa, modalità AI ECO / Normale / Gaming, luci, ventole, spegnimento e accensione. Risponde solo al proprietario abbinato.'})):
                try: self.call(method, payload)
                except Exception: logging.info('Telegram: %s non applicato', method)
            from core import json_save, STATE_FILE
            with self.ctrl.lock:
                self.ctrl.state['bot_branded'] = me.get('username'); json_save(STATE_FILE, self.ctrl.state)
        return True

    # ---------- API ----------
    def call(self, method, payload):
        req = Request('https://api.telegram.org/bot'+self.token+'/'+method,
                      data=urlencode(payload).encode('utf-8'), method='POST')
        with urlopen(req, timeout=45) as res:
            obj = json.load(res)
        if not obj.get('ok'): raise RuntimeError('Telegram API: '+method)
        return obj.get('result')
    def send(self, chat_id, msg, markup=None):
        payload={'chat_id':chat_id,'text':msg[:3900],'parse_mode':'HTML','disable_web_page_preview':'true'}
        if markup: payload['reply_markup']=json.dumps(markup)
        return self.call('sendMessage',payload)
    def edit(self, chat_id, message_id, msg, markup=None):
        """Aggiorna il pannello nello stesso messaggio: la chat non si riempie di risposte."""
        payload={'chat_id':chat_id,'message_id':message_id,'text':msg[:3900],'parse_mode':'HTML','disable_web_page_preview':'true'}
        if markup: payload['reply_markup']=json.dumps(markup)
        try: self.call('editMessageText',payload)
        except Exception: pass  # testo identico o messaggio troppo vecchio: nessun problema

    def set_webapp(self, url):
        self.webapp_url = url or ''
        self.menu_synced = None  # risincronizza il pulsante al prossimo giro del polling

    def sync_menu_button(self):
        if not (self.token and self.user_id) or self.menu_synced == self.webapp_url: return
        button = {'type':'web_app','text':'📱 App','web_app':{'url':self.webapp_url}} if self.webapp_url else {'type':'commands'}
        try:
            self.call('setChatMenuButton',{'chat_id':self.user_id,'menu_button':json.dumps(button)})
            self.call('setMyCommands',{'commands':json.dumps([{'command':c,'description':d} for c,d in COMMANDS])})
            self.menu_synced = self.webapp_url
        except Exception: logging.warning('Telegram: pulsante app non aggiornato')

    # ---------- pannelli ----------
    def app_row(self):
        return [[{'text':'📱 Apri la dashboard','web_app':{'url':self.webapp_url}}]] if self.webapp_url else []
    def menu(self):
        s = self.ctrl.status()
        mode = s.get('mode')
        auto = '🟢 attiva' if s.get('auto_enabled') else '⚪ spenta'
        tick = lambda m: '✅ ' if mode == m else ''
        return {'inline_keyboard': self.app_row() + [
            [{'text':tick('eco')+'🌙 AI ECO','callback_data':'eco'},{'text':tick('normal')+'⚡ Normale','callback_data':'normal'},
             {'text':tick('gaming')+'🎮 Gaming','callback_data':'gaming'}],
            [{'text':'📊 Stato','callback_data':'status'},{'text':'🔌 Consumo','callback_data':'power'}],
            [{'text':'💡 Luci','callback_data':'rgb'},{'text':'🌀 Ventole','callback_data':'fans'},{'text':'🖥 Monitor','callback_data':'screen'}],
            [{'text':f'🤖 Automazione AI: {auto}','callback_data':'auto'}],
            [{'text':'⏻ Accensione e spegnimento','callback_data':'pw'}],
        ]}
    @staticmethod
    def back(): return [{'text':'⬅️ Menu','callback_data':'home'}]
    def rgb_menu(self):
        # I tuoi colori salvati (dashboard o /salva): pallino più vicino + codice, 3 per riga.
        buttons=[{'text':f'{nearest_emoji(c)} {c[1:].upper()}','callback_data':'c:'+c} for c in self.ctrl.rgb_palette()]
        rows=[buttons[i:i+3] for i in range(0,len(buttons),3)]
        return {'inline_keyboard':[[{'text':'⚫ Spegni LED','callback_data':'rgb_off'},{'text':'💡 Riaccendi','callback_data':'rgb_on'}]]+rows+[self.back()]}
    def fans_menu(self):
        return {'inline_keyboard':[[{'text':'⏸ Spente','callback_data':'fans_off'},{'text':'🤫 Silenziose','callback_data':'fans_eco'}],
                                   [{'text':'🌀 Normali','callback_data':'fans_normal'},{'text':'🚀 Massimo','callback_data':'fans_max'}],self.back()]}
    def power_menu(self):
        pc = self.ctrl.pc_info()
        rows = [[{'text':'🌙 Sospendi','callback_data':'pwc:sleep'},{'text':'🔄 Riavvia','callback_data':'pwc:restart'},{'text':'⏻ Spegni','callback_data':'pwc:shutdown'}],
                [{'text':'⏱ 30 min','callback_data':'t:30'},{'text':'⏱ 1 ora','callback_data':'t:60'},{'text':'⏱ 2 ore','callback_data':'t:120'}],
                [{'text':'🤖 Spegni quando l\'AI ha finito','callback_data':'pwai'}],
                [{'text':'🔒 Blocca lo schermo','callback_data':'pwx:lock'}]]
        if pc.get('hibernate'): rows[0].insert(1, {'text':'💤 Iberna','callback_data':'pwc:hibernate'})
        if pc.get('pending'): rows.insert(0, [{'text':'✖️ Annulla spegnimento','callback_data':'pwcancel'}])
        return {'inline_keyboard':rows+[self.back()]}
    def power_status(self):
        pc = self.ctrl.pc_info(); plan = pc.get('pending')
        text = f"⏻ <b>Accensione</b>\n🟢 Acceso da {duration(pc['uptime_s'])}"
        if plan:
            when = 'quando Codex e Claude hanno finito' if plan['after_ai'] else 'tra ' + duration(max(60, plan['seconds_left'] or 0))
            text += f"\n⏳ <b>{html.escape(plan['label'])}</b> {when}"
        return text + '\n\n<i>Per accenderlo da spento: /accendi tramite il relay su Umbrel.</i>'

    def status_text(self):
        s = self.ctrl.status()
        n = lambda v, unit='': '—' if v is None else f'{round(v)}{unit}'
        p, e, pw = s.get('processes', {}), s.get('energy', {}), s.get('power')
        agents = ' · '.join(f"{k.capitalize()} {'🟢' if v else '⚪'}" for k, v in p.items())
        fans = [f['rpm'] for f in s.get('fans', []) if 'system' in f['name'].lower() and f['rpm'] > 0]
        lines = [
            f"<b>{ {'eco':'🌙 AI ECO attiva','gaming':'🎮 Modalità Gaming'}.get(s.get('mode'),'⚡ Modalità normale') }</b>",
            '',
            f"🔌 <b>{n(pw['total'] if pw else None,' W')}</b> alla presa · oggi {e.get('today_kwh',0):.2f} kWh ({e.get('today_cost',0):.2f} €)",
            f"⏻ Acceso da {duration(s['pc']['uptime_s'])}" + (' · ⏳ ' + html.escape(s['pc']['pending']['label']) + ' programmato' if s['pc'].get('pending') else ''),
            f"🧠 CPU {n(s.get('cpu'),'%')} · {n(s.get('cpu_temp'),'°C')}",
            f"🎮 GPU {n(s.get('gpu'),'%')} · {n(s.get('gpu_temp'),'°C')}",
            f"💾 RAM {n(s.get('ram'),'%')} ({s.get('ram_used')} di {s.get('ram_total')} GB)",
            f"🌀 Ventole case {round(sum(fans)/len(fans)) if fans else '—'} RPM · { {'off':'spente','eco':'silenziose','max':'al massimo'}.get(s.get('fans_level'),'normali') }",
            f"💡 LED {'spenti' if s.get('rgb_off') else 'accesi'}",
            f"🤖 {agents} · automazione {'attiva' if s.get('auto_enabled') else 'spenta'}",
        ]
        return '\n'.join(lines)

    def power_text(self):
        s = self.ctrl.status(); p, e = s.get('power'), s.get('energy', {})
        if not p: return '🔌 Consumo non disponibile: collega i sensori dalla app sul PC.'
        icons = {'cpu':'🧠','gpu':'🎮','board':'🧩','ram':'💾','disks':'🗄','cooling':'🌀','rgb':'💡','usb':'🖱','monitor':'🖥'}
        rows = '\n'.join(f"{icons.get(i['key'],'•')} {html.escape(i['name'])} {'' if i['source']=='misurato' else '~'}{i['watts']:.0f} W"
                         for i in sorted(p['items'], key=lambda i: -i['watts']))
        forecast = f"\n🔮 Fine mese ≈ {e['forecast_kwh']:.0f} kWh · {e['forecast_cost']:.2f} €" if e.get('forecast_kwh') else ''
        return (f"🔌 <b>{p['total']:.0f} W</b> alla presa ({p['low']}–{p['high']} W)\n"
                f"⚡ {p['amps']:.2f} A a {p['voltage']} V · alimentatore al {p['psu_load']:.0f}%, efficienza {p['efficiency']*100:.0f}%\n\n"
                f"{rows}\n⚙️ Perdite alimentatore {p['loss']:.0f} W\n\n"
                f"📅 Oggi <b>{e.get('today_kwh',0):.2f} kWh</b> · {e.get('today_cost',0):.2f} €\n"
                f"🗓 Mese <b>{e.get('month_kwh',0):.1f} kWh</b> · {e.get('month_cost',0):.2f} €{forecast}\n"
                f"<i>~ = stimato · {e.get('price_eur_kwh',0)*100:.0f} c€/kWh{'' if p['monitor_on'] or p['monitor_watts'] else ' · monitor escluso'}</i>")

    def notify(self, message):
        # In coda anche prima che il bot sia partito (es. "PC acceso" all'avvio): li invia il primo giro di run().
        if self.ctrl.config.get('telegram', {}).get('token') and self.user_id:
            try: self.notifications.put_nowait(html.escape(str(message)[:3800]))
            except queue.Full: logging.warning('Coda notifiche Telegram piena')

    def flush_notifications(self):
        while not self.notifications.empty():
            message=self.notifications.get_nowait()
            try: self.send(self.user_id,message,self.menu())
            except Exception:
                logging.exception('Invio avviso Telegram')
                try: self.notifications.put_nowait(message)
                except queue.Full: pass
                break

    # ---------- comandi ----------
    def dispatch(self, action, chat, message_id=None, arg=''):
        """message_id presente = pulsante premuto: si aggiorna lo stesso messaggio."""
        def reply(text, markup=None):
            markup = markup or self.menu()
            if message_id: self.edit(chat, message_id, text, markup)
            else: self.send(chat, text, markup)
        esc = lambda t: html.escape(str(t))
        a = action.lstrip('/')
        if a in ('start','help','menu','home'):
            reply('<b>NEXAR</b>\nScegli cosa fare. '+('Con 📱 apri la dashboard completa.' if self.webapp_url else ''))
        elif a == 'status': reply(self.status_text())
        elif a in ('power','consumo'): reply(self.power_text())
        elif a in ('eco','normal','gaming'):
            reply('✅ '+esc(self.ctrl.set_mode(a))+'\n\n'+self.status_text())
        elif a == 'screen': reply('🖥 '+esc(self.ctrl.screen_off()))
        elif a in ('rgb','luci'): reply('💡 <b>Luci</b>\nSpegni, riaccendi o scegli un colore per tutti i LED.', self.rgb_menu())
        elif a in ('rgb_off','rgb_on'):
            reply('💡 '+esc(self.ctrl.rgb_profile(a=='rgb_off')), self.rgb_menu())
        elif a.startswith('c:') or a == 'colore':
            name = (a[2:] if a.startswith('c:') else arg).strip().lower()
            value = COLORS.get(name, name if len(name)==7 and name.startswith('#') else '')
            if not value: reply('🎨 Colori: '+', '.join(COLORS)+'\noppure un codice, es. <code>/colore #ff8800</code>', self.rgb_menu())
            else:
                bright = int(self.ctrl.config.get('rgb',{}).get('brightness',100))
                reply('🎨 '+esc(self.ctrl.rgb_color(value, bright)), self.rgb_menu())
        elif a in ('salva', 'togli'):
            value = arg.strip().lower()
            value = COLORS.get(value, value)
            palette = self.ctrl.rgb_palette()
            if not (len(value) == 7 and value.startswith('#')):
                reply(f'🎨 Scrivi un codice colore, es. <code>/{a} #ff8800</code>', self.rgb_menu())
            else:
                palette = [c for c in palette if c != value] + ([value] if a == 'salva' else [])
                self.ctrl.set_rgb_palette(palette[-18:])
                reply(('💾 Colore salvato: ' if a == 'salva' else '🗑 Colore tolto: ') + value.upper(), self.rgb_menu())
        elif a in ('fans','ventole'):
            reply('🌀 <b>Ventole</b>\n🚀 Massimo: tutte al 100% (case, radiatore, pompa, scheda video).\n⏸ Spente e 🤫 Silenziose: solo quelle del case. Sopra 80 °C tornano normali da sole.', self.fans_menu())
        elif a in ('fans_off','fans_eco','fans_normal','fans_max'):
            reply('🌀 '+esc(self.ctrl.fans_level(a[5:])), self.fans_menu())
        elif a == 'auto':
            old=bool(self.ctrl.config.get('auto_detect',{}).get('enabled'))
            reply('🤖 '+esc(self.ctrl.set_auto(not old)))
        elif a == 'alerts':
            s=self.ctrl.public_settings()
            reply(f'🌡 Avvisi: {"attivi" if s["alerts_enabled"] else "disattivati"}\nCPU ≥ {s["cpu_temp_alert"]}°C · GPU ≥ {s["gpu_temp_alert"]}°C')
        elif a in ('pw', 'accensione'): reply(self.power_status(), self.power_menu())
        elif a.startswith('pwc:') or a in ('spegni', 'riavvia', 'sospendi'):
            kind = a[4:] if a.startswith('pwc:') else {'spegni':'shutdown','riavvia':'restart','sospendi':'sleep'}[a]
            if kind not in POWER_ASK: raise ValueError('Azione non prevista')
            reply('<b>'+POWER_ASK[kind]+'</b>', {'inline_keyboard':[[{'text':'✅ Sì','callback_data':'pwx:'+kind},{'text':'❌ No','callback_data':'pw'}]]})
        elif a.startswith('pwx:'):
            msg = self.ctrl.power_action(a[4:])
            reply('⏻ '+esc(msg), {'inline_keyboard':[[{'text':'✖️ Annulla','callback_data':'pwcancel'}]]} if a[4:] in ('shutdown','restart') else self.power_menu())
        elif a.startswith('t:'):
            reply('⏱ '+esc(self.ctrl.power_action('shutdown', minutes=int(a[2:])))+'\n\n'+self.power_status(), self.power_menu())
        elif a == 'pwai':
            reply('🤖 '+esc(self.ctrl.power_action('shutdown', after_ai=True))+'\n\n'+self.power_status(), self.power_menu())
        elif a in ('pwcancel', 'annulla'): reply('✖️ '+esc(self.ctrl.cancel_power())+'\n\n'+self.power_status(), self.power_menu())
        elif a in ('accendi', 'wake'):
            reply('🟢 Il PC è già acceso.\n<i>Quando è spento, /accendi lo riceve il relay su Umbrel (app → Accensione).</i>', self.power_menu())
        elif a in ('aggiorna', 'versione', 'upd_check'):
            if not self.updater: reply('Aggiornamenti non disponibili.'); return
            try: u = self.updater.check()
            except Exception: u = self.updater.info(); u['message'] = 'GitHub non raggiungibile, riprova più tardi.'
            text = f"⬆️ <b>NEXAR {u['current']}</b>\n{esc(u['message'])}"
            buttons = [[{'text':f"⬇️ Installa {u['latest']}",'callback_data':'upd_install'}]] if u['available'] else []
            reply(text + (f"\n\n<i>{esc(u['notes'][:600])}</i>" if u['available'] and u['notes'] else ''), {'inline_keyboard':buttons+[self.back()]})
        elif a == 'upd_install':
            if not self.updater: reply('Aggiornamenti non disponibili.'); return
            reply('⬆️ '+esc(self.ctrl.run_job('update', self.updater.install))+'\nNEXAR si riavvia da solo: ti scrivo quando è tornato.')
        elif a == 'app':
            if self.webapp_url: reply('📱 Tocca il pulsante per aprire la dashboard.', {'inline_keyboard':self.app_row()+[self.back()]})
            else: reply('📱 App non ancora disponibile: sul PC apri Collegamenti → App Telegram.')
        else:
            reply('Comando non riconosciuto.')

    def run(self, stop: threading.Event):
        logging.info('Bot Telegram: servizio in attesa di configurazione')
        while not stop.is_set():
            try:
                # Permette di abbinare Telegram dalla dashboard senza riavviare il PC.
                config = self.ctrl.config.get('telegram', {})
                next_token = str(config.get('token') or '').strip()
                next_user = int(config.get('allowed_user_id') or 0)
                if not next_token:
                    stop.wait(3)
                    continue
                if next_token == self.bad_token:
                    stop.wait(5)  # token rifiutato da Telegram: si riprova solo quando ne incolli uno nuovo
                    continue
                if next_token != self.token:
                    self.token=next_token
                    self.offset=None
                    self.menu_synced=None
                    # Se Telegram non risponde (rete non ancora pronta all'avvio) si riprova al giro dopo:
                    # così nome del bot e salto dei comandi vecchi non vengono persi.
                    try: known = self.identify()
                    except Exception: self.token = ''; raise
                    if not known: continue
                    if next_user:
                        try:
                            # Se gia abbinato, non eseguire comandi arrivati quando il PC era offline.
                            old=self.call('getUpdates',{'offset':-1,'timeout':0})
                            if old: self.offset=old[-1]['update_id']+1
                        except Exception: logging.warning('Telegram: inizializzazione polling fallita')
                    # Se NON abbinato, leggi anche gli ultimi /pair: il codice effimero e il controllo
                    # della chat privata impediscono di accettare richieste vecchie.
                if next_user != self.user_id: self.menu_synced=None
                self.user_id=next_user
                self.sync_menu_button()
                self.flush_notifications()
                args={'timeout':10,'allowed_updates':json.dumps(['message','callback_query'])}
                if self.offset is not None: args['offset']=self.offset
                updates=self.call('getUpdates',args)
                for event in updates:
                    self.offset=event['update_id']+1
                    message=event.get('message')
                    cb=event.get('callback_query')
                    message_id, arg = None, ''
                    if cb:
                        # Si risponde sempre al callback così il client Telegram chiude lo spinner.
                        try: self.call('answerCallbackQuery',{'callback_query_id':cb['id']})
                        except Exception: pass
                        actor=cb.get('from',{}).get('id')
                        chat=cb.get('message',{}).get('chat',{})
                        message_id=cb.get('message',{}).get('message_id')
                        action=cb.get('data','')
                    elif message:
                        actor=message.get('from',{}).get('id')
                        chat=message.get('chat',{})
                        text=message.get('text','')
                        action=text.split(' ',1)[0].split('@')[0]
                        arg=text.partition(' ')[2]
                    else: continue
                    # Token nuovo: solo /pair CODE in chat privata; codice valido 10 minuti.
                    if not self.user_id and chat.get('type') == 'private' and actor == chat.get('id'):
                        raw=(message or {}).get('text','')
                        if raw.startswith('/pair '):
                            candidate=raw.partition(' ')[2].strip()
                            if self.ctrl.accept_telegram_pair(candidate,actor):
                                self.user_id=actor
                                self.menu_synced=None
                                self.send(actor,'✅ <b>NEXAR collegato.</b> Ora solo tu puoi comandare il PC.',self.menu())
                        continue
                    if actor != self.user_id or chat.get('type') != 'private' or chat.get('id') != self.user_id:
                        logging.warning('Telegram accesso ignorato (non autorizzato)')
                        continue
                    try: self.dispatch(action,chat['id'],message_id,arg)
                    except Exception as ex:
                        logging.exception('Comando Telegram')
                        try: self.send(chat['id'],'⚠️ Operazione non eseguita: '+html.escape(str(ex)[:250]))
                        except Exception: pass
            except HTTPError as ex:
                if ex.code == 401: self.reject_token()  # token revocato mentre l'app era accesa
                else: logging.warning('Telegram non disponibile (HTTP %s)', ex.code)
                stop.wait(6)
            except Exception as ex:
                logging.warning('Telegram temporaneamente non disponibile (dettagli omessi per proteggere il token)')
                stop.wait(6)
