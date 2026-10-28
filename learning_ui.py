"""A small modeless monitor; only an explicit click enables candidate readings."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog,QVBoxLayout,QLabel,QProgressBar,QComboBox,QPlainTextEdit,QPushButton,QHBoxLayout
from long_learning import analyze,save_mapping,mappings,mapping_path
from settings import atomic_json


class LearningPanel(QDialog):
    def __init__(self,controller,refresh,parent=None):
        super().__init__(parent,Qt.WindowType.Tool);self.controller=controller;self.refresh_devices=refresh
        self.setWindowTitle('长时间电量观察 · 实验');self.resize(420,480)
        layout=QVBoxLayout(self);self.title=QLabel();self.title.setWordWrap(True);layout.addWidget(self.title)
        self.progress=QProgressBar();self.progress.setRange(0,100);layout.addWidget(self.progress)
        self.note=QLabel();self.note.setWordWrap(True);layout.addWidget(self.note)
        self.candidates=QComboBox();layout.addWidget(self.candidates)
        self.details=QPlainTextEdit();self.details.setReadOnly(True);layout.addWidget(self.details,1)
        self.apply=QPushButton('确认并启用所选实验读数');self.apply.clicked.connect(self.enable);layout.addWidget(self.apply)
        self.remove=QPushButton('停用本设备的实验读数');self.remove.clicked.connect(self.disable);layout.addWidget(self.remove)
        row=QHBoxLayout();layout.addLayout(row)
        self.resume=QPushButton('继续观察');self.resume.clicked.connect(self.continue_session);row.addWidget(self.resume)
        self.stop=QPushButton('结束观察');self.stop.clicked.connect(controller.cancel);row.addWidget(self.stop)
        close=QPushButton('收起');close.clicked.connect(self.close);row.addWidget(close)
        controller.changed.connect(self.update_state);self.update_state()

    def update_state(self):
        s=self.controller.session;state=s.get('state','');elapsed=s.get('elapsed_seconds',0);target=s.get('target_seconds',3600)
        self.title.setText((s.get('name') or '尚未开始观察')+f'\n有效观察 {int(elapsed/60)} / {int(target/60)} 分钟 · {len(s.get("usage",[]))} 个样本')
        self.progress.setValue(min(100,int(elapsed/target*100)))
        self.note.setText(s.get('message','先完成初始与插线采样，再选择 1 或 2 小时观察。')+'\n关闭面板可继续；结束观察会停止采样。')
        old=self.candidates.currentData();self.candidates.clear()
        result=analyze(s.get('before',[]),s.get('charged',[]),s.get('usage',[]))
        for c in result['candidates']:
            self.candidates.addItem(f'偏移 {c["offset"]} · {c["current"]}% · 下降 {c["drop"]} · 置信度 {c["confidence"]}',c)
        if old:
            for i in range(self.candidates.count()):
                if self.candidates.itemData(i)['offset']==old['offset']:self.candidates.setCurrentIndex(i);break
        self.apply.setEnabled(state=='completed' and bool(result['candidates']) and s.get('before',[{}])[0].get('backend')=='feature-get')
        self.resume.setText('再观察 1 小时' if state=='completed' else '继续观察')
        self.resume.setEnabled(state=='paused' or state=='completed' and target==3600);self.stop.setEnabled(state in ('observing','awaiting_unplug','paused'))
        self.remove.setEnabled(s.get('identity') in mappings())
        lines=[result['note'],'候选启用后在主界面标注“实验推测”；不参与最低电量和提醒。',
            '没有独立电量旁证时，慢速计数器仍可能被误选。']
        usage=s.get('usage',[])
        if usage:lines+=['\n最近状态报告：',usage[-1]['hex']]
        self.details.setPlainText('\n'.join(lines))

    def continue_session(self):
        if self.controller.session.get('state')=='completed':self.controller.extend()
        else:self.controller.resume()

    def enable(self):
        candidate=self.candidates.currentData()
        if not candidate:return
        try:save_mapping(self.controller.session,candidate);self.refresh_devices();self.update_state();self.note.setText('已启用实验推测读数。可随时停用，数值尚未得到独立验证。')
        except (ValueError,OSError) as error:self.note.setText(str(error))

    def disable(self):
        data=mappings();data.pop(self.controller.session.get('identity'),None)
        try:atomic_json(mapping_path(),data);self.refresh_devices();self.update_state()
        except OSError as error:self.note.setText(str(error))
