# autocad-mcp

Make your AI assistant actually draw CAD.

[中文](README.zh-CN.md) · English

A live product page — all four example drawings, feature notes and install steps — is in the [`site/`](site/) directory.

This is a standard MCP server (MCP tool) with nothing bespoke about it; any MCP-capable AI client can use it. It lets an assistant generate drawings from your instructions, batch-edit existing drawings, audit them for problems, and drive a real AutoCAD engine for dimensions, hatching and plotting.

---

## What it can do

**Parametric batch output** — give it a spec table and it produces a whole set of drawings in one pass. Part families, standard components, hole patterns, drawing frames, title blocks and parts lists all come out complete; change one number and the whole drawing is redrawn.

**Batch-edit existing drawings** — change layers, colours and lineweights in bulk; replace blocks and update title blocks; convert versions (e.g. 2018 down to 2013); process an entire folder at once.

**Read and audit drawings** — find duplicate lines, zero-length lines, contours that look closed but aren't, entities left on layer 0, text too small to print, and geometry that runs outside the frame. Outputs a problem list and circles and numbers each issue on the drawing.

**Manufacturing and nesting** — nest a bill of materials onto sheet stock, report material utilisation, and output a cut sheet ready to hand over.

**Extract data from drawings** — layer structure, entity counts, drawing extents, areas, lengths, block-reference statistics, organised into a table for the next step.

**AutoCAD-only capabilities** — native DWG read/write, real dimensions and hatching, plotting and batch publishing.

---

## For AI assistants: install and configuration

> Users may say to you "read the README.md in this directory and set it up for me". This is the information you need; work through it in order.

### 1. Requirements

- Python 3.10 or newer. Check first: `python --version`
- Two required packages: `mcp`, `ezdxf`
- `Pillow` — needed only to generate drawing previews or to run the examples under `cases/`
- `matplotlib` — optional, only needed for PNG (rather than SVG) previews
- AutoCAD 2013 or newer — needed **only** for the `autocad_*` tools. Generation, editing and auditing all work without AutoCAD.

### 2. Install dependencies

```
pip install "mcp>=2,<3" ezdxf Pillow
```

`mcp` and `ezdxf` are the server's entire dependency set; with just these two it runs:

```
pip install "mcp>=2,<3" ezdxf
```

`Pillow` is only needed for previews (the examples and `render.py` use it). Whichever Python interpreter you use, the MCP config's `command` must point to that same interpreter. On Windows it's best to use the interpreter's full path:

```
where python
```

### 3. Write the MCP config

Add the block below to your client's MCP config file. **Change three things**: `command` is the interpreter you confirmed above, and `args` holds the full path to `server.py`.

```json
{
  "mcpServers": {
    "autocad": {
      "command": "C:/Python313/python.exe",
      "args": ["D:/tools/autocad-mcp/server.py"],
      "cwd": "D:/tools/autocad-mcp"
    }
  }
}
```

Use a full path in `args`; `cwd` is just insurance — some clients don't pass a working directory, and `server.py` locates its sibling modules relative to its own file, so the full path always works. Backslashes in paths must be written as `/` or `\\`; a single `\` is treated as an escape by JSON.

Config file locations differ per client; put it in the right place:

| Client | Config file |
|---|---|
| Claude Desktop | `%APPDATA%\Claude\claude_desktop_config.json` (macOS: `~/Library/Application Support/Claude/`) |
| Cursor | `~/.cursor/mcp.json` |
| Cline / VS Code | the client's MCP settings UI, or workspace `.vscode/mcp.json` |
| pi | `~/.pi/agent/mcp.json` |

If your client isn't listed, follow its documentation for "adding an MCP server" and supply the same `command` / `args` / `cwd`.

### 4. Verify

Restart the client (or reload the MCP server) after configuring, then call `autocad_status`:

- Returns an `accoreconsole` path → the AutoCAD side works too; full functionality.
- Returns `accoreconsole: null` and a message → drawing generation, editing and auditing all work normally; only the tools that need real AutoCAD are unavailable. This is not a fault; tell the user so.

If the tool list doesn't show any `autocad_*` tools at all, check the client's MCP log first: usually `command` points at the wrong interpreter, or `mcp` is installed in a different Python. Verify with `<that interpreter> -c "import mcp, ezdxf"`.

You can also self-check without a client, from this directory:

```
python -c "import server; print(server.autocad_status())"
```

### 5. Optional: AutoCAD in a non-default location

Normally it's found automatically. If the user has a portable build or a non-standard install, add this to the config:

```json
{
  "mcpServers": {
    "autocad": {
      "command": "C:/Python313/python.exe",
      "args": ["D:/tools/autocad-mcp/server.py"],
      "env": {
        "CAD_ACCORECONSOLE": "D:/AutoCAD/accoreconsole.exe"
      }
    }
  }
}
```

