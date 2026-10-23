"""The smart parts, all offline: where the subject is (for reframing to 9:16),
where the silence ends (for trimming), and how bright the picture is behind
the text (so it gets a colour that reads)."""

from __future__ import annotations

import re
import subprocess

import numpy as np

SIDE = 160   # frames are analysed at 160x160; coordinates come back as 0..1, so the squash doesn't matter
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def frames(ffmpeg: str, path, start: float, end: float, count: int = 16) -> list[np.ndarray]:
    """count grey frames spread over [start, end]."""
    span = max(0.5, end - start)
    rate = count / span
    cmd = [ffmpeg, "-v", "error", "-ss", f"{start:.3f}", "-t", f"{span:.3f}", "-i", str(path),
           "-an", "-vf", f"fps={rate:.5f},scale={SIDE}:{SIDE},format=gray", "-f", "rawvideo", "pipe:1"]
    raw = subprocess.run(cmd, capture_output=True, creationflags=NO_WINDOW).stdout
    n = len(raw) // (SIDE * SIDE)
    if n == 0:
        return []
    data = np.frombuffer(raw[:n * SIDE * SIDE], np.uint8).reshape(n, SIDE, SIDE).astype(np.float32)
    return list(data)


def energy_map(gray: list[np.ndarray]) -> np.ndarray:
    """Where things happen: movement between frames, plus detail (edges)."""
    acc = np.zeros((SIDE, SIDE), np.float32)
    for i, f in enumerate(gray):
        gy, gx = np.gradient(f)
        acc += np.hypot(gx, gy)
        if i:
            acc += 2.0 * np.abs(f - gray[i - 1])
    # the very edges are often letterbox bars or burned-in watermarks
    acc[:, :6] = acc[:, -6:] = 0
    acc[:6, :] = acc[-6:, :] = 0
    return acc


def subject_center(ffmpeg: str, path, start: float, end: float) -> tuple[float, float]:
    """The point the viewer looks at, as (x, y) in 0..1. (0.5, 0.5) when unsure."""
    gray = frames(ffmpeg, path, start, end)
    if not gray:
        return 0.5, 0.5
    energy = energy_map(gray)
    if energy.sum() <= 0:
        return 0.5, 0.5
    weight = energy ** 2   # favour the strongest spot over spread-out texture
    ys, xs = np.mgrid[0:SIDE, 0:SIDE]
    total = weight.sum()
    cx = float((weight * xs).sum() / total) / (SIDE - 1)
    cy = float((weight * ys).sum() / total) / (SIDE - 1)
    # pull a little towards the middle: a wrong guess then costs less
    return 0.5 + (cx - 0.5) * 0.85, 0.5 + (cy - 0.5) * 0.85


def crop_offset(center: float, keep: float) -> float:
    """Where a crop window covering `keep` (0..1) of an axis should start, as a
    fraction of the room it can move in, so `center` stays in view."""
    if keep >= 1:
        return 0.5
    return float(min(1.0, max(0.0, (center - keep / 2) / (1 - keep))))


def silence_bounds(ffmpeg: str, path, duration: float, noise_db: int = -38,
                   min_len: float = 0.4) -> tuple[float, float]:
    """(start, end) with the silence at both ends cut off; the whole clip when there is none."""
    cmd = [ffmpeg, "-hide_banner", "-nostats", "-i", str(path), "-vn",
           "-af", f"silencedetect=n={noise_db}dB:d={min_len}", "-f", "null", "-"]
    log = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                         creationflags=NO_WINDOW).stderr
    starts = [float(x) for x in re.findall(r"silence_start: (-?[\d.]+)", log)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", log)]
    begin, finish = 0.0, duration
    if starts and ends and starts[0] <= 0.05:
        begin = ends[0]
    if starts and (len(ends) < len(starts) or (ends and ends[-1] >= duration - 0.1)):
        if starts[-1] > begin:
            finish = starts[-1]
    if finish - begin < 1.0:   # all quiet, or almost: keep everything
        return 0.0, duration
    # leave a breath either side
    return max(0.0, begin - 0.15), min(duration, finish + 0.15)


def brightness(ffmpeg: str, path, t: float, top: float, bottom: float) -> float:
    """Mean brightness (0..1) of a horizontal band of the frame at time t."""
    gray = frames(ffmpeg, path, max(0.0, t), max(0.0, t) + 0.6, count=1)
    if not gray:
        return 0.0
    band = gray[0][int(top * SIDE):max(int(top * SIDE) + 1, int(bottom * SIDE))]
    return float(band.mean()) / 255


def text_colors(level: float) -> tuple[str, str]:
    """(text, outline) that read on a background of this brightness."""
    return ("#111111", "#FFFFFF") if level > 0.62 else ("#FFFFFF", "#000000")
