"""Elenco dei processi sicuro tra thread.

psutil.process_iter(attrs) riusa gli stessi oggetti Process fra una chiamata e l'altra e scrive i valori in p.info:
se due thread lo usano insieme (la scheda Programmi, Gaming, le ventole…) uno trova il p.info dell'altro e salta
fuori un KeyError ('cpu_times', 'memory_info', 'exe' nel log). Qui ogni giro ha i suoi dizionari.
"""
from __future__ import annotations

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
