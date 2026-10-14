"""Libellés traduits des sanctions, enquêtes et types de choc du serveur de jeu.

Les valeurs brutes (énumérations du serveur : ``PenaltyType_Drive_Through``,
``InvestigationType_Racecar_Cut``…) sont converties en libellés localisés.
Une valeur inconnue (nouvelle version du jeu) retombe sur un libellé lisible
déduit du nom, jamais sur une erreur.
"""
from flask_babel import gettext as _


def _fallback(raw: str, prefix: str) -> str:
    name = raw[len(prefix):] if raw.startswith(prefix) else raw
    return name.replace("_", " ").strip().capitalize() or "—"


def penalty_type_label(raw: str) -> str:
    labels = {
        "PenaltyType_Warning":                    _("Avertissement"),
        "PenaltyType_Reprimand":                  _("Réprimande"),
        "PenaltyType_Fine":                       _("Amende"),
        "PenaltyType_Remove_Best_Laptime":        _("Meilleur tour supprimé"),
        "PenaltyType_Drop_Of_Grid_Position":      _("Recul sur la grille"),
        "PenaltyType_Start_From_Pitlane":         _("Départ des stands"),
        "PenaltyType_Time_Penalty_Seconds":       _("Pénalité de temps"),
        "PenaltyType_Penalty_Laps":               _("Pénalité de tours"),
        "PenaltyType_Drop_Of_Place_In_Classification": _("Places perdues au classement"),
        "PenaltyType_Drive_Through":              _("Drive-through"),
        "PenaltyType_Stop_And_Go":                _("Stop-and-go"),
        "PenaltyType_InvalidNextLap":             _("Tour suivant invalidé"),
        "PenaltyType_InvalidLap":                 _("Tour invalidé"),
        "PenaltyType_Disqualification":           _("Disqualification"),
        "PenaltyType_MP_TeleportToPit":           _("Téléportation aux stands"),
    }
    return labels.get(raw) or _fallback(raw, "PenaltyType_")


def investigation_label(raw: str) -> str:
    labels = {
        "InvestigationType_Racecar_Cut":            _("Coupure de piste"),
        "InvestigationType_Collision":              _("Collision"),
        "InvestigationType_Illegal_Overtake":       _("Dépassement illégal"),
        "InvestigationType_Pit_Speeding":           _("Excès de vitesse aux stands"),
        "InvestigationType_Pit_Entry":              _("Entrée des stands irrégulière"),
        "InvestigationType_Pit_Exit":               _("Sortie des stands irrégulière"),
        "InvestigationType_Ignored_Mandatory_Pit":  _("Arrêt obligatoire ignoré"),
        "InvestigationType_Unsafe_Rejoin":          _("Rejointe dangereuse"),
        "InvestigationType_Race_Control":           _("Direction de course"),
        "InvestigationType_Reverse_In_Pitlane":     _("Marche arrière dans les stands"),
        "InvestigationType_Wrong_Way":              _("Mauvais sens"),
        "InvestigationType_Ignored_Driver_Stint":   _("Relais ignoré"),
        "InvestigationType_Exceeded_Driver_Stint_Limit": _("Relais trop long"),
        "InvestigationType_Driver_Ran_No_Stint":    _("Relais non effectué"),
        "InvestigationType_Damaged_Car":            _("Voiture endommagée"),
        "InvestigationType_Lights_Off":             _("Phares éteints"),
        "InvestigationType_Speeding_On_Start":      _("Excès de vitesse au départ"),
        "InvestigationType_Wrong_Position_On_Start": _("Mauvaise position au départ"),
        "InvestigationType_Speeding":               _("Excès de vitesse"),
        "InvestigationType_StartFromPit":           _("Départ des stands"),
    }
    return labels.get(raw) or _fallback(raw, "InvestigationType_")


def collider_label(raw: str) -> str:
    labels = {
        "wall":   _("Mur"),
        "car":    _("Voiture"),
        "object": _("Objet"),
    }
    return labels.get((raw or "").lower()) or (raw or "—")
