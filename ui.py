import datetime as dt
import time
from PySide6.QtCore import Qt, QTimer, Signal, QRectF, QEasingCurve, QPropertyAnimation, Property
from PySide6.QtGui import QColor,QPainter,QPen,QFont,QCursor
from PySide6.QtWidgets import (QWidget,QLabel,QPushButton,QToolButton,QVBoxLayout,QHBoxLayout,
    QFrame,QScrollArea,QStackedWidget,QAbstractButton,QSizePolicy,QApplication,QGridLayout,QComboBox)
from icons import font,glyph_icon,BrandIcon,BatteryBar,GLYPHS
from models import lowest
from catalog import visible_devices
from settings import Settings,REFRESH_INTERVALS
import startup
import windows


def label(text='',size=12,muted=False,bold=False):
    l=QLabel(text);l.setTextFormat(Qt.TextFormat.PlainText);l.setFont(font(size,QFont.Weight.DemiBold if bold else QFont.Weight.Normal))
    if muted:l.setObjectName('muted')
    return l


def tool(kind,tip,callback):
    b=QToolButton();b.setFixedSize(30,30);b.setToolTip(tip);b.setAccessibleName(tip)
    b.setProperty('glyphKind',kind)
    b.setIcon(glyph_icon(kind,'#efefef' if windows.is_dark() else '#343434',24))
    b.clicked.connect(callback);return b


class Toggle(QAbstractButton):
    """Vector switch; no bitmap resources, keyboard and screen reader enabled."""
    def __init__(self,checked,parent=None):
        super().__init__(parent);self.setCheckable(True);self.setChecked(checked)
        self.setFixedSize(48,30);self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName('开机自启');self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._pos=1.0 if checked else 0.0
        self.anim=QPropertyAnimation(self,b'position',self);self.anim.setDuration(130)
        self.anim.setEasingCurve(QEasingCurve.Type.OutCubic);self.toggled.connect(self.animate)

    def getPosition(self):return self._pos
    def setPosition(self,p):self._pos=p;self.update()
    position=Property(float,getPosition,setPosition)

    def animate(self,on):
        self.anim.stop();self.anim.setStartValue(self._pos);self.anim.setEndValue(1.0 if on else 0.0);self.anim.start()

    def set_checked_silent(self,on):
        self.anim.stop();previous=self.blockSignals(True)
        self.setChecked(bool(on));self.setPosition(float(on));self.blockSignals(previous)

    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing)
        dark=windows.is_dark()
        p.setPen(QPen(QColor(windows.accent() if self.isChecked() else '#969696'),1))
        p.setBrush(QColor(windows.accent() if self.isChecked() else '#292929' if dark else '#fafafa'))
        p.drawRoundedRect(QRectF(3.5,5.5,40,20),10,10)
        p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor('#151515' if self.isChecked() and dark else '#ffffff' if self.isChecked() else '#bcbcbc' if dark else '#606060'))
        p.drawEllipse(QRectF(7.5+20*self._pos,9.5,12,12))
        if self.hasFocus():
            p.setBrush(Qt.BrushStyle.NoBrush);p.setPen(QPen(QColor(windows.accent()),1,Qt.PenStyle.DotLine));p.drawRoundedRect(QRectF(1,2,45,26),12,12)


def display_name(device):
    name=device.name
    for prefix in ('SteelSeries ','Razer ','SCYROX '):
        if name.startswith(prefix):name=name[len(prefix):]
    return name.removesuffix(' RECEIVER')


