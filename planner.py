"""Azioni programmate: «spegni il PC alle 23», «AI ECO di notte», «LED spenti alle 0:30»…

Ogni regola ha un orario, i giorni della settimana e un'azione. Le azioni che spengono o sospendono il PC
partono con 5 minuti di preavviso (avviso su Telegram e /annulla per fermarle). Se il PC era spento
all'orario giusto la regola si recupera solo entro 10 minuti: niente spegnimenti a sorpresa al mattino.
"""
from __future__ import annotations
import re
import secrets
import threading
from datetime import datetime, timedelta

ACTIONS = {
    'shutdown': 'Spegni il PC', 'sleep': 'Sospendi il PC',
    'eco': 'AI ECO', 'normal': 'Profilo normale', 'gaming': 'Gaming',
    'monitor_off': 'Spegni il monitor', 'lock': 'Blocca il PC',
    'leds_off': 'Spegni i LED', 'leds_on': 'Accendi i LED',
}
POWER = ('shutdown', 'sleep')
WARN = 300          # preavviso per spegnimento e sospensione
LATE = 600          # recupero se il PC era occupato o NEXAR si è appena avviato
MAX_RULES = 20
DAYS = ('lun', 'mar', 'mer', 'gio', 'ven', 'sab', 'dom')
HHMM = re.compile(r'^([01]\d|2[0-3]):([0-5]\d)$')


def clean_rule(r: dict) -> dict:
    if not isinstance(r, dict): raise ValueError('Regola non valida')
    t = str(r.get('time') or '')
    if not HHMM.match(t): raise ValueError('Orario non valido (HH:MM)')
    days = r.get('days')
    if not isinstance(days, list) or not days or any(type(d) is not int or not 0 <= d <= 6 for d in days):
        raise ValueError('Scegli almeno un giorno')
    action = r.get('action')
    if action not in ACTIONS: raise ValueError('Azione non prevista')
    rid = str(r.get('id') or '')
    if not re.fullmatch(r'[a-f0-9]{8}', rid): rid = secrets.token_hex(4)
    return {'id': rid, 'time': t, 'days': sorted(set(days)), 'action': action, 'enabled': bool(r.get('enabled', True))}


def clean_rules(rules) -> list:
    if not isinstance(rules, list): raise ValueError('Elenco non valido')
    if len(rules) > MAX_RULES: raise ValueError(f'Massimo {MAX_RULES} azioni programmate')
    out, seen = [], set()
    for r in rules:
        c = clean_rule(r)
        while c['id'] in seen: c['id'] = secrets.token_hex(4)
        seen.add(c['id']); out.append(c)
    return out


def _at(rule, day) -> datetime:
    h, m = map(int, rule['time'].split(':'))
    return datetime(day.year, day.month, day.day, h, m)


def due(rule: dict, now: datetime, last: str | None):
    """(orario previsto, secondi che mancano) se la regola va eseguita adesso, altrimenti None."""
    if not rule.get('enabled'): return None
    lead = WARN if rule['action'] in POWER else 0
    for shift in (-1, 0, 1):              # a cavallo della mezzanotte
        at = _at(rule, (now + timedelta(days=shift)).date())
        if at.weekday() not in rule['days'] or last == at.date().isoformat(): continue
        if at - timedelta(seconds=lead) <= now <= at + timedelta(seconds=LATE):
            return at, (at - now).total_seconds()
    return None


def next_run(rule: dict, now: datetime):
    if not rule.get('enabled'): return None
    for shift in range(0, 8):
        at = _at(rule, (now + timedelta(days=shift)).date())
        if at.weekday() in rule['days'] and at > now: return at
    return None


def describe(rule: dict) -> str:
    d = rule['days']
    days = 'ogni giorno' if len(d) == 7 else 'lun–ven' if d == [0, 1, 2, 3, 4] else 'sab e dom' if d == [5, 6] else ', '.join(DAYS[i] for i in d)
    return f"{ACTIONS[rule['action']]} alle {rule['time']} · {days}"


class Planner:
    def __init__(self, get_rules, runs: dict, save, do, clock=datetime.now, lock=None):
        self.get_rules, self.runs, self.save, self.do, self.clock = get_rules, runs, save, do, clock
        self.lock = lock or threading.Lock()   # lo stesso lock di chi salva lo stato

    def tick(self):
        now = self.clock()
        for rule in list(self.get_rules() or []):
            with self.lock:
                hit = due(rule, now, self.runs.get(rule['id']))
                if not hit: continue
                self.runs[rule['id']] = hit[0].date().isoformat()
            self.save()
            self.do(rule, hit[1])

    def view(self):
        now = self.clock()
        out = []
        for r in self.get_rules() or []:
            n = next_run(r, now)
            out.append({**r, 'label': ACTIONS[r['action']], 'text': describe(r), 'next': n.isoformat(timespec='minutes') if n else None})
        return out

    def run(self, stop):
        while not stop.wait(20):
            try: self.tick()
            except Exception:
                import logging; logging.exception('Azioni programmate')
