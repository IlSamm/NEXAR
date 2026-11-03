"""Stima del consumo alla presa, componente per componente.

Misurati: processore (sensore Package di LibreHardwareMonitor) e scheda video (nvidia-smi, potenza della scheda).
Stimati da dati tecnici tipici: scheda madre, RAM, dischi (con la loro attività), ventole (dai giri), pompa, LED,
periferiche USB e monitor. Il totale passa per la curva di efficienza dell'alimentatore 80 PLUS a 230 V.
"""
from __future__ import annotations

# Efficienza in funzione del carico (frazione della potenza nominale). Valori 80 PLUS a 230 V con
# la tipica caduta sotto il 20% di carico, dove un PC da scrivania passa la maggior parte del tempo.
PSU_CURVES = {
    'bronze':   [(0.02, .66), (0.05, .76), (0.10, .83), (0.20, .86), (0.50, .89), (1.00, .86)],
    'gold':     [(0.02, .70), (0.05, .80), (0.10, .87), (0.20, .91), (0.50, .93), (1.00, .90)],
    'platinum': [(0.02, .73), (0.05, .83), (0.10, .89), (0.20, .93), (0.50, .95), (1.00, .91)],
    'titanium': [(0.02, .78), (0.05, .87), (0.10, .91), (0.20, .95), (0.50, .96), (1.00, .92)],
}
PSU_CLASSES = tuple(PSU_CURVES)
VRM_EFFICIENCY = 0.90       # regolatori di tensione della CPU sulla scheda madre
LED_WATTS = 0.10            # un LED indirizzabile a bianco pieno (60 mA a 5 V, limitati dai controller)
LED_IDLE_WATTS = 0.004      # LED spento: resta alimentato il suo piccolo driver

def interpolate(points, x):
    if x <= points[0][0]: return points[0][1]
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if x <= x1: return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return points[-1][1]

def psu_efficiency(dc_watts, psu_watts=750, psu_class='gold'):
    load = dc_watts / max(200, psu_watts)
    return interpolate(PSU_CURVES.get(psu_class, PSU_CURVES['gold']), load), load

def power_factor(load):
    """PFC attivo: ~0.88 a carico molto basso, oltre 0.97 da metà carico."""
    return min(0.99, 0.86 + 0.24 * min(load, 0.5))

def fan_watts(rpm, rpm_max=1800, max_watts=1.6):
    """Le ventole consumano circa con il cubo della velocità, più l'elettronica del motore."""
    if not rpm or rpm <= 0: return 0.0
    ratio = min(1.3, rpm / rpm_max)
    return 0.25 + (max_watts - 0.25) * ratio ** 3

def disk_watts(kind, busy):
    idle, active = {'nvme': (1.0, 5.5), 'ssd': (0.6, 2.8), 'hdd': (3.2, 5.6)}.get(kind, (1.0, 4.0))
    return idle + (active - idle) * max(0.0, min(1.0, busy))

def rgb_watts(leds, color, brightness, off):
    if not leds: return 0.0
    if off: return leds * LED_IDLE_WATTS
    try: level = sum(int(color[i:i + 2], 16) for i in (1, 3, 5)) / 765
    except (TypeError, ValueError): level = 1.0
    return leds * (LED_IDLE_WATTS + LED_WATTS * level * max(0, min(100, brightness)) / 100)

def board_watts(name):
    """Chipset, audio, rete e Wi-Fi: le schede X670E/X870E hanno due chip e consumano di più."""
    n = (name or '').upper()
    if any(x in n for x in ('X870E', 'X670E', 'Z790', 'Z890')): return 22.0
    if any(x in n for x in ('X870', 'X670', 'B850', 'B650', 'B760', 'B860')): return 14.0
    return 12.0