class DeviceCard(QFrame):
    clicked=Signal(str)
    def __init__(self,d,compact=False):
        super().__init__();self.d=d;self.setObjectName('card');self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus);self.setAccessibleName(d.name+'，'+d.status+'，'+d.reading_text)
        self.setFixedHeight(70 if compact else 82)
        row=QHBoxLayout(self);row.setContentsMargins(12,8,10,8);row.setSpacing(12)
        self.brand_icon=BrandIcon(d.brand,d.kind);row.addWidget(self.brand_icon)
        center=QVBoxLayout();center.setSpacing(3);center.setContentsMargins(0,0,0,0)
        name=label(display_name(d),13,bold=True)
        name.setToolTip(d.name);name.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Preferred)
        self.name_label=name;center.addWidget(name)
        status=QHBoxLayout();status.setSpacing(5)
        kind=label(GLYPHS[d.kind],12,True);kind.setObjectName('glyph');kind.setFont(font(12,icons=True));status.addWidget(kind)
        type_name=d.type_name
        self.kind_label=kind;self.status_label=label(type_name+' · '+d.status,11,True)
        status.addWidget(self.status_label);status.addStretch();center.addLayout(status)
        bar=BatteryBar();bar.value=d.percent;bar.stale=d.stale or d.connected is not True;bar.charging=d.charging
        self.bar=bar;bar.setVisible(d.power_mode!='wired' and d.kind!='auxiliary');center.addWidget(bar);row.addLayout(center,1)
        pct=QVBoxLayout();pct.setSpacing(0)
        value=label(d.reading_text,20 if d.kind!='auxiliary' else 13,bold=True)
        if not d.usable:value.setObjectName('muted')
        value.setAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter);pct.addWidget(value)
        self.value_label=value;self.brand_label=label(d.brand if d.brand!='Unknown' else '品牌待指定',10,True);pct.addWidget(self.brand_label);row.addLayout(pct)
        arrow=label(GLYPHS['chevron'],11,True);arrow.setObjectName('glyph');arrow.setFont(font(11,icons=True));row.addWidget(arrow)

    def update_device(self,d):
        if self.d==d:return
        self.d=d;self.brand_icon.set_brand(d.brand,d.kind)
        self.name_label.setText(display_name(d));self.name_label.setToolTip(d.name)
        self.kind_label.setText(GLYPHS.get(d.kind,GLYPHS['mouse']))
        self.status_label.setText(d.type_name+' · '+d.status)
        self.status_label.setToolTip(d.note);self.value_label.setText(d.reading_text)
        tone='' if d.usable else 'muted'
        if self.value_label.objectName()!=tone:
            self.value_label.setObjectName(tone);self.value_label.style().unpolish(self.value_label);self.value_label.style().polish(self.value_label)
        self.brand_label.setText(d.brand if d.brand!='Unknown' else '品牌待指定')
        self.bar.value=d.percent;self.bar.stale=not d.usable;self.bar.charging=d.charging;self.bar.update()
        self.bar.setVisible(d.power_mode!='wired' and d.kind!='auxiliary')
        self.setAccessibleName(d.name+'，'+d.status+'，'+self.value_label.text())

    def mouseReleaseEvent(self,e):
        if e.button()==Qt.MouseButton.LeftButton:self.clicked.emit(self.d.key)

    def keyPressEvent(self,e):
        if e.key() in (Qt.Key.Key_Return,Qt.Key.Key_Space):self.clicked.emit(self.d.key)
        else:super().keyPressEvent(e)


