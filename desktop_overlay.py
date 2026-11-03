"""Transparent, vector-rendered desktop battery display; no hardware polling."""
from pathlib import Path
from PySide6.QtCore import Qt,QRectF,QPoint,Signal
from PySide6.QtGui import QColor,QPainter,QPainterPath,QIcon
from PySide6.QtWidgets import QWidget,QMenu,QApplication
from icons import font,GLYPHS
from catalog import visible_devices,brand_info
import windows

SIZES={'small':(26,252,132,11),'medium':(34,300,164,13),'large':(44,360,202,16)}

class DesktopOverlay(QWidget):
    preferencesChanged=Signal()
    def __init__(self,preferences):
        super().__init__(None,Qt.WindowType.Tool|Qt.WindowType.FramelessWindowHint|Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowTitle('设备电量 · 桌面显示');self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.preferences=preferences;self.devices=[];self.all_devices=[];self.offset=0;self.logos={};self.drag_offset=None
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

    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing)
        detailed=self.preferences.get('desktop_mode')=='detailed';pixels=SIZES[self.preferences.get('desktop_size','medium')][3]
        p.setPen(Qt.PenStyle.NoPen)
        if not self.devices:
            p.setBrush(QColor(32,32,32,180));p.drawRoundedRect(QRectF(3,3,self.width()-6,self.height()-6),8,8)
            p.setFont(font(pixels));p.setPen(QColor('white'));p.drawText(self.rect(),Qt.AlignmentFlag.AlignCenter,'暂无已接入设备');return
        for i,d in enumerate(self.devices):
            y=6+i*self.row_height;h=self.row_height-6;x=6
            if detailed:
                # Each logo has its own readable neutral plate, outside the bar.
                side=h;p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor(250,250,250,225));p.drawRoundedRect(QRectF(x,y,side,side),5,5)
                if d.brand not in self.logos:
                    info=brand_info(d.brand);path=Path(__file__).parent/info['logo'] if info and info.get('logo') else None
                    self.logos[d.brand]=QIcon(str(path)) if path and path.is_file() else QIcon()
                icon=self.logos[d.brand]
                if icon.isNull():
                    p.setPen(QColor('#343434'));p.setFont(font(max(9,pixels-2)));p.drawText(QRectF(x,y,side,side),Qt.AlignmentFlag.AlignCenter,'?')
                else:icon.paint(p,int(x+3),int(y+3),int(side-6),int(side-6))
                x+=side+5
                p.setBrush(QColor(32,32,32,190));p.setPen(Qt.PenStyle.NoPen);p.drawRoundedRect(QRectF(x,y,side,side),5,5)
                p.setPen(QColor('white'));p.setFont(font(pixels,icons=True));p.drawText(QRectF(x,y,side,side),Qt.AlignmentFlag.AlignCenter,GLYPHS.get(d.kind,GLYPHS['mouse']))
                x+=side+5
            bar=QRectF(x,y,self.width()-x-6,h);p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor(32,32,32,190));p.drawRoundedRect(bar,6,6)
            value=d.display_percent
            if d.power_mode=='wired':text='有线';value=None
            elif value is not None:text=('约' if d.approximate else '')+str(value)+'%'+('?' if d.experimental else ' · 上次' if d.cached else ' ⚡' if d.charging else '')
            elif d.display_grade:
                text=d.display_grade+(' · 上次' if d.cached else ' · 分档');value={'耗尽':0,'低':20,'中':50,'高':75,'满':100}[d.display_grade]
            else:text='电量未知' if detailed else '—'
            fill=QRectF(bar);fill.setWidth(bar.width()*(value or 0)/100)
            p.save();path=QPainterPath();path.addRoundedRect(bar,6,6);p.setClipPath(path)
            p.fillRect(fill,QColor('#c42b1c' if value is not None and value<=20 else '#008463' if d.charging else windows.accent()))
            p.restore();p.setPen(QColor('white'));p.setFont(font(pixels))
            if not detailed:
                p.setFont(font(pixels,icons=True));p.drawText(QRectF(bar.x()+5,y,h,h),Qt.AlignmentFlag.AlignCenter,GLYPHS.get(d.kind,GLYPHS['mouse']))
                p.setFont(font(pixels));text_rect=bar.adjusted(h+8,0,-3,0)
            else:text_rect=bar
            p.drawText(text_rect,Qt.AlignmentFlag.AlignCenter,text)

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
