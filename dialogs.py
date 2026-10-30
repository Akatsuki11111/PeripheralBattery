"""Local brand directory and device preferences; no network access at runtime."""
from PySide6.QtCore import Signal,Qt
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QWidget,QTabWidget,QTableWidget,QTableWidgetItem,
 QHeaderView,QLineEdit,QLabel,QCheckBox,QComboBox,QPushButton,QScrollArea)
from catalog import brands,load_catalog
from icons import BrandIcon
from settings import REFRESH_INTERVALS


class CatalogDialog(QDialog):
    preferencesChanged=Signal()
    forgetRequested=Signal(str)
    deviceRequested=Signal(str)
    trayPromotionRequested=Signal()

    def __init__(self,devices,preferences,parent=None):
        # A normal independent window must not inherit the flyout's topmost
        # ownership or disable it through a nested modal event loop.
        super().__init__(None,Qt.WindowType.Window);self.preferences=preferences;self.logos=[]
        self.setWindowModality(Qt.WindowModality.NonModal)
        if parent:self.setStyleSheet(parent.styleSheet())
        self.setWindowTitle('品牌目录与设备管理');self.setObjectName('catalogWindow');self.resize(720,560)
        root=QVBoxLayout(self);tabs=QTabWidget();root.addWidget(tabs)
        page=QWidget();layout=QVBoxLayout(page)
        layout.addWidget(QLabel(f'{len(brands())} 个品牌 · {len(load_catalog()["devices"])} 个明确型号 ID'))
        note=QLabel('品牌识别不等于电量已适配；无有效协议的设备显示电量未知。');note.setWordWrap(True);layout.addWidget(note)
        search=QLineEdit();search.setPlaceholderText('搜索品牌、中文名或型号');layout.addWidget(search)
        table=QTableWidget(0,3);table.setHorizontalHeaderLabels(['品牌','电量适配','明确型号 ID'])
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers);table.verticalHeader().hide()
        table.horizontalHeader().setSectionResizeMode(0,QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setSectionResizeMode(1,QHeaderView.ResizeMode.ResizeToContents)
        for info in brands():
            profiles=[p for p in load_catalog()['devices'] if p['brand']==info['id']]
            row=table.rowCount();table.insertRow(row);table.setRowHeight(row,40)
            item=QTableWidgetItem(info['zh']+' · '+info['name']);logo=BrandIcon(info['name'],'mouse');self.logos.append(logo)
            item.setIcon(logo.icon);item.setToolTip(info['website']);table.setItem(row,0,item)
            status=QTableWidgetItem('手柄标准通道，依型号/模式' if info.get('controller') else '部分型号可读取' if any(p['backend'] for p in profiles) or info['id']=='logitech' else '有线设备，电量不适用' if any(p.get('wired') for p in profiles) else '可识别，电量待适配')
            status.setToolTip('\n'.join(p['name'] for p in profiles) or '不会向未知型号猜测发送电量命令。')
            table.setItem(row,1,status);table.setItem(row,2,QTableWidgetItem(str(len(profiles))))
        def filter_rows(text):
            for row,info in enumerate(brands()):
                model_names=' '.join(p['name'] for p in load_catalog()['devices'] if p['brand']==info['id'])
                table.setRowHidden(row,text.casefold() not in (info['name']+' '+info['zh']+' '+model_names).casefold())
        search.textChanged.connect(filter_rows);layout.addWidget(table);tabs.addTab(page,'支持目录')
        manager=QWidget();body=QVBoxLayout(manager)
        promote=QPushButton('显示到任务栏（无需拖动）');promote.clicked.connect(lambda checked=False:self.trayPromotionRequested.emit());body.addWidget(promote)
        taskbar=QPushButton('任务栏图标显示设置');taskbar.setToolTip('在 Windows“其他系统托盘图标”中开启设备电量，即可固定显示。')
        import windows
        taskbar.clicked.connect(windows.show_tray_settings);body.addWidget(taskbar)
        hint=QLabel('供电类型未能自动确认时，可点击设备“详情”手动指定有线供电 / 无电池。');hint.setWordWrap(True);body.addWidget(hint)
        for key,title in [('show_offline','显示接收器仍接入的休眠或关闭设备'),
                          ('show_unreadable','显示无电量协议且无线类型待确认的 HID 设备'),
                          ('show_auxiliary','在主列表显示辅助 USB 设备（非鼠标/键盘）'),
                          ('low_notifications','低电量提醒（每次放电周期仅一次）')]:
            check=QCheckBox(title);check.setChecked(preferences.get(key,False));check.toggled.connect(lambda on,k=key:self.save(k,on));body.addWidget(check)
        interval=QComboBox();interval.setObjectName('refreshInterval');interval.setAccessibleName('自动刷新间隔')
        for seconds in REFRESH_INTERVALS:interval.addItem(f'每 {seconds} 秒刷新',seconds)
        interval.setCurrentIndex(REFRESH_INTERVALS.index(preferences.get('refresh_seconds',15)))
        interval.currentIndexChanged.connect(lambda:self.save('refresh_seconds',interval.currentData()));body.addWidget(interval)
        threshold=QComboBox()
        for value in (10,15,20,25,30,40,50):threshold.addItem(f'低电量阈值 {value}%',value)
        threshold.setCurrentIndex(max(0,threshold.findData(preferences.get('low_threshold',20))))
        threshold.currentIndexChanged.connect(lambda:self.save('low_threshold',threshold.currentData()));body.addWidget(threshold)
        auto=QPushButton('托盘恢复为自动选择最低电量');auto.clicked.connect(lambda:self.save('pinned_key',''));body.addWidget(auto)
        scroll=QScrollArea();scroll.setWidgetResizable(True);container=QWidget();entries=QVBoxLayout(container)
        for device in devices:
            row=QHBoxLayout();check=QCheckBox(device.name+' · '+device.status);check.setChecked(device.key not in preferences.get('hidden',[]))
            check.toggled.connect(lambda on,key=device.key:self.set_visible(key,on));row.addWidget(check,1)
            detail=QPushButton('详情');detail.clicked.connect(lambda checked=False,key=device.key:self.open_detail(key));row.addWidget(detail)
            if not device.present:
                button=QPushButton('忘记');button.clicked.connect(lambda checked=False,key=device.key:self.forgetRequested.emit(key));row.addWidget(button)
            entries.addLayout(row)
        entries.addStretch();scroll.setWidget(container);body.addWidget(scroll);tabs.addTab(manager,'设备管理')
        done=QPushButton('完成');done.clicked.connect(self.accept);root.addWidget(done)

    def save(self,key,value):self.preferences.set(key,value);self.preferencesChanged.emit()

    def open_detail(self,key):
        self.accept();self.deviceRequested.emit(key)

    def set_visible(self,key,on):
        hidden=set(self.preferences.get('hidden',[]))
        hidden.discard(key) if on else hidden.add(key)
        self.save('hidden',sorted(hidden))
