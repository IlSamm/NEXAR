"""Toglie il segno "scaricato da Internet" dai file di NEXAR prima di aprire la finestra.

Quando lo zip viene scaricato col browser ed estratto con Esplora file, Windows marca ogni file
(flusso nascosto Zone.Identifier). .NET si rifiuta di caricare le DLL marcate e la finestra non parte:
"Failed to resolve Python.Runtime.Loader.Initialize". È lo stesso effetto di Proprietà → Sblocca,
fatto solo sui file della cartella dell'app.
"""
import os
import sys

EXT = ('.dll', '.exe', '.pyd')

def unblock(root):
    """Rimuove Zone.Identifier da DLL ed eseguibili sotto root; restituisce quanti ne ha sbloccati."""
    n = 0
    for dirpath, _, files in os.walk(root):
        for f in files:
            if not f.lower().endswith(EXT):
                continue
            try:
                os.remove(os.path.join(dirpath, f) + ':Zone.Identifier')
                n += 1
            except OSError:
                pass
    return n

def unblock_app():
    """Solo nell'exe su Windows: sblocca la cartella dell'app (exe e _internal)."""
    if os.name != 'nt' or not getattr(sys, 'frozen', False):
        return 0
    try:
        return unblock(os.path.dirname(sys.executable))
    except Exception:
        return 0
