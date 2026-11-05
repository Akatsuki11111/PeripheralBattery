"""Transparent, vector-rendered desktop battery display; no hardware polling."""
from pathlib import Path
from PySide6.QtCore import Qt,QRectF,QPoint,Signal
from PySide6.QtGui import QColor,QPainter,QIcon,QFont
from PySide6.QtWidgets import QWidget,QMenu,QApplication
from icons import font,device_outline
from appearance import CARD_RADIUS,panel_dark,palette,paint_meter
from catalog import visible_devices,brand_info

SIZES = {'small': (32, 252, 148, 12), 'medium': (41, 300, 180, 14), 'large': (50, 360, 218, 16)}

class DesktopOverlay(QWidget):
    preferencesChanged=Signal()
    def __init__(self,preferences):
        super().__init__(None,Qt.WindowType.Tool|Qt.WindowType.FramelessWindowHint|Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowTitle('设备电量 · 桌面显示');self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.preferences=preferences;self.devices=[];self.all_devices=[];self.offset=0;self.logos={};self.outlines={};self.drag_offset=None
        self.setMouseTracking(True);self.restore_position()

    def restore_position(self):
        screen=QApplication.primaryScreen().availableGeometry();pos=self.preferences.get('desktop_position',[])
        self.move(QPoint(*pos) if len(pos)==2 else QPoint(screen.right()-330,screen.top()+70))

    def sync(self,devices):
        self.all_devices=visible_devices(devices,self.preferences)
        mode=self.preferences.get('desktop_mode','off');size=self.preferences.get('desktop_size','medium')
        height,detailed,compact,_=SIZES[size];self.row_height=height
        bounds=(QApplication.screenAt(self.geometry().center()) or QApplication.primaryScreen()).availableGeometry()
        capacity=max(1,(bounds.height()-24)//height);self.offset=min(self.offset,max(0,len(self.all_devices)-capacity))
        self.devices=self.all_devices[self.offset:self.offset+capacity]
        self.resize(detailed if mode=='detailed' else compact,max(1,len(self.devices))*height+12)
        bounds=(QApplication.screenAt(self.geometry().center()) or QApplication.primaryScreen()).availableGeometry()
        self.move(max(bounds.left(),min(self.x(),bounds.right()-self.width()+1)),max(bounds.top(),min(self.y(),bounds.bottom()-self.height()+1)))
        self.setVisible(mode!='off');self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        theme = palette(panel_dark(self.preferences))
        detailed = self.preferences.get('desktop_mode') == 'detailed'
        pixels = SIZES[self.preferences.get('desktop_size', 'medium')][3]
        if not self.devices:
            rect = QRectF(self.rect()).adjusted(4, 4, -4, -4)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(theme.card))
            painter.drawRoundedRect(rect, CARD_RADIUS, CARD_RADIUS)
            painter.setFont(font(pixels, QFont.Weight.DemiBold))
            painter.setPen(QColor(theme.muted))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, '暂无已接入设备')
            return

        for index, device in enumerate(self.devices):
            row = QRectF(4, 6 + index * self.row_height, self.width() - 8, self.row_height - 6)
            radius = min(CARD_RADIUS, row.height() / 2)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(theme.card))
            painter.drawRoundedRect(row, radius, radius)

            meter = row.adjusted(4, 3, -4, -3)
            icon_size = int(meter.height()) - 4
            if detailed:
                self.paint_brand(painter, device.brand, int(meter.x()), int(meter.y()) + 2, icon_size)
                self.paint_kind(painter, device.kind, int(meter.x()) + icon_size + 6,
                                int(meter.y()) + 2, icon_size, theme.text)
                meter.setLeft(meter.left() + 2 * icon_size + 12)

            paint_meter(painter, meter, theme, device.display_percent, device.display_grade,
                        device.cached or device.experimental, inset_text=True)
            text_rect = meter.adjusted(6, 0, -8, -2)
            if not detailed:
                self.paint_kind(painter, device.kind, int(meter.x()) + 4,
                                int(meter.y()) + 1, icon_size, theme.text)
                text_rect.setLeft(meter.left() + icon_size + 8)
            value = '电量未知' if detailed and device.reading_text == '—' else device.reading_text
            painter.setFont(font(pixels, QFont.Weight.Bold))
            painter.setPen(QColor(theme.muted if device.cached or device.reading_text == '—' else theme.text))
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, value)

            marker = ''
            if device.cached:
                marker = '上次 ' + device.last_read_time if detailed else '上次'
            elif device.experimental:
                marker = '待核实' if detailed else ''
            elif device.charging and (device.usable or device.fresh_grade):
                marker = '充电中' if detailed else '充电'
            elif device.display_grade:
                marker = '分档'
            if marker:
                value_width = painter.fontMetrics().horizontalAdvance(value)
                marker_rect = text_rect.adjusted(0, 0, -value_width - 7, 0)
                painter.setFont(font(max(10, pixels - 2), QFont.Weight.Medium))
                painter.setPen(QColor(theme.muted))
                visible_marker = painter.fontMetrics().elidedText(
                    marker, Qt.TextElideMode.ElideRight, max(0, int(marker_rect.width())))
                painter.drawText(marker_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                                 visible_marker)

    def paint_kind(self, painter, kind, x, y, size, color):
        dpr = self.devicePixelRatioF()
        key = (kind, size, color, dpr)
        if key not in self.outlines:
            self.outlines[key] = device_outline(kind, size, color, dpr)
        painter.drawPixmap(x, y, self.outlines[key])

    def paint_brand(self, painter, brand, x, y, size):
        if brand not in self.logos:
            info = brand_info(brand)
            logo = Path(__file__).parent / info['logo'] if info and info.get('logo') else None
            self.logos[brand] = QIcon(str(logo)) if logo and logo.is_file() else QIcon()
        icon = self.logos[brand]
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor('#f5f6f8'))
        rect = QRectF(x, y, size, size)
        painter.drawRoundedRect(rect, 5, 5)
        if icon.isNull():
            painter.setPen(QColor('#526477'))
            painter.setFont(font(max(10, size // 2), QFont.Weight.DemiBold))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, '?')
        else:
            icon.paint(painter, x + 2, y + 2, size - 4, size - 4)

    def mousePressEvent(self,e):
        if e.button()==Qt.MouseButton.LeftButton and not self.preferences.get('desktop_locked',False):
            self.drag_offset=e.globalPosition().toPoint()-self.pos();e.accept()

    def mouseMoveEvent(self,e):
        if self.drag_offset is not None and e.buttons() & Qt.MouseButton.LeftButton:self.move(e.globalPosition().toPoint()-self.drag_offset)
        if self.devices:
            index=max(0,min(len(self.devices)-1,int((e.position().y()-6)//self.row_height)));d=self.devices[index]
            self.setToolTip(d.name+' · '+d.reading_text+'\n'+d.status+('\n上次有效读数：'+d.last_read_time if d.cached else '')+'\n拖动移动 · 右键设置')

    def mouseReleaseEvent(self,e):
        if self.drag_offset is not None:
            self.drag_offset=None;self.preferences.set('desktop_position',[self.x(),self.y()])

    def contextMenuEvent(self,e):
        menu=QMenu(self);add_desktop_actions(menu,self.preferences,self.changed)
        lock=menu.addAction('锁定位置');lock.setCheckable(True);lock.setChecked(self.preferences.get('desktop_locked',False))
        lock.triggered.connect(lambda on:self.changed('desktop_locked',on))
        try:menu.exec(e.globalPos())
        finally:menu.deleteLater()

    def changed(self,key,value):
        self.preferences.set(key,value);self.sync(self.all_devices);self.preferencesChanged.emit()

    def wheelEvent(self,event):
        self.offset=max(0,self.offset+(-1 if event.angleDelta().y()>0 else 1));self.sync(self.all_devices);event.accept()

    def closeEvent(self,event):
        self.preferences.set('desktop_mode','off');self.preferencesChanged.emit();event.accept()

def add_desktop_actions(menu,preferences,callback):
    from PySide6.QtGui import QActionGroup
    modes=QActionGroup(menu);modes.setExclusive(True)
    for text,value in (('详细显示','detailed'),('简略显示','compact'),('关闭桌面显示','off')):
        action=menu.addAction(text);action.setCheckable(True);modes.addAction(action)
        action.setChecked(preferences.get('desktop_mode','off')==value)
        action.triggered.connect(lambda checked,v=value:callback('desktop_mode',v))
    sizes=menu.addMenu('显示大小');group=QActionGroup(sizes);group.setExclusive(True)
    for text,value in (('大','large'),('中','medium'),('小','small')):
        action=sizes.addAction(text);action.setCheckable(True);group.addAction(action)
        action.setChecked(preferences.get('desktop_size','medium')==value)
        action.triggered.connect(lambda checked,v=value:callback('desktop_size',v))
