import core
import procstop


def test_names_list_groups_duplicates():
    assert core.names_list(['ENE DRAM', 'ENE DRAM', 'Corsair']) == 'ENE DRAM ×2, Corsair'
    assert core.names_list([]) == ''


class FakeProc:
    def __init__(self, pid, name):
        self.pid = pid; self.info = {'name': name, 'username': 'me', 'exe': r'C:\\Prog\\' + name}


def test_stopper_gives_up_on_programs_windows_restarts(monkeypatch):
    s = procstop.Stopper(); s.me = 'me'
    monkeypatch.setattr(procstop, 'visible_pids', lambda: set())
    monkeypatch.setattr(procstop.proclist, 'iter_info', lambda attrs: [FakeProc(10, 'phoneexperiencehost.exe')])
    closed = []
    for i in range(8):
        closed += s.tick('gaming', {}, now=i * 100, closer=lambda name, procs, force=False: True)
    assert closed == ['phoneexperiencehost.exe'] * procstop.MAX_CLOSES
    s.release()
    assert s.tick('gaming', {}, now=10000, closer=lambda name, procs, force=False: True) == ['phoneexperiencehost.exe']


def test_discover_keeps_state_written_meanwhile(tmp_path, monkeypatch):
    import discovery
    monkeypatch.setattr(core, 'STATE_FILE', tmp_path / 'state.json')
    monkeypatch.setattr(core, 'CONFIG_FILE', tmp_path / 'config.json')
    monkeypatch.setattr(core, 'DATA_DIR', tmp_path)
    c = core.Control({})
    c.state['last_version'] = '1.0.41'
    def slow_search(config, state, allow_uac=False):
        c.state['last_version'] = '9.9.9'          # intanto l'app scrive la versione nuova
        state['lhm_uac_asked'] = True                # la ricerca cambia solo questo
        return []
    monkeypatch.setattr(discovery, 'autoconfigure', slow_search)
    monkeypatch.setattr(discovery, 'hardware_inventory', lambda: {})
    c.discover()
    assert c.state['last_version'] == '9.9.9' and c.state['lhm_uac_asked'] is True
