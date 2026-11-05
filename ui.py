import datetime as dt
import time
from PySide6.QtCore import Qt, QEvent, QTimer, Signal, QRectF, QSize
from PySide6.QtGui import QColor,QPainter,QPen,QFont,QCursor,QPalette
from PySide6.QtWidgets import (QWidget,QLabel,QPushButton,QToolButton,QVBoxLayout,QHBoxLayout,
    QFrame,QScrollArea,QStackedWidget,QSizePolicy,QApplication,QGridLayout,QComboBox,QProgressBar,
    QStyle,QStyleOptionToolButton,QStylePainter,QMenu)
from icons import font,glyph_icon,BrandIcon,BatteryBar,device_outline
from appearance import CARD_RADIUS, panel_dark, palette
from models import lowest
from catalog import visible_devices
from settings import Settings,REFRESH_INTERVALS,VERSION,RELEASE_CHANNEL,EXPERIMENTAL_ENABLED,LOCAL_PREVIEW
import startup
import windows

PANEL_WIDTH = 350
CARD_SPACING = 8


def label(text='',size=12,muted=False,bold=False):
    l=QLabel(text);l.setTextFormat(Qt.TextFormat.PlainText);l.setFont(font(size,QFont.Weight.DemiBold if bold else QFont.Weight.Normal))
    if muted:l.setObjectName('muted')
    return l


def tool(kind,tip,callback):
    b=QToolButton();b.setFixedSize(30,30);b.setToolTip(tip);b.setAccessibleName(tip)
    b.setFocusPolicy(Qt.FocusPolicy.TabFocus)
    b.setProperty('glyphKind',kind)
    b.setIcon(glyph_icon(kind,'#efefef' if windows.is_dark() else '#343434',24))
    b.clicked.connect(callback);return b


def footer_style(widget):
    widget.setObjectName('footerAction')
    widget.setMinimumSize(0, 47)
    widget.setMaximumHeight(47)
    widget.setFont(font(10, QFont.Weight.Medium))
    widget.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)


class FooterButton(QToolButton):
    def __init__(self, kind, text, caption=None):
        super().__init__()
        footer_style(self)
        self.caption = caption
        self.setText(text)
        self.setToolTip(text)
        self.setAccessibleName(text)
        self.setProperty('glyphKind', kind)
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        self.setIconSize(QSize(19, 19))

    def paintEvent(self, event):
        option = QStyleOptionToolButton()
        self.initStyleOption(option)
        option.text = self.caption or {
            '检查更新': '更新', '下载并更新': '下载', '正在检查…': '检查中',
            '导入更新配置': '导入', '安装并重启': '安装',
        }.get(self.text(), self.text())
        option.text = self.fontMetrics().elidedText(
            option.text, Qt.TextElideMode.ElideRight, max(0, self.width() - 4))
        painter = QStylePainter(self)
        painter.drawComplexControl(QStyle.ComplexControl.CC_ToolButton, option)


class Toggle(FooterButton):
    def __init__(self, checked):
        super().__init__('power', '开机自启', '自启')
        self.setCheckable(True)
        self.setChecked(checked)

    @property
    def position(self):
        return int(self.isChecked())

    def set_checked_silent(self, on):
        previous = self.blockSignals(True)
        self.setChecked(bool(on))
        self.blockSignals(previous)


def display_name(device):
    name=device.name
    for prefix in ('SteelSeries ','Razer ','SCYROX '):
        if name.startswith(prefix):name=name[len(prefix):]
    return name.removesuffix(' RECEIVER')


def needs_power_choice(d):
    return (d.present and not d.receiver and d.kind!='auxiliary' and d.power_mode=='unknown'
            and not d.usable and not d.fresh_grade and (d.usb_keyboard or 'USB' in d.transport))


class ElidedLabel(QLabel):
    """Keep the full label available to accessibility and the tooltip."""
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setFont(self.font())
        painter.setPen(self.palette().color(QPalette.ColorRole.WindowText))
        rect = self.contentsRect()
        text = self.fontMetrics().elidedText(self.text(), Qt.TextElideMode.ElideRight, rect.width())
        painter.drawText(rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)


