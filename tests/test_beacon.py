"""App per Mac: il PC pubblica l'indirizzo cifrato su ntfy e l'app lo ritrova (primo collegamento con il codice)."""
import json
import beacon

# Stesso vettore controllato dall'app per Mac in compilazione (mac/NEXAR.swift → selfTest).
VECTOR_SECRET = 'pair:ABCDEFGH'
VECTOR_TOPIC = 'nexar-687e95d18aab6f3771d80bc6d695cc25'
VECTOR_PAYLOAD = {'url': 'https://example.trycloudflare.com', 't': 1700000000, 'bot': 'nexar_bot', 'v': '1.0.40'}
VECTOR_NONCE = bytes(range(16))


class Clock:
    def __init__(self): self.t = 1000.0
    def __call__(self): return self.t


def test_seal_roundtrip_and_tamper():
    s = 'segreto'
    text = beacon.seal(s, {'url': 'https://a.trycloudflare.com', 't': 5})
    assert beacon.unseal(s, text) == {'url': 'https://a.trycloudflare.com', 't': 5}
    assert beacon.unseal('altro', text) is None
    flip = text[:30] + ('A' if text[30] != 'A' else 'B') + text[31:]
    assert beacon.unseal(s, flip) is None and beacon.unseal(s, 'xx') is None
    assert 'trycloudflare' not in text
    assert beacon.topic(s) == beacon.topic(s) and beacon.topic(s) != beacon.topic('altro')
    assert beacon.pair_secret('abcd efgh') == beacon.pair_secret('ABCD-EFGH') == 'pair:ABCDEFGH'


def test_swift_vector_is_stable():
    assert beacon.topic(VECTOR_SECRET) == VECTOR_TOPIC
    sealed = beacon.seal(VECTOR_SECRET, VECTOR_PAYLOAD, nonce=VECTOR_NONCE)
    assert beacon.unseal(VECTOR_SECRET, sealed) == VECTOR_PAYLOAD
    swift = open(__file__.replace('tests\\test_beacon.py', 'mac\\NEXAR.swift').replace('tests/test_beacon.py', 'mac/NEXAR.swift'), encoding='utf-8').read()
    assert f'"{VECTOR_TOPIC}"' in swift and f'"{sealed}"' in swift


def test_beacon_publishes_code_then_device_channel():
    cfg, sent, clock = {}, [], Clock()
    url = ['']
    b = beacon.Beacon(cfg, save=lambda: None, get_url=lambda: url[0], info=lambda: {'bot': 'nb'},
                      post=lambda t, m: sent.append((t, m)), clock=clock)
    assert not b.wanted()
    b.announce_code('ABCD-EFGH', 600)
    assert b.wanted()
    b.tick(); assert sent == []                       # tunnel non ancora pronto
    url[0] = 'https://x.trycloudflare.com'
    b.tick(); b.tick()
    assert len(sent) == 1
    s = beacon.pair_secret('ABCDEFGH')
    assert sent[0][0] == beacon.topic(s) and beacon.unseal(s, sent[0][1])['url'] == url[0]
    cfg['devices'] = [{'id': '1'}]                    # il Mac si è collegato
    b.tick()
    sec = cfg['beacon']['secret']
    assert sent[-1][0] == beacon.topic(sec) and beacon.unseal(sec, sent[-1][1]) == {'url': url[0], 't': 1000, 'bot': 'nb'}
    n = len(sent); b.tick(); assert len(sent) == n    # niente doppioni
    clock.t += 601; url[0] = 'https://y.trycloudflare.com'
    b.tick(); assert len(sent) == n + 1               # nuovo indirizzo: solo canale del dispositivo (codice scaduto)
    clock.t += beacon.REPUBLISH + 1; b.tick(); assert len(sent) == n + 2
    cfg['devices'] = []; assert not b.wanted()


def test_pair_returns_beacon_secret_and_code_reports_online(monkeypatch):
    from fastapi.testclient import TestClient
    import main
    b = beacon.Beacon(main.controller.config, save=lambda: None, get_url=lambda: '', post=lambda t, m: None)
    monkeypatch.setattr(main, 'beacon', b)
    monkeypatch.setitem(main.controller.config, 'devices', [])
    monkeypatch.setitem(main.controller.config, 'beacon', {'secret': 'fisso'})
    monkeypatch.setattr(main.controller, 'notify', lambda m: None)
    monkeypatch.setattr(main.controller.devices, 'save', lambda: None)
    pc = TestClient(main.app, client=('127.0.0.1', 1000))
    r = pc.post('/api/devices/code', headers={'X-PC-ECO-Key': main.key}).json()
    assert r['online'] is False and b.wanted()
    out = pc.post('/api/devices/pair', json={'code': r['code'], 'name': 'MacBook'}).json()
    assert out['beacon'] == 'fisso' and len(out['token']) > 40
