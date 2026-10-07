"""File-level CAD operations via ezdxf.

No AutoCAD, no license, no Windows - this is drawing *file* manipulation.
Reads/writes DXF natively. DWG needs the ODA File Converter (see read_drawing).

Target format defaults to R2010 (AC1024), which is what AutoCAD 2010 writes
natively and what every version since opens.

Self-check:  python3 drawings.py
"""
import contextlib
import io
import logging
import math
import traceback

import ezdxf

# ezdxf attaches a stdout handler and narrates the dictionaries it creates while
# setting up a new document. The MCP server speaks JSON-RPC over stdout, so that
# chatter is not merely noise - it corrupts the protocol stream.
logging.getLogger("ezdxf").setLevel(logging.WARNING)

DEFAULT_VERSION = "R2010"          # AC1024 - AutoCAD 2010's native format
VERSIONS = ("R12", "R2000", "R2004", "R2007", "R2010", "R2013", "R2018")


class DrawingError(RuntimeError):
    pass


def _open(path: str, dxfversion: str):
    if not path:
        # validate here rather than letting ezdxf raise DXFVersionError, which
        # is not a DrawingError and would escape the tool boundary as a raw
        # traceback - the caller just gets told which versions are valid
        version = dxfversion.strip().upper()
        if version not in VERSIONS:
            raise DrawingError(
                f"unsupported dxfversion {dxfversion!r} - use one of: "
                f"{', '.join(VERSIONS)}")
        return ezdxf.new(version, setup=True)
    if path.lower().endswith(".dwg"):
        raise DrawingError(
            "ezdxf cannot read DWG directly. Convert first with the ODA File "
            "Converter and the ezdxf.addons.odafc addon, or ask whoever "
            "produced the file for a DXF.")
    try:
        return ezdxf.readfile(path)
    except IOError as e:
        raise DrawingError(f"cannot read {path}: {e}") from e
    except ezdxf.DXFStructureError as e:
        raise DrawingError(f"{path} is not a valid DXF: {e}") from e


def blank_dxf_bytes(dxfversion: str = DEFAULT_VERSION) -> bytes:
    """A blank drawing as ASCII DXF bytes.

    For the accoreconsole backend. accoreconsole *requires* an input drawing
    (`/i`) - with no `/i` it exits 53 and does nothing at all - so "create from
    scratch" has to start from a real file. It opens DXF happily, so no DWG
    conversion step is needed anywhere in the pipeline.
    """
    sink = io.StringIO()
    ezdxf.new(dxfversion, setup=True).write(sink)
    return sink.getvalue().encode("utf-8")


def run(code: str, path: str = "", save_as: str = "",
        dxfversion: str = DEFAULT_VERSION) -> dict:
    """Execute Python against a drawing.

    `code` is the scripting surface, exactly as AutoLISP is for accoreconsole -
    the model writes the language rather than us inventing a typed entity API.
    Pre-bound names:
        doc          ezdxf Drawing (opened from `path`, or new if empty)
        msp          doc.modelspace()
        ezdxf        the module itself
        emit(*args)  collect a result, returned in "emitted"
    """
    doc = _open(path, dxfversion)
    msp = doc.modelspace()
    emitted: list[str] = []

    def emit(*args):
        emitted.append(" ".join(str(a) for a in args))

    scope = {"doc": doc, "msp": msp, "ezdxf": ezdxf, "emit": emit,
             "DEFAULT_VERSION": dxfversion}

    stdout = io.StringIO()
    error = None
    try:
        with contextlib.redirect_stdout(stdout):
            exec(compile(code, "<drawing>", "exec"), scope)
    except Exception:
        error = traceback.format_exc(limit=4)

    saved = None
    if save_as and error is None:
        try:
            doc.saveas(save_as)
            saved = save_as
        except Exception as e:
            error = f"save failed: {e}"

    return {
        "ok": error is None,
        "emitted": emitted,
        "stdout": stdout.getvalue()[-4000:],
        "error": error,
        "saved": saved,
    }