class DeviceCard(QFrame):
    clicked = Signal(str)
    powerModeRequested = Signal(str, str)

    def __init__(self, d, compact=False, show_power_choice=False, *, dark=None):
        super().__init__()
        self.setObjectName('card')
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.theme = None
        self.d = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 9, 12, 9)
        layout.setSpacing(5)
        header = QHBoxLayout()
        header.setSpacing(10)

        self.brand_icon = BrandIcon(d.brand, d.kind)
        header.addWidget(self.brand_icon, 0, Qt.AlignmentFlag.AlignVCenter)
        content = QVBoxLayout()
        content.setSpacing(7)
        details = QHBoxLayout()
        details.setSpacing(6)

        text = QVBoxLayout()
        text.setSpacing(1)
        self.name_label = ElidedLabel()
        self.name_label.setTextFormat(Qt.TextFormat.PlainText)
        self.name_label.setFont(font(14, QFont.Weight.DemiBold))
        self.name_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        text.addWidget(self.name_label)

        status = QHBoxLayout()
        status.setSpacing(5)
        self.kind_label = QLabel()
        self.kind_label.setFixedSize(16, 16)
        self.kind_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.kind_label.setToolTip(d.type_name)
        status.addWidget(self.kind_label)
        self.status_label = ElidedLabel()
        self.status_label.setObjectName('muted')
        self.status_label.setFont(font(11))
        self.status_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        status.addWidget(self.status_label, 1)
        text.addLayout(status)
        details.addLayout(text, 1)

        self.value_label = label()
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.value_label.setFixedWidth(68)
        details.addWidget(self.value_label, 0, Qt.AlignmentFlag.AlignTop)
        content.addLayout(details)

        self.bar = BatteryBar()
        content.addWidget(self.bar)
        header.addLayout(content, 1)
        layout.addLayout(header)
        self.power_row = QWidget()
        power = QHBoxLayout(self.power_row)
        power.setContentsMargins(0, 0, 0, 0)
        power.setSpacing(6)
        power.addWidget(label('供电状态', 11, True))
        from PySide6.QtWidgets import QButtonGroup
        self.power_group = QButtonGroup(self)
        self.power_buttons = {}
        for text, mode in (('有线', 'wired'), ('电池', 'battery')):
            button = QPushButton(text)
            button.setObjectName('powerChoice')
            button.setCheckable(True)
            button.setFont(font(11, QFont.Weight.Medium))
            button.setFixedSize(44, 23)
            button.setAccessibleName('供电状态：' + text)
            self.power_group.addButton(button)
            button.clicked.connect(lambda checked, m=mode: self.powerModeRequested.emit(self.d.key, m))
            power.addWidget(button)
            self.power_buttons[mode] = button
        power.addStretch()
        layout.addWidget(self.power_row)
        self.update_device(d, show_power_choice, dark)

    def update_device(self, d, show_power_choice=False, dark=None):
        dark = windows.is_dark() if dark is None else dark
        dpr = self.devicePixelRatioF()
        if self.d == d and self.show_power_choice == show_power_choice and self.theme == (dark, dpr):
            return
        if self.d is None or self.d.kind != d.kind or self.theme != (dark, dpr):
            self.kind_label.setPixmap(device_outline(d.kind, 15, palette(dark).text, dpr))
            self.kind_label.setToolTip(d.type_name)
        self.theme = (dark, dpr)
        self.bar.dark = dark
        self.d = d
        self.show_power_choice = show_power_choice
        self.power_row.setVisible(show_power_choice)
        show_bar = d.power_mode != 'wired' and d.kind != 'auxiliary' and not needs_power_choice(d)
        for mode, button in self.power_buttons.items():
            button.setChecked(d.power_mode == mode)
        self.brand_icon.set_brand(d.brand, d.kind)
        self.name_label.setText(display_name(d))
        self.name_label.setToolTip(d.name)
        status = 'USB 已接入' if needs_power_choice(d) else d.status
        if d.cached and '上次' not in status:
            status += ' · 上次 ' + d.last_read_time
        if d.power_mode == 'wired' and d.connected is True:
            status = '已连接'
        elif status == '已连接' and '2.4' in d.transport:
            status = '2.4 GHz · 已连接'
        self.status_label.setText('上次 ' + d.last_read_time if d.cached else status)
        self.status_label.setToolTip(status + ('\n' + d.note if d.note else ''))
        self.value_label.setText(d.reading_text)
        self.value_label.setFont(font(14 if d.kind == 'auxiliary' else 17,
                                      QFont.Weight.DemiBold))
        self.value_label.setToolTip(
            '上次有效电量 · ' + dt.datetime.fromtimestamp(d.last_observed_at).strftime('%m-%d %H:%M:%S')
            if d.cached else '实验推测' if d.experimental else '分档电量，非百分比'
            if d.display_grade else d.approximate or status)
        tone = '' if d.usable or d.fresh_grade or d.power_mode == 'wired' else 'muted'
        if self.value_label.objectName() != tone:
            self.value_label.setObjectName(tone)
            self.value_label.style().unpolish(self.value_label)
            self.value_label.style().polish(self.value_label)
        self.bar.value = d.display_percent
        self.bar.grade = d.display_grade
        self.bar.stale = not (d.usable or d.fresh_grade)
        self.bar.charging = bool(d.charging and not self.bar.stale)
        self.bar.setVisible(show_bar)
        self.bar.update()
        self.setAccessibleName(d.name + '，' + status + '，' + d.reading_text)

    def mouseReleaseEvent(self,e):
        if e.button()==Qt.MouseButton.LeftButton:self.clicked.emit(self.d.key)

    def keyPressEvent(self,e):
        if e.key() in (Qt.Key.Key_Return,Qt.Key.Key_Space):self.clicked.emit(self.d.key)
        else:super().keyPressEvent(e)


