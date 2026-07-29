"""
AC EVO car-mod (.kspkg) scanner.

A modded car ships as a .kspkg — the same archive format as the game's own
content.kspkg: a fixed-size file table at the END of the archive (0x4000000 or
0x2000000 bytes, depending on build), XOR'd with a static 8-byte key, made of
256-byte entries (name, flags, path hash, size, offset). Format reverse
-engineered from github.com/Nenkai/ACEvo.Package (MIT).

The critical, non-obvious fact this scanner exists to get right: the
selectable car identifier the game expects in cars.json / allowed_cars_list_full
is NOT the content folder name (e.g. "ks_honda_ci_1") — it's the MECHANICAL
PRESET stem inside that folder's presets/ directory (e.g.
"preset_modded_car_mech_1"). Confirmed empirically: every official car in
cars.json is keyed this way ("preset_zl1_mech_1", "preset_a290b_mech_1", ...),
and a real player join only succeeds when the manifest uses this preset stem,
not the folder name.

We read this straight from the archive's own file table (fast — a few KB to
megabytes, never the multi-hundred-MB content stream) rather than mining
embedded path references from decrypted content: some real-world mods never
embed such a reference anywhere (observed on a mod that still works in-game),
so the table is the only reliably-present source of truth.

Real distributed mods ship no sidecar [modded_car].json, so we never require
one — everything needed is inside the .kspkg itself.
"""
import json
import re
import struct
from io import BytesIO
from pathlib import Path

XOR_KEY = 0x9F9721A97D1135C1
FILE_TABLE_SIZES = (0x4_000_000, 0x2_000_000)
ENTRY_SIZE = 0x100
FLAG_IS_DIRECTORY = 1 << 0

_RE_PRESET_PATH = re.compile(
    r"^content\\cars\\([a-z0-9_]{2,64})\\presets\\(preset_[ -~]{1,60}?)\.(mechanical|visual)carpreset$",
    re.IGNORECASE,
)
_RE_SOURCE = re.compile(r"ACE_3D_Cars_Source\\[^\\]{1,40}\\([^\\]{2,60})\\", re.IGNORECASE)

# Le badge (logo de marque) d'un mod produit par le convertisseur générique
# "ks_modded_car" vit toujours à ce chemin, préfixé par le dossier de la voiture
# elle-même (ça exclut le logo générique de l'outil, ex: uiresources\branding\
# oem\evoforge\badge.texturemips, qui n'est PAS préfixé par content\cars\<car>\).
_RE_BADGE = re.compile(
    r"^content\\cars\\([a-z0-9_]{2,64})\\uiresources\\branding\\oem\\[^\\]{1,40}\\badge\.(texture|texturemips)$",
    re.IGNORECASE,
)


