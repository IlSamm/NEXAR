"""Bot NEXAR: avvisi dal PC e accesso alla dashboard. Long polling (nessuna porta aperta), solo il proprietario abbinato."""
import html
import json
import queue
import logging
import threading
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

# Il bot non è un telecomando a pulsanti: manda gli avvisi e apre la dashboard (Mini App), dove c'è tutto.
COMMANDS = [('start', 'Apri NEXAR'), ('stato', 'Il PC in breve'), ('schermo', 'Foto dello schermo del PC')]
SCREEN_BTN = {'text': '🖥 Vedi schermo', 'callback_data': 'schermo'}
KEEP_BUTTONS = 25   # ultimi messaggi con il pulsante della dashboard: si aggiornano quando cambia il collegamento

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
        self._buttons = []
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
        if markup and markup.get('inline_keyboard'): payload['reply_markup']=json.dumps(markup)
        res = self.call('sendMessage',payload)
        self.remember(chat_id, res, markup)
        return res
    def send_photo(self, chat_id, jpg, caption='', markup=None):
        """Foto dello schermo: multipart, senza librerie in più."""
        boundary = 'nexar' + str(int(time.time() * 1000))
        fields = {'chat_id': str(chat_id), 'caption': caption[:1000], 'parse_mode': 'HTML'}
        if markup and markup.get('inline_keyboard'): fields['reply_markup'] = json.dumps(markup)
        body = b''.join(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode('utf-8') for k, v in fields.items())
        body += (f'--{boundary}\r\nContent-Disposition: form-data; name="photo"; filename="schermo.jpg"\r\n'
                 'Content-Type: image/jpeg\r\n\r\n').encode('utf-8') + jpg + f'\r\n--{boundary}--\r\n'.encode('utf-8')
        req = Request('https://api.telegram.org/bot'+self.token+'/sendPhoto', data=body, method='POST',
                      headers={'Content-Type': 'multipart/form-data; boundary=' + boundary})
        with urlopen(req, timeout=60) as res: obj = json.load(res)
        if not obj.get('ok'): raise RuntimeError('Telegram API: sendPhoto')
        self.remember(chat_id, obj.get('result'), markup)
        return obj.get('result')
    def edit(self, chat_id, message_id, msg, markup=None):
        """Aggiorna il pannello nello stesso messaggio: la chat non si riempie di risposte."""
        payload={'chat_id':chat_id,'message_id':message_id,'text':msg[:3900],'parse_mode':'HTML','disable_web_page_preview':'true'}
        if markup and markup.get('inline_keyboard'): payload['reply_markup']=json.dumps(markup)
        try: self.call('editMessageText',payload)
        except Exception: return  # testo identico o messaggio troppo vecchio: nessun problema
        self.remember(chat_id, {'message_id': message_id}, markup)

    # ---------- pulsanti della dashboard sempre validi ----------
    # Il collegamento esterno (trycloudflare) cambia a ogni riavvio di NEXAR: i pulsanti dei messaggi
    # già inviati punterebbero a un indirizzo morto. Si ricordano gli ultimi e si aggiornano.
    def _saved(self):
        st = getattr(self.ctrl, 'state', None)
        return st.setdefault('tg_buttons', []) if isinstance(st, dict) else self._buttons
    def _persist(self):
        st = getattr(self.ctrl, 'state', None)
        if not isinstance(st, dict): return
        try:
            from core import json_save, STATE_FILE
            with self.ctrl.lock: json_save(STATE_FILE, st)
        except Exception: logging.warning('Telegram: pulsanti non salvati')
    def remember(self, chat_id, result, markup):
        if chat_id != self.user_id or not isinstance(result, dict) or not result.get('message_id'): return
        rows = (markup or {}).get('inline_keyboard') or []
        extra = [r for r in rows if not any('web_app' in b for b in r)]
        if not rows: return
        saved = self._saved()
        saved[:] = [m for m in saved if m.get('m') != result['message_id']] + [{'m': result['message_id'], 'x': extra}]
        del saved[:-KEEP_BUTTONS]
        self._persist()
    def refresh_buttons(self):
        """Collegamento nuovo: i messaggi recenti ricevono il pulsante della dashboard con l'indirizzo giusto."""
        if not (self.webapp_url and self.user_id): return 0
        saved, done, keep = self._saved(), 0, []
        for m in list(saved):
            if m.get('u') == self.webapp_url: keep.append(m); continue
            markup = {'inline_keyboard': self.app_row() + (m.get('x') or [])}
            try:
                self.call('editMessageReplyMarkup', {'chat_id': self.user_id, 'message_id': m['m'], 'reply_markup': json.dumps(markup)})
                done += 1; keep.append({**m, 'u': self.webapp_url})
            except HTTPError as ex:
                if ex.code == 400: continue          # messaggio cancellato o troppo vecchio: si dimentica
                keep.append(m); break
            except Exception: keep.append(m); break  # rete: si riprova al prossimo cambio
        saved[:] = keep
        self._persist()
        return done

    def set_webapp(self, url):
        self.webapp_url = url or ''
        self.menu_synced = None  # risincronizza il pulsante al prossimo giro del polling

    def sync_menu_button(self):
        if not (self.token and self.user_id) or self.menu_synced == self.webapp_url: return
        button = {'type':'web_app','text':'📱 NEXAR','web_app':{'url':self.webapp_url}} if self.webapp_url else {'type':'commands'}
        try:
            self.call('setChatMenuButton',{'chat_id':self.user_id,'menu_button':json.dumps(button)})
            self.call('setMyCommands',{'commands':json.dumps([{'command':c,'description':d} for c,d in COMMANDS])})
            self.menu_synced = self.webapp_url
        except Exception: logging.warning('Telegram: pulsante app non aggiornato'); return
        try:
            n = self.refresh_buttons()
            if n: logging.info('Telegram: aggiornati %s pulsanti della dashboard', n)
        except Exception: logging.exception('Telegram: pulsanti dei messaggi')

    # ---------- messaggi ----------
    def app_row(self):
        return [[{'text':'📱 Apri la dashboard','web_app':{'url':self.webapp_url}}]] if self.webapp_url else []
    def menu(self):
        """La dashboard (quando il collegamento esterno è pronto) e la foto dello schermo."""
        return {'inline_keyboard': self.app_row() + [[SCREEN_BTN]]}

    def send_screen(self, chat):
        try: jpg = self.ctrl.screen_shot('Telegram')
        except (PermissionError, RuntimeError) as ex:
            self.send(chat, '🖥 ' + html.escape(str(ex)), self.menu()); return
        when = time.strftime('%H:%M:%S')
        self.send_photo(chat, jpg, f'🖥 Schermo del PC alle {when}',
                        {'inline_keyboard': self.app_row() + [[{'text': '🔄 Aggiorna', 'callback_data': 'schermo'}]]})

    def status_text(self):
        s = self.ctrl.status()
        n = lambda v, unit='': '—' if v is None else f'{round(v)}{unit}'
        e, pw, boost = s.get('energy', {}), s.get('power'), s.get('boost') or {}
        mode = {'eco':'🌙 AI ECO','gaming':'🎮 Gaming'}.get(s.get('mode'),'⚡ Normale')
        game = (boost.get('session') or {}).get('game') or (boost.get('running') or {}).get('name')
        lines = [f"<b>NEXAR</b> · {mode}" + (f" · {html.escape(game)}" if game else ''),
                 f"🔌 {n(pw['total'] if pw else None,' W')} · oggi {e.get('today_kwh',0):.2f} kWh ({e.get('today_cost',0):.2f} €)".replace('.', ','),
                 f"🧠 CPU {n(s.get('cpu'),'%')} · {n(s.get('cpu_temp'),'°C')}   🎮 GPU {n(s.get('gpu'),'%')} · {n(s.get('gpu_temp'),'°C')}",
                 f"⏻ Acceso da {duration(s['pc']['uptime_s'])}" + (' · ⏳ ' + html.escape(s['pc']['pending']['label']) if s['pc'].get('pending') else '')]
        try:
            t = self.ctrl.stats_summary()
            if t.get('since'): lines.append(f"📊 Da sempre: {t['total_kwh']:.1f} kWh · {t['total_cost']:.2f} € · {t['on_hours']:.0f} h acceso".replace('.', ','))
        except Exception: pass
        return '\n'.join(lines)

    def home_text(self):
        try: summary = self.status_text()
        except Exception: summary = '<b>NEXAR</b>'
        hint = ('Tocca <b>📱 Apri la dashboard</b>: lì trovi modalità, Gaming, Ottimizza, luci, ventole e accensione.'
                if self.webapp_url else 'La dashboard da Telegram si attiva quando il collegamento esterno è pronto (sul PC: Collegamenti → App Telegram).')
        return summary + '\n\n' + hint + '\n<i>Gli avvisi del PC arrivano qui da soli.</i>'

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
        """Qualsiasi messaggio (o pulsante di vecchi messaggi): riepilogo e pulsante della dashboard."""
        a = action.lstrip('/')
        if a in ('schermo', 'screen'): return self.send_screen(chat)
        if a in ('accendi', 'wake'):
            text = '🟢 Il PC è già acceso.\n<i>Quando è spento, /accendi lo riceve il relay su Umbrel.</i>'
        else: text = self.home_text()
        if message_id: self.edit(chat, message_id, text, self.menu())
        else: self.send(chat, text, self.menu())

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
                                self.send(actor,'✅ <b>NEXAR collegato.</b> Qui ti arrivano gli avvisi del PC; con 📱 apri la dashboard.',self.menu())
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
