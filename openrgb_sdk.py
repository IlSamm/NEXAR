"""Client minimo del protocollo SDK di OpenRGB (porta 6742).

Il server di OpenRGB resta acceso: i dispositivi come il Corsair Lighting Node mantengono
lo stato solo finché qualcuno li tiene aggiornati, cosa che un comando da riga non fa.
"""
from __future__ import annotations
import socket
import struct

PROTOCOL = 3
REQUEST_CONTROLLER_COUNT = 0
REQUEST_CONTROLLER_DATA = 1
REQUEST_PROTOCOL_VERSION = 40
SET_CLIENT_NAME = 50
UPDATELEDS = 1050
UPDATEMODE = 1101
RESIZEZONE = 1000
COLOR_PER_LED, COLOR_MODE_SPECIFIC = 1, 2
OFF_NAMES = ('off', 'disable', 'disabled', 'spento')
STATIC_NAMES = ('static', 'direct', 'custom')
RAINBOW_NAMES = ('rainbow wave', 'rainbow', 'spectrum cycle', 'color cycle')
MAX_RESIZE = 120  # LED per connettore: più di qualsiasi striscia o gruppo di ventole reale

class Reader:
    def __init__(self, data: bytes): self.d, self.i = data, 0
    def take(self, fmt):
        v = struct.unpack_from('<' + fmt, self.d, self.i); self.i += struct.calcsize('<' + fmt)
        return v if len(v) > 1 else v[0]
    def string(self):
        n = self.take('H'); s = self.d[self.i:self.i + n]; self.i += n
        return s.rstrip(b'\0').decode('utf-8', 'replace')

def parse_controller(data: bytes) -> dict:
    r = Reader(data)
    r.take('I')
    ctl = {'type': r.take('i'), 'name': r.string()}
    for _ in range(5): r.string()  # vendor, descrizione, versione, seriale, posizione
    num_modes = r.take('H')
    ctl['active_mode'] = r.take('i')
    modes = []
    for _ in range(num_modes):
        m = {'name': r.string()}
        (m['value'], m['flags'], m['speed_min'], m['speed_max'], m['brightness_min'], m['brightness_max'],
         m['colors_min'], m['colors_max'], m['speed'], m['brightness'], m['direction'], m['color_mode']) = r.take('iIIIIIIIIIII')
        m['colors'] = [r.take('I') for _ in range(r.take('H'))]
        modes.append(m)
    ctl['modes'] = modes
    ctl['zones'] = []
    for _ in range(r.take('H')):
        z = {'name': r.string()}
        z['type'], z['leds_min'], z['leds_max'], z['leds_count'] = r.take('iIII')
        matrix = r.take('H')
        if matrix: r.i += matrix
        ctl['zones'].append(z)
    leds = r.take('H')
    for _ in range(leds): r.string(); r.take('I')
    ctl['colors'] = [r.take('I') for _ in range(r.take('H'))]
    return ctl

def pack_mode(index: int, m: dict) -> bytes:
    name = m['name'].encode('utf-8') + b'\0'
    body = struct.pack('<i', index) + struct.pack('<H', len(name)) + name + struct.pack(
        '<iIIIIIIIIIIIH', m['value'], m['flags'], m['speed_min'], m['speed_max'], m['brightness_min'], m['brightness_max'],
        m['colors_min'], m['colors_max'], m['speed'], m['brightness'], m['direction'], m['color_mode'], len(m['colors']))
    body += b''.join(struct.pack('<I', c) for c in m['colors'])
    return struct.pack('<I', len(body) + 4) + body

def pack_colors(colors: list[int]) -> bytes:
    body = struct.pack('<H', len(colors)) + b''.join(struct.pack('<I', c) for c in colors)
    return struct.pack('<I', len(body) + 4) + body

class Client:
    def __init__(self, host='127.0.0.1', port=6742, timeout=5):
        self.s = socket.create_connection((host, port), timeout)
        self.send(0, REQUEST_PROTOCOL_VERSION, struct.pack('<I', PROTOCOL))
        self.version = min(PROTOCOL, struct.unpack('<I', self.recv()[1])[0])
        self.send(0, SET_CLIENT_NAME, b'NEXAR\0')

    def close(self): self.s.close()
    def __enter__(self): return self
    def __exit__(self, *a): self.close()

    def send(self, dev, pid, data=b''):
        self.s.sendall(b'ORGB' + struct.pack('<III', dev, pid, len(data)) + data)

    def _exact(self, n):
        buf = b''
        while len(buf) < n:
            chunk = self.s.recv(n - len(buf))
            if not chunk: raise ConnectionError('OpenRGB ha chiuso la connessione')
            buf += chunk
        return buf

    def recv(self):
        magic, dev, pid, size = struct.unpack('<4sIII', self._exact(16))
        if magic != b'ORGB': raise ConnectionError('Risposta OpenRGB non valida')
        return pid, self._exact(size)

    def controller(self, i) -> dict:
        self.send(i, REQUEST_CONTROLLER_DATA, struct.pack('<I', self.version))
        ctl = parse_controller(self.recv()[1]); ctl['index'] = i
        return ctl

    def controllers(self) -> list[dict]:
        self.send(0, REQUEST_CONTROLLER_COUNT)
        count = struct.unpack('<I', self.recv()[1])[0]
        return [self.controller(i) for i in range(count)]

    def set_mode(self, dev, index, mode): self.send(dev, UPDATEMODE, pack_mode(index, mode))
    def set_colors(self, dev, colors): self.send(dev, UPDATELEDS, pack_colors(colors))
    def resize(self, dev, zone, size): self.send(dev, RESIZEZONE, struct.pack('<ii', zone, size))