def summary(path: str) -> dict:
    """Structural overview of a drawing, so an agent can orient itself."""
    doc = _open(path, "")
    msp = doc.modelspace()

    counts: dict[str, int] = {}
    for e in msp:
        counts[e.dxftype()] = counts.get(e.dxftype(), 0) + 1

    out = {
        "file": path,
        "dxfversion": doc.dxfversion,
        "units": doc.header.get("$INSUNITS", 0),
        "layers": sorted(l.dxf.name for l in doc.layers),
        "entity_counts": dict(sorted(counts.items(), key=lambda kv: -kv[1])),
        "total_entities": sum(counts.values()),
        "blocks": sorted(b.name for b in doc.blocks if not b.name.startswith("*")),
    }
    try:
        # Returns a ezdxf.math.BoundingBox, NOT an Extents object. Note that its
        # `is_empty` flag is unreliable in ezdxf 1.4.4 - it reads True even with
        # valid bounds - so gate on `has_data` and guard against inf instead.
        from ezdxf import bbox
        ext = bbox.extents(msp)
        # Vec3 supports integer indexing but NOT slicing.
        corners = [ext.extmin[0], ext.extmin[1], ext.extmax[0], ext.extmax[1]]
        if ext.has_data and all(math.isfinite(v) for v in corners):
            out["extents"] = {
                "min": [round(ext.extmin[0], 3), round(ext.extmin[1], 3)],
                "max": [round(ext.extmax[0], 3), round(ext.extmax[1], 3)],
            }
        else:
            out["extents"] = None
    except Exception as e:
        # Never hide a real failure behind a bare None.
        out["extents"] = None
        out["extents_error"] = f"{type(e).__name__}: {e}"
    return out


def self_check():
    import tempfile, os

    with tempfile.TemporaryDirectory() as d:
        f = os.path.join(d, "t.dxf")

        r = run('''
msp.add_line((0, 0), (100, 0))
msp.add_circle((50, 25), radius=25)
msp.add_lwpolyline([(0, 0), (100, 0), (100, 60), (0, 60)], close=True)
doc.layers.add("WALLS", color=1)
for i in range(5):
    msp.add_text(f"PT{i}", height=2.5).set_placement((i * 10, 50))
emit("made", len(list(msp)), "entities")
''', save_as=f)
        assert r["ok"], r["error"]
        assert r["saved"] == f
        assert r["emitted"] == ["made 8 entities"], r["emitted"]

        # re-open from disk: proves the file is valid, not just in-memory
        r2 = run("emit('walls', 'WALLS' in [l.dxf.name for l in doc.layers])", path=f)
        assert r2["emitted"] == ["walls True"], r2["emitted"]

        # modify an existing file
        r3 = run("msp.add_line((0, 60), (100, 60))\nemit(len(list(msp)))",
                 path=f, save_as=f)
        assert r3["ok"] and r3["emitted"] == ["9"], r3

        s = summary(f)
        assert s["entity_counts"]["LINE"] == 2, s["entity_counts"]
        assert s["entity_counts"]["CIRCLE"] == 1
        assert s["entity_counts"]["LWPOLYLINE"] == 1
        assert s["entity_counts"]["TEXT"] == 5
        assert s["total_entities"] == 9
        assert "WALLS" in s["layers"]
        assert s["extents"]["min"] == [0.0, 0.0], s["extents"]
        assert s["extents"]["max"] == [100.0, 60.0], s["extents"]

        # R2010 header round-trip
        with open(f, "rb") as fh:
            assert b"AC1024" in fh.read(200), "not written as R2010"

        # failure is reported, not raised, and nothing is saved
        bad = os.path.join(d, "bad.dxf")
        r4 = run("nope(", save_as=bad)
        assert not r4["ok"] and r4["error"] and r4["saved"] is None
        assert not os.path.exists(bad), "saved despite error"

    print("drawings.py self-check: OK "
          "(create, persist, reopen, modify, summary, R2010, error handling)")


if __name__ == "__main__":
    self_check()
