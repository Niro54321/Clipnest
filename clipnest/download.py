"""Reading a link and downloading it with yt-dlp, then writing a clean file with FFmpeg.

The clean step drops every tag the source left (title, comment, purl, encoder,
chapters) so the file doesn't say where it came from. MP3 and M4A get the
title, artist and cover the user chose instead.
"""

from __future__ import annotations

import re
import threading
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import yt_dlp

from clipnest.util import ffprobe_next_to, safe_name

VIDEO_FORMATS = ["mp4", "webm", "mkv", "mov"]
AUDIO_FORMATS = ["mp3", "m4a", "opus", "flac", "wav"]
FORMATS = VIDEO_FORMATS + AUDIO_FORMATS

# codecs each container can hold without re-encoding
COPY_OK = {
    "mp4": ({"h264", "hevc", "av1", "vp9"}, {"aac", "mp3", "opus", "flac", "alac"}),
    "mov": ({"h264", "hevc", "prores"}, {"aac", "mp3", "alac", "pcm_s16le"}),
    "webm": ({"vp8", "vp9", "av1"}, {"opus", "vorbis"}),
    "mkv": (None, None),  # anything
}

PLATFORMS = [
    ("tiktok", "TikTok", r"(^|\.)tiktok\.com$"),
    ("instagram", "Instagram", r"(^|\.)instagram\.com$"),
    ("facebook", "Facebook", r"(^|\.)(facebook\.com|fb\.watch|fb\.com)$"),
    ("x", "X / Twitter", r"(^|\.)(x\.com|twitter\.com)$"),
    ("youtube", "YouTube", r"(^|\.)(youtube\.com|youtu\.be)$"),
]

URL_RE = re.compile(r"https?://[^\s<>\"']+", re.I)


class Cancelled(Exception):
    pass


def extract_urls(text: str) -> list[str]:
    """Every link in pasted text, in order, without duplicates."""
    seen, out = set(), []
    for m in URL_RE.finditer(text or ""):
        url = m.group(0).rstrip(").,;]")
        if url not in seen:
            seen.add(url)
            out.append(url)
    return out


def platform(url: str) -> tuple[str, str]:
    """(key, display name) of the site a link points to."""
    host = re.sub(r"^https?://", "", url.strip(), flags=re.I).split("/")[0].split(":")[0].lower()
    for key, name, pattern in PLATFORMS:
        if re.search(pattern, host):
            return key, name
    return "other", host or "Web"


@dataclass
class Clip:
    url: str
    title: str
    artist: str
    duration: float
    width: int | None
    height: int | None
    thumbnail: str | None
    heights: list[int]
    info: dict = field(repr=False)

    @property
    def platform(self) -> str:
        return platform(self.url)[1]


def _base_opts() -> dict:
    return {"quiet": True, "no_warnings": True, "noplaylist": True, "noprogress": True,
            "updatetime": False,  # file gets today's date, not the upload date
            "socket_timeout": 20}


def probe(url: str) -> Clip:
    """What a link holds: title, length and the qualities on offer."""
    with yt_dlp.YoutubeDL(_base_opts()) as ydl:
        info = ydl.extract_info(url, download=False)
    if info.get("_type") == "playlist":
        entries = [e for e in info.get("entries") or [] if e]
        if not entries:
            raise ValueError("No video found at this link.")
        info = entries[0]
    heights = sorted({f["height"] for f in info.get("formats") or []
                      if f.get("height") and f.get("vcodec") not in (None, "none")}, reverse=True)
    if not heights and info.get("height"):
        heights = [info["height"]]
    artist = info.get("artist") or info.get("creator") or info.get("uploader") or info.get("channel") or ""
    title = info.get("track") or info.get("title") or info.get("id") or "video"
    return Clip(url=url, title=title, artist=artist, duration=float(info.get("duration") or 0),
                width=info.get("width"), height=info.get("height"), thumbnail=info.get("thumbnail"),
                heights=heights, info=info)


def _size(f: dict, duration: float) -> float:
    size = f.get("filesize") or f.get("filesize_approx")
    if not size and f.get("tbr") and duration:
        size = f["tbr"] * 1000 / 8 * duration
    return float(size or 0)


def estimate_size(clip: Clip, height: int | None, audio_only: bool) -> float:
    """Rough bytes for a choice, from the formats the site lists (0 when unknown)."""
    formats = clip.info.get("formats") or []
    audio = [f for f in formats if f.get("acodec") not in (None, "none") and f.get("vcodec") in (None, "none")]
    best_audio = max((_size(f, clip.duration) for f in audio), default=0.0)
    if audio_only:
        return best_audio
    video = [f for f in formats if f.get("vcodec") not in (None, "none") and f.get("height")
             and (height is None or f["height"] <= height)]
    if not video:
        return 0.0
    top = max(f["height"] for f in video)
    best_video = max(_size(f, clip.duration) for f in video if f["height"] == top)
    muxed = all(f.get("acodec") not in (None, "none") for f in video if f["height"] == top)
    return best_video + (0 if muxed else best_audio)


