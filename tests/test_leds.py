import openrgb_sdk as o

def mode(name, color_mode=1, colors=()):
    return {'name': name, 'value': 0, 'flags': 0, 'speed_min': 0, 'speed_max': 0, 'brightness_min': 0, 'brightness_max': 0,
            'colors_min': 0, 'colors_max': 0, 'speed': 0, 'brightness': 0, 'direction': 0, 'color_mode': color_mode,
            'colors': list(colors)}

def ctl(i, name, modes, leds=4, active=0):
    return {'index': i, 'name': name, 'type': 1, 'active_mode': active, 'modes': modes,
            'zones': [{'name': 'z', 'type': 0, 'leds_min': leds, 'leds_max': leds, 'leds_count': leds}],
            'colors': [0xff] * leds}

DRAM = [mode('Direct'), mode('Off', 0), mode('Static', 2, [0])]

class FakeClient:
    devices = []
    log = []
    def __init__(self, *a, **k): pass
    def __enter__(self): return self
    def __exit__(self, *a): pass
    def controllers(self): return [dict(x) for x in FakeClient.devices]
    def controller(self, i): return dict(FakeClient.devices[i])
    def set_mode(self, dev, index, m): FakeClient.log.append(('mode', FakeClient.devices[dev]['name'], m['name']))
    def set_colors(self, dev, colors): FakeClient.log.append(('colors', FakeClient.devices[dev]['name'], colors[0]))
    def resize(self, *a): pass

def setup(monkeypatch, devices):
    FakeClient.devices, FakeClient.log = devices, []
    monkeypatch.setattr(o, 'Client', FakeClient)

def test_keys_stay_the_same_when_a_device_comes_and_goes():
    a = [ctl(0, 'ENE DRAM', DRAM), ctl(1, 'ENE DRAM', DRAM), ctl(2, 'DualSense', [mode('Direct')]), ctl(3, 'Corsair', [mode('Direct')])]
    assert o.keys(a) == ['ENE DRAM', 'ENE DRAM#2', 'DualSense', 'Corsair']
    b = [a[0], a[1], dict(a[3], index=2)]
    assert o.keys(b)[2] == 'Corsair'
    assert o.lookup({'3:Corsair': 1}, 'Corsair', a[3]) == 1  # stato salvato dalle versioni prima della 1.0.67

def test_all_off_keeps_saved_state_and_adds_new_devices(monkeypatch):
    setup(monkeypatch, [ctl(0, 'ENE DRAM', DRAM, active=2), ctl(1, 'Corsair', [mode('Direct')]), ctl(2, 'MSI MYSTIC LIGHT', [mode('Direct')])])
    saved = {'0:ENE DRAM': {'name': 'ENE DRAM', 'active_mode': 2}}
    snaps, done = o.all_off(saved, exclude=('MSI MYSTIC LIGHT',))
    assert snaps['0:ENE DRAM'] == saved['0:ENE DRAM'] and 'ENE DRAM' not in snaps
    assert snaps['Corsair']['active_mode'] == 0 and 'MSI MYSTIC LIGHT' not in snaps
    assert done == ['ENE DRAM', 'Corsair']
    assert ('mode', 'ENE DRAM', 'Off') in FakeClient.log
    assert not [x for x in FakeClient.log if x[1] == 'MSI MYSTIC LIGHT']

def test_all_restore_finds_devices_after_the_index_moved(monkeypatch):
    setup(monkeypatch, [ctl(0, 'Corsair', [mode('Direct'), mode('Static', 2, [0])])])
    snap = o.snapshot(ctl(5, 'Corsair', [mode('Direct'), mode('Static', 2, [0])], active=1))
    assert o.all_restore({'Corsair': snap}) == ['Corsair']
    assert FakeClient.log[0] == ('mode', 'Corsair', 'Static')

def control(tmp_path, monkeypatch, rgb, state=None):
    import core
    monkeypatch.setattr(core, 'CONFIG_FILE', tmp_path / 'config.json')
    monkeypatch.setattr(core, 'STATE_FILE', tmp_path / 'state.json')
    log = tmp_path / 'MysticLight.txt'; log.write_text('avvio\n')
    monkeypatch.setattr(core, 'MSI_LIGHT_LOG', log)
    import discovery
    monkeypatch.setattr(discovery, 'port_open', lambda port: True)
    c = core.Control({'rgb': dict(enabled=True, exclude=['MSI MYSTIC LIGHT'], **rgb)})
    c.state.update(state or {})
    c.openrgb_ready = lambda: None
    c.events = []
    c.log_event = c.events.append
    return c, log

