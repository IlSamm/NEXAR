"""Elenco dei processi sicuro tra thread.

psutil.process_iter(attrs) riusa gli stessi oggetti Process fra una chiamata e l'altra e scrive i valori in p.info:
se due thread lo usano insieme (la scheda Programmi, Gaming, le ventole…) uno trova il p.info dell'altro e salta
fuori un KeyError ('cpu_times', 'memory_info', 'exe' nel log). Qui ogni giro ha i suoi dizionari.
"""
from __future__ import annotations

import time

import psutil


class Proc:
    """Il processo di psutil con un .info tutto suo; il resto (pid, kill, wait…) passa al processo vero."""

    def __init__(self, proc, info):
        self._proc = proc
        self.info = info

    def __getattr__(self, name):
        return getattr(self._proc, name)


def iter_info(attrs):
    for p in psutil.process_iter():
        try: info = p.as_dict(attrs=list(attrs), ad_value=None)
        except psutil.Error: continue
        except AttributeError: info = dict(getattr(p, 'info', None) or {})   # processi finti dei test
        yield Proc(p, info)


def wait_gone(procs, timeout):
    """Come psutil.wait_procs, ma un processo protetto da Windows (accesso negato) conta come ancora aperto
    invece di fermare tutto con un errore."""
    end, alive = time.monotonic() + timeout, list(procs)
    while alive:
        still = []
        for p in alive:
            try:
                if p.is_running() and p.status() != psutil.STATUS_ZOMBIE: still.append(p)
            except psutil.NoSuchProcess: pass
            except psutil.Error: still.append(p)
        alive = still
        if not alive or time.monotonic() >= end: break
        time.sleep(0.25)
    return alive
