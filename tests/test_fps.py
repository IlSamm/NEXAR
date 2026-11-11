"""FPS da RivaTuner e statistiche delle partite."""
import struct
import time

import fps
import gaming_boost


def _rtss(apps, size=4 + 260 + 40, offset=64):
    head = struct.pack('<5I', fps.SIGNATURE, 0x00020015, size, offset, len(apps)).ljust(offset, b'\0')
    body = b''
    for pid, name, t0, t1, frames, ft in apps:
        e = struct.pack('<I', pid) + name.encode().ljust(260, b'\0') + struct.pack('<5I', 0, t0, t1, frames, ft)
        body += e.ljust(size, b'\0')
    return head + body


def test_parse_rtss_memory():
    buf = _rtss([(10, r'C:\Games\RocketLeague.exe', 1000, 2000, 144, 6900), (0, '', 0, 0, 0, 0), (11, 'x.exe', 0, 0, 0, 16667)])
    apps = fps.parse(buf)
    assert apps[10]['fps'] == 144.0 and apps[10]['exe'].endswith('RocketLeague.exe') and apps[10]['frametime_ms'] == 6.9
    assert apps[11]['fps'] == 60.0 and 0 not in apps
    assert fps.parse(b'DEAD' + buf[4:]) == {} and fps.parse(b'') == {}
    assert fps.parse(buf[:200]) == {}                                   # memoria troncata: niente letture fuori
    assert fps.game_fps({99, 10}, reader=lambda: apps) == 144.0
    assert fps.game_fps({99}, fallback_pid=11, reader=lambda: apps) == 60.0
    assert fps.game_fps({99}, reader=lambda: apps) is None
    assert fps.game_fps({10}, reader=lambda: (_ for _ in ()).throw(OSError())) is None


def test_session_fps_summary_and_per_game_stats():
    state = {}
    b = gaming_boost.Booster({}, state=state)
    now = time.time()
    b.session = {'start': now - 1200, 'last': now - 1200, 'game': 'Rocket League', 'gid': 'epic-Sugar', 'wh': 50.0}
    for i in range(240):                                                # 20 minuti, un campione ogni 5 s
        f = 60 if 100 <= i < 112 else 200 if 200 <= i < 212 else 140
        b.session['points'] = b.session.get('points', []) + [[i * 5, f, 70, 65, 90, 400]]
    v = b.finish_session()
    assert v['fps_max'] == 200 and v['fps_low'] == 60 and 135 < v['fps_avg'] < 145
    assert v['fps_best_at'] == {'t': 1000, 'fps': 200.0} and v['fps_worst_at'] == {'t': 500, 'fps': 60.0}
    g = state['games']['epic-Sugar']
    assert g['fps_max'] == 200 and g['fps_best']['fps'] == v['fps_avg'] and len(g['recent'][0]['points']) == 120
    assert 'points' not in state['gaming_history'][0]
    assert g['w_fps_avg'][1] == v['elapsed']


def test_sample_records_points():
    b = gaming_boost.Booster({})
    b.session = {'start': time.time() - 10, 'last': time.time() - 5, 'game': '', 'gid': '', 'wh': 0.0}
    b.sample({'fps': 120.4, 'cpu_temp': 61, 'gpu_temp': 55, 'gpu': 80, 'power': {'total': 350}})
    b.sample({'fps': None, 'cpu_temp': 62})
    p = b.session['points']
    assert p[0][1:] == [120.4, 61.0, 55.0, 80.0, 350.0] and p[1][1] is None and b.session['max_fps'] == 120.4


def test_downsample_keeps_shape():
    pts = [[i, float(i), None] for i in range(1000)]
    d = gaming_boost.downsample(pts, 100)
    assert len(d) == 100 and d[0][0] == 0 and d[0][1] == 4.5 and d[0][2] is None
