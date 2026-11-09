import os
import time
import pytest
import optimizer

def make(path, size=10, age=0):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'x' * size)
    if age: os.utime(path, (time.time() - age, time.time() - age))
    return path

@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """Obiettivi finti in una cartella di prova: i test non toccano mai i file veri."""
    temp, cache, keep = tmp_path / 'Temp', tmp_path / 'Cache', tmp_path / 'Documenti'
    fake = [
        {'key': 'temp', 'name': 'Temp', 'desc': '', 'paths': [temp], 'min_age': optimizer.DAY, 'skip': [temp / 'NEXAR']},
        {'key': 'thumbs', 'name': 'Thumbs', 'desc': '', 'paths': [cache], 'pattern': 'thumbcache_*.db'},
        {'key': 'wintemp', 'name': 'Win', 'desc': '', 'paths': [tmp_path / 'WinTemp'], 'admin': True},
    ]
    monkeypatch.setattr(optimizer, 'targets', lambda: fake)
    return temp, cache, keep

def test_clean_respects_age_skip_and_pattern(sandbox):
    temp, cache, keep = sandbox
    old = make(temp / 'old.tmp', 100, age=2 * optimizer.DAY)
    new = make(temp / 'new.tmp', 100)
    ours = make(temp / 'NEXAR' / 'nexar-admin.ps1', 100, age=2 * optimizer.DAY)
    thumb = make(cache / 'thumbcache_256.db', 50)
    other = make(cache / 'iconcache_256.db', 50)
    doc = make(keep / 'tesi.docx', 500, age=10 * optimizer.DAY)
    report = {i['key']: i for i in optimizer.analyze()['items']}
    assert report['temp']['bytes'] == 100 and report['thumbs']['bytes'] == 50
    res = optimizer.clean(['temp', 'thumbs'])
    assert res['freed'] == 150
    assert not old.exists() and not thumb.exists()
    assert new.exists() and ours.exists() and other.exists() and doc.exists()

def test_admin_items_need_pc(sandbox):
    res = optimizer.clean(['wintemp'], run_elevated=lambda *a, **k: True, allow_admin=False)
    assert res['freed'] == 0 and 'Amministratore da remoto' in res['notes'][0]

def test_unknown_key_rejected(sandbox):
    with pytest.raises(ValueError): optimizer.clean(['documenti'])

def test_human_sizes():
    assert optimizer.human(512) == '512 B' and optimizer.human(1536 * 1024 ** 2) == '1,5 GB'


def test_large_files_lists_only_big_local_files(tmp_path):
    import optimizer
    (tmp_path / 'Video').mkdir(); (tmp_path / 'node_modules').mkdir()
    (tmp_path / 'Video' / 'film.mp4').write_bytes(b'x' * 2048)
    (tmp_path / 'piccolo.txt').write_bytes(b'x' * 10)
    (tmp_path / 'node_modules' / 'pesante.bin').write_bytes(b'x' * 4096)   # cartelle di sviluppo saltate
    r = optimizer.large_files(min_bytes=1024, roots=[tmp_path])
    assert [f['name'] for f in r['files']] == ['film.mp4'] and r['files'][0]['kind'] == 'mp4' and r['total'] == 2048

def test_close_app_refuses_system_processes():
    import optimizer, pytest
    for name in ('explorer.exe', 'svchost.exe', 'NEXAR.exe', r'..\x.exe', 'nonexe'):
        with pytest.raises(ValueError): optimizer.close_app(name)

def test_processes_report_shape():
    import optimizer
    p = optimizer.processes(n=5)
    assert p['count'] > 0 and len(p['by_ram']) <= 5 and {'name', 'cpu', 'bytes', 'closable'} <= set(p['by_ram'][0])
    assert not any(a['closable'] for a in p['by_ram'] if a['name'].lower() in optimizer.NEVER_CLOSE)

def test_clean_history_and_total(tmp_path, monkeypatch):
    import core
    monkeypatch.setattr(core, 'STATE_FILE', tmp_path / 'state.json')
    monkeypatch.setattr(core, 'CONFIG_FILE', tmp_path / 'config.json')
    c = core.Control({})
    c.record_clean(1000, 'rapida'); c.record_clean(500, 'automatica')
    e = c.optimize_extra()
    assert e['freed_total'] == 1500 and [h['kind'] for h in e['history']] == ['automatica', 'rapida'] and e['auto'] is False
    assert 'attiva' in c.set_optimize_auto(True) and c.optimize_extra()['auto'] and c.optimize_extra()['auto_next']
