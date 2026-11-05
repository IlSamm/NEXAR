"""Schermo visto da lontano, piccoli comandi e avviso quando l'AI finisce."""
import pytest
import ai_watch
import screen_remote


# ---------- fine lavoro dell'AI ----------
def run(watch, loads, step=12, start=0):
    """loads = core usati a ogni lettura; restituisce i lavori finiti."""
    cpu, now, done = 0.0, start, []
    for c in loads:
        cpu += c * step; now += step
        done += watch.tick({'codex.exe'}, now=now, sampler=lambda names, cpu=cpu: {1: ('codex.exe', cpu)})
    return done


def test_long_job_that_stops_is_reported_once():
    w = ai_watch.AiWatch()
    done = run(w, [0] + [0.6] * 25 + [0.01] * 12)        # 5 minuti di lavoro, poi ferma
    assert len(done) == 1 and done[0][0] == 'codex.exe' and 270 <= done[0][1] <= 320
    assert run(w, [0.01] * 10, start=1000) == []          # non ripete l'avviso


def test_short_or_idle_work_is_not_reported():
    assert run(ai_watch.AiWatch(), [0] + [0.6] * 5 + [0] * 12) == []      # un minuto: troppo poco
    assert run(ai_watch.AiWatch(), [0] + [0.05] * 40) == []                # app aperta e ferma
    w = ai_watch.AiWatch()
    run(w, [0] + [0.6] * 20)
    assert w.busy() == ['codex.exe']


def test_new_child_process_counts_and_closed_ones_do_not_go_negative():
    w = ai_watch.AiWatch()
    w.tick({'codex.exe'}, now=0, sampler=lambda n: {1: ('codex.exe', 10.0)})
    w.tick({'codex.exe'}, now=12, sampler=lambda n: {1: ('codex.exe', 10.1), 2: ('codex.exe', 5.0)})   # comando lanciato
    assert w.apps['codex.exe']['ticks'] == 1
    w.tick({'codex.exe'}, now=24, sampler=lambda n: {1: ('codex.exe', 12.0)})                            # comando finito
    assert w.apps['codex.exe']['start'] is not None


def _controller(tmp_path, monkeypatch):
    import core
    monkeypatch.setattr(core, 'STATE_FILE', tmp_path / 'state.json')
    monkeypatch.setattr(core, 'CONFIG_FILE', tmp_path / 'config.json')
    monkeypatch.setattr(core, 'DATA_DIR', tmp_path)
    return core.Control({})


def test_ai_done_notifies_only_when_away(tmp_path, monkeypatch):
    c = _controller(tmp_path, monkeypatch)
    sent = []
    c.notify = sent.append
    monkeypatch.setattr(c.ai_watch, 'tick', lambda names, now=None: [('codex.exe', 600)])
    assert c.ai_done_check(idle=10) == ['✅ Codex ha finito: lavorava da 10 min.'] and sent == []   # sei al PC: solo registro
    c.ai_done_check(idle=600)
    assert sent and sent[0].startswith('✅ Codex ha finito') and 'Vedi schermo' in sent[0]
    c.set_screen_settings(ai_alert=False)
    assert c.ai_done_check(idle=600) == []


# ---------- schermo ----------
def test_capture_scales_and_refuses_black_screen():
    from PIL import Image
    jpg = screen_remote.capture(max_width=800, grab=lambda: Image.new('RGB', (3840, 1080), (40, 90, 160)))
    img = Image.open(__import__('io').BytesIO(jpg))
    assert img.size == (800, 225) and jpg[:2] == b'\xff\xd8'
    with pytest.raises(RuntimeError, match='nero'): screen_remote.capture(grab=lambda: Image.new('RGB', (100, 100)))
    def locked(): raise OSError('screen grab failed')
    with pytest.raises(RuntimeError, match='bloccato'): screen_remote.capture(grab=locked)


def test_screen_view_can_be_turned_off(tmp_path, monkeypatch):
    c = _controller(tmp_path, monkeypatch)
    monkeypatch.setattr(screen_remote, 'capture', lambda: b'jpg')
    assert c.screen_shot() == b'jpg'
    c.set_screen_settings(view=False)
    with pytest.raises(PermissionError): c.screen_shot()


def test_close_window_only_from_list():
    wins = [{'id': 5, 'title': 'Spotify', 'exe': 'Spotify.exe', 'pid': 50, 'hung': True},
            {'id': 6, 'title': 'Desktop', 'exe': 'explorer.exe', 'pid': 60, 'hung': False}]
    posted, killed = [], []
    assert 'Spotify' in screen_remote.close_window(5, listing=wins, post=posted.append)
    assert posted == [5] and killed == []
    screen_remote.close_window(5, force=True, listing=wins, kill=killed.append)
    assert killed == [50]
    with pytest.raises(ValueError): screen_remote.close_window(99, listing=wins, post=posted.append)
    with pytest.raises(ValueError): screen_remote.close_window(6, force=True, listing=wins, kill=killed.append)
    assert killed == [50]


