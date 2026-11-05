"""Capisce quando Codex o Claude finiscono un lavoro.

Le app restano aperte anche quando non fanno nulla, quindi non basta vedere se sono avviate:
si guarda quanto lavorano (CPU dell'app e dei comandi che lancia). Lavoro lungo che si ferma = ha finito.
"""
import time

import psutil

BUSY_CORES = 0.12     # oltre ~12% di un core in media: sta lavorando
START_TICKS = 2       # due letture di fila (≈25 s) per dire che ha iniziato
QUIET_SECONDS = 90    # ferma da 90 s: ha finito
MIN_WORK = 180        # avvisa solo per lavori di almeno 3 minuti
AWAY_SECONDS = 120    # e solo se nessuno usa il PC da 2 minuti


def sample(names) -> dict:
    """{pid: (app, secondi di CPU)} per ogni app cercata e per i processi che ha avviato."""
    out = {}
    for p in psutil.process_iter(['name']):
        app = (p.info.get('name') or '').lower()
        if app not in names: continue
        try: family = [p] + p.children(recursive=True)
        except psutil.Error: continue
        for q in family:
            if q.pid in out: continue
            try: t = q.cpu_times(); out[q.pid] = (app, t.user + t.system)
            except psutil.Error: pass
    return out


class AiWatch:
    def __init__(self):
        self.prev, self.prev_at, self.apps = None, None, {}

    def reset(self):
        self.prev, self.prev_at, self.apps = None, None, {}

    def busy(self):
        return sorted(a for a, s in self.apps.items() if s.get('start') is not None)

    def tick(self, names, now=None, sampler=sample) -> list:
        """Una lettura. Restituisce [(app, secondi di lavoro)] per i lavori appena finiti."""
        now = time.monotonic() if now is None else now
        cur = sampler(names)
        if self.prev is None:
            self.prev, self.prev_at = cur, now
            return []
        dt = max(1.0, now - self.prev_at)
        load = {}
        for pid, (app, cpu) in cur.items():
            old = self.prev.get(pid)
            used = cpu - old[1] if old else cpu        # processo nuovo (un comando lanciato): tutto il suo lavoro conta
            load[app] = load.get(app, 0.0) + max(0.0, used)
        self.prev, self.prev_at = cur, now
        done = []
        for app in set(load) | set(self.apps):
            st = self.apps.setdefault(app, {'ticks': 0, 'start': None, 'last': None})
            if load.get(app, 0.0) / dt >= BUSY_CORES:
                st['ticks'] += 1; st['last'] = now
                if st['start'] is None and st['ticks'] >= START_TICKS: st['start'] = now - dt * st['ticks']
            elif st['start'] is None: st['ticks'] = 0
            elif now - st['last'] >= QUIET_SECONDS:
                worked = st['last'] - st['start']
                if worked >= MIN_WORK: done.append((app, worked))
                st.update(ticks=0, start=None, last=None)
        return done
