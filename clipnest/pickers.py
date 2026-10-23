"""Colour choosing, after Spinvert: round swatches with a (+) for any colour,
and a glass colour picker (hue bar, shade square, hex)."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QAbstractButton, QButtonGroup, QHBoxLayout, QLabel, QLineEdit, QPushButton, QWidget

from clipnest.widgets import GlassDialog

ACCENT = QColor("#7C5CFF")


class Dot(QAbstractButton):
    """A round swatch: a colour circle inside a ring, or a (+)."""

    def __init__(self, color: str | None = None, size: int = 26, plus: bool = False):
        super().__init__()
        self.color = QColor(color or "white")
        self.plus = plus
        self.setCheckable(not plus)
        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Any colour you like" if plus else self.color.name().upper())

    def sizeHint(self):
        return QSize(self.width(), self.height())

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
        c = r.center()
        if self.isChecked():
            p.setPen(QPen(ACCENT, 2.6))
        else:
            p.setPen(QPen(QColor(255, 255, 255, 120 if self.underMouse() else 70), 1.2))
        if self.plus:
            grad = QLinearGradient(r.topLeft(), r.bottomRight())
            for i, hue in enumerate((0.0, 0.17, 0.33, 0.5, 0.67, 0.83)):
                grad.setColorAt(i / 5, QColor.fromHsvF(hue, 0.75, 1))
            p.setBrush(grad)
            p.drawEllipse(r)
            p.setPen(QPen(QColor("white"), 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            arm = r.width() * 0.22
            p.drawLine(QPointF(c.x() - arm, c.y()), QPointF(c.x() + arm, c.y()))
            p.drawLine(QPointF(c.x(), c.y() - arm), QPointF(c.x(), c.y() + arm))
            return
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(r)
        p.setPen(QPen(QColor(0, 0, 0, 50), 0.8))
        p.setBrush(self.color)
        p.drawEllipse(r.adjusted(3.5, 3.5, -3.5, -3.5))


class Swatches(QWidget):
    """'Auto', a few colours, and (+) to pick any colour and shade. changed emits
    'auto' or a hex colour; a picked colour joins the row as its own swatch."""

    changed = Signal(str)

    def __init__(self, colors: list[str], current: str = "auto"):
        super().__init__()
        self.row = QHBoxLayout(self)
        self.row.setContentsMargins(0, 0, 0, 0)
        self.row.setSpacing(7)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons: dict[str, QAbstractButton] = {}
        auto = QPushButton("Auto")
        auto.setCheckable(True)
        auto.setProperty("segment", True)
        auto.setToolTip("Black or white, whichever reads on the video behind the text")
        self._add("auto", auto)
        for c in colors:
            self._add(c.upper(), Dot(c))
        self.plus = Dot(plus=True)
        self.plus.clicked.connect(self._custom)
        self.row.addWidget(self.plus)
        self.row.addStretch()
        self.set(current)

    def _add(self, key: str, button: QAbstractButton):
        button.clicked.connect(lambda _=False, k=key: self.changed.emit(k))
        self.group.addButton(button)
        self.buttons[key] = button
        self.row.insertWidget(len(self.buttons) - 1, button)

    def _custom(self):
        start = self.get() if self.get() != "auto" else "#7C5CFF"
        color = pick_color(start)
        if not color:
            return
        if color not in self.buttons:
            if len(self.buttons) > 9:   # keep the row short: the oldest picked colour makes room
                oldest = list(self.buttons)[7]
                b = self.buttons.pop(oldest)
                self.group.removeButton(b)
                b.setParent(None)
            self._add(color, Dot(color))
        self.set(color)
        self.changed.emit(color)

    def get(self) -> str:
        return next((k for k, b in self.buttons.items() if b.isChecked()), "auto")

    def set(self, key: str):
        key = key if key == "auto" else key.upper()
        if key in self.buttons:
            self.buttons[key].setChecked(True)


class _HueBar(QWidget):
    changed = Signal(float)

    def __init__(self):
        super().__init__()
        self.hue = 0.0
        self.setFixedHeight(22)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(2, 4, -2, -4)
        grad = QLinearGradient(r.topLeft(), r.topRight())
        for i in range(7):
            grad.setColorAt(i / 6, QColor.fromHsvF((i / 6) % 1.0, 1, 1))
        path = QPainterPath()
        path.addRoundedRect(r, 7, 7)
        p.fillPath(path, grad)
        x = r.left() + self.hue * r.width()
        p.setPen(QPen(QColor("white"), 2.5))
        p.setBrush(QColor.fromHsvF(self.hue, 1, 1))
        p.drawEllipse(QPointF(x, r.center().y()), 8, 8)

    def _set(self, x):
        r = QRectF(self.rect()).adjusted(2, 4, -2, -4)
        self.hue = min(0.999, max(0.0, (x - r.left()) / r.width()))
        self.update()
        self.changed.emit(self.hue)

    def mousePressEvent(self, e):
        self._set(e.position().x())

    def mouseMoveEvent(self, e):
        self._set(e.position().x())


class _ShadeSquare(QWidget):
    """Saturation left to right, brightness bottom to top, for the current hue."""

    changed = Signal(float, float)

    def __init__(self):
        super().__init__()
        self.hue, self.sat, self.val = 0.0, 1.0, 1.0
        self.setMinimumSize(300, 200)
        self.setCursor(Qt.CursorShape.CrossCursor)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        path = QPainterPath()
        path.addRoundedRect(r, 12, 12)
        p.setClipPath(path)
        p.fillRect(r, QColor.fromHsvF(self.hue, 1, 1))
        white = QLinearGradient(r.topLeft(), r.topRight())
        white.setColorAt(0, QColor(255, 255, 255, 255))
        white.setColorAt(1, QColor(255, 255, 255, 0))
        p.fillRect(r, white)
        black = QLinearGradient(r.topLeft(), r.bottomLeft())
        black.setColorAt(0, QColor(0, 0, 0, 0))
        black.setColorAt(1, QColor(0, 0, 0, 255))
        p.fillRect(r, black)
        p.setClipping(False)
        pt = QPointF(r.left() + self.sat * r.width(), r.top() + (1 - self.val) * r.height())
        p.setPen(QPen(QColor("white"), 2.5))
        p.setBrush(QColor.fromHsvF(self.hue, self.sat, self.val))
        p.drawEllipse(pt, 9, 9)

    def _set(self, pos):
        r = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        self.sat = min(1.0, max(0.0, (pos.x() - r.left()) / r.width()))
        self.val = min(1.0, max(0.0, 1 - (pos.y() - r.top()) / r.height()))
        self.update()
        self.changed.emit(self.sat, self.val)

    def mousePressEvent(self, e):
        self._set(e.position())

    def mouseMoveEvent(self, e):
        self._set(e.position())


class ColorDialog(GlassDialog):
    def __init__(self, start: str = "#7C5CFF"):
        super().__init__("Choose a colour", (460, 540), (420, 480), primary="Use colour")
        self.cancel_button.setText("Cancel")
        self.ok_button.clicked.connect(self.accept)
        self.ok_button.setDefault(True)
        color = QColor(start)
        self.square = _ShadeSquare()
        self.hue = _HueBar()
        h, s, v, _ = color.getHsvF()
        self.square.hue = self.hue.hue = max(0.0, h)
        self.square.sat, self.square.val = s, v
        self.hex = QLineEdit(color.name().upper())
        self.hex.setMaxLength(7)
        self.hex.setMaximumWidth(110)
        self.sample = Dot(color.name(), 34)
        self.sample.setCheckable(False)
        self.hue.changed.connect(self._hue)
        self.square.changed.connect(lambda *_: self._sync())
        self.hex.editingFinished.connect(self._typed)
        self.body.addWidget(QLabel("Shade"))
        self.body.addWidget(self.square, 1)
        self.body.addWidget(QLabel("Colour"))
        self.body.addWidget(self.hue)
        row = QHBoxLayout()
        row.addWidget(self.sample)
        row.addWidget(QLabel("Hex"))
        row.addWidget(self.hex)
        row.addStretch()
        self.body.addLayout(row)
        self.frame.style_children()

    def _hue(self, h):
        self.square.hue = h
        self.square.update()
        self._sync()

    def _sync(self):
        c = QColor.fromHsvF(self.square.hue, self.square.sat, self.square.val)
        self.hex.setText(c.name().upper())
        self.sample.color = c
        self.sample.update()

    def _typed(self):
        text = self.hex.text().strip()
        c = QColor(text if text.startswith("#") else "#" + text)
        if c.isValid():
            h, s, v, _ = c.getHsvF()
            self.square.hue = self.hue.hue = max(0.0, h)
            self.square.sat, self.square.val = s, v
            self.square.update()
            self.hue.update()
            self.sample.color = c
            self.sample.update()

    def color(self) -> str:
        return QColor.fromHsvF(self.square.hue, self.square.sat, self.square.val).name().upper()


def pick_color(start: str = "#7C5CFF") -> str | None:
    d = ColorDialog(start)
    return d.color() if d.run() else None
