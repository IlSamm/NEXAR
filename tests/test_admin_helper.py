"""Amministratore da remoto: solo azioni dell'elenco, mai testo arrivato dall'esterno."""
import json, os, shutil, subprocess

import admin_helper as ah
import pytest
import remote_control as rc


def helper(base, reply):
    base.mkdir(exist_ok=True)
    folder = base / 'admin'; folder.mkdir(); (folder / 'runner.ps1').write_text('x')
    h = ah.AdminHelper(base, folder, task_exists=lambda name: True, sleep=lambda s: None)
    def run():
        req = json.loads(h.request.read_text(encoding='utf-8'))
        h.result.write_text(json.dumps({'id': req['id'], **reply}), encoding='utf-8')
        return True
    h.run_task = run
    return h


def test_call_ok_and_error(tmp_path):
    assert helper(tmp_path / 'a', {'ok': True, 'message': 'ok'}).call('trim') is True
    with pytest.raises(RuntimeError, match='non prevista'):
        helper(tmp_path / 'b', {'ok': False, 'message': 'Azione non prevista'}).call('nope')


def test_inactive_explains_what_to_do(tmp_path):
    h = ah.AdminHelper(tmp_path, tmp_path / 'manca', task_exists=lambda name: False)
    with pytest.raises(RuntimeError, match='Amministratore da remoto'): h.call('trim')


def test_stale_result_is_ignored(tmp_path):
    h = helper(tmp_path / 'a', {'ok': True, 'message': 'ok'})
    h.result.write_text(json.dumps({'id': 'vecchio', 'ok': True}), encoding='utf-8')
    ticks = iter(range(0, 1000))
    h.clock = lambda: next(ticks); h.run_task = lambda: True
    with pytest.raises(RuntimeError, match='in tempo'): h.call('trim', timeout=5)


def runner(tmp_path):
    return ah.runner_text(tmp_path / 'r.json', tmp_path / 'res.json', r'C:\x\NEXAR.exe', {'wintemp': str(tmp_path / 'none')}, {'fans': 'Rem0o.FanControl'},
                          trim='Write-Output trim', autostart='Write-Output a', approved=r'Software\X', rule='NEXAR - ponte', port=8767, autostart_task='T')


def test_runner_never_evaluates_request_text(tmp_path):
    text = runner(tmp_path).lower()
    for bad in ('invoke-expression', 'iex ', 'start-process', 'scriptblock', 'encodedcommand'):
        assert bad not in text
    assert "default { throw 'azione non prevista' }" in text and '@@' not in text


def test_setup_protects_folder(tmp_path):
    s = ah.setup_script(tmp_path / 'a', 'x', 'PC\\me')
    assert '/inheritance:r' in s and '*S-1-5-32-545:(OI)(CI)RX' in s and '-RunLevel Highest' in s and "@'\nx\n'@" in s


@pytest.mark.skipif(os.name != 'nt' or not shutil.which('powershell'), reason='serve Windows')
def test_runner_refuses_unknown_requests(tmp_path):
    (tmp_path / 'runner.ps1').write_text(runner(tmp_path), encoding='utf-8-sig')
    def go(req):
        (tmp_path / 'r.json').write_text(json.dumps(req), encoding='utf-8')
        subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(tmp_path / 'runner.ps1')], check=True, capture_output=True, timeout=60)
        return json.loads((tmp_path / 'res.json').read_text(encoding='utf-8-sig'))
    assert go({'id': 'a', 'action': 'ping', 'args': {}}) == {'id': 'a', 'ok': True, 'message': 'ok'}
    out = go({'id': 'b', 'action': 'format-c', 'args': {}})
    assert out['ok'] is False and 'non prevista' in out['message']
    for req in ({'action': 'clean', 'args': {'keys': ['system32']}}, {'action': 'install', 'args': {'key': 'virus'}},
                {'action': 'startup', 'args': {'sub': '..\\..\\Run', 'name': 'x', 'enabled': True}}, {'action': 'firewall', 'args': {'ip': '8.8.8.8'}}):
        out = go({'id': 'c', **req})
        assert out['ok'] is False, req
    assert not (tmp_path / 'r.json').exists()


def test_pin_rules():
    cfg = {'pin_hash': rc.pin_hash('482913'), 'enabled': True}
    r = rc.Remote(lambda: cfg, lambda m: None, lambda m: None, grabber=lambda *a: None, mons=lambda: [], cursor=lambda: None)
    with pytest.raises(rc.NeedPin): r.check_pin(None)
    assert r.fails == 0
    with pytest.raises(rc.NeedPin, match='sbagliato'): r.check_pin('000001')
    r.check_pin('482913')
    assert r.fails == 0
    cfg.pop('pin_hash')
    with pytest.raises(PermissionError) as ex: r.check_pin('482913')
    assert not isinstance(ex.value, rc.NeedPin)
