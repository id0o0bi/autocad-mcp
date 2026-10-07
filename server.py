# /// script
# requires-python = ">=3.10"
# dependencies = ["mcp>=2,<3", "ezdxf>=1.0"]
# ///
"""MCP server for CAD work, with two independent backends.

1. drawing_*  - ezdxf. Creates and edits drawing FILES. No AutoCAD, no licence,
                no Windows. Writes DXF in any version from R12 to R2018, and
                reads back anything ezdxf can open. Millisecond turnaround, so
                this is the backend for generation and for analysis.

2. autocad_*  - accoreconsole.exe, spawned as a child process on this machine.
                The real AutoCAD engine, for what only AutoCAD can do: native
                DWG, hatching, real DIMENSION objects, plotting, and the whole
                command set. Requires AutoCAD 2013 or newer, and costs one
                process launch per call (~0.3 s, measured on AutoCAD 2026).

The two compose in either direction - AutoCAD opens DXF, and ezdxf reads back
what AutoCAD wrote - so one job can pass through both engines.
cases/04_floorplan.py is that pipeline end to end.

Both backends expose a scripting language rather than a typed entity API
(Python and AutoLISP respectively): the model already knows both, and one
general tool composes far better than dozens of narrow ones.

Run standalone:  uv run server.py
"""
import re
import sys
from pathlib import Path

from mcp.server.mcpserver import MCPServer

import accore
import drawings

mcp = MCPServer("autocad")

SENTINEL = "CADMCP|"

# SAVEAS behaviour, all verified against AutoCAD 2026. The keyword and the
# filename extension are not independent, and getting it wrong fails silently:
#   "DXF"                -> DXF, always AC1032 (R2018). It asks for a decimal
#                           precision; omit that answer and accoreconsole HANGS
#                           instead of erroring.
#   "2010"/"2018"/...    -> DWG at that version, and AutoCAD appends ".dwg".
#   numeric keyword + a .dxf name -> writes nothing at all, exit code 0.
# So a numeric keyword can never produce DXF, and the output name must carry
# the extension that matches the keyword.
DXF_PRECISION = "16"

PRELUDE = r"""(vl-load-com)
(setvar "FILEDIA" 0)
(setvar "CMDDIA" 0)
(setq cad-dir "{gdir}/")
(setq cad-in  "{gdir}/{inname}")
(setq cad-out "{gdir}/{outname}")
(setq cad-save {save})
(defun cad-emit (s)
  (setq s (vl-string-translate (strcat (chr 10) (chr 13)) "  " s))
  (princ (strcat (chr 10) "CADMCP|" s (chr 10))))
"""

EPILOGUE = r"""
(if cad-save
  (if (= (strcase "{ver}") "DXF")
    (command "_.SAVEAS" "DXF" "{prec}" cad-out)
    (command "_.SAVEAS" "{ver}" cad-out)))
(princ (strcat (chr 10) "CADMCP|__DONE__" (chr 10)))
"""


@mcp.tool()
def drawing_run(code: str, path: str = "", save_as: str = "",
                dxfversion: str = "R2010") -> dict:
    """Create or edit a CAD drawing by running Python with ezdxf.

    Runs in-process - no AutoCAD, no licence, no process launch. Use this for
    creating drawings from scratch and for reading or modifying existing ones.

    Pre-bound names inside `code`:
        doc          ezdxf Drawing (opened from `path`, or a new empty one)
        msp          doc.modelspace()
        ezdxf        the module itself
        emit(*args)  collect a value; returned in "emitted"

    Format versions: R12, R2000, R2004, R2007, R2010, R2013, R2018.
    R2010 (AC1024) is the default - it is what AutoCAD 2010 writes natively
    and every later release opens.

    Args:
        code: Python source, e.g. msp.add_line((0,0),(100,0))
        path: existing .dxf to open. Empty creates a new drawing.
        save_as: .dxf to write to. Empty means do not save. Nothing is saved
                 if the code raises.
        dxfversion: format for a NEW drawing (ignored when opening `path`).
    """
    try:
        return drawings.run(code, path, save_as, dxfversion)
    except drawings.DrawingError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        # a tool call should always answer with a structured error rather than
        # a traceback, whatever the caller passed in
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


