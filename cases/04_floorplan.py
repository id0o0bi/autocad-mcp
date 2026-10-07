#!/usr/bin/env python3
"""A floor plan drawn by two engines - the capability demo for autocad-mcp.

Stage 1  ezdxf builds the structure: layers, walls, door and window openings,
         labels, border, title block. No AutoCAD, no licence, milliseconds.
Stage 2  AutoCAD (accoreconsole) does the drafting AutoCAD is genuinely good
         at: offsets every construction axis into a real double line, measures
         every room with its own geometry engine, and adds real DIMENSION
         objects.
Stage 3  ezdxf reads AutoCAD's output back, cross-checks the areas AutoCAD
         reported against its own, and writes the room schedule from them.
Stage 4  renders a PNG preview and prints a report.

Run:  python cases/04_floorplan.py

The AutoCAD stage uses only invocations verified not to hang against AutoCAD
2026: option values go through sysvars rather than inline prompt answers, and no
dialog-driven command is used (EXPORTPDF is a silent no-op headlessly).
"""
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import ezdxf  # noqa: E402
from ezdxf.enums import TextEntityAlignment  # noqa: E402
import server  # noqa: E402
from render import preview  # noqa: E402

OUT = ROOT / "out"

# ---------------------------------------------------------------------------
# The input: plain data. This is everything an AI has to produce for a drawing.
# ---------------------------------------------------------------------------
PLAN = {
    "drawing_title": "TWO BEDROOM FLAT - SHEET 1",
    "project": "AI-GENERATED / AUTOCAD-DRAWN",
    "scale": "1:50",
    "wall_outer": 200,
    "wall_inner": 100,
    "door_width": 900,
    # name, x, y, width, height - these tile an 8000 x 5500 footprint
    "rooms": [
        ("LIVING", 0, 0, 4500, 3200),
        ("KITCHEN", 4500, 0, 3500, 1800),
        ("BATH", 4500, 1800, 3500, 1400),
        ("BED 1", 0, 3200, 4000, 2300),
        ("BED 2", 4000, 3200, 4000, 2300),
    ],
    # (kind, axis coord, from, to, openings)
    # kind 'h': horizontal wall at y=axis, running x=from..to
    # kind 'v': vertical wall at x=axis, running y=from..to
    # openings are in the SAME absolute coordinate as from/to, never distances
    "inner_walls": [
        ("h", 3200, 0, 8000, [(1200, 2100), (5500, 6400)]),
        ("v", 4000, 3200, 5500, [(4000, 4900)]),
        ("v", 4500, 0, 3200, [(500, 1400)]),
        ("h", 1800, 4500, 8000, [(6500, 7400)]),
    ],
    # the outer wall axes sit half a thickness outside the rooms, so their inner
    # faces land exactly on the room edges
    "outer_walls": [
        ("h", -100, -100, 8100, [(3000, 3900), (500, 1900)]),   # entrance + window
        ("h", 5600, -100, 8100, [(1000, 2400), (5000, 6400)]),  # two windows
        ("v", -100, -100, 5600, [(1000, 2400)]),                # living window
        ("v", 8100, -100, 5600, [(300, 1200)]),                 # kitchen window
    ],
    # (hinge, leaf bearing, arc start, arc end) - every leaf is door_width long
    "doors": [
        ((1200, 3200), 90, 0, 90),      # LIVING   -> BED 1
        ((6400, 3200), 90, 90, 180),    # LIVING   -> BED 2
        ((4500, 500), 180, 90, 180),    # LIVING   -> KITCHEN
        ((6500, 1800), 270, 270, 360),  # KITCHEN  -> BATH
        ((4000, 4900), 180, 180, 270),  # BED 1    -> BED 2
        ((3000, 0), 90, 0, 90),         # entrance
    ],
}

LAYERS = [
    ("WALL-AXIS-OUT", 8, "construction: outer wall centre lines"),
    ("WALL-AXIS-IN", 8, "construction: inner wall centre lines"),
    ("WALLS", 7, "wall faces"),
    ("ROOM-BOUND", 9, "room boundary and floor fill"),
    ("DOORS", 30, "door leaves and swings"),
    ("WINDOWS", 4, "glazing"),
    ("DIMS", 2, "dimensions - made by AutoCAD"),
    ("TEXT", 3, "labels"),
    ("SCHEDULE", 3, "room schedule - areas from AutoCAD"),
    ("BORDER", 7, "sheet border and title block"),
]


