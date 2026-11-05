"""Shared surfaces and battery colours for the panel, desktop and tray."""
from typing import NamedTuple

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainterPath
import windows


class Palette(NamedTuple):
    background: str
    card: str
    text: str
    muted: str
    border: str
    hover: str
    tile: str
    track: str
    accent: str
    good: str
    amber: str
    low: str
    history: str


LIGHT = Palette('#f3f3f3', '#fafafa', '#1a1a1a', '#575c63', '#dddddd',
                '#ffffff', '#eceff3', '#e0e4e9', '#005fba',
                '#19804d', '#986200', '#c4323d', '#65758a')
DARK = Palette('#20262e', '#2a323d', '#f3f6fa', '#aebdd0', '#3d4858',
               '#323d4a', '#364457', '#48576a', '#8bc6ff',
               '#54d694', '#f1bd62', '#ff828b', '#a2b2c7')
CARD_RADIUS = 14


def palette(dark):
    return DARK if dark else LIGHT


def panel_dark(preferences):
    mode = preferences.get('theme', 'system')
    return windows.is_dark() if mode == 'system' else mode == 'dark'


def battery_color(theme, percent=None, grade='', stale=False):
    if stale or (percent is None and not grade):
        return theme.history
    if grade in ('耗尽', '低') or (percent is not None and percent <= 20):
        return theme.low
    if grade == '中' or (percent is not None and percent < 50):
        return theme.amber
    return theme.good


def paint_meter(painter, rect, theme, percent=None, grade='', stale=False, inset_text=False):
    """Paint a numeric fill or four discrete grade segments."""
    color = QColor(battery_color(theme, percent, grade, stale))
    track = QColor(theme.track)
    if percent == 0 or grade == '耗尽':
        # A confirmed empty battery has a visible red rail; unknown stays neutral.
        track = QColor(theme.low if not stale else theme.history)
        track.setAlpha(105)

    radius = min(rect.height() / 2, 10)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(track if not inset_text else QColor(theme.tile))
    painter.drawRoundedRect(rect, radius, radius)

    if percent is None and not grade:
        return

    painter.save()
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    painter.setClipPath(path, Qt.ClipOperation.IntersectClip)

    if grade and percent is None:
        count = {'耗尽': 0, '低': 1, '中': 2, '高': 3, '满': 4}[grade]
        gap = min(2, rect.width() / 16)
        width = (rect.width() - gap * 3) / 4
        segments = [QRectF(rect.x() + i * (width + gap), rect.y(), width, rect.height())
                    for i in range(count)]
    elif percent > 0:
        width = max(1, rect.width() * percent / 100)
        segments = [QRectF(rect.x(), rect.y(), width, rect.height())]
    else:
        segments = []

    for segment in segments:
        if inset_text:
            tint = QColor(color)
            tint.setAlpha(50)
            painter.fillRect(segment, tint)
            segment.setTop(segment.bottom() - 3)
        painter.fillRect(segment, color)

    if inset_text and not segments:
        painter.fillRect(QRectF(rect.left(), rect.bottom() - 3, rect.width(), 3), track)
    painter.restore()
