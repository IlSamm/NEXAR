import json
import energy_model
import pc_power

HW = {'cpu': 'AMD Ryzen 7 9800X3D', 'gpu': 'RTX 3060 Ti', 'motherboard': 'MSI MAG B850 TOMAHAWK MAX WIFI', 'cooler': 'ARCTIC Liquid Freezer II 240'}
INV = {'dimms': 2, 'disks': [{'id': '0', 'kind': 'nvme'}, {'id': '3', 'kind': 'hdd'}]}

def test_estimate_idle_desktop_is_realistic():
    p = energy_model.estimate({'cpu_w': 30, 'gpu_w': 18, 'cpu_load': 3, 'fans': [{'name': 'System Fan #2', 'rpm': 750}],
                               'rgb': {'leds': 60, 'color': '#ff0000', 'brightness': 100, 'off': False}}, {}, HW, INV)
    keys = {i['key'] for i in p['items']}
    assert {'cpu', 'gpu', 'board', 'ram', 'disks', 'cooling', 'rgb', 'usb'} <= keys
    # Un 9800X3D + 3060 Ti al minimo assorbe circa 90–130 W alla presa.
    assert 90 <= p['total'] <= 130
    assert p['low'] < p['total'] < p['high']
    assert 0.3 < p['amps'] < 0.7 and p['voltage'] == 230
    assert abs(p['dc'] - sum(i['watts'] for i in p['items'])) < 0.5

def test_psu_curve_and_monitor():
    low, _ = energy_model.psu_efficiency(40, 750, 'gold')
    mid, _ = energy_model.psu_efficiency(375, 750, 'gold')
    assert low < mid and 0.9 < mid < 0.95
    base = energy_model.estimate({'cpu_w': 30}, {}, HW, INV)
    with_mon = energy_model.estimate({'cpu_w': 30, 'display_on': True}, {'monitor_watts': 25}, HW, INV)
    off_mon = energy_model.estimate({'cpu_w': 30, 'display_on': False}, {'monitor_watts': 25}, HW, INV)
    assert round(with_mon['total'] - base['total']) == 25 and off_mon['total'] == base['total']

def test_leds_off_cost_almost_nothing():
    on = energy_model.rgb_watts(120, '#ffffff', 100, False)
    off = energy_model.rgb_watts(120, '#ffffff', 100, True)
    assert on > 10 and off < 1

def test_magic_packet():
    p = pc_power.magic_packet('34:5A:60:77:D4:8D')
    assert len(p) == 102 and p[:6] == b'\xff' * 6 and p[6:12] == bytes.fromhex('345A6077D48D')

def test_relay_compose_is_valid_and_escaped():
    text = pc_power.relay_compose('123:ABC', 42, '34:5A:60:77:D4:8D', '192.168.0.128', '192.168.0.255')
    doc = json.loads(text.split('\n', 1)[1])
    svc = doc['services']['nexar-accensione']
    assert svc['network_mode'] == 'host' and svc['environment']['PC_MAC'] == '34:5A:60:77:D4:8D'
    compile(svc['command'][3].replace('$$', '$'), 'relay', 'exec')

def test_power_schedule_and_cancel(monkeypatch):
    import core
    c = core.Control({})
    ran = []
    monkeypatch.setattr(pc_power, 'execute', ran.append)
    monkeypatch.setattr(pc_power, 'abort_windows_shutdown', lambda: False)
    assert 'programmato' in c.power_action('shutdown', minutes=30)
    assert c.pc_info()['pending']['seconds_left'] > 1700 and not ran
    assert 'Annullato' in c.cancel_power() and c.power_plan is None
    c.power_action('restart')
    assert ran == ['restart'] and c.pc_info()['pending']['started']
    try: c.power_action('lock', minutes=5); assert False
    except ValueError: pass

