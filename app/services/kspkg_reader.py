"""
Lecture lazy du content.kspkg : noms de voitures et presets.

Accès via get_car_name() et get_preset_class(). Le premier appel scanne
le fichier kspkg (~343 MB) et met en cache les résultats. Thread-safe.
"""

import logging
import mmap
import os
import re
import struct
import threading
from typing import Optional

logger = logging.getLogger(__name__)

_XOR_KEY     = struct.pack('<Q', 0x9F9721A97D1135C1)
_XOR_KEY_INT = struct.unpack('<Q', _XOR_KEY)[0]
_TABLE_START = 0x11700000

_lock = threading.Lock()
_car_names: dict[str, str] = {}      # car_slug → display name
_preset_names: dict[str, str] = {}   # preset_slug → car display name
_preset_classes: dict[str, str] = {} # preset_slug → class label
_loaded = False

# Acronymes toujours en majuscules dans le fallback slug→nom
_ACRONYMS = {
    'amg', 'ap1', 'ae86', 'bop', 'csl', 'csr', 'cup',
    'exp', 'gr', 'gt', 'gt2', 'gt3', 'gt4', 'gta', 'gtm', 'gtr',
    'hf', 'lm', 'lms', 'mk1', 'mk8', 'mkiv', 'na', 'nd',
    'nsx', 'rs', 'sf', 'sto', 'zl1',
}


# ---------------------------------------------------------------------------
# Helpers binaires
# ---------------------------------------------------------------------------

def _xor(data: bytes) -> bytes:
    out = bytearray(len(data))
    view = memoryview(data)
    chunks = len(data) // 8
    for i in range(chunks):
        val = struct.unpack_from('<Q', view, i * 8)[0] ^ _XOR_KEY_INT
        struct.pack_into('<Q', out, i * 8, val)
    for j in range(chunks * 8, len(data)):
        out[j] = data[j] ^ _XOR_KEY[j % 8]
    return bytes(out)


def _read_varint(buf: bytes, pos: int) -> tuple[int, int]:
    r = s = 0
    while pos < len(buf):
        b = buf[pos]; pos += 1
        r |= (b & 0x7F) << s
        if not (b & 0x80):
            break
        s += 7
    return r, pos


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------

def _extract_car_name(data: bytes) -> Optional[str]:
    """Retourne le premier nom d'affichage ASCII lisible trouvé dans le .car."""
    found = re.findall(rb'[A-Za-z][A-Za-z0-9 \-.()' + b"'" + rb'&]+', data)
    for raw in found[:8]:
        try:
            s = raw.decode('ascii').strip()
            if len(s) >= 5 and ' ' in s and s[0].isupper() and '\\' not in s:
                return s
        except Exception:
            pass
    return None


def _extract_preset_strings(data: bytes) -> list[str]:
    """Extrait les champs string lisibles du protobuf d'un .mechanicalcarpreset."""
    result: list[str] = []
    pos = 0
    while pos < len(data) - 2:
        try:
            tag, pos = _read_varint(data, pos)
        except Exception:
            break
        wire = tag & 7
        if wire == 0:
            _, pos = _read_varint(data, pos)
        elif wire == 2:
            try:
                length, pos = _read_varint(data, pos)
            except Exception:
                break
            if length <= 0 or length > len(data) - pos:
                break
            val = data[pos:pos + length]
            pos += length
            if 3 <= length <= 100:
                try:
                    s = val.decode('utf-8').strip()
                    if s and re.match(r'^[\w\s\-\.\(\)\'\|&:,°%/]+$', s):
                        result.append(s)
                except Exception:
                    pass
        elif wire == 5:
            pos += 4
        elif wire == 1:
            pos += 8
        else:
            break
        if len(result) >= 5:
            break
    return result


# ---------------------------------------------------------------------------
# Chargement
# ---------------------------------------------------------------------------

