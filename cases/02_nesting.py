#!/usr/bin/env python3
"""CASE 2 - nesting a cut list onto sheet stock.

Input is a bill of materials: tags, sizes, quantities. Output is a set of
sheets with every part positioned, tagged and dimensioned, plus the material
utilisation. This is the shape of a real job - the numbers come from a
spreadsheet or a PDM export, and someone has to turn them into a cut sheet.

The packing is deliberately a plain shelf (next-fit, decreasing height) so the
code stays readable; production nests are usually done by a specialist tool.
What matters here is that the *whole loop* - pack, draw, label, report - runs
in one `drawing_run` call with no AutoCAD process and no licence.

Run:  python cases/02_nesting.py
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import server            # noqa: E402
from render import preview   # noqa: E402

OUT = ROOT / "out"

# ---------------------------------------------------------------------------
# the payload: this is the tool argument
# ---------------------------------------------------------------------------
CODE = r'''
from ezdxf.enums import TextEntityAlignment

# ---- input: stock and bill of materials -------------------------------
SHEET = (2440, 1220)          # 8 x 4 ft sheet, millimetres
MARGIN, GAP = 25, 12          # edge margin, and kerf allowance between parts
PARTS = [    #  tag,      w,    h,  qty,  hole dia (None = no hole)
    ("BRK-01",  420,  300,    4,     60),
    ("PLT-03",  620,  240,    2,    100),
    ("BRK-02",  260,  180,    6,   None),
    ("GUS-04",  160,  160,    8,   None),
    ("STR-05",  340,  120,    4,     40),
    ("PLT-06",  500,  300,    2,     80),
    ("RNG-07",  200,   90,    6,   None),
]

for name, color, lt in [("SHEET", 8, "CONTINUOUS"), ("CUT", 3, "CONTINUOUS"),
                        ("HOLE", 1, "CONTINUOUS"), ("LABEL", 7, "CONTINUOUS"),
                        ("BOM", 7, "CONTINUOUS")]:
    doc.layers.add(name, color=color)
doc.styles.get("Standard").dxf.font = "arial.ttf"
doc.header["$INSUNITS"] = 4
doc.header["$LTSCALE"] = 20

def text(pt, h, s, layer, center=False):
    e = msp.add_text(s, height=h, dxfattribs={"layer": layer})
    e.set_placement(pt, align=TextEntityAlignment.MIDDLE_CENTER if center
                    else TextEntityAlignment.MIDDLE_LEFT)
    return e

# ---- pack: shelf, next-fit decreasing height --------------------------
CW, CH = SHEET[0] - 2 * MARGIN, SHEET[1] - 2 * MARGIN
queue = sorted(({"tag": t, "w": w, "h": h, "hole": d} for t, w, h, q, d in PARTS
                for _ in range(q)), key=lambda p: -p["h"])

def place(sh, p):
    if sh["x"] > 0 and sh["x"] + p["w"] > CW:     # this row is full
        sh["y"] += sh["row_h"] + GAP
        sh["x"], sh["row_h"] = 0.0, 0.0
    if sh["y"] + p["h"] > CH:
        return False
    sh["parts"].append(dict(p, x=sh["x"], y=sh["y"]))
    sh["row_h"] = max(sh["row_h"], p["h"])
    sh["x"] += p["w"] + GAP
    return True

sheets = []
for p in queue:
    for sh in sheets:
        if place(sh, p):
            break
    else:
        sheets.append({"x": 0.0, "y": 0.0, "row_h": 0.0, "parts": []})
        place(sheets[-1], p)

# ---- draw one sheet per stock plate -----------------------------------
placed_area = 0.0
for si, sh in enumerate(sheets):
    ox, oy = 0.0, si * (SHEET[1] + 210)
    msp.add_lwpolyline([(ox, oy), (ox + SHEET[0], oy),
                        (ox + SHEET[0], oy + SHEET[1]), (ox, oy + SHEET[1])],
                       close=True, dxfattribs={"layer": "SHEET"})
    for p in sh["parts"]:
        x, y = ox + MARGIN + p["x"], oy + MARGIN + p["y"]
        w, h = p["w"], p["h"]
        msp.add_lwpolyline([(x, y), (x + w, y), (x + w, y + h), (x, y + h)],
                           close=True, dxfattribs={"layer": "CUT"})
        if p["hole"]:
            msp.add_circle((x + w / 2, y + h / 2), p["hole"] / 2,
                           dxfattribs={"layer": "HOLE"})
        placed_area += w * h
        if w > 220 and h > 130:           # only label parts that can hold text
            text((x + w / 2, y + h / 2 + 34), 52, p["tag"], "LABEL", center=True)
            text((x + w / 2, y + h / 2 - 34), 38, f"{w}x{h}", "LABEL", center=True)
    used = sum(q["w"] * q["h"] for q in sh["parts"]) / (SHEET[0] * SHEET[1]) * 100
    text((ox + 12, oy - 100), 60, f"SHEET {si + 1} / {len(sheets)}"
         f"     {len(sh['parts'])} PARTS     MATERIAL UTILISATION {used:.1f}%",
         "SHEET")
    text((ox + 12, oy - 175), 36,
         f"STOCK {SHEET[0]} x {SHEET[1]} x 3.0 t     KERF {GAP}     "
         f"MARGIN {MARGIN}     UNITS: MILLIMETRES", "SHEET")

# ---- bill of materials, above the sheets ------------------------------
# the table is drawn downward from its title, so the title has to clear the top
# of the last sheet by the full table height - 205 mm of head plus one 62 mm
# row per part - or the rows land on top of the nesting
sheet_top = (len(sheets) - 1) * (SHEET[1] + 210) + SHEET[1]
by_y = sheet_top + 205 + 62 * len(PARTS) + 120
text((12, by_y), 60, "BILL OF MATERIALS", "BOM")
HEADS = ["TAG", "SIZE", "QTY", "HOLE", "PLACED"]
COLS = (30, 430, 950, 1250, 1550)
for x, s in zip(COLS, HEADS):
    text((x, by_y - 100), 42, s, "BOM")
msp.add_line((0, by_y - 140), (2200, by_y - 140), dxfattribs={"layer": "BOM"})
y = by_y - 205
for tag, w, h, qty, hole in PARTS:
    for x, s in zip(COLS, (tag, f"{w} x {h}", qty,
                           f"O{hole}" if hole else "-",
                           sum(1 for sh_ in sheets for q in sh_["parts"]
                               if q["tag"] == tag))):
        text((x, y), 42, str(s), "BOM")
    y -= 62

area = SHEET[0] * SHEET[1] * len(sheets)
emit(f"parts={len(queue)} sheets={len(sheets)} "
     f"utilisation={placed_area / area * 100:.1f}% "
     f"entities={len(list(msp))}")
'''


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    dxf = OUT / "02_nesting.dxf"

    print("=" * 74)
    print("CASE 2 - sheet nesting from a bill of materials  (drawing_run)")
    print("=" * 74)
    t0 = time.perf_counter()
    r = server.drawing_run(CODE, save_as=str(dxf))
    ms = (time.perf_counter() - t0) * 1000
    if not r["ok"]:
        print("FAILED:", r["error"])
        return 1

    print(f"  {dxf.name}: {dxf.stat().st_size:,} bytes in {ms:.0f} ms")
    for line in r["emitted"]:
        print(f"    emit: {line}")
    s = server.drawing_summary(str(dxf))
    print(f"  layers={len(s['layers'])} entities={s['total_entities']}")
    print(f"  extents={s['extents']}")

    svg = OUT / "02_nesting.svg"
    preview(dxf, svg)
    print(f"  preview: {svg.name} ({svg.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
