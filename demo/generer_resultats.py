"""Résultats de session ENTIÈREMENT FICTIFS pour une instance de démonstration (captures, aperçus).

Pilotes, identifiants Steam, serveur et dates sont inventés ; seuls les circuits et les voitures
viennent du jeu. Ne jamais utiliser de vraies données sur une instance de démonstration (charte §8).

Usage : python demo/generer_resultats.py DOSSIER [--sessions 14] [--graine 7]
Écrit des fichiers JSON au format du serveur ACE EVO, à importer ensuite par le panel
(il importe tout seul le dossier aceserver/results au démarrage).
"""
import argparse
import json
import random
from datetime import datetime, timedelta
from pathlib import Path

PILOTES = [
    ("Léo", "Marchal", "LeoM"), ("Inès", "Vidal", "Vidalia"), ("Tom", "Rigal", "T.Rigal"),
    ("Sacha", "Morel", "Sachamo"), ("Nina", "Ferrand", "NinaF"), ("Hugo", "Brun", "HBrun_77"),
    ("Clara", "Lemaire", "Clem"), ("Yanis", "Garnier", "Yaniz"), ("Lou", "Perrin", "LouP"),
    ("Malo", "Chevalier", "MaloRacing"), ("Jade", "Roussel", "JadeR"), ("Axel", "Fontaine", "AxFont"),
    ("Emma", "Barbier", "Emmab"), ("Noé", "Gauthier", "NoeG_44"), ("Rose", "Mercier", "Rosie"),
    ("Paul", "Dumont", "P.Dumont"),
]
VOITURES = [
    ("preset_m4gt3_mech_1", "BMW M4 GT3", 3.2), ("preset_r8gt3_mech_1", "Audi R8 LMS GT3 evo II", 3.2),
    ("preset_296gt3_mech_1", "Ferrari 296 GT3", 3.2), ("preset_911gt3r_mech_1", "Porsche 911 GT3 R", 3.2),
    ("preset_huracangt3_mech_1", "Lamborghini Huracán GT3 EVO2", 3.2), ("preset_amggt3_mech_1", "Mercedes-AMG GT3", 3.2),
]
# circuit, tracé, tour de référence (ms), 3 secteurs (proportions)
CIRCUITS = [
    ("Brands Hatch", "GP", 86_500, (0.31, 0.37, 0.32)),
    ("Circuit de Spa Francorchamps", "GP", 138_200, (0.29, 0.44, 0.27)),
    ("Autodromo Nazionale Monza", "GP", 108_400, (0.34, 0.33, 0.33)),
    ("Autodromo Enzo e Dino Ferrari", "Imola", 101_300, (0.32, 0.36, 0.32)),
    ("Nürburgring", "GP-Strecke", 115_900, (0.33, 0.35, 0.32)),
    ("Suzuka Circuit", "GP", 121_700, (0.36, 0.33, 0.31)),
]
SESSIONS = ["Practice", "Qualify", "Race"]


def guid(rng):
    return {"a": str(rng.getrandbits(62)), "b": str(rng.getrandbits(62))}