class Flyout(QWidget):
    installUpdateRequested=Signal(object)
    refreshRequested=Signal()
    preferencesChanged=Signal()
    forgetRequested=Signal(str)
    promoteTrayRequested=Signal()
    def __init__(self,preferences=None,history=None):
        super().__init__(None,Qt.WindowType.Tool|Qt.WindowType.FramelessWindowHint|Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowTitle('设备电量 · Peripheral Battery');self.setObjectName('flyout')
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.devices=[];self.errors=[];self.selected=None;self.pinned=False;self.menu_open=False;self.theme=None
        self.preferences=preferences or Settings();self.cards={};self.anchor=None;self.detail_labels={};self.detail_key=None
        from history import HistoryStore
        self.history=history or HistoryStore(self.preferences.path.with_name('history.json'))
        self.catalog_dialog=None;self.research_dialog=None;self.research_controller=None;self.learning=None;self.learning_dialog=None
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.root=QVBoxLayout(self);self.root.setContentsMargins(13,12,13,10);self.root.setSpacing(8)
        head=QHBoxLayout();head.setSpacing(5)
        self.back=tool('back','返回设备列表',self.go_back);self.back.hide();head.addWidget(self.back)
        titlecol=QVBoxLayout();titlecol.setSpacing(1);title_row=QHBoxLayout();title_row.setSpacing(6)
        title = label('设备电量', 21)
        title.setFont(font(21, QFont.Weight.Bold))
        title_row.addWidget(title)
        self.version_label = label('v' + VERSION, 10, True)
        self.version_label.setToolTip('本地界面测试版' if LOCAL_PREVIEW else '当前版本：' + VERSION)
        title_row.addWidget(self.version_label)
        title_row.addStretch()
        titlecol.addLayout(title_row);head.addLayout(titlecol,1)
        self.refresh=tool('refresh','立即刷新',self.refreshRequested.emit);head.addWidget(self.refresh)
        self.info_button=tool('info','品牌目录与设备管理',self.open_catalog);head.addWidget(self.info_button);head.addWidget(tool('close','收起到系统托盘',self.hide))
        self.root.addLayout(head)
        self.summary=label('正在读取设备状态…',11,True);self.root.addWidget(self.summary)
        self.release_notice=QFrame();self.release_notice.setObjectName('releaseNotice')
        notice=QVBoxLayout(self.release_notice);notice.setContentsMargins(10,8,10,8);notice.setSpacing(4)
        notice_head=QHBoxLayout();self.release_notice_title=label('',12,bold=True);notice_head.addWidget(self.release_notice_title,1)
        dismiss=QPushButton('知道了');dismiss.setFont(font(10));dismiss.setFocusPolicy(Qt.FocusPolicy.TabFocus);dismiss.clicked.connect(self.dismiss_release_notice);notice_head.addWidget(dismiss)
        notice.addLayout(notice_head);self.release_notice_text=label('',11);self.release_notice_text.setWordWrap(True);notice.addWidget(self.release_notice_text)
        self.release_notice.hide();self.root.addWidget(self.release_notice)
        self.stack = QStackedWidget()
        # The root hint now measures the header and footer separately from the active page.
        self.stack.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Ignored)
        self.root.addWidget(self.stack, 1)
        self.scroll=QScrollArea();self.scroll.setWidgetResizable(True);self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list_body=QWidget();self.list_body.setObjectName('transparent');self.list_layout=QVBoxLayout(self.list_body);self.list_layout.setContentsMargins(0,0,0,0);self.list_layout.setSpacing(CARD_SPACING)
        self.scroll.setWidget(self.list_body);self.stack.addWidget(self.scroll)
        self.detail=QScrollArea();self.detail.setWidgetResizable(True);self.detail.setFrameShape(QFrame.Shape.NoFrame);self.stack.addWidget(self.detail)
        line=QFrame();line.setObjectName('separator');line.setFixedHeight(1);self.root.addWidget(line)
        version_box = QWidget()
        self.version_box = version_box
        self.footer = QHBoxLayout(version_box)
        self.footer.setContentsMargins(0, 0, 0, 0)
        self.footer.setSpacing(4)
        self.root.addWidget(version_box)

        self.auto_state = label('', 10, True)
        self.auto_state.setParent(self)
        self.auto_state.hide()
        self.toggle = Toggle(False)
        self.toggle.toggled.connect(self.change_startup)
        self.refresh_choice = FooterButton('clock', f"{self.preferences.get('refresh_seconds')} 秒")
        self.refresh_choice.setAccessibleName('自动刷新间隔')
        self.refresh_choice.setToolTip('自动刷新间隔')
        self.refresh_choice.clicked.connect(self.open_refresh_menu)

        self.desktop_button = FooterButton('desktop', '桌面显示', '桌面')
        self.desktop_button.clicked.connect(self.open_desktop_menu)
        self.test_button = FooterButton('test', '无法适配电量时，点此测试', '电量测试')
        self.test_button.clicked.connect(self.open_research)
        self.update_button = FooterButton('update', '检查更新')
        self.theme_button = FooterButton('theme', '界面主题', '主题')
        self.theme_button.clicked.connect(self.open_theme_menu)
        for control in (self.toggle, self.refresh_choice, self.desktop_button,
                        self.test_button, self.update_button, self.theme_button):
            self.footer.addWidget(control, 1)
        self.update_badge=QLabel('新版本可更新',version_box);self.update_badge.setFont(font(9));self.update_badge.setFixedSize(88,18)
        self.update_badge.setAlignment(Qt.AlignmentFlag.AlignCenter);self.update_badge.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents,True)
        self.update_badge.setStyleSheet('QLabel {background:#0067c0;color:white;border-radius:4px;padding:1px 3px;}');self.update_badge.hide()
        self.statusline=label('托盘显示最低电量',10,True);self.statusline.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Preferred);self.statusline.hide();self.root.addWidget(self.statusline)
        self.update_job=None;self.update_url=None;self.update_button.clicked.connect(self.check_update)
        self.update_candidate=None;self.download_ready=None;self.needs_update_config=False
        download_row=QHBoxLayout();self.root.addLayout(download_row)
        self.download_progress=QProgressBar();self.download_progress.setRange(0,100);self.download_progress.hide();download_row.addWidget(self.download_progress,1)
        self.cancel_download=QPushButton('取消');self.cancel_download.hide();self.cancel_download.clicked.connect(self.cancel_update);download_row.addWidget(self.cancel_download)
        self.update_progress_timer=QTimer(self);self.update_progress_timer.setInterval(400);self.update_progress_timer.timeout.connect(self.read_download_progress)
        from settings import read_json,data_dir
        previous_update=read_json(data_dir()/'updates/last-result.json',{})
        if previous_update.get('ok') is False and 0<=time.time()-previous_update.get('at',0)<86400:
            self.update_button.setText('上次更新失败');self.update_button.setToolTip(previous_update.get('message','请重新检查更新'))
        self.load_release_notice(previous_update)
        if LOCAL_PREVIEW:
            self.update_button.setEnabled(False)
            self.update_button.setToolTip('本地测试版独立运行，正式版可检查更新。')
            self.toggle.setEnabled(False)
        self.apply_theme()
        self.refresh_startup()

    def check_update(self,automatic=False):
        if LOCAL_PREVIEW or self.update_job:return
        if automatic and (self.download_ready or self.needs_update_config):return
        if self.needs_update_config:
            from PySide6.QtWidgets import QFileDialog
            from update_config import save_config
            import json
            pinned=self.pinned;self.pinned=True
            try:
                path,_=QFileDialog.getOpenFileName(self,'导入更新配置','','JSON (*.json)')
                if not path:return
                from pathlib import Path
                raw=Path(path).read_bytes()
                if len(raw)>16384:raise ValueError('更新配置文件过大')
                save_config(json.loads(raw));self.needs_update_config=False
                self.update_button.setText('检查更新');self.update_button.setToolTip('更新配置已保存到本机受保护的用户目录')
            except (ValueError,OSError):self.update_button.setToolTip('更新配置导入失败，请检查部署配置')
            finally:self.pinned=pinned
            return
        if not automatic and self.download_ready:self.installUpdateRequested.emit(self.download_ready);return
        if not automatic and self.update_candidate:self.download_update();return
        from jobs import WorkerJob
        self.update_button.setEnabled(False);self.update_button.setText('正在检查…')
        job=WorkerJob({'operation':'check-updates','include_prereleases':False,'background':automatic},18000,self);self.update_job=job
        job.finished.connect(lambda result:self.update_checked(job,result));job.start()

    def update_checked(self,job,result):
        if self.update_job is not job:return
        self.update_job=None;self.update_button.setEnabled(True)
        if not result.get('ok'):
            self.update_button.setText('重试更新');self.update_button.setToolTip(result.get('user_message',result.get('error','检查失败')));return
        info=result.get('update',{});status=info.get('status');self.update_button.setToolTip(info.get('message',''))
        self.version_label.setToolTip(info.get('message',''))
        if status=='available':
            self.update_candidate = info
            self.update_badge.show()
            self.footer.setContentsMargins(0, 18, 0, 0)
            self.footer.activate()
            self.update_button.setText('下载并更新')
            if self.isVisible():self.resize_for_content()
            self.position_update_badge()
            return
        self.update_badge.hide()
        self.footer.setContentsMargins(0, 0, 0, 0)
        self.footer.activate()
        if self.isVisible():self.resize_for_content()
        self.update_candidate=None
        if status=='unconfigured':
            self.needs_update_config=True;self.update_button.setText('导入更新配置');return
        if status=='no_release':self.update_button.setText('暂无新版');return
        self.update_button.setText('已是最新' if status=='current' else '当前较新' if status=='ahead' else '检查更新')

    def position_update_badge(self):
        if hasattr(self,'update_badge'):
            self.update_badge.move(max(0, self.update_button.x() + self.update_button.width()
                                       - self.update_badge.width()), 0)
            self.update_badge.raise_()

    def load_release_notice(self,last_update):
        from settings import read_json,data_dir
        from pathlib import Path
        seen=read_json(data_dir()/'updates/seen-release.json',{})
        if (last_update.get('ok') is not True or str(last_update.get('version','')).removeprefix('v')!=VERSION
                or seen.get('version')==VERSION or not 0<=time.time()-last_update.get('at',0)<7*86400):return
        notes=read_json(Path(__file__).with_name('release-notes.json'),{})
        items=notes.get('items',[]) if notes.get('version')==VERSION else []
        items=[x[:90] for x in items[:3] if isinstance(x,str)]
        if not items:return
        self.release_notice_title.setText('已更新至 v'+VERSION)
        self.release_notice_text.setText('\n'.join('• '+item for item in items));self.release_notice.show()

    def dismiss_release_notice(self):
        from settings import atomic_json,data_dir
        try:atomic_json(data_dir()/'updates/seen-release.json',{'version':VERSION,'at':time.time()})
        except OSError:pass
        self.release_notice.hide()
        if self.isVisible():self.resize_for_content()

    def resizeEvent(self,event):
        super().resizeEvent(event);self.position_update_badge()

    def download_update(self):
        import sys
        if not getattr(sys,'frozen',False):self.update_button.setToolTip('源码运行模式请使用 Git 更新');return
        from jobs import WorkerJob
        self.download_progress.show();self.download_progress.setValue(0);self.download_progress.setFormat('正在连接版本服务器…')
        self.cancel_download.show();self.update_button.setEnabled(False)
        job=WorkerJob({'operation':'download-update','tag':self.update_candidate['latest'],
                       'include_prereleases':False},1800000,self)
        self.update_job=job;job.finished.connect(lambda result:self.download_finished(job,result));job.start();self.update_progress_timer.start()
        self.resize_for_content()

    def read_download_progress(self):
        if not self.update_job:return
        from settings import read_json
        info=read_json(self.update_job.path.with_name(self.update_job.nonce+'.progress.json'),{})
        total=info.get('total',0);received=info.get('received',0)
        if type(total) is int and total>0 and type(received) is int and 0<=received<=total:
            self.download_progress.setValue(int(received/total*100))
            self.download_progress.setFormat(f'{received/1048576:.1f} / {total/1048576:.1f} MB · %p%')

    def download_finished(self,job,result):
        if self.update_job is not job:return
        self.update_job=None;self.update_progress_timer.stop();self.cancel_download.hide();self.update_button.setEnabled(True)
        if not result.get('ok'):
            self.download_progress.setFormat('下载失败，未安装');self.update_candidate=None;self.update_button.setText('重新检查')
            self.update_button.setToolTip(result.get('user_message',result.get('error','下载失败')));return
        self.download_ready=result['download'];self.download_progress.setValue(100);self.download_progress.setFormat('校验完成，正在安装并重启…')
        self.update_button.setText('安装并重启');self.installUpdateRequested.emit(self.download_ready)

    def cancel_update(self):
        job=self.update_job;self.update_job=None;self.update_progress_timer.stop()
        if job:
            job.cancel()
            from settings import data_dir
            for suffix in ('.part','.exe'):
                try:(data_dir()/'updates'/(job.nonce+suffix)).unlink(missing_ok=True)
                except OSError:pass
        self.download_progress.hide();self.cancel_download.hide();self.update_button.setEnabled(True)
        self.update_button.setText('下载并更新' if self.update_candidate else '检查更新')

    def paintEvent(self, event):
        theme = palette(self.theme)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(theme.border), 1))
        painter.setBrush(QColor(theme.background))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(.5, .5, -.5, -.5), 16, 16)

    def apply_theme(self):
        dark = panel_dark(self.preferences)
        self.theme = dark
        theme = palette(dark)
        self.update()
        for b in self.findChildren(QToolButton):
            kind=b.property('glyphKind')
            if kind:b.setIcon(glyph_icon(kind, theme.text, 36))
        bg, card, fg, muted, border, hover = theme[:6]
        accent = theme.accent
        self.setStyleSheet(f'''
        QWidget {{ color:{fg}; font-family:'Segoe UI Variable Text','Segoe UI','Microsoft YaHei UI'; }}
        QDialog#catalogWindow {{background:{bg};}}
        QLabel {{background:transparent;border:0;}}
        QLabel#muted {{color:{muted};}}
        QFrame#card {{background:{card};border:1px solid {border};border-radius:{CARD_RADIUS}px;}}
        QFrame#card:hover {{background:{hover};}}
        QFrame#card:focus {{border-color:{accent};}}
        QPushButton {{background:{card};border:1px solid {border};border-radius:8px;padding:4px 8px;}}
        QPushButton:hover {{background:{hover};}}
        QPushButton:focus {{border-color:{accent};}}
        QPushButton:disabled {{color:{muted};background:{bg};}}
        QPushButton#powerChoice {{background:{card};border:1px solid {border};border-radius:6px;padding:0;}}
        QPushButton#powerChoice:checked {{background:{accent};color:{bg};border-color:{accent};}}
        QFrame#separator {{background:{border};border:0;}}
        QFrame#releaseNotice {{background:{card};border:1px solid {border};border-radius:{CARD_RADIUS}px;}}
        QToolButton {{background:transparent;border:0;border-radius:4px;}}
        QToolButton:hover {{background:{border};}}
        QToolButton:focus {{border:1px solid {accent};}}
        QToolButton#footerAction {{border:1px solid transparent;border-radius:8px;padding:0;}}
        QToolButton#footerAction:hover {{background:{theme.tile};}}
        QToolButton#footerAction:checked {{background:{theme.tile};color:{accent};}}
        QToolButton#footerAction:focus {{border-color:{accent};}}
        QToolButton#footerAction:disabled {{color:{muted};}}
        QMenu,QAbstractItemView {{background:{card};color:{fg};border:1px solid {border};}}
        QMenu::item:selected,QAbstractItemView::item:selected {{background:{theme.tile};color:{fg};}}
        QScrollArea,QWidget#transparent,QStackedWidget {{background:transparent;border:0;}}
        QScrollBar:vertical {{background:transparent;width:5px;}}
        QScrollBar::handle:vertical {{background:{border};border-radius:2px;min-height:20px;}}
        QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical {{height:0;}}
        ''')
        if self.catalog_dialog:self.catalog_dialog.setStyleSheet(self.styleSheet())

    def change_startup(self,on):
        if LOCAL_PREVIEW:return
        try:
            current=startup.set_enabled(on);self.preferences.set('autostart_requested',on)
            self.toggle.set_checked_silent(current.enabled);self.auto_state.setText(current.message)
        except OSError as e:
            self.refresh_startup()
            self.statusline.setText('开机自启设置失败');self.statusline.setToolTip(str(e))

    def refresh_startup(self):
        if LOCAL_PREVIEW:
            self.toggle.setToolTip('本地测试版，请从正式版管理开机自启。')
            return
        current=startup.state();self.toggle.set_checked_silent(current.enabled)
        self.auto_state.setText(current.message);self.auto_state.setToolTip(current.command or '登录 Windows 后自动运行');self.toggle.setToolTip(current.message+'；登录 Windows 后自动运行')

    def rebuild(self,devices,errors):
        self.devices=devices;self.errors=errors
        if self.research_dialog is not None and self.research_dialog.stage==0:self.research_dialog.fill_devices()
        if self.theme!=panel_dark(self.preferences):self.apply_theme()
        displayed=visible_devices(devices,self.preferences);keys={d.key for d in displayed}
        for key in list(self.cards):
            if key not in keys:
                card=self.cards.pop(key);self.list_layout.removeWidget(card);card.hide();card.deleteLater()
        for index,d in enumerate(displayed):
            card=self.cards.get(d.key)
            if card is None:
                card=DeviceCard(d,True,needs_power_choice(d) or d.key in self.preferences.get('device_modes',{}),dark=self.theme);card.clicked.connect(self.show_detail);card.powerModeRequested.connect(lambda key,mode:self.assign_mode(next(d for d in self.devices if d.key==key),mode));self.cards[d.key]=card
                self.list_layout.insertWidget(index,card)
                card.show()
            else:
                card.update_device(d,needs_power_choice(d) or d.key in self.preferences.get('device_modes',{}),self.theme)
                if self.list_layout.indexOf(card)!=index:
                    self.list_layout.removeWidget(card);self.list_layout.insertWidget(index,card)
        if not hasattr(self,'empty_label'):
            self.empty_label=label('暂无可显示的设备\n可在设备管理中查看其他 HID 设备。',12,True)
            self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter);self.empty_label.setWordWrap(True)
            self.empty_label.setMinimumHeight(72)
            self.list_layout.addWidget(self.empty_label);self.list_layout.addStretch()
        self.empty_label.setVisible(not displayed)
        low = lowest(displayed)
        summary = f'{len(displayed)} 台设备'
        if low:
            summary += f' · 最低 {low.percent}%'
        elif any(d.fresh_grade for d in displayed):
            summary += ' · 分档电量'
        self.summary.setText(summary)
        self.statusline.setText(errors[0] if errors else '托盘显示最低电量');self.statusline.setVisible(bool(errors))
        self.refresh_choice.setText(f"{self.preferences.get('refresh_seconds')} 秒")
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
        last=(('约' if d.approximate else '')+f'{d.last_percent}%' if d.last_percent is not None else d.last_battery_grade)
        last_text=(last+' · '+d.last_read_time+' · 非实时') if last and d.last_observed_at else '暂无'
        battery_stamp=d.observed_at if d.usable or d.fresh_grade else d.last_observed_at
        return [('设备类型',d.type_name),
                ('当前电量','不适用（有线供电）' if d.power_mode=='wired' else '不适用（辅助设备）' if d.kind=='auxiliary' else ('约' if d.approximate else '')+f'{d.percent}%'+(' · 已过期' if d.stale else '') if d.percent is not None else d.battery_grade+'（分档电量，非百分比）' if d.battery_grade else '未知'),
                ('连接情况',d.status),('USB 接口','已接入' if d.present else '未接入'),('连接方式',d.transport),
                ('充电状态','不适用' if d.power_mode=='wired' or d.kind=='auxiliary' else '正在充电' if d.charging is True else '未充电' if d.charging is False and d.connected else '未知'),
                ('连接依据',d.evidence or '未知'),('数据来源',d.source or '暂无'),
                ('电量更新时间',dt.datetime.fromtimestamp(battery_stamp).strftime('%m-%d %H:%M:%S') if battery_stamp else '暂无有效读数'),
                ('USB 标识',f'{d.vid:04X}:{d.pid:04X}'),('固件信息',d.firmware or '未提供'),
                ('电量精度',d.approximate or ('分档电量，非百分比' if d.display_grade else '设备报告值' if d.percent is not None else '未知')),
                ('当前电压',f'{d.voltage_mv} mV' if d.usable and d.voltage_mv is not None else '设备未提供' if d.usable else '暂无有效读数'),
                ('放电速率',estimate.rate_text),('预计剩余',estimate.remaining_text),('估算依据',estimate.reason),
                ('上次有效值',last_text)]

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

    def change_interval(self, seconds):
        if seconds not in REFRESH_INTERVALS:
            return
        self.preferences.set('refresh_seconds', seconds)
        self.refresh_choice.setText(f'{seconds} 秒')
        self.preferencesChanged.emit()

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

    def open_desktop_menu(self):
        from desktop_overlay import add_desktop_actions
        menu = QMenu(self)
        add_desktop_actions(menu, self.preferences, self.set_desktop_option)
        self.open_footer_menu(menu, self.desktop_button)

    def open_refresh_menu(self):
        choices = [(seconds, f'{seconds} 秒') for seconds in REFRESH_INTERVALS]
        self.open_footer_choice(self.refresh_choice, choices,
                                self.preferences.get('refresh_seconds'), self.change_interval)

    def open_theme_menu(self):
        choices = (('system', '跟随系统'), ('light', '浅色'), ('dark', '深色'))
        self.open_footer_choice(self.theme_button, choices, self.preferences.get('theme'), self.set_theme)

    def open_footer_choice(self, button, choices, current, callback):
        from PySide6.QtGui import QActionGroup
        menu = QMenu(self)
        group = QActionGroup(menu)
        for value, title in choices:
            action = menu.addAction(title)
            action.setCheckable(True)
            action.setChecked(value == current)
            action.setData(value)
            group.addAction(action)
        self.open_footer_menu(menu, button, callback)

    def set_theme(self, value):
        self.preferences.set('theme', value)
        self.rebuild(self.devices, self.errors)
        self.preferencesChanged.emit()

    def open_footer_menu(self, menu, button, callback=None):
        self.menu_open = True
        try:
            chosen = menu.exec(button.mapToGlobal(button.rect().topLeft()))
            if chosen is not None and callback is not None:
                callback(chosen.data())
        finally:
            menu.deleteLater()
            self.menu_open = False
            QTimer.singleShot(160, self.hide_if_inactive)

    def set_desktop_option(self,key,value):
        self.preferences.set(key,value);self.preferencesChanged.emit()

    def open_research(self):
        if self.research_controller is None or self.learning is None:
            self.statusline.setText('设备扫描器正在准备，请稍后再试');self.statusline.show();return
        if self.research_dialog is not None:
            self.research_dialog.show();self.research_dialog.raise_();self.research_dialog.activateWindow();return
        from battery_test_ui import BatteryTestPanel
        self.pinned=True;dialog=BatteryTestPanel(self,self.research_controller);self.research_dialog=dialog
        dialog.setStyleSheet(self.styleSheet())
        def closed(*args):
            dialog.dispose();self.research_dialog=None;self.pinned=False;dialog.deleteLater()
        dialog.finished.connect(closed)
        bounds=(self.screen() or QApplication.primaryScreen()).availableGeometry()
        dialog.resize(min(438,bounds.width()-24),min(590,bounds.height()-24))
        x=self.x()-dialog.width()-8
        if x<bounds.left():x=self.x()+self.width()+8
        dialog.move(max(bounds.left()+8,min(x,bounds.right()-dialog.width()-8)),max(bounds.top()+8,min(self.y(),bounds.bottom()-dialog.height()-8)))
        dialog.show();dialog.raise_();dialog.activateWindow()

    def open_learning(self):self.open_research()

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
        if self.update_job:self.cancel_update()
        if self.catalog_dialog:self.catalog_dialog.close()
        if self.research_dialog:self.research_dialog.close()
        if self.learning_dialog:self.learning_dialog.close()
        self.hide()

    def go_back(self):
        self.selected=None;self.back.hide();self.stack.setCurrentIndex(0)
        if self.isVisible():self.resize_for_content()

    def show_at_tray(self,rect=None):
        self.anchor=rect;self.refresh_startup();self.resize_for_content()
        if self.theme!=panel_dark(self.preferences):self.apply_theme()
        self.rebuild(self.devices,self.errors);self.show();self.raise_();self.activateWindow()
        self.setFocus(Qt.FocusReason.OtherFocusReason)

    def resize_for_content(self):
        rect=self.anchor
        screen=QApplication.screenAt(rect.center()) if rect and not rect.isNull() else QApplication.screenAt(QCursor.pos())
        screen=screen or QApplication.primaryScreen();bounds=screen.availableGeometry()
        width = max(1, min(PANEL_WIDTH, bounds.width() - 24))
        height = min(self.content_height(width), max(1, bounds.height() - 20))
        if self.width()!=width or self.height()!=height:self.setFixedSize(width,height)
        x=rect.center().x()-self.width()//2 if rect and not rect.isNull() else bounds.right()-self.width()-12
        y=bounds.bottom()-self.height()-10
        if rect and not rect.isNull() and rect.center().y()<bounds.top()+50:y=bounds.top()+10
        x=max(bounds.left()+8,min(x,bounds.right()-self.width()-8))
        if self.x()!=x or self.y()!=y:self.move(x,y)
        self.position_update_badge()

    def content_height(self, width):
        chrome = self.root.totalHeightForWidth(width)
        if chrome < 0:
            chrome = self.root.totalSizeHint().height()

        page = self.stack.currentWidget()
        body = page.widget()
        if body is None:
            return chrome

        outer = self.root.contentsMargins()
        stack = self.stack.contentsMargins()
        frame = 2 * page.frameWidth()
        body_width = max(1, width - outer.left() - outer.right()
                         - stack.left() - stack.right() - frame)
        layout = body.layout()
        body_height = layout.totalHeightForWidth(body_width)
        if body_height < 0:
            body_height = layout.totalSizeHint().height()
        body_height = max(body_height, body.minimumSizeHint().height())
        if (page.horizontalScrollBarPolicy() != Qt.ScrollBarPolicy.ScrollBarAlwaysOff
                and body.minimumSizeHint().width() > body_width):
            body_height += page.horizontalScrollBar().sizeHint().height()
        return chrome + frame + stack.top() + stack.bottom() + body_height

    def event(self, event):
        result = super().event(event)
        if event.type() == QEvent.Type.LayoutRequest and self.isVisible():
            self.resize_for_content()
        return result

    def keyPressEvent(self,e):
        if e.key()==Qt.Key.Key_Escape:
            self.go_back() if self.selected else self.hide()
        else:super().keyPressEvent(e)

    def changeEvent(self,e):
        if e.type()==QEvent.Type.ActivationChange and not self.isActiveWindow() and not self.pinned and not self.menu_open:
            QTimer.singleShot(160,self.hide_if_inactive)
        super().changeEvent(e)

    def hide_if_inactive(self):
        if not self.isActiveWindow() and not self.pinned and not self.menu_open:self.hide()

    def closeEvent(self,e):e.ignore();self.hide()
