#!/usr/bin/env python3
"""Run every case in order and leave the artifacts in `out/`.

Case 4 is the slow one - it starts accoreconsole twice, so expect roughly half a
minute for the suite and a couple of seconds for the other three.

Run:  python cases/run_all.py
"""
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
CASES = ["01_parts.py", "02_nesting.py", "03_audit.py", "04_floorplan.py"]


def main() -> int:
    failed = []
    for name in CASES:
        print(f"\n### {name}\n")
        t0 = time.perf_counter()
        rc = subprocess.run([sys.executable, str(HERE / name)],
                            cwd=HERE.parent).returncode
        dt = time.perf_counter() - t0
        print(f"\n--- {name}: exit {rc} in {dt:.1f}s")
        if rc:
            failed.append(name)

    print("\n" + "=" * 74)
    print(f"{len(CASES) - len(failed)}/{len(CASES)} cases passed")
    if failed:
        print("failed:", ", ".join(failed))
        return 1
    print(f"artifacts are in {(HERE.parent / 'out').resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