@mcp.tool()
def drawing_summary(path: str) -> dict:
    """Structural overview of a drawing: layers, entity counts, extents, blocks.

    Call this first when you are handed an existing drawing you have not seen -
    it is far cheaper than reading the file and tells you what is in it.
    """
    try:
        return drawings.summary(path)
    except drawings.DrawingError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


@mcp.tool()
def autocad_run_lisp(
    code: str,
    input_dwg: str = "",
    output_dwg: str = "",
    dwg_version: str = "2018",
    timeout: int = 180,
    keep_workdir: bool = False,
) -> dict:
    """Run AutoLISP in AutoCAD's own engine (accoreconsole.exe) on this machine.

    This is headless: no GUI, no dialog boxes, and it is a separate process from
    any AutoCAD window the user has open. Use command-line forms of commands
    (leading "_" and explicit arguments), never dialog-driven ones.

    Pre-bound inside `code`:
        cad-dir   scratch dir, forward slashes, trailing "/"
        cad-in    path of the opened input drawing
        cad-out   path the result is saved to
        cad-emit  (cad-emit "text") -> appears in the returned `emitted` list

    Args:
        code: AutoLISP source, e.g. (command "_.LINE" "0,0" "100,100" "").
        input_dwg: local drawing to open - .dxf or .dwg both work. Empty starts
                   from a blank R2010 drawing, generated by the ezdxf side.
        output_dwg: local file to write the result to - .dwg for a year
                    keyword, .dxf for "DXF". Empty means do not save.
        dwg_version: SAVEAS format keyword. A year ("2018", "2013", "2010")
                     saves DWG at that version. "DXF" saves DXF - but AutoCAD
                     only ever writes the *current* DXF version, so DXF output
                     is always AC1032 (R2018). Re-target it with ezdxf if an
                     older DXF is needed; that needs no external converter.
        timeout: seconds to allow accoreconsole to run.
        keep_workdir: keep the scratch dir for debugging.
    """
    try:
        accore_bin = accore.find_accoreconsole()
        _, wdir = accore.mkwork()
    except accore.ToolError as e:
        return {"ok": False, "error": str(e)}
    # LISP wants forward slashes; the scratch path is handed over verbatim.
    gdir = wdir.replace("\\", "/")
    try:
        # accoreconsole REQUIRES /i. With no /i it exits 53 having done nothing
        # (verified against AutoCAD 2026) - so "create from scratch" still has
        # to hand it a real file, hence the blank drawing below. It opens DXF
        # fine, so the extension of the caller's input is preserved rather than
        # pretending everything is a .dwg.
        in_name = f"in{Path(input_dwg).suffix.lower()}" if input_dwg else "in.dxf"
        out_name = "out.dxf" if dwg_version.strip().upper() == "DXF" else "out.dwg"
        in_local = f"{wdir}{accore.sep}{in_name}"
        if input_dwg:
            accore.write_file(in_local, Path(input_dwg).read_bytes())
        else:
            accore.write_file(in_local, drawings.blank_dxf_bytes("R2010"))

        lisp = PRELUDE.format(gdir=gdir, inname=in_name, outname=out_name,
                              save="T" if output_dwg else "nil") \
            + code + "\n" + EPILOGUE.format(ver=dwg_version, prec=DXF_PRECISION)
        accore.write_file(f"{wdir}{accore.sep}job.lsp", lisp.encode("utf-8"))
        # SECURELOAD defaults to 1, which makes AutoCAD silently cancel
        # (load ...) with "file load cancelled" and no non-zero exit code. A
        # .scr line is fed to the command line rather than loaded, so it is not
        # itself restricted - dropping the sysvar here is what lets the load
        # through. Verified on AutoCAD 2026: before=1, after=0, load succeeds.
        accore.write_file(
            f"{wdir}{accore.sep}job.scr",
            f'(setvar "SECURELOAD" 0)\n(load "{gdir}/job.lsp")\n'.encode())

        # Absolute paths for both switches: a relative /s exits 0 having done
        # nothing at all, which is the nastiest failure mode here.
        argv = [accore_bin, "/i", in_local,
                "/s", f"{wdir}{accore.sep}job.scr"]

        # accoreconsole emits UTF-16LE - see accore.run's `encoding` note.
        try:
            rc, out, err = accore.run(argv, timeout=timeout, encoding="utf-16-le")
        except accore.ToolError:
            # accoreconsole has no internal timeout: a script that fails to
            # answer a prompt waits forever, holding a licence. accore.run's
            # timeout is the only thing that ends it, so the orphan has to be
            # reaped here rather than left to poison the next call.
            accore.kill_orphans()
            return {"ok": False, "exit_code": None, "emitted": [],
                    "stdout": "", "stderr": "", "work_dir": wdir,
                    "error": f"accoreconsole did not finish within {timeout}s - "
                             f"almost always a script that did not answer every "
                             f"prompt. Raise the timeout or answer the prompt."}
        # accoreconsole emits CRLF, so a captured group keeps a trailing \r and
        # `"__DONE__" in emitted` would never match - ok would always be False.
        emitted = [m.group(1).strip() for m in
                   re.finditer(rf"^{re.escape(SENTINEL)}(.*)$", out, re.M)]

        result = {
            # Exit code 0 is not success: a script that dies on a LISP error
            # still exits 0, it just never reaches the terminator. This is why
            # `ok` is keyed on the sentinel as well.
            "ok": rc == 0 and "__DONE__" in emitted,
            "exit_code": rc,
            "emitted": [e for e in emitted if e != "__DONE__"],
            "stdout": out[-8000:],
            "stderr": err[-2000:],
            "work_dir": wdir,
        }
        if output_dwg:
            try:
                data = accore.read_file(f"{wdir}{accore.sep}{out_name}")
                Path(output_dwg).write_bytes(data)
                result["saved"] = {"path": output_dwg, "bytes": len(data)}
            except accore.ToolError as e:
                result["ok"] = False
                result["saved"] = None
                result["save_error"] = str(e)
        return result
    finally:
        if not keep_workdir:
            accore.cleanup(wdir)


