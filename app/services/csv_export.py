"""Export CSV : encodage UTF-8 avec BOM (Excel) et protection contre l'injection de formules."""
import csv
import io

_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def safe_cell(v):
    """Une cellule qui commence par = + - @ serait interprétée comme une formule par Excel/LibreOffice."""
    if isinstance(v, str) and v.startswith(_FORMULA_START):
        return "'" + v
    return "" if v is None else v


def to_csv(headers: list[str], rows) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    w.writerow([safe_cell(h) for h in headers])
    for row in rows:
        w.writerow([safe_cell(c) for c in row])
    return ("﻿" + buf.getvalue()).encode("utf-8")


def response(filename: str, headers: list[str], rows):
    from flask import Response
    return Response(to_csv(headers, rows), mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"',
                             "Cache-Control": "no-store"})
