"""Azioni programmate, medie orarie per i grafici lunghi e brano in riproduzione."""
from datetime import datetime
import pytest
import control_plus
import planner


def rule(**kw):
    r = {'id': 'abcd1234', 'time': '23:00', 'days': [0, 1, 2, 3, 4, 5, 6], 'action': 'eco', 'enabled': True}
    r.update(kw); return r


def test_clean_rules_validates():
    assert planner.clean_rule({'time': '07:30', 'days': [4, 0, 0], 'action': 'lock'})['days'] == [0, 4]
    for bad in ({'time': '24:00', 'days': [0], 'action': 'eco'}, {'time': '7:30', 'days': [0], 'action': 'eco'},
                {'time': '07:30', 'days': [], 'action': 'eco'}, {'time': '07:30', 'days': [7], 'action': 'eco'},
                {'time': '07:30', 'days': [0], 'action': 'format_c'}):
        with pytest.raises(ValueError): planner.clean_rule(bad)
    with pytest.raises(ValueError): planner.clean_rules([rule()] * (planner.MAX_RULES + 1))
    two = planner.clean_rules([rule(), rule()])
    assert two[0]['id'] != two[1]['id']


def test_due_window_weekdays_and_once_a_day():
    sat = datetime(2026, 11, 7, 23, 0, 30)                    # sabato
    assert planner.due(rule(), sat, None)[1] == pytest.approx(-30)
    assert planner.due(rule(), sat, '2026-11-07') is None      # già fatta oggi
    assert planner.due(rule(days=[0]), sat, None) is None      # solo lunedì
    assert planner.due(rule(enabled=False), sat, None) is None
    assert planner.due(rule(), datetime(2026, 11, 7, 23, 11), None) is None   # troppo tardi: niente sorprese
    assert planner.due(rule(), datetime(2026, 11, 7, 22, 58), None) is None   # le modalità partono all'orario
    # spegnimento: 5 minuti di preavviso, anche a cavallo della mezzanotte
    at, left = planner.due(rule(action='shutdown'), datetime(2026, 11, 7, 22, 55), None)
    assert left == 300 and at.hour == 23
    at, left = planner.due(rule(action='shutdown', time='00:02'), datetime(2026, 11, 7, 23, 58), None)
    assert at.day == 8 and left == 240


def test_planner_runs_once_and_describes():
    done, runs, saved = [], {}, []
    now = [datetime(2026, 11, 9, 7, 0, 10)]
    p = planner.Planner(lambda: [rule(time='07:00', days=[0, 1, 2, 3, 4], action='lock')], runs, lambda: saved.append(1),
                        lambda r, left: done.append((r['action'], left)), clock=lambda: now[0])
    p.tick(); p.tick()
    assert [d[0] for d in done] == ['lock'] and runs == {'abcd1234': '2026-11-09'} and saved
    v = p.view()[0]
    assert v['text'] == 'Blocca il PC alle 07:00 · lun–ven' and v['next'] == '2026-11-10T07:00'


def test_schedules_api_and_scheduled_shutdown(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    import core, main
    monkeypatch.setattr(core, 'CONFIG_FILE', tmp_path / 'c.json'); monkeypatch.setattr(core, 'STATE_FILE', tmp_path / 's.json')
    c = TestClient(main.app, client=('127.0.0.1', 1000)); h = {'X-PC-ECO-Key': main.key}
    assert c.post('/api/schedules', json={'rules': []}).status_code == 401
    assert c.post('/api/schedules', headers=h, json={'rules': [{'time': '25:00', 'days': [0], 'action': 'eco'}]}).status_code == 400
    r = c.post('/api/schedules', headers=h, json={'rules': [{'time': '23:00', 'days': [0, 1], 'action': 'shutdown'}]}).json()
    assert r['rules'][0]['label'] == 'Spegni il PC' and r['rules'][0]['next']
    assert c.get('/api/schedules', headers=h).json()['actions']['leds_off'] == 'Spegni i LED'
    # lo spegnimento programmato diventa un timer annullabile (nessun comando reale)
    ctl = main.controller; sent = []
    monkeypatch.setattr(ctl, 'notify', sent.append)
    ctl.run_scheduled(r['rules'][0], 300)
    assert ctl.power_plan['action'] == 'shutdown' and '/annulla' in sent[-1]
    assert ctl.cancel_power().startswith('Annullato') and ctl.power_plan is None
    c.post('/api/schedules', headers=h, json={'rules': []})


def test_hourly_trend_and_ranges():
    clock = [1_700_000_000.0 // 3600 * 3600]
    temp = [50]
    store, saves = [], []
    h = control_plus.History(lambda: {'cpu': 20, 'gpu': 10, 'ram': 40, 'cpu_temp': temp[0], 'gpu_temp': 40, 'power': {'total': 100}},
                             clock=lambda: clock[0], counters=lambda: None, trend=store, save=lambda: saves.append(1))
    for i in range(3):
        temp[0] = 50 + i * 10; h.sample(); clock[0] += 1200        # tre campioni nella stessa ora
    h.sample()                                                     # ora nuova: la precedente si chiude e si salva
    assert len(store) == 1 and saves == [1]
    assert store[0]['ct'] == 60 and store[0]['ctx'] == 70 and store[0]['w'] == 100 and store[0]['n'] == 3
    pts = h.range('24h')
    assert len(pts) == 2 and pts[-1]['n'] == 1                    # con l'ora in corso
    for _ in range(control_plus.TREND_KEEP + 30):
        clock[0] += 3600; h.sample()
    assert len(store) == control_plus.TREND_KEEP
    month = h.range('30d')
    assert 115 <= len(month) <= 125 and all(p['t'] % (6 * 3600) == 0 for p in month)
    assert len(h.range('7d')) <= 7 * 24 + 1


def test_now_playing_from_window_titles():
    np = control_plus.now_playing
    assert np([{'exe': 'Spotify.exe', 'title': 'Spotify Premium'}]) is None
    assert np([{'exe': 'Spotify.exe', 'title': 'Daft Punk - One More Time'}]) == {'app': 'Spotify', 'title': 'One More Time', 'artist': 'Daft Punk'}
    assert np([{'exe': 'chrome.exe', 'title': '(3) Lo-fi radio - YouTube - Google Chrome'}])['title'] == 'Lo-fi radio'
    assert np([{'exe': 'notepad.exe', 'title': 'a - b'}]) is None
