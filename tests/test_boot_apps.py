"""Collegamenti automatici all'accensione, programmi inutili fermati, app da aprire a distanza."""
import json
import pytest
import apps_remote
import discovery
import procstop


def _controller(tmp_path, monkeypatch):
    import core
    monkeypatch.setattr(core, 'STATE_FILE', tmp_path / 'state.json')
    monkeypatch.setattr(core, 'CONFIG_FILE', tmp_path / 'config.json')
    monkeypatch.setattr(core, 'DATA_DIR', tmp_path)
    c = core.Control({})
    return c, core


# ---------- collegamenti ----------
def test_connections_restart_sensors_and_start_fancontrol(tmp_path, monkeypatch):
    c, core = _controller(tmp_path, monkeypatch)
    exe = tmp_path / 'FanControl.exe'; exe.write_text('')
    c.config['fans'] = {'enabled': True, 'fancontrol_exe': str(exe)}
    c.state.update(fans_level='eco')
    c.integrations = [{'key': 'sensors', 'name': 'Sensori', 'level': 'warn', 'detail': 'Avvio in corso…'}]
    restarted, ran = [], []
    monkeypatch.setattr(discovery, 'find_lhm', lambda: str(tmp_path / 'lhm.exe'))
    monkeypatch.setattr(discovery, 'sensors_online', lambda url=None: False)
    monkeypatch.setattr(discovery, 'task_exists', lambda name=None: True)
    monkeypatch.setattr(discovery, 'task_restart', lambda name: restarted.append(name) or True)
    monkeypatch.setattr(discovery, 'lhm_enable_webserver', lambda exe: True)
    monkeypatch.setattr(discovery, 'process_running', lambda n: False)
    monkeypatch.setattr(core, 'cmd', lambda args, t=0: ran.append(args[-1]) or '')
    tries = {}
    assert c.connections_check(tries, age=10, now=100) == {'sensors': False, 'fans': False}
    assert restarted == [] and ran == [discovery.FAN_TASKS['eco']]            # sensori: troppo presto dopo l'avvio
    c.connections_check(tries, age=60, now=110)
    assert restarted == [discovery.LHM_TASK] and len(ran) == 1               # Fan Control: aspetta 2 minuti
    c.connections_check(tries, age=70, now=120)
    assert restarted == [discovery.LHM_TASK]                                 # niente riavvii a raffica
    monkeypatch.setattr(discovery, 'sensors_online', lambda url=None: True)
    c.connections_check(tries, age=80, now=130)
    assert c.integrations[0]['level'] == 'ok'                                # la pagina non resta su "Avvio in corso…"


def test_fans_task_follows_what_you_left(tmp_path, monkeypatch):
    c, _ = _controller(tmp_path, monkeypatch)
    assert c.fans_task_now() == discovery.FAN_TASKS['normal']
    c.state.update(fans_level='off', fans_pump=True)
    assert c.fans_task_now() == discovery.FAN_TASKS['off_pump']
    c.state.update(fans_custom={'/x': 40}, fans_slot='manual_b')
    assert c.fans_task_now() == discovery.FAN_TASKS['manual_b']


def test_boot_report_waits_then_tells(tmp_path, monkeypatch):
    c, _ = _controller(tmp_path, monkeypatch)
    seq = iter([{'sensors': False, 'fans': True}, {'sensors': True, 'fans': True}])
    monkeypatch.setattr(c, 'connections_state', lambda: next(seq))
    notes = []
    class Stop:
        def wait(self, s): return False
    msg = c.boot_report(notes.append, stop_event=Stop(), step=0)
    assert notes == [msg] and 'collegati: sensori, ventole' in msg and '⚠' not in msg


