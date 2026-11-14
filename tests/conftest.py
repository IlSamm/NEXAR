"""Protezione per tutti i test: niente attività pianificate vere di Windows.
Sul PC di sviluppo esistono davvero (ventole, luci MSI, sensori): un test non deve mai lanciarle."""
import subprocess
import pytest

_real_run = subprocess.run

@pytest.fixture(autouse=True)
def no_real_scheduled_tasks(monkeypatch):
    def run(args, *a, **k):
        first = (args[0] if isinstance(args, (list, tuple)) and args else str(args)).lower()
        if 'schtasks' in first:
            return subprocess.CompletedProcess(args, 1, '' if k.get('text') else b'', 'bloccato nei test')
        return _real_run(args, *a, **k)
    monkeypatch.setattr(subprocess, 'run', run)
    # Né chiudere programmi veri del PC (Armoury Crate, OpenRGB…) né leggerne l'elenco.
    import discovery, psutil
    monkeypatch.setattr(discovery, 'conflicts_running', lambda: {})
    monkeypatch.setattr(discovery, 'openrgb_service', lambda: {})
    def no_kill(self): raise RuntimeError('chiusura di processi bloccata nei test')
    monkeypatch.setattr(psutil.Process, 'kill', no_kill)
