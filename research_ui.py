"""Nonmodal, bounded guided research for verified status channels."""
import time
from PySide6.QtCore import Qt,QTimer
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QComboBox,QProgressBar,QPlainTextEdit,QCheckBox,QFileDialog)
from jobs import WorkerJob
from research import compare,research_devices
from settings import atomic_json,data_dir,read_json,VERSION
import json

class ResearchDrawer(QDialog):
 def __init__(self,flyout,controller):
  super().__init__(flyout,Qt.WindowType.Tool)
  self.flyout=flyout;self.controller=controller;self.setWindowTitle('电量适配 · 分步检查');self.resize(410,510)
  self.stage=0;self.generation=0;self.job=None;self.before=[];self.after=[];self.poll_count=0;self.deadline=0;self.identity='';self.result=None;self.candidate=0;self.channel=None;self.owns_scanner=False
  self.timer=QTimer(self);self.timer.setSingleShot(True);self.timer.timeout.connect(self.take_sample)
  self.last_failure=None
  layout=QVBoxLayout(self);self.heading=QLabel();self.heading.setWordWrap(True);layout.addWidget(self.heading)
  self.text=QLabel();self.text.setWordWrap(True);layout.addWidget(self.text)
  self.choices=QComboBox();layout.addWidget(self.choices)
  self.include_supported=QCheckBox('显示在线的已适配设备（仅用于验证实验）');layout.addWidget(self.include_supported)
  self.include_supported.toggled.connect(lambda:self.fill_devices())
  self.progress=QProgressBar();self.progress.setRange(0,3);layout.addWidget(self.progress)
  self.details=QPlainTextEdit();self.details.setReadOnly(True);layout.addWidget(self.details,1)
  self.diagnostic_button=QPushButton('导出所选设备诊断');self.diagnostic_button.clicked.connect(self.export_diagnostic);layout.addWidget(self.diagnostic_button)
  self.duration=QComboBox();self.duration.addItem('后台观察 1 小时',1);self.duration.addItem('后台观察 2 小时',2);layout.addWidget(self.duration)
  self.long_button=QPushButton('我已拔线，开始后台观察');self.long_button.clicked.connect(self.start_long);layout.addWidget(self.long_button)
  row=QHBoxLayout();self.back=QPushButton('上一步');self.next=QPushButton('继续');self.reject_button=QPushButton('下一个候选');self.cancel=QPushButton('取消 / 关闭')
  for button in (self.back,self.next,self.reject_button,self.cancel):row.addWidget(button)
  layout.addLayout(row);self.back.clicked.connect(self.previous);self.next.clicked.connect(self.advance);self.reject_button.clicked.connect(self.next_candidate);self.cancel.clicked.connect(self.close)
  self.fill_devices();self.choices.currentIndexChanged.connect(self.show_topology);self.render();self.show_topology()
 def fill_devices(self):
  self.choices.clear();snapshot={d.identity:d for d in research_devices(self.flyout.devices,self.include_supported.isChecked())}
  for group in self.controller.inventory:
   d=snapshot.get(group['device'].get('identity'))
   if d:self.choices.addItem(f'{d.brand if d.brand!="Unknown" else "品牌待识别"} · {d.name}  {d.vid:04X}:{d.pid:04X}',d.identity)
  if hasattr(self,'next'):self.render();self.show_topology()
 def show_topology(self):
  if self.stage!=0:return
  from identity import metadata,instance_from_path
  identity=self.choices.currentData()
  group=next((g for g in self.controller.inventory if g['device'].get('identity')==identity),None)
  if not group:self.details.clear();return
  device=group['device'];lines=[f'型号：{device["name"]}  ·  VID:PID {device["vid"]:04X}:{device["pid"]:04X}',
    'USB 端点数量：未取得；以下为已枚举的 HID 集合。设备路径仅在本窗口显示。']
  for raw in group.get('infos',[])[:16]:
   try:
    from inventory import decode_info
    info=decode_info(raw);path=info.get('path',b'');meta=metadata(path)
    lines.append(f'接口 {info.get("interface_number",-1)} · usage {info.get("usage_page",0):04X}:{info.get("usage",0):04X}')
    lines.append('实例：'+(instance_from_path(path) or '未知'))
    lines.append('物理父节点：'+(meta.get('physical') or '未知')+'\n容器 ID：'+(meta.get('container') or '未知'))
   except (TypeError,ValueError):lines.append('部分接口信息不可用。')
  self.details.setPlainText('\n'.join(lines))
 def render(self,message=''):
  titles=['选择设备','拔电前置检查','拔电采样','插电并等待','插电采样','差分结果']
  descriptions=[
   '列出尚未适配的设备；已适配但关机或休眠的设备不属于待适配。未知报告仅使用描述符声明的 Feature GET。',
   '拔掉设备充电线并保持设备开机。先检查状态接口；未知报告有应答也不代表远端在线，需你确认设备正在使用。',
   '按同一接口采集 3 份状态报告，用于排查数据抖动。',
   '现在插上充电线；程序会等待已知协议中的充电标志翻转，最多约 45 秒。',
   '充电状态已确认，采集 3 份同一接口状态报告。',
   '以下差分只是低置信度线索。点击“保存证据”仅保存在本机，不会自动用于显示电量。']
  titles.append('专用协议验证完成');descriptions.append('已从设备专用状态查询获得电量，不再通过插拔差分猜测字段；可以关闭窗口或再次查询。')
  self.heading.setText('已完成 · 专用协议验证' if self.stage==6 else f'第 {self.stage+1} / 6 步 · {titles[self.stage]}')
  manual=bool(self.before and self.before[0].get('charging') is None)
  if self.stage==3 and manual:descriptions[3]='现在插上充电线，再点击“我已插线”。未知 Feature 报告没有已验证的充电标志，本阶段由你的操作标注。'
  self.text.setText(message or descriptions[self.stage]);self.choices.setVisible(self.stage==0);self.include_supported.setVisible(self.stage==0)
  self.duration.setVisible(self.stage==5);self.long_button.setVisible(self.stage==5)
  self.diagnostic_button.setEnabled(self.job is None and bool(self.identity if self.stage else self.choices.currentData()))
  self.progress.setVisible(self.stage in (2,3,4));self.back.setEnabled(self.stage>0 and self.job is None)
  self.next.setEnabled(self.job is None and (self.stage!=0 or self.choices.count()>0))
  self.next.setText('再次查询' if self.stage==6 else '保存证据' if self.stage==5 else '开始检查' if self.stage==1 else '开始采样' if self.stage in (2,4) else '开始等待' if self.stage==3 else '继续')
  if self.stage==3 and manual:self.next.setText('我已插线')
  self.reject_button.setVisible(self.stage==5);self.reject_button.setEnabled(bool(self.result and self.result['stable_changed']))
  if self.stage==0 and not self.choices.count():self.text.setText('目前没有待适配设备。已适配设备休眠或关闭不会进入这个清单。')
 def release_scanner(self):
  if self.owns_scanner:self.controller.research_active=False;self.owns_scanner=False
 def halt(self):
  self.generation+=1;self.timer.stop()
  if self.job:
   job=self.job;self.job=None;job.cancel()
  self.release_scanner()
 def previous(self):
  self.halt();self.stage=0 if self.stage==6 else max(0,self.stage-1)
  if self.stage<=1:self.before=[];self.after=[]
  elif self.stage<=3:self.after=[]
  self.details.clear();self.render()
  if self.stage==0:self.show_topology()
 def advance(self):
  if self.stage==6:self.stage=1
  if self.stage==0:
   self.identity=self.choices.currentData() or '';self.channel=None;self.last_failure=None;self.stage=1;self.details.clear();self.render();return
  if self.stage==5:self.save();return
  if self.stage==3 and self.before and self.before[0].get('charging') is None:
   self.stage=4;self.render('已记录你确认插线；接下来采样。');return
  if self.controller.busy or self.controller.research_active and not self.owns_scanner:
   self.render('设备刷新尚未结束，请稍后再试。');return
  if not self.identity:return
  self.controller.research_active=True;self.owns_scanner=True;self.generation+=1;self.progress.setValue(0);self.poll_count=0;self.deadline=time.monotonic()+45
  if self.stage==2:self.before=[]
  if self.stage==4:self.after=[]
  self.take_sample()
 def take_sample(self):
  if self.job or self.stage not in (1,2,3,4):return
  generation=self.generation;stage=self.stage
  self.progress.setRange(0,45 if stage==3 else 3 if stage in (2,4) else 1)
  self.next.setEnabled(False);self.back.setEnabled(False)
  self.diagnostic_button.setEnabled(False)
  self.text.setText('正在检查可读取的状态报告，超时会自动停止；可以随时取消。')
  job=WorkerJob({'operation':'research-sample','identity':self.identity,'channel':self.channel},6500,self);self.job=job
  job.finished.connect(lambda result:self.completed(job,result,generation,stage));job.start()
 def completed(self,job,result,generation,stage):
  if self.job is job:self.job=None
  if generation!=self.generation or stage!=self.stage:return
  if not result.get('ok'):
   self.last_failure={k:result.get(k) for k in ('error_code','feature_diagnostics','user_message','error') if result.get(k) is not None}
   self.release_scanner();self.render('预检已停止：'+str(result.get('user_message',result.get('error','设备没有应答'))))
   if result.get('feature_diagnostics'):self.details.setPlainText(json.dumps(result['feature_diagnostics'],ensure_ascii=False,indent=2))
   return
  s=result['sample'];self.details.appendPlainText(time.strftime('%H:%M:%S',time.localtime(s['timestamp']))+' · '+str(s['length'])+' 字节\n'+s['hex'])
  if self.channel is None:self.channel=s.get('channel')
  if stage==1:
   self.release_scanner()
   if s.get('protocol_verified') and s.get('remote_confirmed') and s.get('percent') is not None:
    self.stage=6;self.progress.hide();self.render(f'已验证 {s["name"]}：{s["percent"]}%。'+s.get('protocol_note',''))
    self.flyout.refreshRequested.emit();return
   if s['charging'] is True:self.render('设备报告仍在充电，请拔掉充电线后重试。');return
   self.stage=2;self.render('接口已返回应答，可以开始拔电采样。未知报告尚不能证明远端在线或充电状态。' if s['charging'] is None else '已确认在线且当前未充电；可以开始拔电采样。');return
  if stage==2:
   if s['charging'] is True:self.release_scanner();self.render('采样时充电状态改变，请重新采样。');return
   self.before.append(s);count=len(self.before)
  elif stage==3:
   self.poll_count+=1;self.progress.setValue(min(45,max(0,int(45-(self.deadline-time.monotonic())))))
   if s['charging'] is True:
    self.release_scanner();self.stage=4;self.render('已从已知状态应答确认充电标志翻转。');return
   if time.monotonic()>=self.deadline:
    self.release_scanner();self.render('等待超时：没有检测到充电标志，可重试或返回。');return
   self.text.setText(f'等待充电状态变化，已检查 {self.poll_count} 次；可以取消。');self.timer.start(1500);return
  else:
   if s['charging'] is False:self.release_scanner();self.render('充电状态未保持，请检查充电线后重试。');return
   self.after.append(s);count=len(self.after)
  self.progress.setValue(count)
  if count<3:self.text.setText(f'已收到 {count} / 3 包；正在等待下一次采样。');self.timer.start(1500);return
  self.release_scanner()
  if stage==2:self.stage=3;self.render('拔电采样完成，接下来等待插电。');return
  try:self.result=compare(self.before,self.after)
  except ValueError as error:self.render('无法比较：'+str(error));return
  self.stage=5;self.candidate=0;self.show_results()
 def show_results(self):
  r=self.result;items=r['stable_changed'];lines=[]
  if items:
   c=items[self.candidate%len(items)];lines.append(f'变化候选 {self.candidate%len(items)+1}/{len(items)}：偏移 {c["offset"]}，变化掩码 0x{c["mask"]:02X}，{c["before"]} → {c["after"]}；置信度：低。')
  else:lines.append('没有稳定的插拔变化候选。')
  lines.append('不稳定偏移：'+(', '.join(map(str,r['unstable_offsets'])) or '无'))
  lines.append('电量候选：'+(', '.join(str(x['offset']) for x in r['battery_candidates']) or '未发现（短时间电量通常不会增长）'))
  lines.append(r['note']);lines.append('\n拔电原始包：')
  lines.extend(s['hex'] for s in self.before);lines.append('\n插电原始包：');lines.extend(s['hex'] for s in self.after)
  self.details.setPlainText('\n'.join(lines));self.render()
 def next_candidate(self):self.candidate+=1;self.show_results()
 def export_diagnostic(self):
  identity=self.choices.currentData() if self.stage==0 else self.identity
  if not identity:return
  if self.controller.busy or self.controller.research_active and not self.owns_scanner:
   self.render('后台查询尚未结束，请稍后导出。');return
  self.halt();self.controller.research_active=True;self.owns_scanner=True;generation=self.generation
  self.next.setEnabled(False);self.back.setEnabled(False);self.diagnostic_button.setEnabled(False)
  self.text.setText('正在读取所选设备的身份与接口描述；不读取键鼠输入。')
  job=WorkerJob({'operation':'research-inspect','identity':identity},9000,self);self.job=job
  job.finished.connect(lambda result:self.diagnostic_ready(job,result,generation));job.start()
 def diagnostic_ready(self,job,result,generation):
  if self.job is job:self.job=None
  if generation!=self.generation:return
  self.release_scanner();self.render()
  if not result.get('ok'):self.render('诊断失败：'+str(result.get('user_message',result.get('error','未知错误'))));return
  payload={k:result[k] for k in ('device','backend','interfaces','feature_diagnostics','valkyrie_candidates','scope')}
  payload.update(version=VERSION,precheck_failure=self.last_failure)
  self.flyout.menu_open=True
  try:path,_=QFileDialog.getSaveFileName(self,'导出设备诊断','Peripheral-HID-diagnostic.json','JSON (*.json)')
  finally:self.flyout.menu_open=False
  if path:
   try:atomic_json(path,payload);self.render('设备诊断已导出，可用于核对型号与采样限制。')
   except OSError as error:self.render('导出失败：'+str(error))
 def start_long(self):
  learning=getattr(self.flyout,'learning',None)
  if learning is None:self.render('后台观察器不可用。');return
  try:learning.start(self.identity,self.before,self.after,self.duration.currentData())
  except ValueError as error:self.render(str(error));return
  self.close();self.flyout.open_learning()
 def save(self):
  path=data_dir()/'research-evidence.json';old=read_json(path,[],500000)
  if not isinstance(old,list):old=[]
  old.append({'saved_at':time.time(),'before':self.before,'after':self.after,'analysis':self.result,
              'selected_candidate':self.candidate,'verified_mapping':False})
  try:atomic_json(path,old[-20:]);self.render('证据已保存在本机 research-evidence.json；未启用电量映射。')
  except OSError as error:self.render('保存失败：'+str(error))
 def closeEvent(self,event):
  self.halt();self.flyout.pinned=False;super().closeEvent(event)
 def reject(self):
  self.halt();self.flyout.pinned=False;super().reject()

