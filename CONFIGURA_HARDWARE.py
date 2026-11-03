"""Abilita integrazioni solo quando l'utente ha verificato profili reali e cablaggi."""
from pathlib import Path
import json
import os
import shutil

BASE=Path(__file__).resolve().parent
CONF=BASE/'config.json'
if not CONF.exists(): raise SystemExit('Prima esegui INSTALLA.ps1')
config=json.loads(CONF.read_text(encoding='utf-8-sig'))

def discover(names, paths):
    candidates=[]
    for n in names:
        f=shutil.which(n)
        if f: candidates.append(Path(f))
    for k in ('ProgramFiles','ProgramFiles(x86)','LOCALAPPDATA'):
        root=os.environ.get(k)
        if root:
            for rel in paths:
                candidates.append(Path(root)/rel)
    for c in candidates:
        if c.is_file(): return str(c.resolve())
    return ''

def ask(title, default=''):
    return input(title+(f' [{default}]' if default else '')+': ').strip() or default

print('NEXAR - CONFIGURAZIONE HARDWARE FACOLTATIVA')
print('La pompa e le ventole del radiatore ARCTIC NON devono essere fermate.')
print('Nessuna integrazione si attiva se non hai creato/testato due profili.')

rgb=config.setdefault('rgb',{})
if ask('\nVuoi configurare OpenRGB? (s/n)','n').lower()=='s':
    guess=discover(['OpenRGB.exe'],['OpenRGB/OpenRGB.exe','OpenRGB (Experimental)/OpenRGB.exe'])
    exe=Path(ask('Percorso completo OpenRGB.exe',guess).strip('"'))
    eco=Path(ask('Percorso completo profilo RGB spenti .orp').strip('"'))
    normal=Path(ask('Percorso completo profilo RGB normale .orp').strip('"'))
    if exe.is_file() and eco.is_file() and normal.is_file() and eco.suffix.lower()==normal.suffix.lower()=='.orp':
        print('Abilita soltanto dopo aver aperto ogni profilo in OpenRGB e averne verificato il risultato.')
        if ask('Confermi di aver testato entrambi i profili? (scrivi SI)')=='SI':
            rgb.update({'enabled':True,'openrgb_exe':str(exe),'eco_profile':str(eco),'normal_profile':str(normal)})
            print('OpenRGB abilitato.')
    else: print('Percorsi non validi: RGB lasciati disattivati.')

fans=config.setdefault('fans',{})
if ask('\nVuoi configurare Fan Control SOLO per ventole case indipendenti? (s/n)','n').lower()=='s':
    guess=discover(['FanControl.exe'],['FanControl/FanControl.exe','Fan Control/FanControl.exe'])
    exe=Path(ask('Percorso completo FanControl.exe',guess).strip('"'))
    eco=ask('Nome profilo già testato (esempio EcoCase.json)')
    normal=ask('Nome profilo normale già testato (esempio Default.json)')
    if exe.is_file() and all(x and Path(x).name==x and x.lower().endswith('.json') and (exe.parent/x).is_file() for x in (eco,normal)):
        print('ATTENZIONE: CPU_FAN/AIO/PMW combinato ARCTIC mai in Zero RPM!')
        if ask('Confermi di aver escluso l\'AIO e testato il profilo ECO sotto carico? (scrivi SICURO)')=='SICURO':
            fans.update({'enabled':True,'fancontrol_exe':str(exe),'eco_profile':eco,'normal_profile':normal})
            print('Fan Control abilitato.')
    else: print('Percorsi/profili non validi: Fan Control lasciato disattivato.')

CONF.write_text(json.dumps(config,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print('\nConfigurazione salvata; riavvia NEXAR.')
input('Premi INVIO per uscire...')