def _build_index(mm: mmap.mmap) -> dict[str, dict]:
    index: dict[str, dict] = {}
    off = _TABLE_START
    empty = 0
    while off + 0x100 <= mm.size() and empty < 512:
        raw = mm[off:off + 0x100]
        dec = _xor(raw)
        raw_path = dec[0:0xE0].split(b'\x00')[0]
        if not raw_path:
            empty += 1
            off += 0x100
            continue
        empty = 0
        try:
            path = raw_path.decode('utf-8').replace('\\', '/')
            if not all(32 <= ord(c) < 128 for c in path):
                off += 0x100
                continue
        except Exception:
            off += 0x100
            continue
        flags     = struct.unpack_from('<H', dec, 0xE4)[0]
        file_size = struct.unpack_from('<Q', dec, 0xF0)[0]
        file_off  = struct.unpack_from('<Q', dec, 0xF8)[0]
        if not (flags & 0x01):
            index[path] = {
                'size':   file_size,
                'offset': file_off,
                'xor':    bool(flags & 0x100),
            }
        off += 0x100
    return index


def _read_entry(mm: mmap.mmap, entry: dict) -> bytes:
    raw = mm[entry['offset']:entry['offset'] + entry['size']]
    return _xor(raw) if entry['xor'] else raw


def _load() -> None:
    global _car_names, _preset_names, _preset_classes, _loaded
    kspkg_path = os.environ.get('KSPKG_PATH', '/aceserver/content.kspkg')
    if not os.path.exists(kspkg_path):
        logger.warning('kspkg_reader: %s introuvable, les noms de voitures seront générés depuis le slug', kspkg_path)
        _loaded = True
        return

    logger.info('kspkg_reader: chargement de %s', kspkg_path)
    fh = open(kspkg_path, 'rb')
    mm = mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ)
    try:
        index = _build_index(mm)

        # --- Noms de voitures ---
        car_files = [p for p in index if p.endswith('.car') and '/data/' in p]
        names: dict[str, str] = {}
        for path in car_files:
            slug = path.split('/')[2]
            if slug == 'dummycar':
                continue
            data = _read_entry(mm, index[path])
            name = _extract_car_name(data)
            if name:
                names[slug] = name
        _car_names = names

        # --- Presets ---
        p_names: dict[str, str] = {}
        p_classes: dict[str, str] = {}
        preset_files = [p for p in index if p.endswith('.mechanicalcarpreset')]
        for path in preset_files:
            preset_slug = path.rsplit('/', 1)[-1].replace('.mechanicalcarpreset', '')
            car_slug    = path.split('/')[2]
            car_name    = names.get(car_slug) or slug_to_name(car_slug)
            data        = _read_entry(mm, index[path])
            strs        = _extract_preset_strings(data)
            p_names[preset_slug]   = car_name
            p_classes[preset_slug] = strs[2] if len(strs) >= 3 else ''
        _preset_names   = p_names
        _preset_classes = p_classes

        logger.info('kspkg_reader: %d voitures, %d presets chargés', len(names), len(p_names))
    finally:
        mm.close()
        fh.close()
    _loaded = True


def _ensure_loaded() -> None:
    global _loaded
    if not _loaded:
        with _lock:
            if not _loaded:
                _load()


# ---------------------------------------------------------------------------
# API publique
# ---------------------------------------------------------------------------

def slug_to_name(slug: str) -> str:
    """Transforme un slug en nom lisible (fallback quand l'extraction échoue)."""
    name = slug.replace('ks_', '').replace('_', ' ')
    return ' '.join(
        w.upper() if w in _ACRONYMS else w.capitalize()
        for w in name.split()
    )


def get_car_name(slug: str) -> str:
    """
    Retourne le nom d'affichage pour un slug voiture ou preset.

    Essaie d'abord la table des presets (preset_slug), puis la table
    des voitures (car_slug), puis le fallback slug→nom.
    """
    _ensure_loaded()
    return (
        _preset_names.get(slug)
        or _car_names.get(slug)
        or slug_to_name(slug)
    )


def get_preset_class(slug: str) -> str:
    """
    Retourne le label de classe pour un preset slug.

    Exemples : 'Standard', 'GT3', 'BOP Carrera Cup', ''
    """
    _ensure_loaded()
    return _preset_classes.get(slug, '')