def session(rng, index, quand):
    circuit, trace, ref, parts = rng.choice(CIRCUITS)
    kind = SESSIONS[index % 3]
    engages = rng.sample(PILOTES, rng.randint(9, 14))
    drivers, cars, laps, standings, collisions = [], [], [], [], []
    for n, (prenom, nom, pseudo) in enumerate(engages):
        dg, cg = guid(rng), guid(rng)
        preset, nom_voiture, pi = rng.choice(VOITURES)
        drivers.append({"guid": dg, "first_name": prenom, "last_name": nom, "nickname": pseudo,
                        "player_id": f"7656119800{PILOTES.index((prenom, nom, pseudo)):07d}",
                        "nation": "FRA", "year_of_birth": 1990 + rng.randint(0, 12)})
        cars.append({"car_id": cg, "model_displayname": nom_voiture, "model_mechanical_preset": preset,
                     "performance_indicator": pi, "race_number": 2 + n * 3})
        niveau = 1 + rng.uniform(0, 0.035) + PILOTES.index((prenom, nom, pseudo)) * 0.0012
        nb_tours = rng.randint(8, 16) if kind == "Race" else rng.randint(4, 11)
        total = 0
        for t in range(nb_tours):
            temps = int(ref * niveau * rng.uniform(0.996, 1.02))
            flags = 2 if rng.random() > 0.12 else 0          # 2 = tour propre ; 0 = tour invalidé
            if kind == "Race" and t == 0:
                flags = 128                                   # tour de formation
            secteurs = [int(temps * p) for p in parts]
            secteurs[-1] = temps - sum(secteurs[:-1])
            laps.append({"car_key": cg, "driver_key": dg, "time": temps, "split": secteurs, "flags": flags})
            total += temps
        propres = [l["time"] for l in laps if l["driver_key"] is dg and l["flags"] == 2]
        # course : temps total ; essais et qualifications : meilleur tour propre (comme le serveur)
        standings.append((total if kind == "Race" else min(propres, default=total), nb_tours, dg, cg))
        for _ in range(rng.randint(0, 3)):
            collisions.append({"local_timestamp": rng.uniform(60, 1500), "server_timestamp": rng.uniform(60, 1500),
                               "car_id": cg, "collider": rng.choice(["car", "wall", "object"]),
                               "has_damage": rng.random() > 0.6, "relative_impact_kmh": round(rng.uniform(4, 70), 1),
                               "world_pos": {"x": rng.uniform(-300, 300), "y": 0.0, "z": rng.uniform(-300, 300)},
                               "rel_pos": {"x": 0.0, "y": 0.0, "z": 0.0}, "normal": {"x": 0.0, "y": 1, "z": 0.0}})
    standings.sort(key=lambda s: (-s[1], s[0]) if kind == "Race" else (s[0],))
    return {
        "server_name": "Zyphro GT (démo)", "server_id": "demo", "server_ip": "0.0.0.0",
        "season_guid": f"demo-{index:04d}", "session_name": kind, "session_type": kind,
        "track_name": circuit, "track_layout_name": trace,
        "championship_id": {"a": "0", "b": "0"}, "event_index": 0, "session_index": index % 3,
        "is_static": False, "is_completed": True,
        "specialization": {"@type": "demo", "base": {"session_duration_ms": 1_800_000, "session_laps": 0,
                                                    "maximum_session_overtime_duration_ms": 120_000,
                                                    "maximum_session_overtime_before_next_session": 0,
                                                    "intro_music": False, "end_music": False, "end_replay_type": "none"},
                           "rules": []},
        "car_standings": [{"car_id": cg, "total_km": rng.randint(40, 160), "total_fuel_liters": rng.randint(20, 90),
                           "energy_source_consumed": 0, "energy_source_type": "fuel",
                           "starting_position": i + 1, "tyre_tread_consumed": {}}
                          for i, (_, _, _, cg) in enumerate(standings)],
        "driver_standings": [dg for _, _, dg, _ in standings],
        "time_standings": [t for t, _, _, _ in standings],
        "drivers": drivers, "laps": laps, "car_points": [], "driver_points": [], "cars": cars,
        "collisions": collisions, "penalty_collection": {"session_penalties": []},
        "_demo_date": quand.isoformat(),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dossier")
    ap.add_argument("--sessions", type=int, default=14)
    ap.add_argument("--graine", type=int, default=7)
    a = ap.parse_args()
    rng = random.Random(a.graine)
    out = Path(a.dossier)
    out.mkdir(parents=True, exist_ok=True)
    debut = datetime(2026, 9, 6, 20, 0)
    for i in range(a.sessions):
        quand = debut + timedelta(days=(i // 3) * 3, minutes=(i % 3) * 40)
        data = session(rng, i, quand)
        nom = f"result_{quand:%Y_%m_%d_%H_%M_%S}_{data['session_type'].lower()}.json"
        (out / nom).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    print(f"{a.sessions} sessions fictives écrites dans {out}")


if __name__ == "__main__":
    main()
