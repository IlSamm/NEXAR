import os

import pytest

import unblock

@pytest.mark.skipif(os.name != 'nt', reason='i flussi Zone.Identifier esistono solo su NTFS')
def test_unblock_removes_internet_mark(tmp_path):
    sub = tmp_path / '_internal' / 'pythonnet' / 'runtime'
    sub.mkdir(parents=True)
    dll = sub / 'Python.Runtime.dll'
    dll.write_bytes(b'MZ')
    txt = tmp_path / 'leggimi.txt'
    txt.write_text('x')
    for f in (dll, txt):
        with open(str(f) + ':Zone.Identifier', 'w') as z:
            z.write('[ZoneTransfer]\nZoneId=3\n')
    assert unblock.unblock(tmp_path) == 1
    with pytest.raises(OSError):
        open(str(dll) + ':Zone.Identifier').close()
    assert dll.read_bytes() == b'MZ'
    # solo DLL ed eseguibili: il resto non si tocca
    open(str(txt) + ':Zone.Identifier').close()
    assert unblock.unblock(tmp_path) == 0

def test_unblock_app_only_in_exe():
    assert unblock.unblock_app() == 0
