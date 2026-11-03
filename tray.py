"""Icona vicino all'orologio di Windows; avvia la stessa API del bot e di Umbrel."""
import os
import threading
import webbrowser

import pystray
from PIL import Image, ImageDraw
import uvicorn
import main


def icon_image():
    from core import ASSET_ROOT
    logo = ASSET_ROOT / 'web' / 'icon-512.png'
    if logo.is_file(): return Image.open(logo).convert('RGBA').resize((64, 64), Image.LANCZOS)
    image = Image.new('RGBA', (64,64), (5,20,35,255))
    draw=ImageDraw.Draw(image)
    draw.rounded_rectangle((5,6,59,58),radius=15,fill=(10,43,68),outline=(41,193,255),width=3)
    draw.line([(19,32),(29,42),(46,19)],fill=(30,235,171),width=6,joint='curve')
    return image


def run():
    port=int(main.config.get('web',{}).get('port',8765))
    host=main.config.get('web',{}).get('host','127.0.0.1')
    if host not in ('127.0.0.1','0.0.0.0'):
        raise RuntimeError('Host non sicuro')
    server=uvicorn.Server(uvicorn.Config(main.app,host=host,port=port,log_level='warning',access_log=False,log_config=None))
    thread=threading.Thread(target=server.run,daemon=True,name='NEXAR Agent')
    thread.start()

    def open_dashboard(icon,item):
        webbrowser.open(f'http://127.0.0.1:{port}')
    def select_mode(mode):
        def cb(icon,item):
            try: main.controller.set_mode(mode)
            except Exception as ex:
                from ctypes import windll
                windll.user32.MessageBoxW(0,str(ex),'NEXAR',0x10)
        return cb
    def quit_app(icon,item):
        server.should_exit=True
        icon.stop()
    menu=pystray.Menu(
        pystray.MenuItem('Apri dashboard',open_dashboard,default=True),
        pystray.MenuItem('🌙 Attiva AI ECO',select_mode('eco')),
        pystray.MenuItem('⚡ Modalità normale',select_mode('normal')),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem('Esci (ferma bot e dashboard)',quit_app),
    )
    tray=pystray.Icon('nexar',icon_image(),'NEXAR',menu)
    tray.run()
    server.should_exit=True
    thread.join(timeout=7)


if __name__ == '__main__':
    if os.name != 'nt':
        raise SystemExit('La tray Windows si esegue solo sul PC Windows.')
    run()
