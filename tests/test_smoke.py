"""Smoke tests: clean metadata, every editor option, and the smart helpers, on
clips FFmpeg makes on the spot. Set CLIPNEST_NETWORK=1 to also download a real link.

    python -m pytest tests -q
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from clipnest import download, edit, smart  # noqa: E402
from clipnest.util import ffprobe_next_to, find_ffmpeg, parse_time  # noqa: E402

FFMPEG = find_ffmpeg()
pytestmark = pytest.mark.skipif(FFMPEG is None, reason="FFmpeg not found")
APP = QApplication.instance() or QApplication([])


def tags(path: Path) -> dict:
    out = subprocess.run([ffprobe_next_to(FFMPEG), "-v", "error", "-print_format", "json",
                          "-show_format", "-show_streams", str(path)], capture_output=True, text=True,
                         encoding="utf-8").stdout
    data = json.loads(out)
    found = dict((data["format"].get("tags") or {}))
    for s in data["streams"]:
        for k, v in (s.get("tags") or {}).items():
            found[f"{s['codec_type']}:{k}"] = v
    return {"tags": found, "streams": data["streams"], "format": data["format"]}


@pytest.fixture(scope="session")
def clip(tmp_path_factory) -> Path:
    """A 6 s 1280x720 clip with a moving box on the right, silence at both ends,
    and the kind of tags a site leaves behind."""
    folder = tmp_path_factory.mktemp("src")
    path = folder / "source.mkv"
    subprocess.run([FFMPEG, "-v", "error", "-y",
                    "-f", "lavfi", "-i", "color=c=gray:s=1280x720:d=6:r=25",
                    "-f", "lavfi", "-i", "color=c=red:s=160x160:d=6:r=25",
                    "-f", "lavfi", "-i", "sine=f=440:d=4:sample_rate=44100",
                    "-filter_complex",
                    "[0:v][1:v]overlay=x=980+60*sin(t*3):y=280[v];"
                    "[2:a]adelay=1000|1000,apad=whole_dur=6[a]",
                    "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "ultrafast",
                    "-c:a", "aac", "-t", "6",
                    "-metadata", "comment=https://example.com/watch?v=abc",
                    "-metadata", "purl=https://example.com/watch?v=abc",
                    "-metadata", "title=Source title", str(path)], check=True)
    return path


@pytest.fixture(scope="session")
def logo(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("logo") / "logo.png"
    subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=blue@0.8:s=200x100,format=rgba",
                    "-frames:v", "1", str(path)], check=True)
    return path


def run_clean(src: Path, dst: Path, fmt: str, **kw):
    v, a = download._streams(ffprobe_next_to(FFMPEG), src)
    download.run_ffmpeg(download.clean_command(FFMPEG, src, dst, fmt, v, a, **kw), 6, None, "")


@pytest.mark.parametrize("fmt", ["mp4", "webm", "mkv", "mov"])
def test_clean_video_has_no_source_tags(clip, tmp_path, fmt):
    out = tmp_path / f"out.{fmt}"
    run_clean(clip, out, fmt)
    info = tags(out)
    text = json.dumps(info["tags"]).lower()
    assert "example.com" not in text and "source title" not in text
    assert not any(k.lower() in ("comment", "purl", "title") for k in info["tags"])
    # Matroska always names a muxing app; bitexact keeps it to a bare "Lavf", no version
    assert all(v in ("Lavf", "Lavc libvpx-vp9", "Lavc libopus", "Lavc libx264", "Lavc aac")
               for k, v in info["tags"].items() if k.lower().endswith("encoder"))
    assert {s["codec_type"] for s in info["streams"]} == {"video", "audio"}


def test_mp3_gets_chosen_tags_and_cover(clip, tmp_path, logo):
    cover = tmp_path / "cover.jpg"
    subprocess.run([FFMPEG, "-v", "error", "-y", "-i", str(logo), str(cover)], check=True)
    out = tmp_path / "song.mp3"
    run_clean(clip, out, "mp3", title="My Song — أغنية", artist="Someone", cover=cover)
    info = tags(out)
    assert info["tags"].get("title") == "My Song — أغنية"
    assert info["tags"].get("artist") == "Someone"
    assert "comment" not in info["tags"] and "example.com" not in json.dumps(info["tags"])
    assert any(s.get("disposition", {}).get("attached_pic") for s in info["streams"])


@pytest.mark.parametrize("fmt", ["m4a", "opus", "flac", "wav"])
def test_audio_formats(clip, tmp_path, fmt):
    out = tmp_path / f"a.{fmt}"
    run_clean(clip, out, fmt, title="T")
    info = tags(out)
    assert [s["codec_type"] for s in info["streams"] if s["codec_type"] == "audio"]
    assert "example.com" not in json.dumps(info["tags"])


@pytest.mark.parametrize("aspect,fit,size", [("9:16", "fill", (1080, 1920)), ("1:1", "blur", (1080, 1080)),
                                             ("16:9", "fill", (1920, 1080)), ("original", "fill", (1280, 720))])
def test_editor_export(clip, tmp_path, logo, aspect, fit, size):
    media = edit.inspect(FFMPEG, clip)
    spec = edit.EditSpec(start=1.0, end=3.5, aspect=aspect, fit=fit, text="مرحبا Hello",
                         logo=logo, logo_pos="bottom-right", text_box=aspect == "1:1")
    out = edit.export(FFMPEG, media, spec, tmp_path, "edited")
    info = tags(out)
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    assert (v["width"], v["height"]) == size
    assert abs(float(info["format"]["duration"]) - 2.5) < 0.2
    assert "encoder" not in {k.lower() for k in info["tags"]}


def test_audio_trim(clip, tmp_path):
    song = tmp_path / "s.mp3"
    run_clean(clip, song, "mp3", title="Keep me")
    media = edit.inspect(FFMPEG, song)
    out = edit.export(FFMPEG, media, edit.EditSpec(start=1, end=3, fmt="mp3"), tmp_path, "cut")
    info = tags(out)
    assert abs(float(info["format"]["duration"]) - 2) < 0.15
    assert info["tags"].get("title") == "Keep me"


def test_smart_reframe_follows_subject(clip):
    media = edit.inspect(FFMPEG, clip)
    fx, _ = edit.smart_reframe(FFMPEG, media, edit.EditSpec(aspect="9:16"))
    assert fx > 0.75   # the moving box is on the right


def test_smart_trim_cuts_silence(clip):
    start, end = smart.silence_bounds(FFMPEG, clip, 6.0)
    assert 0.6 < start < 1.2 and 4.8 < end < 5.4


def test_text_color_from_brightness(clip):
    level = smart.brightness(FFMPEG, clip, 1.0, 0.7, 0.95)
    assert 0.3 < level < 0.7
    assert smart.text_colors(0.9)[0] == "#111111" and smart.text_colors(0.1)[0] == "#FFFFFF"


def test_links_and_platforms():
    text = "look https://www.tiktok.com/@a/video/1 and https://x.com/u/status/2, https://x.com/u/status/2"
    urls = download.extract_urls(text)
    assert urls == ["https://www.tiktok.com/@a/video/1", "https://x.com/u/status/2"]
    assert download.platform(urls[0])[0] == "tiktok"
    assert download.platform("https://fb.watch/xyz")[0] == "facebook"
    assert download.platform("https://www.instagram.com/reel/abc/")[0] == "instagram"
    assert parse_time("1:30") == 90 and parse_time("0:01:30") == 90 and parse_time("x") is None


@pytest.mark.skipif(os.environ.get("CLIPNEST_NETWORK") != "1", reason="network test")
def test_real_download(tmp_path):
    c = download.probe("https://www.youtube.com/watch?v=jNQXAC9IVRw")
    assert c.heights and c.duration > 10
    out = download.download(download.Job(clip=c, fmt="mp4", height=360, folder=tmp_path, name="zoo"), FFMPEG)
    assert out.exists() and "youtube" not in json.dumps(tags(out)["tags"]).lower()
    mp3 = download.download(download.Job(clip=c, fmt="mp3", folder=tmp_path, name="zoo",
                                         title=c.title, artist=c.artist), FFMPEG)
    assert tags(mp3)["tags"].get("title") == c.title


def test_preview_frame_matches_preset(clip, tmp_path, logo):
    media = edit.inspect(FFMPEG, clip)
    spec = edit.EditSpec(aspect="9:16", text="نص", logo=logo)
    text_png = edit.text_layer(spec, media, tmp_path)
    out = tmp_path / "frame.png"
    subprocess.run(edit.preview_command(FFMPEG, media, spec, 2.0, out, text_png, width=360), check=True)
    v = tags(out)["streams"][0]
    assert (v["width"], v["height"]) == (360, 640)


def test_windows_build(clip):
    """The main window and the editor come up with all their controls (offscreen)."""
    from PySide6.QtWidgets import QApplication

    if not isinstance(QApplication.instance(), QApplication):
        pytest.skip("needs a QApplication; run this file on its own")
    from clipnest.app import MainWindow
    from clipnest.editor import Editor

    w = MainWindow(FFMPEG)
    assert w.fmt.count() and w.quality.count()
    e = Editor(FFMPEG, clip)
    assert e.spec().end == pytest.approx(6.0, abs=0.1)
    e.done(0)
    w.close()


def test_hevc_becomes_h264_when_compatible(clip, tmp_path):
    hevc = tmp_path / "hevc.mkv"
    subprocess.run([FFMPEG, "-v", "error", "-y", "-i", str(clip), "-t", "2", "-c:v", "libx265",
                    "-preset", "ultrafast", "-c:a", "copy", str(hevc)], check=True)
    for compatible, codec in ((True, "h264"), (False, "hevc")):
        out = tmp_path / f"out-{compatible}.mp4"
        v, a = download._streams(ffprobe_next_to(FFMPEG), hevc)
        download.run_ffmpeg(download.clean_command(FFMPEG, hevc, out, "mp4", v, a, compatible=compatible),
                            2, None, "")
        assert download._streams(ffprobe_next_to(FFMPEG), out)[0] == codec


def test_format_choice_prefers_resolution_then_codec():
    assert download.format_selector("mp4", 1080) == ("bv*+ba/b", ["res:1080", "fps", "vcodec:h264"])
    assert download.format_selector("webm", None)[1] == ["res", "fps", "vcodec:vp9"]
    assert download.format_selector("mp3", None)[0] == "ba/b"


@pytest.mark.skipif(os.environ.get("CLIPNEST_NETWORK") != "1", reason="network test")
def test_real_tiktok(tmp_path):
    c = download.probe("https://www.tiktok.com/@cartoons_and_movi/video/7683106671551434002")
    assert c.platform == "TikTok" and c.heights
    out = download.download(download.Job(clip=c, fmt="mp4", folder=tmp_path, name="tt"), FFMPEG)
    assert download._streams(ffprobe_next_to(FFMPEG), out)[0] == "h264"
    assert "tiktok" not in json.dumps(tags(out)["tags"]).lower()
