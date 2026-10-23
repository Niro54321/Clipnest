"""Liquid-glass windows: a frameless card over a frosted snapshot of the screen
behind it, and a style sheet that makes the controls on it match.

Used by the main window and the editor.
"""

from __future__ import annotations

from PIL import Image, ImageDraw, ImageFilter
from PySide6.QtCore import QObject, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QImage, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QCheckBox, QGraphicsDropShadowEffect, QLabel, QPushButton

from clipnest import glass
from clipnest.theme import ON_BRIGHT, ON_DARK, draw_mark, soft_text, thin_pen
from clipnest.util import app_data_dir

MARGIN = 26      # room around the card for its shadow
RADIUS = 26
HEADER = 52


def _icons() -> dict[str, str]:
    """Small images the style sheet needs (check mark, drop-down arrows), drawn once."""
    folder = app_data_dir() / "ui-1"
    folder.mkdir(exist_ok=True)
    paths = {}
    for name, color, points in [
            ("check", "#FFFFFF", [(8, 17), (14, 23), (25, 10)]),
            ("arrow-light", "#FFFFFF", [(9, 13), (16, 20), (23, 13)]),
            ("arrow-dark", "#17171F", [(9, 13), (16, 20), (23, 13)])]:
        path = folder / f"{name}.png"
        if not path.exists():
            img = QImage(32, 32, QImage.Format.Format_ARGB32_Premultiplied)
            img.fill(Qt.GlobalColor.transparent)
            p = QPainter(img)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setPen(QPen(QColor(color), 3.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                          Qt.PenJoinStyle.RoundJoin))
            p.drawPolyline([QPointF(x, y) for x, y in points])
            p.end()
            img.save(str(path))
        paths[name] = path.as_posix()
    return paths


