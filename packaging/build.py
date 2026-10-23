"""Builds the Windows installer.

    .venv\\Scripts\\python.exe packaging\\build.py [--skip-test] [--network] [--app | --installer]

1. icon, version info and third-party notices into build/
2. PyInstaller: dist/Clipnest (the app, plus a self-test exe)
3. the self-test in the packaged app: yt-dlp extras, clean files, editor export, playback
   (--network also reads a TikTok link)
4. Inno Setup: dist/Clipnest-Setup-<version>.exe, and its SHA-256 next to it

Needs PyInstaller in the venv and Inno Setup 6 (winget install JRSoftware.InnoSetup).
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD, DIST = ROOT / "build", ROOT / "dist"
sys.path.insert(0, str(ROOT))

from clipnest import __version__  # noqa: E402

# Tools that build or check the app; none of them ship.
NOT_SHIPPED = {"pyinstaller", "pyinstaller-hooks-contrib", "altgraph", "pefile", "pywin32-ctypes", "pip",
               "setuptools", "packaging", "pyflakes", "clipnest", "pytest", "pluggy", "iniconfig",
               "pygments", "colorama"}


def step(text: str) -> None:
    print(f"\n== {text}", flush=True)


def prepare() -> None:
    from PySide6.QtGui import QGuiApplication

    from clipnest.theme import save_ico

    BUILD.mkdir(exist_ok=True)
    _app = QGuiApplication.instance() or QGuiApplication(["build"])  # icons need Qt
    save_ico(BUILD / "clipnest.ico")
    nums = ", ".join((__version__.split(".") + ["0"] * 4)[:4])
    (BUILD / "version.txt").write_text(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers=({nums}), prodvers=({nums})),
  kids=[StringFileInfo([StringTable('040904B0', [
    StringStruct('CompanyName', 'Niro54321'),
    StringStruct('FileDescription', 'Clipnest video downloader'),
    StringStruct('FileVersion', '{__version__}'),
    StringStruct('InternalName', 'Clipnest'),
    StringStruct('LegalCopyright', 'MIT License'),
    StringStruct('OriginalFilename', 'Clipnest.exe'),
    StringStruct('ProductName', 'Clipnest'),
    StringStruct('ProductVersion', '{__version__}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])])
""", encoding="utf-8")


def notices(target: Path) -> None:
    """THIRD-PARTY-NOTICES.txt and every bundled package's own licence files."""
    licenses = target / "licenses"
    shutil.rmtree(licenses, ignore_errors=True)
    lines = ["Clipnest is MIT licensed (see LICENSE). The installer also contains the",
             "open-source software below, each under its own licence; the full texts are",
             "in the licenses folder next to this file.", "",
             f"Python {sys.version.split()[0]}  PSF-2.0  https://www.python.org/"]
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if python_license.is_file():
        (licenses / "Python").mkdir(parents=True, exist_ok=True)
        shutil.copy2(python_license, licenses / "Python" / "LICENSE.txt")
    for dist in sorted(metadata.distributions(), key=lambda d: d.metadata["Name"].lower()):
        name = dist.metadata["Name"]
        if name.lower() in NOT_SHIPPED:
            continue
        licence = dist.metadata.get("License-Expression") or next(
            (c.split("::")[-1].strip() for c in dist.metadata.get_all("Classifier") or [] if c.startswith("License ::")),
            (dist.metadata.get("License") or "see licence file").splitlines()[0][:60])
        url = next((u.split(",", 1)[-1].strip() for u in dist.metadata.get_all("Project-URL") or []
                    if u.lower().startswith(("source", "repository", "homepage", "code"))),
                   dist.metadata.get("Home-page") or "")
        lines.append(f"{name} {dist.version}  {licence}  {url}".rstrip())
        for f in dist.files or []:
            if any(part.lower().startswith(("license", "licence", "copying", "notice", "authors"))
                   for part in Path(f).parts[-1:]) or "licenses" in Path(f).parts:
                src = Path(dist.locate_file(f))
                if src.is_file():
                    dest = licenses / name / Path(f).name
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dest)
    lines += ["",
              "Bundled programs and libraries inside the packages above:",
              "- Qt 6 and its FFmpeg-based multimedia backend (inside PySide6), LGPL-3.0; source:",
              "  https://download.qt.io/official_releases/qt/ and https://code.qt.io/",
              "- libcurl-impersonate (inside curl_cffi), MIT; source:",
              "  https://github.com/lexiforest/curl-impersonate",
              "",
              "FFmpeg is not included. The installer can download it for you with winget",
              "(Gyan.FFmpeg); it runs as a separate program under its own licence."]
    (target / "THIRD-PARTY-NOTICES.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def pyinstaller() -> Path:
    shutil.rmtree(DIST / "Clipnest", ignore_errors=True)
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
                    "--distpath", str(DIST), "--workpath", str(BUILD / "pyinstaller"),
                    str(ROOT / "packaging" / "clipnest.spec")], check=True)
    out = DIST / "Clipnest"
    shutil.copy2(ROOT / "LICENSE", out / "LICENSE.txt")
    notices(out)
    return out


def selftest(out: Path) -> None:
    work = Path(tempfile.mkdtemp(prefix="clipnest-selftest-"))
    extra = ["--network"] if "--network" in sys.argv else []
    subprocess.run([str(out / "clipnest-selftest.exe"), str(work), *extra], check=True)
    shutil.rmtree(work, ignore_errors=True)


def inno() -> Path:
    candidates = [Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/Inno Setup 6/ISCC.exe",
                  Path(os.environ.get("ProgramFiles(x86)", "")) / "Inno Setup 6/ISCC.exe",
                  Path(os.environ.get("ProgramFiles", "")) / "Inno Setup 6/ISCC.exe"]
    iscc = next((c for c in candidates if c.is_file()), None) or shutil.which("ISCC")
    if not iscc:
        sys.exit("Inno Setup 6 not found: winget install JRSoftware.InnoSetup")
    subprocess.run([str(iscc), f"/DAppVersion={__version__}", str(ROOT / "packaging" / "clipnest.iss")],
                   check=True)
    return DIST / f"Clipnest-Setup-{__version__}.exe"


def main() -> None:
    # CI signs in between: --app builds and tests dist/Clipnest, the app gets signed,
    # then --installer packs the signed files into the setup.
    app_stage = "--installer" not in sys.argv
    installer_stage = "--app" not in sys.argv
    if app_stage:
        step(f"Clipnest {__version__}: icon and version info")
        prepare()
        step("PyInstaller")
        out = pyinstaller()
        if "--skip-test" not in sys.argv:
            step("Self-test in the packaged app")
            selftest(out)
    if not installer_stage:
        return
    if not (BUILD / "clipnest.ico").exists():
        prepare()
    step("Inno Setup")
    setup = inno()
    digest = hashlib.sha256(setup.read_bytes()).hexdigest()
    setup.with_name(setup.name + ".sha256").write_text(f"{digest}  {setup.name}\n", encoding="ascii")
    print(f"\nDone: {setup} ({setup.stat().st_size / 1e6:.0f} MB)\nSHA-256 {digest}")


if __name__ == "__main__":
    main()