def test_bot_only_opens_dashboard():
    # Il bot non comanda il PC a pulsanti: qualunque comando (anche /spegni) mostra solo la dashboard.
    from telegram_bot import TelegramBot
    class Fake:
        config = {}
        def status(self): raise RuntimeError('non serve')
        def power_action(self, *a, **k): raise AssertionError('spento da Telegram')
    bot = TelegramBot(Fake()); sent = []
    bot.webapp_url = 'https://pc.example.org/'
    bot.send = lambda chat, text, markup=None: sent.append((text, markup))
    for cmd in ('/start', '/spegni', 'eco', 'pwx:shutdown', '/qualcosa'): bot.dispatch(cmd, 1)
    for text, markup in sent:
        buttons = [b for row in markup['inline_keyboard'] for b in row]
        # dashboard + foto dello schermo (solo da guardare): nessun comando del PC a pulsanti
        assert buttons == [{'text': '📱 Apri la dashboard', 'web_app': {'url': 'https://pc.example.org/'}},
                           {'text': '🖥 Vedi schermo', 'callback_data': 'schermo'}]
    bot.webapp_url = ''; bot.dispatch('/start', 1)
    assert sent[-1][1] == {'inline_keyboard': [[{'text': '🖥 Vedi schermo', 'callback_data': 'schermo'}]]} and 'collegamento esterno' in sent[-1][0]

def test_led_count_ignores_resized_headers_and_wireless():
    import core
    z = lambda lo, hi, n: {'leds_min': lo, 'leds_max': hi, 'leds_count': n}
    assert core.leds_estimate({'type': 1, 'zones': [z(8, 8, 8)]}) == 8
    assert core.leds_estimate({'type': 0, 'zones': [z(0, 240, 120)] * 4}) == 4 * core.ARGB_HEADER_GUESS
    assert core.leds_estimate({'type': 5, 'zones': [z(1, 1, 1)]}) == 0

def test_rgb_palette_and_exclusion(tmp_path, monkeypatch):
    import core
    monkeypatch.setattr(core, 'CONFIG_FILE', tmp_path / 'config.json')
    c = core.Control({'rgb': {'exclude': ['MSI MYSTIC LIGHT']}})
    assert c.rgb_palette() == core.DEFAULT_PALETTE
    assert c.set_rgb_palette(['#FF8800', '#ff8800', '#123456']) == ['#ff8800', '#123456']
    assert c.rgb_palette() == ['#ff8800', '#123456']
    assert c.rgb_excluded() == ('MSI MYSTIC LIGHT',)
    import pytest
    with pytest.raises(ValueError): c.set_rgb_palette(['rosso'])
    with pytest.raises(ValueError): c.set_rgb_palette(['#000000'] * 19)

def test_gaming_plan_and_back_to_normal(tmp_path, monkeypatch):
    import core
    monkeypatch.setattr(core, 'STATE_FILE', tmp_path / 'state.json')
    calls, active = [], ['381b4222-f694-41f0-9685-ff5bb260df2e']
    def fake_power(*args):
        calls.append(args)
        if args[0] == '/list': return core.HIGH_PERFORMANCE + ' ' + core.BALANCED
        if args[0] == '/duplicatescheme': return 'GUID: 11111111-2222-3333-4444-555555555555'
        if args[0] == '/setactive': active[0] = args[1]
        return ''
    monkeypatch.setattr(core, 'power', fake_power)
    monkeypatch.setattr(core, 'get_guid', lambda: active[0])
    c = core.Control({})
    c.apply_power('gaming')
    assert ('/duplicatescheme', core.HIGH_PERFORMANCE) in calls
    assert ('/setacvalueindex', '11111111-2222-3333-4444-555555555555', 'SUB_PROCESSOR', 'PROCTHROTTLEMIN', 100) in calls
    assert ('/setacvalueindex', '11111111-2222-3333-4444-555555555555', 'SUB_PROCESSOR', 'PERFBOOSTMODE', 2) in calls
    assert c.mode() == 'gaming'
    c.apply_power('eco')
    assert ('/setacvalueindex', '11111111-2222-3333-4444-555555555555', 'SUB_PROCESSOR', 'PERFBOOSTMODE', 0) in calls   # turbo spento
    assert ('/setacvalueindex', '11111111-2222-3333-4444-555555555555', 'SUB_PCIEXPRESS', 'ASPM', 2) in calls
    c.apply_power('normal')
    assert active[0] == core.BALANCED and c.mode() == 'normal'

