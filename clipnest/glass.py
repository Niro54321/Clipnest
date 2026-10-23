"""Frosted glass: the screen behind a window, blurred, the way CSS
backdrop-filter does on the web.

Windows can't blur behind a round or per-pixel transparent window, and a
screen capture always includes windows on top (our own too). So Clipnest
snapshots the monitor just before a window opens. The snapshot is frosted once
and kept in memory only; a window then paints the part of it that lies behind
its current position.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

from PIL import Image, ImageEnhance, ImageFilter, ImageStat
from PySide6.QtCore import QRectF
from PySide6.QtGui import QImage

BLUR = 16          # px, like backdrop-filter: blur(16px)
SATURATE = 1.25    # like backdrop-filter: saturate(1.25)
SHRINK = 3         # keep the frosted copy at a third of the size: blurred, it looks the same

user32 = ctypes.WinDLL("user32")
gdi32 = ctypes.WinDLL("gdi32")


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD),
                ("biCompression", wintypes.DWORD), ("biSizeImage", wintypes.DWORD),
                ("biXPelsPerMeter", wintypes.LONG), ("biYPelsPerMeter", wintypes.LONG),
                ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]


for _f, _args, _res in [
    (user32.GetDC, [wintypes.HWND], wintypes.HDC),
    (user32.ReleaseDC, [wintypes.HWND, wintypes.HDC], ctypes.c_int),
    (user32.MonitorFromPoint, [wintypes.POINT, wintypes.DWORD], wintypes.HMONITOR),
    (user32.MonitorFromWindow, [wintypes.HWND, wintypes.DWORD], wintypes.HMONITOR),
    (user32.GetMonitorInfoW, [wintypes.HMONITOR, ctypes.POINTER(MONITORINFO)], wintypes.BOOL),
    (user32.GetWindowRect, [wintypes.HWND, ctypes.POINTER(wintypes.RECT)], wintypes.BOOL),
    (gdi32.CreateCompatibleDC, [wintypes.HDC], wintypes.HDC),
    (gdi32.CreateCompatibleBitmap, [wintypes.HDC, ctypes.c_int, ctypes.c_int], wintypes.HBITMAP),
    (gdi32.SelectObject, [wintypes.HDC, wintypes.HGDIOBJ], wintypes.HGDIOBJ),
    (gdi32.BitBlt, [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                    wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.DWORD], wintypes.BOOL),
    (gdi32.GetDIBits, [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT, ctypes.c_void_p,
                       ctypes.c_void_p, wintypes.UINT], ctypes.c_int),
    (gdi32.DeleteObject, [wintypes.HGDIOBJ], wintypes.BOOL),
    (gdi32.DeleteDC, [wintypes.HDC], wintypes.BOOL),
]:
    _f.argtypes, _f.restype = _args, _res

MONITOR_DEFAULTTONEAREST = 2
SRCCOPY = 0x00CC0020


def _monitor_rect(hmon) -> tuple[int, int, int, int]:
    info = MONITORINFO()
    info.cbSize = ctypes.sizeof(MONITORINFO)
    user32.GetMonitorInfoW(hmon, ctypes.byref(info))
    r = info.rcMonitor
    return r.left, r.top, r.right - r.left, r.bottom - r.top


def window_rect(widget) -> tuple[int, int, int, int]:
    """A window's rectangle on the desktop in physical pixels."""
    r = wintypes.RECT()
    user32.GetWindowRect(int(widget.winId()), ctypes.byref(r))
    return r.left, r.top, r.right - r.left, r.bottom - r.top