# ---------------------------------------------------------------------------
# geometry helpers
# ---------------------------------------------------------------------------
def axis_of(kind, coord, start, end, openings):
    """Normalise a wall to (x1, y1, x2, y2, openings as distances from start).

    Callers give openings in absolute coordinates because that is how a human
    reads a plan; distances are an internal detail and are easy to get wrong.
    """
    ops = [(a - start, b - start) for a, b in openings]
    if kind == "h":
        return (start, coord, end, coord, ops)
    return (coord, start, coord, end, ops)


def frame(axis):
    x1, y1, x2, y2, ops = axis
    length = math.hypot(x2 - x1, y2 - y1)
    ux, uy = (x2 - x1) / length, (y2 - y1) / length
    return x1, y1, ux, uy, length, ops


def wall_segments(axis):
    """The parts of an axis run not covered by an opening."""
    x1, y1, ux, uy, length, ops = frame(axis)
    out, pos = [], 0.0
    for a, b in sorted(ops):
        if a > pos:
            out.append((pos, a))
        pos = max(pos, b)
    if pos < length:
        out.append((pos, length))

    def pt(t):
        return (x1 + ux * t, y1 + uy * t)

    return [(pt(a), pt(b)) for a, b in out]


def opening_ends(axis):
    """Both ends of every opening, with the axis normal."""
    x1, y1, ux, uy, _length, ops = frame(axis)
    nx, ny = -uy, ux

    def pt(t):
        return (x1 + ux * t, y1 + uy * t)

    for a, _b in ops:
        yield pt(a), (nx, ny)
    for _a, b in ops:
        yield pt(b), (nx, ny)


def add_text(msp, pt, height, text, layer, center=False):
    e = msp.add_text(text, height=height,
                     dxfattribs={"layer": layer, "style": "Standard"})
    e.set_placement(pt, align=TextEntityAlignment.MIDDLE_CENTER if center
                    else TextEntityAlignment.LEFT)
    return e


def add_poly(msp, pts, layer, close=True, **kw):
    return msp.add_lwpolyline(pts, close=close, dxfattribs={"layer": layer, **kw})


