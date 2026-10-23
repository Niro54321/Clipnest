"""The step after a download: trim, resize for TikTok/Reels/YouTube, add text
and a logo, with a live preview that FFmpeg renders with the real edits."""

from __future__ import annotations

import dataclasses
import os
import subprocess
import tempfile
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
                               QProgressBar, QPushButton, QScrollArea, QSizePolicy, QSlider, QVBoxLayout,
                               QWidget)

from clipnest import edit, smart
from clipnest.download import AUDIO_FORMATS, VIDEO_FORMATS
from clipnest.util import fmt_time, parse_time
from clipnest.widgets import GlassDialog, Segmented, SliderRow, Swatches, Worker, label

COLORS = ["#FFFFFF", "#111111", "#FFD60A", "#FF3B5C", "#7C5CFF", "#34D399"]
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def section(title: str) -> tuple[QWidget, QVBoxLayout]:
    box = QWidget()
    box.setProperty("card", True)
    box.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
    lay = QVBoxLayout(box)
    lay.setContentsMargins(14, 12, 14, 12)
    lay.setSpacing(8)
    lay.addWidget(label(title, bold=True, size=14))
    return box, lay


class Editor(GlassDialog):
    def __init__(self, ffmpeg: str, path: Path, suggested_aspect: str = "original"):
        super().__init__(f"Edit · {path.name}", primary="Export")
        self.ffmpeg = ffmpeg
        self.media = edit.inspect(ffmpeg, path)
        self.video = self.media.has_video
        self.tmp = tempfile.TemporaryDirectory(prefix="clipnest-preview-")
        self.generation = 0
        self.worker: Worker | None = None
        self.preview_worker: Worker | None = None
        self.reframed: dict[str, tuple[float, float]] = {}
        self.auto_colors = ("#FFFFFF", "#000000")
        self.result: Path | None = None

        row = QHBoxLayout()
        row.setSpacing(14)
        self.body.addLayout(row, 1)

        # left: preview and its time slider
        left = QVBoxLayout()
        self.preview = QLabel("Loading preview…")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(420, 320)
        self.preview.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.preview.setProperty("card", True)
        self.preview.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        left.addWidget(self.preview, 1)
        scrub = QHBoxLayout()
        self.time = QSlider(Qt.Orientation.Horizontal)
        self.time.setRange(0, max(1, int(self.media.duration * 10)))
        self.time_label = QLabel("0:00")
        self.time_label.setMinimumWidth(90)
        scrub.addWidget(self.time, 1)
        scrub.addWidget(self.time_label)
        left.addLayout(scrub)
        row.addLayout(left, 1)

        # right: the settings
        panel = QWidget()
        side = QVBoxLayout(panel)
        side.setContentsMargins(0, 0, 6, 0)
        side.setSpacing(10)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(panel)
        scroll.setFixedWidth(370)
        row.addWidget(scroll)

        box, lay = section("Trim")
        times = QHBoxLayout()
        self.start = QLineEdit("0:00")
        self.end = QLineEdit(fmt_time(self.media.duration))
        for w in (self.start, self.end):
            w.setMaximumWidth(90)
            w.setToolTip("Minutes:seconds, e.g. 1:30 or 0:01:30")
        times.addWidget(QLabel("From"))
        times.addWidget(self.start)
        times.addWidget(QLabel("to"))
        times.addWidget(self.end)
        times.addStretch()
        lay.addLayout(times)
        here = QHBoxLayout()
        b_start = QPushButton("Start here")
        b_end = QPushButton("End here")
        b_smart = QPushButton("✨ Cut silence")
        b_smart.setToolTip("Find where the sound starts and ends and trim the quiet bits")
        for b in (b_start, b_end, b_smart):
            here.addWidget(b)
        here.addStretch()
        lay.addLayout(here)
        self.length = label("", muted=True, size=12)
        lay.addWidget(self.length)
        b_start.clicked.connect(lambda: self.start.setText(fmt_time(self.time.value() / 10)))
        b_end.clicked.connect(lambda: self.end.setText(fmt_time(self.time.value() / 10)))
        b_smart.clicked.connect(self.smart_trim)
        side.addWidget(box)

        self.video_boxes = []
        box, lay = section("Size")
        self.aspect = Segmented([(k, n.split(" ")[0]) for k, n in edit.ASPECT_NAMES], suggested_aspect)
        for k, n in edit.ASPECT_NAMES:
            self.aspect.buttons[k].setToolTip(n)
        lay.addWidget(self.aspect)
        self.aspect_hint = label("", muted=True, size=12)
        lay.addWidget(self.aspect_hint)
        self.fit = Segmented([("fill", "Fill (crop)"), ("blur", "Fit on blur")], "fill")
        lay.addWidget(self.fit)
        self.focus = SliderRow("Crop at", 0, 100, 50, "%")
        lay.addWidget(self.focus)
        self.reframe_button = QPushButton("✨ Find the subject")
        self.reframe_button.setToolTip("Look at the clip and put the crop where the action is")
        lay.addWidget(self.reframe_button)
        self.reframe_button.clicked.connect(lambda: self.smart_reframe(force=True))
        side.addWidget(box)
        self.video_boxes.append(box)

        box, lay = section("Text")
        self.text = QLineEdit()
        self.text.setPlaceholderText("Caption — any language, Arabic too")
        lay.addWidget(self.text)
        self.text_size = SliderRow("Size", 2, 16, 6, "%", scale=2)
        lay.addWidget(self.text_size)
        self.text_pos = Segmented([("top", "Top"), ("center", "Middle"), ("bottom", "Bottom")], "bottom")
        lay.addWidget(self.text_pos)
        self.text_color = Swatches(COLORS, "auto")
        lay.addWidget(self.text_color)
        self.text_box = QCheckBox("Background box")
        lay.addWidget(self.text_box)
        side.addWidget(box)
        self.video_boxes.append(box)

        box, lay = section("Logo")
        pick = QHBoxLayout()
        self.logo_button = QPushButton("Choose image…")
        self.logo_clear = QPushButton("Remove")
        pick.addWidget(self.logo_button)
        pick.addWidget(self.logo_clear)
        pick.addStretch()
        lay.addLayout(pick)
        self.logo_name = label("No logo", muted=True, size=12)
        lay.addWidget(self.logo_name)
        self.logo_pos = Segmented([("top-left", "↖"), ("top-right", "↗"), ("center", "•"),
                                   ("bottom-left", "↙"), ("bottom-right", "↘")], "top-right")
        lay.addWidget(self.logo_pos)
        self.logo_size = SliderRow("Size", 5, 50, 18, "%")
        self.logo_opacity = SliderRow("Opacity", 10, 100, 90, "%")
        lay.addWidget(self.logo_size)
        lay.addWidget(self.logo_opacity)
        self.logo: Path | None = None
        self.logo_button.clicked.connect(self.choose_logo)
        self.logo_clear.clicked.connect(lambda: self.set_logo(None))
        side.addWidget(box)
        self.video_boxes.append(box)

        box, lay = section("Save as")
        self.fmt = QComboBox()
        source_ext = path.suffix.lower().lstrip(".")
        if self.video:
            self.fmt.addItems(VIDEO_FORMATS)
            self.fmt.setCurrentText(source_ext if source_ext in VIDEO_FORMATS else "mp4")
        else:
            self.fmt.addItems(AUDIO_FORMATS)
            self.fmt.setCurrentText(source_ext if source_ext in AUDIO_FORMATS else "mp3")
        lay.addWidget(self.fmt)
        lay.addWidget(label("Saved next to the original. No source tags are written.", muted=True, size=12))
        side.addWidget(box)
        side.addStretch()

        if not self.video:
            for b in self.video_boxes:
                b.hide()
            self.preview.setText("Audio file — trim it, then export.")

        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setTextVisible(False)
        self.progress.setMaximumWidth(220)
        self.progress.hide()
        self.status = QLabel("")
        self.open_button = QPushButton("Show file")
        self.open_button.hide()
        self.open_button.clicked.connect(self.show_result)
        self.footer_left.addWidget(self.progress)
        self.footer_left.addWidget(self.status, 1)
        self.footer_left.addWidget(self.open_button)
        self.ok_button.clicked.connect(self.export)

        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(260)
        self.timer.timeout.connect(self.render_preview)
        for sig in (self.time.valueChanged, self.text.textChanged, self.start.editingFinished,
                    self.end.editingFinished, self.text_box.toggled, self.focus.changed,
                    self.text_size.changed, self.logo_size.changed, self.logo_opacity.changed,
                    self.text_pos.changed, self.logo_pos.changed, self.fit.changed, self.text_color.changed):
            sig.connect(self.changed)
        self.aspect.changed.connect(self.aspect_changed)
        self.time.valueChanged.connect(lambda v: self.time_label.setText(
            f"{fmt_time(v / 10)} / {fmt_time(self.media.duration)}"))
        self.time.setValue(min(int(self.media.duration * 10), 20))
        self.frame.style_children()
        self.aspect_changed(suggested_aspect)

    # ----------------------------------------------------------- state

    def spec(self) -> edit.EditSpec:
        start = parse_time(self.start.text()) or 0.0
        end = parse_time(self.end.text())
        if end is None or end > self.media.duration:
            end = self.media.duration
        if end <= start:
            end = self.media.duration
        color = self.text_color.get()
        text_color, outline = self.auto_colors if color == "auto" else (color, smart.text_colors(
            0.9 if color in ("#FFFFFF", "#FFD60A", "#34D399") else 0.1)[1])
        return edit.EditSpec(start=start, end=end, aspect=self.aspect.get() or "original",
                             fit=self.fit.get() or "fill", focus_x=self.focus.get() / 100,
                             focus_y=self._focus_y, text=self.text.text(), text_size=self.text_size.get(),
                             text_color=text_color, outline_color=outline,
                             text_pos=self.text_pos.get() or "bottom", text_box=self.text_box.isChecked(),
                             logo=self.logo, logo_size=self.logo_size.get(),
                             logo_pos=self.logo_pos.get() or "top-right",
                             logo_opacity=self.logo_opacity.get() / 100, fmt=self.fmt.currentText())

    _focus_y = 0.5

    def changed(self, *_):
        s = self.spec()
        self.length.setText(f"Keeps {fmt_time(s.end - s.start)} of {fmt_time(self.media.duration)}")
        if self.video:
            self.timer.start()

    def aspect_changed(self, key):
        crop = key != "original"
        self.fit.setEnabled(crop)
        self.focus.setEnabled(crop)
        self.reframe_button.setEnabled(crop)
        size = edit.ASPECTS.get(key)
        self.aspect_hint.setText(f"{size[0]} × {size[1]}" if size else
                                 f"{self.media.width} × {self.media.height}, as it is")
        if crop and self.video:
            self.smart_reframe()
        self.changed()

    # ----------------------------------------------------------- smart helpers

    def smart_reframe(self, force: bool = False):
        """Put the crop on the subject, once per preset unless asked again."""
        key = self.aspect.get()
        if key in self.reframed and not force:
            fx, fy = self.reframed[key]
            self.focus.set(fx * 100)
            self._focus_y = fy
            return
        spec = self.spec()
        self.reframe_button.setText("✨ Looking…")
        self.reframe_button.setEnabled(False)

        def job(progress, cancelled):
            return key, edit.smart_reframe(self.ffmpeg, self.media, spec)

        def done(result):
            k, (fx, fy) = result
            self.reframed[k] = (fx, fy)
            self.reframe_button.setText("✨ Find the subject")
            self.reframe_button.setEnabled(self.aspect.get() != "original")
            if self.aspect.get() == k:
                self.focus.set(fx * 100)
                self._focus_y = fy
                self.changed()

        w = Worker(job, self)
        w.done.connect(done)
        w.failed.connect(lambda e: self.reframe_button.setText("✨ Find the subject"))
        w.start()

    def smart_trim(self):
        self.status.setText("Listening for silence…")

        def job(progress, cancelled):
            return smart.silence_bounds(self.ffmpeg, self.media.path, self.media.duration)

        def done(bounds):
            start, end = bounds
            if start <= 0.05 and end >= self.media.duration - 0.05:
                self.status.setText("No silence at the ends to cut.")
                return
            self.start.setText(fmt_time(start) if start >= 1 else f"{start:.1f}")
            self.end.setText(fmt_time(end) if end >= 1 else f"{end:.1f}")
            self.status.setText(f"Cut {start:.1f}s at the start and {self.media.duration - end:.1f}s at the end.")
            self.changed()

        w = Worker(job, self)
        w.done.connect(done)
        w.failed.connect(self.status.setText)
        w.start()

    def choose_logo(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose a logo", str(Path.home()),
                                              "Images (*.png *.jpg *.jpeg *.webp *.bmp *.gif)")
        if path:
            self.set_logo(Path(path))

    def set_logo(self, path: Path | None):
        self.logo = path
        self.logo_name.setText(path.name if path else "No logo")
        self.changed()

    # ----------------------------------------------------------- preview

    def render_preview(self):
        self.generation += 1
        gen = self.generation
        spec = self.spec()
        t = self.time.value() / 10
        folder = Path(self.tmp.name)
        want_auto = self.text_color.get() == "auto" and spec.text.strip()
        # Qt draws text on this thread only; the thread does the FFmpeg parts
        text_png = None
        if spec.text.strip():
            W, H = edit.out_size(spec, self.media)
            text_png = folder / f"text-{gen}.png"
            edit.render_text(spec, W, H, text_png)

        def job(progress, cancelled):
            colors = None
            if want_auto:
                top, bottom = edit.text_band(spec.text_pos)
                colors = smart.text_colors(smart.brightness(self.ffmpeg, self.media.path, t, top, bottom))
            out = folder / f"frame-{gen}.png"
            cmd = edit.preview_command(self.ffmpeg, self.media, spec, t, out, text_png)
            subprocess.run(cmd, capture_output=True, creationflags=NO_WINDOW)
            return gen, out, colors

        def done(result):
            g, out, colors = result
            if colors and colors != self.auto_colors:
                # the picture behind the text calls for the other colour: draw it again
                self.auto_colors = colors
                if g == self.generation:
                    self.timer.start(0)
            if g != self.generation or not out.exists():
                return
            pm = QPixmap(str(out))
            self._pixmap = pm
            self._show_pixmap()
            for old in [*folder.glob("frame-*.png"), *folder.glob("text-[0-9]*.png")]:
                if old != out:
                    try:
                        old.unlink()
                    except OSError:
                        pass

        w = Worker(job, self)
        w.done.connect(done)
        w.start()

    _pixmap: QPixmap | None = None

    def _show_pixmap(self):
        if self._pixmap and not self._pixmap.isNull():
            self.preview.setPixmap(self._pixmap.scaled(self.preview.size() * 0.96,
                                                       Qt.AspectRatioMode.KeepAspectRatio,
                                                       Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._show_pixmap()

    # ----------------------------------------------------------- export

    def export(self):
        if self.worker:
            self.worker.cancel()
            return
        spec = self.spec()
        if spec.text.strip() and self.text_color.get() == "auto":
            spec = dataclasses.replace(spec, text_color=self.auto_colors[0], outline_color=self.auto_colors[1])
        name = f"{self.media.path.stem} (edited)"
        folder = self.media.path.parent
        text_png = edit.text_layer(spec, self.media, Path(self.tmp.name))

        def job(progress, cancelled):
            return edit.export(self.ffmpeg, self.media, spec, folder, name, progress, cancelled, text_png)

        self.worker = Worker(job, self)
        self.worker.progress.connect(lambda f, text: (self.progress.setValue(int(f * 1000)),
                                                      self.status.setText(f"{text} {f * 100:.0f}%")))
        self.worker.done.connect(self.exported)
        self.worker.failed.connect(self.export_failed)
        self.worker.cancelled.connect(lambda: self.export_failed("Export stopped."))
        self.progress.setValue(0)
        self.progress.show()
        self.open_button.hide()
        self.ok_button.setText("Stop")
        self.status.setText("Exporting…")
        self.worker.start()

    def exported(self, path: Path):
        self.worker = None
        self.result = path
        self.progress.hide()
        self.ok_button.setText("Export")
        self.status.setText(f"Saved {path.name}")
        self.open_button.show()

    def export_failed(self, message: str):
        self.worker = None
        self.progress.hide()
        self.ok_button.setText("Export")
        self.status.setText(message)

    def show_result(self):
        if self.result and self.result.exists():
            subprocess.Popen(["explorer", "/select,", str(self.result)])

    def done(self, r):
        if self.worker:
            self.worker.cancel()
        self.tmp.cleanup()
        super().done(r)


def open_editor(ffmpeg: str, path: Path, aspect: str = "original") -> None:
    Editor(ffmpeg, path, aspect).run()


if __name__ == "__main__":  # python -m clipnest.editor <file>
    import sys

    from PySide6.QtWidgets import QApplication

    from clipnest.util import find_ffmpeg

    app = QApplication(sys.argv)
    open_editor(find_ffmpeg(), Path(sys.argv[1]))
    os._exit(0)