def test_autostart_only_from_installed_app(tmp_path, monkeypatch):
    import sys
    calls = []
    monkeypatch.setattr(discovery, 'autostart_get', lambda: False)
    monkeypatch.setattr(discovery, 'autostart_set', lambda on: calls.append(on))
    monkeypatch.setattr(discovery, 'ensure_shortcuts', lambda state: [])
    for name in ('find_openrgb', 'find_fancontrol', 'find_lhm', 'find_nvidia_smi'): monkeypatch.setattr(discovery, name, lambda: '')
    monkeypatch.setattr(discovery, 'sensors_online', lambda url=None: False)
    monkeypatch.setattr(sys, 'frozen', False, raising=False)
    discovery.autoconfigure({}, {})
    assert calls == []                        # una copia di prova non riscrive l'avvio con Windows
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    discovery.autoconfigure({}, {})
    assert calls == [True]


# ---------- programmi inutili ----------
def test_plan_merges_junk_and_choices():
    p = procstop.plan({'chrome.exe': 'lower', 'overwolf.exe': 'keep', 'explorer.exe': 'close'}, junk_on=True)
    assert p['chrome.exe'] == 'lower' and 'overwolf.exe' not in p and p['manycam.exe'] == 'close'
    assert 'explorer.exe' not in p                      # il sistema non si chiude mai
    assert procstop.plan({'x.exe': 'close'}, junk_on=False) == {'x.exe': 'close'}


class FakeProc:
    def __init__(self, pid, name, user='me', exe=None):
        self.pid, self.info = pid, {'name': name, 'username': user, 'exe': exe or rf'C:\Apps\{name}'}
        self._nice = 32
    def nice(self, v=None):
        if v is None: return self._nice
        self._nice = v


def test_stopper_closes_junk_and_throttles_background_in_eco(monkeypatch):
    procs = [FakeProc(10, 'manycam.exe'), FakeProc(11, 'onedrive.exe'), FakeProc(12, 'codex.exe'), FakeProc(13, 'chrome.exe'),
             FakeProc(14, 'svchost.exe'), FakeProc(15, 'other.exe', user='someone')]
    monkeypatch.setattr(procstop.psutil, 'process_iter', lambda attrs=None: procs)
    monkeypatch.setattr(procstop.psutil, 'Process', lambda pid: next(p for p in procs if p.pid == pid))
    monkeypatch.setattr(procstop, 'visible_pids', lambda: {13})            # chrome ha una finestra aperta
    monkeypatch.setattr(procstop, 'efficiency', lambda pid, on: True)
    s = procstop.Stopper(); s.me = 'me'
    closed = []
    out = s.tick('eco', {}, now=0, closer=lambda n, p, force: closed.append((n, force)) or True)
    assert out == ['manycam.exe'] and closed == [('manycam.exe', True)]
    assert set(s.throttled) == {11}                                         # sfondo sì; Codex, finestre, sistema e altri utenti no
    assert procs[1]._nice == procstop.IDLE
    assert s.tick('eco', {}, now=5, closer=lambda n, p, force: closed.append(n) or True) == []   # richiude solo dopo 20 s
    assert s.tick('eco', {}, now=30, closer=lambda n, p, force: True) == ['manycam.exe']      # ripartito: richiuso
    s.tick('normal', {}, now=40)
    assert s.throttled == {} and procs[1]._nice == 32                       # fuori da AI ECO tutto come prima


def test_stopper_gaming_only_closes(monkeypatch):
    procs = [FakeProc(1, 'overwolf.exe'), FakeProc(2, 'onedrive.exe')]
    monkeypatch.setattr(procstop.psutil, 'process_iter', lambda attrs=None: procs)
    monkeypatch.setattr(procstop, 'visible_pids', lambda: set())
    s = procstop.Stopper(); s.me = 'me'
    assert s.tick('gaming', {}, now=0, closer=lambda n, p, force: True) == ['overwolf.exe']
    assert s.throttled == {}                                                # in Gaming lo sfondo non si rallenta da qui


def test_startup_junk():
    items = [{'id': 'HKCU|Run|Opera', 'name': 'Opera GX Browser Assistant', 'command': r'"C:\x\assistant\browser_assistant.exe" --autostart', 'enabled': True},
             {'id': 'HKCU|Run|Steam', 'name': 'Steam', 'command': r'"C:\Steam\steam.exe" -silent', 'enabled': True},
             {'id': 'HKCU|Run|Old', 'name': 'ManyCam', 'command': r'C:\m\ManyCam.exe', 'enabled': False}]
    assert [j['name'] for j in procstop.startup_junk(items)] == ['Opera GX Browser Assistant']


