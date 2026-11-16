"""Luci della scheda MSI (l'ARCTIC) comandate col programma ufficiale di MSI tramite NEXAR Admin."""
import json
import os
import shutil
import subprocess
import pytest
import admin_helper as ah
import discovery
import openrgb_sdk as o
from test_leds import FakeClient, setup, ctl, mode, DRAM, control


def msi_ready(c, monkeypatch, calls):
    monkeypatch.setattr(c, 'msi_state', lambda: 'ready')
    monkeypatch.setattr(c.admin, 'call', lambda action, timeout=None, **a: calls.append((action, a)) or True)


def test_runner_only_accepts_off_or_a_steady_colour(tmp_path):
    text = ah.runner_text(tmp_path / 'r.json', tmp_path / 'res.json', r'C:\x\NEXAR.exe', {}, {})
    assert "'msi_light'" in text and "@('Steady') -cnotcontains $style" in text and 'NexarMsi' in text and '@@' not in text
    assert 'MLAPI_SetLedColor' in text and 't.Join(ms)' in text   # se MSI non risponde il runner non resta appeso


def test_sdk_is_installed_only_when_signed_by_msi(tmp_path):
    s = ah.msi_sdk_script()
    assert ah.MSI_SDK_URL in s and "$s.Status -eq 'Valid'" in s and '*MICRO-STAR INTERNATIONAL*' in s and 'catch{}' in s
    assert ah.setup_script(tmp_path / 'a', 'x', 'PC\\me', s).endswith(s)


@pytest.mark.skipif(os.name != 'nt' or not shutil.which('powershell'), reason='serve Windows')
def test_runner_refuses_other_effects_and_a_missing_sdk(tmp_path):
    (tmp_path / 'runner.ps1').write_text(ah.runner_text(tmp_path / 'r.json', tmp_path / 'res.json', r'C:\x\NEXAR.exe', {}, {}), encoding='utf-8-sig')
    def go(args):
        (tmp_path / 'r.json').write_text(json.dumps({'id': 'a', 'action': 'msi_light', 'args': args}), encoding='utf-8')
        subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(tmp_path / 'runner.ps1')], check=True, capture_output=True, timeout=60)
        return json.loads((tmp_path / 'res.json').read_text(encoding='utf-8-sig'))
    assert 'Effetto non previsto' in go({'style': 'Rainbow; Remove-Item C:\\', 'r': 0, 'g': 0, 'b': 0})['message']
    assert 'Colore non valido' in go({'style': 'Steady', 'r': 300, 'g': 0, 'b': 0})['message']
    assert 'Effetto non previsto' in go({'style': 'Off', 'r': 0, 'g': 0, 'b': 0})['message']   # "Off" blocca MSI
    out = go({'style': 'Steady', 'r': 0, 'g': 0, 'b': 0})
    assert out['ok'] is False and 'Sistema adesso' in out['message']


def test_state_needs_mystic_light_admin_and_the_sdk(tmp_path, monkeypatch):
    setup(monkeypatch, [])
    c, _ = control(tmp_path, monkeypatch, {})
    assert c.msi_state() == ''
    monkeypatch.setattr(discovery, 'mystic_light_installed', lambda: True)
    c.msi_state_cache = (0.0, None)
    monkeypatch.setattr(c.admin, 'active', lambda: True)
    monkeypatch.setattr(c.admin, 'current', lambda: True)
    monkeypatch.setattr(c.admin, 'has', lambda name: False)
    assert c.msi_state() == 'setup'
    monkeypatch.setattr(c.admin, 'has', lambda name: name == 'msi/MysticLight_SDK_x64.dll')
    c.msi_state_cache = (0.0, None)
    assert c.msi_state() == 'ready'


def test_colour_for_the_arctic_only(tmp_path, monkeypatch):
    setup(monkeypatch, [ctl(0, 'Corsair', [mode('Direct')])])
    c, _ = control(tmp_path, monkeypatch, {})
    calls = []; msi_ready(c, monkeypatch, calls)
    assert 'ARCTIC' in c.rgb_color('#ff8000', 50, 'msi')
    assert calls == [('msi_light', {'style': 'Steady', 'r': 128, 'g': 64, 'b': 0})] and FakeClient.log == []
    assert c.config['rgb']['device_colors'] == {'msi': '#ff8000'}
    assert {'key': 'msi', 'name': 'ARCTIC e scheda madre (MSI)', 'type': 3, 'leds': 0, 'color': '#ff8000'} in c.rgb_devices()


