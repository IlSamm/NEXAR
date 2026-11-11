"""Temperature: dal JSON di LibreHardwareMonitor ai gruppi della pagina Temperature."""
import temps


def S(text, value, sid, mx=None):
    return {'Text': text, 'Value': f'{value} °C', 'Max': f'{mx if mx is not None else value} °C', 'Type': 'Temperature', 'SensorId': sid}


def dev(name, *sensors):
    return {'Text': name, 'Children': [{'Text': 'Temperatures', 'Children': list(sensors)}]}


TREE = {'Text': 'Sensor', 'Children': [{'Text': 'PC', 'Children': [
    dev('Nuvoton NCT6687D-R', S('CPU Core', 49, '/lpc/nct/0/temperature/0'), S('VRM MOS', 39.5, '/lpc/nct/0/temperature/2')),
    dev('AMD Ryzen 7 9800X3D', S('Core (Tctl/Tdie)', 49, '/amdcpu/0/temperature/2', 90.1), S('CCD1 (Tdie)', 37.6, '/amdcpu/0/temperature/3')),
    dev('Lexar Co Limited - LD5U16     e?z? (#1)', S('DIMM #1', 36.8, '/memory/dimm/1/temperature/0'),
        S('Thermal Sensor High Limit', 55, '/memory/dimm/1/temperature/3')),
    dev('NVIDIA GeForce RTX 3060 Ti', S('GPU Core', 48, '/gpu-nvidia/0/temperature/0'), S('GPU Hot Spot', 60.5, '/gpu-nvidia/0/temperature/2')),
    dev('KINGSTON SA2000M8250G', S('Composite Temperature', 35, '/nvme/1/temperature/0'), S('Warning Temperature', 74, '/nvme/1/temperature/10')),
    dev('WDC WD10EARS', S('Temperature', 34, '/hdd/3/temperature/0')),
]}]}


def test_groups_names_and_limits():
    g = {x['kind']: x for x in temps.groups(TREE)}
    assert [x['kind'] for x in temps.groups(TREE)] == ['cpu', 'gpu', 'board', 'ram', 'disk']
    assert [r['name'] for r in g['cpu']['rows']] == ['Processore', 'CCD 1'] and g['cpu']['rows'][0]['max'] == 90.1
    assert [r['name'] for r in g['gpu']['rows']] == ['Chip', 'Punto più caldo'] and g['gpu']['rows'][1]['hot'] == 90
    assert [r['name'] for r in g['board']['rows']] == ['VRM (alimentazione CPU)']        # "CPU Core" della scheda madre è un doppione
    assert [r['name'] for r in g['ram']['rows']] == ['Banco 1']                         # i limiti del sensore non sono temperature
    disks = {r['name']: r for r in g['disk']['rows']}
    assert disks['Kingston SA2000M8250G']['crit'] == 74 and disks['Kingston SA2000M8250G']['tag'] == 'NVMe'
    assert disks['WD WD10EARS']['tag'] == 'HDD'


def test_no_sensors_no_groups():
    assert temps.groups({}) == [] and temps.groups([]) == []


def _controller(tmp_path, monkeypatch):
    import core
    monkeypatch.setattr(core, 'STATE_FILE', tmp_path / 'state.json')
    monkeypatch.setattr(core, 'CONFIG_FILE', tmp_path / 'config.json')
    monkeypatch.setattr(core, 'DATA_DIR', tmp_path)
    return core.Control({})


def _t(vrm=40, cpu=50):
    return {'temps': [{'kind': 'cpu', 'name': 'Ryzen', 'rows': [{'id': '/amdcpu/0/temperature/2', 'name': 'Processore', 'value': cpu, 'hot': 80, 'crit': 90}]},
                      {'kind': 'board', 'name': 'Scheda madre', 'rows': [{'id': '/lpc/nct/0/temperature/2', 'name': 'VRM (alimentazione CPU)', 'value': vrm, 'hot': 75, 'crit': 95}]}]}


def test_alerts_on_any_sensor_once_and_back(tmp_path, monkeypatch):
    c = _controller(tmp_path, monkeypatch); sent = []; c.notify = sent.append
    c.temps_alerts(_t(vrm=96, cpu=99)); c.temps_alerts(_t(vrm=97, cpu=99))
    assert len(sent) == 1 and 'VRM' in sent[0] and '96' in sent[0]          # la CPU ha già le sue soglie
    c.temps_alerts(_t(vrm=80)); assert len(sent) == 2 and 'rientrata' in sent[1]
    c.config['alerts'] = {'sensors': False}; c.temps_alerts(_t(vrm=99)); assert len(sent) == 2


def test_history_one_snapshot_per_minute(tmp_path, monkeypatch):
    c = _controller(tmp_path, monkeypatch)
    c.temps_track(_t(vrm=40), now=1000); c.temps_track(_t(vrm=41), now=1030); c.temps_track(_t(vrm=42), now=1060)
    h = c.temps_history(['/lpc/nct/0/temperature/2'])
    assert h['t'] == [1000, 1060] and h['s']['/lpc/nct/0/temperature/2'] == [40, 42]


def test_fan_curve_can_follow_a_board_sensor_but_not_a_disk():
    import discovery
    ok = discovery.fan_curve_clean({'src': '/lpc/nct6687dr/0/temperature/2', 'pts': [[30, 30], [70, 80]]})
    assert ok['src'] == '/lpc/nct6687dr/0/temperature/2'
    import pytest
    with pytest.raises(ValueError): discovery.fan_curve_clean({'src': '/nvme/0/temperature/0', 'pts': [[30, 30], [70, 80]]})
    prof = {'FanControl': {'Controls': [{'Identifier': '/lpc/x/control/1'}]}}
    discovery.apply_fan_custom(prof, {'/lpc/x/control/1': ok}, {})
    assert prof['FanControl']['FanCurves'][0]['SelectedTempSource']['Identifier'] == '/lpc/nct6687dr/0/temperature/2'


def test_game_session_keeps_part_maxima():
    import gaming_boost
    m = gaming_boost._part_maxima([{'kind': 'gpu', 'name': 'RTX', 'rows': [{'name': 'Punto più caldo', 'value': 88.4}]},
                                   {'kind': 'disk', 'name': 'Dischi', 'rows': [{'name': 'A', 'value': 40}, {'name': 'B', 'value': 51}]}])
    assert m == {'hotspot': 88.4, 'disk': 51}
