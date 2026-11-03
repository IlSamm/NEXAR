"""Genera le immagini NEXAR da branding/: logo trasparente per l'app, icon.ico e banner per GitHub."""
from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'branding' / 'nexar-logo.webp'
BANNER = ROOT / 'branding' / 'nexar-banner.webp'

def unblack(img: Image.Image) -> Image.Image:
    """Il logo è luce su nero: alpha = luminosità massima, così il bagliore sfuma su qualsiasi sfondo scuro."""
    rgb = img.convert('RGB')
    out = Image.new('RGBA', rgb.size)
    out.putdata([(0, 0, 0, 0) if (a := max(p)) == 0 else (min(255, p[0] * 255 // a), min(255, p[1] * 255 // a), min(255, p[2] * 255 // a), a)
                 for p in rgb.getdata()])
    return out

def tile(logo: Image.Image, size=256) -> Image.Image:
    """Icona di Windows: logo su piastrella scura arrotondata, leggibile anche su barra delle applicazioni chiara."""
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    mask = Image.new('L', (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size - 1, size - 1), radius=size // 5, fill=255)
    img.paste(Image.new('RGBA', (size, size), (6, 10, 20, 255)), (0, 0), mask)
    inner = logo.resize((round(size * 0.92),) * 2, Image.LANCZOS)
    off = (size - inner.width) // 2
    img.alpha_composite(inner, (off, off))
    return img

if __name__ == '__main__':
    src = Image.open(SOURCE)
    side = min(src.size)
    src = src.crop(((src.width - side) // 2, (src.height - side) // 2, (src.width + side) // 2, (src.height + side) // 2))
    logo = unblack(src.resize((512, 512), Image.LANCZOS))
    logo.save(ROOT / 'web' / 'logo.png', optimize=True)
    tile(logo).save(ROOT / 'icon.ico', sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    tile(logo, 512).save(ROOT / 'web' / 'icon-512.png', optimize=True)
    Image.open(BANNER).convert('RGB').save(ROOT / 'docs' / 'banner.jpg', quality=90, optimize=True)
    print('web/logo.png, web/icon-512.png, icon.ico, docs/banner.jpg creati')