def test_msi_reset_puts_the_leds_back_off(tmp_path, monkeypatch):
    setup(monkeypatch, [ctl(0, 'ENE DRAM', DRAM, active=2), ctl(1, 'MSI MYSTIC LIGHT', [mode('Direct')])])
    c, log = control(tmp_path, monkeypatch, {}, {'rgb_off': True, 'rgb_saved': {'ENE DRAM': {'name': 'ENE DRAM'}}})
    assert c.rgb_keep() == 'LED rimessi spenti: ENE DRAM'  # all'avvio di NEXAR: i LED potrebbero essere tornati accesi
    FakeClient.log.clear()
    assert c.rgb_keep() == ''  # niente di nuovo: non si tocca nulla
    with open(log, 'a') as f: f.write('Display Power On : Begin\nResetItem : 6\t(DDR5 DIMM)\t1\n')
    assert c.rgb_keep() == 'LED rimessi spenti: ENE DRAM'
    assert FakeClient.log == [('mode', 'ENE DRAM', 'Off')]
    assert c.events == ['RGB (MSI Center ha rimesso i suoi effetti): LED rimessi spenti: ENE DRAM']
    with open(log, 'a') as f: f.write('WM_DISPLAYCHANGE\n')
    assert c.rgb_keep() == ''  # righe nuove ma nessun effetto riapplicato

def test_resume_puts_the_chosen_colour_back(tmp_path, monkeypatch):
    setup(monkeypatch, [ctl(0, 'ENE DRAM', DRAM), ctl(1, 'Corsair', [mode('Direct')])])
    c, _ = control(tmp_path, monkeypatch, {'normal_color': '#ff0000', 'brightness': 100, 'device_colors': {'1:Corsair': '#0000ff'}})
    c.rgb_keep()
    FakeClient.log.clear()
    assert c.rgb_keep(resumed=True).startswith('Colore #FF0000')
    assert ('colors', 'Corsair', o.color('#0000ff')) == FakeClient.log[-1]
    c.state['rgb_gaming'] = True  # colore del gioco: resta quello
    FakeClient.log.clear()
    assert c.rgb_keep(resumed=True) == '' and FakeClient.log == []

def test_device_colour_is_saved_with_the_stable_key(tmp_path, monkeypatch):
    setup(monkeypatch, [ctl(0, 'Pad', [mode('Direct')]), ctl(1, 'Corsair', [mode('Direct')])])
    c, _ = control(tmp_path, monkeypatch, {'device_colors': {'3:Corsair': '#00ff00'}})
    c.rgb_color('#123456', 100, 'Corsair')
    assert c.config['rgb']['device_colors'] == {'Corsair': '#123456'}
    assert FakeClient.log[-1] == ('colors', 'Corsair', o.color('#123456'))

def test_msi_pause_from_1_0_68_is_undone(tmp_path, monkeypatch):
    """La 1.0.68 poteva lasciare in pausa MSI Center: la funzione è stata tolta, NEXAR lo rimette in funzione una volta."""
    import discovery
    ran = []
    monkeypatch.setattr(discovery, 'msi_lights_ready', lambda: True)
    monkeypatch.setattr(discovery, 'msi_lights_run', lambda action: ran.append(action) or True)
    setup(monkeypatch, [ctl(0, 'ENE DRAM', DRAM)])
    c, _ = control(tmp_path, monkeypatch, {'msi_off': True}, {'rgb_off': True, 'rgb_msi_paused': True, 'rgb_saved': {}})
    c.rgb_keep()
    assert ran == ['resume'] and 'rgb_msi_paused' not in c.state and 'msi_off' not in c.config['rgb']
    assert c.events[0] == "Luci MSI: MSI Center rimesso in funzione, l'ARCTIC torna al suo effetto"
    c.rgb_keep()
    assert ran == ['resume']  # una volta sola

def test_off_is_not_undone_by_the_keeper(tmp_path, monkeypatch):
    """Segnalato: "spegne 1 sec per poi riaccenderli". Il guardiano scattava mentre lo spegnimento era in corso
    e rimetteva il colore normale su tutto."""
    import core
    setup(monkeypatch, [ctl(0, 'ENE DRAM', DRAM, active=2), ctl(1, 'Corsair', [mode('Direct')])])
    exe = tmp_path / 'OpenRGB.exe'; exe.write_text('')
    c, _ = control(tmp_path, monkeypatch, {'openrgb_exe': str(exe), 'normal_color': '#ff0000', 'brightness': 100})
    jobs = []
    monkeypatch.setattr(core.threading, 'Thread', lambda target, **k: type('T', (), {'start': lambda self: jobs.append(target)})())
    monkeypatch.setattr(core, 'RGB_OFF_SETTLE', (0, 0, 0))
    assert c.rgb_profile(True) == 'RGB: spegnimento LED in corso'
    assert c.state['rgb_off'] is True  # stato voluto fissato prima ancora di toccare i LED
    assert c.rgb_keep() == ''  # comando appena dato: il guardiano non tocca nulla
    jobs[0]()
    offs = [x for x in FakeClient.log if x == ('mode', 'ENE DRAM', 'Off')]
    assert len(offs) == 4  # spegnimento + 3 conferme nei secondi successivi
    assert not [x for x in FakeClient.log if x[0] == 'colors' and x[2] == o.color('#ff0000')]
    assert c.state['rgb_off'] is True and 'Corsair' in c.state['rgb_saved']
    FakeClient.log.clear()
    monkeypatch.setattr(core, 'RGB_QUIET_AFTER_USER', 0)
    c.rgb_kept_at = 0.0
    assert c.rgb_keep().startswith('LED rimessi spenti')  # col tempo li tiene spenti, non li riaccende
    assert not [x for x in FakeClient.log if x[0] == 'colors' and x[2] == o.color('#ff0000')]

