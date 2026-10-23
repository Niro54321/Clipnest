"""Small helpers: where things live, finding FFmpeg, time strings."""

from __future__ import annotations

import os
import shutil
from pathlib import Path


def app_data_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    folder = Path(base) / "Clipnest"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def downloads_dir() -> Path:
    folder = Path.home() / "Downloads" / "Clipnest"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def find_ffmpeg() -> str | None:
    """FFmpeg is not bundled: look on PATH, then in the folders winget installs to."""
    found = shutil.which("ffmpeg")
    if found:
        return found
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    links = local / "Microsoft" / "WinGet" / "Links" / "ffmpeg.exe"
    if links.exists():
        return str(links)
    packages = local / "Microsoft" / "WinGet" / "Packages"
    if packages.exists():
        for exe in sorted(packages.glob("*FFmpeg*/**/bin/ffmpeg.exe"), reverse=True):
            return str(exe)
    return None


def ffprobe_next_to(ffmpeg: str) -> str:
    probe = Path(ffmpeg).with_name("ffprobe.exe")
    return str(probe) if probe.exists() else "ffprobe"


def fmt_time(seconds: float) -> str:
    seconds = max(0, int(round(seconds)))
    h, rest = divmod(seconds, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def parse_time(text: str) -> float | None:
    """'90', '1:30' or '0:01:30' → seconds; None when it isn't a time."""
    text = text.strip()
    if not text:
        return None
    try:
        parts = [float(p) for p in text.split(":")]
    except ValueError:
        return None
    if len(parts) > 3 or any(p < 0 for p in parts):
        return None
    total = 0.0
    for p in parts:
        total = total * 60 + p
    return total


def safe_name(text: str, limit: int = 120) -> str:
    bad = '<>:"/\\|?*\n\r\t'
    clean = "".join("_" if c in bad else c for c in text).strip(" .")
    return clean[:limit] or "video"
