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