@mcp.tool()
def autocad_status() -> dict:
    """Which AutoCAD this server drives, whether it is usable, and its build."""
    st: dict = {"runs_on": "this machine, as a child process"}
    try:
        st["accoreconsole"] = accore.find_accoreconsole()
    except accore.ToolError as e:
        st["accoreconsole"] = None
        st["error"] = str(e)
        st["hint"] = ("accoreconsole.exe ships with AutoCAD 2013 and newer - "
                      "install AutoCAD, or set CAD_ACCORECONSOLE to its full "
                      "path.")
        return st
    if sys.platform == "win32":
        _, out, _ = accore.run([
            "powershell.exe", "-NoProfile", "-Command",
            "(Get-ItemProperty 'HKLM:\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion')"
            ".EditionID",
        ])
        st["windows_edition"] = out.strip()
    st["python"] = sys.version.split()[0]
    return st


@mcp.tool()
def autocad_accoreconsole_switches() -> dict:
    """Return accoreconsole.exe's real /? output, so switch usage is never guessed."""
    try:
        accore_bin = accore.find_accoreconsole()
    except accore.ToolError as e:
        return {"ok": False, "error": str(e)}
    rc, out, err = accore.run([accore_bin, "/?"], timeout=60,
                              encoding="utf-16-le")
    # NOTE: /? is not a real switch - accoreconsole prints the usage and exits
    # 53. That is expected; treat the text as the answer, not the exit code.
    return {"ok": True, "exit_code": rc, "help": (out + err)[-6000:]}


if __name__ == "__main__":
    mcp.run()
