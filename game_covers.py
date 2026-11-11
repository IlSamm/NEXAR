"""Copertine dei giochi.

In ordine: l'immagine scelta dall'utente, la cache di Steam già sul PC, le immagini ufficiali di Steam scaricate
una volta sola e tenute sul PC (anche per i giochi di Epic e GOG che esistono pure su Steam).
Da internet si chiede solo il nome del gioco al negozio di Steam e l'immagine pubblica: niente account, niente dati del PC.
"""
from __future__ import annotations
import base64
import io
import json
import os
import logging
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

KIND_FILES = {'capsule': ('library_600x900_2x.jpg', 'library_600x900.jpg'), 'header': ('header.jpg',),
              'hero': ('library_hero.jpg',), 'logo': ('logo.png',)}
CDNS = ('https://shared.cloudflare.steamstatic.com/store_item_assets/steam/apps/{id}/{f}',
        'https://cdn.cloudflare.steamstatic.com/steam/apps/{id}/{f}')
SEARCH = 'https://store.steampowered.com/api/storesearch/?term={q}&l=english&cc=US'
NO_MATCH = 7 * 86400      # gioco che su Steam non c'è (o immagine che manca): si riprova fra una settimana
NET_ERROR = 3600          # internet assente o Steam lento: si riprova fra un'ora
MAX_BYTES = 8_000_000
GID = re.compile(r'[a-z]+-[A-Za-z0-9_-]{1,70}')

_net = threading.Semaphore(3)


def _norm(name: str) -> str:
    return re.sub(r'[^a-z0-9]+', '', re.sub(r'[®™©]', '', str(name).lower()))


def _fetch(url: str):
    """Bytes della risposta, None se non c'è (404). Le altre eccezioni salgono: sono errori di rete."""
    req = urllib.request.Request(url, headers={'User-Agent': 'NEXAR'})
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            data = r.read(MAX_BYTES + 1)
            return data if len(data) <= MAX_BYTES else None
    except urllib.error.HTTPError as ex:
        if ex.code in (403, 404, 410): return None
        raise


def _image_ok(data: bytes) -> bool:
    try:
        from PIL import Image
        with Image.open(io.BytesIO(data)) as im:
            im.verify()
            return 32 <= im.size[0] <= 6000 and 32 <= im.size[1] <= 6000
    except Exception:
        return False


EPIC_CATALOG = Path(os.environ.get('PROGRAMDATA', r'C:\ProgramData')) / 'Epic' / 'EpicGamesLauncher' / 'Data' / 'Catalog' / 'catcache.bin'
EPIC_KINDS = {'capsule': ('DieselGameBoxTall', 'OfferImageTall'), 'header': ('DieselGameBox', 'OfferImageWide'),
              'hero': ('DieselGameBox', 'OfferImageWide'), 'logo': ('DieselGameBoxLogo',)}
EPIC_HOSTS = ('https://cdn1.epicgames.com/', 'https://cdn2.unrealengine.com/', 'https://cdn1.unrealengine.com/')
EPIC_WIDTH = {'capsule': 600, 'header': 1280, 'hero': 1920, 'logo': 800}
_epic = {'mtime': None, 'images': {}}
_epic_lock = threading.Lock()


def epic_catalog(path: Path = None):
    """id del catalogo Epic → immagini {tipo: url}. Il file del launcher è JSON in base64; si rilegge solo se cambia."""
    path = Path(path or EPIC_CATALOG)
    try: mtime = path.stat().st_mtime
    except OSError: return {}
    with _epic_lock:
        if _epic['mtime'] == (str(path), mtime): return _epic['images']
        images = {}
        try:
            items = json.loads(base64.b64decode(path.read_bytes()))
            for it in items if isinstance(items, list) else []:
                imgs = {k.get('type'): k.get('url') for k in it.get('keyImages') or [] if isinstance(k, dict) and k.get('url')}
                if it.get('id') and imgs: images[str(it['id'])] = imgs
        except (OSError, ValueError, TypeError) as ex:
            logging.info('Catalogo Epic non leggibile: %s', ex)
        _epic.update(mtime=(str(path), mtime), images=images)
        return images


def epic_image_urls(ids, kind, catalog=epic_catalog):
    """Indirizzi delle immagini ufficiali Epic per il gioco (prima ridimensionate dal loro server, poi originali)."""
    if not ids or kind not in EPIC_KINDS: return []
    images = catalog() or {}
    out = []
    for item in ids:
        imgs = images.get(str(item)) or {}
        for t in EPIC_KINDS[kind]:
            u = str(imgs.get(t) or '')
            if u.startswith(EPIC_HOSTS):
                u = u.replace(' ', '%20')
                out += [u + ('&' if '?' in u else '?') + f'resize=1&w={EPIC_WIDTH[kind]}', u]
        if out: break
    return out


def _shrink(data: bytes, kind: str) -> bytes:
    """Immagini scaricate: JPEG (o PNG per i loghi) di dimensioni ragionevoli, qualunque formato mandi il server."""
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(data)); im.load()
        limit = {'capsule': (900, 1350), 'header': (1280, 720), 'hero': (1920, 1080), 'logo': (1000, 500)}[kind]
        if kind != 'logo' and im.format == 'JPEG' and im.size[0] <= limit[0] and im.size[1] <= limit[1]: return data
        im.thumbnail(limit)
        buf = io.BytesIO()
        if kind == 'logo': im.convert('RGBA').save(buf, 'PNG')
        else: im.convert('RGB').save(buf, 'JPEG', quality=88)
        return buf.getvalue()
    except Exception:
        return data


