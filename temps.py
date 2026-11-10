"""Tutte le temperature del PC lette da LibreHardwareMonitor, raggruppate e con nomi chiari."""
import re

# soglie: da qui in su arancione (hot), da qui in su rosso (crit)
LIMITS = {
    'cpu': (80, 90), 'gpu': (75, 85), 'gpu_hot': (90, 100), 'board': (60, 75), 'vrm': (75, 95),
    'ram': (50, 55), 'nvme': (60, 74), 'hdd': (45, 55),
}
SKIP = re.compile(r'(?i)resolution|limit|warning temperature|critical temperature')
KIND = [
    (re.compile(r'^/(amdcpu|intelcpu)/\d+/temperature/'), 'cpu'),
    (re.compile(r'^/gpu-(nvidia|amd|intel)/\d+/temperature/'), 'gpu'),
    (re.compile(r'^/(lpc|mainboard|superio)/'), 'board'),
    (re.compile(r'^/memory/dimm/\d+/temperature/'), 'ram'),
    (re.compile(r'^/(nvme|hdd|ssd|storage|ata)/\d+/temperature/'), 'disk'),
]
ORDER = {'cpu': 0, 'gpu': 1, 'board': 2, 'ram': 3, 'disk': 4}


def _num(x):
    try: return float(re.search(r'-?\d+(?:[.,]\d+)?', str(x)).group(0).replace(',', '.'))
    except (AttributeError, ValueError, TypeError): return None


def _label(kind, name):
    n = name.strip()
    low = n.lower()
    if kind == 'cpu':
        if ('tctl' in low or 'tdie' in low) and 'ccd' not in low: return 'Processore'
        m = re.match(r'(?i)ccd\s*(\d+)', n)
        if m: return f'CCD {m.group(1)}'
        if 'package' in low: return 'Processore'
        m = re.match(r'(?i)(?:cpu\s*)?core\s*#?(\d+)', n)
        if m: return f'Core {m.group(1)}'
    if kind == 'gpu':
        if 'hot spot' in low or 'hotspot' in low: return 'Punto più caldo'
        if 'memory' in low: return 'Memoria video'
        if 'vr' in low or 'soc' in low: return 'Alimentazione'
        if 'core' in low or low == 'gpu': return 'Chip'
    if kind == 'board':
        return {'system': 'Sistema', 'vrm mos': 'VRM (alimentazione CPU)', 'vrm': 'VRM (alimentazione CPU)', 'chipset': 'Chipset',
                'pch': 'Chipset', 'motherboard': 'Scheda madre'}.get(low, n)
    if kind == 'ram':
        m = re.search(r'#\s*(\d+)', n)
        return f'Banco {m.group(1)}' if m else n
    return n


BRANDS = [(r'^WDC\s+', 'WD '), (r'^KINGSTON\b', 'Kingston'), (r'^SAMSUNG\b', 'Samsung'), (r'^CT(\d)', r'Crucial CT\1'),
          (r'^ST(\d)', r'Seagate ST\1'), (r'^TOSHIBA\b', 'Toshiba')]


def _disk_name(name):
    n = name or 'Disco'
    for rx, rep in BRANDS: n = re.sub(rx, rep, n)
    return n


def _clean_device(name):
    n = re.sub(r'[^\x20-\x7e]+', ' ', name or '')
    n = re.sub(r'\s{2,}.*$', '', n.strip())          # nomi RAM con caratteri sporchi in coda
    return re.sub(r'\s*\(#\d+\)$', '', n).strip()


def groups(tree):
    """Dal JSON di LibreHardwareMonitor ai gruppi della dashboard: processore, scheda video, scheda madre, RAM, dischi."""
    found = {}       # chiave gruppo → dict
    disk_info = {}   # id disco → {'warn','crit','name'}

    def add(key, kind, device, row):
        g = found.setdefault(key, {'kind': kind, 'name': device, 'rows': []})
        g['rows'].append(row)

    def walk(node, trail):
        if isinstance(node, list):
            for n in node: walk(n, trail)
            return
        if not isinstance(node, dict): return
        name = str(node.get('Text', ''))
        sid = str(node.get('SensorId', '')).lower()
        val = _num(node.get('Value'))
        is_temp = str(node.get('Type', '')).lower() == 'temperature' or '°c' in str(node.get('Value', '')).lower()
        if sid and val is not None and is_temp:
            kind = next((k for rx, k in KIND if rx.match(sid)), None)
            device = _clean_device(trail[-2] if len(trail) >= 2 else '')
            if kind == 'disk':
                dev = sid.split('/temperature/')[0]
                info = disk_info.setdefault(dev, {'name': device})
                if re.search(r'(?i)warning', name): info['warn'] = val
                elif re.search(r'(?i)critical', name): info['crit'] = val
                elif not SKIP.search(name) and 'main' not in info and -10 < val < 120:
                    info['main'] = {'id': sid, 'value': round(val, 1), 'max': _num(node.get('Max'))}
            elif kind and not SKIP.search(name) and 0 < val < 130:
                if kind == 'board' and re.search(r'(?i)\bcpu\b', name): pass   # doppione del processore
                else:
                    lim = LIMITS['gpu_hot'] if kind == 'gpu' and re.search(r'(?i)hot ?spot|memory', name) else \
                          LIMITS['vrm'] if kind == 'board' and 'vrm' in name.lower() else LIMITS[kind]
                    mx = _num(node.get('Max'))
                    row = {'id': sid, 'name': _label(kind, name), 'value': round(val, 1),
                           'max': round(mx, 1) if mx is not None else None, 'hot': lim[0], 'crit': lim[1]}
                    key = {'cpu': 'cpu', 'board': 'board', 'ram': 'ram'}.get(kind) or sid.split('/temperature/')[0]
                    dev_name = {'board': 'Scheda madre', 'ram': 'Memoria RAM'}.get(kind) or device
                    if kind == 'gpu' and re.search(r'(?i)radeon\(tm\) graphics|uhd graphics|iris', device): dev_name = 'Grafica integrata'
                    add(key, kind, dev_name, row)
        for c in node.get('Children', []): walk(c, trail + [name])

    walk(tree, [])
    names = {}
    for dev, info in sorted(disk_info.items()):
        if 'main' not in info: continue
        base = _disk_name(info['name'])
        names[base] = names.get(base, 0) + 1
        nvme = '/nvme/' in dev
        crit = info.get('warn') or LIMITS['nvme' if nvme else 'hdd'][1]
        hot = min(crit - 8, LIMITS['nvme' if nvme else 'hdd'][0])
        m = info['main']
        add('disk', 'disk', 'Dischi', {'id': m['id'], 'name': base + (f' ({names[base]})' if names[base] > 1 else ''),
                                      'value': m['value'], 'max': round(m['max'], 1) if m['max'] is not None else None,
                                      'hot': hot, 'crit': crit, 'tag': 'NVMe' if nvme else 'HDD' if '/hdd/' in dev else 'SSD'})
    out = sorted(found.values(), key=lambda g: (ORDER[g['kind']], g['name'] == 'Grafica integrata'))
    for g in out:
        if g['kind'] == 'cpu': g['rows'].sort(key=lambda r: r['name'] != 'Processore')
        if g['kind'] == 'gpu': g['rows'].sort(key=lambda r: r['name'] != 'Chip')
        g['rows'] = _dedupe(g['rows'])
    return out


def _dedupe(rows):
    seen, out = set(), []
    for r in rows:
        if r['name'] in seen: continue
        seen.add(r['name']); out.append(r)
    return out