def test_fan_levels_validation():
    import core, pytest
    c = core.Control({'fans': {'enabled': False}})
    assert 'BIOS' in c.fans_level('max')
    with pytest.raises(ValueError): c.fans_level('turbo')

def test_hardware_names_detected():
    import discovery
    assert discovery.pick_gpu(['Microsoft Basic Display Adapter', 'AMD Radeon(TM) Graphics', 'NVIDIA GeForce RTX 4070']) == 'NVIDIA GeForce RTX 4070'
    assert discovery.pick_gpu(['Parsec Virtual Display Adapter', 'Intel(R) UHD Graphics 770']) == 'Intel(R) UHD Graphics 770'
    assert discovery.board_name('Micro-Star International Co., Ltd.', 'MAG B850 TOMAHAWK MAX WIFI (MS-7E62)') == 'MSI MAG B850 TOMAHAWK MAX WIFI (MS-7E62)'
    assert discovery.board_name('ASUSTeK COMPUTER INC.', 'ROG STRIX B650E-F GAMING WIFI') == 'ASUS ROG STRIX B650E-F GAMING WIFI'

def test_pump_from_sensor_without_cooler_name():
    p = energy_model.estimate({'cpu_w': 30, 'fans': [{'name': 'Pump Fan', 'rpm': 2400}]}, {}, {}, {})
    cooling = next(i for i in p['items'] if i['key'] == 'cooling')
    assert cooling['watts'] == 3.5 and 'pompa' in cooling['detail']

def test_bot_identity_and_rejected_token(monkeypatch, tmp_path):
    import core, telegram_bot
    from urllib.error import HTTPError
    monkeypatch.setattr(core, 'STATE_FILE', tmp_path / 'state.json')
    c = core.Control({})
    bot = telegram_bot.TelegramBot(c)
    calls = []
    def ok(method, payload):
        calls.append(method)
        return {'username': 'NexarPc_Bot'} if method == 'getMe' else True
    bot.call = ok
    assert bot.identify() and c.telegram_bot['username'] == 'NexarPc_Bot'
    assert 'setMyName' in calls and c.state['bot_branded'] == 'NexarPc_Bot'
    calls.clear(); bot.identify()
    assert calls == ['getMe']   # nome e descrizioni impostati una volta sola
    def denied(method, payload): raise HTTPError('u', 401, 'Unauthorized', None, None)
    bot.call = denied; bot.token = 'vecchio'
    assert not bot.identify() and bot.bad_token == 'vecchio' and 'non più valido' in c.telegram_bot['error']

def test_shortcut_script_targets_exe():
    import discovery
    from pathlib import Path
    s = discovery.shortcut_script(r'C:\Apps\NEXAR\NEXAR.exe', [Path(r'C:\Desk\NEXAR.lnk')])
    assert r"TargetPath -ne 'C:\Apps\NEXAR\NEXAR.exe'" in s and r"IconLocation='C:\Apps\NEXAR\NEXAR.exe,0'" in s

