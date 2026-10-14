"""
Parse et importe les fichiers de résultats générés par AssettoCorsaEVOServer.

Format ACE EVO — champs clés :
  drivers[]       : guid {a,b} → first_name, last_name, nickname, player_id, nation
  cars[]          : car_id {a,b} → model_displayname, race_number
  laps[]          : driver_key {a,b}, car_key {a,b}, time (ms), split [ms,ms,ms], flags
  time_standings  : meilleur temps officiel par pilote (même ordre que driver_standings)
  driver_standings: liste de guids ordonnée par classement
  car_standings[] : total_km, total_fuel_liters, starting_position

Interprétation des flags de tour (confirmée par observation des données) :
  flags == 2  : tour propre, officiellement chronométré
  flags < 64  : tour conduit avec une note (coupure légère, avertissement) — affiché avec ⚠
  flags >= 64 : tour invalide ou hors-session (out-lap, crash) — affiché en grisé
"""
import hashlib
import json
import logging
from collections import defaultdict, OrderedDict
from datetime import timedelta
from pathlib import Path

log = logging.getLogger(__name__)

## Aligné sur le plus gros scan existant (leaderboard.py::_collect_best_by_track, jusqu'à 2000
# lignes) : un cache plus petit que le scan réévince en boucle et re-parse à chaque hit.
_MAX_PARSE_CACHE = 2000
_parse_cache: OrderedDict[int, dict] = OrderedDict()


def get_parsed(session_result) -> dict:
    """Retourne le résultat parsé depuis le cache (LRU), ou le parse."""
    rid = session_result.id
    if rid in _parse_cache:
        _parse_cache.move_to_end(rid)
        return _parse_cache[rid]
    result = parse_result_file(json.loads(session_result.raw_json))
    _parse_cache[rid] = result
    if len(_parse_cache) > _MAX_PARSE_CACHE:
        _parse_cache.popitem(last=False)
    return result

# ISO 3166-1 alpha-3 → alpha-2 pour les codes nation ACE EVO
_NATION3_TO_2 = {
    "AFG":"AF","ALB":"AL","ALG":"DZ","AND":"AD","AGO":"AO","ARG":"AR","ARM":"AM",
    "AUS":"AU","AUT":"AT","AZE":"AZ","BHR":"BH","BAN":"BD","BLR":"BY","BEL":"BE",
    "BLZ":"BZ","BEN":"BJ","BTN":"BT","BOL":"BO","BIH":"BA","BWA":"BW","BRA":"BR",
    "BRN":"BN","BUL":"BG","BFA":"BF","BDI":"BI","CPV":"CV","CAM":"KH","CMR":"CM",
    "CAN":"CA","CAF":"CF","CHA":"TD","CHI":"CL","CHN":"CN","COL":"CO","COM":"KM",
    "COD":"CD","COG":"CG","CRC":"CR","CIV":"CI","CRO":"HR","CUB":"CU","CYP":"CY",
    "CZE":"CZ","DEN":"DK","DJI":"DJ","DOM":"DO","ECU":"EC","EGY":"EG","ESA":"SV",
    "GEQ":"GQ","ERI":"ER","EST":"EE","ETH":"ET","FIJ":"FJ","FIN":"FI","FRA":"FR",
    "GAB":"GA","GAM":"GM","GEO":"GE","GER":"DE","DEU":"DE","GHA":"GH","GRE":"GR",
    "GRN":"GD","GUA":"GT","GUI":"GN","GBS":"GW","GUY":"GY","HAI":"HT","HON":"HN",
    "HKG":"HK","HUN":"HU","ISL":"IS","IND":"IN","INA":"ID","IRN":"IR","IRQ":"IQ",
    "IRL":"IE","ISR":"IL","ITA":"IT","JAM":"JM","JPN":"JP","JOR":"JO","KAZ":"KZ",
    "KEN":"KE","PRK":"KP","KOR":"KR","KUW":"KW","KGZ":"KG","LAO":"LA","LAT":"LV",
    "LIB":"LB","LES":"LS","LBR":"LR","LBA":"LY","LIE":"LI","LTU":"LT","LUX":"LU",
    "MAD":"MG","MAW":"MW","MAS":"MY","MDV":"MV","MLI":"ML","MLT":"MT","MTN":"MR",
    "MRI":"MU","MEX":"MX","MDA":"MD","MON":"MC","MNG":"MN","MNE":"ME","MAR":"MA",
    "MOZ":"MZ","MYA":"MM","NAM":"NA","NEP":"NP","NED":"NL","NLD":"NL","NZL":"NZ","NCA":"NI",
    "NIG":"NE","NGR":"NG","MKD":"MK","NOR":"NO","OMA":"OM","PAK":"PK","PLE":"PS",
    "PAN":"PA","PNG":"PG","PAR":"PY","PER":"PE","PHI":"PH","POL":"PL","POR":"PT",
    "PRT":"PT","PUR":"PR","QAT":"QA","ROU":"RO","RUS":"RU","RWA":"RW","SKN":"KN",
    "LCA":"LC","VIN":"VC","SAM":"WS","SMR":"SM","STP":"ST","KSA":"SA","SEN":"SN",
    "SRB":"RS","SEY":"SC","SLE":"SL","SGP":"SG","SVK":"SK","SLO":"SI","SVN":"SI",
    "SOL":"SB","SOM":"SO","RSA":"ZA","ZAF":"ZA","SSD":"SS","ESP":"ES","SRI":"LK",
    "SUD":"SD","SUR":"SR","SWZ":"SZ","SWE":"SE","SUI":"CH","CHE":"CH","SYR":"SY",
    "TPE":"TW","TJK":"TJ","TAN":"TZ","THA":"TH","TLS":"TL","TOG":"TG","TGA":"TO",
    "TRI":"TT","TUN":"TN","TUR":"TR","TKM":"TM","UGA":"UG","UKR":"UA","UAE":"AE",
    "GBR":"GB","USA":"US","URU":"UY","UZB":"UZ","VAN":"VU","VEN":"VE","VIE":"VN",
    "YEM":"YE","ZAM":"ZM","ZIM":"ZW",
}


