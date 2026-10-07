#!/usr/bin/env python3
"""CASE 1 - a parametric part family, from a data table.

The whole input is the six-column table at the top of CODE. Everything else -
bolt circles, hole patterns, centre lines, layers, the sheet, the border, the
parts list - is derived from it.

The point of this case is *throughput and determinism*: no AutoCAD process is
started, no template is opened, no licence is checked out. One `drawing_run`
call, milliseconds, and the file is on disk. That makes it the right backend
for anything generated in bulk or regenerated on every commit.

Everything below the marker is passed verbatim to the `drawing_run` tool, so
what you read here is literally what the agent sends.

Run:  python cases/01_parts.py
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
import math
from ezdxf.enums import TextEntityAlignment

# ---- the entire input -------------------------------------------------
SPEC = [    #  tag,      OD,  PCD,  hole,  bolts,  bore
    ("DN50",     165,  125,    18,      4,    61),
    ("DN80",     200,  160,    18,      8,    90),
    ("DN100",    220,  180,    18,      8,   115),
    ("DN150",    285,  240,    22,      8,   169),
]
SHEET = (3000, 1500)          # millimetres
SCALE = 2.0                   # drawn at 2:1, as a parts catalogue would

# ---- setup ------------------------------------------------------------
for name, color in {"OUTLINE": 5, "BORE": 3, "BOLT": 1, "CENTER": 4,
                    "TEXT": 7, "BORDER": 7, "TABLE": 7}.items():
    doc.layers.add(name, color=color)

# CENTER has to exist as a linetype; degrade rather than fail if it does not
have = {lt.dxf.name.upper() for lt in doc.linetypes}
LT = next((c for c in ("CENTER", "DASHDOT", "DASHED", "CONTINUOUS")
           if c in have), "CONTINUOUS")

# setup=True installs two dozen OpenSans/Liberation text styles that are not
# installed on this machine, so AutoCAD substitutes a font for every one and
# the console fills with warnings. Unlink the dimstyles, drop the rest, and
# point the one style we use at a font that really exists.
for ds in doc.dimstyles:
    ds.dxf.dimtxsty = "Standard"
for s in list(doc.styles):
    if s.dxf.name != "Standard":
        doc.styles.discard(s.dxf.name)
doc.styles.get("Standard").dxf.font = "arial.ttf"

doc.header["$INSUNITS"] = 4      # millimetres
doc.header["$MEASUREMENT"] = 1
doc.header["$LTSCALE"] = 25

def text(pt, h, s, layer, center=True):
    e = msp.add_text(s, height=h, dxfattribs={"layer": layer})
    e.set_placement(pt, align=TextEntityAlignment.MIDDLE_CENTER if center
                    else TextEntityAlignment.LEFT)
    return e

# ---- one part ---------------------------------------------------------
def flange(cx, cy, od, pcd, hole, bolts, bore):
    # the sheet is drawn at SCALE:1, so every real dimension scales here - the
    # labels below keep printing the true values
    r_out, r_pcd = od / 2 * SCALE, pcd / 2 * SCALE
    r_h, r_b = hole / 2 * SCALE, bore / 2 * SCALE
    msp.add_circle((cx, cy), r_out, dxfattribs={"layer": "OUTLINE"})
    msp.add_circle((cx, cy), r_b,   dxfattribs={"layer": "BORE"})
    msp.add_circle((cx, cy), r_pcd,
                   dxfattribs={"layer": "CENTER", "linetype": LT})
    for k in range(bolts):
        # 180/bolts puts the pattern symmetrically about the centre lines: 45 deg
        # for four bolts, 22.5 deg for eight - which is how a flange is drawn
        a = math.radians(180.0 / bolts + k * 360.0 / bolts)
        msp.add_circle((cx + math.cos(a) * r_pcd, cy + math.sin(a) * r_pcd),
                       r_h, dxfattribs={"layer": "BOLT"})
    e = r_out + 25
    for a, b in (((cx - e, cy), (cx + e, cy)), ((cx, cy - e), (cx, cy + e))):
        msp.add_line(a, b, dxfattribs={"layer": "CENTER", "linetype": LT})

# ---- sheet ------------------------------------------------------------
W, H = SHEET
for inset in (30, 55):
    msp.add_lwpolyline([(inset, inset), (W - inset, inset),
                        (W - inset, H - inset), (inset, H - inset)],
                       close=True, dxfattribs={"layer": "BORDER"})
text((90, 1400), 56, "PARAMETRIC FLANGE FAMILY", "TEXT", center=False)
text((90, 1325), 28,
     "EVERY LINE BELOW IS DERIVED FROM THE SIX-COLUMN TABLE IN THE SOURCE.",
     "TEXT", center=False)

# ---- the parts, laid out in one row -----------------------------------
# two label lines, not one: a single combined line is wide enough to overrun
# the sheet border on the outer flanges, and AutoCAD's extents grow to fit
# whatever overruns - so the drawing silently gets bigger than its own frame
for i, (tag, od, pcd, hole, bolts, bore) in enumerate(SPEC):
    cx = 400 + i * 720
    flange(cx, 1000, od, pcd, hole, bolts, bore)
    # labels sit on fixed rows rather than below each flange, so they line up
    text((cx, 675), 40, tag, "TEXT")
    text((cx, 620), 24,
         f"OD {od}   PCD {pcd}   {bolts}x\u00d8{hole}   BORE \u00d8{bore}",
         "TEXT")

# ---- parts list -------------------------------------------------------
text((90, 550), 34, "PARTS LIST", "TABLE", center=False)
HEADS = ["TAG", "OD", "PCD", "HOLE", "HOLES", "BORE"]
COLS = (110, 430, 690, 950, 1200, 1420)
for x, s in zip(COLS, HEADS):
    text((x, 480), 28, s, "TABLE", center=False)
msp.add_line((90, 456), (1880, 456), dxfattribs={"layer": "TABLE"})
for j, (tag, od, pcd, hole, bolts, bore) in enumerate(SPEC):
    y = 405 - j * 75
    for x, s in zip(COLS, (tag, od, pcd, f"\u00d8{hole}", bolts, f"\u00d8{bore}")):
        text((x, y), 28, str(s), "TABLE", center=False)
    msp.add_line((90, y - 34), (1880, y - 34), dxfattribs={"layer": "TABLE"})

# ---- title block ------------------------------------------------------
msp.add_lwpolyline([(2000, 90), (2945, 90), (2945, 550), (2000, 550)],
                   close=True, dxfattribs={"layer": "BORDER"})
for i, (h, s) in enumerate([(40, "FLANGE FAMILY"), (26, "PARAMETRIC SHEET"),
                            (26, "UNITS: MILLIMETRES"),
                            (26, "SCALE 2:1    SHEET 1 OF 1"),
                            (26, "DRAWN BY: ezdxf + AutoCAD MCP")]):
    text((2040, 480 - i * 76), h, s, "BORDER", center=False)

emit("parts", len(SPEC), "entities", len(list(msp)), "linetype", LT)
'''


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    dxf = OUT / "01_flange_family.dxf"

    print("=" * 74)
    print("CASE 1 - parametric part family  (drawing_run / ezdxf)")
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
    print(f"  layers={len(s['layers'])} entities={s['total_entities']} "
          f"{s['entity_counts']}")
    print(f"  extents={s['extents']}")

    svg = OUT / "01_flange_family.svg"
    preview(dxf, svg)
    print(f"  preview: {svg.name} ({svg.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