def test_max_profile_drives_every_fan(tmp_path, monkeypatch):
    import discovery, json
    cfg = tmp_path / 'Configurations'; cfg.mkdir()
    ctl = lambda ident, nick: {'Identifier': ident, 'NickName': nick, 'Enable': False, 'ManualControl': False}
    (cfg / 'userConfig.json').write_text(json.dumps({'FanControl': {'Controls': [
        ctl('/lpc/nct6687dr/control/0', 'CPU Fan'), ctl('/lpc/nct6687dr/control/1', 'Pump Fan'),
        ctl('/lpc/nct6687dr/control/11', 'System Fan #2'), ctl('NVApiWrapper/0-GA104-A/control/0', 'Control 1 - NVIDIA GeForce RTX 3060 Ti')]}}))
    monkeypatch.setattr(discovery, 'live_fan_rpm', lambda: {'nct6687dr/0': 900, 'nct6687dr/1': 2400, 'nct6687dr/11': 750})
    profiles, chosen = discovery.build_fan_profiles(str(tmp_path / 'FanControl.exe'), 40)
    manual = lambda level: {c['NickName']: c.get('ManualControlValue') for c in profiles[level]['FanControl']['Controls'] if c['ManualControl']}
    assert manual('max') == {'CPU Fan': 100, 'Pump Fan': 100, 'System Fan #2': 100, 'Control 1 - NVIDIA GeForce RTX 3060 Ti': 100}
    every = {'CPU Fan', 'Pump Fan', 'System Fan #2', 'Control 1 - NVIDIA GeForce RTX 3060 Ti'}
    assert manual('off') == dict.fromkeys(every, 0)        # Spente: tutte ferme, pompa compresa
    # Pompa al minimo anche su CPU_FAN: l'ARCTIC Liquid Freezer ha pompa e radiatore sullo stesso cavo.
    assert manual('off_pump') == dict(dict.fromkeys(every, 0), **{'Pump Fan': discovery.PUMP_MIN_PERCENT, 'CPU Fan': discovery.PUMP_MIN_PERCENT})
    assert manual('eco') == {'System Fan #2': 40} and manual('normal') == {} and chosen == ['System Fan #2']

def test_bot_retries_identity_after_network_error(monkeypatch, tmp_path):
    import core, telegram_bot, threading
    monkeypatch.setattr(core, 'STATE_FILE', tmp_path / 'state.json')
    c = core.Control({'telegram': {'token': '123:abc', 'allowed_user_id': 7}})
    bot = telegram_bot.TelegramBot(c)
    stop = threading.Event(); attempts = []
    def call(method, payload):
        if method == 'getMe':
            attempts.append(1)
            if len(attempts) == 1: raise OSError('rete non pronta')
            return {'username': 'NexarPc_Bot'}
        if method == 'getUpdates' and payload.get('offset') != -1: stop.set()
        return []
    bot.call = call
    monkeypatch.setattr(stop, 'wait', lambda t=None: stop.is_set())
    bot.run(stop)
    assert len(attempts) == 2 and c.telegram_bot['username'] == 'NexarPc_Bot'

def test_fan_guard_restores_when_hot(monkeypatch, tmp_path):
    import core, threading
    monkeypatch.setattr(core, 'STATE_FILE', tmp_path / 'state.json')
    c = core.Control({}); c.state['fans_level'] = 'off'
    calls, notes = [], []
    monkeypatch.setattr(c, 'fans_level', lambda level, keep_pump=None: calls.append(level) or 'Ventole: normali')
    c.notify = notes.append
    temps = iter([60, 76])
    monkeypatch.setattr(core, 'collect_sensors', lambda url: {'cpu_temp': next(temps)})
    monkeypatch.setattr(core, 'gpu_read', lambda: {'temp': 50})
    stop = threading.Event(); waits = []
    def wait(t=None):
        waits.append(t)
        if calls: stop.set()
        return stop.is_set()
    monkeypatch.setattr(stop, 'wait', wait)
    c.fan_guard_loop(stop)
    assert calls == ['normal'] and 'CPU a 76' in notes[0] and waits[0] == core.FAN_GUARD_SECONDS


