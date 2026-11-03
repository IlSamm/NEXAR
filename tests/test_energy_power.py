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

def test_bot_power_needs_confirmation():
    from telegram_bot import TelegramBot
    class Fake:
        config = {}
        def pc_info(self): return {'uptime_s': 3600, 'pending': None, 'hibernate': False}
        def power_action(self, *a, **k): raise AssertionError('spento senza conferma')
    bot = TelegramBot(Fake()); sent = []
    bot.send = lambda chat, text, markup=None: sent.append((text, markup))
    bot.dispatch('/spegni', 1)
    buttons = [b['callback_data'] for row in sent[-1][1]['inline_keyboard'] for b in row]
    assert buttons == ['pwx:shutdown', 'pw']

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

def test_bot_palette_buttons_and_save():
    from telegram_bot import TelegramBot
    class Fake:
        config = {}
        pal = ['#ff8800']
        def rgb_palette(self): return list(self.pal)
        def set_rgb_palette(self, colors): self.pal = colors; return colors
    f = Fake(); bot = TelegramBot(f); sent = []
    bot.send = lambda chat, text, markup=None: sent.append((text, markup))
    bot.dispatch('/salva', 1, arg='#00aaff')
    assert f.pal == ['#ff8800', '#00aaff']
    data = [b['callback_data'] for row in sent[-1][1]['inline_keyboard'] for b in row]
    assert 'c:#00aaff' in data
    bot.dispatch('/togli', 1, arg='#ff8800')
    assert f.pal == ['#00aaff']

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
    assert c.mode() == 'gaming'
    c.apply_power('normal')
    assert active[0] == core.BALANCED and c.mode() == 'normal'

def test_fan_levels_validation():
    import core, pytest
    c = core.Control({'fans': {'enabled': False}})
    assert 'BIOS' in c.fans_level('max')
    with pytest.raises(ValueError): c.fans_level('turbo')