# ---------------------------------------------------------------------------
# Stage 1 - ezdxf builds the drawing
# ---------------------------------------------------------------------------
def build(plan):
    doc = ezdxf.new("R2010", setup=True)
    msp = doc.modelspace()
    for name, color, _desc in LAYERS:
        doc.layers.add(name, color=color)

    # ezdxf's setup=True installs 26 text styles naming OpenSans and Liberation
    # fonts, none of which exist on the target machine, so AutoCAD substitutes
    # for every one of them and the console fills with substitution warnings.
    # They are all unused. Drop them, and point the one style we do use at a font
    # that definitely exists. The default was "txt", i.e. txt.shx, and this
    # install does not carry that either - so the labels were drawn in whatever
    # AutoCAD fell back to, which is why the labels used to look wrong.
    for ds in doc.dimstyles:             # unlink before deleting the styles
        ds.dxf.dimtxsty = "Standard"
    for style in list(doc.styles):
        if style.dxf.name != "Standard":
            doc.styles.discard(style.dxf.name)
    doc.styles.get("Standard").dxf.font = "arial.ttf"

    doc.header["$INSUNITS"] = 4          # millimetres
    doc.header["$MEASUREMENT"] = 1       # metric
    doc.header["$LTSCALE"] = 20

    # AutoCAD dimensions with the CURRENT dimstyle, and ezdxf's setup=True makes
    # that "EZDXF" - which is configured for a 1:100 *metre* drawing. Its text
    # is 2.5 units tall (invisible on a millimetre plan) and its measurement
    # factor is 100, so a dimension reads "350000" instead of "3500". Setting
    # the $DIMSTYLE header var alone did not change which style AutoCAD picked,
    # so configure every style the drawing carries and the question goes away.
    doc.header["$DIMSTYLE"] = "Standard"
    for ds in doc.dimstyles:
        ds.dxf.dimtxt = 150              # 150 mm text, readable at 1:50
        ds.dxf.dimasz = 100
        ds.dxf.dimexe = 60
        ds.dxf.dimexo = 60
        ds.dxf.dimgap = 40
        ds.dxf.dimscale = 1
        ds.dxf.dimlfac = 1               # we draw in millimetres, no scaling
        ds.dxf.dimdec = 0                # whole millimetres

    # --- rooms first: the wall linework has to draw on top of the fill, and
    # --- the renderer draws in entity order
    handles = {}
    for name, x, y, w, h in plan["rooms"]:
        pts = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
        handles[name] = add_poly(msp, pts, "ROOM-BOUND").dxf.handle
        # a true colour, not an ACI grey: the ACI ramp renders as a heavy
        # mid-grey that swamps the linework underneath
        fill = msp.add_hatch(color=7, dxfattribs={"layer": "ROOM-BOUND"})
        fill.paths.add_polyline_path(pts, is_closed=True)
        fill.set_solid_fill(rgb=(238, 238, 238))
        add_text(msp, (x + w / 2, y + h / 2 + 150), 260, name, "TEXT",
                 center=True)
        add_text(msp, (x + w / 2, y + h / 2 - 220), 160,
                 f"{w} x {h}", "TEXT", center=True)

    # --- wall axes (construction) and opening reveals (permanent) ----------
    for kind, coord, start, end, openings in plan["outer_walls"]:
        axis = axis_of(kind, coord, start, end, openings)
        for a, b in wall_segments(axis):
            add_poly(msp, [a, b], "WALL-AXIS-OUT", close=False)
        t = plan["wall_outer"] / 2
        for (px, py), (nx, ny) in opening_ends(axis):
            msp.add_line((px + nx * t, py + ny * t),
                         (px - nx * t, py - ny * t),
                         dxfattribs={"layer": "WALLS"})
        # glazing for the window openings
        x1, y1, ux, uy, _len, ops = frame(axis)
        gnx, gny = -uy, ux
        for a, b in ops:
            for f in (0.25, -0.25):
                d = f * plan["wall_outer"]
                pa = (x1 + ux * a + gnx * d, y1 + uy * a + gny * d)
                pb = (x1 + ux * b + gnx * d, y1 + uy * b + gny * d)
                msp.add_line(pa, pb, dxfattribs={"layer": "WINDOWS"})

    for kind, coord, start, end, openings in plan["inner_walls"]:
        axis = axis_of(kind, coord, start, end, openings)
        for a, b in wall_segments(axis):
            add_poly(msp, [a, b], "WALL-AXIS-IN", close=False)
        t = plan["wall_inner"] / 2
        for (px, py), (nx, ny) in opening_ends(axis):
            msp.add_line((px + nx * t, py + ny * t),
                         (px - nx * t, py - ny * t),
                         dxfattribs={"layer": "WALLS"})

    # --- door leaves and swings --------------------------------------------
    for hinge, bearing, a0, a1 in plan["doors"]:
        r = math.radians(bearing)
        tip = (hinge[0] + math.cos(r) * plan["door_width"],
               hinge[1] + math.sin(r) * plan["door_width"])
        msp.add_line(hinge, tip, dxfattribs={"layer": "DOORS"})
        msp.add_arc(center=hinge, radius=plan["door_width"],
                    start_angle=a0, end_angle=a1,
                    dxfattribs={"layer": "DOORS"})

    # --- sheet border and title block --------------------------------------
    bx0, by0, bx1, by1 = -1600, -3800, 9600, 7600
    add_poly(msp, [(bx0, by0), (bx1, by0), (bx1, by1), (bx0, by1)], "BORDER")
    add_poly(msp, [(bx0 + 60, by0 + 60), (bx1 - 60, by0 + 60),
                   (bx1 - 60, by1 - 60), (bx0 + 60, by1 - 60)], "BORDER")
    tb = (4000, by0 + 60, bx1 - 60, by0 + 1560)
    add_poly(msp, [(tb[0], tb[1]), (tb[2], tb[1]), (tb[2], tb[3]), (tb[0], tb[3])],
             "BORDER")
    add_text(msp, (tb[0] + 180, tb[3] - 340), 200, plan["drawing_title"], "BORDER")
    add_text(msp, (tb[0] + 180, tb[3] - 700), 170, plan["project"], "BORDER")
    add_text(msp, (tb[0] + 180, tb[3] - 1000), 120,
             f"SCALE {plan['scale']}   ALL DIMENSIONS IN MILLIMETRES", "BORDER")

    # text sizes are kept clear of the sheet edge: AutoCAD's drawing extents
    # grow to fit any string that overruns the border
    add_text(msp, (0, 6300), 240, "AI WROTE THIS. AUTOCAD DREW IT.", "TEXT")
    add_text(msp, (0, 5950), 110,
             "wall centre lines are construction geometry: AutoCAD offsets them, "
             "then erases them", "TEXT")
    return doc, handles


