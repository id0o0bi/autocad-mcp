"""Preview rendering: DXF -> SVG (or PNG), with no AutoCAD and no licence.

`preview()` picks the backend from the output suffix:

    .svg   ezdxf's own SVG backend. Vector, small, and it needs nothing beyond
           Pillow - no matplotlib, no font lookup (text is emitted as filled
           paths, so a preview looks the same on any machine). Default choice.
    .png   ezdxf.addons.drawing + matplotlib. Raster, so pick the dpi.

A drawing file describes geometry, not appearance: the colours in it are ACI
indices, and an ACI index means whatever the *viewer* decides. AutoCAD's model
space is black, so the palette is chosen for a black screen - and on white paper
several of those entries are very nearly invisible:

    ACI 4  cyan    #00ffff   contrast on white  1.25
    ACI 3  green   #00ff00                     1.37
    ACI 2  yellow  #ffff00                     1.07
    ACI 9  grey    #c0c0c0                     1.82
    ACI 30 orange  #ff7f00                     2.53

so a preview that renders the raw ACI values is mostly blank paper. The DXF
itself is left untouched: those ACI values are the standard ones a CAD user
expects to find in the file, and the background is not drawing data at all -
`#212830` is ezdxf's stand-in for AutoCAD's dark model space, `MODEL_SPACE_BG_COLOR`
in `ezdxf.addons.drawing.properties`, and it is a per-user display setting in
AutoCAD rather than anything stored in a DWG.

AutoCAD's own answer to the colour problem is the plot style table, and this
machine has plenty of them - `acad.ctb`, `monochrome.ctb`, `Grayscale.ctb`, and
a dozen office `!黑白线型*.ctb` variants whose existence is the very same
complaint. Two things are worth knowing before reaching for one:

  * `acad.ctb` deliberately preserves the object colour, so it does *not* fix
    legibility - ACI 4 still plots as cyan.
  * `RenderContext.set_current_layout(layout, ctb)` accepts a plot style table
    but has **no effect on model space**. Verified against both `acad.ctb` and
    `monochrome.ctb` from AutoCAD 2026: all three cases render byte-identical
    colour sets.

So the mapping is done here instead. `_paper_color()` keeps the layer colours
recognisable while making them readable; `mono=True` drops colour altogether,
which is what the black-and-white tables are for and is the usual convention
for issued drawings.

Three more traps, all of which produce a *silently wrong* picture:

  * **The paper has to be asked for in the Configuration.**
    `Frontend.draw_layout()` calls `backend.set_background()` itself, from the
    config, and it does so *after* whatever the caller set - so a
    `backend.set_background("#ffffff")` before the draw is silently discarded.
    Use `background_policy=BackgroundPolicy.WHITE`.
  * **Do not reach for `ColorPolicy.COLOR_SWAP_BW`.** It swaps black and white
    unconditionally, and ACI 7 already resolves to black on a light background -
    so the swap turns every colour-7 entity pure white, i.e. exactly the
    linework you were trying to protect. Plain `ColorPolicy.COLOR` is correct
    here; `_paper_color()` handles the rest.
  * **Stroke width is a real-world measurement, and the SVG viewBox is always
    1e6 units wide.** A 0.25 mm stroke on a 3 m drawing shown at 800 px comes out
    at 0.09 px - in the file, absent from the screen. `_display_stroke()`
    rescales every stroke by one factor, so real lineweight differences survive.
    `Configuration(lineweight_policy=...)` does not help: under the default
    ABSOLUTE policy the setting is ignored entirely, and SVGBackend's
    `fixed_stroke_width` does nothing either.

The drawing addon itself imports PIL at module import time, so Pillow is not
optional even on the SVG path.
"""
import re
from pathlib import Path

PAPER = "#ffffff"          # the page every preview is drawn on
MIN_CONTRAST = 4.0         # target for linework; WCAG's small-text threshold

# Standard ACI entries remapped for white paper.
_PAPER_COLORS = {
    "#ff0000": "#cc2222",   # ACI 1   red
    "#ffff00": "#8a6a00",   # ACI 2   yellow  -> dark amber
    "#00ff00": "#1a7f37",   # ACI 3   green
    "#00ffff": "#0e7490",   # ACI 4   cyan    -> teal
    "#0000ff": "#1d4ed8",   # ACI 5   blue
    "#ff00ff": "#a21caf",   # ACI 6   magenta
    "#808080": "#444c5c",   # ACI 8   dark grey
    "#c0c0c0": "#7b8494",   # ACI 9   light grey
    "#ff7f00": "#b45309",   # ACI 30  orange
}


def _rgb(color: str) -> tuple[int, int, int]:
    return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))       # type: ignore


def _hex(r: float, g: float, b: float) -> str:
    return "#%02x%02x%02x" % (round(r), round(g), round(b))


def _linear(channel: float) -> float:
    channel /= 255.0
    return channel / 12.92 if channel <= 0.03928 else ((channel + 0.055) / 1.055) ** 2.4


def _luminance(color: str) -> float:
    r, g, b = _rgb(color[:7])
    return 0.2126 * _linear(r) + 0.7152 * _linear(g) + 0.0722 * _linear(b)


