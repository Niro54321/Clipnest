"""The editor's export: trim, resize to a preset, burn in text and a logo.

Text is drawn by Qt into a transparent PNG the size of the output frame and
laid over the video, so Arabic and other scripts shape and run the right way
(FFmpeg's drawtext doesn't do either).
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter, QPainterPath, QPen, QTextOption

from clipnest import smart
from clipnest.download import AUDIO_FORMATS, Progress, run_ffmpeg, unique_path
from clipnest.util import ffprobe_next_to

ASPECTS = {"original": None, "9:16": (1080, 1920), "1:1": (1080, 1080), "4:5": (1080, 1350),
           "16:9": (1920, 1080)}
ASPECT_NAMES = [("original", "Original"), ("9:16", "9:16 TikTok/Reels"), ("1:1", "1:1 Square"),
                ("4:5", "4:5 Post"), ("16:9", "16:9 YouTube")]
CORNERS = ["top-left", "top-right", "bottom-left", "bottom-right", "center"]
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


@dataclass
class Media:
    path: Path
    duration: float
    width: int
    height: int
    has_video: bool
    has_audio: bool


def inspect(ffmpeg: str, path: Path) -> Media:
    out = subprocess.run([ffprobe_next_to(ffmpeg), "-v", "error", "-print_format", "json",
                          "-show_streams", "-show_format", str(path)],
                         capture_output=True, text=True, encoding="utf-8", errors="replace",
                         creationflags=NO_WINDOW).stdout
    data = json.loads(out or "{}")
    video = [s for s in data.get("streams", []) if s.get("codec_type") == "video"
             and not (s.get("disposition") or {}).get("attached_pic")]
    audio = [s for s in data.get("streams", []) if s.get("codec_type") == "audio"]
    w = int(video[0].get("width", 0)) if video else 0
    h = int(video[0].get("height", 0)) if video else 0
    if video:
        rotate = (video[0].get("tags") or {}).get("rotate") or next(
            (sd.get("rotation") for sd in video[0].get("side_data_list") or [] if "rotation" in sd), 0)
        if abs(int(float(rotate or 0))) in (90, 270):
            w, h = h, w
    return Media(path=Path(path), duration=float((data.get("format") or {}).get("duration") or 0),
                 width=w, height=h, has_video=bool(video), has_audio=bool(audio))


@dataclass
class EditSpec:
    start: float = 0.0
    end: float | None = None          # None = to the end
    aspect: str = "original"
    fit: str = "fill"                 # fill = crop to the frame, blur = whole picture on a blurred copy
    focus_x: float = 0.5              # where the crop window sits, 0..1 (smart reframe sets these)
    focus_y: float = 0.5
    text: str = ""
    text_size: float = 6.0            # % of the frame height
    text_color: str = "#FFFFFF"
    outline_color: str = "#000000"
    text_pos: str = "bottom"          # top / center / bottom
    text_box: bool = False
    logo: Path | None = None
    logo_size: float = 18.0           # % of the frame width
    logo_pos: str = "top-right"
    logo_opacity: float = 0.9
    fmt: str = "mp4"


def out_size(spec: EditSpec, media: Media) -> tuple[int, int]:
    size = ASPECTS.get(spec.aspect)
    if size:
        return size
    return max(2, media.width // 2 * 2), max(2, media.height // 2 * 2)


def text_band(pos: str) -> tuple[float, float]:
    """The part of the frame (top, bottom as 0..1) the text sits in."""
    return {"top": (0.05, 0.25), "center": (0.38, 0.62)}.get(pos, (0.72, 0.93))


def render_text(spec: EditSpec, width: int, height: int, path: Path) -> None:
    """The text layer as a transparent PNG the size of the output frame. Needs a QGuiApplication."""
    img = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    font = QFont("Segoe UI")
    font.setPixelSize(max(8, int(height * spec.text_size / 100)))
    font.setWeight(QFont.Weight.Bold)
    p.setFont(font)
    top, bottom = text_band(spec.text_pos)
    area = QRectF(width * 0.06, height * top, width * 0.88, height * (bottom - top))
    option = QTextOption(Qt.AlignmentFlag.AlignHCenter)
    option.setWrapMode(QTextOption.WrapMode.WordWrap)
    metrics = QFontMetricsF(font)
    used = metrics.boundingRect(area, int(Qt.AlignmentFlag.AlignHCenter | Qt.TextFlag.TextWordWrap), spec.text)
    vertical = {"top": Qt.AlignmentFlag.AlignTop, "center": Qt.AlignmentFlag.AlignVCenter}.get(
        spec.text_pos, Qt.AlignmentFlag.AlignBottom)
    flags = int(Qt.AlignmentFlag.AlignHCenter | vertical | Qt.TextFlag.TextWordWrap)
    box = QRectF(area.left(), 0, area.width(), used.height())
    if vertical == Qt.AlignmentFlag.AlignTop:
        box.moveTop(area.top())
    elif vertical == Qt.AlignmentFlag.AlignBottom:
        box.moveBottom(area.bottom())
    else:
        box.moveCenter(area.center())
    if spec.text_box:
        pad = font.pixelSize() * 0.35
        back = QRectF(box.center().x() - used.width() / 2 - pad, box.top() - pad * 0.6,
                      used.width() + 2 * pad, used.height() + pad * 1.2)
        shape = QPainterPath()
        shape.addRoundedRect(back, pad, pad)
        fill = QColor(spec.outline_color)
        fill.setAlpha(150)
        p.fillPath(shape, fill)
    else:
        # outline: the text drawn around itself, then a soft shadow below
        outline = QColor(spec.outline_color)
        r = max(1, font.pixelSize() // 18)
        shadow = QColor(0, 0, 0, 90)
        p.setPen(QPen(shadow))
        p.drawText(box.translated(0, r * 2), flags, spec.text)
        p.setPen(QPen(outline))
        for dx in range(-r, r + 1):
            for dy in range(-r, r + 1):
                if dx * dx + dy * dy <= r * r and (dx or dy):
                    p.drawText(box.translated(dx, dy), flags, spec.text)
    p.setPen(QPen(QColor(spec.text_color)))
    p.drawText(box, flags, spec.text)
    p.end()
    img.save(str(path))


def logo_xy(pos: str) -> tuple[str, str]:
    m = "main_w*0.03"
    return {"top-left": (m, m), "top-right": (f"main_w-overlay_w-{m}", m),
            "bottom-left": (m, f"main_h-overlay_h-{m}"),
            "bottom-right": (f"main_w-overlay_w-{m}", f"main_h-overlay_h-{m}"),
            "center": ("(main_w-overlay_w)/2", "(main_h-overlay_h)/2")}.get(pos, (m, m))


def build_command(ffmpeg: str, media: Media, spec: EditSpec, dst: Path, text_png: Path | None) -> list[str]:
    start = max(0.0, spec.start)
    end = media.duration if spec.end is None else min(spec.end, media.duration or spec.end)
    length = max(0.1, end - start)
    cmd = [ffmpeg, "-ss", f"{start:.3f}", "-t", f"{length:.3f}", "-i", str(media.path)]

    if spec.fmt in AUDIO_FORMATS or not media.has_video:
        codec = {"mp3": ["libmp3lame", "-q:a", "0"], "m4a": ["aac", "-b:a", "256k"],
                 "opus": ["libopus", "-b:a", "160k"], "flac": ["flac"], "wav": ["pcm_s16le"]}
        cmd += ["-map", "0:a:0"]
        if spec.fmt in ("mp3", "m4a", "flac"):   # keep the cover art
            cmd += ["-map", "0:v?", "-c:v", "copy"]
        # the file is already clean, so its own title and artist tags carry over
        cmd += ["-map_metadata", "0", "-map_chapters", "-1", "-fflags", "+bitexact",
                "-c:a", *codec.get(spec.fmt, codec["m4a"]), "-flags:a", "+bitexact"]
        if spec.fmt == "mp3":
            cmd += ["-id3v2_version", "3"]
        if spec.fmt == "m4a":
            cmd += ["-f", "ipod"]
        cmd.append(str(dst))
        return cmd

    inputs, chain = video_graph(media, spec, text_png)
    cmd += inputs + ["-filter_complex", chain, "-map", "[out]", "-map", "0:a:0?",
                     "-map_metadata", "-1", "-map_chapters", "-1", "-fflags", "+bitexact", "-sn", "-dn"]
    if spec.fmt == "webm":
        cmd += ["-c:v", "libvpx-vp9", "-crf", "31", "-b:v", "0", "-row-mt", "1", "-deadline", "good",
                "-cpu-used", "4", "-c:a", "libopus", "-b:a", "160k"]
    else:
        cmd += ["-c:v", "libx264", "-crf", "20", "-preset", "medium", "-c:a", "aac", "-b:a", "192k"]
        if spec.fmt in ("mp4", "mov"):
            cmd += ["-movflags", "+faststart"]
    cmd += ["-flags:v", "+bitexact", "-flags:a", "+bitexact", str(dst)]
    return cmd


def preview_command(ffmpeg: str, media: Media, spec: EditSpec, t: float, dst: Path,
                    text_png: Path | None, width: int = 640) -> list[str]:
    """One frame at time t with every edit applied, scaled down, as a PNG."""
    inputs, chain = video_graph(media, spec, text_png, final=f"scale={width}:-2")
    return [ffmpeg, "-v", "error", "-y", "-ss", f"{max(0.0, t):.3f}", "-i", str(media.path), *inputs,
            "-filter_complex", chain, "-map", "[out]", "-frames:v", "1", str(dst)]


def video_graph(media: Media, spec: EditSpec, text_png: Path | None,
                final: str = "format=yuv420p") -> tuple[list[str], str]:
    """Extra inputs (text layer, logo) and the filter graph that resizes and lays them on."""
    W, H = out_size(spec, media)
    cmd: list[str] = []
    inputs = 1
    if text_png:
        cmd += ["-i", str(text_png)]
        text_index = inputs
        inputs += 1
    if spec.logo:
        cmd += ["-i", str(spec.logo)]
        logo_index = inputs
        inputs += 1

    if spec.aspect == "original":
        chain = [f"[0:v]scale={W}:{H},setsar=1[v0]"]
    elif spec.fit == "blur":
        chain = ["[0:v]split[a][b]",
                 f"[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
                 f"boxblur=24:2,eq=brightness=-0.06[bg]",
                 f"[b]scale={W}:{H}:force_original_aspect_ratio=decrease[fg]",
                 "[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1[v0]"]
    else:
        fx, fy = min(1, max(0, spec.focus_x)), min(1, max(0, spec.focus_y))
        chain = [f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,"
                 f"crop={W}:{H}:(iw-ow)*{fx:.4f}:(ih-oh)*{fy:.4f},setsar=1[v0]"]
    last = "v0"
    if text_png:
        chain.append(f"[{last}][{text_index}:v]overlay=0:0[v1]")
        last = "v1"
    if spec.logo:
        lw = max(8, int(W * spec.logo_size / 100) // 2 * 2)
        x, y = logo_xy(spec.logo_pos)
        chain.append(f"[{logo_index}:v]scale={lw}:-2,format=rgba,"
                     f"colorchannelmixer=aa={spec.logo_opacity:.2f}[lg]")
        chain.append(f"[{last}][lg]overlay={x}:{y}[v2]")
        last = "v2"
    chain.append(f"[{last}]{final}[out]")
    return cmd, ";".join(chain)


def smart_reframe(ffmpeg: str, media: Media, spec: EditSpec) -> tuple[float, float]:
    """Crop position that keeps the subject in view for the chosen preset."""
    size = ASPECTS.get(spec.aspect)
    if not size or not media.width or not media.height:
        return 0.5, 0.5
    end = media.duration if spec.end is None else spec.end
    cx, cy = smart.subject_center(ffmpeg, media.path, spec.start, end)
    W, H = size
    src_ratio, out_ratio = media.width / media.height, W / H
    keep_x = min(1.0, out_ratio / src_ratio)   # share of the width the crop keeps
    keep_y = min(1.0, src_ratio / out_ratio)
    return smart.crop_offset(cx, keep_x), smart.crop_offset(cy, keep_y)


def text_layer(spec: EditSpec, media: Media, folder: Path) -> Path | None:
    """Draw the text layer for an export into folder. Call on the UI (or main) thread."""
    if not (spec.text.strip() and media.has_video and spec.fmt not in AUDIO_FORMATS):
        return None
    W, H = out_size(spec, media)
    path = Path(folder) / "text-export.png"
    render_text(spec, W, H, path)
    return path


def export(ffmpeg: str, media: Media, spec: EditSpec, folder: Path, name: str,
           progress: Progress | None = None, cancel=None, text_png: Path | None = None) -> Path:
    """Write the edited file. The text layer comes from text_layer(); without one it is
    drawn here, so only leave it out when calling from the main thread."""
    ext = spec.fmt if (media.has_video or spec.fmt in AUDIO_FORMATS) else "m4a"
    dst = unique_path(folder, name, ext)
    part = dst.with_name(dst.stem + ".part" + dst.suffix)
    with tempfile.TemporaryDirectory(prefix="clipnest-edit-") as tmp:
        if text_png is None:
            text_png = text_layer(spec, media, Path(tmp))
        cmd = build_command(ffmpeg, media, spec, part, text_png)
        end = media.duration if spec.end is None else min(spec.end, media.duration)
        try:
            run_ffmpeg(cmd, max(0.1, end - spec.start), progress, "Exporting…", cancel)
        except BaseException:
            part.unlink(missing_ok=True)
            raise
    part.replace(dst)
    return dst
