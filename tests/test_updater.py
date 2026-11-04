import json
import zipfile
import pytest
import updater

class Ctrl:
    def __init__(self): self.state, self.config, self.notes, self.events = {}, {}, [], []
    lock = __import__('threading').RLock()
    def notify(self, m): self.notes.append(m)
    def log_event(self, m): self.events.append(m)

def release(tag, with_hash=True):
    name = f'NEXAR-{tag.lstrip("v")}-win64.zip'
    assets = [{'name': name, 'browser_download_url': f'https://github.com/IlSamm/NEXAR/releases/download/{tag}/{name}'}]
    if with_hash: assets.append({'name': name + '.sha256', 'browser_download_url': assets[0]['browser_download_url'] + '.sha256'})
    return json.dumps({'tag_name': tag, 'assets': assets, 'body': 'Novità'}).encode()

def test_version_compare(monkeypatch, tmp_path):
    monkeypatch.setattr(updater, 'VERSION', '1.0.0')
    u = updater.Updater(Ctrl(), tmp_path, tmp_path, True)
    monkeypatch.setattr(updater, 'fetch', lambda url, limit=0: release('v1.0.1'))
    info = u.check()
    assert info['available'] and info['latest'] == '1.0.1'
    monkeypatch.setattr(updater, 'fetch', lambda url, limit=0: release('v1.0.0'))
    assert not u.check()['available']
    monkeypatch.setattr(updater, 'fetch', lambda url, limit=0: release('v2.0.0', with_hash=False))
    assert not u.check()['available']   # senza hash non si installa niente

def test_safe_extract_rejects_traversal(tmp_path):
    bad = tmp_path / 'bad.zip'
    with zipfile.ZipFile(bad, 'w') as z: z.writestr('../evil.txt', 'x')
    with pytest.raises(RuntimeError): updater.safe_extract(bad, tmp_path / 'out')
    good = tmp_path / 'good.zip'
    with zipfile.ZipFile(good, 'w') as z:
        z.writestr('NEXAR/NEXAR.exe', 'exe'); z.writestr('NEXAR/_internal/base.dll', 'dll')
    assert updater.safe_extract(good, tmp_path / 'out2').name == 'NEXAR'

def test_download_only_from_github(tmp_path):
    with pytest.raises(RuntimeError): updater.download('https://example.com/NEXAR.zip', tmp_path / 'x.zip')

def test_announce_after_update(monkeypatch, tmp_path):
    import core
    monkeypatch.setattr(core, 'STATE_FILE', tmp_path / 'state.json')
    c = Ctrl(); c.state['last_version'] = '0.9.0'
    updater.Updater(c, tmp_path, tmp_path, True).announce()
    assert c.state['last_version'] == updater.VERSION and 'aggiornato' in c.notes[0]

def test_spawn_falls_back_when_breakaway_denied(monkeypatch):
    calls = []
    def fake_popen(args, creationflags=0, **kw):
        calls.append(creationflags)
        if creationflags & updater.CREATE_BREAKAWAY_FROM_JOB: raise PermissionError('job senza breakaway')
        return 'proc'
    monkeypatch.setattr(updater.subprocess, 'Popen', fake_popen)
    assert updater.spawn_detached(['x']) == 'proc' and len(calls) == 2

def test_swap_script_is_plain_batch():
    s = updater.SWAP.format(pid=1234, src=r'C:\T\NEXAR', dst=r'C:\P\NEXAR', log=r'C:\D\update.log', version='v9.9.9', exe='NEXAR.exe')
    low = s.lower()
    assert 'powershell' not in low and 'encodedcommand' not in low and 'bypass' not in low
    assert r'robocopy "C:\T\NEXAR\_internal" "C:\P\NEXAR\_internal" /MIR' in s and 'PID eq 1234' in s
    # le righe di log non devono finire su un handle: "=8>>file" perderebbe la riga
    assert not any(l.startswith('echo') and '>>' in l for l in s.splitlines())
    assert 'taskkill /F /IM NEXAR.exe' in s and r'copy /y "C:\T\NEXAR\NEXAR.exe" "C:\P\NEXAR\NEXAR.exe"' in s
    assert 'timeout /t' not in s  # senza console non aspetta

def test_download_reports_progress(monkeypatch, tmp_path):
    import io, hashlib
    data = b'x' * 700_000
    class Resp(io.BytesIO):
        headers = {'Content-Length': str(len(data))}
        def __enter__(self): return self
        def __exit__(self, *a): pass
    monkeypatch.setattr(updater, 'urlopen', lambda req, timeout=0: Resp(data))
    seen = []
    digest = updater.download('https://github.com/IlSamm/NEXAR/x.zip', tmp_path / 'x.zip', lambda d, t: seen.append((d, t)))
    assert digest == hashlib.sha256(data).hexdigest()
    assert seen[0] == (0, len(data)) and seen[-1] == (len(data), len(data)) and len(seen) >= 3

def test_loop_never_installs(monkeypatch, tmp_path):
    import threading
    c = Ctrl(); u = updater.Updater(c, tmp_path, tmp_path, True)
    monkeypatch.setattr(updater, 'VERSION', '1.0.0')
    monkeypatch.setattr(updater, 'fetch', lambda url, limit=0: release('v1.0.1'))
    monkeypatch.setattr(u, 'install', lambda: (_ for _ in ()).throw(AssertionError('installato da solo')))
    class Stop:
        n = 0
        def wait(self, s):
            Stop.n += 1; return Stop.n > 2
    u.loop(Stop())
    assert u.info()['available'] and len(c.notes) == 1 and 'Aggiorna' in c.notes[0]