class Covers:
    def __init__(self, folder: Path, online=lambda: True, fetch=None, local=None, epic=None):
        self.dir = Path(folder)
        self.online = online
        self.fetch = fetch or _fetch
        self.local = local            # (appid, kind) -> Path | None: cache di Steam sul PC
        self.epic_catalog = epic or epic_catalog
        self.lock = threading.Lock()
        self._meta = None

    # ---------- memoria di cosa è già stato cercato ----------
    def meta(self):
        with self.lock:
            if self._meta is None:
                try: self._meta = json.loads((self.dir / 'covers.json').read_text(encoding='utf-8'))
                except (OSError, ValueError): self._meta = {}
                self._meta.setdefault('appids', {}); self._meta.setdefault('miss', {})
            return self._meta

    def _remember(self, appids=None, miss=None):
        m = self.meta()
        with self.lock:
            m['appids'].update(appids or {}); m['miss'].update(miss or {})
            try:
                self.dir.mkdir(parents=True, exist_ok=True)
                (self.dir / 'covers.json').write_text(json.dumps(m), encoding='utf-8')
            except OSError: pass

    def _missed(self, key):
        miss = self.meta()['miss'].get(key)
        if not miss: return False
        at, wait = miss if isinstance(miss, list) else (miss, NO_MATCH)
        return time.time() - at < wait

    # ---------- copertina scelta dall'utente ----------
    def custom(self, gid: str) -> Path:
        if not GID.fullmatch(gid): raise ValueError('Gioco non valido')
        return self.dir / 'custom' / f'{gid}.jpg'

    def set_custom(self, gid: str, data: bytes):
        from PIL import Image, ImageOps
        dest = self.custom(gid)
        if not data or len(data) > 12_000_000: raise ValueError('Immagine troppo grande (massimo 12 MB)')
        try:
            im = Image.open(io.BytesIO(data)); im = ImageOps.exif_transpose(im); im.load()
        except Exception: raise ValueError('File non riconosciuto: scegli una foto JPG, PNG o WebP') from None
        if min(im.size) < 64: raise ValueError('Immagine troppo piccola')
        im = im.convert('RGB'); im.thumbnail((1400, 2100))
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix('.tmp'); im.save(tmp, 'JPEG', quality=88); tmp.replace(dest)
        return dest

    def remove_custom(self, gid: str) -> bool:
        p = self.custom(gid)
        if p.is_file(): p.unlink(); return True
        return False

    def version(self, gid: str) -> int:
        try: return int(self.custom(gid).stat().st_mtime)
        except (OSError, ValueError): return 0

    # ---------- Steam ----------
    def appid(self, game: dict):
        """Numero del gioco su Steam: dal suo id se è di Steam, altrimenti cercando il nome esatto nel negozio."""
        gid = game['id']
        m = re.fullmatch(r'steam-(\d{1,10})', gid)
        if m: return m.group(1)
        known = self.meta()['appids'].get(gid)
        if known is not None: return known or None
        if not self.online() or self._missed('search:' + gid): return None
        try:
            raw = self.fetch(SEARCH.format(q=urllib.parse.quote(str(game.get('name', ''))[:80])))
            items = (json.loads(raw or b'{}') or {}).get('items') or []
        except Exception as ex:
            logging.info('Copertina di %s: ricerca su Steam non riuscita (%s)', game.get('name'), ex)
            self._remember(miss={'search:' + gid: [time.time(), NET_ERROR]}); return None
        want = _norm(game.get('name', ''))
        found = next((str(i['id']) for i in items if i.get('id') and _norm(i.get('name', '')) == want), None)
        if found: self._remember(appids={gid: found})
        else: self._remember(miss={'search:' + gid: [time.time(), NO_MATCH]})
        return found

    def path(self, game: dict, kind: str):
        """File dell'immagine sul PC, scaricandolo la prima volta se serve. None se non c'è."""
        if kind not in KIND_FILES: return None
        gid = game['id']
        if kind != 'logo':
            c = self.custom(gid)
            if c.is_file(): return c
        if gid.startswith('steam-') and self.local:
            p = self.local(gid[6:], kind)
            if p: return p
        ext = '.png' if kind == 'logo' else '.jpg'
        dest = self.dir / f'{gid}_{kind}{ext}'
        if dest.is_file(): return dest
        key = f'{gid}/{kind}'
        if not self.online() or self._missed(key): return None
        data, err = None, False
        # Epic: le copertine ufficiali sono già elencate nel catalogo del launcher Epic sul PC.
        for url in epic_image_urls(game.get('epic'), kind, self.epic_catalog):
            try: data = self.fetch(url)
            except Exception: err, data = True, None
            if data and _image_ok(data): break
            data = None
        appid = None if data else self.appid(game)
        if appid:
            with _net:
                for f in KIND_FILES[kind]:
                    for cdn in CDNS:
                        try: data = self.fetch(cdn.format(id=appid, f=f))
                        except Exception: err, data = True, None
                        if data and _image_ok(data): break
                        data = None
                    if data: break
        if not data:
            self._remember(miss={key: [time.time(), NET_ERROR if err else NO_MATCH]}); return None
        data = _shrink(data, kind)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix('.tmp'); tmp.write_bytes(data); tmp.replace(dest)
        return dest
