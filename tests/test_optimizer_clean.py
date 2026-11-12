import optimizer

def test_quick_and_auto_clean_leave_game_shaders_alone():
    # Cancellare la cache degli shader fa scattare i giochi finché la ricostruiscono: solo a mano.
    assert 'shader' not in optimizer.SAFE_CLEAN
    shader = next(t for t in optimizer.targets() if t['key'] == 'shader')
    assert shader['optional'] and not shader.get('admin')
    assert {'temp', 'thumbs', 'crash', 'browser'} <= set(optimizer.SAFE_CLEAN)

def test_analysis_marks_optional_items(monkeypatch, tmp_path):
    monkeypatch.setattr(optimizer, 'targets', lambda: [
        {'key': 'temp', 'name': 'T', 'desc': '', 'paths': [tmp_path]},
        {'key': 'shader', 'name': 'S', 'desc': '', 'paths': [tmp_path], 'optional': True}])
    (tmp_path / 'a.bin').write_bytes(b'x' * 10)
    items = {i['key']: i for i in optimizer.analyze()['items']}
    assert items['shader']['optional'] and not items['temp']['optional']
    assert items['temp']['bytes'] == 10

def test_clean_removes_read_only_and_long_paths_and_reports_files_in_use(monkeypatch, tmp_path):
    import os, stat
    ro = tmp_path / 'git' / 'objects' / 'ab' / 'cdef'
    ro.parent.mkdir(parents=True); ro.write_bytes(b'x' * 7); os.chmod(ro, stat.S_IREAD)
    deep = tmp_path
    for i in range(12): deep = deep / ('cartella-molto-lunga-%02d' % i)
    os.makedirs(optimizer._long(deep))
    far = optimizer._long(deep / 'cache.bin')
    with open(far, 'wb') as f: f.write(b'y' * 5)
    assert len(far) > 260
    busy = tmp_path / 'aperto.tmp'; busy.write_bytes(b'z' * 3)
    monkeypatch.setattr(optimizer, 'targets', lambda: [{'key': 'temp', 'name': 'File temporanei', 'desc': '', 'paths': [tmp_path]}])
    held = open(busy, 'rb')
    try:
        if os.name == 'nt':  # su Windows un file aperto non si cancella
            res = optimizer.clean(['temp'])
            assert res['items']['temp'] == {'freed': 12, 'left': 1}
            assert res['notes'] == ['File temporanei: 1 file in uso (li usano programmi aperti)']
    finally:
        held.close()
    assert not ro.exists() and not os.path.exists(far)
    assert not (tmp_path / 'git').exists()  # cartelle rimaste vuote: via
    res = optimizer.clean(['temp'])
    assert res['notes'] == [] and not busy.exists()

def test_windows_update_cleanup_pauses_the_update_service():
    s = optimizer.admin_clean_script([r'C:\Windows\SoftwareDistribution\Download'])
    assert s.index('Stop-Service wuauserv') < s.index('Remove-Item') < s.index('Start-Service')
    assert 'Stop-Service' not in optimizer.admin_clean_script([r'C:\Windows\Temp'])

def test_rows_left_half_clean_say_why():
    rep = {'items': [{'key': 'shader', 'bytes': 9, 'note': ''}, {'key': 'temp', 'bytes': 0, 'note': ''},
                     {'key': 'browser', 'bytes': 5, 'note': 'chiudi Edge per pulirla'}]}
    optimizer.mark_left(rep, {'shader': {'freed': 1, 'left': 3}, 'temp': {'freed': 5, 'left': 0}, 'browser': {'freed': 0, 'left': 2}})
    assert rep['items'][0]['note'] == '3 file in uso: chiudi i giochi e riprova'
    assert rep['items'][1]['note'] == '' and rep['items'][2]['note'] == 'chiudi Edge per pulirla'

def test_process_list_has_no_nameless_entries():
    d = optimizer.processes()
    assert all(a['name'] and a['name'] != '?' for a in d['by_cpu'] + d['by_ram'])
