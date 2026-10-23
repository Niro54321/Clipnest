# Clipnest

A liquid-glass video downloader for Windows. Paste a link from X/Twitter, TikTok,
Instagram, Facebook, YouTube or [any site yt-dlp supports](https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md),
choose a format and quality (up to 4K, or audio only), and get a clean file.
Then trim it, resize it for TikTok/Reels, and add text and a logo in the built-in editor.

## Features

- **Any quality, any format**: MP4, WebM, MKV, MOV, or audio only as MP3, M4A, Opus, FLAC or WAV.
  The quality list shows what the link actually offers (up to 4K) with an estimated size for each.
- **Plays everywhere**: some sites (TikTok, YouTube above 1080p) send HEVC or AV1, which many
  Windows players can't open. Clipnest picks the highest resolution first, prefers H.264 when it's
  on offer at that resolution, and otherwise converts to H.264 at the same quality (switch it off to keep the original).
- **Clean metadata**: every tag the source left is dropped (title, comment, source URL, chapters,
  encoder version) and the file gets today's date, not the upload date. MP3 and M4A get the
  title, artist and cover you choose instead.
- **Editor after the download**
  - Trim: type the minutes to keep, or scrub the preview and press *Start here* / *End here*.
  - Resize presets: 9:16 TikTok/Reels, 1:1, 4:5, 16:9, either cropped to fill or fitted on a blurred copy.
  - Text overlay in any language (Arabic shapes and runs right to left), with size, position,
    colour, outline or a background box.
  - Logo/image overlay with size, corner and opacity.
  - A preview you can play with sound (Play/Pause, 10 s back and forward; Space, ← and →)
    with the edits drawn live, and FFmpeg's exact frame when paused. Playback stays inside the trim.
- **Smart, and all offline**
  - *Catch copied links*: copy a video link anywhere and it appears in Clipnest, ready to download.
  - Paste several links at once and they download one after another with the same settings.
  - *Find the subject*: when cropping to 9:16 or square, Clipnest looks at motion and detail
    across the clip and puts the crop where the action is.
  - *Cut silence*: finds where the sound starts and ends and trims the quiet bits.
  - *Auto text colour*: picks black or white from how bright the video is behind the text.
- **Liquid glass**: a frosted, translucent window that shows the desktop behind it, with
  text that turns dark on light backgrounds and light on dark ones.

## Install and run

You need Windows 10/11, Python 3.10 or newer, and FFmpeg (it isn't bundled):

```bash
winget install Gyan.FFmpeg
```

```bash
git clone https://github.com/Niro54321/Clipnest.git
cd Clipnest
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m clipnest
```

`requirements.txt` installs yt-dlp with its extras: `curl_cffi` (TikTok needs browser
impersonation) and `yt-dlp-ejs` (YouTube's player challenges). Update yt-dlp now and then,
since sites change: `.venv\Scripts\python -m pip install -U "yt-dlp[default,curl-cffi]"`.

Clipnest finds FFmpeg on `PATH` or in winget's install folders. Downloads go to
`Downloads\Clipnest` unless you choose another folder. To open the editor on a file you already have:

```bash
.venv\Scripts\python -m clipnest --edit "C:\path\to\video.mp4"
```

## Tests

```bash
.venv\Scripts\python -m pytest tests -q
```

The tests make their own clips with FFmpeg and check the clean metadata, every export format,
the editor presets, trimming, overlays and the smart helpers. Set `CLIPNEST_NETWORK=1` to also
download a real public video.

## How it works

| Part | File |
| --- | --- |
| Reading links, downloading (yt-dlp), writing the clean file (FFmpeg) | `clipnest/download.py` |
| Trim, resize, text and logo export, preview frames | `clipnest/edit.py` |
| Subject finding, silence detection, text colour | `clipnest/smart.py` |
| Main window and editor | `clipnest/app.py`, `clipnest/editor.py` |
| Frosted glass window and controls | `clipnest/glass.py`, `clipnest/glassui.py`, `clipnest/widgets.py` |

## Use it responsibly

Download only public content you have the right to save: your own videos, ones whose owner
allows it, or ones the law lets you keep. Respect each site's terms and creators' copyright.
Clipnest doesn't sign in to accounts, read browser cookies or get around DRM; private and
protected videos fail with a clear message.

## License

[MIT](LICENSE). Clipnest uses [yt-dlp](https://github.com/yt-dlp/yt-dlp) (Unlicense),
[FFmpeg](https://ffmpeg.org) (installed separately, LGPL/GPL) and [Qt for Python](https://www.qt.io/qt-for-python) (LGPL).