# ---------------------------------------------------------------------------
# Stage 2 - AutoCAD does the drafting
# ---------------------------------------------------------------------------
LISP = """
;; ---- double-line walls: offset every construction axis both ways ----
(defun cad-relayer (e layer / ed)
  (setq ed (entget e))
  (entmod (subst (cons 8 layer) (assoc 8 ed) ed))
)
(defun cad-double (layer dist / ss i e ne a b dx dy len nx ny mx my)
  (setq ss (ssget "_X" (list (cons 0 "LWPOLYLINE") (cons 8 layer))))
  (if (null ss)
    (cad-emit (strcat "MISSING " layer))
    (progn
      (cad-emit (strcat "axes_" layer "=" (itoa (sslength ss))))
      (setq i 0)
      (repeat (sslength ss)
        (setq e (ssname ss i) i (1+ i))
        (setq a (vlax-curve-getStartPoint e)
              b (vlax-curve-getPointAtDist e 1.0)
              dx (- (car b) (car a))
              dy (- (cadr b) (cadr a))
              len (sqrt (+ (* dx dx) (* dy dy)))
              nx (/ (- dy) len)
              ny (/ dx len)
              mx (/ (+ (car a) (car b)) 2.0)
              my (/ (+ (cadr a) (cadr b)) 2.0))
        ;; the side has to be given as a point on that side, not a direction
        (command "_.OFFSET" dist e
                 (list (+ mx (* nx 20.0)) (+ my (* ny 20.0))) "")
        (cad-relayer (entlast) "WALLS")
        (command "_.OFFSET" dist e
                 (list (- mx (* nx 20.0)) (- my (* ny 20.0))) "")
        (cad-relayer (entlast) "WALLS")
      )
      (cad-emit (strcat "offsets_done_" layer))
    )
  )
)
(cad-double "WALL-AXIS-OUT" {outer_half})
(cad-double "WALL-AXIS-IN" {inner_half})

;; ---- measure every room with AutoCAD's own geometry engine ----
(setq rs (ssget "_X" (list (cons 0 "LWPOLYLINE") (cons 8 "ROOM-BOUND"))))
(setq i 0)
(repeat (sslength rs)
  (setq e (ssname rs i) i (1+ i))
  (command "_.AREA" "_O" e)
  (cad-emit (strcat "room=" (cdr (assoc 5 (entget e)))
                    " area=" (rtos (getvar "AREA") 2 1)))
)

;; ---- real DIMENSION objects ----
;; AutoCAD writes the DIM* variables onto each dimension as an override, so
;; configuring the dimstyle in the DXF is not enough: the style it inherits is
;; scaled for a 1:100 *metre* drawing (DIMLFAC 100, DIMTXT 0.25) which makes a
;; dimension read "350000" in text far too small to see. Set the variables
;; explicitly - the same lesson FILLET taught: set the sysvar, never try to
;; answer an option prompt from a script.
(setvar "CLAYER" "DIMS")
(setvar "DIMLFAC" 1)
(setvar "DIMTXT" 150)
(setvar "DIMTXSTY" "Standard")
(setvar "DIMASZ" 100)
(setvar "DIMEXO" 60)
(setvar "DIMEXE" 60)
(setvar "DIMGAP" 40)
(setvar "DIMSCALE" 1)
(setvar "DIMDEC" 0)
{dims}
(cad-emit (strcat "dims="
                  (itoa (sslength (ssget "_X" (list (cons 0 "DIMENSION")))))))

;; ---- the construction geometry has done its job ----
(foreach l (list "WALL-AXIS-OUT" "WALL-AXIS-IN")
  (if (setq s (ssget "_X" (list (cons 8 l))))
    (progn (command "_.ERASE" s "") (cad-emit (strcat "erased " l)))))
(cad-emit (strcat "wall_lines_remaining="
                  (itoa (sslength (ssget "_X" (list (cons 8 "WALLS")))))))
"""


