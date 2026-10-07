#!/usr/bin/env python3
"""Build the zip that gets handed to someone else.

It is written to `site/`, so the file that ships with the deployed product page
is the same file visitors click to download - one artifact, nothing to drift.

The archive holds the tool and its examples, not the product page. The page is
what the web version is for, and shipping a copy of it inside the zip would only
put a download button into the package that has nothing to download next to it.
`out/` is left out too - `cases/run_all.py` rebuilds it in a few seconds.

The packaged README is the Chinese one (`README.zh-CN.md`), since the download
button lives on the Chinese product page. Set SITE_URL below before
distributing and the packaged copy points at the live page; leave it empty and
the reader is told to use the link they were given.

Run:  python make_dist.py
"""
import re
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SITE = ROOT / "site"
NAME = "autocad-mcp"

SITE_URL = ""            # e.g. "https://autocad-mcp.pages.dev"

TOP = ["accore.py", "drawings.py", "render.py", "server.py",
       "check_previews.py", "make_dist.py"]
DIRS = ["cases"]
SKIP_PARTS = {"__pycache__", "dist", "out", "site", ".git", ".venv"}


def main() -> int:
    SITE.mkdir(exist_ok=True)
    target = SITE / f"{NAME}.zip"

    files = [ROOT / n for n in TOP if (ROOT / n).is_file()]
    for d in DIRS:
        files += [p for p in sorted((ROOT / d).rglob("*"))
                  if p.is_file() and p.suffix != ".pyc"
                  and not any(s in p.parts for s in SKIP_PARTS)]

    readme = (ROOT / "README.zh-CN.md").read_text(encoding="utf-8")
    site_line = (f"在线介绍页：{SITE_URL}" if SITE_URL
                 else "在线介绍页见分享给你这个压缩包的链接。")
    readme = re.sub(r"^在线介绍页.*$", site_line, readme,
                    count=1, flags=re.M)
    # the zip carries a single README, so the language switcher is a dead link
    readme = re.sub(r"^\[English\].*\n", "", readme, count=1, flags=re.M)
    members = [(f"{NAME}/README.md", readme)]
    members += [(f"{NAME}/{p.relative_to(ROOT).as_posix()}", p) for p in files]

    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for arcname, content in members:
            if isinstance(content, str):
                z.writestr(arcname, content)
            else:
                z.write(content, arcname)

    print(f"site/{target.name}: {len(members)} files, {target.stat().st_size:,} bytes")
    for arcname, _ in members:
        print(f"  {arcname}")
    if not SITE_URL:
        print("\nSITE_URL is empty, so the packaged README has no live-page URL.\n"
              "Set it at the top of make_dist.py and run this again.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
