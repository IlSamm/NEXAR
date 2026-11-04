import gaming_boost as gb

class FakeProc:
    def __init__(self, pid, name, exe, prio=32):
        self.pid, self.info, self.prio = pid, {'name': name, 'exe': exe}, prio
    def nice(self, value=None):
        if value is None: return self.prio
        self.prio = value

def test_game_detection():
    assert gb.is_game(r'C:\Program Files (x86)\Steam\steamapps\common\Counter-Strike Global Offensive\cs2.exe')
    assert gb.is_game(r'C:\Riot Games\VALORANT\live\VALORANT.exe')
    assert not gb.is_game(r'C:\Program Files\Google\Chrome\Application\chrome.exe')

def test_settings_validation():
    b = gb.Booster({})
    s = b.update_settings({'game_mode': False, 'apps': {'Discord.exe': 'close', 'chrome.exe': 'lower', 'explorer.exe': 'close', 'x.exe': 'boh'}})
    assert s['game_mode'] is False and s['apps'] == {'discord.exe': 'close', 'chrome.exe': 'lower'}

def test_tweaks_and_priorities_restored(monkeypatch):
    reg = {('HKCU', r'System\GameConfigStore', 'GameDVR_Enabled'): 1}
    def fake_reg(hive, path, name, value=None, delete=False):
        if value is None and not delete: return reg.get((hive, path, name))
        if delete: reg.pop((hive, path, name), None)
        else: reg[(hive, path, name)] = value
    monkeypatch.setattr(gb, '_reg', fake_reg)
    monkeypatch.setattr(gb.os, 'name', 'nt')
    game = FakeProc(10, 'cs2.exe', r'D:\SteamLibrary\steamapps\common\cs2\cs2.exe')
    chat = FakeProc(11, 'discord.exe', r'C:\Users\x\AppData\Local\Discord\app\Discord.exe')
    monkeypatch.setattr(gb.psutil, 'process_iter', lambda attrs=None: [game, chat])
    monkeypatch.setattr(gb.psutil, 'Process', lambda pid: {10: game, 11: chat}[pid])
    monkeypatch.setattr(gb, 'foreground_fullscreen_pid', lambda: None)
    b = gb.Booster({'gaming_boost': {'apps': {'discord.exe': 'lower'}}})
    b.start()
    assert reg[('HKCU', r'System\GameConfigStore', 'GameDVR_Enabled')] == 0
    assert reg[('HKCU', r'Software\Microsoft\GameBar', 'AutoGameModeEnabled')] == 1
    assert game.prio == gb.HIGH and chat.prio == gb.BELOW and b.info()['game'] == 'cs2'
    b.stop()
    assert reg[('HKCU', r'System\GameConfigStore', 'GameDVR_Enabled')] == 1          # valore originale
    assert ('HKCU', r'Software\Microsoft\GameBar', 'AutoGameModeEnabled') not in reg  # non c'era: tolto
    assert game.prio == 32 and chat.prio == 32 and not b.active
