"""Colours and the app icon, drawn in code (no image files to ship)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from io import BytesIO

from PySide6.QtCore import QBuffer, QIODevice, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPainterPathStroker, QPen, QPixmap

ACCENT = {"convert": QColor("#7C5CFF"), "tools": QColor("#06B6D4")}
MARK = [QColor("#7C5CFF"), QColor("#06B6D4"), QColor("#F472B6"), QColor("#34D399")]


def ring_segment(center: QPointF, r_in: float, r_out: float, start: float, sweep: float) -> QPainterPath:
    """Annular sector. Angles in degrees, Qt style (counter-clockwise from 3 o'clock)."""
    outer = QRectF(center.x() - r_out, center.y() - r_out, 2 * r_out, 2 * r_out)
    inner = QRectF(center.x() - r_in, center.y() - r_in, 2 * r_in, 2 * r_in)
    path = QPainterPath()
    path.arcMoveTo(outer, start)
    path.arcTo(outer, start, sweep)
    path.arcTo(inner, start + sweep, -sweep)
    path.closeSubpath()
    return path


def pill_segment(center: QPointF, r_in: float, r_out: float, center_angle: float, span: float,
                 gap: float, rounding: float) -> QPainterPath:
    """A wheel segment with an even gap to its neighbours and rounded corners."""
    g = gap + 2 * rounding
    ri, ro = r_in + rounding, r_out - rounding

    def half(r):
        return math.degrees(math.asin(min(0.99, g / (2 * r))))

    so, eo = center_angle - span / 2 + half(ro), center_angle + span / 2 - half(ro)
    si, ei = center_angle - span / 2 + half(ri), center_angle + span / 2 - half(ri)
    outer = QRectF(center.x() - ro, center.y() - ro, 2 * ro, 2 * ro)
    inner = QRectF(center.x() - ri, center.y() - ri, 2 * ri, 2 * ri)
    path = QPainterPath()
    path.arcMoveTo(outer, so)
    path.arcTo(outer, so, eo - so)
    path.arcTo(inner, ei, si - ei)
    path.closeSubpath()
    if rounding:
        stroker = QPainterPathStroker()
        stroker.setWidth(2 * rounding)
        stroker.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        path = path.united(stroker.createStroke(path)).simplified()
    return path


def annulus(center: QPointF, r_in: float, r_out: float) -> QPainterPath:
    outer = QPainterPath()
    outer.addEllipse(center, r_out, r_out)
    inner = QPainterPath()
    inner.addEllipse(center, r_in, r_in)
    return outer.subtracted(inner)


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
    """The Clipnest mark: a four-part ring around a dot."""
    c = rect.center()
    r = min(rect.width(), rect.height()) / 2
    p.setPen(Qt.PenStyle.NoPen)
    for i, color in enumerate(MARK):
        p.setBrush(color)
        p.drawPath(ring_segment(c, r * 0.52, r * 0.98, 90 - i * 90 - 84, 78))
    p.setBrush(QColor("#F4F4F8"))
    p.drawEllipse(c, r * 0.26, r * 0.26)


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
    """Write the icon as .ico for the Send to shortcut."""
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
