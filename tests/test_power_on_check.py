"""Accensione da spento per chiunque: prova dal PC verso l'app su Umbrel, bot Telegram che la segue, niente litigi sul bot."""
import importlib.util, io, json, urllib.error
from pathlib import Path

import beacon
import pytest
from test_leds import setup, control

SPEC = importlib.util.spec_from_file_location('nexar_umbrel_p', Path(__file__).parent.parent / 'umbrel' / 'app' / 'nexar.py')
nx = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(nx)


class Stop(BaseException): pass


class Clock:
    def __init__(self): self.t = 1_000_000.0
    def __call__(self): return self.t
    def sleep(self, s): self.t += s


def test_relay_test_waits_for_the_matching_answer():
    clock, posted = Clock(), []
    def get(url):
        assert '/json?poll=1&since=' in url
        if not posted: return ''
        t = beacon.unseal('wake:s', posted[0][1])['wake']
        return '\n'.join(json.dumps({'message': beacon.seal('ack:s', {'ack': a, 'on': True, 'tg': True})}) for a in (t - 50, t)) + '\nnon json'
    got = beacon.relay_test('s', post=lambda tp, m: posted.append((tp, m)), get=get, clock=clock, sleep=clock.sleep)
    assert posted[0][0] == beacon.topic('wake:s') and beacon.unseal('wake:s', posted[0][1])['test'] is True
    assert got['on'] is True and got['tg'] is True
    # nessuno risponde: dopo l'attesa None
    assert beacon.relay_test('s', post=lambda *a: None, get=lambda u: '', clock=clock, sleep=clock.sleep) is None


def test_pc_explains_what_is_missing(tmp_path, monkeypatch):
    setup(monkeypatch, [])
    c, _ = control(tmp_path, monkeypatch, {})
    c.beacon = beacon.Beacon(c.config, save=lambda: None, get_url=lambda: '')
    c.state['inventory'] = {'net': {'ip': '192.168.1.20', 'mac': 'AA:BB:CC:DD:EE:FF'}}
    assert 'non risponde' in c.relay_test(test=lambda s: None)['message']
    assert 'non vede il PC (192.168.1.20)' in c.relay_test(test=lambda s: {'on': False})['message']
    c.config['telegram'] = {'token': '1:x', 'allowed_user_id': 5}
    r = c.relay_test(test=lambda s: {'on': True, 'tg': False})
    assert not r['ok'] and 'bot Telegram' in r['message']
    r = c.relay_test(test=lambda s: {'on': True, 'tg': True})
    assert r['ok'] and '/accendi' in r['message'] and c.state['relay_test'] == r
    assert c.relay_test(test=lambda s: {'on': True})['ok']          # app su Umbrel vecchia: non dice del bot
    assert c.pc_info()['relay']['ok'] is True


def test_bot_is_published_for_umbrel_only_when_linked_and_when_it_changes(tmp_path, monkeypatch):
    setup(monkeypatch, [])
    c, _ = control(tmp_path, monkeypatch, {})
    assert c.relay_info() is None
    c.config['devices'] = [{'tag': 'umbrel'}]
    c.config['telegram'] = {'token': '1:x', 'allowed_user_id': 5}
    sent, clock = [], Clock()
    b = beacon.Beacon(c.config, save=lambda: None, get_url=lambda: '', post=lambda tp, m: sent.append((tp, m)), clock=clock, relay=c.relay_info)
    b.tick(); b.tick()
    s = 'relay:' + b.secret()
    assert len(sent) == 1 and sent[0][0] == beacon.topic(s)
    assert nx.unseal(s, sent[0][1])['bot_token'] == '1:x'           # l'app su Umbrel lo sa leggere
    c.config['telegram']['allowed_user_id'] = 6; b.tick()
    assert len(sent) == 2 and beacon.unseal(s, sent[1][1])['user_id'] == 6


class Resp(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *a): return False


def waker_env(monkeypatch, cfg, on=True):
    calls = {'wake': 0, 'told': [], 'posted': [], 'saved': []}
    monkeypatch.setattr(nx, 'load', lambda: dict(cfg))
    monkeypatch.setattr(nx, 'save', lambda c: calls['saved'].append(c))
    monkeypatch.setattr(nx, 'pc_on', lambda c: on)
    monkeypatch.setattr(nx, 'send_wake', lambda c: calls.__setitem__('wake', calls['wake'] + 1))
    monkeypatch.setattr(nx.Waker, 'tell', lambda self, c, text: calls['told'].append(text))
    return calls


def test_umbrel_answers_the_test_without_waking_the_pc(monkeypatch):
    cfg = {'wake_secret': 'w', 'pc_ip': '192.168.1.20', 'bot_token': '1:x', 'user_id': 5}
    calls = waker_env(monkeypatch, cfg, on=False)
    now = nx.time.time()
    req = json.dumps({'event': 'message', 'topic': nx.topic('wake:w'), 'message': nx.seal('wake:w', {'wake': now, 'test': True})}).encode()
    def urlopen(r, timeout=None):
        if getattr(r, 'data', None): calls['posted'].append(r.data.decode()); return Resp(b'')
        if calls['posted']: raise Stop
        return Resp(req + b'\n')
    monkeypatch.setattr(nx.urllib.request, 'urlopen', urlopen)
    monkeypatch.setattr(nx.time, 'sleep', lambda s: (_ for _ in ()).throw(Stop()))
    with pytest.raises(Stop): nx.Waker().channels()
    assert calls['wake'] == 0                                           # una prova non accende mai il PC
    assert nx.unseal('ack:w', calls['posted'][0]) == {'ack': now, 'on': False, 'tg': True}
    assert 'non vede il PC (192.168.1.20)' in calls['told'][0]


def test_umbrel_takes_the_new_bot_from_the_pc(monkeypatch):
    cfg = {'wake_secret': 'w', 'pc_ip': '192.168.1.20', 'pc_mac': 'AA:BB:CC:DD:EE:FF', 'bot_token': '', 'user_id': 0}
    calls = waker_env(monkeypatch, cfg)
    bot = json.dumps({'message': nx.seal('relay:w', {'bot_token': '1:new', 'user_id': 9, 't': 1})}).encode()
    monkeypatch.setattr(nx.urllib.request, 'urlopen', lambda r, timeout=None: Resp(bot if nx.topic('relay:w') in r.full_url else b''))
    sleeps = []
    def sleep(s):
        sleeps.append(s)
        if s == 300: raise Stop
    monkeypatch.setattr(nx.time, 'sleep', sleep)
    with pytest.raises(Stop): nx.Waker().follow()
    assert calls['saved'] == [{**cfg, 'bot_token': '1:new', 'user_id': 9}] and sleeps == [20, 300]


def test_umbrel_steps_aside_when_the_pc_reads_the_bot(monkeypatch):
    cfg = {'wake_secret': 'w', 'pc_ip': '192.168.1.20', 'bot_token': '1:x', 'user_id': 5}
    waker_env(monkeypatch, cfg, on=False)
    monkeypatch.setattr(nx, 'app_up', lambda c: False)
    def conflict(self, c, method, **p): raise urllib.error.HTTPError('u', 409, 'Conflict', {}, None)
    monkeypatch.setattr(nx.Waker, 'tg', conflict)
    sleeps = []
    def sleep(s):
        sleeps.append(s); raise Stop
    monkeypatch.setattr(nx.time, 'sleep', sleep)
    with pytest.raises(Stop): nx.Waker().telegram()
    assert sleeps == [60]
