"""Più controllo: storico per i grafici, tasti multimediali, cartella condivisa (niente percorsi arbitrari)."""
from types import SimpleNamespace
import pytest
import control_plus


def test_history_samples_and_net_rate():
    clock = [100.0]; net = [SimpleNamespace(bytes_recv=1000, bytes_sent=500)]
    h = control_plus.History(lambda: {'cpu': 10, 'gpu': 5, 'ram': 40, 'cpu_temp': 50, 'gpu_temp': 40, 'power': {'total': 120}},
                             clock=lambda: clock[0], counters=lambda: net[0])
    first = h.sample()
    assert first['down'] is None and first['w'] == 120 and first['ct'] == 50
    clock[0] += 5; net[0] = SimpleNamespace(bytes_recv=6000, bytes_sent=1500)
    s = h.sample()
    assert s['down'] == 1000 and s['up'] == 200 and h.latest() == s and len(h.data()) == 2
    for _ in range(control_plus.HISTORY + 5): h.sample()
    assert len(h.data()) == control_plus.HISTORY


def test_media_keys():
    pressed = []
    assert control_plus.media('play', press=pressed.append) == 'Play / pausa' and pressed == [0xB3]
    with pytest.raises(ValueError): control_plus.media('format_c', press=pressed.append)


def test_shared_names_are_safe(tmp_path):
    assert control_plus.safe_name('..\\..\\Windows\\evil.exe') == 'evil.exe'
    assert control_plus.safe_name('a/b:c?.txt') == 'b_c_.txt'
    for bad in ('', '...', 'CON', 'nul.txt'):
        with pytest.raises(ValueError): control_plus.safe_name(bad)
    (tmp_path / 'foto.jpg').write_bytes(b'x'); (tmp_path / 'LEGGIMI').write_bytes(b'x')
    assert control_plus.free_path(tmp_path, 'foto.jpg').name == 'foto (2).jpg'
    assert control_plus.free_path(tmp_path, 'LEGGIMI').name == 'LEGGIMI (2)'
    assert control_plus.shared_file('foto.jpg', tmp_path).name == 'foto.jpg'
    (tmp_path.parent / 'segreto.txt').write_bytes(b's')
    with pytest.raises(FileNotFoundError): control_plus.shared_file('../segreto.txt', tmp_path)
    assert [f['name'] for f in control_plus.list_files(tmp_path)] and all(not f['name'].endswith('.part') for f in control_plus.list_files(tmp_path))


def test_files_api_upload_list_download(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import main
    monkeypatch.setattr(control_plus, 'share_dir', lambda: tmp_path)
    monkeypatch.setattr(main.controller, 'notify', lambda m: None)
    c = TestClient(main.app, client=('127.0.0.1', 1000)); h = {'X-PC-ECO-Key': main.key}
    assert c.post('/api/files/upload?name=x.txt', content=b'ciao').status_code == 401
    r = c.post('/api/files/upload?name=..%2Fnota.txt', headers=h, content=b'ciao').json()
    assert r['name'] == 'nota.txt' and (tmp_path / 'nota.txt').read_bytes() == b'ciao'
    assert c.post('/api/files/upload?name=nota.txt', headers=h, content=b'bis').json()['name'] == 'nota (2).txt'
    names = [f['name'] for f in c.get('/api/files', headers=h).json()['files']]
    assert set(names) == {'nota.txt', 'nota (2).txt'} and not list(tmp_path.glob('*.part'))
    assert c.get('/api/files/get?name=nota.txt', headers=h).content == b'ciao'
    assert c.get('/api/files/get?name=..%2F..%2Fwin.ini', headers=h).status_code == 404
    hist = c.get('/api/history', headers=h).json()
    assert 'samples' in hist and isinstance(hist['disks'], list)
    assert c.post('/api/media', headers=h, json={'action': 'boom'}).status_code == 400
