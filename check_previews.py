#!/usr/bin/env python3
"""Audit generated previews for anything that will not be readable on paper.

A preview can be wrong in two ways that both look like "the drawing is blank",
and neither raises an error:

  * a colour too close to the page - the ACI palette is chosen for a black
    screen, so raw cyan/green/yellow on white paper is nearly invisible;
  * a stroke too thin to survive being scaled down to screen size.

This reads the stylesheets inside the SVG previews and checks both, so the
problem is caught here instead of by eye. Exits non-zero if it finds anything.

Run:  python check_previews.py [directory]      (default: out)
"""
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from render import PAPER, _contrast, _is_tint   # noqa: E402

MIN_LINEWORK = 3.0      # contrast below this is not usable for a line
DISPLAY_PX = 800        # reference width the previews are shown at
MIN_STROKE_PX = 0.8     # a hairline disappears on most displays


def _styles(svg: str) -> dict[str, str]:
    return dict(re.findall(r"\.(C\d+)\s*\{([^}]*)\}", svg))


def audit(path: Path) -> list[str]:
    svg = path.read_text(encoding="utf-8")
    bgm = re.search(r'<rect fill="(#[0-9a-fA-F]{6})"', svg)
    bg = bgm.group(1) if bgm else PAPER
    problems = []

    if _contrast(bg, PAPER) > 1.6:
        problems.append(f"background {bg} is not a light page (paper is {PAPER})")

    for cls, decl in _styles(svg).items():
        used = len(re.findall(rf'class="{cls}"', svg))
        for prop in ("stroke", "fill"):
            m = re.search(rf"{prop}:\s*(#[0-9a-fA-F]{{6}})", decl)
            if not m:
                continue
            color = m.group(1).lower()
            if _is_tint(color):
                continue                     # a deliberate wash, not linework
            contrast = _contrast(color, bg)
            if contrast < MIN_LINEWORK:
                problems.append(
                    f"{prop} {color} used by {used} element(s): "
                    f"contrast {contrast:.2f} against {bg} is below {MIN_LINEWORK}")

    vb = re.search(r'viewBox="0 0 ([\d.]+)', svg)
    widths = [float(w) for w in re.findall(r"stroke-width:\s*([\d.]+)", svg)]
    if vb and widths:
        scale = DISPLAY_PX / float(vb.group(1))
        thinnest = min(w for w in widths if w > 0) * scale
        if thinnest < MIN_STROKE_PX:
            problems.append(
                f"thinnest stroke is {thinnest:.2f} px at {DISPLAY_PX} px wide "
                f"(minimum {MIN_STROKE_PX})")
    return problems


def main(argv: list[str]) -> int:
    root = Path(argv[1]) if len(argv) > 1 else Path(__file__).resolve().parent / "out"
    svgs = sorted(root.rglob("*.svg"))
    if not svgs:
        print(f"no SVG previews found under {root}")
        return 1

    failed = 0
    for p in svgs:
        problems = audit(p)
        rel = p.relative_to(root)
        if problems:
            failed += 1
            print(f"FAIL  {rel}")
            for problem in problems:
                print(f"        {problem}")
        else:
            print(f"ok    {rel}")
    print(f"\n{len(svgs) - failed}/{len(svgs)} previews readable on {PAPER}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
