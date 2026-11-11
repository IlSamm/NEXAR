"""FPS dei giochi da RivaTuner Statistics Server (RTSS, incluso con MSI Afterburner).

RTSS misura i frame di ogni gioco e li pubblica in una memoria condivisa ("RTSSSharedMemoryV2"):
NEXAR la legge in sola lettura, senza installare né iniettare niente.
Struttura dal suo SDK (SDK/Include/RTSSSharedMemory.h)."""
from __future__ import annotations
import os
import struct
from pathlib import Path

MAP_NAME = 'RTSSSharedMemoryV2'
SIGNATURE = 0x52545353          # 'RTSS': memoria pronta
MIN_VERSION = 0x00020000
NAME_LEN = 260                  # MAX_PATH
ENTRY_MIN = 4 + NAME_LEN + 5 * 4
MAX_APPS = 256


def parse(buf: bytes) -> dict:
    """Memoria di RTSS → {pid: {'fps', 'frametime_ms', 'exe'}} per i programmi che stanno disegnando frame."""
    if len(buf) < 20: return {}
    sig, ver, size, offset, count = struct.unpack_from('<5I', buf, 0)
    if sig != SIGNATURE or ver < MIN_VERSION or size < ENTRY_MIN or count > MAX_APPS: return {}
    out = {}
    for i in range(count):
        at = offset + i * size
        if at + ENTRY_MIN > len(buf): break
        pid = struct.unpack_from('<I', buf, at)[0]
        if not pid: continue
        name = buf[at + 4:at + 4 + NAME_LEN].split(b'\0', 1)[0].decode('mbcs' if os.name == 'nt' else 'latin-1', 'replace')
        _flags, t0, t1, frames, frametime = struct.unpack_from('<5I', buf, at + 4 + NAME_LEN)
        fps = 1000.0 * frames / (t1 - t0) if t0 and t1 > t0 and frames else (1e6 / frametime if frametime else 0.0)
        if 0 < fps < 2000:
            out[pid] = {'fps': round(fps, 1), 'frametime_ms': round(frametime / 1000, 2) if frametime else None, 'exe': name}
    return out


def read() -> dict:
    """Legge la memoria di RTSS; {} se RTSS non è aperto (o non siamo su Windows)."""
    if os.name != 'nt': return {}
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL('kernel32', use_last_error=True)
    k32.OpenFileMappingW.restype = wintypes.HANDLE
    k32.OpenFileMappingW.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR)
    k32.MapViewOfFile.restype = ctypes.c_void_p
    k32.MapViewOfFile.argtypes = (wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t)
    k32.UnmapViewOfFile.argtypes = (ctypes.c_void_p,)
    k32.CloseHandle.argtypes = (wintypes.HANDLE,)
    k32.VirtualQuery.argtypes = (ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t)

    class MBI(ctypes.Structure):
        _fields_ = [('BaseAddress', ctypes.c_void_p), ('AllocationBase', ctypes.c_void_p), ('AllocationProtect', wintypes.DWORD),
                    ('PartitionId', wintypes.WORD), ('RegionSize', ctypes.c_size_t), ('State', wintypes.DWORD),
                    ('Protect', wintypes.DWORD), ('Type', wintypes.DWORD)]

    handle = k32.OpenFileMappingW(0x0004, False, MAP_NAME)   # FILE_MAP_READ: solo lettura
    if not handle: return {}
    try:
        view = k32.MapViewOfFile(handle, 0x0004, 0, 0, 0)
        if not view: return {}
        try:
            mbi = MBI()
            if not k32.VirtualQuery(view, ctypes.byref(mbi), ctypes.sizeof(mbi)): return {}
            size = min(int(mbi.RegionSize), 8_000_000)      # mai oltre la memoria davvero mappata
            return parse(ctypes.string_at(view, size))
        finally:
            k32.UnmapViewOfFile(view)
    finally:
        k32.CloseHandle(handle)


def game_fps(pids, fallback_pid=None, reader=read):
    """FPS del gioco: il processo del gioco che RTSS sta misurando (quello con più FPS se sono più d'uno)."""
    try: apps = reader() or {}
    except Exception: return None
    hits = [apps[p]['fps'] for p in pids or () if p in apps]
    if not hits and fallback_pid in apps: hits = [apps[fallback_pid]['fps']]
    return max(hits) if hits else None


RTSS_PATHS = [Path(os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)')) / 'RivaTuner Statistics Server' / 'RTSS.exe',
              Path(os.environ.get('ProgramFiles', r'C:\Program Files')) / 'RivaTuner Statistics Server' / 'RTSS.exe']


def rtss_exe():
    return next((p for p in RTSS_PATHS if p.is_file()), None)


_status = {'at': 0.0, 'val': None}


def status() -> dict:
    """'on' se RTSS è aperto, 'closed' se è installato ma spento, 'missing' se non c'è (ricontrollato ogni 5 s)."""
    import time
    if _status['val'] and time.monotonic() - _status['at'] < 5: return dict(_status['val'])
    exe = rtss_exe()
    running = False
    try:
        import psutil
        running = any((p.info['name'] or '').lower() == 'rtss.exe' for p in psutil.process_iter(['name']))
    except Exception: pass
    val = {'state': 'on' if running else 'closed' if exe else 'missing'}
    _status.update(at=time.monotonic(), val=val)
    return dict(val)