def test_settle_stops_when_the_user_picks_a_colour(tmp_path, monkeypatch):
    setup(monkeypatch, [ctl(0, 'Corsair', [mode('Direct')])])
    c, _ = control(tmp_path, monkeypatch, {}, {'rgb_off': True, 'rgb_saved': {}})
    stamp = c.rgb_user_at = 5.0
    c.rgb_settle(stamp, sleep=lambda s: c.rgb_color('#00ff00'))
    assert c.state['rgb_off'] is False
    assert FakeClient.log == [('mode', 'Corsair', 'Direct'), ('colors', 'Corsair', o.color('#00ff00'))]

def test_keeper_colour_does_not_change_on_off_state(tmp_path, monkeypatch):
    setup(monkeypatch, [ctl(0, 'Corsair', [mode('Direct')])])
    c, _ = control(tmp_path, monkeypatch, {'normal_color': '#ff0000'})
    c.state.update(rgb_off=True, rgb_saved={'Corsair': {}})
    c.rgb_color('#ff0000', 100, remember=False, quiet=True)
    assert c.state['rgb_off'] is True and 'rgb_saved' in c.state

def test_mode_change_keeps_leds_turned_off_by_hand(tmp_path, monkeypatch):
    import core
    setup(monkeypatch, [ctl(0, 'Corsair', [mode('Direct')])])
    exe = tmp_path / 'OpenRGB.exe'; exe.write_text('')
    c, _ = control(tmp_path, monkeypatch, {'openrgb_exe': str(exe)})
    monkeypatch.setattr(core.threading, 'Thread', lambda target, **k: type('T', (), {'start': lambda self: target()})())
    monkeypatch.setattr(core, 'RGB_OFF_SETTLE', ())
    c.rgb_profile(True)
    assert c.rgb_mode('normal') == '' and c.state['rgb_off'] is True
    c.rgb_profile(False)
    monkeypatch.setattr(c, 'eco_settings', lambda: {'leds_off': True})
    c.rgb_mode('eco')
    assert c.state['rgb_off_by'] == 'mode'
    assert c.rgb_mode('normal') == 'RGB: riaccensione LED in corso' and c.state['rgb_off'] is False

def test_mode_change_during_led_command_does_not_freeze(tmp_path, monkeypatch):
    """Spegnimento LED in corso (tiene rgb_lock e poi vuole lo stato) mentre parte un cambio di modalità che cambia
    colore ai LED: prima set_mode teneva self.lock e aspettava rgb_lock → NEXAR bloccato per sempre."""
    import threading, time
    c, _ = control(tmp_path, monkeypatch, {})
    led_has_lock, mode_has_lock = threading.Event(), threading.Event()
    def led_command():
        with c.rgb_lock:
            led_has_lock.set(); mode_has_lock.wait(2); time.sleep(0.05)
            with c.lock: c.state['led_done'] = True
    def power(value): mode_has_lock.set()
    monkeypatch.setattr(c, 'apply_power', power)
    monkeypatch.setattr(c, 'rgb_mode', lambda value: c.rgb_lock.acquire() and c.rgb_lock.release() or 'luci')
    monkeypatch.setattr(c, 'fans_level', lambda level: '')
    monkeypatch.setattr(c, 'eco_settings', lambda: {'fans_quiet': False, 'leds_off': False})
    c.booster = type('B', (), {'running': None, 'start': lambda self: '', 'stop': lambda self: ''})()
    t = threading.Thread(target=led_command, daemon=True); t.start(); led_has_lock.wait(2)
    m = threading.Thread(target=lambda: c.set_mode('normal'), daemon=True); m.start()
    t.join(3); m.join(3)
    assert not t.is_alive() and not m.is_alive() and c.state.get('led_done')
