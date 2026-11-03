import io
import json
import time
from unittest.mock import patch
from pathlib import Path
import core
from telegram_bot import TelegramBot

def test_pairing_one_time_expiry_and_code_check(tmp_path, monkeypatch):
    monkeypatch.setattr(core, 'CONFIG_FILE', tmp_path/'config.json')
    ctl=core.Control({'telegram':{'token':'','allowed_user_id':0}})
    good_bot='123456789:AA0123456789012345678901234567890'
    payload=json.dumps({'ok':True,'result':{'is_bot':True,'username':'myprivate_bot'}}).encode('utf8')
    with patch('urllib.request.urlopen',return_value=io.BytesIO(payload)):
        resp=ctl.begin_telegram_pair(good_bot)
    assert resp['bot_username']=='myprivate_bot'
    assert len(resp['code'])==10
    assert not ctl.accept_telegram_pair('BADCODE',47123)
    assert not ctl.accept_telegram_pair(resp['code'],0)
    assert ctl.accept_telegram_pair(resp['code'],47123)
    assert ctl.config['telegram']['allowed_user_id']==47123
    assert not ctl.accept_telegram_pair(resp['code'],999)
    assert json.loads((tmp_path/'config.json').read_text())['telegram']['allowed_user_id']==47123

def test_pairing_expiry(tmp_path, monkeypatch):
    monkeypatch.setattr(core, 'CONFIG_FILE', tmp_path/'config.json')
    ctl=core.Control({'telegram':{'token':'','allowed_user_id':0}})
    ctl.telegram_pair={'code':'ABCDEF1234','until':time.monotonic()-1}
    assert not ctl.accept_telegram_pair('ABCDEF1234',777)
    assert not ctl.telegram_pair_pending()

def test_api_rejects_remote_setup():
    from fastapi.testclient import TestClient
    import main
    with TestClient(main.app, client=('192.168.1.49',12345)) as client:
        r=client.post('/api/telegram/pair',headers={'X-PC-ECO-Key':main.key},json={'token':'1234:ABCDEFGHIJK'})
        assert r.status_code==403

def test_api_rejects_unauthorized_setup():
    from fastapi.testclient import TestClient
    import main
    with TestClient(main.app) as client:
        r=client.post('/api/telegram/pair',json={'token':'anything'})
        assert r.status_code==401