def style_sheet(look) -> str:
    """Glass controls: see-through fills, light edges, a solid primary button."""
    icons = _icons()
    dark = look is ON_DARK
    fg = "white" if dark else "#17171F"
    fill = "rgba(255,255,255,0.13)" if dark else "rgba(255,255,255,0.58)"
    hover = "rgba(255,255,255,0.24)" if dark else "rgba(255,255,255,0.85)"
    edge = "rgba(255,255,255,0.38)" if dark else "rgba(0,0,0,0.14)"
    primary_bg, primary_fg = ("white", "#16161D") if dark else ("#16161D", "white")
    groove = "rgba(255,255,255,0.22)" if dark else "rgba(0,0,0,0.12)"
    track = "rgba(255,255,255,0.85)" if dark else "rgba(22,22,30,0.75)"
    arrow = icons["arrow-light" if dark else "arrow-dark"]
    card = "rgba(16,16,24,0.40)" if dark else "rgba(255,255,255,0.42)"
    card_edge = "rgba(255,255,255,0.18)" if dark else "rgba(0,0,0,0.08)"
    return f"""
        QLabel, QCheckBox {{ color: {fg}; background: transparent; font-size: 13px; }}
        QPushButton {{ color: {fg}; background: {fill}; border: 1px solid {edge};
                       border-radius: 15px; padding: 6px 18px; font-weight: 600; }}
        QPushButton:hover {{ background: {hover}; }}
        QPushButton[primary="true"] {{ color: {primary_fg}; background: {primary_bg};
                                       border: 1px solid {primary_bg}; }}
        QPushButton[round="true"] {{ padding: 0; }}
        QLineEdit, QComboBox {{ color: {fg}; background: {fill}; border: 1px solid {edge};
                                border-radius: 12px; padding: 5px 10px; min-height: 20px;
                                selection-background-color: #7C5CFF; selection-color: white; }}
        QLineEdit:hover, QComboBox:hover {{ background: {hover}; }}
        QComboBox::drop-down {{ border: none; width: 28px; }}
        QComboBox::down-arrow {{ image: url({arrow}); width: 12px; height: 12px; }}
        QComboBox QAbstractItemView {{ color: white; background: #262634; outline: none;
                                       border: 1px solid rgba(255,255,255,0.2); padding: 4px;
                                       selection-background-color: #7C5CFF; }}
        QCheckBox {{ spacing: 10px; }}
        QCheckBox::indicator {{ width: 18px; height: 18px; border-radius: 6px;
                                border: 1px solid {edge}; background: {fill}; }}
        QCheckBox::indicator:checked {{ background: #7C5CFF; border-color: #7C5CFF;
                                        image: url({icons["check"]}); }}
        QSlider::groove:horizontal {{ height: 6px; border-radius: 3px; background: {groove}; }}
        QSlider::sub-page:horizontal {{ height: 6px; border-radius: 3px; background: {track}; }}
        QSlider::handle:horizontal {{ width: 18px; height: 18px; margin: -6px 0; border-radius: 9px;
                                      background: white; border: 1px solid rgba(0,0,0,0.2); }}
        QProgressBar {{ color: {fg}; background: {fill}; border: 1px solid {edge}; border-radius: 9px; height: 18px; text-align: center; font-size: 11px; }}
        QProgressBar::chunk {{ background: #7C5CFF; border-radius: 8px; }}
        QToolTip {{ color: white; background: #262634; border: 1px solid rgba(255,255,255,0.2); }}
        QPushButton[segment="true"] {{ padding: 5px 13px; border-radius: 13px; font-weight: 600; }}
        QPushButton[segment="true"]:checked {{ color: {primary_fg}; background: {primary_bg};
                                               border: 1px solid {primary_bg}; }}
        QPushButton[player="true"] {{ background: transparent; border: none; padding: 0;
                                      border-radius: 20px; }}
        QPushButton[player="true"]:hover {{ background: {hover}; }}
        QPushButton[player="true"]:pressed {{ background: {fill}; }}
        QPushButton[swatch="true"] {{ padding: 0; border-radius: 13px; border: 2px solid {edge}; }}
        QPushButton[swatch="true"]:checked {{ border: 3px solid #7C5CFF; }}
        QWidget[card="true"] {{ background: {card}; border: 1px solid {card_edge}; border-radius: 16px; }}
        QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
        QListWidget, QTableWidget {{ color: {fg}; background: {fill}; border: 1px solid {edge};
                                     border-radius: 12px; padding: 4px; outline: none; }}
        QListWidget::item:selected, QTableWidget::item:selected {{ background: rgba(124,92,255,0.55);
                                                                   color: white; border-radius: 6px; }}
        QHeaderView::section {{ color: {fg}; background: transparent; border: none; font-weight: 700;
                                padding: 4px; }}
        QTableWidget {{ gridline-color: transparent; }}
        QSpinBox, QDoubleSpinBox {{ color: {fg}; background: {fill}; border: 1px solid {edge};
                                    border-radius: 12px; padding: 4px 8px; min-height: 20px; }}
        QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button,
        QDoubleSpinBox::down-button {{ width: 0; border: none; }}
        QScrollBar:vertical {{ width: 8px; background: transparent; margin: 2px; }}
        QScrollBar::handle:vertical {{ background: {groove}; border-radius: 4px; min-height: 30px; }}
        QScrollBar:horizontal {{ height: 8px; background: transparent; margin: 2px; }}
        QScrollBar::handle:horizontal {{ background: {groove}; border-radius: 4px; min-width: 30px; }}
        QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
    """


def _shadow_image(width: int, height: int) -> QImage:
    """A soft drop shadow for the card, like box-shadow: 0 16px 40px rgba(0,0,0,.28)."""
    mask = Image.new("L", (width, height), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (MARGIN, MARGIN + 10, width - MARGIN, height - MARGIN + 6), RADIUS, fill=72)
    mask = mask.filter(ImageFilter.GaussianBlur(14))
    rgba = Image.merge("RGBA", (Image.new("L", mask.size, 0),) * 3 + (mask,))
    return QImage(rgba.tobytes(), width, height, width * 4, QImage.Format.Format_RGBA8888).copy()


