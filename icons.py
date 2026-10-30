"""Windows glyphs and vector battery/tray rendering at every DPI."""
from pathlib import Path
from math import floor
from PySide6.QtCore import Qt, QRectF, QSize, QPointF
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QWidget
import windows

ASSETS = Path(__file__).parent / 'assets'
GLYPHS = {'mouse':'\ue962', 'keyboard':'\ue765', 'headset':'\ue95b', 'gamepad':'\ue7fc', 'battery':'\ue83f',
          'refresh':'\ue72c', 'close':'\ue711', 'back':'\ue72b', 'settings':'\ue713',
          'chevron':'\ue76c', 'power':'\ue7e8', 'signal':'\ue701', 'info':'\ue946','auxiliary':'\ue946'}


def font(size, weight=QFont.Weight.Normal, icons=False):
    f = QFont('Segoe Fluent Icons' if icons else 'Segoe UI Variable Text')
    if not icons:f.setFamilies(['Segoe UI Variable Text','Segoe UI','Microsoft YaHei UI'])
    f.setPixelSize(size)
    f.setWeight(weight)
    return f


def glyph_icon(kind, color, size=32):
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(QColor(color))
    p.setFont(font(int(size*.67), icons=True))
    p.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, GLYPHS.get(kind, kind))
    p.end()
    return QIcon(pm)


def tray_number_font(text, size, area):
    """Choose a real font size that fits; never stretch or condense glyphs."""
    for pixels in range(max(1, round(size * .90)), 0, -1):
        number_font = QFont('Segoe UI')
        number_font.setPixelSize(pixels)
        number_font.setWeight(QFont.Weight.Bold)
        number_font.setHintingPreference(QFont.HintingPreference.PreferFullHinting)
        metrics = QFontMetricsF(number_font)
        # All one/two-digit readings share a size, so changing 11 to 88 doesn't
        # visibly resize the text. Only the three-digit 100 needs a smaller font.
        reference = '88' if text.isdigit() and len(text) <= 2 else text
        bounds = metrics.tightBoundingRect(reference)
        if bounds.width() <= area.width() and bounds.height() <= area.height():
            return number_font, metrics.tightBoundingRect(text)
    return number_font, bounds


