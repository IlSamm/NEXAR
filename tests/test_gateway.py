"""Mac via Umbrel + Tailscale: codici di collegamento, porta solo per Umbrel e ponte su Umbrel."""
import http.client
import http.server
import json
import os
import threading
import pytest
import gateway
import pc_power


class Clock:
    def __init__(self): self.t = 1000.0
    def __call__(self): return self.t


def test_code_is_one_use_expires_and_only_hash_is_saved():
    cfg, saved, clock = {}, [], Clock()
    d = gateway.Devices(cfg, save=lambda: saved.append(1), clock=clock)
    with pytest.raises(PermissionError, match='scaduto'): d.pair('ABCD-EFGH', 'Mac')
    code, ttl = d.new_code()
    assert ttl == 600 and len(code) == 9 and code[4] == '-'
    with pytest.raises(PermissionError, match='sbagliato'): d.pair('ZZZZ-ZZZZ', 'Mac')
    token, name = d.pair(code.lower().replace('-', ' '), 'Mac')        # minuscole e spazi vanno bene
    assert name == 'Mac' and saved and d.check(token) and not d.check(token[:-1] + 'x') and not d.check('')
    assert token not in json.dumps(cfg) and cfg['devices'][0]['name'] == 'Mac'
    with pytest.raises(PermissionError): d.pair(code, 'Altro')        # già usato
    code2, _ = d.new_code(); clock.t += 601
    with pytest.raises(PermissionError, match='scaduto'): d.pair(code2, 'Tardi')
    d.remove(cfg['devices'][0]['id'])
    assert not d.check(token) and d.list() == []


def test_only_private_lan_ip_for_umbrel():
    assert gateway.valid_lan_ip('192.168.0.50') and gateway.valid_lan_ip('10.0.0.9')
    for bad in ('8.8.8.8', '127.0.0.1', '169.254.1.1', 'umbrel', '', '192.168.0.300'):
        assert not gateway.valid_lan_ip(bad)
    script = gateway.firewall_script(r"C:\Program Files\NEXAR's\NEXAR.exe", '192.168.0.50')
    assert "-RemoteAddress '192.168.0.50'" in script and "NEXAR''s" in script and '-LocalPort 8767' in script


def test_setup_needs_firewall_confirmation(tmp_path, monkeypatch):
    import core
    monkeypatch.setattr(core, 'STATE_FILE', tmp_path / 'state.json')
    monkeypatch.setattr(core, 'CONFIG_FILE', tmp_path / 'config.json')
    c = core.Control({})
    with pytest.raises(ValueError): c.gateway_setup(True, '8.8.8.8')
    with pytest.raises(RuntimeError, match='annullata'): c.gateway_setup(True, '192.168.0.50', firewall=lambda: False)
    assert not c.gateway_info()['enabled']
    asked = []
    c.gateway_setup(True, '192.168.0.50', firewall=lambda: asked.append(1) or True)
    c.gateway_setup(False); c.gateway_setup(True, firewall=lambda: asked.append(1) or True)
    assert len(asked) == 1                                   # la regola c'è già: niente seconda richiesta UAC
    c.gateway_setup(True, '192.168.0.51', firewall=lambda: asked.append(1) or True)
    assert len(asked) == 2 and c.gateway_info()['umbrel_ip'] == '192.168.0.51'


def test_api_bridge_port_only_umbrel_and_device_login(monkeypatch):
    from fastapi.testclient import TestClient
    import main
    monkeypatch.setitem(main.controller.config, 'gateway', {'enabled': True, 'umbrel_ip': '192.168.0.50', 'firewall': True})
    monkeypatch.setitem(main.controller.config, 'devices', [])
    monkeypatch.setattr(main.controller, 'notify', lambda m: None)
    monkeypatch.setattr(main.controller.devices, 'save', lambda: None)
    base = f'http://testserver:{gateway.GATEWAY_PORT}'
    stranger = TestClient(main.app, base_url=base, client=('192.168.0.77', 1000))
    assert stranger.get('/').status_code == 403                        # altri in casa: niente
    umbrel = TestClient(main.app, base_url=base, client=('192.168.0.50', 1000))
    assert umbrel.get('/').status_code == 200
    assert umbrel.get('/manifest.webmanifest').json()['display'] == 'standalone'
    assert umbrel.get('/api/events').status_code == 401                 # serve comunque la chiave
    h = {'X-PC-ECO-Key': main.key}
    assert umbrel.post('/api/devices/code', headers=h).status_code == 403   # i codici solo dal PC
    assert umbrel.post('/api/gateway/setup', headers=h, json={'enabled': False}).status_code == 403
    pc = TestClient(main.app, client=('127.0.0.1', 1000))
    code = pc.post('/api/devices/code', headers=h).json()['code']
    assert umbrel.post('/api/devices/pair', json={'code': 'AAAA-AAAA'}).status_code == 403
    r = umbrel.post('/api/devices/pair', json={'code': code, 'name': 'Mac'}).json()
    dev = {'X-PC-ECO-Key': r['token']}
    assert umbrel.get('/api/events', headers=dev).status_code == 200
    g = umbrel.get('/api/gateway', headers=dev).json()
    assert g['local'] is False and 'umbrel_ip' not in g and g['devices'][0]['name'] == 'Mac'
    assert umbrel.post('/api/autostart', headers=dev, json={'enabled': False}).status_code == 403   # cose da PC: no
    umbrel.post('/api/devices/remove', headers=dev, json={'id': g['devices'][0]['id']})
    assert umbrel.get('/api/events', headers=dev).status_code == 401
    monkeypatch.setitem(main.controller.config, 'gateway', {'enabled': False, 'umbrel_ip': '192.168.0.50'})
    assert umbrel.get('/').status_code == 403                           # ponte spento: porta chiusa anche a Umbrel


