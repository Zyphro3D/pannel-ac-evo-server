"""
Mapping SelectedTrackValue → SVG de la carte du circuit.

Les SVG sont générés depuis content.kspkg et stockés dans
app/static/img/tracks/{track}__{layout}.svg.
"""

# (track_name, layout) → nom du fichier SVG (sans extension)
_SVG_MAP: dict[tuple[str, str], str] = {
    ("Brands Hatch",               "GP"):              "brands_hatch__layout_gp",
    ("Brands Hatch",               "Indy"):            "brands_hatch__layout_indy",
    ("Circuit de Spa Francorchamps", "GP"):            "spa__layout_gp",
    ("Circuit Of The Americas",    "GP"):              "cota__layout_gp",
    ("Circuit Of The Americas",    "National"):        "cota__layout_national",
    ("Donington Park",             "GP"):              "donington__layout_grand_prix",
    ("Donington Park",             "National"):        "donington__layout_national",
    ("Fuji Speedway",              "GP"):              "fuji__layout_gp_circuit",
    ("Fuji Speedway",              "GP Short"):        "fuji__layout_gp_circuit_shortcut",
    ("Imola",                      "GP"):              "imola__layout_imola",
    ("Laguna Seca",                "GP"):              "laguna_seca__layout_laguna_seca",
    ("Monza",                      "GP"):              "monza__layout_gp",
    ("Mount Panorama",             "GP"):              "mount_panorama__track_layout",
    ("Nurburgring",                "24h"):             "nurburgring__layout_24h",
    ("Nurburgring",                "Gp Strecke"):      "nurburgring__layout_gp_strecke",
    ("Nurburgring",                "Nordschleife"):    "nurburgring__layout_nordschleife",
    ("Nurburgring",                "Sprint"):          "nurburgring__layout_sprint",
    ("Nurburgring",                "Touristenfahrten"): "nurburgring__layout_nordschleife_touristenfahrten",
    ("Oulton Park",                "Fosters"):         "oulton_park__layout_fosters",
    ("Oulton Park",                "International"):   "oulton_park__layout_international",
    ("Paul Ricard",                "Layout 1A-V2"):    "paul_ricard__layout_1a_v2",
    ("Paul Ricard",                "Layout 1C-V2"):    "paul_ricard__layout_1c_v2",
    ("Paul Ricard",                "Layout 3A"):       "paul_ricard__layout_3a",
    ("Paul Ricard",                "Layout 3C"):       "paul_ricard__layout_3c",
    ("Red Bull Ring",              "GP"):              "redbull_ring__layout_gp",
    ("Red Bull Ring",              "National"):        "redbull_ring__layout_national",
    ("Road Atlanta",               "GP"):              "road_atlanta__layout_gp",
    ("Sebring International Raceway", "GP"):           "sebring__layout_gp",
    ("Suzuka",                     "East"):            "suzuka__layout_east",
    ("Suzuka",                     "GP"):              "suzuka__layout_gp",
    ("Suzuka",                     "West"):            "suzuka__layout_west",
    ("Watkins Glen International", "GP"):              "watkins_glen__layout_gp",
    ("Watkins Glen International", "GP Inner Loop"):   "watkins_glen__layout_gp_inner_loop",
    ("Watkins Glen International", "Short"):           "watkins_glen__layout_short",
    ("Watkins Glen International", "Short Inner Loop"): "watkins_glen__layout_short_inner_loop",
}


def get_track_svg_name(track_name: str, layout: str) -> str | None:
    """Retourne le nom du fichier SVG (sans extension) pour le circuit donné, ou None."""
    return _SVG_MAP.get((track_name, layout))
