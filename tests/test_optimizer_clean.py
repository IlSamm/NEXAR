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
