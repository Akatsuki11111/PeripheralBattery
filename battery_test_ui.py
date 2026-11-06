"""One device, one panel: verified read, paired samples, observation and review."""
import time
from PySide6.QtCore import Qt,QTimer
from PySide6.QtWidgets import (QDialog,QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,
    QComboBox,QCheckBox,QProgressBar,QPlainTextEdit,QStackedWidget,QToolButton,QScrollArea,QFrame,QSizePolicy)
from research_ui import ResearchDrawer
from long_learning import analyze,save_mapping,mappings,mapping_path
from settings import atomic_json
from icons import font


class BatteryTestPanel(ResearchDrawer):
    def __init__(self,flyout,controller):
        # Keep the bounded sampling engine; replace its separate dialog flows.
        QDialog.__init__(self,flyout,Qt.WindowType.Tool)
        self.flyout=flyout;self.controller=controller;self.learning=flyout.learning
        self.setWindowTitle('电量测试');self.resize(438,590)
        self.stage=0;self.generation=0;self.job=None;self.before=[];self.after=[]
        self.poll_count=0;self.deadline=0;self.identity='';self.result=None;self.candidate=0
        self.channel=None;self.owns_scanner=False;self.last_failure=None
        self.rejected={v for v in (self.learning.session.get('rejected_offsets',[]) if self.learning else []) if type(v) is int and 0<v<256}
        self.timer=QTimer(self);self.timer.setSingleShot(True);self.timer.timeout.connect(self.take_sample)
        self.clock=QTimer(self);self.clock.setInterval(200);self.clock.timeout.connect(self.update_wait)
        self.clock.start();self.setFont(font(12))
        root=QVBoxLayout(self);root.setContentsMargins(18,16,18,14);root.setSpacing(10)
        title=QLabel('电量测试');title.setFont(font(18));root.addWidget(title)
        sub=QLabel('先验证可读性，再采样；有依据时才显示电量。');sub.setWordWrap(True);root.addWidget(sub)
        rail=QHBoxLayout();self.steps=[]
        for name in ('设备','预检','拔线采样','插线采样','结果 / 观察'):
            step=QLabel(name);step.setAlignment(Qt.AlignmentFlag.AlignCenter);step.setFont(font(11));rail.addWidget(step);self.steps.append(step)
        root.addLayout(rail)
        self.pages=QStackedWidget();scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff);scroll.setWidget(self.pages);root.addWidget(scroll,1)
        short=QWidget();layout=QVBoxLayout(short);layout.setContentsMargins(0,0,0,0);layout.setSpacing(9)
        self.heading=QLabel();self.heading.setFont(font(14));self.heading.setWordWrap(True);layout.addWidget(self.heading)
        self.text=QLabel();self.text.setWordWrap(True);layout.addWidget(self.text)
        self.choices=QComboBox();self.choices.setMinimumHeight(30);layout.addWidget(self.choices)
        self.include_supported=QCheckBox('也验证已有有效电量的设备');layout.addWidget(self.include_supported)
        self.include_supported.toggled.connect(self.fill_devices)
        self.disable_existing=QPushButton('停用所选设备的推测值');self.disable_existing.clicked.connect(self.disable_existing_mapping);layout.addWidget(self.disable_existing)
        self.unplug_ack=QCheckBox('已拔掉充电线，设备已开机且能正常使用');layout.addWidget(self.unplug_ack)
        self.unplug_ack.toggled.connect(lambda:self.render())
        self.progress=QProgressBar();layout.addWidget(self.progress)
        self.wait_label=QLabel();self.wait_label.setWordWrap(True);layout.addWidget(self.wait_label)
        self.summary=QLabel();self.summary.setWordWrap(True);layout.addWidget(self.summary)
        self.technical=QToolButton();self.technical.setText('查看接口与原始证据');self.technical.setCheckable(True)
        self.technical.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon);layout.addWidget(self.technical)
        self.details=QPlainTextEdit();self.details.setReadOnly(True);self.details.setFont(font(11));layout.addWidget(self.details,1)
        self.technical.toggled.connect(lambda on:self.details.setVisible(on))
        self.diagnostic_button=QPushButton('导出设备诊断');self.diagnostic_button.clicked.connect(self.export_diagnostic);layout.addWidget(self.diagnostic_button)
        self.long_box=QWidget();long_layout=QVBoxLayout(self.long_box);long_layout.setContentsMargins(0,0,0,0)
        self.duration=QComboBox();self.duration.addItem('继续观察 1 小时',1);self.duration.addItem('继续观察 2 小时',2);long_layout.addWidget(self.duration)
        self.long_ack=QCheckBox('已重新拔线，接下来正常使用设备');long_layout.addWidget(self.long_ack)
        self.long_ack.toggled.connect(lambda:self.render())
        self.long_button=QPushButton('开始后台观察');self.long_button.clicked.connect(self.start_long);long_layout.addWidget(self.long_button)
        layout.addWidget(self.long_box)
        row=QHBoxLayout();layout.addLayout(row)
        self.back=QPushButton('上一步');self.back.clicked.connect(self.previous);row.addWidget(self.back)
        self.reject_button=QPushButton('下一个线索');self.reject_button.clicked.connect(self.next_candidate);row.addWidget(self.reject_button)
        self.next=QPushButton();self.next.clicked.connect(self.advance);row.addWidget(self.next)
        self.pages.addWidget(short)
        monitor=QWidget();observe=QVBoxLayout(monitor);observe.setContentsMargins(0,0,0,0);observe.setSpacing(10)
        self.observation_title=QLabel();self.observation_title.setFont(font(14));self.observation_title.setWordWrap(True);observe.addWidget(self.observation_title)
        self.observation_progress=QProgressBar();observe.addWidget(self.observation_progress)
        self.observation_note=QLabel();self.observation_note.setWordWrap(True);observe.addWidget(self.observation_note)
        self.resume_ack=QCheckBox('已确认拔线，设备正通过无线连接使用');observe.addWidget(self.resume_ack)
        self.candidates=QComboBox();self.candidates.currentIndexChanged.connect(self.choose_candidate);observe.addWidget(self.candidates)
        self.review_note=QLabel();self.review_note.setWordWrap(True);observe.addWidget(self.review_note)
        self.review_ack=QCheckBox('我理解这仍是推测，并确认尝试当前候选');self.review_ack.toggled.connect(self.review_changed);observe.addWidget(self.review_ack)
        review_row=QHBoxLayout();observe.addLayout(review_row)
        self.reject_candidate=QPushButton('不符合，下一候选');self.reject_candidate.clicked.connect(self.reject_observation);review_row.addWidget(self.reject_candidate)
        self.apply_candidate=QPushButton('确认并显示推测值');self.apply_candidate.clicked.connect(self.enable_candidate);review_row.addWidget(self.apply_candidate)
        self.observation_details=QLabel();self.observation_details.setWordWrap(True);observe.addWidget(self.observation_details);observe.addStretch()
        self.remove_mapping=QPushButton('停用此设备的推测值');self.remove_mapping.clicked.connect(self.disable_candidate);observe.addWidget(self.remove_mapping)
        actions=QHBoxLayout();observe.addLayout(actions)
        self.pause_button=QPushButton('暂停');self.pause_button.clicked.connect(self.pause_observation);actions.addWidget(self.pause_button)
        self.resume_button=QPushButton('继续观察');self.resume_button.clicked.connect(self.resume_observation);actions.addWidget(self.resume_button)
        self.reset_button=QPushButton('结束并重新选择');self.reset_button.clicked.connect(self.new_test);observe.addWidget(self.reset_button)
        self.pages.addWidget(monitor)
        self.cancel=QPushButton('收起');self.cancel.clicked.connect(self.close);root.addWidget(self.cancel)
        self.footer=QLabel('采样仅保存在本机。短时测试收起会停止；后台观察收起后继续。')
        self.footer.setFont(font(10));self.footer.setWordWrap(True);root.addWidget(self.footer)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        for text in self.findChildren(QLabel):text.setSizePolicy(QSizePolicy.Policy.Preferred,QSizePolicy.Policy.Maximum)
        for button in self.findChildren(QPushButton):
            button.setAutoDefault(False);button.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.choices.currentIndexChanged.connect(self.show_topology);self.choices.currentIndexChanged.connect(lambda:self.render());self.fill_devices()
        if self.learning:self.learning.changed.connect(self.observation_changed)
        if self.learning and self.learning.session.get('state') in ('observing','awaiting_unplug','paused','completed'):
            self.pages.setCurrentIndex(1);self.observation_changed()
        else:self.render();self.show_topology()

    def set_step(self,index):
        for i,step in enumerate(self.steps):
            step.setStyleSheet('padding:6px 2px;border-radius:4px;'+('background:#0067c0;color:white;' if i==index else 'background:rgba(128,128,128,0.12);'))

    def fill_devices(self):
        if hasattr(self,'pages') and self.pages.currentIndex()==1:return
        super().fill_devices()

    def render(self,message=''):
        if not hasattr(self,'pages'):return
        titles=['选择一台设备','先检查设备是否应答','拔线状态 · 采样三次','现在插上充电线','插线状态 · 采样三次','采样结果','已获取有效电量']
        descriptions=['默认列出尚无有效电量的设备，包括连接待确认的接收器。',
          '先拔掉充电线并唤醒设备。预检无应答会停止，不进入长时间等待。',
          '锁定同一接口，间隔采样；不稳定字段会单独排除。',
          '已知充电标志会自动检测。未知报告只能记录你的插线操作，不能据此证明充电。',
          '保持插线，采集同一报告，与拔线组逐字段比较。',
          '插拔变化不等于电量。短样本证据不足时，可继续后台观察。',
          '可靠协议已提供读数，无需再等待或猜测字段。']
        self.set_step({0:0,1:1,2:2,3:3,4:3,5:4,6:4}.get(self.stage,0))
        self.heading.setText(titles[self.stage]);self.text.setText(message or descriptions[self.stage])
        self.choices.setVisible(self.stage==0);self.include_supported.setVisible(self.stage==0)
        self.disable_existing.setVisible(self.stage==0 and self.choices.currentData() in mappings())
        self.unplug_ack.setVisible(self.stage==1);self.progress.setVisible(self.job is not None or self.stage in (2,3,4))
        self.back.setEnabled(self.stage>0);self.reject_button.setVisible(self.stage==5 and bool(self.result and self.result['stable_changed']))
        self.next.setText({0:'下一步',1:'开始预检',2:'采样三次',3:'我已插线',4:'开始采样',5:'保存本机证据',6:'再次验证'}[self.stage])
        self.next.setEnabled(self.job is None and (self.stage!=0 or self.choices.count()>0) and (self.stage!=1 or self.unplug_ack.isChecked()))
        self.diagnostic_button.setEnabled(self.job is None and bool(self.identity if self.stage else self.choices.currentData()))
        self.long_box.setVisible(self.stage==5)
        eligible=self.stage==5 and len(self.before)==len(self.after)==3 and all(s.get('backend')=='feature-get' for s in self.before+self.after)
        self.long_button.setEnabled(bool(eligible and self.long_ack.isChecked()))
        self.summary.setVisible(self.stage==5)
        if self.stage==5 and self.result:
            self.summary.setText(f'插拔变化：{len(self.result["stable_changed"])} 项 · 不稳定偏移：{len(self.result["unstable_offsets"])} 项\n'
                '短时线索不会自动变成电量。观察满 1 小时且数值实际下降，才可能得到候选。')
        self.details.setVisible(self.technical.isChecked())
        if self.stage==0 and not self.choices.count():self.text.setText('暂无待测试设备。可勾选验证已有有效电量的设备，或唤醒休眠的设备后刷新。')
        self.cancel.setText('取消并关闭' if self.job else '收起')

    def advance(self):
        if self.stage==1 and not self.unplug_ack.isChecked():return
        if self.learning and self.learning.session.get('state') in ('observing','awaiting_unplug','paused'):
            self.pages.setCurrentIndex(1);self.observation_changed();return
        previous=self.stage;super().advance()
        if previous==3 and self.stage==4 and self.before and self.before[0].get('charging') is None:super().advance()

    def previous(self):
        super().previous();self.long_ack.setChecked(False)
        if self.stage<=1:self.unplug_ack.setChecked(False)

    def take_sample(self):
        super().take_sample()
        if self.job:self.job_at=time.monotonic();self.back.setEnabled(True);self.cancel.setText('取消并关闭')

    def update_wait(self):
        busy=self.job is not None
        self.wait_label.setVisible(busy)
        if busy:self.wait_label.setText(f'正在读取状态 · {max(0,int(time.monotonic()-getattr(self,"job_at",time.monotonic())))} 秒；超时自动停止，可返回或取消。')

    def completed(self,job,result,generation,stage):
        s=result.get('sample',{})
        if (generation==self.generation and stage==self.stage==1 and result.get('ok') and s.get('remote_confirmed')
                and (s.get('percent') is not None or s.get('battery_grade'))):
            self.job=None;self.release_scanner();self.stage=6
            reading=f'{s["percent"]}%' if s.get('percent') is not None else s['battery_grade']+'（分档）'
            if s.get('hex'):
                self.details.setPlainText(f"{s['length']} 字节 · {s.get('backend','已验证状态报告')}\n{s['hex']}")
            self.render(f'已读取 {s.get("name","设备")}：{reading}。'+s.get('protocol_note',''))
            self.flyout.refreshRequested.emit();return
        super().completed(job,result,generation,stage)

    def start_long(self):
        if not self.long_ack.isChecked() or not self.learning:return
        try:self.learning.start(self.identity,self.before,self.after,self.duration.currentData(),unplug_confirmed=True)
        except ValueError as error:self.render(str(error));return
        self.pages.setCurrentIndex(1);self.observation_changed()

    def observation_changed(self):
        if not self.learning:return
        s=self.learning.session;state=s.get('state','');target=max(1,s.get('target_seconds',3600));elapsed=s.get('elapsed_seconds',0)
        self.set_step(4);self.observation_title.setText((s.get('name') or '电量观察')+f'\n有效采样 {int(elapsed/60)} / {int(target/60)} 分钟 · {len(s.get("usage",[]))} 个样本')
        self.observation_progress.setValue(min(100,int(elapsed/target*100)))
        self.observation_note.setText(s.get('message','')+'\n每分钟采样一次；关闭面板继续，重启程序后先暂停。')
        old=self.candidates.currentData();self.candidates.blockSignals(True);self.candidates.clear()
        analysis=analyze(s.get('before',[]),s.get('charged',[]),s.get('usage',[]))
        for candidate in analysis['candidates']:
            if candidate['offset'] not in self.rejected:self.candidates.addItem(f'偏移 {candidate["offset"]} · {candidate["current"]}% · 置信度 {candidate["confidence"]}',candidate)
        if old:
            for i in range(self.candidates.count()):
                if self.candidates.itemData(i)['offset']==old['offset']:self.candidates.setCurrentIndex(i);break
        self.candidates.blockSignals(False)
        self.observation_details.setText(analysis['note']+f'\n最长连续观察：{analysis["valid_minutes"]} 分钟。分段间隔不作为连续变化证据。')
        self.pause_button.setEnabled(state in ('observing','awaiting_unplug'))
        self.resume_button.setEnabled(state=='paused' or state=='completed' and target==3600 or state=='awaiting_unplug')
        self.resume_button.setText('再观察 1 小时' if state=='completed' else '确认拔线并继续')
        self.resume_ack.setVisible(state in ('paused','awaiting_unplug') and s.get('before',[{}])[0].get('charging') is None)
        self.pause_button.setVisible(state in ('observing','awaiting_unplug','paused'))
        self.remove_mapping.setVisible(s.get('identity') in mappings())
        if self.candidates.currentData()!=old:self.review_ack.setChecked(False)
        self.remove_mapping.setEnabled(s.get('identity') in mappings());self.review_changed()

    def choose_candidate(self):
        self.review_ack.setChecked(False);self.review_changed()

    def review_changed(self):
        s=self.learning.session if self.learning else {};candidate=self.candidates.currentData()
        self.review_note.setText(f'当前候选下降 {candidate["drop"]}%、变化 {candidate["changes"]} 次；仍可能是计数器。' if candidate else '尚无可用电量候选。可继续观察或结束；不会自动启用。')
        self.apply_candidate.setEnabled(bool(s.get('state')=='completed' and candidate and self.review_ack.isChecked()))
        self.reject_candidate.setEnabled(bool(candidate));self.review_ack.setVisible(bool(candidate))

    def reject_observation(self):
        c=self.candidates.currentData()
        if c:
            self.rejected.add(c['offset']);self.review_ack.setChecked(False)
            self.learning.session['rejected_offsets']=sorted(self.rejected);self.learning.save()

    def enable_candidate(self):
        if not self.apply_candidate.isEnabled():return
        try:save_mapping(self.learning.session,self.candidates.currentData());self.flyout.refreshRequested.emit();self.observation_changed();self.observation_note.setText('已启用推测值，主界面仍标注推测；不参与最低电量和提醒。')
        except (ValueError,OSError) as error:self.observation_note.setText(str(error))

    def disable_candidate(self):
        data=mappings();data.pop(self.learning.session.get('identity'),None)
        try:atomic_json(mapping_path(),data);self.flyout.refreshRequested.emit();self.observation_changed()
        except OSError as error:self.observation_note.setText(str(error))

    def disable_existing_mapping(self):
        data=mappings();data.pop(self.choices.currentData(),None)
        try:atomic_json(mapping_path(),data);self.flyout.refreshRequested.emit();self.render('已停用所选设备的推测值，可以重新测试。')
        except OSError as error:self.render(str(error))

    def pause_observation(self):self.learning.pause();self.resume_ack.setChecked(False);self.observation_changed()

    def resume_observation(self):
        s=self.learning.session
        if s.get('state')=='completed':
            self.learning.extend();self.resume_ack.setChecked(False);self.observation_changed();return
        if s.get('before',[{}])[0].get('charging') is None and not self.resume_ack.isChecked():
            self.observation_note.setText('未知报告不能自动确认拔线，请先勾选无线使用确认。');return
        if s.get('state')=='paused':self.learning.resume()
        self.learning.confirm_unplugged();self.observation_changed()

    def new_test(self):
        self.learning.cancel();self.halt();self.stage=0;self.before=[];self.after=[];self.result=None
        self.rejected.clear();self.unplug_ack.setChecked(False);self.long_ack.setChecked(False);self.review_ack.setChecked(False)
        self.pages.setCurrentIndex(0);self.fill_devices();self.render()

    def dispose(self):
        self.halt();self.clock.stop()
        if self.learning:
            try:self.learning.changed.disconnect(self.observation_changed)
            except (RuntimeError,TypeError):pass

    def showEvent(self,event):
        super().showEvent(event);self.setFocus(Qt.FocusReason.OtherFocusReason)