def format_selector(fmt: str, height: int | None) -> tuple[str, list[str]]:
    """yt-dlp's format and format_sort: the highest resolution up to the cap first,
    and among equals the codec the container plays best (H.264 for MP4/MOV, VP9 for WebM)."""
    if fmt in AUDIO_FORMATS:
        return "ba/b", ["abr", "asr"]
    sort = [f"res:{height}" if height else "res", "fps"]
    codec = {"mp4": "vcodec:h264", "mov": "vcodec:h264", "webm": "vcodec:vp9"}.get(fmt)
    if codec:
        sort.append(codec)
    return "bv*+ba/b", sort


@dataclass
class Job:
    clip: Clip
    fmt: str = "mp4"
    height: int | None = None     # None = best
    folder: Path = Path(".")
    name: str = ""                # file name without extension
    title: str = ""               # tags for audio files
    artist: str = ""
    cover: bool = True
    audio_bitrate: int = 320
    compatible: bool = True       # MP4/MOV: turn HEVC, AV1 or VP9 into H.264 so every player opens it


Progress = Callable[[float, str], None]   # (0..1, status text)


def _streams(ffprobe: str, path: Path) -> tuple[str | None, str | None]:
    out = subprocess.run([ffprobe, "-v", "error", "-show_entries", "stream=codec_type,codec_name",
                          "-of", "csv=p=0", str(path)], capture_output=True, text=True, encoding="utf-8", errors="replace",
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    v = a = None
    for line in out.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 2:
            continue
        name, kind = parts[0], parts[1]
        if kind == "video" and v is None and name not in ("mjpeg", "png"):
            v = name
        elif kind == "audio" and a is None:
            a = name
    return v, a


def run_ffmpeg(cmd: list[str], duration: float, progress: Progress | None, label: str,
               cancel: Callable[[], bool] | None = None) -> None:
    """Run FFmpeg, reporting how far it got from its -progress output."""
    cmd = [cmd[0], "-hide_banner", "-nostdin", "-y", "-progress", "pipe:1", "-nostats", *cmd[1:]]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            encoding="utf-8", errors="replace",
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    err_lines: list[str] = []


    def read_err():
        for line in proc.stderr:
            err_lines.append(line)
            del err_lines[:-30]

    t = threading.Thread(target=read_err, daemon=True)
    t.start()
    for line in proc.stdout:
        if cancel and cancel():
            proc.kill()
            raise Cancelled()
        if line.startswith("out_time_us=") and duration > 0 and progress:
            try:
                done = int(line.split("=", 1)[1]) / 1e6
                progress(min(1.0, done / duration), label)
            except ValueError:
                pass
    proc.wait()
    t.join(timeout=2)
    if proc.returncode != 0:
        raise RuntimeError("FFmpeg failed:\n" + "".join(err_lines[-8:]))


def clean_command(ffmpeg: str, src: Path, dst: Path, fmt: str, vcodec: str | None, acodec: str | None,
                  title: str = "", artist: str = "", cover: Path | None = None, bitrate: int = 320,
                  compatible: bool = False) -> list[str]:
    """FFmpeg arguments that write src as dst in fmt with no source metadata at all."""
    cmd = [ffmpeg, "-i", str(src)]
    audio = fmt in AUDIO_FORMATS
    use_cover = cover is not None and fmt in ("mp3", "m4a", "flac")
    if use_cover:
        cmd += ["-i", str(cover)]
    cmd += ["-map_metadata", "-1", "-map_chapters", "-1", "-fflags", "+bitexact"]
    if audio:
        cmd += ["-map", "0:a:0"]
        if use_cover:
            cmd += ["-map", "1:v:0", "-c:v", "mjpeg", "-disposition:v:0", "attached_pic"]
        codec = {"mp3": ["libmp3lame", "-b:a", f"{bitrate}k"],
                 "m4a": ["copy"] if acodec == "aac" else ["aac", "-b:a", f"{min(bitrate, 256)}k"],
                 "opus": ["copy"] if acodec == "opus" else ["libopus", "-b:a", f"{min(bitrate, 192)}k"],
                 "flac": ["flac"], "wav": ["pcm_s16le"]}[fmt]
        cmd += ["-c:a", *codec, "-flags:a", "+bitexact"]
        if title:
            cmd += ["-metadata", f"title={title}"]
        if artist:
            cmd += ["-metadata", f"artist={artist}"]
        if fmt == "mp3":
            cmd += ["-id3v2_version", "3", "-write_xing", "1"]
        if fmt == "m4a":
            cmd += ["-f", "ipod"]
    else:
        cmd += ["-map", "0:v:0", "-map", "0:a:0?", "-sn", "-dn"]
        okv, oka = COPY_OK[fmt]
        copy_video = okv is None or vcodec in okv
        if compatible and fmt in ("mp4", "mov") and vcodec != "h264":
            copy_video = False
        if copy_video:
            cmd += ["-c:v", "copy"]
        elif fmt == "webm":
            cmd += ["-c:v", "libvpx-vp9", "-crf", "32", "-b:v", "0", "-row-mt", "1", "-flags:v", "+bitexact"]
        else:
            cmd += ["-c:v", "libx264", "-crf", "19", "-preset", "fast", "-pix_fmt", "yuv420p",
                    "-flags:v", "+bitexact"]
        if acodec is None or oka is None or acodec in oka:
            cmd += ["-c:a", "copy"]
        elif fmt == "webm":
            cmd += ["-c:a", "libopus", "-b:a", "160k"]
        else:
            cmd += ["-c:a", "aac", "-b:a", "192k"]
        if fmt in ("mp4", "mov"):
            cmd += ["-movflags", "+faststart"]
            if vcodec == "hevc" and copy_video:
                cmd += ["-tag:v", "hvc1"]  # so Windows and Apple players open it
    cmd.append(str(dst))
    return cmd


def unique_path(folder: Path, name: str, ext: str) -> Path:
    path = folder / f"{name}.{ext}"
    n = 2
    while path.exists():
        path = folder / f"{name} ({n}).{ext}"
        n += 1
    return path


def download(job: Job, ffmpeg: str, progress: Progress | None = None,
             cancel: Callable[[], bool] | None = None) -> Path:
    """Download, then write the clean file. Returns its path."""
    ffprobe = ffprobe_next_to(ffmpeg)
    audio = job.fmt in AUDIO_FORMATS
    tmp = Path(tempfile.mkdtemp(prefix="clipnest-"))
    try:
        def hook(d):
            if cancel and cancel():
                raise Cancelled()
            if progress and d.get("status") == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                done = d.get("downloaded_bytes") or 0
                speed = d.get("speed") or 0
                text = f"Downloading… {done / 1e6:.1f} MB"
                if total:
                    text += f" of {total / 1e6:.1f} MB"
                if speed:
                    text += f"  ·  {speed / 1e6:.1f} MB/s"
                progress(done / total if total else 0.0, text)

        selector, sort = format_selector(job.fmt, job.height)
        opts = _base_opts() | {
            "format": selector,
            "format_sort": sort,
            "outtmpl": str(tmp / "source.%(ext)s"),
            "merge_output_format": "mkv",
            "ffmpeg_location": str(Path(ffmpeg).parent),
            "progress_hooks": [hook],
            "writethumbnail": audio and job.cover,
            "concurrent_fragment_downloads": 4,
            "playlist_items": "1",  # a post with several videos: the first, like the probe shows
        }
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                # extract again in this session: links and cookies from the probe may not carry over
                ydl.extract_info(job.clip.url, download=True)
        except yt_dlp.utils.DownloadError as e:
            if isinstance(e.exc_info[1] if e.exc_info else None, Cancelled):
                raise Cancelled() from e
            raise
        media = [p for p in tmp.iterdir() if p.stem == "source" and p.suffix.lower()
                 not in (".jpg", ".jpeg", ".png", ".webp", ".part")]
        if not media:
            raise RuntimeError("The download produced no file.")
        src = max(media, key=lambda p: p.stat().st_size)

        cover = None
        if audio and job.cover:
            thumbs = [p for p in tmp.iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")]
            if thumbs:
                cover = tmp / "cover.jpg"
                subprocess.run([ffmpeg, "-y", "-v", "error", "-i", str(thumbs[0]), "-frames:v", "1",
                                "-map_metadata", "-1", "-vf", "scale='min(1200,iw)':-2", str(cover)],
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                if not cover.exists():
                    cover = None

        vcodec, acodec = _streams(ffprobe, src)
        if audio and acodec is None:
            raise RuntimeError("This link has no sound to save.")
        job.folder.mkdir(parents=True, exist_ok=True)
        out = unique_path(job.folder, safe_name(job.name or job.clip.title), job.fmt)
        part = out.with_name(out.stem + ".part" + out.suffix)
        cmd = clean_command(ffmpeg, src, part, job.fmt, vcodec, acodec,
                            title=job.title if audio else "", artist=job.artist if audio else "",
                            cover=cover, bitrate=job.audio_bitrate, compatible=job.compatible)
        if progress:
            progress(0.0, "Cleaning metadata…")
        converting = not audio and cmd[cmd.index("-c:v") + 1] != "copy"
        run_ffmpeg(cmd, job.clip.duration, progress,
                   "Converting to H.264…" if converting and job.fmt in ("mp4", "mov") else
                   "Converting…" if converting else "Writing a clean file…", cancel)
        part.replace(out)
        return out
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