def test_lifetime_stats_and_records(tmp_path, monkeypatch):
    import core
    monkeypatch.setattr(core, 'STATE_FILE', tmp_path / 'state.json')
    monkeypatch.setattr(core, 'CONFIG_FILE', tmp_path / 'config.json')
    c = core.Control({'energy': {'price_eur_kwh': 0.25}})
    c.add_energy(300, 3600, {'cpu_temp': 71, 'gpu_temp': 64}, 'gaming')   # 300 Wh in un'ora di gioco
    c.add_energy(100, 1800, {'cpu_temp': 50}, 'eco')                     # 50 Wh in mezz'ora
    s = c.stats_summary()
    assert s['total_kwh'] == 0.35 and abs(s['total_cost'] - 0.09) < 0.01 and s['on_hours'] == 1.5
    assert s['modes'] == {'gaming': 1.0, 'eco': 0.5} and s['avg_w'] == 233
    assert s['records']['peak_w']['v'] == 300 and s['records']['cpu_temp']['v'] == 71 and s['records']['gpu_temp']['v'] == 64
    d = s['days'][-1]
    assert d['kwh'] == 0.35 and d['peak'] == 300 and d['cpu_temp'] == 71 and d['modes'] == {'gaming': 1.0, 'eco': 0.5}
    assert s['months'][-1]['kwh'] == 0.35 and s['co2_kg'] == 0.1


def test_eco_levels_and_custom(tmp_path, monkeypatch):
    import core, pytest
    monkeypatch.setattr(core, 'STATE_FILE', tmp_path / 'state.json')
    monkeypatch.setattr(core, 'CONFIG_FILE', tmp_path / 'config.json')
    c = core.Control({})
    monkeypatch.setattr(c, 'mode', lambda: 'normal')          # non in ECO: niente da applicare subito
    r = c.set_eco_settings({'level': 'max'})
    e = r['settings']
    assert e['level'] == 'max' and e['cpu'] == 60 and e['turbo_off'] and e['sleep_idle'] == 20 and e['monitor'] == 30
    extra = dict(((s, k), v) for s, k, v in c.eco_power_extra())
    assert extra[('SUB_PROCESSOR', 'PERFBOOSTMODE')] == 0 and extra[('SUB_DISK', 'DISKIDLE')] == 300 and extra[('SUB_PCIEXPRESS', 'ASPM')] == 2
    e = c.set_eco_settings({'turbo_off': False, 'cpu': 85})['settings']
    assert e['level'] == 'custom' and e['turbo_off'] is False and e['cpu'] == 85 and e['park'] == 10
    assert dict(((s, k), v) for s, k, v in c.eco_power_extra())[('SUB_PROCESSOR', 'PERFBOOSTMODE')] == 2
    for bad in ({'cpu': 20}, {'level': 'turbo'}, {'pcie': 'si'}, {}):
        with pytest.raises(ValueError): c.set_eco_settings(bad)

def test_eco_sleep_only_when_ai_done_and_idle(tmp_path, monkeypatch):
    import core
    monkeypatch.setattr(core, 'STATE_FILE', tmp_path / 'state.json')
    monkeypatch.setattr(core, 'CONFIG_FILE', tmp_path / 'config.json')
    c = core.Control({'eco': {'sleep_idle': 20}})
    slept = []
    monkeypatch.setattr(c, 'mode', lambda: 'eco')
    monkeypatch.setattr(c, 'power_action', lambda kind, **k: slept.append(kind))
    running = {'codex': True}
    monkeypatch.setattr(c, 'processes', lambda: running)
    assert not c.eco_sleep_check(now_idle=30 * 60)               # l'AI lavora ancora
    running['codex'] = False
    assert not c.eco_sleep_check(now_idle=10 * 60)               # inattivo da troppo poco
    assert c.eco_sleep_check(now_idle=25 * 60) and slept == ['sleep']
    assert not c.eco_sleep_check(now_idle=26 * 60)               # una volta sola per pausa
    c.eco_sleep_check(now_idle=5)                                # torni al PC: si riarma
    assert c.eco_sleep_check(now_idle=21 * 60) and slept == ['sleep', 'sleep']