def test_boost_settings_accept_eco_apps():
    import gaming_boost
    b = gaming_boost.Booster({})
    s = b.update_settings({'eco_apps': {'Chrome.exe': 'lower', 'overwolf.exe': 'keep', 'svchost.exe': 'close', 'x': 'close'}, 'stop_junk': False})
    assert s['eco_apps'] == {'chrome.exe': 'lower', 'overwolf.exe': 'keep'} and s['stop_junk'] is False and s['eco_throttle'] is True
    with pytest.raises(ValueError): b.update_settings({'eco_throttle': 'si'})


# ---------- app da aprire a distanza ----------
START = json.dumps([{'Name': 'Claude', 'AppID': 'Claude_pzs8sxrjxfjjc!Claude'}, {'Name': 'ChatGPT', 'AppID': 'OpenAI.Codex_2p2nqsd0c76g0!App'},
                    {'Name': 'Disinstalla Steam', 'AppID': r'C:\Steam\uninstall.exe'}, {'Name': 'Leggimi', 'AppID': r'C:\x\readme.txt'},
                    {'Name': 'Sito', 'AppID': 'https://example.com'}, {'Name': 'Steam', 'AppID': '{7C5A40EF-A0FB-4BFC-874A-C0F2E0B9FA8E}\\Steam\\steam.exe'}])


def test_start_apps_filters_and_defaults():
    apps = apps_remote.start_apps(force=True, runner=lambda: START)
    assert [a['name'] for a in apps] == ['Claude', 'Codex', 'Steam']        # niente disinstallazioni, guide o siti
    assert apps_remote.defaults(apps) == [{'id': 'Claude_pzs8sxrjxfjjc!Claude', 'name': 'Claude'}, {'id': 'OpenAI.Codex_2p2nqsd0c76g0!App', 'name': 'Codex'}]


def test_launch_uses_shell_appsfolder_and_rejects_bad_ids():
    got = []
    apps_remote.launch('Claude_pzs8sxrjxfjjc!Claude', popen=lambda args, **k: got.append(args))
    assert got == [['explorer.exe', 'shell:AppsFolder\\Claude_pzs8sxrjxfjjc!Claude']]
    for bad in ('', 'a"b', 'x\nexplorer', 'a|b'):
        with pytest.raises(ValueError): apps_remote.launch(bad, popen=lambda *a, **k: None)


def test_remote_apps_only_open_pinned(tmp_path, monkeypatch):
    c, core = _controller(tmp_path, monkeypatch)
    apps_remote.start_apps(force=True, runner=lambda: START)
    monkeypatch.setattr(apps_remote, 'start_apps', lambda force=False, runner=None: apps_remote._cache['apps'])
    opened = []
    monkeypatch.setattr(apps_remote, 'launch', lambda aid, popen=None: opened.append(aid))
    assert [a['name'] for a in c.apps_view()['pinned']] == ['Claude', 'Codex']   # primo avvio: Claude e Codex
    steam = '{7C5A40EF-A0FB-4BFC-874A-C0F2E0B9FA8E}\\Steam\\steam.exe'
    with pytest.raises(ValueError): c.app_open(steam)                          # non nell'elenco: no
    with pytest.raises(ValueError): c.app_pin(r'C:\Windows\System32\cmd.exe', True)   # non nel menu Start: no
    assert 'aggiunta' in c.app_pin(steam, True)
    assert 'Apro Steam' == c.app_open(steam) and opened == [steam]
    c.app_pin(steam, False)
    assert [a['name'] for a in c.apps_view(True)['pinned']] == ['Claude', 'Codex']
    assert json.loads((tmp_path / 'config.json').read_text(encoding='utf-8'))['remote_apps'][0]['name'] == 'Claude'