def _grab(left: int, top: int, width: int, height: int) -> QImage | None:
    screen = user32.GetDC(None)
    mem = gdi32.CreateCompatibleDC(screen)
    bmp = gdi32.CreateCompatibleBitmap(screen, width, height)
    try:
        old = gdi32.SelectObject(mem, bmp)
        ok = gdi32.BitBlt(mem, 0, 0, width, height, screen, left, top, SRCCOPY)
        gdi32.SelectObject(mem, old)
        if not ok:
            return None
        header = BITMAPINFOHEADER()
        header.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        header.biWidth, header.biHeight = width, -height  # negative: top-down rows
        header.biPlanes, header.biBitCount = 1, 32
        buf = ctypes.create_string_buffer(width * height * 4)
        if not gdi32.GetDIBits(mem, bmp, 0, height, buf, ctypes.byref(header), 0):
            return None
        return QImage(buf.raw, width, height, width * 4, QImage.Format.Format_RGB32).copy()
    finally:
        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(mem)
        user32.ReleaseDC(None, screen)


class Snapshot:
    """One monitor as it looked at a moment, not frosted yet (cheap to take)."""

    def __init__(self, image: QImage, rect: tuple[int, int, int, int]):
        self.image = image
        self.rect = rect

    def crop(self, rect, margin: int = 48) -> "Snapshot | None":
        """The part around a physical rectangle (with room for the blur at the edges)."""
        left, top, w, h = rect
        ml, mt, mw, mh = self.rect
        x0, y0 = max(ml, left - margin), max(mt, top - margin)
        x1, y1 = min(ml + mw, left + w + margin), min(mt + mh, top + h + margin)
        if x1 <= x0 or y1 <= y0:
            return None
        return Snapshot(self.image.copy(x0 - ml, y0 - mt, x1 - x0, y1 - y0), (x0, y0, x1 - x0, y1 - y0))


def snapshot_at(x: int, y: int) -> Snapshot | None:
    """The monitor under a physical screen point."""
    rect = _monitor_rect(user32.MonitorFromPoint(wintypes.POINT(x, y), MONITOR_DEFAULTTONEAREST))
    image = _grab(*rect)
    return Snapshot(image, rect) if image is not None else None


def snapshot_for(widget) -> Snapshot | None:
    """The monitor a window is on (take it while the window is hidden)."""
    rect = _monitor_rect(user32.MonitorFromWindow(int(widget.winId()), MONITOR_DEFAULTTONEAREST))
    image = _grab(*rect)
    return Snapshot(image, rect) if image is not None else None


class Backdrop:
    """A frosted monitor snapshot. Windows paint the part behind them."""

    def __init__(self, snap: Snapshot):
        rgba = snap.image.convertToFormat(QImage.Format.Format_RGBA8888)
        w, h = rgba.width(), rgba.height()
        pil = Image.frombuffer("RGBA", (w, h), bytes(rgba.constBits()), "raw", "RGBA",
                               rgba.bytesPerLine(), 1).convert("RGB")
        small = pil.reduce(SHRINK)
        small = small.filter(ImageFilter.GaussianBlur(max(1.0, BLUR / SHRINK)))
        self.pil = ImageEnhance.Color(small).enhance(SATURATE)
        sw, sh = self.pil.size
        self.image = QImage(self.pil.convert("RGBA").tobytes(), sw, sh, sw * 4,
                            QImage.Format.Format_RGBA8888).copy()
        self.rect = snap.rect
        self.k = sw / w

    def source(self, rect) -> QRectF | None:
        """Where a physical desktop rectangle lies in the frosted image."""
        left, top, w, h = rect
        ml, mt, mw, mh = self.rect
        if left + w <= ml or top + h <= mt or left >= ml + mw or top >= mt + mh:
            return None
        return QRectF((left - ml) * self.k, (top - mt) * self.k, w * self.k, h * self.k)

    def brightness(self, rect) -> float:
        src = self.source(rect)
        if src is None:
            return 0.0
        box = (max(0, int(src.left())), max(0, int(src.top())),
               min(self.pil.width, int(src.right()) + 1), min(self.pil.height, int(src.bottom()) + 1))
        if box[2] <= box[0] or box[3] <= box[1]:
            return 0.0
        return ImageStat.Stat(self.pil.crop(box).convert("L")).mean[0] / 255
