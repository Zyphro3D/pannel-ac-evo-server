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
import json
import logging
import os
from collections import defaultdict
from pathlib import Path

log = logging.getLogger(__name__)

# Cache immuable keyed par SessionResult.id — les résultats ne changent jamais après import.
_parse_cache: dict[int, dict] = {}


def get_parsed(session_result) -> dict:
    """Retourne le résultat parsé depuis le cache, ou le parse et le met en cache."""
    rid = session_result.id
    if rid not in _parse_cache:
        _parse_cache[rid] = parse_result_file(json.loads(session_result.raw_json))
    return _parse_cache[rid]

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
    }


def import_result_file(path: Path, source: str = "file",
                       config_name: str | None = None,
                       run_id: str | None = None,
                       server_id: int | None = None) -> bool:
    """Importe un fichier de résultats en base. Retourne True si importé."""
    from app.services.database import db
    from app.models import SessionResult

    try:
        raw  = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except Exception as e:
        log.error("Impossible de lire %s : %s", path, e)
        return False

    parsed = parse_result_file(data)

    existing = SessionResult.query.filter_by(
        track=parsed["track"],
        session_type=parsed["session_type"],
        source=source,
        raw_json=raw,
    ).first()
    if existing:
        return False

    result = SessionResult(
        raw_json=raw,
        source=source,
        track=parsed["track"][:200],
        session_type=parsed["session_type"][:60],
        config_name=config_name,
        run_id=run_id,
        server_id=server_id,
    )
    db.session.add(result)
    db.session.commit()
    log.info("Résultats importés depuis %s (track=%s, run=%r)", path.name, parsed["track"], run_id)
    return True


def scan_and_import(aceserver_dir: str, config_name: str | None = None,
                    run_id: str | None = None, server_id: int | None = None) -> int:
    """Scanne le dossier aceserver pour des fichiers de résultats non encore importés."""
    base     = Path(aceserver_dir)
    imported = 0
    for f in sorted(base.rglob("result*.json")):
        if import_result_file(f, source="file", config_name=config_name,
                              run_id=run_id, server_id=server_id):
            imported += 1
    if imported:
        log.info("scan_and_import : %d nouveau(x) fichier(s) importé(s)", imported)
    return imported
