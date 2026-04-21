"""Compile all .po translation files to binary .mo format."""
from babel.messages.mofile import write_mo
from babel.messages.pofile import read_po
import pathlib

translations = pathlib.Path(__file__).parent / "translations"

for po_path in translations.rglob("*.po"):
    mo_path = po_path.with_suffix(".mo")
    with open(po_path, "r", encoding="utf-8") as f_po:
        catalog = read_po(f_po)
    with open(mo_path, "wb") as f_mo:
        write_mo(f_mo, catalog)
    print(f"Compiled {po_path.relative_to(pathlib.Path(__file__).parent)}")

print("Done.")
