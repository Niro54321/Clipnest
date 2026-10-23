"""Playback in the editor: the file plays with sound (Qt Multimedia), and each
frame is drawn with the edits on it (crop or blurred fit, text, logo), so you
see the result while it plays. Paused, the editor shows FFmpeg's exact frame."""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_FFMPEG_DEBUG", "0")

from PySide6.QtCore import QObject, QRectF, Qt, QUrl, Signal  # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter  # noqa: E402

from clipnest import edit  # noqa: E402


class Player(QObject):
    """A file playing with sound. Emits each video frame and the position (s)."""

    frame = Signal(QImage)
    position = Signal(float)
    playing = Signal(bool)

    def __init__(self, path: Path, video: bool = True, parent=None):
        super().__init__(parent)
        from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer, QVideoSink

        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.audio.setVolume(1.0)
        self.player.setAudioOutput(self.audio)
        if video:
            self.sink = QVideoSink(self)
            self.sink.videoFrameChanged.connect(self._frame)
            self.player.setVideoSink(self.sink)
        self.player.positionChanged.connect(lambda ms: self._moved(ms / 1000))
        self.player.playbackStateChanged.connect(
            lambda s: self.playing.emit(s == QMediaPlayer.PlaybackState.PlayingState))
        self.player.setSource(QUrl.fromLocalFile(str(path)))
        self.stop_at: float | None = None  # pause here (the end of the trim)

    def _frame(self, frame):
        if frame.isValid() and self.is_playing:
            image = frame.toImage()
            if not image.isNull():
                self.frame.emit(image)

    def _moved(self, seconds: float):
        if self.stop_at is not None and seconds >= self.stop_at:
            self.stop_at = None
            self.player.pause()
        self.position.emit(seconds)

    @property
    def is_playing(self) -> bool:
        from PySide6.QtMultimedia import QMediaPlayer

        return self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState

    def play(self, start: float, stop_at: float | None):
        self.seek(start)
        self.stop_at = stop_at
        self.player.play()

    def pause(self):
        self.player.pause()

    def seek(self, seconds: float):
        self.player.setPosition(int(max(0.0, seconds) * 1000))

    def close(self):
        self.player.stop()
        self.player.setSource(QUrl())


def compose(frame: QImage, spec: edit.EditSpec, media: edit.Media, text: QImage | None,
            logo: QImage | None, width: int, height: int) -> QImage:
    """One playing frame with the edits drawn on, fitted into width x height.
    A quick likeness of what FFmpeg will export, good enough to watch."""
    W, H = edit.out_size(spec, media)
    k = min(width / W, height / H)
    w, h = max(2, int(W * k)), max(2, int(H * k))
    out = QImage(w, h, QImage.Format.Format_RGB32)
    out.fill(QColor("black"))
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    fw, fh = frame.width(), frame.height()
    target = QRectF(0, 0, w, h)
    if spec.aspect == "original":
        p.drawImage(target, frame)
    else:
        cover = max(w / fw, h / fh)
        cw, ch = w / cover, h / cover
        if spec.fit == "blur":
            # a soft copy behind: shrink a lot, then scale back up smoothly
            bg = frame.copy(int((fw - cw) / 2), int((fh - ch) / 2), int(cw), int(ch))
            bg = bg.scaled(max(1, w // 28), max(1, h // 28), Qt.AspectRatioMode.IgnoreAspectRatio,
                           Qt.TransformationMode.SmoothTransformation)
            p.drawImage(target, bg)
            p.fillRect(target, QColor(0, 0, 0, 30))
            fit = min(w / fw, h / fh)
            fg = QRectF((w - fw * fit) / 2, (h - fh * fit) / 2, fw * fit, fh * fit)
            p.drawImage(fg, frame)
        else:
            fx, fy = min(1, max(0, spec.focus_x)), min(1, max(0, spec.focus_y))
            p.drawImage(target, frame, QRectF((fw - cw) * fx, (fh - ch) * fy, cw, ch))
    if text is not None:
        p.drawImage(target, text)
    if logo is not None and not logo.isNull():
        lw = w * spec.logo_size / 100
        lh = lw * logo.height() / max(1, logo.width())
        m = w * 0.03
        x = {"top-left": m, "bottom-left": m, "center": (w - lw) / 2}.get(spec.logo_pos, w - lw - m)
        y = {"top-left": m, "top-right": m, "center": (h - lh) / 2}.get(spec.logo_pos, h - lh - m)
        p.setOpacity(spec.logo_opacity)
        p.drawImage(QRectF(x, y, lw, lh), logo)
        p.setOpacity(1.0)
    p.end()
    return out
