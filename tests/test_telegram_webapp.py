import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

TOKEN = '123456789:AA0123456789012345678901234567890'

def signed(user_id, token=TOKEN, age=0):
    fields = {'auth_date': str(int(time.time()) - age), 'query_id': 'AAE', 'user': json.dumps({'id': user_id, 'first_name': 'Sam'})}
    check = '\n'.join(f'{k}={v}' for k, v in sorted(fields.items()))
    secret = hmac.new(b'WebAppData', token.encode(), hashlib.sha256).digest()
    fields['hash'] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)

def test_webapp_signature(monkeypatch):
    import main
    monkeypatch.setitem(main.controller.config, 'telegram', {'token': TOKEN, 'allowed_user_id': 4242})
    assert main.telegram_user(signed(4242)) == 4242
    assert main.telegram_user(signed(4242, token='999:other')) == 0          # firmato da un altro bot
    assert main.telegram_user(signed(4242, age=90000)) == 0                 # scaduto
    assert main.telegram_user(signed(4242).replace('4242', '4243')) == 0    # manomesso

def test_webapp_auth_only_for_paired_user(monkeypatch):
    from fastapi.testclient import TestClient
    import main
    monkeypatch.setitem(main.controller.config, 'telegram', {'token': TOKEN, 'allowed_user_id': 4242})
    client = TestClient(main.app)
    assert client.get('/api/settings', headers={'X-TG-Init-Data': signed(4242)}).status_code == 200
    assert client.get('/api/settings', headers={'X-TG-Init-Data': signed(777)}).status_code == 401

def test_tunnel_requests_are_remote():
    from starlette.requests import Request
    import main
    from tunnel import TUNNEL_PORT
    req = Request({'type': 'http', 'server': ('127.0.0.1', TUNNEL_PORT), 'client': ('127.0.0.1', 5555), 'headers': []})
    assert main.is_remote(req)
    local = Request({'type': 'http', 'server': ('127.0.0.1', 8765), 'client': ('127.0.0.1', 5555), 'headers': []})
    assert not main.is_remote(local)
