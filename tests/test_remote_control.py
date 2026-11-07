"""Controllo remoto: PIN, sessione, fotogrammi e comandi (senza toccare mouse e tastiera veri)."""
import threading
import pytest
import remote_control as rc

MONS = [{'id': 0, 'name': 'Schermo 1', 'x': 0, 'y': 0, 'w': 2560, 'h': 1440, 'primary': True},
        {'id': 1, 'name': 'Schermo 2', 'x': 2560, 'y': 0, 'w': 1920, 'h': 1080, 'primary': False}]


class Clock:
    def __init__(self): self.t = 1000.0
    def __call__(self): return self.t


class FakeOverlay:
    def __init__(self): self.shown = 0; self.hidden = 0
    def show(self, text): self.shown += 1
    def hide(self): self.hidden += 1


def make(enabled=True, pin='482915', **kw):
    cfg = {'enabled': enabled, 'pin_hash': rc.pin_hash(pin) if pin else '', 'idle_minutes': 10}
    sent, notes = [], []
    moves = []
    inj = rc.Injector(send=sent.append, move=lambda x, y: moves.append((x, y)))
    from PIL import Image
    r = rc.Remote(lambda: cfg, notify=notes.append, log=lambda m: None, injector=inj, overlay=FakeOverlay(),
                  grabber=lambda rect: Image.new('RGB', (rect['w'] // 8, rect['h'] // 8), (30, 60, 90)),
                  mons=lambda: MONS, cursor=lambda: (1280, 720), **kw)
    return r, cfg, sent, moves, notes


def test_pin_rules_and_hash():
    assert rc.valid_pin('482915') and not rc.valid_pin('111111') and not rc.valid_pin('123456') and not rc.valid_pin('12345a')
    h = rc.pin_hash('482915')
    assert rc.pin_ok('482915', h) and not rc.pin_ok('482916', h) and '482915' not in h


def test_start_needs_enabled_and_right_pin():
    r, cfg, *_ = make(enabled=False)
    with pytest.raises(PermissionError, match='spento'): r.start('482915')
    cfg['enabled'] = True
    with pytest.raises(PermissionError, match='PIN sbagliato'): r.start('000001')
    s = r.start('482915', 'Telegram')
    assert len(s['token']) > 30 and [m['id'] for m in s['monitors']] == [0, 1]
    assert r.info()['active'] and r.overlay.shown == 1
    r.end()


def test_five_wrong_pins_lock_and_warn():
    clock = Clock()
    r, cfg, sent, moves, notes = make(clock=clock)
    for _ in range(4):
        with pytest.raises(PermissionError, match='sbagliato'): r.start('999990')
    with pytest.raises(PermissionError, match='15 minuti'): r.start('999990')
    assert any('PIN sbagliati' in n for n in notes)
    with pytest.raises(PermissionError, match='Troppi'): r.start('482915')     # anche quello giusto, finché è bloccato
    clock.t += rc.LOCK_SECONDS + 1
    r.start('482915'); r.end()


def test_input_maps_to_real_pixels_and_keys():
    r, cfg, sent, moves, notes = make()
    tok = r.start('482915')['token']
    r.input(tok, [{'t': 'click', 'b': 'left', 'x': 0.5, 'y': 0.5}])
    assert moves[-1] == (1280, 720) and len(sent[-1]) == 2            # giù + su
    r.configure(tok, mon=1)
    r.input(tok, [{'t': 'move', 'x': 1, 'y': 1}])
    assert moves[-1] == (2560 + 1919, 1079)                             # secondo schermo, ultimo pixel
    r.input(tok, [{'t': 'key', 'k': 'c', 'mods': ['ctrl']}])
    vks = [(i.u.ki.wVk, bool(i.u.ki.dwFlags & 2)) for i in sent[-1]]
    assert vks == [(0x11, False), (0x43, False), (0x43, True), (0x11, True)]
    r.input(tok, [{'t': 'text', 's': 'è\n'}])
    seq = sent[-1]
    assert seq[0].u.ki.wScan == ord('è') and seq[0].u.ki.dwFlags & 4 and seq[2].u.ki.wVk == 0x0D
    r.input(tok, [{'t': 'wheel', 'dy': -240}])
    assert sent[-1][0].u.mi.mouseData == (-240) & 0xFFFFFFFF
    for bad in ([{'t': 'key', 'k': 'rm -rf'}], [{'t': 'boom'}], [{'t': 'down', 'b': 'quarto'}], 'x'):
        with pytest.raises(ValueError): r.input(tok, bad)
    with pytest.raises(PermissionError): r.input('falso', [{'t': 'alive'}])
    r.end()


def test_idle_session_closes():
    clock = Clock()
    r, cfg, sent, moves, notes = make(clock=clock)
    tok = r.start('482915')['token']
    clock.t += 9 * 60
    r.input(tok, [{'t': 'alive'}])                     # "Ancora lì?" allunga la sessione
    clock.t += 9 * 60
    r.input(tok, [{'t': 'alive'}])
    clock.t += 11 * 60
    with pytest.raises(PermissionError, match='inattività'): r.input(tok, [{'t': 'alive'}])
    assert not r.info()['active'] and r.overlay.hidden == 1 and any('terminato' in n for n in notes)


def test_frames_long_poll_and_skip_unchanged():
    r, cfg, *_ = make()
    tok = r.start('482915')['token']
    meta, jpg = r.next(tok, 0, 0, timeout=3)
    if jpg is None: meta, jpg = r.next(tok, meta['v'], 0, timeout=3)
    assert jpg[:2] == b'\xff\xd8' and meta['seq'] == 1 and meta['cursor'] == (0.5, 0.5) and meta['state'] == 'ok'
    meta2, jpg2 = r.next(tok, meta['v'], meta['seq'], timeout=0.6)    # schermo fermo: niente fotogramma nuovo
    assert jpg2 is None
    r.configure(tok, quality='eco', fps=5)
    meta3, jpg3 = r.next(tok, meta2['v'], meta['seq'], timeout=3)
    if jpg3 is None: meta3, jpg3 = r.next(tok, meta3['v'], meta['seq'], timeout=3)
    assert jpg3 and meta3['quality'] == 'eco'
    with pytest.raises(ValueError): r.configure(tok, mon=7)
    r.end()
    with pytest.raises(PermissionError): r.next(tok, 0, 0, timeout=0.1)


def test_locked_pc_is_reported():
    r, cfg, *_ = make()
    def locked(rect): raise OSError('bloccato')
    r._grab = locked
    tok = r.start('482915')['token']
    meta, jpg = r.next(tok, 0, 0, timeout=3)
    if meta['state'] != 'locked': meta, jpg = r.next(tok, meta['v'], 0, timeout=3)
    assert meta['state'] == 'locked' and jpg is None
    r.end()


def test_setup_only_validates_and_api_is_local_only(tmp_path, monkeypatch):
    import core
    monkeypatch.setattr(core, 'STATE_FILE', tmp_path / 'state.json')
    monkeypatch.setattr(core, 'CONFIG_FILE', tmp_path / 'config.json')
    c = core.Control({})
    with pytest.raises(ValueError, match='PIN'): c.remote_setup(enabled=True)
    with pytest.raises(ValueError): c.remote_setup(pin='111111')
    info = c.remote_setup(enabled=True, pin='482915', idle_minutes=15)
    assert info['enabled'] and info['pin_set'] and info['idle_minutes'] == 15
    assert '482915' not in (tmp_path / 'config.json').read_text(encoding='utf-8')
    assert not c.remote_setup(enabled=False)['enabled']


def test_api_pin_setup_only_local_and_frames_over_http(monkeypatch):
    from fastapi.testclient import TestClient
    import json, main
    cfg = {'enabled': True, 'pin_hash': rc.pin_hash('482915'), 'idle_minutes': 10}
    r, _, sent, moves, _ = make()
    r.get_cfg = lambda: cfg
    monkeypatch.setattr(main.controller, 'remote', r)
    h = {'X-PC-ECO-Key': main.key}
    far = TestClient(main.app, client=('192.168.1.49', 1234))
    assert far.post('/api/remote/setup', headers=h, json={'pin': '135790', 'enabled': True}).status_code == 403
    assert far.post('/api/remote/start', headers=h, json={'pin': '000000'}).status_code == 403
    s = far.post('/api/remote/start', headers=h, json={'pin': '482915'}).json()
    hs = {**h, 'X-Remote-Session': s['token']}
    assert far.get('/api/remote/frame', headers=h).status_code == 403            # senza sessione: niente schermo
    f = far.get('/api/remote/frame?v=0&seq=0', headers=hs)
    if f.headers['content-type'].startswith('application/json'): f = far.get(f'/api/remote/frame?v={f.json()["v"]}&seq=0', headers=hs)
    assert f.headers['content-type'] == 'image/jpeg' and json.loads(f.headers['x-remote-meta'])['seq'] >= 1
    assert far.post('/api/remote/input', headers=hs, json={'events': [{'t': 'click', 'x': 0.5, 'y': 0.5}]}).json()['done'] == 1
    assert moves[-1] == (1280, 720)
    assert far.post('/api/remote/config', headers=hs, json={'mon': 1, 'quality': 'sharp'}).json()['quality'] == 'sharp'
    assert far.post('/api/remote/end', headers=h).json()['message'] == 'Controllo terminato'
    assert far.post('/api/remote/input', headers=hs, json={'events': [{'t': 'alive'}]}).status_code == 403


def test_stream_sends_frames_and_ends(monkeypatch):
    import struct, json as js
    r, cfg, *_ = make()
    tok = r.start('482915')['token']
    g = r.stream(tok)
    def read():
        b = next(g); ml, jl = struct.unpack('>II', b[:8])
        assert len(b) == 8 + ml + jl
        return js.loads(b[8:8 + ml]), b[8 + ml:]
    got = [read() for _ in range(3)]
    assert any(j[:2] == b'\xff\xd8' and m['seq'] >= 1 for m, j in got)       # arriva un JPEG nel flusso
    r.end()
    for _ in range(3):
        m, j = read()
        if 'end' in m: break
    assert 'end' in m and not j
    with pytest.raises(StopIteration): next(g)


def test_stream_over_http(monkeypatch):
    from fastapi.testclient import TestClient
    import struct, main
    r, cfg, *_ = make()
    monkeypatch.setattr(main.controller, 'remote', r)
    h = {'X-PC-ECO-Key': main.key}
    far = TestClient(main.app, client=('192.168.1.49', 1234))
    assert far.get('/api/remote/stream', headers=h).status_code == 403         # serve la sessione
    tok = far.post('/api/remote/start', headers=h, json={'pin': '482915'}).json()['token']
    with far.stream('GET', '/api/remote/stream', headers={**h, 'X-Remote-Session': tok}) as resp:
        assert resp.status_code == 200 and 'no-transform' in resp.headers['cache-control']
        buf = b''
        for chunk in resp.iter_bytes():
            buf += chunk
            if len(buf) >= 8:
                ml, jl = struct.unpack('>II', buf[:8])
                if len(buf) >= 8 + ml + jl and jl: break
                if len(buf) >= 8 + ml + jl: buf = buf[8 + ml + jl:]
        r.end()
    assert buf[8 + ml:8 + ml + 2] == b'\xff\xd8'


def test_encode_presets_are_sharper_and_cheap():
    from PIL import Image
    img = Image.new('RGB', (2560, 1440), (20, 40, 60))
    sizes = {k: rc.encode(img, k)[2] for k in rc.QUALITY}
    assert sizes == {'eco': (1280, 720), 'balanced': (1920, 1080), 'sharp': (2560, 1440)}
    assert rc.encode(img, 'eco')[1] == rc.encode(img, 'eco')[1]          # stessa immagine, stessa impronta
    assert 20 in rc.FPS_CHOICES and 30 in rc.FPS_CHOICES
