"""Altre app che comandano ventole e luci, OpenRGB in una copia sola, Fan Control ridotto a icona."""
import json
import psutil
import pytest
import admin_helper as ah
import discovery

ORIGINAL = discovery.conflicts_running   # letta prima che conftest la sostituisca


def _controller(tmp_path, monkeypatch):
    import core
    monkeypatch.setattr(core, 'STATE_FILE', tmp_path / 'state.json')
    monkeypatch.setattr(core, 'CONFIG_FILE', tmp_path / 'config.json')
    monkeypatch.setattr(core, 'DATA_DIR', tmp_path)
    return core.Control({}), core


class FakeProc:
    killed, denied = [], set()
    def __init__(self, pid): self.pid = pid
    def kill(self):
        if self.pid in FakeProc.denied: raise psutil.AccessDenied(self.pid)
        FakeProc.killed.append(self.pid)


def test_apps_close_kills_user_apps_and_asks_admin_for_elevated_ones(tmp_path, monkeypatch):
    c, core = _controller(tmp_path, monkeypatch)
    running = {'armoury': [11, 12], 'openrgb_extra': [20]}
    monkeypatch.setattr(discovery, 'conflicts_running', lambda: dict(running))
    FakeProc.killed, FakeProc.denied = [], {20}
    monkeypatch.setattr(psutil, 'Process', FakeProc)
    calls = []
    monkeypatch.setattr(c.admin, 'active', lambda: True)
    monkeypatch.setattr(c.admin, 'current', lambda: True)
    monkeypatch.setattr(c.admin, 'call', lambda action, **a: calls.append((action, a)) or True)
    msg = c.apps_close(auto=True)
    assert FakeProc.killed == [11, 12] and calls == [('close_apps', {'keys': ['openrgb_extra']})]
    assert 'ASUS Armoury Crate' in msg and 'Seconda copia di OpenRGB' in msg
    assert set(c.state['apps_closed']) == {'armoury', 'openrgb_extra'}
    assert any('Armoury' in e['message'] for e in c.events)
    n = len(c.events)
    c.apps_close(auto=True)                       # ogni minuto: nel registro una volta sola ogni mezz'ora
    assert len(c.events) == n


def test_apps_close_without_admin_explains_what_to_press(tmp_path, monkeypatch):
    c, core = _controller(tmp_path, monkeypatch)
    monkeypatch.setattr(discovery, 'conflicts_running', lambda: {'armoury': [11]})
    FakeProc.killed, FakeProc.denied = [], {11}
    monkeypatch.setattr(psutil, 'Process', FakeProc)
    monkeypatch.setattr(c.admin, 'active', lambda: False)
    with pytest.raises(RuntimeError, match='Sistema'): c.apps_close(['armoury'])
    assert c.apps_close(auto=True) == 'Chiuse: '         # in automatico non è un errore: riprova al giro dopo
    assert c.apps_close(['icue']) == 'Nessuna app in conflitto aperta'


def test_connections_check_closes_conflicts_only_when_auto_is_on(tmp_path, monkeypatch):
    c, core = _controller(tmp_path, monkeypatch)
    monkeypatch.setattr(discovery, 'find_lhm', lambda: '')
    monkeypatch.setattr(discovery, 'conflicts_running', lambda: {'signalrgb': [5]})
    closed = []
    monkeypatch.setattr(c, 'apps_close', lambda keys=None, auto=False: closed.append(auto))
    c.connections_check({}, age=10, now=100)
    assert closed == [True]
    c.set_apps_auto(False); closed.clear()
    c.connections_check({}, age=10, now=200)
    assert closed == []


def test_conflicts_running_finds_apps_and_a_second_openrgb(monkeypatch):
    class P:
        def __init__(self, name, pid, ppid=1): self.info = {'name': name, 'pid': pid, 'ppid': ppid}
    procs = [P('asus_framework.exe', 1), P('OpenRGB.exe', 2), P('OpenRGB.exe', 3), P('explorer.exe', 4), P('gcc.exe', 5)]
    monkeypatch.setattr(psutil, 'process_iter', lambda attrs=None: procs)
    monkeypatch.setattr(discovery, 'openrgb_service', lambda: {'status': 'running', 'pid': 2})
    fn = ORIGINAL                                        # conftest sostituisce quella vera in tutti i test
    assert fn() == {'armoury': [1], 'openrgb_extra': [3]}
    monkeypatch.setattr(discovery, 'openrgb_service', lambda: {})
    assert fn() == {'armoury': [1]}                      # senza servizio una copia sola è quella giusta


def test_openrgb_not_started_twice_when_the_service_runs(monkeypatch):
    monkeypatch.setattr(discovery, 'openrgb_service', lambda: {'status': 'running', 'pid': 9})
    monkeypatch.setattr(discovery, 'elevated_task', lambda *a: pytest.fail('seconda copia di OpenRGB'))
    assert discovery.openrgb_start(r'C:\OpenRGB\OpenRGB.exe', True) == 'avviato'
    fix = discovery.openrgb_fix_script()
    assert 'Unregister-ScheduledTask' in fix and "'PC ECO Control - RGB'" in fix and 'SessionId -ne 0' in fix
    monkeypatch.setattr(discovery, 'openrgb_service', lambda: {})
    assert discovery.openrgb_fix_script() == ''


def test_fan_tasks_start_fancontrol_minimized(tmp_path, monkeypatch):
    monkeypatch.setattr(discovery, 'user_sid', lambda: '')
    s = discovery.fancontrol_script(r'C:\FC\FanControl.exe', tmp_path)
    assert s.count("-Argument '-c PCECO-") == len(discovery.FAN_TASKS) and s.count(".json -m'") == len(discovery.FAN_TASKS)


def test_runner_closes_only_listed_apps(tmp_path):
    text = ah.runner_text(tmp_path / 'r.json', tmp_path / 'res.json', r'C:\x\NEXAR.exe', {}, {}, apps=discovery.close_apps_table())
    assert "'close_apps'" in text and "'armoury' = 'ArmouryCrate|ArmouryCrate.UserSessionHelper|asus_framework|ArmourySwAgent|ArmourySocketServer'" in text
    assert "throw 'App non prevista'" in text and '@@' not in text
    h = ah.AdminHelper(tmp_path, folder=tmp_path / 'adm', task_exists=lambda t: True)
    assert not h.current()
    (tmp_path / 'adm').mkdir(); (tmp_path / 'adm' / 'runner.ps1').write_text(text, encoding='utf-8-sig')
    assert h.current()


def test_fix_needed_lists_what_one_confirmation_repairs(tmp_path, monkeypatch):
    c, core = _controller(tmp_path, monkeypatch)
    c.config['fans'] = {'enabled': True, 'tasks_version': 1}
    monkeypatch.setattr(discovery, 'openrgb_service', lambda: {'status': 'running', 'pid': 9})
    monkeypatch.setattr(discovery, 'task_exists', lambda t: t == discovery.OPENRGB_TASK)
    monkeypatch.setattr(c.admin, 'active', lambda: True)
    monkeypatch.setattr(c.admin, 'current', lambda: False)
    assert c.apps_fix_needed() == ['fans', 'openrgb', 'admin']
    c.config['fans']['tasks_version'] = discovery.FAN_TASKS_VERSION; c.apps_fix_cache = (0.0, None)
    monkeypatch.setattr(c.admin, 'current', lambda: True)
    monkeypatch.setattr(discovery, 'task_exists', lambda t: False)
    assert c.apps_fix_needed() == []
