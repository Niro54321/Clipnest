"""Player icons drawn in code, in the style of YouTube's controls: a rounded play
triangle, two pause bars, and circular arrows with a 10 for skipping."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPainterPathStroker, QPen, QPixmap

CANVAS = 96


def _rounded(path: QPainterPath, radius: float) -> QPainterPath:
    stroker = QPainterPathStroker()
    stroker.setWidth(radius * 2)
    stroker.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return path.united(stroker.createStroke(path)).simplified()


def _play(p: QPainter, color: QColor):
    tri = QPainterPath()
    tri.moveTo(32, 22)
    tri.lineTo(74, 48)
    tri.lineTo(32, 74)
    tri.closeSubpath()
    p.fillPath(_rounded(tri, 4), color)


def _pause(p: QPainter, color: QColor):
    for x in (26, 56):
        bar = QPainterPath()
        bar.addRoundedRect(QRectF(x, 22, 14, 52), 3, 3)
        p.fillPath(bar, color)


def _skip(p: QPainter, color: QColor, forward: bool):
    """A circle of arrow with the gap at the top and a 10 inside, like Material's replay_10."""
    c, r = QPointF(48, 52), 30
    box = QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r)
    pen = QPen(color, 7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    arc = QPainterPath()
    start, sweep = (90, 290) if forward else (90, -290)
    arc.arcMoveTo(box, start)
    arc.arcTo(box, start, sweep)
    p.drawPath(arc)
    # arrowhead at the top, pointing the way it turns
    top = QPointF(c.x(), c.y() - r)
    d = 1 if forward else -1
    head = QPainterPath()
    head.moveTo(top.x() + d * 15, top.y())
    head.lineTo(top.x() - d * 2, top.y() - 12)
    head.lineTo(top.x() - d * 2, top.y() + 12)
    head.closeSubpath()
    p.setPen(Qt.PenStyle.NoPen)
    p.fillPath(_rounded(head, 2), color)
    font = QFont("Segoe UI")
    font.setPixelSize(27)
    font.setWeight(QFont.Weight.Black)
    p.setFont(font)
    p.setPen(color)
    p.drawText(QRectF(c.x() - r, c.y() - r + 3, 2 * r, 2 * r), Qt.AlignmentFlag.AlignCenter, "10")


def icon(name: str, color: QColor, size: int = 48) -> QIcon:
    """play, pause, back10 or forward10, in one colour."""
    result = QIcon()
    for scale in (1, 2):
        pm = QPixmap(size * scale, size * scale)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        p.scale(size * scale / CANVAS, size * scale / CANVAS)
        # a faint shadow first, so the icon reads on any glass
        shadow = QColor(0, 0, 0, 70) if color.lightnessF() > 0.5 else QColor(255, 255, 255, 90)
        for col, dy in ((shadow, 2.0), (color, 0.0)):
            p.save()
            p.translate(0, dy)
            {"play": lambda: _play(p, col), "pause": lambda: _pause(p, col),
             "back10": lambda: _skip(p, col, False), "forward10": lambda: _skip(p, col, True)}[name]()
            p.restore()
        p.end()
        pm.setDevicePixelRatio(scale)
        result.addPixmap(pm)
    return result