def expected_wall_faces(plan):
    """What the AutoCAD stage must leave on the WALLS layer.

    Two reveals per opening, plus two faces for every construction axis. Worth
    asserting: OFFSET puts its result on the *source* object's layer, so if the
    faces are not re-layered they are deleted along with the construction layer
    and the drawing silently loses all its walls.
    """
    axes = openings = 0
    for kind, coord, start, end, ops in plan["outer_walls"] + plan["inner_walls"]:
        axes += len(wall_segments(axis_of(kind, coord, start, end, ops)))
        openings += len(ops)
    return 2 * openings + 2 * axes


def autocad_stage(plan):
    dims = [
        # overall width and depth, clear of the plan
        '(command "_.DIMLINEAR" "-200,-500" "8200,-500" "4000,-900")',
        '(command "_.DIMLINEAR" "-500,-200" "-500,5600" "-900,2700")',
    ]
    # the structural grid along the bottom
    for a, b in ((0, 4500), (4500, 8000)):
        dims.append(f'(command "_.DIMLINEAR" "{a},-500" "{b},-500" '
                    f'"{(a + b) // 2},-1500")')
    return LISP.format(outer_half=plan["wall_outer"] // 2,
                       inner_half=plan["wall_inner"] // 2,
                       dims="\n".join(dims))


# ---------------------------------------------------------------------------
# Stage 3 - cross-check, then write the schedule
# ---------------------------------------------------------------------------
def finish(src, dst, cad_areas, plan):
    doc = ezdxf.readfile(src)
    msp = doc.modelspace()

    counts = {}
    for e in msp:
        counts[e.dxftype()] = counts.get(e.dxftype(), 0) + 1

    for e in list(msp):                      # replace the placeholder schedule
        if e.dxf.layer == "SCHEDULE":
            msp.delete_entity(e)
    sx = -1540
    total = sum(cad_areas.get(r[0], 0.0) for r in plan["rooms"])
    add_text(msp, (sx + 220, -2060), 150,
             f"ROOM SCHEDULE        TOTAL {total:.2f} m2", "SCHEDULE")
    add_text(msp, (sx + 220, -2300), 120, "ROOM", "SCHEDULE")
    add_text(msp, (sx + 2300, -2300), 120, "AREA m2 (AutoCAD)",
             "SCHEDULE")
    for i, (name, _x, _y, _w, _h) in enumerate(plan["rooms"]):
        y = -2520 - i * 190
        add_text(msp, (sx + 220, y), 150, name, "SCHEDULE")
        add_text(msp, (sx + 2300, y), 150, f"{cad_areas.get(name, 0.0):.2f}",
                 "SCHEDULE")
        msp.add_line((sx + 160, y - 110), (sx + 3600, y - 110),
                     dxfattribs={"layer": "SCHEDULE"})

    doc.saveas(dst)
    # read the dimension text back: it lives in the anonymous geometry block,
    # and it is where a wrong dimlfac shows up as a number 100x too large
    dims = []
    for e in msp:
        if e.dxftype() == "DIMENSION":
            blk = doc.blocks.get(e.dxf.geometry)
            txt = next((x.text for x in blk if x.dxftype() == "MTEXT"), "")
            dims.append((e.get_measurement(), txt))
    return counts, sum(counts.values()), dims


