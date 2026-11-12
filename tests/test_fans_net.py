"""Regolazione delle singole ventole (velocità fissa e curva), storico e avvisi della rete, giochi Riot."""
import json
import pytest
import discovery


def test_fan_control_id_maps_sensor_to_control():
    assert discovery.fan_control_id('/lpc/nct6687dr/0/fan/3') == '/lpc/nct6687dr/control/3'
    assert discovery.fan_control_id('/gpu-nvidia/0/fan/1') == '/gpu-nvidia/0/control/1'
    assert discovery.fan_control_id('/amdcpu/0/temperature/2') == ''


def test_curve_duty_interpolates_and_holds_at_ends():
    pts = [[40, 20], [60, 40], [80, 100]]
    assert discovery.curve_duty(pts, 20) == 20
    assert discovery.curve_duty(pts, 50) == 30
    assert discovery.curve_duty(pts, 70) == 70
    assert discovery.curve_duty(pts, 95) == 100


def test_fan_curve_clean_accepts_a_good_curve():
    c = discovery.fan_curve_clean({'src': 'cpu', 'pts': [[35, 30], [55, 45], [70, 70], [80, 100]], 'extra': 1})
    assert c == {'src': 'cpu', 'pts': [[35, 30], [55, 45], [70, 70], [80, 100]]}


@pytest.mark.parametrize('curve', [
    None, {'src': 'disk', 'pts': [[30, 50], [80, 100]]},           # sorgente sconosciuta
    {'src': 'cpu', 'pts': [[30, 50]]},                              # un punto solo
    {'src': 'cpu', 'pts': [[30, 50]] * 7},                          # troppi punti
    {'src': 'cpu', 'pts': [[60, 50], [50, 100]]},                   # temperature in discesa
    {'src': 'cpu', 'pts': [[30, 80], [80, 60]]},                    # velocità in discesa
    {'src': 'cpu', 'pts': [[10, 50], [80, 100]]},                   # temperatura fuori scala
    {'src': 'cpu', 'pts': [[30, 50], [80, 101]]},                   # velocità fuori scala
    {'src': 'cpu', 'pts': [[30, 50.5], [80, 100]]},                 # non intero
    {'src': 'cpu', 'pts': [[30, True], [80, 100]]},                 # bool non è un numero
    {'src': 'cpu', 'pts': [[30, 10], [90, 45]]},                    # a 80 °C sotto il 50%: troppo lenta
])
def test_fan_curve_clean_rejects_bad_curves(curve):
    with pytest.raises(ValueError): discovery.fan_curve_clean(curve)


def test_pump_curve_never_below_minimum():
    with pytest.raises(ValueError): discovery.fan_curve_clean({'src': 'cpu', 'pts': [[30, 20], [70, 100]]}, pump=True)
    assert discovery.fan_curve_clean({'src': 'cpu', 'pts': [[30, 40], [70, 100]]}, pump=True)


def _profile():
    return {'FanControl': {'Controls': [
        {'NickName': 'CPU Fan', 'Identifier': '/lpc/x/control/0', 'Enable': False, 'ManualControl': False, 'ManualControlValue': 50, 'SelectedFanCurve': None},
        {'NickName': 'System Fan #1', 'Identifier': '/lpc/x/control/1', 'Enable': False, 'ManualControl': False, 'ManualControlValue': 50, 'SelectedFanCurve': None},
        {'NickName': 'Pump Fan', 'Identifier': '/lpc/x/control/2', 'Enable': True, 'ManualControl': True, 'ManualControlValue': 60, 'SelectedFanCurve': None}],
        'FanCurves': [{'Name': 'Mia curva'}, {'Name': 'NEXAR /lpc/x/control/9'}]}}


def test_apply_fan_custom_fixed_and_curve():
    prof = discovery.apply_fan_custom(_profile(), {'/lpc/x/control/0': {'src': 'gpu', 'pts': [[40, 30], [80, 100]]}, '/lpc/x/control/1': 25},
                                      {'cpu': '/amdcpu/0/temperature/2', 'gpu': '/gpu-nvidia/0/temperature/0'})
    cpu, case, pump = prof['FanControl']['Controls']
    assert case['Enable'] and case['ManualControl'] and case['ManualControlValue'] == 25 and case['SelectedFanCurve'] is None
    assert cpu['Enable'] and not cpu['ManualControl'] and cpu['SelectedFanCurve'] == {'Name': 'NEXAR /lpc/x/control/0'}
    assert pump['ManualControlValue'] == 60                       # le altre restano come il profilo
    names = [c['Name'] for c in prof['FanControl']['FanCurves']]
    assert names == ['Mia curva', 'NEXAR /lpc/x/control/0']       # le curve vecchie di NEXAR spariscono, quelle dell'utente no
    curve = prof['FanControl']['FanCurves'][1]
    assert curve['SelectedTempSource'] == {'Identifier': '/gpu-nvidia/0/temperature/0'} and curve['Points'] == ['40,30', '80,100']
    json.dumps(prof)                                              # Fan Control legge JSON


