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
    assert res['freed'] == 0 and 'solo dall' in res['notes'][0]

def test_unknown_key_rejected(sandbox):
    with pytest.raises(ValueError): optimizer.clean(['documenti'])

def test_human_sizes():
    assert optimizer.human(512) == '512 B' and optimizer.human(1536 * 1024 ** 2) == '1,5 GB'
