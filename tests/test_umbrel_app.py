"""App NEXAR su Umbrel: codice di collegamento, accensione, dashboard del PC in streaming."""
import base64, http.client, http.server, importlib.util, json, socket, socketserver, threading, time
from pathlib import Path

import beacon
import pytest

SPEC = importlib.util.spec_from_file_location('nexar_umbrel', Path(__file__).parent.parent / 'umbrel' / 'app' / 'nexar.py')
nx = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(nx)


def code(**over):
    d = {'name': 'PC', 'pc_ip': '192.168.0.10', 'pc_mac': 'AA:BB:CC:DD:EE:FF', 'broadcast': '192.168.0.255', 'pc_port': 8767,
         'wake_secret': 'segreto', 'token': 'tok', 'bot_token': '', 'user_id': 0, **over}
    return 'NEXAR1.' + base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip('=')


def test_code_valid_and_bad():
    c = nx.parse_code('  ' + code() + '\n')
    assert c['pc_ip'] == '192.168.0.10' and c['token'] == 'tok'
    for bad in ('', 'ciao', 'NEXAR1.@@@', code(pc_ip='8.8.8.8'), code(pc_mac='x'), code(token='')):
        with pytest.raises(ValueError): nx.parse_code(bad)


def test_same_crypto_as_pc():
    s = 'chiave'
    assert nx.topic('wake:' + s) == beacon.topic('wake:' + s)
    assert nx.unseal(s, beacon.seal(s, {'wake': 5})) == {'wake': 5}
    assert beacon.unseal(s, nx.seal(s, {'ack': 7})) == {'ack': 7}
    assert nx.unseal('altra', beacon.seal(s, {'wake': 5})) is None


def test_wake_request_rules():
    now = 1000.0
    assert nx.fresh({'wake': 990}, 0, now) and not nx.fresh({'wake': 990}, 990, now) and not nx.fresh({'wake': 500}, 0, now)
    assert nx.link_ok({'time': 995}, 0, now) and not nx.link_ok({'time': 995}, 990, now) and not nx.link_ok({'time': 100}, 0, now)
    assert nx.magic('AA:BB:CC:DD:EE:FF') == b'\xff' * 6 + bytes.fromhex('AABBCCDDEEFF') * 16


class Fake(http.server.BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    seen = {}
    def log_message(self, *a): pass
    def do_GET(self):
        Fake.seen = dict(self.headers)
        if self.path == '/':
            body = b'<html><head><title>x</title></head></html>'
            self.send_response(200); self.send_header('Content-Type', 'text/html'); self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)
        elif self.path == '/api/remote/stream':
            self.send_response(200); self.send_header('Content-Type', 'application/octet-stream'); self.send_header('Transfer-Encoding', 'chunked'); self.end_headers()
            self.wfile.write(b'5\r\nprimo\r\n'); self.wfile.flush()
            time.sleep(1.2)
            self.wfile.write(b'7\r\nsecondo\r\n0\r\n\r\n')
        else:
            body = b'{"ok":true}'
            self.send_response(200); self.send_header('Content-Type', 'application/json'); self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)
    def do_POST(self):
        size = int(self.headers.get('Content-Length') or 0)
        body = self.rfile.read(size)
        self.send_response(200); self.send_header('Content-Type', 'application/octet-stream'); self.send_header('Content-Length', str(size)); self.end_headers(); self.wfile.write(body)


