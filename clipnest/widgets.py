"""Glass windows and the small controls on them, after Spinvert's editors:
a frameless window you resize by its edges, pill toggles, slider rows,
round colour swatches, and a worker that runs a job off the UI thread."""

from __future__ import annotations

import threading
import traceback

from PySide6.QtCore import QEvent, QObject, QPointF, QSize, Qt, Signal
from PySide6.QtGui import QCursor, QGuiApplication, QPainter
from PySide6.QtWidgets import (QButtonGroup, QDialog, QHBoxLayout, QLabel, QPushButton, QSlider,
                               QVBoxLayout, QWidget)

from clipnest.download import Cancelled
from clipnest.glassui import HEADER, MARGIN, GlassFrame
from clipnest.theme import app_icon

EDGE = 9  # px either side of the card's border that resize the window


class GlassMixin:
    """Paint, move, resize and drag handling shared by the glass window and dialog."""

    frame: GlassFrame

    def setup_glass(self, title: str, size, minimum):
        self.setWindowTitle(title)
        self.setWindowIcon(app_icon())
        self.setMouseTracking(True)
        self.least = QSize(*minimum)
        self.setMinimumSize(self.least)
        screen = (QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()).availableGeometry()
        self.resize(min(size[0], int(screen.width() * 0.96)), min(size[1], int(screen.height() * 0.94)))
        self.frame = GlassFrame(self, title)
        root = QVBoxLayout(self)
        root.setContentsMargins(MARGIN + 18, MARGIN + 10, MARGIN + 18, MARGIN + 16)
        root.setSpacing(10)
        self.top_bar = QHBoxLayout()
        self.top_bar.addStretch()
        root.addLayout(self.top_bar)
        self.body = QVBoxLayout()
        self.body.setSpacing(10)
        root.addLayout(self.body, 1)
        return root

    def center_on_screen(self):
        self.winId()
        screen = (QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()).availableGeometry()
        self.move(screen.center().x() - self.width() // 2, screen.center().y() - self.height() // 2)
        self.frame.refresh_backdrop()

    def paintEvent(self, event):
        p = QPainter(self)
        self.frame.paint(p)
        p.end()

    def moveEvent(self, event):
        self.frame.moved()

    def resizeEvent(self, event):
        self.frame.resized()
        self.frame.moved()

    def _edges(self, pos: QPointF):
        if self.isMaximized():
            return None
        card = self.frame.card()
        x, y = pos.x(), pos.y()
        if not card.adjusted(-EDGE, -EDGE, EDGE, EDGE).contains(pos):
            return None
        edges = Qt.Edge(0)
        if abs(x - card.left()) <= EDGE:
            edges |= Qt.Edge.LeftEdge
        elif abs(x - card.right()) <= EDGE:
            edges |= Qt.Edge.RightEdge
        if abs(y - card.top()) <= EDGE:
            edges |= Qt.Edge.TopEdge
        elif abs(y - card.bottom()) <= EDGE:
            edges |= Qt.Edge.BottomEdge
        return edges if edges != Qt.Edge(0) else None

    def mouseMoveEvent(self, event):
        edges = self._edges(event.position())
        if edges is None:
            self.unsetCursor()
            return
        horizontal = bool(edges & (Qt.Edge.LeftEdge | Qt.Edge.RightEdge))
        vertical = bool(edges & (Qt.Edge.TopEdge | Qt.Edge.BottomEdge))
        if horizontal and vertical:
            forward = edges in (Qt.Edge.LeftEdge | Qt.Edge.TopEdge, Qt.Edge.RightEdge | Qt.Edge.BottomEdge)
            self.setCursor(Qt.CursorShape.SizeFDiagCursor if forward else Qt.CursorShape.SizeBDiagCursor)
        else:
            self.setCursor(Qt.CursorShape.SizeHorCursor if horizontal else Qt.CursorShape.SizeVerCursor)

    def mousePressEvent(self, event):
        edges = self._edges(event.position())
        if edges is not None and event.button() == Qt.MouseButton.LeftButton:
            self.windowHandle().startSystemResize(edges)
            return
        self.frame.press(event)

    def mouseDoubleClickEvent(self, event):
        if event.position().y() < MARGIN + HEADER:
            self.showNormal() if self.isMaximized() else self.showMaximized()


class GlassWindow(GlassMixin, QWidget):
    def __init__(self, title: str, size=(620, 700), minimum=(520, 560)):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setup_glass(title, size, minimum)
        minimize = self.frame.close_button(self.showMinimized)
        minimize.setText("–")
        minimize.setToolTip("Minimise")
        self.top_bar.addWidget(minimize)
        self.top_bar.addWidget(self.frame.close_button(self.close))

    def changeEvent(self, event):
        # back from the taskbar: the desktop behind may have changed, so frost it again
        if event.type() == QEvent.Type.WindowStateChange and not self.isMinimized() \
                and event.oldState() & Qt.WindowState.WindowMinimized:
            self.hide()
            self.frame.refresh_backdrop()
            self.show()
        super().changeEvent(event)


class GlassDialog(GlassMixin, QDialog):
    def __init__(self, title: str, size=(1000, 700), minimum=(820, 560), primary: str = "Export"):
        super().__init__(None, Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        root = self.setup_glass(title, size, minimum)
        self.top_bar.addWidget(self.frame.close_button(self.reject))
        self.footer = QHBoxLayout()
        self.footer.setSpacing(8)
        self.footer_left = QHBoxLayout()
        self.footer.addLayout(self.footer_left, 1)
        self.cancel_button = QPushButton("Close")
        self.cancel_button.clicked.connect(self.reject)
        self.ok_button = QPushButton(primary)
        self.ok_button.setProperty("primary", True)
        self.footer.addWidget(self.cancel_button)
        self.footer.addWidget(self.ok_button)
        root.addLayout(self.footer)

    def run(self) -> int:
        self.center_on_screen()
        return self.exec()


def label(text: str = "", muted: bool = False, bold: bool = False, size: int = 13) -> QLabel:
    w = QLabel(text)
    w.setWordWrap(True)
    style = f"font-size: {size}px;"
    if bold:
        style += " font-weight: 700;"
    if muted:
        style += " opacity: 0.8;"
    w.setStyleSheet(style)
    return w


class Segmented(QWidget):
    """A row of pill buttons, one checked at a time."""

    changed = Signal(str)

    def __init__(self, options, current=None):
        super().__init__()
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons: dict[str, QPushButton] = {}
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        for key, text in options:
            b = QPushButton(text.replace("&", "&&"))
            b.setCheckable(True)
            b.setProperty("segment", True)
            b.clicked.connect(lambda _=False, k=key: self.changed.emit(k))
            self.group.addButton(b)
            self.buttons[key] = b
            row.addWidget(b)
        row.addStretch()
        self.set(current)

    def get(self):
        return next((k for k, b in self.buttons.items() if b.isChecked()), None)

    def set(self, key):
        if key in self.buttons:
            self.buttons[key].setChecked(True)


class SliderRow(QWidget):
    """Name, slider and the value, on one line."""

    changed = Signal(float)

    def __init__(self, name: str, lo: float, hi: float, value: float, suffix: str = "", scale: int = 1):
        super().__init__()
        self.scale, self.suffix = scale, suffix
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        self.name = QLabel(name)
        self.name.setMinimumWidth(70)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(int(lo * scale), int(hi * scale))
        self.slider.setValue(int(value * scale))
        self.value = QLabel()
        self.value.setMinimumWidth(44)
        self.value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self.name)
        row.addWidget(self.slider, 1)
        row.addWidget(self.value)
        self.slider.valueChanged.connect(self._moved)
        self._moved(self.slider.value())

    def _moved(self, v):
        self.value.setText(f"{v / self.scale:g}{self.suffix}")
        self.changed.emit(v / self.scale)

    def get(self) -> float:
        return self.slider.value() / self.scale

    def set(self, v: float):
        self.slider.setValue(int(round(v * self.scale)))


class Swatches(QWidget):
    """Round colour buttons, one picked at a time. 'auto' lets the app choose."""

    changed = Signal(str)

    def __init__(self, colors: list[str], current: str, auto: bool = True):
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        self.group = QButtonGroup(self)
        self.buttons: dict[str, QPushButton] = {}
        if auto:
            b = QPushButton("Auto")
            b.setCheckable(True)
            b.setProperty("segment", True)
            b.setToolTip("Pick black or white from how bright the video is behind the text")
            self._add("auto", b, row)
        for c in colors:
            b = QPushButton()
            b.setCheckable(True)
            b.setFixedSize(26, 26)
            b.setProperty("swatch", True)
            b.setStyleSheet(f"QPushButton {{ background: {c}; }}")
            b.setToolTip(c)
            self._add(c, b, row)
        row.addStretch()
        self.set(current)

    def _add(self, key, b, row):
        b.clicked.connect(lambda _=False, k=key: self.changed.emit(k))
        self.group.addButton(b)
        self.buttons[key] = b
        row.addWidget(b)

    def get(self) -> str:
        return next((k for k, b in self.buttons.items() if b.isChecked()), "auto")

    def set(self, key):
        if key in self.buttons:
            self.buttons[key].setChecked(True)


class Worker(QObject):
    """Runs fn(progress, cancelled) on a thread; reports back on the UI thread."""

    progress = Signal(float, str)
    done = Signal(object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self.fn = fn
        self._stop = threading.Event()

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()
        return self

    def cancel(self):
        self._stop.set()

    def _run(self):
        try:
            result = self.fn(lambda f, text: self.progress.emit(f, text), self._stop.is_set)
        except Cancelled:
            self.cancelled.emit()
        except Exception as e:  # shown to the user, not raised
            if self._stop.is_set():
                self.cancelled.emit()
                return
            traceback.print_exc()
            self.failed.emit(friendly_error(e))
        else:
            self.done.emit(result)


def friendly_error(e: Exception) -> str:
    text = str(e).replace("ERROR: ", "").strip()
    low = text.lower()
    if "unsupported url" in low:
        return "This link isn't a video Clipnest can read."
    if "private" in low or "login" in low or "sign in" in low or "log in" in low:
        return "This video is private or needs an account, so it can't be downloaded."
    if "drm" in low:
        return "This video is DRM-protected and can't be downloaded."
    if "unable to download webpage" in low or "getaddrinfo" in low or "timed out" in low:
        return "Couldn't reach the site. Check your connection and try again."
    return text.splitlines()[0][:300] if text else e.__class__.__name__

