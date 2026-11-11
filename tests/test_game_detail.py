"""Gaming: copertine, profilo di ogni gioco e scheda del gioco."""
import io
import json

import pytest

import game_covers
import gaming_boost


def _png(w=120, h=180):
    from PIL import Image
    buf = io.BytesIO(); Image.new('RGB', (w, h), (200, 30, 90)).save(buf, 'PNG'); return buf.getvalue()


def test_cover_found_on_steam_by_exact_name_and_kept_on_disk(tmp_path):
    calls = []
    def fetch(url):
        calls.append(url)
        if 'storesearch' in url:
            return json.dumps({'items': [{'id': 1, 'name': 'Rocket League Sideswipe'}, {'id': 252950, 'name': 'Rocket League®'}]}).encode()
        return _png() if '/252950/' in url else None
    c = game_covers.Covers(tmp_path, fetch=fetch)
    game = {'id': 'epic-Sugar', 'name': 'Rocket League®'}
    p = c.path(game, 'capsule')
    assert p and p.is_file() and c.appid(game) == '252950'
    n = len(calls)
    assert c.path(game, 'capsule') == p and len(calls) == n          # seconda volta: dal disco, niente internet


def test_cover_not_on_steam_is_not_asked_again(tmp_path):
    calls = []
    def fetch(url):
        calls.append(url); return json.dumps({'items': [{'id': 9, 'name': 'Valorant Tracker'}]}).encode()
    c = game_covers.Covers(tmp_path, fetch=fetch)
    game = {'id': 'riot-valorant', 'name': 'VALORANT'}
    assert c.path(game, 'capsule') is None and c.path(game, 'hero') is None
    assert len(calls) == 1                                           # nome cercato una volta sola
    assert game_covers.Covers(tmp_path, fetch=fetch).path(game, 'capsule') is None and len(calls) == 1


def test_cover_offline_and_custom_cover(tmp_path):
    c = game_covers.Covers(tmp_path, online=lambda: False, fetch=lambda u: pytest.fail('niente internet'))
    game = {'id': 'gog-123', 'name': 'Gioco'}
    assert c.path(game, 'capsule') is None
    with pytest.raises(ValueError): c.set_custom('gog-123', b'non sono una foto')
    c.set_custom('gog-123', _png(800, 1200))
    assert c.path(game, 'capsule') == c.custom('gog-123') and c.path(game, 'logo') is None and c.version('gog-123') > 0
    assert c.remove_custom('gog-123') and c.path(game, 'capsule') is None
    with pytest.raises(ValueError): c.custom('../../x')


def test_game_profile_saved_only_when_different():
    cfg = {}
    b = gaming_boost.Booster(cfg)
    assert b.game_profile('steam-1') == {'auto': True, 'fans': '', 'rgb': None, 'mouse': None}
    p = b.set_game_profile('steam-1', {'fans': 'max', 'rgb': '#FF0000', 'mouse': True, 'auto': False})
    assert p == {'auto': False, 'fans': 'max', 'rgb': '#ff0000', 'mouse': True}
    b.set_game_profile('steam-1', {'fans': '', 'rgb': None, 'mouse': None, 'auto': True})
    assert cfg['gaming_boost']['per_game'] == {}
    for bad in ({'fans': 'turbo'}, {'rgb': 'rosso'}, {'auto': 'si'}):
        with pytest.raises(ValueError): b.set_game_profile('steam-1', bad)
    with pytest.raises(ValueError): b.set_game_profile('../x', {})


def test_session_adds_up_per_game():
    state = {}
    b = gaming_boost.Booster({}, state=state)
    for t in (80, 70):
        b.session = {'start': 0, 'last': 0, 'game': 'Hollow Knight', 'gid': 'steam-367520', 'wh': 100.0,
                     'sum_cpu_temp': t * 2, 'n_cpu_temp': 2, 'max_cpu_temp': t}
        import time as _t
        b.session['start'] = _t.time() - 600
        b.finish_session()
    g = state['games']['steam-367520']
    assert g['sessions'] == 2 and g['cpu_temp_max'] == 80 and g['kwh'] == 0.2 and len(g['recent']) == 2
    assert 'gid' not in g['recent'][0]


def _controller(tmp_path, monkeypatch):
    import core
    monkeypatch.setattr(core, 'STATE_FILE', tmp_path / 'state.json')
    monkeypatch.setattr(core, 'CONFIG_FILE', tmp_path / 'config.json')
    monkeypatch.setattr(core, 'DATA_DIR', tmp_path)
    return core.Control({})


def test_auto_gaming_respects_the_game_choice(tmp_path, monkeypatch):
    c = _controller(tmp_path, monkeypatch)
    modes = []
    monkeypatch.setattr(c, 'set_mode', lambda v, **k: modes.append(v))
    c.booster.set_game_profile('steam-1', {'auto': False})
    c.auto_gaming({'id': 'steam-1', 'name': 'Calmo'}, False)
    assert modes == []
    c.auto_gaming({'id': 'steam-2', 'name': 'Sparatutto'}, False)
    assert modes == ['gaming']


def test_game_detail_and_profile_applied(tmp_path, monkeypatch):
    c = _controller(tmp_path, monkeypatch)
    lib = [{'id': 'steam-367520', 'name': 'Hollow Knight', 'store': 'Steam', 'dir': str(tmp_path), 'size': 5, 'last': 0,
            'launch': 'steam://rungameid/367520', 'cover': False}]
    monkeypatch.setattr(gaming_boost, 'library', lambda force=False: list(lib))
    c.state['games'] = {'steam-367520': {'seconds': 3600, 'last': 10, 'sessions': 3, 'kwh': 0.9, 'cost': 0.27, 'gpu_temp_max': 70}}
    d = c.game_detail('steam-367520')
    assert d['stats']['sessions'] == 3 and d['stats']['gpu_temp_max'] == 70 and d['steam'] and d['appid'] == '367520'
    with pytest.raises(ValueError): c.game_detail('steam-9')
    c.config['fans'] = {'enabled': True, 'gaming_level': 'normal'}
    fans = []; monkeypatch.setattr(c, 'fans_level', lambda lvl: fans.append(lvl) or 'ventole ' + lvl)
    c.save_game_profile('steam-367520', {'fans': 'max'})
    assert c.apply_game_profile({'id': 'steam-367520', 'name': 'Hollow Knight'}) == ['ventole max'] and fans == ['max']
    assert json.loads((tmp_path / 'config.json').read_text(encoding='utf-8'))['gaming_boost']['per_game']['steam-367520'] == {'fans': 'max'}