def test_apply_fan_custom_needs_the_sensor():
    with pytest.raises(RuntimeError): discovery.apply_fan_custom(_profile(), {'/lpc/x/control/0': {'src': 'gpu', 'pts': [[40, 60], [80, 100]]}}, {'cpu': 'x'})


def _controller(tmp_path, monkeypatch, fans_dir=None):
    import core
    monkeypatch.setattr(core, 'STATE_FILE', tmp_path / 'state.json')
    monkeypatch.setattr(core, 'CONFIG_FILE', tmp_path / 'config.json')
    c = core.Control({})
    c.notes = []
    c.notify = c.notes.append
    return c, core


def test_fan_set_writes_alternate_manual_profiles(tmp_path, monkeypatch):
    c, core = _controller(tmp_path, monkeypatch)
    folder = tmp_path / 'FanControl' / 'Configurations'; folder.mkdir(parents=True)
    exe = tmp_path / 'FanControl' / 'FanControl.exe'; exe.write_text('')
    (folder / discovery.FAN_FILES['normal']).write_text(json.dumps(_profile()), encoding='utf-8')
    c.config['fans'] = {'enabled': True, 'fancontrol_exe': str(exe)}
    ran = []
    monkeypatch.setattr(discovery, 'task_restart', lambda task: ran.append([task]) or True)
    monkeypatch.setattr(core, 'FAN_SPACING', 0)
    monkeypatch.setattr(c, 'fans_manual_ready', lambda: True)
    monkeypatch.setattr(core, 'collect_sensors', lambda url: {'temp_ids': {'cpu': '/amdcpu/0/temperature/2'}})
    assert '40%' in c.fan_set('/lpc/x/control/1', 40)
    assert 'curva' in c.fan_set('/lpc/x/control/0', None, {'src': 'cpu', 'pts': [[40, 30], [80, 100]]})
    a = json.loads((folder / discovery.FAN_FILES['manual_a']).read_text(encoding='utf-8'))
    b = json.loads((folder / discovery.FAN_FILES['manual_b']).read_text(encoding='utf-8'))
    assert a['FanControl']['Controls'][1]['ManualControlValue'] == 40 and not a['FanControl']['FanCurves'][1:]
    assert b['FanControl']['Controls'][1]['ManualControlValue'] == 40          # la ventola fissa resta fissa
    assert b['FanControl']['Controls'][0]['SelectedFanCurve'] == {'Name': 'NEXAR /lpc/x/control/0'}
    assert [r[-1] for r in ran] == [discovery.FAN_TASKS['manual_a'], discovery.FAN_TASKS['manual_b']]
    assert set(c.state['fans_custom']) == {'/lpc/x/control/0', '/lpc/x/control/1'}
    with pytest.raises(ValueError): c.fan_set('/lpc/x/control/2', 10)                     # pompa sotto il minimo
    with pytest.raises(ValueError): c.fan_set('/lpc/x/control/1', 30, {'src': 'cpu', 'pts': [[40, 60], [80, 100]]})
    with pytest.raises(ValueError): c.fan_set('../x', 30)
    c.fan_set('/lpc/x/control/1', None)
    assert set(c.state['fans_custom']) == {'/lpc/x/control/0'}


def test_net_history_and_alerts(tmp_path, monkeypatch):
    c, _ = _controller(tmp_path, monkeypatch)
    def n(ms, q='ottima', loss=0): return {'at': 0, 'internet': {'ms': ms, 'loss': loss}, 'router': {'ms': 1}, 'dns_ms': 20, 'quality': q}
    for ms in (20, 22, 21, 19): assert c.net_alert(c.record_net(n(ms), auto=True)) is None
    assert 'internet a 90 ms' in c.net_alert(c.record_net(n(90, 'lenta')))
    assert c.net_alert(c.record_net(n(None, 'offline', 100))) is None             # già avvisato da poco: niente doppioni
    assert 'di nuovo a posto' in c.net_alert(c.record_net(n(20)))
    e = c.optimize_extra()
    assert len(e['net_history']) == 7 and e['net_history'][-1]['ms'] == 20 and e['net_auto'] is True
    assert 'spenta' in c.set_net_auto(False) and c.optimize_extra()['net_auto'] is False


