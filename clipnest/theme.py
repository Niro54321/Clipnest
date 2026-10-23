"""Colours and the app icon, drawn in code (no image files to ship)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from io import BytesIO

from PySide6.QtCore import QBuffer, QIODevice, QPointF, QRectF, Qt
from PySide6.QtGui import (QColor, QIcon, QLinearGradient, QPainter, QPainterPath, QPainterPathStroker,
                           QPen, QPixmap)

MARK_FROM, MARK_TO = QColor("#7C5CFF"), QColor("#F472B6")   # the button's gradient
STAR = QColor("#FFC93C")


def play_path(rect: QRectF) -> QPainterPath:
    """A play triangle with rounded corners, centred by its weight so it looks centred."""
    s = min(rect.width(), rect.height())
    c = rect.center()
    h = s * 0.50                      # triangle height (left edge)
    w = h * 0.93
    left = c.x() - w * 0.40
    tri = QPainterPath()
    tri.moveTo(left, c.y() - h / 2)
    tri.lineTo(left + w, c.y())
    tri.lineTo(left, c.y() + h / 2)
    tri.closeSubpath()
    stroker = QPainterPathStroker()
    stroker.setWidth(s * 0.09)
    stroker.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return tri.united(stroker.createStroke(tri)).simplified()


def star_path(center: QPointF, r: float) -> QPainterPath:
    """A four-pointed sparkle."""
    path = QPainterPath()
    inner = r * 0.30
    for i in range(8):
        a = math.radians(-90 + i * 45)
        k = r if i % 2 == 0 else inner
        pt = QPointF(center.x() + k * math.cos(a), center.y() + k * math.sin(a))
        path.moveTo(pt) if i == 0 else path.lineTo(pt)
    path.closeSubpath()
    return path


@dataclass(frozen=True)
class Glass:
    """Colours for frosted glass over a dark or a bright background."""
    tint: QColor
    sheen: int
    rim_top: int
    rim_bottom: int
    outline: QColor
    shadow: int
    segment: QColor
    segment_edge: QColor
    hover: QColor
    hover_text: QColor
    text: QColor
    text_shadow: QColor
    muted: QColor
    hub: QColor
    pill: QColor


ON_DARK = Glass(tint=QColor(22, 22, 30, 64), sheen=46, rim_top=120, rim_bottom=30,
                outline=QColor(0, 0, 0, 40), shadow=70,
                segment=QColor(255, 255, 255, 20), segment_edge=QColor(255, 255, 255, 60),
                hover=QColor(255, 255, 255, 238), hover_text=QColor("#16161D"),
                text=QColor(255, 255, 255, 248), text_shadow=QColor(0, 0, 0, 110),
                muted=QColor(255, 255, 255, 200), hub=QColor(255, 255, 255, 40),
                pill=QColor(255, 255, 255, 46))
ON_BRIGHT = Glass(tint=QColor(246, 246, 250, 96), sheen=70, rim_top=230, rim_bottom=90,
                  outline=QColor(0, 0, 0, 34), shadow=50,
                  segment=QColor(255, 255, 255, 92), segment_edge=QColor(0, 0, 0, 26),
                  hover=QColor(22, 22, 30, 225), hover_text=QColor(255, 255, 255),
                  text=QColor("#17171F"), text_shadow=QColor(255, 255, 255, 120),
                  muted=QColor(23, 23, 31, 170), hub=QColor(255, 255, 255, 120),
                  pill=QColor(0, 0, 0, 16))


def draw_mark(p: QPainter, rect: QRectF) -> None:
    """The Clipnest mark: a gradient play button with a white play sign and a star in its middle."""
    s = min(rect.width(), rect.height())
    box = QRectF(rect.center().x() - s / 2, rect.center().y() - s / 2, s, s).adjusted(
        s * 0.03, s * 0.03, -s * 0.03, -s * 0.03)
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    grad = QLinearGradient(box.topLeft(), box.bottomRight())
    grad.setColorAt(0.0, MARK_FROM)
    grad.setColorAt(1.0, MARK_TO)
    button = QPainterPath()
    button.addRoundedRect(box, box.width() * 0.28, box.height() * 0.28)
    p.fillPath(button, grad)
    shine = QLinearGradient(box.topLeft(), box.center())
    shine.setColorAt(0.0, QColor(255, 255, 255, 70))
    shine.setColorAt(1.0, QColor(255, 255, 255, 0))
    p.fillPath(button, shine)
    tri = play_path(box)
    p.fillPath(tri, QColor("white"))
    # the star sits on the play sign's centre of weight
    b = tri.boundingRect()
    center = QPointF(b.left() + b.width() * 0.38, b.center().y())
    p.fillPath(star_path(center, s * 0.13), STAR)
    p.restore()


def app_icon() -> QIcon:
    icon = QIcon()
    for size in (16, 20, 24, 32, 40, 48, 64, 128, 256):
        pm = QPixmap(size, size)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        draw_mark(p, QRectF(0, 0, size, size))
        p.end()
        icon.addPixmap(pm)
    return icon


def save_ico(path) -> None:
    """Write the icon as .ico (for a shortcut or an installer)."""
    from PIL import Image

    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    app_icon().pixmap(256, 256).save(buf, "PNG")
    Image.open(BytesIO(bytes(buf.data()))).save(
        path, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (256, 256)])


def soft_text(p: QPainter, rect: QRectF, text: str, color: QColor, shadow: QColor,
              flags=Qt.AlignmentFlag.AlignCenter) -> None:
    """Text with a soft shadow under it, so it reads on any glass."""
    if shadow.alpha():
        faint = QColor(shadow)
        faint.setAlpha(shadow.alpha() // 2)
        for (dx, dy), pen in (((0, 2), faint), ((1, 1), faint), ((-1, 1), faint), ((0, 1), shadow)):
            p.setPen(pen)
            p.drawText(rect.translated(dx, dy), flags, text)
    p.setPen(color)
    p.drawText(rect, flags, text)


def thin_pen(color: QColor, width: float = 1.0) -> QPen:
    pen = QPen(color)
    pen.setWidthF(width)
    return pen