def main():
    OUT.mkdir(exist_ok=True)
    p1 = OUT / "04_floorplan_1_ezdxf.dxf"
    p2 = OUT / "04_floorplan_2_autocad.dxf"
    p3 = OUT / "04_floorplan_3_final.dxf"

    print("=" * 76)
    print("STAGE 1 - ezdxf builds the structure (no AutoCAD, no licence)")
    print("=" * 76)
    doc, handles = build(PLAN)
    doc.saveas(str(p1))
    print(f"  {p1.name}: {p1.stat().st_size:,} bytes, "
          f"{len(LAYERS)} layers, {len(PLAN['rooms'])} rooms, "
          f"{len(PLAN['doors'])} doors")
    print(f"  room polylines: {handles}")

    print()
    print("=" * 76)
    print("STAGE 2 - AutoCAD drafts it (accoreconsole, AutoCAD 2026)")
    print("=" * 76)
    r = server.autocad_run_lisp(autocad_stage(PLAN), input_dwg=str(p1),
                                output_dwg=str(p2), dwg_version="DXF",
                                timeout=900)
    print(f"  ok={r['ok']}  exit={r['exit_code']}")
    for e in r["emitted"]:
        print(f"    {e}")
    if not r["ok"]:
        print("  ERROR:", str(r.get("error"))[:400])
        return
    print(f"  saved {p2.name}: {r['saved']['bytes']:,} bytes")
    faces = int(next(e.split("=")[1] for e in r["emitted"]
                     if e.startswith("wall_lines_remaining="))) 
    want = expected_wall_faces(PLAN)
    print(f"  wall faces on layer WALLS: {faces}, expected {want}")
    assert faces == want, "walls lost - check the OFFSET result layer"

    print()
    print("=" * 76)
    print("STAGE 3 - ezdxf reads AutoCAD's output back and cross-checks")
    print("=" * 76)
    by_handle = {h: n for n, h in handles.items()}
    cad_areas = {}
    for e in r["emitted"]:
        if e.startswith("room="):
            handle = e.split("=")[1].split()[0]
            name = by_handle.get(handle)
            if name:
                cad_areas[name] = float(e.split("area=")[1]) / 1e6
    counts, total_entities, dims = finish(str(p2), str(p3), cad_areas, PLAN)
    print(f"  entity types: {counts}")
    print(f"  total entities: {total_entities}")
    print()
    print("  dimensions AutoCAD created:")
    for meas, txt in sorted(dims):
        print(f"    measures {meas:8.0f} mm, displayed as {txt!r}")
        assert txt and abs(float(txt) - meas) < 0.5, \
            f"dimension text {txt!r} disagrees with measurement {meas}"
    print()
    print(f"  area cross-check - AutoCAD vs ezdxf, two independent engines:")
    print(f"    {'room':9s} {'AutoCAD m2':>12s} {'ezdxf m2':>12s} {'delta':>12s}")
    worst = 0.0
    for name, x, y, w, h in PLAN["rooms"]:
        a, b = cad_areas.get(name, 0.0), w * h / 1e6
        worst = max(worst, abs(a - b))
        print(f"    {name:9s} {a:12.2f} {b:12.2f} {a - b:12.6f}")
    print(f"    largest disagreement: {worst:.6f} m2")

    print()
    print("=" * 76)
    print("STAGE 4 - AutoCAD reopens the finished drawing")
    print("=" * 76)
    chk = server.autocad_run_lisp(
        """
(cad-emit (strcat "reopened_entities=" (itoa (sslength (ssget "_X")))))
(cad-emit (strcat "dims=" (itoa (sslength (ssget "_X" (list (cons 0 "DIMENSION")))))))
(cad-emit (strcat "insunits=" (itoa (getvar "INSUNITS"))))
(cad-emit (strcat "extmin=" (rtos (car (getvar "EXTMIN")) 2 0) ","
                           (rtos (cadr (getvar "EXTMIN")) 2 0)))
(cad-emit (strcat "extmax=" (rtos (car (getvar "EXTMAX")) 2 0) ","
                           (rtos (cadr (getvar "EXTMAX")) 2 0)))
""",
        input_dwg=str(p3), timeout=300)
    for e in chk["emitted"]:
        print(f"    {e}")
    assert chk["ok"], str(chk.get("error"))[:200]
    ex = dict(e.split("=", 1) for e in chk["emitted"])
    mx, my = (float(v) for v in ex["extmax"].split(","))
    assert mx <= 9600 and my <= 7600, f"content overflows the sheet: {ex['extmax']}"

    print()
    print("=" * 76)
    print("STAGE 5 - preview render (ezdxf SVG backend, no AutoCAD)")
    print("=" * 76)
    svg = OUT / "04_floorplan.svg"
    preview(p3, svg)
    print(f"  {svg.name}: {svg.stat().st_size:,} bytes")

    print()
    print(f"artifacts in {OUT}/")
    for p in sorted(OUT.iterdir()):
        print(f"  {p.name:28s} {p.stat().st_size:>10,} bytes")


if __name__ == "__main__":
    main()