To change the temp directory (default is under the system temp dir), add a `"CAD_WORKDIR"` entry to `env` as well.

---

## Tools

| Tool | Purpose | Needs AutoCAD |
|---|---|---|
| `drawing_run(code, path, save_as, dxfversion)` | Generate or edit drawings with Python + ezdxf | No |
| `drawing_summary(path)` | Quickly see a drawing: layers, entity counts, extents, blocks | No |
| `autocad_run_lisp(code, input_dwg, output_dwg, dwg_version, timeout, keep_workdir)` | Execute inside the real AutoCAD engine | Yes |
| `autocad_status()` | Check whether AutoCAD is available | — |
| `autocad_accoreconsole_switches()` | Query the available accoreconsole switches | Yes |

A few usage conventions:

- Inside `drawing_run` you can use `doc`, `msp`, `ezdxf`, and `emit(...)` to return information. If the code raises, **no half-finished file is written**, so retrying is safe.
- `dxfversion` defaults to `R2010`. Options: `R12 / R2000 / R2004 / R2007 / R2010 / R2013 / R2018`.
- For `autocad_run_lisp`, an empty `input_dwg` starts from a blank drawing; `dwg_version` as a year (e.g. `"2013"`, `"2018"`) saves DWG, `"DXF"` saves DXF.
- **The `output_dwg` extension must match `dwg_version`**: use `.dwg` for a year, `.dxf` for `"DXF"`. Writing `dwg_version="2013"` with `output_dwg="x.dxf"` won't error, but `x.dxf` will actually contain DWG data, which is very confusing to open later.
- For large drawings or complex scripts, raise `timeout`.
- When debugging, use `keep_workdir=True`; the tool keeps the intermediate directory so you can inspect the generated script and AutoCAD's raw output.
- `drawing_run` executes the Python code you give it, with the privileges of the user running the server. That's exactly why it's flexible, but don't expose the server to untrusted callers.

## Examples

`cases/` has four runnable examples. From this directory:

```
python cases/run_all.py
```

This produces drawings and previews in `out/`. The full-page results are in `site/index.html`; open it in a browser — the images are vector and can be zoomed for detail.

| Example | Content |
|---|---|
| `01_parts.py` | Generate a flange part-family drawing from a spec table, with frame and parts list |
| `02_nesting.py` | Nest a BOM onto sheet stock and report utilisation |
| `03_audit.py` | Audit a drawing and output a problem list and annotated drawing |
| `04_floorplan.py` | A generic engine draws the structure, real AutoCAD dimensions it; the two engines cross-check each other |

`render.py` converts any DXF to an SVG or PNG preview, no AutoCAD needed:

```
python render.py out/01_flange_family.dxf preview.svg
```

Previews automatically swap the "designed for a black screen" colours for equivalents that are visible on white paper. AutoCAD's model space is black, so ACI colours such as cyan, green, yellow and light grey are clear on black but almost invisible on white paper (cyan's contrast against white is only 1.25).

Two colour modes:

```
python render.py out/01_flange_family.dxf preview.svg          # keep layer colours (default)
python render.py --mono out/01_flange_family.dxf preview.svg   # all black
```

`--mono` is equivalent to a monochrome plot style table (`monochrome.ctb`, or the common `!黑白线型*.ctb`), which is the convention for issued and archived drawings.

**The DXF file is never modified**: layer colours remain the standard ACI values; the preview colouring exists only in the preview file. The background colour works the same way — model space's dark background is an AutoCAD UI theme (stored in user preferences), not drawing data, and isn't recorded in the DXF at all.

`check_previews.py` is the matching quality gate; it checks each preview for "invisible lines":

```
python check_previews.py
```

It checks both colour contrast and stroke width, and exits non-zero if anything fails, so it can be wired into a build.

## Known limitations

- The generic part (no AutoCAD) **handles DXF only, not DWG directly**. Given a `.dwg` it gives a clear message. Converting to DWG requires the real-AutoCAD tools.
- DXF saved by AutoCAD is always the current version (AC1032 / R2018). To convert to an older version, read it back, set the version, and save:

  ```
  drawing_run("doc.dxfversion = ezdxf.const.DXF2010",
              path="a.dxf", save_as="b.dxf")
  ```

  Note that a plain `save_as` **does not** change the version; you must set `doc.dxfversion`. (`ezdxf.const.DXF2010` is R2010; you can also pass a string like `"R2000"`.)
- AutoCAD LT's AutoLISP support has always been limited (only partial support from 2024), and the `autocad_*` tools depend on AutoLISP — verify before using LT.
- Previews are static images; there is no interactive zoom/pan viewer.

## License

MIT — see [LICENSE](LICENSE).

## A note on CAD licences

CAD software is commercial; obtain it through legitimate channels. Workable options include the official 30-day trial, Autodesk Education licensing, Flex tokens, and compatible alternatives such as BricsCAD / ZWCAD / nanoCAD.
