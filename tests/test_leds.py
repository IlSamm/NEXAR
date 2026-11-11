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