def _nation_flag(code3: str) -> str:
    """Convertit un code nation 3 lettres en emoji drapeau (ex: FRA → 🇫🇷)."""
    if not code3:
        return ""
    code2 = _NATION3_TO_2.get(code3.upper(), "")
    if not code2 or len(code2) != 2:
        return ""
    return chr(0x1F1E6 + ord(code2[0]) - ord("A")) + chr(0x1F1E6 + ord(code2[1]) - ord("A"))


def _ms_to_laptime(ms: int) -> str:
    if not ms:
        return "—"
    minutes, rem = divmod(ms, 60_000)
    seconds, millis = divmod(rem, 1_000)
    return f"{minutes}:{seconds:02d}.{millis:03d}"


def _ms_to_delta(ms: int) -> str:
    """Formatte un écart en millisecondes → '+X.XXX' ou '+M:SS.mmm'."""
    if ms <= 0:
        return "—"
    minutes, rem = divmod(ms, 60_000)
    seconds, millis = divmod(rem, 1_000)
    if minutes:
        return f"+{minutes}:{seconds:02d}.{millis:03d}"
    return f"+{seconds}.{millis:03d}"


def _guid_key(g: dict) -> tuple:
    return (str(g.get("a", "")), str(g.get("b", "")))


def _lap_is_clean(flags: int) -> bool:
    """Tour propre officiel selon le serveur ACE EVO."""
    return flags == 2


def _lap_is_invalid(flags: int) -> bool:
    """Tour invalide (out-lap, crash, hors-piste sévère)."""
    return flags >= 64


def _lap_is_formation(flags: int) -> bool:
    """Tour de formation / tour de mise en grille (bit 7 = 128 activé)."""
    return bool(flags & 128)



# ── Incidents (collisions) et sanctions ──────────────────────────────────────
# Ces données sont dans tous les fichiers de résultats du serveur mais n'étaient
# pas exploitées. Format observé (200 fichiers réels, juin–octobre 2026) :
#   collisions[]        : server_timestamp (ms, horloge serveur), car_id, collider
#                         ("Wall" | "Car" | "Object"), has_damage, relative_impact_kmh,
#                         world_pos {x,y,z}. local_timestamp = horloge du CLIENT qui a
#                         rapporté le choc : ne sert pas à comparer deux voitures.
#   penalty_collection  : {"session_penalties": [{car_id, pending_penalties[],
#                         cleared_penalties[{penalty_data{type, penalty_time_ms,
#                         laps_for_clearing}, investigation, given_lap_count,
#                         given_session_time_ms (chaîne), cleared_session_time_ms}]}]}
# Deux voitures qui se touchent produisent deux enregistrements « Car » quasi
# simultanés (un par voiture) : on les apparie pour compter un contact, pas deux.

_CLUSTER_WINDOW_MS = 1000   # écart max entre deux enregistrements d'un même contact
_CLUSTER_DISTANCE_M = 15.0  # distance max entre leurs positions dans le monde
_BIG_IMPACT_KMH = 30.0      # seuil d'un « gros choc » mur / objet
# Sanctions lourdes (hors avertissements et secondes) : comptées à part pour le fair-play
SEVERE_PENALTIES = frozenset({"PenaltyType_Disqualification", "PenaltyType_Drive_Through",
                              "PenaltyType_Stop_And_Go"})


