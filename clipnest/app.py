"""The main window: paste (or just copy) a link, pick a format and quality, download."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication, QPixmap
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QLabel,
                               QLineEdit, QMessageBox, QProgressBar, QPushButton, QVBoxLayout, QWidget)

from clipnest import __version__, download
from clipnest.download import AUDIO_FORMATS, VIDEO_FORMATS, Clip, Job
from clipnest.util import app_data_dir, downloads_dir, find_ffmpeg, fmt_time
from clipnest.theme import app_icon
from clipnest.widgets import GlassWindow, Segmented, Worker, label

SETTINGS = app_data_dir() / "settings.json"
DEFAULTS = {"kind": "video", "video_fmt": "mp4", "audio_fmt": "mp3", "quality": "best", "bitrate": 320,
            "folder": "", "editor": True, "watch": True}


def load_settings() -> dict:
    try:
        return DEFAULTS | json.loads(SETTINGS.read_text("utf-8"))
    except (OSError, ValueError):
        return dict(DEFAULTS)


def save_settings(s: dict) -> None:
    try:
        SETTINGS.write_text(json.dumps(s, indent=1), "utf-8")
    except OSError:
        pass


def human_size(n: float) -> str:
    if n <= 0:
        return ""
    return f"~{n / 1e9:.1f} GB" if n >= 1e9 else f"~{n / 1e6:.0f} MB" if n >= 1e6 else f"~{n / 1e3:.0f} KB"


class MainWindow(GlassWindow):
    def __init__(self, ffmpeg: str):
        super().__init__("Clipnest")
        self.ffmpeg = ffmpeg
        self.settings = load_settings()
        self.clip: Clip | None = None
        self.queue: list[str] = []
        self.seen: set[str] = set()
        self.worker: Worker | None = None
        self.last_file: Path | None = None

        self.body.addWidget(label("Paste a link from X, TikTok, Instagram, Facebook, YouTube… "
                                  "or just copy one — Clipnest picks it up.", muted=True))
        row = QHBoxLayout()
        self.url = QLineEdit()
        self.url.setPlaceholderText("https://…")
        self.url.setClearButtonEnabled(True)
        paste = QPushButton("Paste")
        self.fetch_button = QPushButton("Get")
        self.fetch_button.setProperty("primary", True)
        row.addWidget(self.url, 1)
        row.addWidget(paste)
        row.addWidget(self.fetch_button)
        self.body.addLayout(row)
        paste.clicked.connect(self.paste)
        self.fetch_button.clicked.connect(self.fetch)
        self.url.returnPressed.connect(self.fetch)

        # what the link holds
        self.card = QWidget()
        self.card.setProperty("card", True)
        self.card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        card = QHBoxLayout(self.card)
        card.setContentsMargins(12, 12, 12, 12)
        self.thumb = QLabel()
        self.thumb.setFixedSize(160, 90)
        self.thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card.addWidget(self.thumb)
        info = QVBoxLayout()
        self.title = label("", bold=True, size=14)
        self.meta = label("", muted=True, size=12)
        info.addWidget(self.title)
        info.addWidget(self.meta)
        info.addStretch()
        card.addLayout(info, 1)
        self.body.addWidget(self.card)
        self.card.hide()

        # choices
        self.kind = Segmented([("video", "Video"), ("audio", "Audio only")], self.settings["kind"])
        self.body.addWidget(self.kind)
        grid = QHBoxLayout()
        self.fmt = QComboBox()
        self.quality = QComboBox()
        self.quality.setMinimumWidth(170)
        grid.addWidget(QLabel("Format"))
        grid.addWidget(self.fmt)
        grid.addSpacing(10)
        self.quality_label = QLabel("Quality")
        grid.addWidget(self.quality_label)
        grid.addWidget(self.quality, 1)
        self.body.addLayout(grid)

        names = QHBoxLayout()
        self.name = QLineEdit()
        self.name.setPlaceholderText("File name")
        names.addWidget(QLabel("Name"))
        names.addWidget(self.name, 1)
        self.body.addLayout(names)
        self.tags = QWidget()
        tags = QHBoxLayout(self.tags)
        tags.setContentsMargins(0, 0, 0, 0)
        self.tag_title = QLineEdit()
        self.tag_title.setPlaceholderText("Title tag")
        self.tag_artist = QLineEdit()
        self.tag_artist.setPlaceholderText("Artist tag")
        self.cover = QCheckBox("Cover")
        self.cover.setChecked(True)
        self.cover.setToolTip("Use the video's thumbnail as the album cover")
        tags.addWidget(self.tag_title, 1)
        tags.addWidget(self.tag_artist, 1)
        tags.addWidget(self.cover)
        self.body.addWidget(self.tags)

        where = QHBoxLayout()
        self.folder = Path(self.settings["folder"]) if self.settings["folder"] else downloads_dir()
        self.folder_label = label("", muted=True, size=12)
        change = QPushButton("Change…")
        where.addWidget(QLabel("Save to"))
        where.addWidget(self.folder_label, 1)
        where.addWidget(change)
        self.body.addLayout(where)
        change.clicked.connect(self.choose_folder)

        opts = QHBoxLayout()
        self.open_editor = QCheckBox("Open the editor after downloading")
        self.open_editor.setChecked(self.settings["editor"])
        self.watch = QCheckBox("Catch copied links")
        self.watch.setChecked(self.settings["watch"])
        self.watch.setToolTip("When you copy a video link anywhere, it appears here ready to download")
        opts.addWidget(self.open_editor)
        opts.addStretch()
        opts.addWidget(self.watch)
        self.body.addLayout(opts)
        self.body.addStretch()

        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setTextVisible(False)
        self.progress.hide()
        self.body.addWidget(self.progress)
        self.status = label("", size=12)
        self.body.addWidget(self.status)

        actions = QHBoxLayout()
        self.show_button = QPushButton("Show file")
        self.edit_button = QPushButton("Edit…")
        self.go = QPushButton("Download")
        self.go.setProperty("primary", True)
        self.go.setMinimumWidth(130)
        actions.addWidget(self.show_button)
        actions.addWidget(self.edit_button)
        actions.addStretch()
        actions.addWidget(QLabel(f"v{__version__}"))
        actions.addWidget(self.go)
        self.body.addLayout(actions)
        self.show_button.hide()
        self.edit_button.hide()
        self.go.setEnabled(False)
        self.show_button.clicked.connect(self.show_file)
        self.edit_button.clicked.connect(lambda: self.edit(self.last_file))
        self.go.clicked.connect(self.start_download)

        self.kind.changed.connect(self.kind_changed)
        self.fmt.currentTextChanged.connect(self.remember)
        self.quality.currentIndexChanged.connect(self.remember)
        for box in (self.open_editor, self.watch):
            box.toggled.connect(self.remember)
        QGuiApplication.clipboard().dataChanged.connect(self.clipboard_changed)
        self.kind_changed(self.settings["kind"])
        self.update_folder()
        self.frame.style_children()

    # ----------------------------------------------------------- choices

    def kind_changed(self, kind: str):
        audio = kind == "audio"
        self.fmt.blockSignals(True)
        self.fmt.clear()
        self.fmt.addItems([f.upper() for f in (AUDIO_FORMATS if audio else VIDEO_FORMATS)])
        self.fmt.setCurrentText(self.settings["audio_fmt" if audio else "video_fmt"].upper())
        self.fmt.blockSignals(False)
        self.tags.setVisible(audio)
        self.quality_label.setText("Bitrate" if audio else "Quality")
        self.fill_quality()
        self.remember()

    def fill_quality(self):
        audio = self.kind.get() == "audio"
        self.quality.blockSignals(True)
        self.quality.clear()
        if audio:
            for kbps in (320, 256, 192, 128):
                self.quality.addItem(f"{kbps} kbps", kbps)
            i = self.quality.findData(self.settings["bitrate"])
            self.quality.setCurrentIndex(max(0, i))
            size = download.estimate_size(self.clip, None, True) if self.clip else 0
            if size:
                self.quality.setToolTip(f"Source audio {human_size(size)}")
        else:
            heights = self.clip.heights if self.clip else [2160, 1440, 1080, 720, 480, 360]
            best = download.estimate_size(self.clip, None, False) if self.clip else 0
            self.quality.addItem("Best" + (f"  ·  {heights[0]}p" if self.clip and heights else "")
                                 + (f"  ·  {human_size(best)}" if best else ""), "best")
            for h in heights:
                size = download.estimate_size(self.clip, h, False) if self.clip else 0
                name = {2160: "4K", 1440: "2K"}.get(h, f"{h}p")
                if h in (2160, 1440):
                    name += f" ({h}p)"
                self.quality.addItem(name + (f"  ·  {human_size(size)}" if size else ""), h)
            i = self.quality.findData(self.settings["quality"])
            if i < 0 and isinstance(self.settings["quality"], int):
                # the clip has no such height: take the best below it
                below = [k for k in range(1, self.quality.count())
                         if self.quality.itemData(k) <= self.settings["quality"]]
                i = below[0] if below else 0
            self.quality.setCurrentIndex(max(0, i))
        self.quality.blockSignals(False)

    def remember(self, *_):
        kind = self.kind.get()
        s = self.settings
        s["kind"] = kind
        if self.fmt.currentText():
            s["audio_fmt" if kind == "audio" else "video_fmt"] = self.fmt.currentText().lower()
        data = self.quality.currentData()
        if data is not None and self.quality.count() and (self.clip or kind == "audio"):
            s["bitrate" if kind == "audio" else "quality"] = data
        s["editor"] = self.open_editor.isChecked()
        s["watch"] = self.watch.isChecked()
        s["folder"] = str(self.folder)
        save_settings(s)

    def choose_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Save downloads to", str(self.folder))
        if path:
            self.folder = Path(path)
            self.update_folder()
            self.remember()

    def update_folder(self):
        text = str(self.folder)
        self.folder_label.setText(text if len(text) < 52 else "…" + text[-50:])
        self.folder_label.setToolTip(text)

    # ----------------------------------------------------------- links

    def paste(self):
        self.url.setText(QGuiApplication.clipboard().text().strip())
        self.fetch()

    def clipboard_changed(self):
        if not self.watch.isChecked() or self.worker:
            return
        urls = [u for u in download.extract_urls(QGuiApplication.clipboard().text())
                if u not in self.seen]
        if not urls:
            return
        self.url.setText(" ".join(urls))
        self.status.setText(f"Caught a {download.platform(urls[0])[1]} link from the clipboard.")
        self.fetch()

    def fetch(self):
        if self.worker:
            return
        urls = download.extract_urls(self.url.text())
        if not urls:
            self.status.setText("That doesn't look like a link.")
            return
        self.seen.update(urls)
        self.queue = urls[1:]
        self.probe(urls[0])

    def probe(self, url: str):
        self.status.setText(f"Reading the {download.platform(url)[1]} link…")
        self.go.setEnabled(False)
        self.fetch_button.setEnabled(False)
        self.show_button.hide()
        self.edit_button.hide()

        def job(progress, cancelled):
            clip = download.probe(url)
            thumb = b""
            if clip.thumbnail:
                try:
                    req = urllib.request.Request(clip.thumbnail, headers={"User-Agent": "Mozilla/5.0"})
                    thumb = urllib.request.urlopen(req, timeout=10).read()
                except Exception:
                    thumb = b""
            return clip, thumb

        self.worker = Worker(job, self)
        self.worker.done.connect(self.probed)
        self.worker.failed.connect(self.failed)
        self.worker.start()

    def probed(self, result):
        self.worker = None
        clip, thumb = result
        self.clip = clip
        self.fetch_button.setEnabled(True)
        self.go.setEnabled(True)
        pm = QPixmap()
        if thumb and pm.loadFromData(thumb):
            self.thumb.setPixmap(pm.scaled(160, 90, Qt.AspectRatioMode.KeepAspectRatio,
                                           Qt.TransformationMode.SmoothTransformation))
        else:
            self.thumb.setText("▶")
        self.title.setText(clip.title)
        bits = [clip.platform]
        if clip.artist:
            bits.append(clip.artist)
        if clip.duration:
            bits.append(fmt_time(clip.duration))
        if clip.heights:
            bits.append(f"up to {clip.heights[0]}p")
        if self.queue:
            bits.append(f"+{len(self.queue)} more in the queue")
        self.meta.setText("  ·  ".join(bits))
        self.card.show()
        self.name.setText(download.safe_name(clip.title, 90))
        self.tag_title.setText(clip.title)
        self.tag_artist.setText(clip.artist)
        if not clip.heights and self.kind.get() == "video":
            self.kind.set("audio")
            self.kind_changed("audio")
        else:
            self.fill_quality()
        self.status.setText("Ready." if not self.queue else
                            f"Ready. {len(self.queue) + 1} links will download with the same settings.")
        self.frame.style_children()
        if self._auto_continue:
            self._auto_continue = False
            self.start_download()

    _auto_continue = False

    # ----------------------------------------------------------- download

    def start_download(self):
        if self.worker:
            self.worker.cancel()
            return
        if not self.clip:
            return
        kind = self.kind.get()
        fmt = self.fmt.currentText().lower()
        data = self.quality.currentData()
        job = Job(clip=self.clip, fmt=fmt, folder=self.folder, name=self.name.text().strip(),
                  height=None if kind == "audio" or data == "best" else data,
                  title=self.tag_title.text().strip(), artist=self.tag_artist.text().strip(),
                  cover=self.cover.isChecked(), audio_bitrate=data if kind == "audio" else 320)

        def work(progress, cancelled):
            return download.download(job, self.ffmpeg, progress, cancelled)

        self.worker = Worker(work, self)
        self.worker.progress.connect(self.on_progress)
        self.worker.done.connect(self.downloaded)
        self.worker.failed.connect(self.failed)
        self.worker.cancelled.connect(lambda: self.failed("Download stopped."))
        self.progress.setValue(0)
        self.progress.show()
        self.go.setText("Stop")
        self.fetch_button.setEnabled(False)
        self.status.setText("Starting…")
        self.worker.start()

    def on_progress(self, f: float, text: str):
        self.progress.setValue(int(f * 1000))
        self.status.setText(text if "MB" in text else f"{text} {f * 100:.0f}%")

    def downloaded(self, path: Path):
        self.worker = None
        self.last_file = path
        self.progress.hide()
        self.go.setText("Download")
        self.fetch_button.setEnabled(True)
        self.show_button.show()
        self.edit_button.show()
        self.status.setText(f"Saved {path.name} — clean, no source tags.")
        if self.queue:
            self._auto_continue = True
            self.probe(self.queue.pop(0))
        elif self.open_editor.isChecked():
            QTimer.singleShot(150, lambda: self.edit(path))

    def failed(self, message: str):
        self.worker = None
        self.progress.hide()
        self.go.setText("Download")
        self.go.setEnabled(self.clip is not None)
        self.fetch_button.setEnabled(True)
        self.status.setText(message)
        if self.queue and message != "Download stopped.":
            self._auto_continue = True
            self.probe(self.queue.pop(0))

    def show_file(self):
        if self.last_file and self.last_file.exists():
            subprocess.Popen(["explorer", "/select,", str(self.last_file)])

    def edit(self, path: Path | None):
        if not path or not path.exists():
            return
        from clipnest.editor import Editor

        Editor(self.ffmpeg, path, "original").run()


def main() -> None:
    if sys.platform == "win32":
        # its own taskbar button and icon, not python.exe's
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Niro54321.Clipnest")
    app = QApplication(sys.argv)
    app.setApplicationName("Clipnest")
    app.setWindowIcon(app_icon())
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        QMessageBox.critical(None, "Clipnest", "Clipnest needs FFmpeg.\n\nInstall it with:\n"
                             "winget install Gyan.FFmpeg\n\nthen open Clipnest again.")
        sys.exit(1)
    if len(sys.argv) > 2 and sys.argv[1] == "--edit":
        from clipnest.editor import Editor

        Editor(ffmpeg, Path(sys.argv[2])).run()
        os._exit(0)
    win = MainWindow(ffmpeg)
    win.center_on_screen()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