class Flyout(QWidget):
    refreshRequested=Signal()
    preferencesChanged=Signal()
    forgetRequested=Signal(str)
    promoteTrayRequested=Signal()
    def __init__(self,preferences=None,history=None):
        super().__init__(None,Qt.WindowType.Tool|Qt.WindowType.FramelessWindowHint|Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowTitle('设备电量 · Peripheral Battery');self.setObjectName('flyout')
        self.devices=[];self.errors=[];self.selected=None;self.pinned=False;self.menu_open=False;self.theme=None
        self.preferences=preferences or Settings();self.cards={};self.anchor=None;self.detail_labels={};self.detail_key=None
        from history import HistoryStore
        self.history=history or HistoryStore(self.preferences.path.with_name('history.json'))
        self.catalog_dialog=None;self.research_dialog=None;self.research_controller=None
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground,True)
        self.root=QVBoxLayout(self);self.root.setContentsMargins(18,14,18,12);self.root.setSpacing(8)
        head=QHBoxLayout();head.setSpacing(10)
        self.back=tool('back','返回设备列表',self.go_back);self.back.hide();head.addWidget(self.back)
        titlecol=QVBoxLayout();titlecol.setSpacing(1);titlecol.addWidget(label('设备电量',18,bold=True));titlecol.addWidget(label('外设状态 · 有线 / 无线',11,True));head.addLayout(titlecol,1)
        self.refresh=tool('refresh','立即刷新',self.refreshRequested.emit);head.addWidget(self.refresh)
        head.addWidget(tool('info','品牌目录与设备管理',self.open_catalog));head.addWidget(tool('close','收起到系统托盘',self.hide))
        self.root.addLayout(head)
        self.summary=label('正在读取设备状态…',11,True);self.root.addWidget(self.summary)
        self.research_button=QPushButton('电量适配检查');self.research_button.setToolTip('逐步检查未知电量设备的已验证状态接口')
        self.research_button.clicked.connect(self.open_research);self.root.addWidget(self.research_button)
        self.stack=QStackedWidget();self.root.addWidget(self.stack,1)
        self.scroll=QScrollArea();self.scroll.setWidgetResizable(True);self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list_body=QWidget();self.list_body.setObjectName('transparent');self.list_layout=QVBoxLayout(self.list_body);self.list_layout.setContentsMargins(0,0,0,0);self.list_layout.setSpacing(6)
        self.scroll.setWidget(self.list_body);self.stack.addWidget(self.scroll)
        self.detail=QScrollArea();self.detail.setWidgetResizable(True);self.detail.setFrameShape(QFrame.Shape.NoFrame);self.stack.addWidget(self.detail)
        line=QFrame();line.setObjectName('separator');line.setFixedHeight(1);self.root.addWidget(line)
        foot=QHBoxLayout();foot.setSpacing(8)
        auto=label('开机自启',12);auto.setBuddy(None);foot.addWidget(auto);foot.addStretch()
        self.auto_state=label('已开启' if windows.startup_enabled() else '已关闭',11,True);foot.addWidget(self.auto_state)
        self.toggle=Toggle(False);self.toggle.toggled.connect(self.change_startup);foot.addWidget(self.toggle);self.root.addLayout(foot)
        status_row=QHBoxLayout();status_row.setSpacing(8)
        self.statusline=label('托盘显示最低电量',10,True);self.statusline.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Preferred)
        status_row.addWidget(self.statusline,1)
        self.refresh_choice=QComboBox();self.refresh_choice.setObjectName('refreshInterval');self.refresh_choice.setFixedSize(108,26)
        self.refresh_choice.setFont(font(11));self.refresh_choice.setAccessibleName('自动刷新间隔')
        for seconds in REFRESH_INTERVALS:self.refresh_choice.addItem(f'{seconds} 秒刷新',seconds)
        self.refresh_choice.setCurrentIndex(REFRESH_INTERVALS.index(self.preferences.get('refresh_seconds',15)))
        self.refresh_choice.setToolTip('切换后立即保存并生效。查询未结束时不会重复启动。')
        self.refresh_choice.currentIndexChanged.connect(lambda:self.change_interval(self.refresh_choice.currentData()))
        status_row.addWidget(self.refresh_choice);self.root.addLayout(status_row)
        self.apply_theme()
        self.refresh_startup()

    def apply_theme(self):
        dark=windows.is_dark();self.theme=dark
        for b in self.findChildren(QToolButton):
            kind=b.property('glyphKind')
            if kind:b.setIcon(glyph_icon(kind,'#efefef' if dark else '#343434',24))
        bg,card,fg,muted,border,hover=('#242424','#2e2e2e','#f4f4f4','#b5b5b5','#454545','#393939') if dark else ('#f3f3f3','#fafafa','#1a1a1a','#626262','#dddddd','#ffffff')
        self.setStyleSheet(f'''
        QWidget {{ color:{fg}; font-family:'Segoe UI Variable Text','Segoe UI','Microsoft YaHei UI'; }}
        QWidget#flyout {{background:{bg};border:1px solid {border};border-radius:10px;}}
        QDialog#catalogWindow {{background:{bg};}}
        QLabel {{background:transparent;border:0;}}
        QLabel#muted {{color:{muted};}}
        QLabel#glyph {{font-family:'Segoe Fluent Icons';color:{muted};}}
        QFrame#card {{background:{card};border:1px solid {border};border-radius:7px;}}
        QFrame#card:hover,QFrame#card:focus {{background:{hover};border-color:{windows.accent()};}}
        QFrame#separator {{background:{border};border:0;}}
        QToolButton {{background:transparent;border:0;border-radius:4px;}}
        QToolButton:hover {{background:{border};}}
        QToolButton:focus {{border:1px solid {windows.accent()};}}
        QScrollArea,QWidget#transparent,QStackedWidget {{background:transparent;border:0;}}
        QScrollBar:vertical {{background:transparent;width:5px;}}
        QScrollBar::handle:vertical {{background:{border};border-radius:2px;min-height:20px;}}
        QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical {{height:0;}}
        ''')
        if self.catalog_dialog:self.catalog_dialog.setStyleSheet(self.styleSheet())

    def change_startup(self,on):
        try:
            current=startup.set_enabled(on);self.preferences.set('autostart_requested',on)
            self.toggle.set_checked_silent(current.enabled);self.auto_state.setText(current.message)
        except OSError as e:
            self.refresh_startup()
            self.statusline.setText('开机自启设置失败');self.statusline.setToolTip(str(e))

    def refresh_startup(self):
        current=startup.state();self.toggle.set_checked_silent(current.enabled)
        self.auto_state.setText(current.message);self.auto_state.setToolTip(current.command or '登录 Windows 后自动运行')

    def rebuild(self,devices,errors):
        self.devices=devices;self.errors=errors
        if self.theme!=windows.is_dark():self.apply_theme()
        displayed=visible_devices(devices,self.preferences);keys={d.key for d in displayed}
        for key in list(self.cards):
            if key not in keys:
                card=self.cards.pop(key);self.list_layout.removeWidget(card);card.deleteLater()
        for index,d in enumerate(displayed):
            card=self.cards.get(d.key)
            if card is None:
                card=DeviceCard(d,True);card.clicked.connect(self.show_detail);self.cards[d.key]=card
                self.list_layout.insertWidget(index,card)
            else:
                card.update_device(d)
                if self.list_layout.indexOf(card)!=index:
                    self.list_layout.removeWidget(card);self.list_layout.insertWidget(index,card)
        if not hasattr(self,'empty_label'):
            self.empty_label=label('暂无可显示的设备\n可在设备管理中查看其他 HID 设备。',12,True)
            self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter);self.empty_label.setWordWrap(True)
            self.list_layout.addWidget(self.empty_label);self.list_layout.addStretch()
        self.empty_label.setVisible(not displayed)
        count=sum(d.present and d.connected is True and d.power_mode!='wired' and d.kind!='auxiliary' for d in displayed);low=lowest(displayed)
        present=sum(d.present for d in devices)
        wired=sum(d.present and d.power_mode=='wired' and d.kind!='auxiliary' for d in displayed)
        pending=sum(d.usb_keyboard and d.power_mode=='unknown' and d.connected is None for d in displayed)
        self.summary.setText(f'{count} 台电池设备在线 · {wired} 台有线'+(f' · {pending} 台 USB 待确认' if pending else '')+' · '+(f'最低 {low.percent}%' if low else '暂无有效电量'))
        self.statusline.setText(errors[0] if errors else '托盘显示最低电量')
        self.refresh_choice.blockSignals(True);self.refresh_choice.setCurrentIndex(REFRESH_INTERVALS.index(self.preferences.get('refresh_seconds',15)));self.refresh_choice.blockSignals(False)
        self.statusline.setToolTip('\n'.join(errors) if errors else '仅计算已连接且未过期的有效电量。可把托盘图标拖入或拖出 ^ 溢出区。')
        if self.selected:self.show_detail(self.selected)
        if self.isVisible():self.resize_for_content()

    def show_detail(self,key):
        d=next((d for d in self.devices if d.key==key),None)
        if not d:self.go_back();return
        rows=self.detail_values(d)
        if self.detail_key==key and self.detail_labels:
            if self.detail_title.text()!=d.name:self.detail_title.setText(d.name)
            if self.detail_note.text()!=d.note:self.detail_note.setText(d.note)
            for field,text in rows:
                if self.detail_labels[field].text()!=text:self.detail_labels[field].setText(text)
            self.detail_brand.set_brand(d.brand,d.kind)
            self.history_chart.set_samples(self.history.samples(d.key))
            self.pin_button.setEnabled(d.power_mode!='wired' and d.kind!='auxiliary')
            self.selected=key;self.back.show();self.stack.setCurrentIndex(1)
            if self.isVisible():self.resize_for_content()
            return
        scroll_position=self.detail.verticalScrollBar().value() if self.selected==key else 0
        self.selected=key;self.back.show()
        content=QWidget();content.setObjectName('transparent');layout=QVBoxLayout(content);layout.setContentsMargins(4,5,4,5);layout.setSpacing(8)
        top=QHBoxLayout();self.detail_brand=BrandIcon(d.brand,d.kind);top.addWidget(self.detail_brand);titles=QVBoxLayout();name=label(d.name,14,bold=True);self.detail_title=name;name.setWordWrap(True);titles.addWidget(name);top.addLayout(titles,1);layout.addLayout(top)
        if d.power_mode!='wired' and d.kind!='auxiliary':
            history_jump=QPushButton('电量历史');history_jump.setToolTip('查看近 24 小时电量与电压趋势')
            history_jump.clicked.connect(lambda:self.detail.ensureWidgetVisible(self.history_chart,0,6));top.addWidget(history_jump)
        self.detail_labels={}
        grid=QGridLayout();grid.setHorizontalSpacing(18);grid.setVerticalSpacing(7)
        for n,(k,v) in enumerate(rows):
            grid.addWidget(label(k,11,True),n,0);value=label(v,11);value.setWordWrap(True);value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse);grid.addWidget(value,n,1);self.detail_labels[k]=value
        grid.setColumnStretch(1,1);layout.addLayout(grid)
        note=label(d.note,11,True);self.detail_note=note;note.setWordWrap(True);layout.addWidget(note)
        from history_chart import HistoryChart
        self.history_chart=HistoryChart();self.history_chart.set_samples(self.history.samples(key));layout.addWidget(self.history_chart)
        history_note=label('本地保存 24 小时 · 每 5 分钟最多一个点\n续航按连续在线放电趋势估算；电池健康与内阻暂不可测。',10,True)
        history_note.setWordWrap(True);layout.addWidget(history_note)
        history_actions=QHBoxLayout()
        export_history=QPushButton('导出此设备历史');export_history.clicked.connect(lambda:self.export_history(d));history_actions.addWidget(export_history)
        clear_history=QPushButton('清空历史');clear_history.clicked.connect(lambda:self.clear_history(d.key));history_actions.addWidget(clear_history)
        layout.addLayout(history_actions)
        from catalog import brands
        brand_choice=QComboBox();brand_choice.addItem('品牌：自动识别','')
        for info in brands():brand_choice.addItem(info['zh']+' / '+info['name'],info['id'])
        brand_choice.setCurrentIndex(max(0,brand_choice.findData(self.preferences.get('brand_overrides',{}).get(f'{d.vid:04X}:{d.pid:04X}',''))))
        brand_choice.currentIndexChanged.connect(lambda:self.assign_brand(d,brand_choice.currentData()));layout.addWidget(brand_choice)
        mode_choice=QComboBox();mode_choice.setObjectName('deviceMode');mode_choice.setAccessibleName('连接与供电方式')
        for title,value in [('供电：自动识别',''),('有线供电 / 无电池','wired'),('电池设备（有线或无线）','battery')]:mode_choice.addItem(title,value)
        mode_choice.setCurrentIndex(max(0,mode_choice.findData(self.preferences.get('device_modes',{}).get(d.key,''))))
        mode_choice.setEnabled(d.kind!='auxiliary' and ':paired:' not in d.key)
        mode_choice.setToolTip('无法自动确认时，可指定此设备的供电类型。选择自动识别可恢复。')
        mode_choice.currentIndexChanged.connect(lambda:self.assign_mode(d,mode_choice.currentData()));layout.addWidget(mode_choice)
        pin=QPushButton('在托盘固定此设备');pin.clicked.connect(lambda:self.pin_device(d.key));layout.addWidget(pin)
        self.pin_button=pin
        pin.setEnabled(d.power_mode!='wired' and d.kind!='auxiliary')
        hide=QPushButton('隐藏此设备');hide.clicked.connect(lambda:self.hide_device(d.key));layout.addWidget(hide);layout.addStretch()
        old=self.detail.takeWidget()
        if old:old.deleteLater()
        self.detail.setWidget(content);self.stack.setCurrentIndex(1);self.detail_key=key
        QTimer.singleShot(0,lambda:self.detail.verticalScrollBar().setValue(scroll_position))
        if self.isVisible():self.resize_for_content()

    def detail_values(self,d):
        estimate=self.history.estimate(d)
        return [('设备类型',d.type_name),
                ('当前电量','不适用（有线供电）' if d.power_mode=='wired' else '不适用（辅助设备）' if d.kind=='auxiliary' else f'{d.percent}%'+(' · 已过期' if d.stale else '') if d.percent is not None else '未知'),
                ('连接情况',d.status),('USB 接口','已接入' if d.present else '未接入'),('连接方式',d.transport),
                ('充电状态','不适用' if d.power_mode=='wired' or d.kind=='auxiliary' else '正在充电' if d.charging is True else '未充电' if d.charging is False and d.connected else '未知'),
                ('连接依据',d.evidence or '未知'),('数据来源',d.source or '暂无'),
                ('电量更新时间',dt.datetime.fromtimestamp(d.observed_at).strftime('%m-%d %H:%M:%S') if d.observed_at else '暂无读数'),
                ('USB 标识',f'{d.vid:04X}:{d.pid:04X}'),('固件信息',d.firmware or '未提供'),
                ('电量精度',d.approximate or ('设备报告值' if d.percent is not None else '未知')),
                ('当前电压',f'{d.voltage_mv} mV' if d.usable and d.voltage_mv is not None else '设备未提供' if d.usable else '暂无有效读数'),
                ('放电速率',estimate.rate_text),('预计剩余',estimate.remaining_text),('估算依据',estimate.reason),
                ('上次有效值',f'{d.last_percent}% · 非实时' if d.last_percent is not None else '暂无')]

    def clear_history(self,key):
        try:self.history.forget(key);self.show_detail(key)
        except OSError as error:self.statusline.setText('历史清理失败');self.statusline.setToolTip(str(error))

    def export_history(self,d):
        from PySide6.QtWidgets import QFileDialog
        from settings import atomic_json
        path,_=QFileDialog.getSaveFileName(self,'导出设备历史','设备电量历史.json','JSON (*.json)')
        if path:
            try:
                atomic_json(path,{'version':1,'device':{'name':d.name,'brand':d.brand},'interval_seconds':300,
                    'samples':self.history.samples(d.key),'note':'仅包含真实采样，不表示电池健康或内阻。'})
                self.statusline.setText('设备历史已导出')
            except OSError as error:self.statusline.setText('历史导出失败');self.statusline.setToolTip(str(error))

    def assign_brand(self,d,brand):
        overrides=dict(self.preferences.get('brand_overrides',{}));key=f'{d.vid:04X}:{d.pid:04X}'
        if brand:overrides[key]=brand
        else:overrides.pop(key,None)
        self.preferences.set('brand_overrides',overrides);self.preferencesChanged.emit();self.refreshRequested.emit()

    def assign_mode(self,d,mode):
        modes=dict(self.preferences.get('device_modes',{}))
        if mode:modes[d.key]=mode
        else:modes.pop(d.key,None)
        self.preferences.set('device_modes',modes);self.preferencesChanged.emit();self.refreshRequested.emit()

    def change_interval(self,seconds):
        self.preferences.set('refresh_seconds',seconds);self.preferencesChanged.emit()

    def pin_device(self,key):self.preferences.set('pinned_key',key);self.preferencesChanged.emit()

    def hide_device(self,key):
        self.preferences.set('hidden',sorted(set(self.preferences.get('hidden',[]))|{key}));self.go_back();self.preferencesChanged.emit()

    def open_catalog(self):
        from dialogs import CatalogDialog
        self.hide()
        if self.raise_catalog():return
        dialog=CatalogDialog(self.devices,self.preferences,self);self.catalog_dialog=dialog
        dialog.preferencesChanged.connect(self.preferencesChanged.emit);dialog.forgetRequested.connect(self.forgetRequested.emit)
        dialog.trayPromotionRequested.connect(self.promoteTrayRequested.emit)
        dialog.deviceRequested.connect(lambda key:QTimer.singleShot(0,lambda:self.open_managed_detail(key)))
        dialog.finished.connect(lambda result:self.catalog_closed(dialog))
        dialog.show();dialog.raise_();dialog.activateWindow()

    def open_research(self):
        if self.research_controller is None:
            self.statusline.setText('当前没有可用的设备扫描器');return
        if self.research_dialog is not None:
            self.research_dialog.show();self.research_dialog.raise_();return
        from research_ui import ResearchDrawer
        self.pinned=True;dialog=ResearchDrawer(self,self.research_controller);self.research_dialog=dialog
        dialog.setStyleSheet(self.styleSheet())
        def closed(*args):
            self.research_dialog=None;self.pinned=False;dialog.deleteLater()
        dialog.finished.connect(closed)
        screen=self.screen() or QApplication.primaryScreen();bounds=screen.availableGeometry()
        x=self.x()-dialog.width()-8 if self.x()-dialog.width()-8>=bounds.left() else self.x()+self.width()+8
        x=max(bounds.left()+8,min(x,bounds.right()-dialog.width()-8))
        y=max(bounds.top()+8,min(self.y(),bounds.bottom()-dialog.height()-8))
        dialog.move(x,y);dialog.show();dialog.raise_();dialog.activateWindow()

    def raise_catalog(self):
        dialog=self.catalog_dialog
        if dialog is None:return False
        if dialog.isMinimized():dialog.showNormal()
        dialog.show();dialog.raise_();dialog.activateWindow();return True

    def catalog_closed(self,dialog):
        if self.catalog_dialog is dialog:self.catalog_dialog=None
        dialog.deleteLater()

    def open_managed_detail(self,key):
        self.show_detail(key);self.show_at_tray(self.anchor)

    def close_windows(self):
        if self.catalog_dialog:self.catalog_dialog.close()
        if self.research_dialog:self.research_dialog.close()
        self.hide()

    def go_back(self):
        self.selected=None;self.back.hide();self.stack.setCurrentIndex(0)
        if self.isVisible():self.resize_for_content()

    def show_at_tray(self,rect=None):
        self.anchor=rect;self.refresh_startup();self.resize_for_content()
        self.apply_theme();self.rebuild(self.devices,self.errors);self.show();self.raise_();self.activateWindow();windows.round_window(int(self.winId()))

    def resize_for_content(self):
        rect=self.anchor
        screen=QApplication.screenAt(rect.center()) if rect and not rect.isNull() else QApplication.screenAt(QCursor.pos())
        screen=screen or QApplication.primaryScreen();bounds=screen.availableGeometry()
        count=len(visible_devices(self.devices,self.preferences))
        self.setFixedSize(min(440,bounds.width()-24),adaptive_height(count,bounds.height(),bool(self.selected)))
        x=rect.center().x()-self.width()//2 if rect and not rect.isNull() else bounds.right()-self.width()-12
        y=bounds.bottom()-self.height()-10
        if rect and not rect.isNull() and rect.center().y()<bounds.top()+50:y=bounds.top()+10
        self.move(max(bounds.left()+8,min(x,bounds.right()-self.width()-8)),y)

    def keyPressEvent(self,e):
        if e.key()==Qt.Key.Key_Escape:
            self.go_back() if self.selected else self.hide()
        else:super().keyPressEvent(e)

    def changeEvent(self,e):
        from PySide6.QtCore import QEvent
        if e.type()==QEvent.Type.ActivationChange and not self.isActiveWindow() and not self.pinned and not self.menu_open:
            QTimer.singleShot(160,self.hide_if_inactive)
        super().changeEvent(e)

    def hide_if_inactive(self):
        if not self.isActiveWindow() and not self.pinned and not self.menu_open:self.hide()

    def closeEvent(self,e):e.ignore();self.hide()


def adaptive_height(count,available_height,detail=False):
    maximum=max(160,min(760,round(available_height*.78),available_height-20))
    desired=max(286,214+max(1,count)*70+max(0,count-1)*6)
    return min(maximum,max(430,desired) if detail else desired)