def _empty_incident_stats() -> dict:
    return {"total": 0, "wall": 0, "car": 0, "object": 0, "damage": 0,
            "max_impact_kmh": 0.0, "per_lap": 0.0}


def _to_int(value) -> int:
    """Les durées sont parfois des chaînes (uint64 sérialisé en JSON)."""
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _car_to_driver_map(data: dict) -> dict:
    """car_key → driver_key, déduit des tours ; repli par index pour les voitures sans tour."""
    mapping: dict = {}
    for lap in data.get("laps", []):
        try:
            mapping[_guid_key(lap["car_key"])] = _guid_key(lap["driver_key"])
        except KeyError:
            continue
    cs = data.get("car_standings", [])
    ds = data.get("driver_standings", [])
    for i, entry in enumerate(cs):
        ck = _guid_key(entry.get("car_id", {}))
        if ck not in mapping and i < len(ds):
            mapping[ck] = _guid_key(ds[i])
    return mapping


def _cluster_car_contacts(car_hits: list) -> list:
    """Regroupe les enregistrements « Car » en événements de contact.

    Un frottement produit plusieurs enregistrements, rapportés par une ou deux voitures :
    on relie deux enregistrements proches dans le temps (_CLUSTER_WINDOW_MS) et l'espace
    (_CLUSTER_DISTANCE_M), puis chaque groupe connexe est un contact. Retourne une liste de
    listes d'enregistrements, triée par instant."""
    hits = sorted(car_hits, key=lambda h: h["ts"])
    parent = list(range(len(hits)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, a in enumerate(hits):
        for j in range(i + 1, len(hits)):
            b = hits[j]
            if b["ts"] - a["ts"] > _CLUSTER_WINDOW_MS:
                break
            dx, dy, dz = (a["pos"][k] - b["pos"][k] for k in range(3))
            if (dx * dx + dy * dy + dz * dz) ** 0.5 <= _CLUSTER_DISTANCE_M:
                parent[find(j)] = find(i)

    groups: dict[int, list] = defaultdict(list)
    for i, h in enumerate(hits):
        groups[find(i)].append(h)
    return sorted(groups.values(), key=lambda g: g[0]["ts"])


def _driver_incident_stats(stats: dict, driver_key: tuple, lap_count: int) -> dict:
    st = dict(stats.get(driver_key) or _empty_incident_stats())
    st["per_lap"] = round(st["total"] / lap_count, 2) if lap_count else 0.0
    return st


def build_incidents(data: dict, driver_map: dict, car_map: dict) -> dict:
    """Extrait incidents et sanctions d'un fichier de résultats.

    Retourne {"stats": {driver_key: stats}, "contacts": [...], "big_hits": [...],
              "penalties": [...]} — toutes les clés présentes même sans donnée."""
    car_driver = _car_to_driver_map(data)

    def who(car_key: tuple) -> dict:
        dk = car_driver.get(car_key)
        d = driver_map.get(dk, {}) if dk else {}
        c = car_map.get(car_key, {})
        nick = d.get("nickname") or f"{d.get('first_name', '')} {d.get('last_name', '')}".strip()
        return {"driver_key": dk, "nickname": nick or "?", "race_number": c.get("race_number", 0),
                "car": c.get("model_displayname", "")}

    stats: dict = defaultdict(_empty_incident_stats)
    car_hits, big_hits = [], []
    for col in data.get("collisions", []) or []:
        try:
            ck = _guid_key(col["car_id"])
        except KeyError:
            continue
        kind = (col.get("collider") or "").lower()
        impact = float(col.get("relative_impact_kmh") or 0.0)
        damage = bool(col.get("has_damage"))
        person = who(ck)
        st = stats[person["driver_key"] or ck]
        if kind in ("wall", "object"):      # les contacts « car » sont comptés après regroupement
            st[kind] += 1
        if damage:
            st["damage"] += 1
        st["max_impact_kmh"] = max(st["max_impact_kmh"], impact)
        pos = col.get("world_pos") or {}
        if kind == "car":
            car_hits.append({"ts": float(col.get("server_timestamp") or 0.0), "car": ck,
                             "impact": impact, "damage": damage,
                             "pos": (float(pos.get("x", 0)), float(pos.get("y", 0)), float(pos.get("z", 0)))})
        elif impact >= _BIG_IMPACT_KMH:
            big_hits.append({**person, "kind": kind, "impact_kmh": impact, "damage": damage,
                             "ts": float(col.get("server_timestamp") or 0.0)})

    contacts = []
    for group in _cluster_car_contacts(car_hits):
        cars = []
        for h in group:
            if h["car"] not in cars:
                cars.append(h["car"])
        people = [who(ck) for ck in cars]
        for ck in cars:           # un contact compte une fois pour chaque voiture impliquée
            stats[who(ck)["driver_key"] or ck]["car"] += 1
        contacts.append({"ts": group[0]["ts"], "drivers": people, "hits": len(group),
                         "impact_kmh": max(h["impact"] for h in group),
                         "damage": any(h["damage"] for h in group)})
    big_hits.sort(key=lambda h: h["impact_kmh"], reverse=True)

    # Sanctions
    penalties = []
    pc = data.get("penalty_collection") or {}
    for entry in pc.get("session_penalties", []) or []:
        try:
            ck = _guid_key(entry["car_id"])
        except KeyError:
            continue
        person = who(ck)
        for status, key in (("pending", "pending_penalties"), ("cleared", "cleared_penalties")):
            for pen in entry.get(key, []) or []:
                pd = pen.get("penalty_data", {}) or {}
                penalties.append({
                    **person,
                    "status": status,
                    "type": pd.get("type", ""),
                    "time_ms": _to_int(pd.get("penalty_time_ms")),
                    "laps": _to_int(pd.get("laps_for_clearing")),
                    "investigation": pen.get("investigation", ""),
                    "lap": _to_int(pen.get("given_lap_count")),
                    "given_ms": _to_int(pen.get("given_session_time_ms")),
                })
    penalties.sort(key=lambda p: (p["given_ms"], p["nickname"]))

    for st in stats.values():
        st["total"] = st["wall"] + st["object"] + st["car"]
    return {"stats": dict(stats), "contacts": contacts, "big_hits": big_hits, "penalties": penalties}


def parse_result_file(data: dict) -> dict:
    """Transforme le JSON brut ACE EVO en dict structuré prêt à afficher."""
    session_type = data.get("session_type", "")
    is_race      = session_type.lower() == "race"

    driver_map  = {_guid_key(d["guid"]): d for d in data.get("drivers", [])}
    car_map     = {_guid_key(c["car_id"]): c for c in data.get("cars", [])}
    car_standings_map = {
        _guid_key(cs["car_id"]): cs
        for cs in data.get("car_standings", [])
    }

    # Regrouper les tours par pilote
    driver_laps: dict[tuple, list] = defaultdict(list)
    for lap in data.get("laps", []):
        dk = _guid_key(lap["driver_key"])
        driver_laps[dk].append(lap)

    # ── Stats de session globales ─────────────────────────────────────────────
    # Tours de référence pour les stats de session :
    # • Practice/Qualify/WarmUp : tours propres (flags==2)
    # • Race : tous tours de course hors formation (flags bit7==0), time > 0
    if is_race:
        all_ref_laps = [
            lap for lap in data.get("laps", [])
            if not _lap_is_formation(lap.get("flags", 0)) and lap.get("time", 0) > 0
        ]
    else:
        all_ref_laps = [
            lap for lap in data.get("laps", [])
            if _lap_is_clean(lap.get("flags", 0)) and lap.get("time", 0) > 0
        ]

    session_best_ms = min((l["time"] for l in all_ref_laps), default=0)

    session_best_splits_ms: list[int] = []
    if all_ref_laps:
        n_splits = max((len(l.get("split", [])) for l in all_ref_laps), default=0)
        for s in range(n_splits):
            candidates = [
                l["split"][s] for l in all_ref_laps
                if len(l.get("split", [])) > s and l["split"][s] > 0
            ]
            session_best_splits_ms.append(min(candidates) if candidates else 0)

    # ── Incidents et sanctions ────────────────────────────────────────────────
    incidents = build_incidents(data, driver_map, car_map)

    # ── Classement pilotes ────────────────────────────────────────────────────
    standings = []
    for idx, guid_dict in enumerate(data.get("driver_standings", [])):
        dk     = _guid_key(guid_dict)
        driver = driver_map.get(dk, {})
        laps   = driver_laps.get(dk, [])

        time_std    = data.get("time_standings", [])
        time_std_ms = time_std[idx] if idx < len(time_std) else 0

        if is_race:
            # En course : time_standings = temps total de course
            race_time_ms   = time_std_ms
            race_laps      = [l for l in laps if not _lap_is_formation(l.get("flags", 0)) and l["time"] > 0]
            fastest_lap_ms = min((l["time"] for l in race_laps), default=0)
            fastest_lap_obj = next((l for l in race_laps if l["time"] == fastest_lap_ms and fastest_lap_ms > 0), None)
            best_splits_ms = fastest_lap_obj["split"] if fastest_lap_obj else []
            # best_ms sert à la détection is_drv_best dans les tours
            best_ms        = fastest_lap_ms
        else:
            # Practice/Qualify/WarmUp : time_standings = best lap
            race_time_ms   = 0
            race_laps      = []
            best_ms        = time_std_ms
            if not best_ms and laps:
                clean = [l["time"] for l in laps if _lap_is_clean(l.get("flags", 0)) and l["time"] > 0]
                best_ms = min(clean) if clean else 0
            best_lap_obj   = next((l for l in laps if l["time"] == best_ms and best_ms > 0), None)
            best_splits_ms = best_lap_obj["split"] if best_lap_obj else []
            fastest_lap_ms = best_ms

        # Voiture depuis le meilleur tour (ou fallback par index)
        car = {}
        car_stats = {}
        ref_lap = (fastest_lap_obj if is_race else None) or next(
            (l for l in laps if l["time"] == best_ms and best_ms > 0), None
        )
        if ref_lap:
            ck        = _guid_key(ref_lap["car_key"])
            car       = car_map.get(ck, {})
            car_stats = car_standings_map.get(ck, {})
        if not car_stats and idx < len(data.get("car_standings", [])):
            car_stats = data["car_standings"][idx]
            if not car and car_stats:
                ck2 = _guid_key(car_stats.get("car_id", {}))
                car = car_map.get(ck2, {})

        # Tours propres (pour stats hors course) et secteurs perso
        driver_clean_laps = [l for l in laps if _lap_is_clean(l.get("flags", 0)) and l["time"] > 0]
        ref_laps_for_splits = race_laps if is_race else driver_clean_laps
        driver_best_splits_ms: list[int] = []
        if ref_laps_for_splits:
            n_s = max((len(l.get("split", [])) for l in ref_laps_for_splits), default=0)
            for s in range(n_s):
                cands = [
                    l["split"][s] for l in ref_laps_for_splits
                    if len(l.get("split", [])) > s and l["split"][s] > 0
                ]
                driver_best_splits_ms.append(min(cands) if cands else 0)

        # Constance : écart-type sur tours de référence (min 2 tours)
        consistency_ms = 0
        if len(ref_laps_for_splits) >= 2:
            times    = [l["time"] for l in ref_laps_for_splits]
            avg      = sum(times) / len(times)
            variance = sum((t - avg) ** 2 for t in times) / len(times)
            consistency_ms = int(variance ** 0.5)

        # Tous les tours enrichis
        all_laps_enriched = []
        for i, l in enumerate(laps):
            flags       = l.get("flags", 0)
            lap_ms      = l["time"]
            splits_ms   = l.get("split", [])
            is_clean    = _lap_is_clean(flags)
            is_invalid  = _lap_is_invalid(flags)
            is_formation = _lap_is_formation(flags)
            is_drv_best  = (lap_ms == best_ms and best_ms > 0 and not is_formation)
            is_sess_best = (lap_ms == session_best_ms and session_best_ms > 0
                            and (is_clean if not is_race else not is_formation))

            splits_enriched = []
            for s_idx, s_ms in enumerate(splits_ms):
                drv_best_s  = driver_best_splits_ms[s_idx] if s_idx < len(driver_best_splits_ms) else 0
                sess_best_s = session_best_splits_ms[s_idx] if s_idx < len(session_best_splits_ms) else 0
                splits_enriched.append({
                    "time":         _ms_to_laptime(s_ms),
                    "time_ms":      s_ms,
                    "is_drv_best":  drv_best_s > 0 and s_ms == drv_best_s,
                    "is_sess_best": sess_best_s > 0 and s_ms == sess_best_s,
                })

            delta_ms = (lap_ms - best_ms) if (best_ms > 0 and lap_ms > 0
                                               and not is_invalid and not is_formation) else 0
            all_laps_enriched.append({
                "lap":          i + 1,
                "time":         _ms_to_laptime(lap_ms),
                "time_ms":      lap_ms,
                "splits":       splits_enriched,
                "flags":        flags,
                "is_clean":     is_clean,
                "is_invalid":   is_invalid,
                "is_formation": is_formation,
                "is_drv_best":  is_drv_best,
                "is_sess_best": is_sess_best,
                "delta":        _ms_to_delta(delta_ms) if not is_drv_best else "ref",
                "delta_ms":     delta_ms,
            })

        nation_code = driver.get("nation", "")
        standings.append({
            "position":              idx + 1,
            "nickname":              driver.get("nickname") or f"{driver.get('first_name','')} {driver.get('last_name','')}".strip(),
            "full_name":             f"{driver.get('first_name','')} {driver.get('last_name','')}".strip(),
            "nation":                nation_code,
            "nation_flag":           _nation_flag(nation_code),
            "player_id":             driver.get("player_id", ""),
            "starting_position":     car_stats.get("starting_position", 0),
            "car":                   car.get("model_displayname", ""),
            "race_number":           car.get("race_number", 0),
            # Course
            "race_time_ms":          race_time_ms,
            "race_time":             _ms_to_laptime(race_time_ms) if race_time_ms else "—",
            "race_laps_count":       len(race_laps),
            "fastest_lap_ms":        fastest_lap_ms,
            "fastest_lap":           _ms_to_laptime(fastest_lap_ms),
            "is_fastest_lap":        fastest_lap_ms > 0 and fastest_lap_ms == session_best_ms,
            # Practice/Qualify (et fastest lap en course)
            "laps_count":            len(laps),
            "clean_laps_count":      len(driver_clean_laps),
            "best_lap_ms":           best_ms,
            "best_lap":              _ms_to_laptime(best_ms),
            "best_splits_ms":        best_splits_ms,
            "best_splits":           [_ms_to_laptime(s) for s in best_splits_ms],
            "driver_best_splits_ms": driver_best_splits_ms,
            "is_session_fastest":    (best_ms == session_best_ms and session_best_ms > 0),
            "consistency_ms":        consistency_ms,
            "consistency":           _ms_to_laptime(consistency_ms) if consistency_ms else "—",
            "total_km":              car_stats.get("total_km", 0),
            "incident_stats":        _driver_incident_stats(incidents["stats"], dk, len(laps)),
            "penalty_count":         sum(1 for p in incidents["penalties"] if p["driver_key"] == dk),
            "severe_penalty_count":  sum(1 for p in incidents["penalties"]
                                         if p["driver_key"] == dk and p["type"] in SEVERE_PENALTIES),
            "gap_ms":                0,
            "gap":                   "—",
            "gap_laps":              0,
            "all_laps":              all_laps_enriched,
        })

    # ── Gaps ─────────────────────────────────────────────────────────────────
    if standings:
        p1 = standings[0]
        if is_race:
            p1_laps = p1["race_laps_count"]
            p1_time = p1["race_time_ms"]
            for drv in standings:
                if drv["position"] == 1:
                    drv["gap_ms"] = 0
                    drv["gap"]    = "—"
                    drv["gap_laps"] = 0
                elif not drv["race_time_ms"]:
                    drv["gap"] = "—"
                else:
                    laps_diff = p1_laps - drv["race_laps_count"]
                    if laps_diff > 0:
                        drv["gap_laps"] = laps_diff
                        drv["gap"]      = f"+{laps_diff} tour{'s' if laps_diff > 1 else ''}"
                    else:
                        gap_ms         = drv["race_time_ms"] - p1_time
                        drv["gap_ms"]  = gap_ms
                        drv["gap"]     = _ms_to_delta(gap_ms) if gap_ms > 0 else "—"
        else:
            p1_best = p1["best_lap_ms"]
            for drv in standings:
                if drv["position"] == 1 or not p1_best or not drv["best_lap_ms"]:
                    drv["gap_ms"] = 0
                    drv["gap"]    = "—"
                else:
                    gap_ms        = drv["best_lap_ms"] - p1_best
                    drv["gap_ms"] = gap_ms
                    drv["gap"]    = _ms_to_delta(gap_ms)

    # Durée de session
    session_duration_ms = 0
    try:
        session_duration_ms = (
            data.get("specialization", {})
                .get("base", {})
                .get("session_duration_ms", 0)
        )
    except Exception:
        pass

    return {
        "track":                  data.get("track_name", ""),
        "layout":                 data.get("track_layout_name", ""),
        "session_type":           session_type,
        "is_race":                is_race,
        "server_name":            data.get("server_name", "").strip(),
        "is_completed":           data.get("is_completed", False),
        "session_duration_ms":    session_duration_ms,
        "session_duration":       _ms_to_laptime(session_duration_ms) if session_duration_ms else "—",
        "session_best_ms":        session_best_ms,
        "session_best":           _ms_to_laptime(session_best_ms),
        "session_best_splits_ms": session_best_splits_ms,
        "standings":              standings,
        "contacts":               incidents["contacts"],
        "big_hits":               incidents["big_hits"],
        "penalties":              incidents["penalties"],
        # Les anciennes versions du serveur de jeu n'écrivaient ni collisions ni sanctions :
        # sans ce drapeau, leurs tours compteraient comme « propres » dans le fair-play.
        "incidents_reported":     "collisions" in data or "penalty_collection" in data,
        "has_incidents":          bool(incidents["contacts"] or incidents["big_hits"]
                                       or any(v["total"] for v in incidents["stats"].values())),
        "has_penalties":          bool(incidents["penalties"]),
    }


def import_result_file(path: Path, source: str = "file",
                       config_name: str | None = None,
                       run_id: str | None = None,
                       server_id: int | None = None,
                       known_hashes: set[str] | None = None) -> bool:
    """Importe un fichier de résultats en base. Retourne True si importé.

    Si `known_hashes` est fourni (ensemble des raw_json_hash déjà en DB, précalculé
    par l'appelant), le hash du fichier est vérifié contre cet ensemble en mémoire
    avant de parser le JSON — évite de re-parser inutilement un fichier déjà importé
    lors d'un scan de dossier. Sans `known_hashes`, comportement inchangé (une requête
    DB par appel), adapté au cas d'un import unique (webhook)."""
    from app.services.database import db
    from app.models import SessionResult

    try:
        raw = path.read_text(encoding="utf-8")
    except Exception as e:
        log.error("Impossible de lire %s : %s", path, e)
        return False

    raw_hash = hashlib.sha256(raw.encode()).hexdigest()

    if known_hashes is not None:
        if raw_hash in known_hashes:
            return False
    elif SessionResult.query.filter_by(raw_json_hash=raw_hash).first():
        return False

    try:
        data = json.loads(raw)
    except Exception as e:
        log.error("Impossible de parser %s : %s", path, e)
        return False
    parsed = parse_result_file(data)

    result = SessionResult(
        raw_json=raw,
        raw_json_hash=raw_hash,
        source=source,
        track=parsed["track"][:200],
        session_type=parsed["session_type"][:60],
        config_name=config_name,
        run_id=run_id,
        server_id=server_id,
    )
    db.session.add(result)
    db.session.commit()
    if known_hashes is not None:
        known_hashes.add(raw_hash)
    log.info("Résultats importés depuis %s (track=%s, run=%r)", path.name, parsed["track"], run_id)
    try:
        from app.routes.leaderboard import invalidate_circuits_cache
        invalidate_circuits_cache()
    except Exception:
        pass
    _notify_session_summary(parsed, path, server_id)
    return True


_SUMMARY_MAX_AGE_S = 900   # au-delà, le fichier est un rattrapage (scan au démarrage) : pas de notification


def _notify_session_summary(parsed: dict, path: Path, server_id: int | None) -> None:
    """Annonce la fin d'une session sur Discord si l'option est activée.

    Garde-fous : option désactivée par défaut ; jamais pour un fichier ancien (le panel
    réimporte les résultats manquants à chaque démarrage) ; jamais pour une session vide."""
    import os
    import time
    if os.environ.get("DISCORD_NOTIFY_SESSION_SUMMARY", "false").lower() != "true":
        return
    if not parsed.get("standings"):
        return
    try:
        if time.time() - path.stat().st_mtime > _SUMMARY_MAX_AGE_S:
            return
    except OSError:
        return
    try:
        from app.models import Server
        from app.services import discord_notifier
        from app.services.database import db
        srv = db.session.get(Server, server_id) if server_id else None
        discord_notifier.safe_notify(discord_notifier.notify_session_summary, parsed,
                                     server_id=server_id, server_name=srv.name if srv else "")
    except Exception as e:      # une notification ne doit jamais faire échouer un import
        log.warning("notification de fin de session ignorée : %s", e)


def scan_and_import(aceserver_dir: str, config_name: str | None = None,
                    run_id: str | None = None, server_id: int | None = None) -> int:
    """Scanne le dossier aceserver pour des fichiers de résultats non encore importés.

    Précalcule l'ensemble des hash déjà en DB en une seule requête, pour éviter de
    reparser (coûteux) chaque fichier déjà importé — seul le hash (lecture + sha256,
    peu coûteux) est recalculé pour chaque fichier du dossier."""
    from app.models import SessionResult
    base = Path(aceserver_dir)
    known_hashes = {h for (h,) in SessionResult.query.with_entities(SessionResult.raw_json_hash).all()}
    imported = 0
    for f in sorted(base.rglob("result*.json")):
        if import_result_file(f, source="file", config_name=config_name,
                              run_id=run_id, server_id=server_id,
                              known_hashes=known_hashes):
            imported += 1
    if imported:
        log.info("scan_and_import : %d nouveau(x) fichier(s) importé(s)", imported)
    return imported


# ── Regroupement de sessions (weekends de course) ──────────────────────────────

_WEEKEND_PALETTE = [
    "#6366f1",  # indigo
    "#10b981",  # emerald
    "#f59e0b",  # amber
    "#ef4444",  # red
    "#8b5cf6",  # violet
    "#06b6d4",  # cyan
    "#ec4899",  # pink
]
_PRACTICE_COLOR = "#64748b"
# Max gap between two consecutive sessions to be considered part of the same race weekend.
# In ACE EVO, Race Weekend sessions run back-to-back automatically; 2h covers restarts/pauses
# without accidentally pulling in a standalone practice done hours earlier.
_MAX_INTRA_GAP = timedelta(hours=2)


def group_sessions(sessions):
    """
    Groupe les sessions par run_id (identifiant unique généré à chaque start_server).

    Passe 1 — sessions avec run_id : regroupement exact, sans heuristique.
    Passe 2 — sessions sans run_id (anciens résultats) : fallback anchor-on-Race.

    Retourne (sessions_annotées, groupes_triés_plus_récent_en_premier).
    """
    if not sessions:
        return sessions, []

    chrono  = sorted(sessions, key=lambda s: s["received_at"])
    id_to_s = {s["id"]: s for s in sessions}
    used    = set()
    raw_groups: list[dict] = []

    # ── Passe 1 : run_id (fiable) ─────────────────────────────────────────
    by_run: dict[str, dict] = {}
    for s in chrono:
        rid = s.get("run_id") or ""
        if not rid:
            continue
        if rid not in by_run:
            g = {"session_ids": [], "run_id": rid,
                 "config_name": s.get("config_name") or ""}
            by_run[rid] = g
            raw_groups.append(g)
        by_run[rid]["session_ids"].append(s["id"])
        used.add(s["id"])

    # ── Passe 2 : fallback anchor-on-Race (anciens résultats sans run_id) ─
    remaining = [s for s in chrono if s["id"] not in used]
    for i, s in enumerate(remaining):
        if s["id"] in used:
            continue
        if (s["parsed"].get("session_type") or "").lower() != "race":
            continue

        track       = (s["parsed"].get("track") or "").strip()
        group_ids   = [s["id"]]
        used.add(s["id"])
        frontier_t  = s["received_at"]

        for j in range(i - 1, -1, -1):
            prev = remaining[j]
            if prev["id"] in used:
                continue
            if (prev["parsed"].get("track") or "").strip() != track:
                break
            if (frontier_t - prev["received_at"]) > _MAX_INTRA_GAP:
                break
            if (prev["parsed"].get("session_type") or "").lower() not in \
                    {"practice", "qualifying", "warmup", "race"}:
                break
            group_ids.insert(0, prev["id"])
            used.add(prev["id"])
            frontier_t = prev["received_at"]

        raw_groups.append({"session_ids": group_ids, "run_id": None, "config_name": None})

    # Sessions restantes sans run_id = standalone
    for s in chrono:
        if s["id"] not in used:
            raw_groups.append({"session_ids": [s["id"]], "run_id": None, "config_name": None})
            used.add(s["id"])

    # ── Couleurs ──────────────────────────────────────────────────────────
    color_idx = 0
    for g in raw_groups:
        types = {
            (id_to_s[sid]["parsed"].get("session_type") or "").lower()
            for sid in g["session_ids"]
        } - {""}
        is_weekend = "race" in types or len(types) > 1
        g["types"]      = types
        g["is_weekend"] = is_weekend
        if is_weekend:
            g["color"] = _WEEKEND_PALETTE[color_idx % len(_WEEKEND_PALETTE)]
            color_idx += 1
        else:
            g["color"] = _PRACTICE_COLOR

    # ── Tri : groupe le plus récent en premier ────────────────────────────
    raw_groups.sort(
        key=lambda g: max(id_to_s[sid]["received_at"] for sid in g["session_ids"]),
        reverse=True,
    )

    # ── Annotation + construction template ───────────────────────────────
    id_to_group = {sid: g for g in raw_groups for sid in g["session_ids"]}
    for s in sessions:
        g = id_to_group.get(s["id"], {})
        s["wkd_color"]  = g.get("color", _PRACTICE_COLOR)
        s["is_weekend"] = g.get("is_weekend", False)

    ordered_groups = []
    for g in raw_groups:
        group_sessions_ = sorted(
            [id_to_s[sid] for sid in g["session_ids"]],
            key=lambda s: s["received_at"],
            reverse=True,
        )
        types = {
            (s["parsed"].get("session_type") or "").lower()
            for s in group_sessions_
            if s["parsed"].get("session_type")
        }
        track = (group_sessions_[0]["parsed"].get("track") or "").strip() if group_sessions_ else ""
        ordered_groups.append({
            "color":       g["color"],
            "is_weekend":  g["is_weekend"],
            "track":       track,
            "types":       types,
            "sessions":    group_sessions_,
            "config_name": g.get("config_name"),
        })

    return sessions, ordered_groups