def draw_tray_device(painter, kind, area, color, charging=False, dark=None):
    """Pixel-aligned, simplified Fluent-style outlines for a very small badge."""
    size = painter.device().width()
    stroke = max(1, round(size / 20))
    def align(value):
        return floor(value) + .5 if stroke % 2 else round(value)
    def point(x, y):
        return QPointF(align(x), align(y))
    top, bottom = align(area.top()), align(area.bottom())
    height = bottom - top
    center = area.center().x() - (size * .065 if charging else 0)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(QColor(color), stroke, Qt.PenStyle.SolidLine,
                        Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    if kind == 'mouse':
        width = max(3, round(height * .70))
        left = align(center - width / 2)
        painter.drawRoundedRect(QRectF(left, top, width, height), width / 2, width / 2)
        wheel_x = align(left + width / 2)
        painter.drawLine(point(wheel_x, top + stroke), point(wheel_x, top + height * .40))
    elif kind == 'headset':
        width = max(5, round(height * 1.3))
        left, right = align(center - width / 2), align(center + width / 2)
        path = QPainterPath()
        path.moveTo(left, bottom - height * .30)
        path.lineTo(left, top + height * .55)
        path.cubicTo(left, top - height * .18, right, top - height * .18, right, top + height * .55)
        path.lineTo(right, bottom - height * .30)
        painter.drawPath(path)
        painter.drawLine(point(left, bottom - height * .38), point(left, bottom))
        painter.drawLine(point(right, bottom - height * .38), point(right, bottom))
    elif kind == 'gamepad':
        width=max(7,round(height*1.9));left=align(center-width/2)
        painter.drawRoundedRect(QRectF(left,top,width,height),height*.38,height*.38)
        painter.drawLine(point(left+width*.23,top+height*.5),point(left+width*.43,top+height*.5))
        painter.drawLine(point(left+width*.33,top+height*.27),point(left+width*.33,top+height*.73))
        painter.drawPoint(point(left+width*.72,top+height*.35))
        painter.drawPoint(point(left+width*.82,top+height*.65))
    elif kind == 'keyboard':
        width = max(7, round(height * 1.9))
        left = align(center - width / 2)
        painter.drawRoundedRect(QRectF(left, top, width, height), stroke, stroke)
        # One readable key row and a space bar, rather than a blurred font glyph.
        for fraction in (.2, .4, .6, .8):
            painter.drawPoint(point(left + width * fraction, top + height * .40))
        painter.drawLine(point(left + width * .35, top + height * .73),
                         point(left + width * .65, top + height * .73))
    else:
        width = max(6, round(height * 1.65))
        left = align(center - width / 2)
        painter.drawRoundedRect(QRectF(left, top, width, height), stroke, stroke)
        painter.drawLine(point(left + width + stroke, top + height * .35),
                         point(left + width + stroke, top + height * .65))
    if charging:
        # Separate from the device outline and the numerical reading.
        bolt = QPainterPath()
        x = size * .86
        bolt.moveTo(x + size * .05, top)
        bolt.lineTo(x - size * .065, top + height * .57)
        bolt.lineTo(x, top + height * .57)
        bolt.lineTo(x - size * .035, bottom)
        bolt.lineTo(x + size * .085, top + height * .37)
        bolt.lineTo(x + size * .025, top + height * .37)
        bolt.closeSubpath()
        painter.setPen(Qt.PenStyle.NoPen)
        dark = windows.is_taskbar_dark() if dark is None else dark
        painter.setBrush(QColor('#60cdff' if dark else '#0067c0'))
        painter.drawPath(bolt)


def tray_pixmap(device, size, dark=None):
    """Normal-proportion number above a distinct device badge, at native DPI."""
    dark = windows.is_taskbar_dark() if dark is None else dark
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    foreground = '#ffffff' if dark else '#171717'
    value=device.display_percent if device else None
    color = ('#aaaaaa' if dark else '#777777') if device and device.cached else ('#ff8080' if dark else '#bc211b') if value is not None and value <= 10 else (
        '#ffd16a' if dark else '#945e00') if value is not None and value <= 20 else foreground
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
    # Full-width number, normal Segoe UI proportions. Integer font size/baseline
    # lets the font rasterizer hint strokes for 16/20/24px rather than resampling.
    number_height = round(size * .64)
    number_area = QRectF(0, 0, size, number_height)
    text = ('~' if device and device.approximate and device.usable else '')+str(value) if value is not None else '–'
    number_font, bounds = tray_number_font(text, size, number_area)
    painter.setFont(number_font)
    painter.setPen(QColor(color))
    x = round((size - bounds.width()) / 2 - bounds.left())
    baseline = round((number_height - bounds.height()) / 2 - bounds.top())
    painter.drawText(x, baseline, text)
    kind = device.kind if device else 'battery'
    gap = max(1, round(size * .04))
    badge = QRectF(0, number_height + gap, size, size - number_height - 2 * gap)
    draw_tray_device(painter, kind, badge, color, bool(device and device.usable and device.charging), dark)
    painter.end()
    return pm


def tray_icon(device=None):
    icon = QIcon()
    for size in (16, 20, 24, 28, 32, 36, 40, 48, 64, 128, 256):
        icon.addPixmap(tray_pixmap(device, size))
    return icon


class BrandIcon(QWidget):
    def __init__(self,brand,kind,parent=None):
        super().__init__(parent)
        self.setFixedSize(44,44)
        self.brand='';self.kind=kind;self.icon=QIcon();self.light_logo=False
        self.set_brand(brand,kind)

    def set_brand(self,brand,kind):
        if self.brand==brand and self.kind==kind:return
        from catalog import brand_info
        self.brand,self.kind=brand,kind
        info=brand_info(brand)
        self.wide=bool(info and info.get('wide'))
        path=Path(__file__).parent/info['logo'] if info and info.get('logo') else ASSETS/(brand.lower()+'.png')
        self.icon=QIcon(str(path)) if path.is_file() else QIcon()
        self.light_logo=False
        if not self.icon.isNull():
            image=self.icon.pixmap(48,48).toImage();values=[]
            for x in range(image.width()):
                for y in range(image.height()):
                    pixel=image.pixelColor(x,y)
                    if pixel.alpha()>100:values.append((pixel.red()+pixel.green()+pixel.blue())/3)
            self.light_logo=bool(values and sum(values)/len(values)>215)
        self.setToolTip((info['zh']+' · '+info['name']) if info else brand)
        self.update()

    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor('#343434' if self.light_logo else '#f8f8f8'))
        p.drawRoundedRect(QRectF(.5,.5,43,43),9,9)
        if self.icon.isNull():
            # A brand wordmark is preferable to assigning another company's logo.
            text=self.brand if self.brand!='Unknown' else '?'
            if len(text)>8 and ' ' in text:text=text.replace(' ','\n',1)
            p.setPen(QColor('#202020'));p.setFont(font(9 if len(self.brand)>8 else 10,QFont.Weight.DemiBold))
            p.drawText(QRectF(2,2,40,35),Qt.AlignmentFlag.AlignCenter,text)
            p.setPen(Qt.PenStyle.NoPen)
        else:
            self.icon.paint(p,4 if self.wide else 8,7,36 if self.wide else 28,28)
        color={'Razer':'#70b84d','SteelSeries':'#e99a59','Scyrox':'#b5c746'}.get(self.brand,windows.accent())
        p.setBrush(QColor(color));p.drawRoundedRect(QRectF(16,38,12,2),1,1)


class BatteryBar(QWidget):
    def __init__(self,parent=None):
        super().__init__(parent);self.value=None;self.charging=False;self.stale=False
        self.setFixedHeight(8)

    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor('#525252' if windows.is_dark() else '#d6d6d6'))
        p.drawRoundedRect(QRectF(0,2,self.width(),4),2,2)
        if self.value is not None:
            color='#858585' if self.stale else '#c42b1c' if self.value<=10 else '#b77900' if self.value<=20 else windows.accent()
            p.setBrush(QColor(color))
            p.drawRoundedRect(QRectF(0,2,max(2,self.width()*self.value/100),4),2,2)