def test_all_leds_include_msi_and_a_synced_board_is_explained(tmp_path, monkeypatch):
    setup(monkeypatch, [ctl(0, 'Corsair', [mode('Direct')])])
    c, _ = control(tmp_path, monkeypatch, {})
    calls = []; msi_ready(c, monkeypatch, calls)
    msg = c.rgb_color('#00ff00', 100)
    assert 'Corsair' in msg and 'ARCTIC' in msg and calls[-1][1]['g'] == 255
    monkeypatch.setattr(discovery, 'msi_board_synced', lambda: True)
    msg = c.rgb_color('#0000ff', 100)          # gli altri LED cambiano comunque
    assert 'Corsair' in msg and 'togli la catena' in msg and len(calls) == 1
    with pytest.raises(RuntimeError, match='togli la catena'): c.rgb_color('#0000ff', 100, 'msi')


def test_off_and_msi_reset_put_the_arctic_back(tmp_path, monkeypatch):
    setup(monkeypatch, [ctl(0, 'ENE DRAM', DRAM, active=2)])
    c, log = control(tmp_path, monkeypatch, {}, {'rgb_off': True, 'rgb_saved': {'ENE DRAM': {'name': 'ENE DRAM'}}})
    calls = []; msi_ready(c, monkeypatch, calls)
    assert 'ARCTIC' in c.rgb_keep()                      # all'avvio di NEXAR
    assert calls == [('msi_light', {'style': 'Steady', 'r': 0, 'g': 0, 'b': 0})]
    calls.clear(); c.rgb_kept_at = 0
    with open(log, 'a') as f: f.write('ResetItem : 0\t(JRGB1)\t0\n')     # l'ha scritto il comando di NEXAR
    c.rgb_keep()
    assert calls == []
    c.msi_own_at = -1e9
    with open(log, 'a') as f: f.write('ResetItem : 1\t(JARGB_V2_1)\t10\n')  # MSI ha rimesso il suo effetto
    c.rgb_keep()
    assert calls == [('msi_light', {'style': 'Steady', 'r': 0, 'g': 0, 'b': 0})]


def test_drawing_layout_is_saved_and_checked(tmp_path, monkeypatch):
    setup(monkeypatch, [])
    c, _ = control(tmp_path, monkeypatch, {})
    assert c.rgb_layout() == {'zones': {}, 'devices': {}}
    lay = c.set_rgb_layout({'mouse': 'none', 'ram': 'plain', 'gpu': 'led'}, {'Corsair Lighting Node Core': 'fans', 'msi': 'cooler'})
    assert lay == {'zones': {'mouse': 'none', 'ram': 'plain'}, 'devices': {'Corsair Lighting Node Core': 'fans', 'msi': 'cooler'}}
    assert c.config['rgb']['layout'] == lay
    for zones, devices in (({'gpu': 'none'}, {}), ({'case': 'led'}, {}), ({'mouse': 'rainbow'}, {}), ({}, {'x': 'garage'}), ({}, {'': 'ram'})):
        with pytest.raises(ValueError): c.set_rgb_layout(zones, devices)
    assert c.rgb_layout() == lay


def test_msi_off_is_steady_black_never_the_off_effect(tmp_path, monkeypatch):
    setup(monkeypatch, [])
    c, _ = control(tmp_path, monkeypatch, {})
    calls = []; msi_ready(c, monkeypatch, calls)
    c.msi_set(off=True)
    assert calls == [('msi_light', {'style': 'Steady', 'r': 0, 'g': 0, 'b': 0})]
    monkeypatch.setattr(c.admin, 'call', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('MSI Center si è bloccato')))
    assert c.msi_apply(off=True) == ''                     # in automatico: una riga nel registro, poi pausa di 5 minuti
    n = len(c.events)
    assert c.msi_apply(off=True) == '' and len(c.events) == n