def estimate(inputs: dict, cfg: dict, hardware: dict, inventory: dict):
    """inputs: cpu_w, gpu_w, cpu_load, gpu_load, fans[], disks_busy{id:0-1}, rgb{leds,color,brightness,off}, display_on."""
    items = []
    def add(key, name, watts, measured, detail=''):
        if watts is not None and watts > 0.05:
            items.append({'key': key, 'name': name, 'watts': round(watts, 1), 'source': 'misurato' if measured else 'stimato', 'detail': detail})

    cpu_load = inputs.get('cpu_load') or 0
    if inputs.get('cpu_w') is not None:
        add('cpu', 'Processore', inputs['cpu_w'] / VRM_EFFICIENCY, True, f"{inputs['cpu_w']:.0f} W nel chip + regolatori")
    else:
        tdp = float(cfg.get('cpu_tdp', 120))
        add('cpu', 'Processore', (0.22 * tdp + cpu_load / 100 * 0.85 * tdp) / VRM_EFFICIENCY, False, 'dal carico, sensore non collegato')
    if inputs.get('gpu_w') is not None:
        add('gpu', 'Scheda video', inputs['gpu_w'], True, 'scheda intera, ventole comprese')
    elif hardware.get('gpu'):
        tdp = float(cfg.get('gpu_tdp', 200))
        add('gpu', 'Scheda video', 0.08 * tdp + (inputs.get('gpu_load') or 0) / 100 * 0.9 * tdp, False, 'dal carico')

    add('board', 'Scheda madre', board_watts(hardware.get('motherboard')), False, 'chipset, rete, audio, Wi-Fi')
    dimms = int(inventory.get('dimms') or 2)
    add('ram', 'Memoria RAM', dimms * (1.6 + 2.4 * cpu_load / 100), False, f'{dimms} moduli')

    busy = inputs.get('disks_busy') or {}
    disks = inventory.get('disks') or []
    total_disk, kinds = 0.0, {}
    for d in disks:
        total_disk += disk_watts(d.get('kind'), busy.get(str(d.get('id')), 0))
        kinds[d.get('kind')] = kinds.get(d.get('kind'), 0) + 1
    if disks:
        label = {'nvme': 'NVMe', 'ssd': 'SSD', 'hdd': 'HDD'}
        add('disks', 'Dischi', total_disk, False, ' + '.join(f'{n} {label.get(k, k)}' for k, n in kinds.items()))

    fans = [f for f in inputs.get('fans') or [] if f.get('rpm', 0) > 0]
    fw = sum(fan_watts(f['rpm']) for f in fans)
    cooler = (hardware.get('cooler') or '').lower()
    pump = 3.5 if any(x in cooler for x in ('liquid', 'aio', 'kraken', 'h100', 'h150')) else 0.0
    if fans or pump:
        add('cooling', 'Ventole e pompa', fw + pump, False, f'{len(fans)} ventole' + (' + pompa AIO' if pump else ''))

    rgb = inputs.get('rgb') or {}
    add('rgb', 'LED RGB', rgb_watts(rgb.get('leds'), rgb.get('color', '#ffffff'), rgb.get('brightness', 100), rgb.get('off')),
        False, f"{rgb.get('leds')} LED" + (' spenti' if rgb.get('off') else ''))
    add('usb', 'Periferiche USB', float(cfg.get('extra_watts', 6)), False, 'mouse, tastiera, cuffie…')

    dc = sum(i['watts'] for i in items)
    psu = int(cfg.get('psu_watts', 750)); cls = cfg.get('psu_class', 'gold')
    eff, load = psu_efficiency(dc, psu, cls)
    wall = dc / eff
    monitor = float(cfg.get('monitor_watts', 0))
    monitor_on = bool(monitor) and inputs.get('display_on', True)
    if monitor_on:
        items.append({'key': 'monitor', 'name': 'Monitor', 'watts': round(monitor, 1), 'source': 'stimato', 'detail': 'presa separata'})
        wall += monitor
    volts = int(cfg.get('mains_voltage', 230))
    pf = power_factor(load)
    measured = sum(i['watts'] for i in items if i['source'] == 'misurato')
    # Più watt misurati = stima più stretta: ±6% se CPU e GPU sono letti dai sensori, fino a ±15% senza.
    margin = 0.06 + 0.09 * (1 - measured / dc) if dc else 0.15
    get = lambda k: next((i['watts'] for i in items if i['key'] == k), None)
    return {
        'items': items, 'dc': round(dc, 1), 'total': round(wall, 1), 'loss': round(dc / eff - dc, 1),
        'efficiency': round(eff, 3), 'psu_load': round(load * 100, 1), 'psu_watts': psu, 'psu_class': cls,
        'amps': round(wall / (volts * pf), 2), 'va': round(wall / pf), 'pf': round(pf, 2), 'voltage': volts,
        'low': round(wall * (1 - margin)), 'high': round(wall * (1 + margin)), 'margin': round(margin * 100),
        'monitor_on': monitor_on, 'monitor_watts': monitor,
        # Compatibilità: bot e grafici leggono ancora queste tre voci.
        'cpu': get('cpu'), 'gpu': get('gpu'), 'other': round(dc - (get('cpu') or 0) - (get('gpu') or 0), 1),
    }