def _xor(data: bytes, key: int) -> bytes:
    n = len(data)
    full = (n // 8) * 8
    head = int.from_bytes(data[:full], "little") ^ int.from_bytes(
        key.to_bytes(8, "little") * (full // 8), "little"
    )
    out = bytearray(head.to_bytes(full, "little"))
    k = key
    for i in range(full, n):
        out.append(data[i] ^ (k & 0xFF))
        k >>= 8
    return bytes(out)


def _parse_entry(entry: bytes) -> tuple[str, int] | None:
    """Returns (name, flags) for one 256-byte table entry, or None past the
    last valid entry. Layout: name[0xE0] + unk0(i32) + flags(u16) + name_len(i16)
    at offset 0xE0, then path_hash/file_size/file_offset (unused here)."""
    _unk0, flags, name_len = struct.unpack_from("<iHh", entry, 0xE0)
    if not (0 < name_len <= 0xE0):
        return None
    try:
        name = entry[:name_len].decode("ascii")
    except UnicodeDecodeError:
        return None
    return name, flags


def _detect_table_size(f, length: int) -> int | None:
    for size in FILE_TABLE_SIZES:
        if size > length:
            continue
        f.seek(length - size)
        entry = _xor(f.read(ENTRY_SIZE), XOR_KEY)
        parsed = _parse_entry(entry)
        if parsed and parsed[0].lower().startswith("content\\"):
            return size
    return None


def prettify_name(car_name: str) -> str:
    s = re.sub(r"^(ks_|sd_|ac_)", "", car_name or "", flags=re.IGNORECASE).replace("_", " ").strip()
    if not s:
        s = car_name or ""
    words = []
    for w in s.split():
        if re.match(r"^[a-z]+\d", w, re.IGNORECASE) or len(w) <= 3:
            words.append(w.upper())
        else:
            words.append(w[:1].upper() + w[1:])
    return " ".join(words)


def _tokens_of(name: str) -> set[str]:
    name = re.sub(r"^(ks_|sd_|ac_)", "", (name or "").lower())
    return {t for t in re.split(r"[\s_\-]+", name) if len(t) >= 2 and not t.isdigit()}


def _best_display_name(car_name: str, source_models: set[str]) -> str:
    car_tokens = _tokens_of(car_name)
    best, best_score = None, 0
    for model in source_models:
        score = len(_tokens_of(model) & car_tokens)
        if score > best_score:
            best, best_score = model, score
    if best and best_score > 0:
        return best.replace("_", " ").strip()
    return prettify_name(car_name)


def scan_kspkg(file_path: str | Path) -> dict:
    """Scan one .kspkg's file table on disk. Returns a dict with 'ok' and
    either the scan result or an 'error' string."""
    path = Path(file_path)
    try:
        size_bytes = path.stat().st_size
    except OSError as e:
        return {"ok": False, "error": f"open failed: {e}"}

    is_common = lambda n: n == "common_assets" or n.startswith("common_")  # noqa: E731

    car_folders: set[str] = set()
    mech_by_car: dict[str, set[str]] = {}
    vis_by_car: dict[str, set[str]] = {}
    source_models: set[str] = set()

    try:
        with open(path, "rb") as f:
            table_size = _detect_table_size(f, size_bytes)
            if table_size is None:
                return {"ok": False, "error": "not a recognised .kspkg (no valid file table found)", "sizeBytes": size_bytes}

            f.seek(size_bytes - table_size)
            table = _xor(f.read(table_size), XOR_KEY)
            max_entries = table_size // ENTRY_SIZE
            for i in range(max_entries):
                entry = table[i * ENTRY_SIZE:(i + 1) * ENTRY_SIZE]
                parsed = _parse_entry(entry)
                if parsed is None:
                    break
                name, flags = parsed
                if flags & FLAG_IS_DIRECTORY:
                    continue

                m = _RE_PRESET_PATH.match(name)
                if m:
                    car = m.group(1).lower()
                    if not is_common(car):
                        car_folders.add(car)
                        target = mech_by_car if m.group(3).lower() == "mechanical" else vis_by_car
                        target.setdefault(car, set()).add(m.group(2))
                    continue

                sm = _RE_SOURCE.search(name)
                if sm:
                    source_models.add(sm.group(1))
                elif name.lower().startswith("content\\cars\\"):
                    parts = name.split("\\")
                    if len(parts) > 2 and not is_common(parts[2].lower()):
                        car_folders.add(parts[2].lower())
    except OSError as e:
        return {"ok": False, "error": f"read failed: {e}"}

    if not car_folders:
        return {"ok": False, "error": "no content\\cars\\<car> path found — not a recognised AC EVO car .kspkg", "sizeBytes": size_bytes}

    expected = path.name
    if expected.lower().endswith(".kspkg"):
        expected = expected[:-6]
    expected = expected.lower()

    cars_with_mech = list(mech_by_car.keys())
    if expected in cars_with_mech:
        car_name = expected
    elif len(cars_with_mech) == 1:
        car_name = cars_with_mech[0]
    elif len(cars_with_mech) > 1:
        car_name = sorted(cars_with_mech, key=lambda c: len(mech_by_car[c]), reverse=True)[0]
    elif expected in car_folders:
        car_name = expected
    else:
        car_name = sorted(car_folders)[0]

    mech_presets = sorted(mech_by_car.get(car_name, set()))
    if not mech_presets:
        return {"ok": False, "error": "no mechanical car preset found — cannot determine a selectable car id", "sizeBytes": size_bytes, "carName": car_name}

    display_name = _best_display_name(car_name, source_models)
    other_cars = sorted(c for c in car_folders if c != car_name)

    return {
        "ok": True,
        "carName": car_name,
        "displayName": display_name,
        "mechPresets": mech_presets,
        "variants": len(mech_presets),
        "visualPresets": sorted(vis_by_car.get(car_name, set())),
        "otherCarsReferenced": other_cars,
        "sizeBytes": size_bytes,
    }


# ── Badge (logo de marque) : fallback auto quand aucune image n'est fournie ──
# Réservé aux mods du convertisseur générique "ks_modded_car" (Honda/Nissan
# testés) : badge.texturemips au format RGBA8 brut, largeur réelle 128px malgré
# le descripteur qui annonce 256 (confirmé empiriquement par reverse engineering,
# pas documenté). Le contenu du .kspkg n'est PAS chiffré (seule la table de
# fichiers l'est) — lecture directe, aucun XOR. Ce n'est qu'un logo de marque
# (ex: le "H" Honda), pas une photo de la voiture précise : deux mods de la même
# marque partageront la même image. Best-effort total : la moindre incohérence
# (mauvais format, entrée absente, taille insuffisante) fait retourner None
# silencieusement plutôt que de risquer d'afficher une image corrompue.
_BADGE_W, _BADGE_H = 128, 128
_BADGE_RGBA_FORMAT = 9  # valeur du champ "format" du descripteur .texture observée sur Honda/Nissan


def _read_varint(buf: bytes, i: int) -> tuple[int, int]:
    result = shift = 0
    while True:
        b = buf[i]
        i += 1
        result |= (b & 0x7F) << shift
        if not (b & 0x80):
            return result, i
        shift += 7


def _texture_descriptor_format(descriptor: bytes) -> int | None:
    """Lit juste le champ protobuf 3 (format) d'un descripteur .texture."""
    i = 0
    try:
        while i < len(descriptor):
            tag, i = _read_varint(descriptor, i)
            field, wire = tag >> 3, tag & 7
            if wire == 0:
                val, i = _read_varint(descriptor, i)
                if field == 3:
                    return val
            elif wire == 2:
                ln, i = _read_varint(descriptor, i)
                i += ln
            else:
                return None
    except (IndexError, ValueError):
        return None
    return None


def _find_badge_files(path: Path, car_name: str) -> tuple[tuple[int, int], tuple[int, int]] | None:
    """Retourne ((offset, size) du .texture, (offset, size) du .texturemips) pour
    le badge de `car_name`, ou None si l'un des deux est absent."""
    try:
        size_bytes = path.stat().st_size
        with open(path, "rb") as f:
            table_size = _detect_table_size(f, size_bytes)
            if table_size is None:
                return None
            f.seek(size_bytes - table_size)
            table = _xor(f.read(table_size), XOR_KEY)
    except OSError:
        return None

    descriptor_loc = mips_loc = None
    max_entries = table_size // ENTRY_SIZE
    for i in range(max_entries):
        entry = table[i * ENTRY_SIZE:(i + 1) * ENTRY_SIZE]
        parsed = _parse_entry(entry)
        if parsed is None:
            break
        name, flags = parsed
        if flags & FLAG_IS_DIRECTORY:
            continue
        m = _RE_BADGE.match(name)
        if not m or m.group(1).lower() != car_name.lower():
            continue
        _path_hash, file_size, file_offset = struct.unpack_from("<QQQ", entry, 0xE8)
        if m.group(2).lower() == "texture":
            descriptor_loc = (file_offset, file_size)
        else:
            mips_loc = (file_offset, file_size)
    if descriptor_loc is None or mips_loc is None:
        return None
    return descriptor_loc, mips_loc


def extract_badge_png(kspkg_path: str | Path, car_name: str) -> bytes | None:
    """Best-effort : extrait le logo de marque du mod en PNG, ou None si quoi que
    ce soit ne correspond pas au format connu (mod d'un autre convertisseur,
    badge absent, etc.) — jamais d'exception propagée vers l'appelant."""
    try:
        path = Path(kspkg_path)
        found = _find_badge_files(path, car_name)
        if found is None:
            return None
        (desc_offset, desc_size), (mips_offset, mips_size) = found
        if desc_size <= 0 or desc_size > 4096:
            return None
        need = _BADGE_W * _BADGE_H * 4
        if mips_size < need:
            return None
        with open(path, "rb") as f:
            f.seek(desc_offset)
            descriptor = f.read(desc_size)
            fmt = _texture_descriptor_format(descriptor)
            if fmt != _BADGE_RGBA_FORMAT:
                return None
            f.seek(mips_offset)
            raw = f.read(need)
        if len(raw) < need:
            return None
        from PIL import Image
        img = Image.frombytes("RGBA", (_BADGE_W, _BADGE_H), raw)
        buf = BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        return None


# ── Bibliothèque de mods partagée (upload / listing / suppression) ──────────
# Un mod = un .kspkg dans MODS_DIR + un [nom].json sidecar auto-généré au même
# format que cars.json (voir server_config.load_mod_cars). Le sidecar est
# régénéré au listing s'il manque ou ne correspond plus au fichier — l'utilisateur
# n'a jamais à en écrire un à la main.

_SAFE_STEM_RE = re.compile(r"[^a-zA-Z0-9_-]")
_COVER_EXTS = (".jpg", ".jpeg", ".png", ".webp")


def _mods_dir() -> Path:
    from flask import current_app
    d = Path(current_app.config["MODS_DIR"])
    d.mkdir(parents=True, exist_ok=True)
    return d


def _manifest_for(kspkg_path: Path) -> dict:
    """One CarInfo entry (server_config / cars.json schema) per mechanical
    preset found — a package with several variants is several selectable
    cars sharing the same .kspkg content."""
    result = scan_kspkg(kspkg_path)
    if not result["ok"]:
        return result
    cars = [
        {
            "name": preset,
            "display_name": result["displayName"] if len(result["mechPresets"]) == 1
                else f'{result["displayName"]} ({i + 1}/{len(result["mechPresets"])})',
            "performance_indicator": 0.0,
            "property_1": 0,
            "property_2": 0,
            "property_3": 0,
            "is_mod": True,
        }
        for i, preset in enumerate(result["mechPresets"])
    ]
    return {"ok": True, "cars": cars, "scan": result}


def _write_manifest(json_path: Path, cars: list) -> None:
    json_path.write_text(json.dumps({"cars": cars}, indent=2, ensure_ascii=False), encoding="utf-8")


def _resolve_kspkg(filename: str) -> Path | None:
    """Validate `filename` as a plain basename inside MODS_DIR and return its
    path, or None if it doesn't exist / attempts path traversal."""
    if "/" in filename or "\\" in filename or not filename.lower().endswith(".kspkg"):
        return None
    mods_dir = _mods_dir()
    kspkg = mods_dir / filename
    if not kspkg.is_file() or kspkg.parent != mods_dir:
        return None
    return kspkg


def _find_cover(kspkg_path: Path) -> Path | None:
    for ext in _COVER_EXTS:
        p = kspkg_path.parent / f"{kspkg_path.stem}.cover{ext}"
        if p.exists():
            return p
    return None


def get_cover_path(filename: str) -> Path | None:
    """Resolve a mod's cover image path from its .kspkg filename, if any."""
    kspkg = _resolve_kspkg(filename)
    if kspkg is None:
        return None
    return _find_cover(kspkg)


def save_mod_cover(filename: str, file_storage, ext: str) -> dict:
    """Save/replace the cover image for an existing mod. `ext` must already be
    validated (allowed extension + magic bytes) by the caller."""
    kspkg = _resolve_kspkg(filename)
    if kspkg is None:
        return {"ok": False, "error": "mod introuvable"}
    existing = _find_cover(kspkg)
    if existing is not None:
        existing.unlink(missing_ok=True)
    dest = kspkg.parent / f"{kspkg.stem}.cover{ext}"
    file_storage.save(str(dest))
    return {"ok": True, "coverImage": dest.name}


def delete_mod_cover(filename: str) -> bool:
    kspkg = _resolve_kspkg(filename)
    if kspkg is None:
        return False
    existing = _find_cover(kspkg)
    if existing is None:
        return False
    existing.unlink()
    return True


def list_mods() -> list[dict]:
    """List every .kspkg in the shared mods library, self-healing the sidecar
    manifest (missing or car_name mismatch) as it goes."""
    mods_dir = _mods_dir()
    all_names: dict[str, list[str]] = {}   # car_name -> [kspkg filenames using it], for collision detection
    entries = []
    kspkg_files = sorted(mods_dir.glob("*.kspkg"))

    for kspkg in kspkg_files:
        json_path = kspkg.with_suffix(".json")
        manifest = None
        if json_path.exists():
            try:
                manifest = json.loads(json_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                manifest = None
        car_names_in_manifest = {c.get("name") for c in (manifest or {}).get("cars", [])} if manifest else set()

        result = scan_kspkg(kspkg)
        entry = {
            "filename": kspkg.name,
            "sizeBytes": kspkg.stat().st_size,
            "ok": result["ok"],
        }
        if not result["ok"]:
            entry["error"] = result["error"]
            entries.append(entry)
            continue

        expected_names = set(result["mechPresets"])
        if manifest is None or car_names_in_manifest != expected_names:
            built = _manifest_for(kspkg)
            _write_manifest(json_path, built["cars"])
            manifest = {"cars": built["cars"]}

        entry["displayName"] = result["displayName"]
        entry["carNames"] = result["mechPresets"]
        entry["variants"] = result["variants"]
        cover = _find_cover(kspkg)
        entry["coverImage"] = cover.name if cover else None
        entries.append(entry)
        for name in result["mechPresets"]:
            all_names.setdefault(name, []).append(kspkg.name)

    for entry in entries:
        if entry.get("ok"):
            entry["collisions"] = {
                name: [f for f in all_names[name] if f != entry["filename"]]
                for name in entry["carNames"] if len(all_names[name]) > 1
            }
    return entries


def save_uploaded_mod(file_storage, cover_file_storage=None, cover_ext: str | None = None) -> dict:
    """Save an uploaded .kspkg, scan it, and write its manifest. Returns a
    dict with 'ok' and either scan info (+ any car_name collision with an
    already-installed mod) or an 'error' string. Rolls back the saved file
    on any failure."""
    original_name = file_storage.filename or ""
    if not original_name.lower().endswith(".kspkg"):
        return {"ok": False, "error": "not a .kspkg file"}

    stem = _SAFE_STEM_RE.sub("_", Path(original_name).stem)[:64].strip("_") or "mod"
    mods_dir = _mods_dir()
    dest = mods_dir / f"{stem}.kspkg"
    suffix = 1
    while dest.exists():
        suffix += 1
        dest = mods_dir / f"{stem}_{suffix}.kspkg"

    file_storage.save(str(dest))
    result = scan_kspkg(dest)
    if not result["ok"]:
        dest.unlink(missing_ok=True)
        return result

    other_mods = [e for e in list_mods() if e.get("ok") and e["filename"] != dest.name]
    collisions = {
        name: [e["filename"] for e in other_mods if name in e["carNames"]]
        for name in result["mechPresets"]
    }
    collisions = {name: files for name, files in collisions.items() if files}

    built = _manifest_for(dest)
    _write_manifest(dest.with_suffix(".json"), built["cars"])

    cover_name = None
    if cover_file_storage is not None and cover_ext:
        cover_dest = dest.parent / f"{dest.stem}.cover{cover_ext}"
        cover_file_storage.save(str(cover_dest))
        cover_name = cover_dest.name
    else:
        # Pas d'image fournie à la main : on tente le fallback auto (logo de
        # marque extrait du .kspkg). Silencieux si le mod n'a pas ce format.
        badge_png = extract_badge_png(dest, result["carName"])
        if badge_png:
            cover_dest = dest.parent / f"{dest.stem}.cover.png"
            cover_dest.write_bytes(badge_png)
            cover_name = cover_dest.name

    return {
        "ok": True,
        "filename": dest.name,
        "coverImage": cover_name,
        "displayName": result["displayName"],
        "carNames": result["mechPresets"],
        "variants": result["variants"],
        "sizeBytes": result["sizeBytes"],
        "collisions": collisions,
    }


def delete_mod(filename: str) -> bool:
    """Remove a mod's .kspkg and sidecar .json from the shared library.
    `filename` must be an existing basename inside MODS_DIR (no path
    components) — validated by the caller against the real listing."""
    mods_dir = _mods_dir()
    if "/" in filename or "\\" in filename or not filename.lower().endswith(".kspkg"):
        return False
    kspkg = mods_dir / filename
    if not kspkg.is_file() or kspkg.parent != mods_dir:
        return False
    cover = _find_cover(kspkg)
    if cover is not None:
        cover.unlink(missing_ok=True)
    kspkg.unlink()
    kspkg.with_suffix(".json").unlink(missing_ok=True)
    return True
