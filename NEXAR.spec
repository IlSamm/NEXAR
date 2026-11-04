from PyInstaller.utils.hooks import collect_data_files
from PyInstaller.utils.win32.versioninfo import (VSVersionInfo, FixedFileInfo, StringFileInfo, StringTable,
                                                 StringStruct, VarFileInfo, VarStruct)
# -*- mode: python ; coding: utf-8 -*-
import re
VERSION = re.search(r"VERSION = '([\d.]+)'", open('version.py', encoding='utf-8-sig').read()).group(1)
NUMS = tuple(int(x) for x in VERSION.split('.')) + (0,)

# Nome, editore e versione dentro l'exe: un programma "anonimo" è uno dei segnali che fanno scattare gli antivirus.
version_info = VSVersionInfo(
    ffi=FixedFileInfo(filevers=NUMS, prodvers=NUMS, mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
    kids=[
        StringFileInfo([StringTable('041004B0', [
            StringStruct('CompanyName', 'IlSamm'),
            StringStruct('FileDescription', 'NEXAR - controllo del PC (consumi, luci, ventole, Telegram)'),
            StringStruct('FileVersion', VERSION),
            StringStruct('InternalName', 'NEXAR'),
            StringStruct('LegalCopyright', 'IlSamm - github.com/IlSamm/NEXAR'),
            StringStruct('OriginalFilename', 'NEXAR.exe'),
            StringStruct('ProductName', 'NEXAR'),
            StringStruct('ProductVersion', VERSION)])]),
        VarFileInfo([VarStruct('Translation', [0x0410, 1200])]),
    ])

a = Analysis(
    ['desktop.py'],
    pathex=[],
    binaries=[],
    datas=[('web', 'web'), ('config.example.json', '.')] + collect_data_files('webview'),
    hiddenimports=['clr', 'webview.platforms.edgechromium', 'webview.platforms.winforms'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='NEXAR',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # UPX comprime l'exe come fanno molti malware: Defender lo segnalava come Trojan
    console=False,
    icon='icon.ico',
    version=version_info,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='NEXAR',
)
