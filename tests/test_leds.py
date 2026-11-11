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

class FakeMsi:
    """Attività "Luci MSI pausa/riprendi" e LEDKeeper2 finti."""
    def __init__(self, monkeypatch, ready=True, running=True):
        import discovery
        self.ready, self.running, self.ran, self.setups = ready, running, [], 0
        monkeypatch.setattr(discovery, 'msi_lights_ready', lambda: self.ready)
        monkeypatch.setattr(discovery, 'msi_lights_setup', self.setup)
        monkeypatch.setattr(discovery, 'msi_lights_run', self.run)
        monkeypatch.setattr(discovery, 'process_running', lambda name: self.running)
        import core
        monkeypatch.setattr(core.time, 'sleep', lambda s: None)
    def setup(self):
        self.setups += 1; self.ready = True; return True
    def run(self, action):
        self.ran.append(action); self.running = action == 'resume'; return True

MSI = lambda i=1: ctl(i, 'MSI MYSTIC LIGHT', [mode('Direct')])

def wait_rgb(c, eco):
    import threading
    real = threading.Thread
    class Now:
        def __init__(self, target, **k): self.t = target
        def start(self): self.t()
    threading.Thread = Now
    try: return c.rgb_profile(eco)
    finally: threading.Thread = real

def test_eco_turns_the_arctic_off_and_msi_puts_it_back(tmp_path, monkeypatch):
    setup(monkeypatch, [ctl(0, 'ENE DRAM', DRAM, active=2), MSI()])
    msi = FakeMsi(monkeypatch)
    c, _ = control(tmp_path, monkeypatch, {'openrgb_exe': __file__, 'msi_off': True})
    wait_rgb(c, True)
    assert msi.ran == ['pause'] and c.state['rgb_msi_paused'] is True
    assert ('colors', 'MSI MYSTIC LIGHT', 0) in FakeClient.log and ('mode', 'ENE DRAM', 'Off') in FakeClient.log
    assert c.events[-1] == 'RGB spenti: ENE DRAM, MSI MYSTIC LIGHT'
    FakeClient.log.clear()
    wait_rgb(c, False)
    assert msi.ran == ['pause', 'resume'] and 'rgb_msi_paused' not in c.state
    assert not [x for x in FakeClient.log if x[1] == 'MSI MYSTIC LIGHT']  # il colore lo rimette MSI Center
    assert 'MSI MYSTIC LIGHT (effetto di MSI Center)' in c.events[-1]

def test_without_the_choice_msi_is_left_alone(tmp_path, monkeypatch):
    setup(monkeypatch, [ctl(0, 'ENE DRAM', DRAM, active=2), MSI()])
    msi = FakeMsi(monkeypatch)
    c, _ = control(tmp_path, monkeypatch, {'openrgb_exe': __file__})
    wait_rgb(c, True)
    assert msi.ran == [] and not [x for x in FakeClient.log if x[1] == 'MSI MYSTIC LIGHT']

def test_keeper_pauses_msi_again_after_a_reboot(tmp_path, monkeypatch):
    setup(monkeypatch, [ctl(0, 'ENE DRAM', DRAM), MSI()])
    msi = FakeMsi(monkeypatch, running=True)  # il servizio di MSI parte da solo all'avvio
    c, log = control(tmp_path, monkeypatch, {'msi_off': True}, {'rgb_off': True, 'rgb_saved': {}})
    assert c.rgb_keep() == 'LED rimessi spenti: ENE DRAM, MSI MYSTIC LIGHT' and msi.ran == ['pause']
    with open(log, 'a') as f: f.write('ResetItem : 6\n')
    msi.running = False  # MSI in pausa: niente da rifare per l'ARCTIC
    assert c.rgb_keep() == 'LED rimessi spenti: ENE DRAM' and msi.ran == ['pause']

def test_switch_creates_the_tasks_once_and_gives_the_arctic_back(tmp_path, monkeypatch):
    setup(monkeypatch, [MSI(0)])
    msi = FakeMsi(monkeypatch, ready=False)
    c, _ = control(tmp_path, monkeypatch, {}, {'rgb_off': True})
    assert 'si spengono con AI ECO' in c.setup_msi_lights(True)
    assert msi.setups == 1 and msi.ran == ['pause'] and c.config['rgb']['msi_off'] is True
    c.setup_msi_lights(True)
    assert msi.setups == 1
    assert c.setup_msi_lights(False) == 'ARCTIC lasciato a MSI Center'
    assert msi.ran[-1] == 'resume' and c.config['rgb']['msi_off'] is False and 'rgb_msi_paused' not in c.state

def test_choosing_a_colour_for_all_brings_msi_back(tmp_path, monkeypatch):
    setup(monkeypatch, [ctl(0, 'Corsair', [mode('Direct')]), MSI()])
    msi = FakeMsi(monkeypatch, running=False)
    c, _ = control(tmp_path, monkeypatch, {'msi_off': True}, {'rgb_off': True, 'rgb_msi_paused': True})
    c.rgb_color('#00ff00')
    assert msi.ran == ['resume'] and not [x for x in FakeClient.log if x[1] == 'MSI MYSTIC LIGHT']

def test_msi_task_script_has_the_commands_inline():
    import discovery
    s = discovery.msi_lights_script()
    assert s.count('Register-ScheduledTask') == 2 and '-RunLevel Highest' in s and 'Start-ScheduledTask' not in s
    assert 'Stop-Service -Name Mystic_Light_Service -Force' in s and 'Start-Service -Name Mystic_Light_Service' in s
    assert '-EncodedCommand' not in s and '.ps1' not in s
