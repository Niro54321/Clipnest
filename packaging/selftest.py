"""Checks a packaged build before it ships; not part of the installer.

    clipnest-selftest.exe <work folder> [--network]

Inside the packaged app: yt-dlp with its impersonation and YouTube extras, a
clean download-style write, an editor export with text and logo, playback
through Qt Multimedia, and the two windows. --network also reads a TikTok link.
"""

import subprocess
import sys
import time
from pathlib import Path


def check(name, ok, detail=""):
    print(f"{'ok  ' if ok else 'FAIL'} {name} {detail}", flush=True)
    if not ok:
        raise SystemExit(1)


def main() -> int:
    work = Path(sys.argv[1])
    work.mkdir(parents=True, exist_ok=True)
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv[:1])

    import yt_dlp
    from yt_dlp.networking.impersonate import ImpersonateTarget

    from clipnest import download, edit
    from clipnest.util import ffprobe_next_to, find_ffmpeg

    ydl = yt_dlp.YoutubeDL({"quiet": True})
    targets = ydl._get_available_impersonate_targets()
    check("impersonation (TikTok)", bool(targets), f"{len(targets)} targets")
    check("impersonate chrome", any(t[0] in ImpersonateTarget.from_str("chrome") for t in targets))
    __import__("yt_dlp_ejs")  # YouTube's player challenges

    check("yt-dlp extras", True, yt_dlp.version.__version__)

    ffmpeg = find_ffmpeg()
    check("ffmpeg found", ffmpeg is not None, str(ffmpeg))
    clip = work / "clip.mkv"
    subprocess.run([ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=1280x720:d=4:r=25",
                    "-f", "lavfi", "-i", "sine=f=440:d=4", "-c:v", "libx264", "-preset", "ultrafast",
                    "-c:a", "aac", "-metadata", "comment=https://example.com/x", "-shortest", str(clip)], check=True)
    v, a = download._streams(ffprobe_next_to(ffmpeg), clip)
    for fmt in ("mp4", "mp3"):
        out = work / f"clean.{fmt}"
        download.run_ffmpeg(download.clean_command(ffmpeg, clip, out, fmt, v, a, title="T"), 4, None, "")
        tags = subprocess.run([ffprobe_next_to(ffmpeg), "-v", "error", "-show_entries", "format_tags",
                               "-of", "compact", str(out)], capture_output=True, text=True).stdout
        check(f"clean {fmt}", "example.com" not in tags)

    logo = work / "logo.png"
    subprocess.run([ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=red:s=120x60", "-frames:v", "1",
                    str(logo)], check=True)
    media = edit.inspect(ffmpeg, clip)
    spec = edit.EditSpec(start=0.5, end=3, aspect="9:16", text="مرحبا Hello", logo=logo)
    out = edit.export(ffmpeg, media, spec, work, "edited")
    size = subprocess.run([ffprobe_next_to(ffmpeg), "-v", "error", "-select_streams", "v:0", "-show_entries",
                           "stream=width,height", "-of", "csv=p=0", str(out)], capture_output=True, text=True).stdout
    check("editor export 9:16", size.strip() == "1080,1920", size.strip())

    from PySide6.QtCore import QUrl
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer, QVideoSink

    frames = []
    sink = QVideoSink()
    sink.videoFrameChanged.connect(lambda f: f.isValid() and frames.append(1))
    audio = QAudioOutput()
    audio.setVolume(0.0)
    player = QMediaPlayer()
    player.setVideoOutput(sink)
    player.setAudioOutput(audio)
    player.setSource(QUrl.fromLocalFile(str(out)))
    player.play()
    end = time.time() + 5
    while time.time() < end and len(frames) < 15:
        app.processEvents()
        time.sleep(0.01)
    player.stop()
    check("playback", bool(frames), f"{len(frames)} frames")

    from clipnest.app import MainWindow
    from clipnest.editor import Editor

    w = MainWindow(ffmpeg)
    e = Editor(ffmpeg, out)
    check("windows", w.fmt.count() > 0 and e.spec().end > 2)
    e.done(0)
    w.close()

    if "--network" in sys.argv:
        c = download.probe("https://www.tiktok.com/@cartoons_and_movi/video/7683106671551434002")
        check("tiktok link", bool(c.heights), c.platform)
    print("all good")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
