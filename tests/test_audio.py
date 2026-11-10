"""Audio: amplificatore (Equalizer APO), impostazioni salvate e comandi dalla dashboard."""
import hashlib
import os
import pytest
import audio

OUT = '{0.0.0.00000000}.{93dcc598-8e2a-41c9-80ff-b5b6b47d3f1f}'
MIC = '{0.0.1.00000000}.{11111111-2222-3333-4444-555555555555}'


def _controller(tmp_path, monkeypatch):
    import core
    monkeypatch.setattr(core, 'STATE_FILE', tmp_path / 'state.json')
    monkeypatch.setattr(core, 'CONFIG_FILE', tmp_path / 'config.json')
    monkeypatch.setattr(core, 'DATA_DIR', tmp_path)
    return core.Control({})


def test_guid_and_text_only_for_real_boosts():
    assert audio.guid_of(OUT) == '{93dcc598-8e2a-41c9-80ff-b5b6b47d3f1f}' and audio.guid_of('rotto') == ''
    text = audio.apo_text({'{93dcc598-8e2a-41c9-80ff-b5b6b47d3f1f}': {'db': 6, 'eq': 'bass'},
                           '{11111111-2222-3333-4444-555555555555}': {'db': 0, 'eq': 'flat'},
                           'Device: all\nPreamp: 40 dB': {'db': 40}})
    assert 'Device: {93dcc598-8e2a-41c9-80ff-b5b6b47d3f1f}\nPreamp: 6 dB\nGraphicEQ: 25 6' in text
    assert '11111111' not in text and '40 dB' not in text      # spento o nome non valido: niente righe
    assert text.rstrip().endswith('Device: all')


def test_config_stock_is_replaced_custom_is_kept(tmp_path):
    stock = 'Preamp: -6 dB\nInclude: example.txt\nGraphicEQ: 25 0; 40 0; 63 0; 100 0\n'
    (tmp_path / 'config.txt').write_text(stock, encoding='utf-8')
    audio.apo_write({}, str(tmp_path))
    assert (tmp_path / 'config.txt').read_text(encoding='utf-8') == 'Include: nexar.txt\n'
    assert (tmp_path / 'config.txt.prima-di-nexar').read_text(encoding='utf-8') == stock
    assert (tmp_path / 'nexar.txt').exists()
    mine = 'Preamp: -2 dB\nGraphicEQ: 25 3; 40 0\n'
    (tmp_path / 'config.txt').write_text(mine, encoding='utf-8')
    audio.apo_write({}, str(tmp_path)); audio.apo_write({}, str(tmp_path))
    assert (tmp_path / 'config.txt').read_text(encoding='utf-8') == mine + 'Include: nexar.txt\n'   # una volta sola


def test_app_names_are_readable():
    assert audio._pretty('FortniteClient-Win64-Shipping.exe') == 'Fortnite'
    assert audio._pretty('msedge.exe') == 'Microsoft Edge' and audio._pretty('RocketLeague.exe') == 'RocketLeague'


def _setup(tmp_path, monkeypatch, payload):
    monkeypatch.setitem(audio.APO_SETUP, 'bytes', len(b'buono'))
    monkeypatch.setitem(audio.APO_SETUP, 'sha256', hashlib.sha256(b'buono').hexdigest())
    asked = []
    def fetch(url, dest):
        with open(dest, 'wb') as f: f.write(payload)
    def runas(exe, args, hidden=False): asked.append((exe, args, hidden)); return True
    inst = audio.Installer(str(tmp_path), log=lambda m: None, fetch=fetch, runas=runas)
    inst.start(); inst.thread.join(5)
    return inst, asked


def test_installer_runs_only_the_official_file(tmp_path, monkeypatch):
    inst, asked = _setup(tmp_path, monkeypatch, b'buono')
    assert inst.info()['step'] == 'select' and len(asked) == 1
    exe, args, hidden = asked[0]
    assert exe.lower().endswith('cmd.exe') and hidden and '/S' in args and 'DeviceSelector.exe' in args
    bad, asked = _setup(tmp_path / 'x', monkeypatch, b'cattivo')
    assert bad.info()['step'] == 'error' and 'ufficiale' in bad.info()['error'] and asked == []
    assert not os.path.exists(tmp_path / 'x' / audio.APO_SETUP['name'])


def test_boost_is_saved_checked_and_written(tmp_path, monkeypatch):
    c = _controller(tmp_path, monkeypatch)
    monkeypatch.setattr(audio, 'apo_paths', lambda: None)
    assert 'installi' in c.audio_boost(OUT, db=8)
    assert c.config['audio']['boosts']['{93dcc598-8e2a-41c9-80ff-b5b6b47d3f1f}'] == {'db': 8.0, 'eq': 'flat'}
    with pytest.raises(ValueError): c.audio_boost(OUT, db=30)        # oltre +18 per le cuffie
    c.audio_boost(MIC, db=22)                                         # il microfono arriva a +24
    with pytest.raises(ValueError): c.audio_boost(OUT, eq='rock')
    with pytest.raises(ValueError): c.audio_boost('nessuno', db=3)
    cfg = tmp_path / 'apo'; cfg.mkdir()
    monkeypatch.setattr(audio, 'apo_paths', lambda: ('C:/x', str(cfg)))
    assert c.audio_boost(OUT, eq='voice') == 'Amplificazione aggiornata'
    assert 'Preamp: 8 dB' in (cfg / 'nexar.txt').read_text(encoding='utf-8')
    c.audio_boost(OUT, db=0, eq='flat')
    assert '{93dcc598' not in str(c.config['audio']['boosts'])


def test_endpoints_and_install_only_from_the_pc(monkeypatch):
    from fastapi.testclient import TestClient
    import main
    seen = []
    monkeypatch.setattr(main.controller, 'audio_device', lambda *a: seen.append(a) or 'Fatto')
    monkeypatch.setattr(main.controller, 'audio_install', lambda: {'step': 'download'})
    local = TestClient(main.app, client=('127.0.0.1', 1000)); h = {'X-PC-ECO-Key': main.key}
    r = local.post('/api/audio/device', json={'id': OUT, 'volume': 40}, headers=h)
    assert r.status_code == 200 and seen[-1] == (OUT, 40, None, None)
    assert local.post('/api/audio/install', json={}, headers=h).json()['setup'] == {'step': 'download'}
    far = TestClient(main.app, client=('203.0.113.9', 1000))
    r = far.post('/api/audio/install', json={}, headers=h)
    assert r.status_code == 409 and 'dal PC' in r.json()['detail']