def test_volume_presses_keys():
    keys = []
    assert screen_remote.volume('up', press=keys.append) == 'Volume +10' and keys == [0xAF] * 5
    keys.clear(); screen_remote.volume('mute', press=keys.append)
    assert keys == [0xAD]
    with pytest.raises(ValueError): screen_remote.volume('boom', press=keys.append)


def test_screen_actions_validate(tmp_path, monkeypatch):
    c = _controller(tmp_path, monkeypatch)
    with pytest.raises(ValueError): c.screen_action('format_c')
    with pytest.raises(ValueError): c.screen_action('close', win_id='abc')
    monkeypatch.setattr(screen_remote, 'monitor_off', lambda: 'Schermi spenti')
    assert c.screen_action('monitor_off') == 'Schermi spenti'


# ---------- Telegram ----------
def test_telegram_schermo_sends_photo(tmp_path, monkeypatch):
    import telegram_bot
    c = _controller(tmp_path, monkeypatch)
    bot = telegram_bot.TelegramBot(c)
    photos, texts = [], []
    bot.send_photo = lambda chat, jpg, caption='', markup=None: photos.append((chat, jpg, markup))
    bot.send = lambda chat, msg, markup=None: texts.append(msg)
    monkeypatch.setattr(c, 'screen_shot', lambda who='': b'jpg')
    bot.dispatch('/schermo', 7)
    assert photos[0][:2] == (7, b'jpg') and photos[0][2]['inline_keyboard'][0][0]['callback_data'] == 'schermo'
    def off(who=''): raise PermissionError('disattivato')
    monkeypatch.setattr(c, 'screen_shot', off)
    bot.dispatch('schermo', 7)
    assert 'disattivato' in texts[-1]
    assert {'text': '🖥 Vedi schermo', 'callback_data': 'schermo'} in bot.menu()['inline_keyboard'][-1]

# ---------- pulsanti della dashboard dopo un riavvio ----------
def test_dashboard_buttons_follow_new_link(tmp_path, monkeypatch):
    import telegram_bot
    from urllib.error import HTTPError
    c = _controller(tmp_path, monkeypatch)
    bot = telegram_bot.TelegramBot(c); bot.user_id = 7; bot.token = 't'
    calls = []
    def call(method, payload):
        calls.append((method, payload))
        if method == 'editMessageReplyMarkup' and payload['message_id'] == 2: raise HTTPError('u', 400, 'old', {}, None)
        return {'message_id': 10 + len(calls)} if method == 'sendMessage' else True
    bot.call = call
    bot.webapp_url = 'https://old.trycloudflare.com'
    bot.send(7, 'PC acceso', bot.menu())
    c.state['tg_buttons'].append({'m': 2, 'x': []})          # messaggio ormai cancellato
    bot.send(99, 'altra chat', bot.menu())                     # non è del proprietario: non si tocca
    assert [m['m'] for m in c.state['tg_buttons']] == [11, 2]
    calls.clear()
    bot.set_webapp('https://new.trycloudflare.com'); bot.sync_menu_button()
    edits = [p for m, p in calls if m == 'editMessageReplyMarkup']
    assert len(edits) == 2 and 'new.trycloudflare.com' in edits[0]['reply_markup'] and 'schermo' in edits[0]['reply_markup']
    assert [m['m'] for m in c.state['tg_buttons']] == [11]      # quello cancellato si dimentica
    calls.clear(); bot.refresh_buttons()
    assert not [m for m, p in calls if m == 'editMessageReplyMarkup']   # già aggiornati: nessuna chiamata in più


def test_autostart_falls_back_to_startup_folder(tmp_path, monkeypatch):
    import sys, discovery
    if sys.platform != 'win32': pytest.skip('solo Windows')
    import winreg
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(discovery, 'startup_link', lambda: tmp_path / 'NEXAR.lnk')
    def denied(*a, **k): raise PermissionError('Accesso negato')
    monkeypatch.setattr(winreg, 'OpenKey', denied)
    made = []
    def fake_link(enable):
        made.append(enable)
        if enable: (tmp_path / 'NEXAR.lnk').write_text('x')
    monkeypatch.setattr(discovery, '_startup_link_set', fake_link)
    discovery.autostart_set(True)
    assert made == [True] and discovery.autostart_get()
