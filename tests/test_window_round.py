"""Angoli tondi della finestra: la forma copre solo l'area visibile e sparisce da ingrandita."""
import ast
from pathlib import Path

SRC = (Path(__file__).resolve().parent.parent / 'desktop.py').read_text(encoding='utf-8-sig')

def load(name):
    # desktop.py all'import avvia WebView2 e il controller: si prende solo la funzione pura.
    tree = ast.parse(SRC)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    radius = next(n for n in tree.body if isinstance(n, ast.Assign) and getattr(n.targets[0], 'id', '') == 'RADIUS')
    ns = {}
    exec(compile(ast.Module(body=[radius, fn], type_ignores=[]), 'desktop.py', 'exec'), ns)
    return ns[name], ns['RADIUS']

def test_region_covers_visible_area_only():
    rr, radius = load('round_region')
    # finestra a (200,120), area visibile a (208,120) 1185×773: i bordi invisibili restano fuori
    assert rr((200, 120), (208, 120, 1185, 773), False) == (8, 0, 1194, 774, radius * 2, radius * 2)

def test_region_scales_with_dpi_and_is_off_when_maximized():
    rr, radius = load('round_region')
    assert rr((0, 0), (0, 0, 800, 600), False, dpi=144)[4] == round(radius * 1.5) * 2
    assert rr((0, 0), (0, 0, 800, 600), True) is None
    assert rr((0, 0), (0, 0, 10, 10), False) is None   # ridotta a icona / dimensioni assurde
