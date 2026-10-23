# PyInstaller recipe, run by packaging/build.py. Makes dist/Clipnest with
# Clipnest.exe and clipnest-selftest.exe sharing one _internal folder; the
# self-test checks the build and is left out of the installer.

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).parent
BUILD = ROOT / "build"
HIDDEN = collect_submodules("clipnest") + collect_submodules("curl_cffi") + collect_submodules("yt_dlp_ejs")
DATAS = collect_data_files("yt_dlp_ejs") + collect_data_files("curl_cffi")
EXCLUDES = ["tkinter", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
            "PySide6.Qt3DCore", "PySide6.QtQuick3D", "PySide6.QtCharts", "PySide6.QtDataVisualization",
            "PySide6.QtDesigner", "PySide6.QtPdf", "PySide6.QtQml", "PySide6.QtQuick", "pytest"]


def analysis(script):
    return Analysis([str(ROOT / "packaging" / script)], pathex=[str(ROOT)], datas=DATAS,
                    hiddenimports=HIDDEN, excludes=EXCLUDES, noarchive=False)


app = analysis("launcher.py")
test = analysis("selftest.py")

app_exe = EXE(PYZ(app.pure), app.scripts, [], exclude_binaries=True, name="Clipnest",
              icon=str(BUILD / "clipnest.ico"), version=str(BUILD / "version.txt"),
              console=False, upx=False)
test_exe = EXE(PYZ(test.pure), test.scripts, [], exclude_binaries=True, name="clipnest-selftest",
               icon=str(BUILD / "clipnest.ico"), console=True, upx=False)

COLLECT(app_exe, app.binaries, app.datas, test_exe, test.binaries, test.datas,
        name="Clipnest", upx=False)