def test_net_loop_tests_once_an_hour(tmp_path, monkeypatch):
    import optimizer, time
    c, _ = _controller(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(optimizer, 'network_check', lambda: calls.append(1) or {'at': int(time.time()), 'internet': {'ms': 20, 'loss': 0}, 'quality': 'ottima'})
    class Stop:
        n = 0
        def wait(self, s):
            self.n += 1; return self.n > 3
    c.net_loop(Stop())                      # tre giri di fila: una prova sola, le altre aspettano l'ora
    assert len(calls) == 1 and c.state['net_history'][-1]['auto'] is True
    c.set_net_auto(False); c.state['net_history'] = []
    c.net_loop(Stop())
    assert len(calls) == 1                  # spenta: nessuna prova


def test_riot_skips_uninstalled_games(tmp_path):
    import gaming_boost
    client = tmp_path / 'RiotClientServices.exe'; client.write_text('')
    live = tmp_path / 'VALORANT' / 'live'; live.mkdir(parents=True)
    (tmp_path / 'RiotClientInstalls.json').write_text(json.dumps({'associated_client': {str(live) + '/': str(client)}}))
    assert gaming_boost.riot_games(tmp_path) == []                               # cartella vuota: disinstallato
    (live / 'VALORANT.exe').write_text('x')
    assert [g['name'] for g in gaming_boost.riot_games(tmp_path)] == ['VALORANT']

def test_fan_rows_names_and_stopped_fans(tmp_path, monkeypatch):
    c, core = _controller(tmp_path, monkeypatch)
    c.config['hardware'] = {'cooler': 'ARCTIC Liquid Freezer II 240'}
    fans = [{'name': 'CPU Fan', 'rpm': 810, 'ctl': '/lpc/n/control/0'}, {'name': 'Pump Fan #1', 'rpm': 0, 'ctl': '/lpc/n/control/1'},
            {'name': 'System Fan #2', 'rpm': 745, 'ctl': '/lpc/n/control/11'}, {'name': 'System Fan #5', 'rpm': 0, 'ctl': '/lpc/n/control/14'},
            {'name': 'GPU Fan 1', 'rpm': 0, 'ctl': '/gpu-nvidia/0/control/1'}]
    rows = {r['name']: r for r in c.fan_rows(fans)}
    assert rows['CPU Fan']['kind'] == 'aio' and rows['CPU Fan']['label'] == 'Radiatore AIO + pompa'
    assert not rows['Pump Fan #1']['show'] and not rows['System Fan #5']['show']   # connettori vuoti
    assert rows['GPU Fan 1']['show'] and rows['GPU Fan 1']['label'] == 'Scheda video · ventola 1'
    fans[2]['rpm'] = 0   # Spente: resta in elenco perché l'ha già vista girare
    assert {r['name']: r for r in c.fan_rows(fans)}['System Fan #2']['show']
    c.fan_name('/lpc/n/control/11', '  Frontale   alta ')
    assert {r['name']: r for r in c.fan_rows(fans)}['System Fan #2']['label'] == 'Frontale alta'
    c.fan_name('/lpc/n/control/11', '')
    assert {r['name']: r for r in c.fan_rows(fans)}['System Fan #2']['label'] == 'Ventola case 2'

def test_fancontrol_service_counts_as_running(monkeypatch):
    monkeypatch.setattr(discovery, 'process_running', lambda n: n == 'FanControl.Service.exe')
    assert discovery.fancontrol_running()

def test_fan_send_retries_when_the_profile_is_not_loaded(tmp_path, monkeypatch):
    c, core = _controller(tmp_path, monkeypatch)
    c.config['fans'] = {'enabled': True, 'fancontrol_exe': str(tmp_path / 'FanControl.exe')}
    c.events = []; c.log_event = c.events.append
    runs, loaded = [], ['PCECO-Normale.json']
    monkeypatch.setattr(discovery, 'task_restart', lambda t: runs.append(t) or True)
    monkeypatch.setattr(discovery, 'fancontrol_config_loaded', lambda exe: loaded[0])
    monkeypatch.setattr(core.threading, 'Thread', lambda target, **k: type('T', (), {'start': lambda self: target()})())
    monkeypatch.setattr(core, 'FAN_VERIFY_SECONDS', 2)
    c.fan_send('eco', sleep=lambda s: None)
    assert runs == [discovery.FAN_TASKS['eco']] * 2   # non caricato: chiusa e rilanciata una volta
    assert any("non ha caricato" in e for e in c.events)

def test_profiles_go_where_fan_control_reads_them(tmp_path, monkeypatch):
    """Fan Control con la cartella dei profili spostata (opzioni → cartella personalizzata): prima i profili di NEXAR
    finivano altrove e "Silenziose" o "Massimo" non cambiavano nulla."""
    exe = tmp_path / 'FanControl' / 'FanControl.exe'; (exe.parent / 'Configurations').mkdir(parents=True)
    custom = tmp_path / 'Documenti' / 'FanControl'; custom.mkdir(parents=True)
    (exe.parent / 'Configurations' / 'CACHE').write_text(json.dumps({'CurrentConfigFileName': 'Mio.json', 'CustomConfigFolder': str(custom)}))
    monkeypatch.setattr(discovery, 'user_sid', lambda: '')
    assert discovery.fancontrol_config_dir(str(exe)) == custom
    script = discovery.fancontrol_script(str(exe), tmp_path / 'staging')
    assert str(custom / 'PCECO-Eco.json') in script and str(exe.parent / 'Configurations' / 'PCECO-Eco.json') in script
