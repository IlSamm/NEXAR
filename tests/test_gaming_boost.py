import json
import time

import core
import gaming_boost as gb

class FakeProc:
    def __init__(self, pid, name, exe, prio=32):
        self.pid, self.info, self.prio = pid, {'name': name, 'exe': exe}, prio
    def nice(self, value=None):
        if value is None: return self.prio
        self.prio = value

def fake_registry(monkeypatch, reg):
    def fake_reg(hive, path, name, value=None, delete=False):
        if value is None and not delete: return reg.get((hive, path, name))
        if delete: reg.pop((hive, path, name), None)
        else: reg[(hive, path, name)] = value
    monkeypatch.setattr(gb, '_reg', fake_reg)
    monkeypatch.setattr(gb.os, 'name', 'nt')

def test_game_detection():
    assert gb.is_game(r'C:\Program Files (x86)\Steam\steamapps\common\Counter-Strike Global Offensive\cs2.exe')
    assert gb.is_game(r'C:\Riot Games\VALORANT\live\VALORANT.exe')
    assert not gb.is_game(r'C:\Program Files\Google\Chrome\Application\chrome.exe')
    # launcher e anti-cheat nelle cartelle dei giochi non sono il gioco
    assert not gb.is_game(r'C:\Riot Games\Riot Client\RiotClientServices.exe')
    assert not gb.is_game(r'C:\Fortnite\FortniteGame\Binaries\Win64\FortniteLauncher.exe')

def test_settings_validation():
    b = gb.Booster({})
    s = b.update_settings({'game_mode': False, 'auto': False, 'hidden': ['steam-431960', '../x', 'epic-Fortnite'],
                           'apps': {'Discord.exe': 'close', 'chrome.exe': 'lower', 'explorer.exe': 'close', 'x.exe': 'boh'}})
    assert s['game_mode'] is False and s['auto'] is False and s['apps'] == {'discord.exe': 'close', 'chrome.exe': 'lower'}
    assert s['hidden'] == ['epic-Fortnite', 'steam-431960']

def test_steam_library(tmp_path):
    root = tmp_path / 'Steam'; apps = root / 'steamapps'; (apps / 'common' / 'Hollow Knight').mkdir(parents=True)
    other = tmp_path / 'Lib2' / 'steamapps'; (other / 'common' / 'wallpaper_engine').mkdir(parents=True)
    (apps / 'libraryfolders.vdf').write_text('"libraryfolders"\n{\n "1"\n {\n  "path"  "%s"\n }\n}' % str(tmp_path / 'Lib2').replace('\\', '\\\\'))
    manifest = '"AppState"\n{\n "appid" "%s"\n "name" "%s"\n "StateFlags" "%s"\n "installdir" "%s"\n "LastPlayed" "1745592874"\n "SizeOnDisk" "5197398400"\n}'
    (apps / 'appmanifest_367520.acf').write_text(manifest % ('367520', 'Hollow Knight', '4', 'Hollow Knight'))
    (apps / 'appmanifest_228980.acf').write_text(manifest % ('228980', 'Steamworks Common Redistributables', '4', 'Steamworks Shared'))
    (apps / 'appmanifest_1.acf').write_text(manifest % ('1', 'Half Downloaded', '1026', 'Hollow Knight'))
    (other / 'appmanifest_431960.acf').write_text(manifest % ('431960', 'Wallpaper Engine', '4', 'wallpaper_engine'))
    games = gb.steam_games(root)
    assert [(g['id'], g['name'], g['launch'], g['size']) for g in games] == [('steam-367520', 'Hollow Knight', 'steam://rungameid/367520', 5197398400)]

def test_epic_library(tmp_path):
    game = tmp_path / 'Fortnite'; game.mkdir()
    def item(name, **kw):
        (tmp_path / (name + '.item')).write_text(json.dumps({'AppName': name, 'DisplayName': name, 'bIsApplication': True,
                                                             'AppCategories': ['games'], 'InstallLocation': str(game), **kw}), encoding='utf-8')
    item('Fortnite', CatalogNamespace='fn', CatalogItemId='abc')
    item('UE_5.2', AppCategories=['engines'])
    item('Gone', InstallLocation=str(tmp_path / 'missing'))
    games = gb.epic_games(tmp_path)
    assert [(g['id'], g['launch']) for g in games] == [('epic-Fortnite', 'com.epicgames.launcher://apps/fn%3Aabc%3AFortnite?action=launch&silent=true')]

def test_background_program_is_not_a_game(monkeypatch):
    # Wallpaper Engine sta nella cartella di Steam ma non va mai in primo piano: niente Gaming automatico.
    bg = FakeProc(20, 'wallpaper64.exe', r'A:\SteamLibrary\steamapps\common\wallpaper_engine\wallpaper64.exe')
    monkeypatch.setattr(gb.psutil, 'process_iter', lambda attrs=None: [bg])
    monkeypatch.setattr(gb, 'library', lambda force=False: [])
    monkeypatch.setattr(gb, 'foreground_window', lambda: (999, False))
    b = gb.Booster({})
    assert b.tick() is None
    monkeypatch.setattr(gb, 'foreground_window', lambda: (20, False))
    monkeypatch.setattr(gb, 'skipped_dirs', lambda: [])
    assert b.tick()['name'] == 'wallpaper64'            # in primo piano e nella cartella di Steam
    monkeypatch.setattr(gb, 'skipped_dirs', lambda: [r'A:\SteamLibrary\steamapps\common\wallpaper_engine'])
    assert b.tick() is None                             # ma Steam dice che non è un gioco