def ensure_leds(c: Client, ctl: dict) -> dict:
    """Connettori ARGB mai configurati (0 LED): li porta al massimo, così il nero arriva a tutta la striscia."""
    if ctl['colors'] or not any(z['leds_max'] for z in ctl['zones']): return ctl
    for zi, z in enumerate(ctl['zones']):
        if z['leds_count'] == 0 and z['leds_max'] > 0:
            c.resize(ctl['index'], zi, min(z['leds_max'], MAX_RESIZE))
    return c.controller(ctl['index'])

def color(hex_rgb: str) -> int:
    """'#RRGGBB' -> colore OpenRGB (byte R, G, B, 0)."""
    h = hex_rgb.lstrip('#')
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return r | (g << 8) | (b << 16)

def leds_set(c: Client, ctl: dict, value: int, allow_off_mode=True) -> str:
    """Modalità "Off" se esiste e si spegne, altrimenti statica/diretta con il colore richiesto."""
    modes = ctl['modes']
    if value == 0 and allow_off_mode:
        for i, m in enumerate(modes):
            if m['name'].lower() in OFF_NAMES:
                c.set_mode(ctl['index'], i, m); return m['name']
    ctl = ensure_leds(c, ctl)
    for wanted in STATIC_NAMES:
        for i, m in enumerate(modes):
            if m['name'].lower() != wanted: continue
            if m['color_mode'] == COLOR_PER_LED and not ctl['colors']: continue
            if m['color_mode'] == COLOR_MODE_SPECIFIC:
                m = dict(m, colors=[value] * max(1, len(m['colors'])))
            elif m['color_mode'] != COLOR_PER_LED: continue
            c.set_mode(ctl['index'], i, m)
            if m['color_mode'] == COLOR_PER_LED:
                c.set_colors(ctl['index'], [value] * len(ctl['colors']))
            return m['name']
    return ''

def snapshot(ctl: dict) -> dict:
    return {'name': ctl['name'], 'active_mode': ctl['active_mode'],
            'mode': ctl['modes'][ctl['active_mode']] if 0 <= ctl['active_mode'] < len(ctl['modes']) else None,
            'colors': ctl['colors'],
            # Senza LED configurati OpenRGB non conosceva l'effetto del firmware: va ricreato.
            'uncontrolled': not ctl['colors']}

def restore(c: Client, ctl: dict, snap: dict, fallback: int):
    if snap.get('uncontrolled'):
        for i, m in enumerate(ctl['modes']):
            if m['name'].lower() in RAINBOW_NAMES and m['color_mode'] == 0:
                c.set_mode(ctl['index'], i, m); return
        leds_set(c, ctl, fallback); return
    if snap.get('mode'):
        c.set_mode(ctl['index'], snap['active_mode'], snap['mode'])
    if snap.get('colors') and len(snap['colors']) == len(ctl['colors']) and (snap.get('mode') or {}).get('color_mode') == COLOR_PER_LED:
        c.set_colors(ctl['index'], snap['colors'])

def legacy_key(ctl): return f"{ctl['index']}:{ctl['name']}"

def keys(ctls: list[dict]) -> list[str]:
    """Chiave stabile di ogni controller: il nome, con #2, #3… per i doppioni (due banchi di RAM).
    L'indice di OpenRGB cambia quando un pad o una tastiera senza fili compare o sparisce."""
    seen, out = {}, []
    for x in ctls:
        n = seen[x['name']] = seen.get(x['name'], 0) + 1
        out.append(x['name'] if n == 1 else f"{x['name']}#{n}")
    return out

def key(ctl, ctls=None):
    """Chiave di un controller; senza l'elenco completo vale solo per il primo con quel nome."""
    return keys(ctls)[ctls.index(ctl)] if ctls else ctl['name']

def lookup(d: dict, k: str, ctl: dict):
    """Valore salvato per un controller: chiave nuova, oppure quella vecchia "indice:nome"."""
    return d[k] if k in d else d.get(legacy_key(ctl))

def all_off(saved: dict | None, skip=(), exclude=()) -> tuple[dict, list[str]]:
    """Restituisce (stato salvato, dispositivi spenti). Con LED già spenti tiene lo stato salvato
    e aggiunge solo i dispositivi comparsi dopo. exclude: controller lasciati ad altri programmi."""
    with Client() as c:
        allc = c.controllers()
        ctls = [(k, x) for k, x in zip(keys(allc), allc) if x['type'] not in skip and x['name'] not in exclude]
        snaps = dict(saved or {})
        for k, x in ctls:
            if lookup(snaps, k, x) is None: snaps[k] = snapshot(x)
        done = [x['name'] for _, x in ctls if leds_set(c, x, 0)]
        c.controllers()  # andata e ritorno: garantisce che i comandi siano stati elaborati
    return snaps, done

def all_restore(saved: dict, fallback='#ffffff', exclude=()) -> list[str]:
    with Client() as c:
        done = []
        allc = c.controllers()
        for k, x in zip(keys(allc), allc):
            snap = None if x['name'] in exclude else lookup(saved, k, x)
            if snap: restore(c, x, snap, color(fallback)); done.append(x['name'])
        c.controllers()
    return done