def test_compose_with_bridge_only():
    text = pc_power.relay_compose(None, None, '', '192.168.0.128', '192.168.0.255', bridge={'pc_port': 8767, 'port': 8790})
    doc = json.loads(text.split('\n', 1)[1])
    assert list(doc['services']) == ['nexar-ponte'] and 'token' not in text.split('\n')[0]
    env = doc['services']['nexar-ponte']['environment']
    assert env['PC_IP'] == '192.168.0.128' and env['PC_PORT'] == '8767' and env['GW_PORT'] == '8790'
    compile(doc['services']['nexar-ponte']['command'][3].replace('$$', '$'), 'bridge', 'exec')
    both = json.loads(pc_power.relay_compose('1:A', 4, '34:5A:60:77:D4:8D', '192.168.0.128', '192.168.0.255', bridge={}).split('\n', 1)[1])
    assert set(both['services']) == {'nexar-accensione', 'nexar-ponte'}
    with pytest.raises(ValueError): pc_power.relay_compose(None, None, '', '', '', bridge={})


def _serve(server):
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server.server_address[1]


def test_bridge_script_forwards_and_shows_off_page(monkeypatch):
    class Back(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def do_POST(self):
            body = self.rfile.read(int(self.headers['Content-Length']))
            out = json.dumps({'got': json.loads(body), 'key': self.headers.get('X-PC-ECO-Key'), 'host': self.headers['Host']}).encode()
            self.send_response(201); self.send_header('Content-Type', 'application/json'); self.send_header('X-Remote-Meta', '{"seq":3}')
            self.send_header('Content-Length', str(len(out))); self.end_headers(); self.wfile.write(out)
    back = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Back)
    port = _serve(back)
    monkeypatch.setenv('PC_IP', '127.0.0.1'); monkeypatch.setenv('PC_PORT', str(port)); monkeypatch.setenv('PC_MAC', '')
    ns = {'__name__': 'bridge_test'}
    exec(compile(pc_power.BRIDGE, 'bridge', 'exec'), ns)
    gw = ns['S'](('127.0.0.1', 0), ns['H'])
    gport = _serve(gw)

    def call(method, path, body=None, headers=None):
        c = http.client.HTTPConnection('127.0.0.1', gport, timeout=10)
        c.request(method, path, body=body, headers=headers or {})
        r = c.getresponse(); data = r.read(); c.close()
        return r, data
    r, data = call('POST', '/api/x', b'{"a":1}', {'X-PC-ECO-Key': 'k', 'Content-Type': 'application/json'})
    assert r.status == 201 and r.getheader('X-Remote-Meta') == '{"seq":3}'
    assert json.loads(data) == {'got': {'a': 1}, 'key': 'k', 'host': f'127.0.0.1:{port}'}
    r, data = call('GET', '/__nexar/status')
    assert json.loads(data) == {'app': True, 'pc': True, 'wake': False}
    back.shutdown(); back.server_close()
    r, data = call('GET', '/api/status')
    assert r.status == 503 and json.loads(data)['off'] is True
    r, data = call('GET', '/')
    assert r.status == 503 and 'Accendi il PC' in data.decode()
    assert call('POST', '/__nexar/wake')[0].status == 400                # senza MAC non si accende
    gw.shutdown(); gw.server_close()


def test_bridge_server_follows_setting():
    import socket, time, main
    cfg = {'enabled': True, 'umbrel_ip': '192.168.0.50'}
    with socket.socket() as s: s.bind(('127.0.0.1', 0)); port = s.getsockname()[1]
    b = gateway.Bridge(lambda: cfg, main.app, port=port, host='127.0.0.1')
    stop = threading.Event()
    threading.Thread(target=b.run, args=(stop,), daemon=True).start()
    for _ in range(60):
        if b.info()['running']: break
        time.sleep(0.1)
    assert b.info() == {'running': True, 'error': ''}
    cfg['enabled'] = False
    for _ in range(100):
        if not b.server: break
        time.sleep(0.1)
    assert not b.info()['running']
    stop.set()