def _contrast(a: str, b: str) -> float:
    la, lb = _luminance(a), _luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def _is_tint(color: str) -> bool:
    """A near-neutral very light colour: a deliberate wash, not linework.

    Room and area fills are meant to be pale - subjecting them to a linework
    contrast rule would turn a floor wash into a heavy grey block.
    """
    r, g, b = _rgb(color[:7])
    return max(r, g, b) - min(r, g, b) <= 16 and min(r, g, b) >= 0xdc


def _paper_color(color: str, page: str = PAPER) -> str:
    """Return `color` adjusted to be legible on `page`, alpha preserved."""
    body = color[:7].lower()
    alpha = color[7:]
    if body in _PAPER_COLORS:
        return _PAPER_COLORS[body] + alpha
    if _is_tint(body) or _contrast(body, page) >= MIN_CONTRAST:
        return color
    r, g, b = _rgb(body)
    for k in (0.80, 0.65, 0.50, 0.40, 0.30, 0.20, 0.12, 0.06):
        candidate = _hex(r * k, g * k, b * k)
        if _contrast(candidate, page) >= MIN_CONTRAST:
            return candidate + alpha
    return "#000000" + alpha


def _load(dxf_path, mono=False):
    import ezdxf
    from ezdxf.addons.drawing import RenderContext
    from ezdxf.addons.drawing.config import (BackgroundPolicy, ColorPolicy,
                                             Configuration)

    class PaperContext(RenderContext):
        """RenderContext that remaps screen colours for white paper."""

        def resolve_color(self, entity, *, resolved_layer=None):
            color = super().resolve_color(entity, resolved_layer=resolved_layer)
            return "#000000" if mono else _paper_color(color)

    doc = ezdxf.readfile(str(dxf_path))
    cfg = Configuration(color_policy=ColorPolicy.COLOR,
                        background_policy=BackgroundPolicy.WHITE)
    return doc, PaperContext(doc), cfg


def _page(doc, pad_frac=0.015):
    """An SVG page sized to the drawing, so `fit_page` needs no guesswork."""
    from ezdxf import bbox
    from ezdxf.addons.drawing import layout

    size = bbox.extents(doc.modelspace()).size
    pad = max(size.x, size.y) * pad_frac + 1.0
    return layout.Page(size.x + 2 * pad, size.y + 2 * pad,
                       units=layout.Units.mm,
                       margins=layout.Margins(pad, pad, pad, pad))


def _display_stroke(svg: str, stroke_px: float, display_px: float) -> str:
    """Scale every stroke width so the thinnest reads as `stroke_px` on screen."""
    m = re.search(r'viewBox="0 0 ([\d.]+)', svg)
    widths = [float(w) for w in re.findall(r"stroke-width:\s*([\d.]+)", svg)]
    if not m or not widths:
        return svg
    thinnest = min(w for w in widths if w > 0)
    factor = (stroke_px * float(m.group(1)) / display_px) / thinnest
    return re.sub(r"stroke-width:\s*([\d.]+)",
                  lambda mm: f"stroke-width: {float(mm.group(1)) * factor:.1f}",
                  svg)


def render_svg(dxf_path, out_path, stroke_px=1.4, display_px=800, mono=False):
    from ezdxf.addons.drawing import Frontend, layout, svg

    doc, ctx, cfg = _load(dxf_path, mono=mono)
    backend = svg.SVGBackend()
    Frontend(ctx, backend, config=cfg).draw_layout(doc.modelspace(),
                                                   finalize=True)
    data = backend.get_string(_page(doc),
                              settings=layout.Settings(fit_page=True))
    if stroke_px:
        data = _display_stroke(data, stroke_px, display_px)
    Path(out_path).write_text(data, encoding="utf-8")
    return str(out_path)


def render_png(dxf_path, out_path, width_in=16, height_in=12, dpi=120,
               mono=False):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from ezdxf.addons.drawing import Frontend
    from ezdxf.addons.drawing.matplotlib import MatplotlibBackend

    doc, ctx, cfg = _load(dxf_path, mono=mono)
    fig = plt.figure(figsize=(width_in, height_in), dpi=dpi)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_axis_off()
    Frontend(ctx, MatplotlibBackend(ax), config=cfg).draw_layout(
        doc.modelspace(), finalize=True)
    fig.set_size_inches(width_in, height_in)   # finalize() resized it; undo
    fig.savefig(str(out_path), dpi=dpi, facecolor=PAPER, bbox_inches=None)
    plt.close(fig)
    return str(out_path)


def preview(dxf_path, out_path, **kw):
    """Render `dxf_path` to `out_path`; backend chosen by the suffix."""
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.suffix.lower() == ".svg":
        return render_svg(dxf_path, out, **kw)
    if out.suffix.lower() == ".png":
        return render_png(dxf_path, out, **kw)
    raise ValueError(f"unknown preview format: {out.suffix!r} (use .svg or .png)")


if __name__ == "__main__":
    import sys

    args = sys.argv[1:]
    mono = "--mono" in args
    args = [a for a in args if a != "--mono"]
    if len(args) < 2:
        print(__doc__.strip().splitlines()[0])
        print("usage: python render.py [--mono] drawing.dxf out.svg|out.png ...")
        raise SystemExit(2)
    for dst in args[1:]:
        print("wrote", preview(args[0], dst, mono=mono))
