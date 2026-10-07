"""The AutoCAD engine: accoreconsole.exe spawned as a child process.

There is nothing else to it: input and output drawings are plain files in a
scratch directory, and every call is one short-lived accoreconsole process that
exits when it is done. No daemon, no listener, no bridge, no shared folder.

accoreconsole ships with AutoCAD 2013 and newer. It is headless - no GUI, no
dialogs - and, importantly, it is a *separate process* from the user's own
AutoCAD window. Nothing in this module can touch an open session, and
kill_orphans only ever targets accoreconsole.exe, never acad.exe.

Config
    CAD_ACCORECONSOLE   full path to accoreconsole.exe (escape hatch for a
                        non-standard install; found by registry/glob otherwise)
    CAD_WORKDIR         where scratch job directories are made
                        (default: <system temp>/cadmcp)

Self-check:  python accore.py
"""
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

sep = os.sep

ACCORE_ENV = "CAD_ACCORECONSOLE"
WORKDIR_ENV = "CAD_WORKDIR"


class ToolError(RuntimeError):
    pass


def run(argv, timeout=180, encoding="utf-8"):
    """Run a command here. Returns (returncode, stdout, stderr).

    subprocess kills the child itself on timeout, so a hung script does not
    survive this call - but accoreconsole can leave its own children behind,
    which is what kill_orphans is for.
    """
    try:
        p = subprocess.run([str(a) for a in argv], capture_output=True,
                           timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raise ToolError(f"{argv[0]} did not finish within {timeout}s") from e
    except OSError as e:
        raise ToolError(f"cannot run {argv[0]}: {e}") from e
    return (p.returncode,
            (p.stdout or b"").decode(encoding, "replace"),
            (p.stderr or b"").decode(encoding, "replace"))


def write_file(path, data):
    """Write bytes to a path here. Creates parent directories."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return len(data)


def read_file(path):
    """Read bytes from a path here."""
    try:
        return Path(path).read_bytes()
    except OSError as e:
        raise ToolError(f"cannot read {path}: {e}") from e


def ping():
    """Is AutoCAD usable here? That is just 'can we find accoreconsole'."""
    try:
        find_accoreconsole()
        return True
    except ToolError:
        return False


def find_accoreconsole():
    """Locate accoreconsole.exe on this machine.

    Order: explicit override, then the registry (authoritative on Windows),
    then the usual install glob. Sorted reverse so the newest AutoCAD wins.
    """
    override = os.environ.get(ACCORE_ENV)
    if override:
        if not Path(override).is_file():
            raise ToolError(f"{ACCORE_ENV}={override} is not a file")
        return override
    found = sorted(set(_registry_accoreconsole()) | set(_glob_accoreconsole()),
                   reverse=True)
    if not found:
        raise ToolError(
            "accoreconsole.exe not found. It ships with AutoCAD 2013 and newer; "
            f"install AutoCAD, or set {ACCORE_ENV} to the full path.")
    return str(found[0])


def _glob_accoreconsole():
    for var in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"):
        root = os.environ.get(var)
        if root and Path(root).is_dir():
            yield from Path(root).glob("Autodesk/AutoCAD */accoreconsole.exe")


def _registry_accoreconsole():
    """HKLM\\SOFTWARE\\Autodesk\\AutoCAD\\<version>\\<product> -> AcadLocation.

    Windows only, and silently empty anywhere else.
    """
    if sys.platform != "win32":
        return
    import winreg
    try:
        top = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Autodesk\AutoCAD")
    except OSError:
        return
    with top:
        for i in range(winreg.QueryInfoKey(top)[0]):
            try:
                with winreg.OpenKey(top, winreg.EnumKey(top, i)) as ver:
                    for j in range(winreg.QueryInfoKey(ver)[0]):
                        with winreg.OpenKey(ver, winreg.EnumKey(ver, j)) as prod:
                            loc, _ = winreg.QueryValueEx(prod, "AcadLocation")
                            p = Path(loc) / "accoreconsole.exe"
                            if p.is_file():
                                yield p
            except OSError:
                continue


def _workroot() -> Path:
    return Path(os.environ.get(WORKDIR_ENV) or tempfile.gettempdir()) / "cadmcp"


def mkwork():
    """Create a scratch directory for one job. Returns (job id, native path)."""
    job = uuid.uuid4().hex[:12]
    wdir = _workroot() / job
    wdir.mkdir(parents=True, exist_ok=True)
    return job, str(wdir)


def cleanup(wdir):
    """Delete a job directory. Refuses to touch anything outside our root."""
    p = Path(wdir).resolve()
    root = _workroot().resolve()
    if p != root and root not in p.parents:
        return
    shutil.rmtree(p, ignore_errors=True)


def kill_orphans():
    """Kill stray accoreconsole processes.

    Only accoreconsole - never acad.exe, which is the user's own window.
    """
    if sys.platform != "win32":
        return
    subprocess.run(["taskkill", "/f", "/im", "accoreconsole.exe"],
                   capture_output=True)


def _self_check():
    print("find_accoreconsole:")
    os.environ[ACCORE_ENV] = sys.executable       # any existing file will do
    print("  override honoured ->", find_accoreconsole())
    os.environ[ACCORE_ENV] = "/nope/does-not-exist"
    assert ping() is False, "a bogus override must not count as usable"
    del os.environ[ACCORE_ENV]
    print("  bogus override -> ping() False  OK")

    job, wdir = mkwork()
    print("mkwork ->", wdir)
    blob = bytes(range(256)) * 400               # 100 KB, all byte values
    write_file(os.path.join(wdir, "in.dxf"), blob)
    assert read_file(os.path.join(wdir, "in.dxf")) == blob, "round trip mismatch"
    print("  100 KB binary round trip  OK")

    rc, out, err = run([sys.executable, "-c", "print('hi')"], timeout=30)
    assert (rc, out.strip()) == (0, "hi"), (rc, out)
    print("run() -> rc/out  OK")

    try:
        run([sys.executable, "-c", "import time; time.sleep(30)"], timeout=2)
        raise AssertionError("a hang should have raised")
    except ToolError as e:
        print("run() timeout ->", e)
        print("  converted to ToolError, not a bare TimeoutExpired  OK")

    cleanup(wdir)
    assert not Path(wdir).exists(), "cleanup left the directory"
    print("cleanup  OK")
    if sys.platform != "win32":
        cleanup("/etc")                          # must be refused
        assert Path("/etc").exists(), "cleanup escaped the work root!"
        print("cleanup refuses to leave the work root  OK")
    print("accore.py self-check passed")


if __name__ == "__main__":
    _self_check()
