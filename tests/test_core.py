import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import core

def test_sensor_num():
    assert core.float_num('45,5 Â°C') == 45.5
    assert core.float_num('â€”') is None
    assert core.float_num(None) is None

def test_guids():
    assert core.valid_guid('381b4222-f694-41f0-9685-ff5bb260df2e')
    assert not core.valid_guid('BAD')

def test_no_automatic_hardware_control():
    c=core.Control({'fans':{'enabled':False},'rgb':{'enabled':False}})
    assert 'BIOS' in c.fans_profile(True)
    assert 'non trovato' in c.rgb_profile(True)

def test_sensor_remote_url_blocked():
    assert core.collect_sensors('http://127.0.0.1:9999/evil')['cpu_temp'] is None
