#!/usr/bin/env python3
"""CASE 3 - auditing a drawing instead of producing one.

Every other case here writes geometry. This one reads it. That direction is
where an agent earns its keep on existing work: a folder of drawings arrives
from a consultant, a supplier or a previous engineer, and someone has to find
what is wrong with them before anything is fabricated or issued.

Two `drawing_run` calls:

  1. build a drawing that carries ten planted defects - the kind that actually
     cause trouble downstream, not made-up ones;
  2. audit it against a rule set, print a report, and write an annotated copy
     with each finding circled and numbered.

The audit is written against *any* DXF, not just this one: it is a rule set,
not a lookup table of the answers. Point `CODE_AUDIT` at a real drawing and it
reports on that instead.

Run:  python cases/03_audit.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import server            # noqa: E402
from render import preview   # noqa: E402

OUT = ROOT / "out"

# ---------------------------------------------------------------------------
# step 1 - a drawing with ten planted defects
# ---------------------------------------------------------------------------
CODE_MESSY = r'''
from ezdxf.enums import TextEntityAlignment

for name, color in [("BORDER", 7), ("WALLS", 5), ("ROOMS", 4), ("TEXT", 3),
                    ("ELECTRICAL", 1), ("FURNITURE", 2), ("TEMP", 6)]:
    doc.layers.add(name, color=color)
doc.styles.get("Standard").dxf.font = "arial.ttf"
doc.header["$INSUNITS"] = 0          # DEFECT 10: the file never says what a unit is
doc.header["$LTSCALE"] = 20

def rect(x0, y0, x1, y1, layer):
    msp.add_lwpolyline([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], close=True,
                       dxfattribs={"layer": layer})

rect(0, 0, 4000, 2800, "BORDER")     # the sheet, and the audit's reference
rect(100, 100, 1900, 1300, "ROOMS")
rect(2100, 100, 3900, 1300, "ROOMS")

# DEFECT 1: the same wall drawn twice, exactly coincident - overdrawn geometry
# is invisible on screen and doubles the cut path on a CNC
msp.add_line((2000, 100), (2000, 2700), dxfattribs={"layer": "WALLS"})
msp.add_line((2000, 100), (2000, 2700), dxfattribs={"layer": "WALLS"})

# DEFECT 2: an outline that looks closed but is not - the last vertex sits on
# the first and the closed flag was never set, so an area or a hatch fails
msp.add_lwpolyline([(100, 1500), (1900, 1500), (1900, 2700), (100, 2700),
                    (100, 1500)], close=False, dxfattribs={"layer": "ROOMS"})

# DEFECT 3: a zero-length line left behind by a bad edit
msp.add_line((1200, 900), (1200, 900), dxfattribs={"layer": "WALLS"})

# DEFECT 4: a degenerate circle
msp.add_circle((3000, 2200), 0.4, dxfattribs={"layer": "ELECTRICAL"})

# DEFECT 5: geometry parked on layer 0, which no layer standard owns
msp.add_line((2100, 1300), (3900, 2700), dxfattribs={"layer": "0"})

# DEFECT 6: text too small to survive the plot
msp.add_text("NOTE 1", height=8,
             dxfattribs={"layer": "TEXT"}).set_placement(
    (300, 620), align=TextEntityAlignment.MIDDLE_LEFT)

# DEFECT 7: a repeated vertex inside a polyline
msp.add_lwpolyline([(2400, 400), (3200, 400), (3200, 400), (3200, 900),
                    (2400, 900)], close=True, dxfattribs={"layer": "FURNITURE"})

# DEFECT 8: geometry that runs off the sheet
msp.add_circle((4050, 2500), 300, dxfattribs={"layer": "ELECTRICAL"})

# DEFECT 9: layer TEMP is defined and never used

emit("built", len(list(msp)), "entities")
'''

# ---------------------------------------------------------------------------
# step 2 - the audit
# ---------------------------------------------------------------------------
CODE_AUDIT = r'''
import math
from collections import Counter
from ezdxf import bbox
from ezdxf.enums import TextEntityAlignment

# house rules for this sheet size, not universal truths
MIN_TEXT = 50.0       # mm - smallest legible height at the issue scale
TOL = 0.01            # mm - coordinate tolerance

issues = []

def flag(kind, severity, entity, detail):
    issues.append({"kind": kind, "severity": severity, "detail": detail,
                   "entity": entity, "handle": entity.dxf.handle if entity else None,
                   "layer": entity.dxf.layer if entity else "-",
                   "type": entity.dxftype() if entity else "-"})

def r(v):
    return round(v, 3)

def flat(p):
    return (r(p[0]), r(p[1]))

# index, never slice: ezdxf's Vec3 supports integer indexing but slicing it
# raises "TypeError: an integer is required"
def dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])

# --- 1. degenerate geometry: entities that carry no shape ------------------
for e in msp:
    t = e.dxftype()
    if t == "LINE" and dist(e.dxf.start, e.dxf.end) < 0.5:
        flag("degenerate", "high", e,
             f"line is only {dist(e.dxf.start, e.dxf.end):.3f} mm long")
    elif t in ("CIRCLE", "ARC") and e.dxf.radius < 1.0:
        flag("degenerate", "high", e, f"radius is {e.dxf.radius:g} mm")

# --- 2. exact duplicates: the same geometry drawn more than once -----------
def geo_key(e):
    t = e.dxftype()
    if t == "LINE":
        return (t,) + tuple(sorted([flat(e.dxf.start), flat(e.dxf.end)]))
    if t == "CIRCLE":
        return (t, flat(e.dxf.center), r(e.dxf.radius))
    if t == "ARC":
        return (t, flat(e.dxf.center), r(e.dxf.radius),
                r(e.dxf.start_angle), r(e.dxf.end_angle))
    if t == "LWPOLYLINE":
        return (t,) + tuple(flat(p) for p in e.get_points("xy"))
    return (t, e.dxf.handle)          # unique by construction, never a duplicate

first_seen = {}
for e in msp:
    k = geo_key(e)
    if k in first_seen:
        flag("duplicate", "medium", e,
             f"identical to handle {first_seen[k].dxf.handle} "
             f"on layer {first_seen[k].dxf.layer}")
    else:
        first_seen[k] = e

# --- 3. polylines: unclosed outlines and repeated vertices -----------------
for e in msp.query("LWPOLYLINE"):
    pts = [flat(p) for p in e.get_points("xy")]
    if any(dist(a, b) < TOL for a, b in zip(pts, pts[1:])):
        flag("repeated-vertex", "low", e, "two consecutive vertices coincide")
    if len(pts) >= 3 and not e.closed and dist(pts[0], pts[-1]) < TOL:
        flag("unclosed-outline", "high", e,
             "first and last vertex coincide but the polyline is not closed")

# --- 4. layer discipline ---------------------------------------------------
for e in msp:
    if e.dxf.layer == "0":
        flag("wrong-layer", "medium", e, "entity is on layer 0")
used = {e.dxf.layer for e in msp}
for lay in doc.layers:
    n = lay.dxf.name
    if n not in used and n not in ("0", "Defpoints"):
        flag("unused-layer", "low", None, f"layer {n!r} is defined but empty")

# --- 5. annotative: text that will not survive the plot --------------------
for e in msp.query("TEXT MTEXT"):
    h = e.dxf.height if e.dxftype() == "TEXT" else e.dxf.char_height
    if h < MIN_TEXT:
        flag("text-too-small", "medium", e,
             f"height {h:g} mm is below the {MIN_TEXT:g} mm rule")

# --- 6. anything outside the sheet border ----------------------------------
border = bbox.extents(msp.query('*[layer=="BORDER"]'))
for e in msp:
    if e.dxf.layer == "BORDER":
        continue
    try:
        bb = bbox.extents([e])
    except Exception:
        continue
    if bb.has_data and (bb.extmin.x < border.extmin.x - TOL
                        or bb.extmin.y < border.extmin.y - TOL
                        or bb.extmax.x > border.extmax.x + TOL
                        or bb.extmax.y > border.extmax.y + TOL):
        flag("outside-sheet", "high", e,
             f"reaches ({bb.extmax.x:.0f}, {bb.extmax.y:.0f}); "
             f"sheet ends at ({border.extmax.x:.0f}, {border.extmax.y:.0f})")

# --- 7. is the file self-describing? ---------------------------------------
if not doc.header.get("$INSUNITS", 0):
    flag("units-undeclared", "medium", None,
         "$INSUNITS is 0, so nothing states whether a unit is mm or inches")

# --- annotate: circle and number every finding that has an entity ----------
# the marker layer is created only now: created earlier it would be an empty
# layer at check time and the audit would report its own bookkeeping
msp.doc.layers.add("ISSUES", color=1)
for i, it in enumerate(issues, 1):
    e = it["entity"]
    if e is None:
        continue
    try:
        bb = bbox.extents([e])
    except Exception:
        continue
    if not bb.has_data or not math.isfinite(bb.extmin.x):
        continue
    cx, cy = (bb.extmin.x + bb.extmax.x) / 2, (bb.extmin.y + bb.extmax.y) / 2
    # a marker of fixed size, not one scaled to the entity: a circle big enough
    # to enclose a 2.6 m wall parks its number 1.4 m away and the result reads
    # as noise instead of as markups. Circle at the centre, short leader out.
    mr = 150.0
    msp.add_circle((cx, cy), mr, dxfattribs={"layer": "ISSUES"})
    lx, ly = cx + mr * 1.6, cy + mr * 1.6
    msp.add_line((cx + mr * 0.75, cy + mr * 0.75), (lx, ly),
                 dxfattribs={"layer": "ISSUES"})
    msp.add_text(f"{i}", height=100, dxfattribs={"layer": "ISSUES"}).set_placement(
        (lx + 50, ly + 40), align=TextEntityAlignment.MIDDLE_LEFT)

counts = Counter(i["kind"] for i in issues)
emit(f"findings={len(issues)}")
for kind, n in counts.most_common():
    emit(f"count {kind}={n}")
for i, it in enumerate(issues, 1):
    emit(f"#{i:02d} {it['severity']:6s} {it['kind']:17s} "
         f"{it['type']}({it['handle']}) layer={it['layer']} :: {it['detail']}")
emit("verdict=" + ("FAIL - %d findings" % len(issues) if issues else "PASS"))
'''


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    messy = OUT / "03_messy.dxf"
    marked = OUT / "03_audited.dxf"

    print("=" * 74)
    print("CASE 3 - drawing audit  (drawing_run, read direction)")
    print("=" * 74)

    r1 = server.drawing_run(CODE_MESSY, save_as=str(messy))
    if not r1["ok"]:
        print("FAILED to build:", r1["error"])
        return 1
    print(f"  built {messy.name}: {r1['emitted']}")

    r2 = server.drawing_run(CODE_AUDIT, path=str(messy), save_as=str(marked))
    if not r2["ok"]:
        print("FAILED to audit:", r2["error"])
        return 1

    sep = False
    for line in r2["emitted"]:
        if line.startswith("#") and not sep:
            print()
            print(f"  {'#':>3}  {'sev':6s} {'kind':17s} {'entity':14s} detail")
            print("  " + "-" * 70)
            sep = True
        if line.startswith("#"):
            n, sev, kind, rest = line[1:].split(None, 3)
            print(f"  {n:>3}  {sev:6s} {kind:17s} {rest}")
        else:
            print(f"  {line}")

    for p in (messy, marked):
        preview(p, OUT / (p.stem + ".svg"))
    print()
    print(f"  artifacts: {messy.name}, {marked.name}, "
          f"03_messy.svg, 03_audited.svg")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