def test_tweaks_priorities_and_session(monkeypatch):
    reg = {('HKCU', r'System\GameConfigStore', 'GameDVR_Enabled'): 1}
    fake_registry(monkeypatch, reg)
    game = FakeProc(10, 'cs2.exe', r'D:\SteamLibrary\steamapps\common\cs2\cs2.exe')
    chat = FakeProc(11, 'discord.exe', r'C:\Users\x\AppData\Local\Discord\app\Discord.exe')
    monkeypatch.setattr(gb.psutil, 'process_iter', lambda attrs=None: [game, chat])
    monkeypatch.setattr(gb.psutil, 'Process', lambda pid: {10: game, 11: chat}[pid])
    monkeypatch.setattr(gb, 'foreground_window', lambda: (10, False))
    monkeypatch.setattr(gb, 'library', lambda force=False: [{'id': 'steam-730', 'name': 'Counter-Strike 2', 'store': 'Steam',
                                                            'dir': r'D:\SteamLibrary\steamapps\common\cs2', 'last': 0}])
    state, notes = {}, []
    b = gb.Booster({'gaming_boost': {'apps': {'discord.exe': 'lower'}}}, state=state, notify=notes.append)
    b.start()
    assert reg[('HKCU', r'System\GameConfigStore', 'GameDVR_Enabled')] == 0
    assert reg[('HKCU', r'Software\Microsoft\GameBar', 'AutoGameModeEnabled')] == 1
    assert state['boost_saved']['tweaks']['no_dvr'] == 1          # originale al sicuro anche se NEXAR si chiude
    assert game.prio == gb.HIGH and chat.prio == gb.BELOW and b.info()['game'] == 'Counter-Strike 2'
    b.session['start'] -= 1800; b.session['last'] -= 10
    b.sample({'cpu_temp': 70, 'gpu_temp': 65, 'cpu': 30, 'gpu': 90, 'power': {'total': 360}})
    b.sample({'cpu_temp': 76, 'gpu_temp': 61, 'cpu': 40, 'gpu': 80, 'power': {'total': 360}})
    b.stop()
    assert reg[('HKCU', r'System\GameConfigStore', 'GameDVR_Enabled')] == 1          # valore originale
    assert ('HKCU', r'Software\Microsoft\GameBar', 'AutoGameModeEnabled') not in reg  # non c'era: tolto
    assert game.prio == 32 and chat.prio == 32 and not b.active and 'boost_saved' not in state
    h = state['gaming_history'][0]
    assert h['game'] == 'Counter-Strike 2' and h['cpu_temp_max'] == 76 and h['gpu_temp_max'] == 65 and h['elapsed'] >= 1800
    assert state['games']['steam-730']['seconds'] >= 1800 and notes and 'Partita finita' in notes[0]

def test_restart_in_gaming_restores_true_originals(monkeypatch):
    # NEXAR riavviata in Gaming: il registro ha già i valori "da gioco"; si devono ripristinare quelli salvati.
    reg = {('HKCU', r'System\GameConfigStore', 'GameDVR_Enabled'): 0}
    fake_registry(monkeypatch, reg)
    monkeypatch.setattr(gb.psutil, 'process_iter', lambda attrs=None: [])
    monkeypatch.setattr(gb, 'foreground_window', lambda: (None, False))
    monkeypatch.setattr(gb, 'library', lambda force=False: [])
    state = {'boost_saved': {'tweaks': {'no_dvr': 1, 'no_capture': None, 'game_mode': None}, 'mouse': None}}
    b = gb.Booster({}, state=state)
    b.start(); b.stop()
    assert reg[('HKCU', r'System\GameConfigStore', 'GameDVR_Enabled')] == 1

class FakeCtl:
    """Il minimo di Control che serve al Gaming automatico."""
    auto_gaming = core.Control.auto_gaming
    def __init__(self, auto=True):
        self.booster = gb.Booster({'gaming_boost': {'auto': auto}})
        self.current, self.calls = 'eco', []
        self.gaming_owned, self.gaming_prev, self.gaming_declined, self.game_gone, self.launch_grace = False, 'normal', False, None, 0.0
    def mode(self): return self.current
    def set_mode(self, value, manual=True, reason='', quiet=False):
        self.calls.append((value, reason)); self.current = value

def test_auto_gaming_on_and_back(monkeypatch):
    c = FakeCtl()
    game = {'id': 'steam-1', 'name': 'Hollow Knight', 'store': 'Steam'}
    c.auto_gaming(game, False)
    assert c.calls == [('gaming', 'Hollow Knight')] and c.gaming_owned and c.gaming_prev == 'eco'
    c.auto_gaming(None, True)                       # appena chiuso: aspetta
    assert len(c.calls) == 1
    c.game_gone = time.monotonic() - 25             # chiuso da 25 s: torna com'era
    c.auto_gaming(None, True)
    assert c.calls[-1] == ('eco', '') and not c.gaming_owned

def test_auto_gaming_respects_user(monkeypatch):
    c = FakeCtl(auto=False)
    c.auto_gaming({'id': 'x', 'name': 'X', 'store': ''}, False)
    assert c.calls == []
    c = FakeCtl(); c.gaming_declined = True          # l'utente è uscito da Gaming con il gioco aperto
    c.auto_gaming({'id': 'x', 'name': 'X', 'store': ''}, False)
    assert c.calls == []
    c.auto_gaming(None, False)                      # chiuso il gioco: la prossima volta si riattiva
    assert c.gaming_declined is False
