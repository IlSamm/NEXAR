"""Chiudere il gioco dalla scheda (es. Fortnite), non solo spegnere Gaming."""
import gaming_boost as gb


class P:
    def __init__(self, pid, name, exe): self.pid, self.info = pid, {'name': name, 'exe': exe}


def test_game_processes_are_the_game_and_its_folder_only(monkeypatch):
    procs = [P(10, 'FortniteClient-Win64-Shipping.exe', r'C:\Program Files\Epic Games\Fortnite\FortniteGame\Binaries\Win64\FortniteClient-Win64-Shipping.exe'),
             P(11, 'EasyAntiCheat_EOS.exe', r'C:\Program Files\Epic Games\Fortnite\FortniteGame\Binaries\Win64\EasyAntiCheat\EasyAntiCheat_EOS.exe'),
             P(12, 'EpicGamesLauncher.exe', r'C:\Program Files (x86)\Epic Games\Launcher\Portal\Binaries\Win64\EpicGamesLauncher.exe'),
             P(13, 'explorer.exe', r'C:\Windows\explorer.exe'), P(14, 'csrss.exe', '')]
    monkeypatch.setattr(gb.psutil, 'process_iter', lambda attrs=None: iter(procs))
    games = [{'id': 'epic-fortnite', 'dir': r'C:\Program Files\Epic Games\Fortnite'}, {'id': 'steam-1', 'dir': r'C:\Games\Other'}]
    got = gb.game_processes({'id': 'epic-fortnite', 'name': 'Fortnite'}, {10}, games)
    assert [p.pid for p in got] == [10, 11]
    assert gb.game_processes(None, set(), games) == []


def test_quit_turns_gaming_off(monkeypatch, tmp_path):
    import core
    monkeypatch.setattr(core, 'STATE_FILE', tmp_path / 'state.json'); monkeypatch.setattr(core, 'CONFIG_FILE', tmp_path / 'config.json')
    c = core.Control({}); c.log_event = lambda m: None
    monkeypatch.setattr(core.os, 'name', 'nt')
    monkeypatch.setattr(c.booster, 'quit_game', lambda: 'Fortnite')
    monkeypatch.setattr(c, 'mode', lambda: 'gaming')
    monkeypatch.setattr(c, 'set_mode', lambda m: 'Energia: Normale' if m == 'normal' else '')
    assert c.quit_game() == 'Fortnite chiuso · Energia: Normale'
