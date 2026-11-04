import sys
from pathlib import Path
from unittest.mock import patch
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import core


def test_settings_validation(tmp_path, monkeypatch):
    monkeypatch.setattr(core,'CONFIG_FILE',tmp_path/'cfg.json')
    ctl=core.Control({'alerts':{'enabled':True},'auto_detect':{'enabled':False}})
    with pytest.raises(ValueError):
        ctl.update_settings({'eco_cpu_max_percent':0})
    with pytest.raises(ValueError):
        ctl.update_settings({'alerts_enabled':'false'})
    s=ctl.update_settings({'eco_cpu_max_percent':85,'alerts_enabled':False,'cpu_temp_alert':88})
    assert s['eco_cpu_max_percent']==85
    assert s['alerts_enabled'] is False
    assert s['cpu_temp_alert']==88
    assert (tmp_path/'cfg.json').exists()


def test_alerts_no_fake_sensor_data(monkeypatch):
    ctl=core.Control({})
    monkeypatch.setattr(core,'gpu_read',lambda: {'load':None,'temp':None,'watts':None})
    monkeypatch.setattr(core,'collect_sensors',lambda url:{'cpu_temp':None,'fans':[]})
    data=ctl.telemetry()
    assert data['cpu_temp'] is None
    assert data['gpu_temp'] is None
    assert data['gpu_watts'] is None


def test_unauthenticated_routes_denied():
    from fastapi.testclient import TestClient
    import main
    client=TestClient(main.app)
    assert client.get('/api/status').status_code==401
    assert client.post('/api/mode',json={'mode':'eco'}).status_code==401
    assert client.get('/api/settings').status_code==401
    assert client.get('/api/events').status_code==401
    key=main.key
    assert client.get('/api/settings',headers={'X-PC-ECO-Key':key}).status_code==200
    assert client.post('/api/settings',headers={'X-PC-ECO-Key':key},json={'eco_cpu_max_percent':5}).status_code==400


def test_telegram_menu_has_no_remote_controls():
    from telegram_bot import TelegramBot
    bot=TelegramBot(type('Fake',(),{'config':{}})())
    bot.webapp_url='https://pc.example.org/'
    rows=bot.menu()['inline_keyboard']
    assert len(rows)==1 and 'web_app' in rows[0][0] and not any('callback_data' in b for r in rows for b in r)