class GlassFrame(QObject):
    """Makes a frameless window a glass card. The window forwards its paint,
    move, resize and mouse-press events here."""

    look_changed = Signal(object)

    def __init__(self, widget, title: str):
        super().__init__(widget)
        self.widget = widget
        self.title = title
        self.backdrop = None
        self.look = ON_DARK
        self._shadow = None
        widget.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._settle = QTimer(self)
        self._settle.setSingleShot(True)
        self._settle.setInterval(60)
        self._settle.timeout.connect(self.update_look)

    def card(self) -> QRectF:
        return QRectF(self.widget.rect()).adjusted(MARGIN, MARGIN - 6, -MARGIN, -MARGIN - 6)

    def refresh_backdrop(self) -> None:
        """Snapshot the monitor behind the window. Call while it is hidden."""
        try:
            snap = glass.snapshot_for(self.widget)
            self.backdrop = glass.Backdrop(snap) if snap else None
        except Exception:
            self.backdrop = None
        self.update_look(force=True)

    def update_look(self, force: bool = False) -> None:
        look = ON_DARK
        if self.backdrop is not None and self.backdrop.brightness(glass.window_rect(self.widget)) > 0.6:
            look = ON_BRIGHT
        if force or look is not self.look:
            self.look = look
            self.style_children()
            self.look_changed.emit(look)
        self.widget.update()

    def style_children(self) -> None:
        """Glass style sheet, and a soft shadow under the text of labels and check boxes."""
        self.widget.setStyleSheet(style_sheet(self.look))
        for child in [*self.widget.findChildren(QLabel), *self.widget.findChildren(QCheckBox)]:
            effect = QGraphicsDropShadowEffect(child)
            effect.setBlurRadius(8)
            effect.setOffset(0, 1)
            effect.setColor(self.look.text_shadow)
            child.setGraphicsEffect(effect)

    def close_button(self, slot) -> QPushButton:
        button = QPushButton("✕")
        button.setFixedSize(30, 30)
        button.setProperty("round", True)
        button.clicked.connect(slot)
        return button

    # events the window forwards

    def moved(self) -> None:
        self.widget.update()
        self._settle.start()

    def resized(self) -> None:
        self._shadow = None

    def press(self, event) -> bool:
        """Drag the window by its header."""
        if event.button() == Qt.MouseButton.LeftButton and event.position().y() < MARGIN + HEADER:
            self.widget.windowHandle().startSystemMove()
            return True
        return False

    def paint(self, p: QPainter) -> None:
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        look = self.look
        if self._shadow is None:
            self._shadow = _shadow_image(self.widget.width(), self.widget.height())
        p.drawImage(0, 0, self._shadow)

        card = self.card()
        shape = QPainterPath()
        shape.addRoundedRect(card, RADIUS, RADIUS)
        p.save()
        p.setClipPath(shape)
        src = self.backdrop.source(glass.window_rect(self.widget)) if self.backdrop else None
        if src is not None:
            p.drawImage(QRectF(self.widget.rect()), self.backdrop.image, src)
        else:
            p.fillPath(shape, QColor(30, 30, 42, 230))
        p.fillPath(shape, look.tint)
        sheen = QLinearGradient(card.topLeft(), card.center())
        sheen.setColorAt(0.0, QColor(255, 255, 255, look.sheen))
        sheen.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.fillPath(shape, sheen)
        p.restore()
        # border, and the bright inset line along the top edge
        rim = QLinearGradient(card.topLeft(), card.bottomLeft())
        rim.setColorAt(0.0, QColor(255, 255, 255, look.rim_top))
        rim.setColorAt(1.0, QColor(255, 255, 255, look.rim_bottom))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(rim, 1.2))
        p.drawRoundedRect(card.adjusted(0.6, 0.6, -0.6, -0.6), RADIUS, RADIUS)
        p.setPen(thin_pen(look.outline, 1))
        p.drawRoundedRect(card.adjusted(-0.5, -0.5, 0.5, 0.5), RADIUS, RADIUS)

        draw_mark(p, QRectF(card.left() + 18, card.top() + 15, 24, 24))
        font = QFont(self.widget.font())
        font.setPixelSize(16)
        font.setWeight(QFont.Weight.Bold)
        p.setFont(font)
        soft_text(p, QRectF(card.left() + 50, card.top() + 12, card.width() - 110, 30), self.title,
                  look.text, look.text_shadow, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