class S(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True; allow_reuse_address = True


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr(nx, 'DATA', str(tmp_path)); monkeypatch.setattr(nx, 'CFG', str(tmp_path / 'config.json'))
    pc = S(('127.0.0.1', 0), Fake); web = S(('127.0.0.1', 0), nx.Web)
    for s in (pc, web): threading.Thread(target=s.serve_forever, daemon=True).start()
    yield pc.server_address[1], web.server_address[1]
    for s in (pc, web): s.shutdown()


def call(port, method, path, body=None, headers=None):
    c = http.client.HTTPConnection('127.0.0.1', port, timeout=8)
    c.request(method, path, body=body, headers=headers or {})
    r = c.getresponse(); data = r.read(); c.close()
    return r.status, data, r


def pair(web, pc_port):
    st, _, _ = call(web, 'POST', '/__nexar/pair', json.dumps({'code': code(token='tok-umbrel', pc_port=pc_port)}), {'Content-Type': 'application/json'})
    assert st == 200
    cfg = nx.load(); cfg['pc_ip'] = '127.0.0.1'; nx.save(cfg)


def test_unpaired_shows_setup_and_blocks_api(app):
    _, web = app
    st, data, _ = call(web, 'GET', '/')
    assert st == 200 and b'Collega il tuo PC' in data
    st, data, _ = call(web, 'GET', '/api/status')
    assert st == 503 and json.loads(data)['off'] is True
    assert json.loads(call(web, 'GET', '/__nexar/status')[1])['paired'] is False


def test_bad_code_rejected(app):
    _, web = app
    st, data, _ = call(web, 'POST', '/__nexar/pair', b'{"code":"nope"}', {'Content-Type': 'application/json'})
    assert st == 400 and 'Codice' in json.loads(data)['detail'] and nx.load() is None


def test_proxy_uses_own_token_and_marks_page(app):
    pc, web = app
    pair(web, pc)
    st, data, _ = call(web, 'GET', '/', headers={'X-PC-ECO-Key': 'di-chi-apre'})
    assert st == 200 and b'/__nexar/proxy.js' in data
    assert Fake.seen['X-PC-ECO-Key'] == 'tok-umbrel'
    assert call(web, 'GET', '/__nexar/proxy.js')[1].startswith(b'window.NEXAR_PROXY')


def test_stream_arrives_piece_by_piece(app):
    pc, web = app
    pair(web, pc)
    c = http.client.HTTPConnection('127.0.0.1', web, timeout=8)
    c.request('GET', '/api/remote/stream'); r = c.getresponse()
    t0 = time.time(); first = r.read1(100); t1 = time.time()
    assert first == b'primo' and t1 - t0 < 0.8        # non aspetta la fine del flusso
    assert r.read() == b'secondo'
    c.close()


def test_post_body_forwarded_and_connection_reused(app):
    pc, web = app
    pair(web, pc)
    c = http.client.HTTPConnection('127.0.0.1', web, timeout=8)
    for payload in (b'x' * 300000, b'corto'):
        c.request('POST', '/api/files', body=payload); r = c.getresponse()
        assert r.status == 200 and r.read() == payload
    c.close()


def test_pc_off_page_and_api(app):
    pc, web = app
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0)); free = s.getsockname()[1]
    pair(web, free)
    st, data, _ = call(web, 'GET', '/api/status')
    assert st == 503 and json.loads(data)['off'] is True
    assert call(web, 'GET', '/')[0] == 503


def test_unpair(app):
    pc, web = app
    pair(web, pc)
    assert call(web, 'POST', '/__nexar/unpair')[0] == 200 and nx.load() is None


def test_wake_goes_to_broadcast_and_to_the_pc(monkeypatch):
    sent = []
    class Sock:
        def __init__(self, *a): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def setsockopt(self, *a): pass
        def sendto(self, pkt, dst): sent.append(dst)
    monkeypatch.setattr(nx.socket, 'socket', Sock)
    monkeypatch.setattr(nx.time, 'sleep', lambda s: None)
    nx.send_wake({'pc_mac': 'AA:BB:CC:DD:EE:FF', 'pc_ip': '192.168.0.10', 'broadcast': '192.168.0.255'})
    assert {d[0] for d in sent} == {'192.168.0.255', '255.255.255.255', '192.168.0.10'} and len(sent) == 30


def test_pc_counts_as_on_only_if_it_answers_itself(monkeypatch):
    """Un ripetitore Wi-Fi risponde all'ARP al posto del PC spento: non deve sembrare acceso."""
    monkeypatch.setattr(nx, 'app_up', lambda cfg: False)
    monkeypatch.setattr(nx, 'quiet', lambda *a: a[0] == 'arping')
    assert not nx.pc_on({'pc_ip': '192.168.0.10'})
