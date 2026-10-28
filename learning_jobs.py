"""One explicitly started session; closing its window does not end collection."""
import time
import re
from PySide6.QtCore import QObject,QTimer,Signal
from jobs import WorkerJob
from settings import data_dir,read_json,atomic_json
from long_learning import analyze


class LearningController(QObject):
    changed=Signal()

    def __init__(self,scanner,parent=None):
        super().__init__(parent);self.scanner=scanner;self.path=data_dir()/'learning-session.json'
        self.session=read_json(self.path,{},1000000);self.job=None;self.generation=0
        if not isinstance(self.session,dict):self.session={}
        if self.session:
            try:
                assert re.fullmatch('[a-f0-9]{24}',self.session['identity'])
                assert self.session['target_seconds'] in (3600,7200)
                assert 0<=self.session['elapsed_seconds']<=15000
                assert self.session['state'] in ('observing','awaiting_unplug','paused','completed','cancelled')
                assert len(self.session['before'])==len(self.session['charged'])==3 and len(self.session['usage'])<=300
                for sample in self.session['before']+self.session['charged']+self.session['usage']:
                    assert 0<len(bytes.fromhex(sample['hex']))<=256 and isinstance(sample['timestamp'],(float,int))
            except (KeyError,TypeError,ValueError,AssertionError):self.session={}
        if self.session.get('state') in ('observing','awaiting_unplug'):
            self.session['state']='paused';self.session['message']='程序重启，观察已暂停；确认同一设备后可继续。'
        self.timer=QTimer(self);self.timer.setSingleShot(True);self.timer.timeout.connect(self.tick)

    def save(self):
        try:atomic_json(self.path,self.session)
        except OSError:self.session['message']='观察记录暂时无法保存，请检查磁盘。'
        self.changed.emit()

    def start(self,identity,before,charged,hours):
        if self.session.get('state') in ('observing','awaiting_unplug'):raise ValueError('已有一台设备在观察，请先结束它。')
        if hours not in (1,2) or len(before)<3 or len(charged)<3:raise ValueError('初始与插线采样不完整')
        self.stop_job();self.session={'identity':identity,'name':before[0]['name'],'before':before,'charged':charged,
            'usage':[],'target_seconds':hours*3600,'elapsed_seconds':0,'state':'awaiting_unplug',
            'created_at':time.time(),'message':'请拔掉充电线后正常使用；关闭面板可继续观察。','failures':0}
        self.save();self.timer.start(1000)

    def tick(self):
        if self.session.get('state') not in ('observing','awaiting_unplug') or self.job:return
        if self.scanner.busy or self.scanner.research_active:self.timer.start(5000);return
        if time.time()-self.session.get('created_at',0)>self.session['target_seconds']*4:
            self.pause('等待时间过长，已暂停，可检查设备后继续。');return
        self.scanner.research_active=True;generation=self.generation
        job=WorkerJob({'operation':'research-sample','identity':self.session['identity'],
            'channel':self.session['before'][0].get('channel')},6500,self);self.job=job
        job.finished.connect(lambda result:self.completed(job,result,generation));job.start()

    def completed(self,job,result,generation):
        if generation!=self.generation:return
        self.job=None;self.scanner.research_active=False
        if not result.get('ok'):
            self.session['failures']=self.session.get('failures',0)+1
            self.session['message']='本次没有应答，间断不计入有效观察。'+str(result.get('error',''))
            if self.session['failures']>=3:self.pause('连续三次没有应答，已暂停；唤醒或重新连接后继续。');return
        else:
            sample=result['sample'];self.session['failures']=0
            if sample.get('charging') is True:
                self.session['message']='仍在充电，等待拔线；这段时间不计入使用观察。'
                self.session['last_unplugged']=False
            else:
                usage=self.session['usage']
                if usage and self.session.get('last_unplugged'):
                    dt=sample['timestamp']-usage[-1]['timestamp']
                    if 0<dt<=180:self.session['elapsed_seconds']+=dt
                if not self.session.get('last_unplugged'):sample['segment_start']=True
                usage.append(sample);self.session['usage']=usage[-300:];self.session['last_unplugged']=True
                self.session['state']='observing';self.session['message']='正在观察，请正常使用。未知报告的拔线状态以你的操作为依据。'
                if self.session['elapsed_seconds']>=self.session['target_seconds']:
                    self.session['analysis']=analyze(self.session['before'],self.session['charged'],usage)
                    self.session['state']='completed';self.session['message']='观察完成，请审阅候选；没有结果也可能是电量未变化或报告没有电量。'
        self.save()
        if self.session['state'] in ('observing','awaiting_unplug'):self.timer.start(60000)

    def stop_job(self):
        self.generation+=1;self.timer.stop()
        if self.job:
            job=self.job;self.job=None;job.cancel();self.scanner.research_active=False

    def pause(self,message='已暂停，可以稍后继续。'):
        self.stop_job()
        if self.session:
            self.session.update(state='paused',message=message,last_unplugged=False);self.save()

    def resume(self):
        if self.session.get('state')!='paused':return
        self.session.update(state='awaiting_unplug',failures=0,created_at=time.time(),last_unplugged=False)
        self.save();self.timer.start(1000)

    def extend(self):
        if self.session.get('state')!='completed' or self.session.get('target_seconds')!=3600:return
        self.session.update(state='awaiting_unplug',target_seconds=7200,created_at=time.time(),failures=0,last_unplugged=False)
        self.save();self.timer.start(1000)

    def cancel(self):
        self.stop_job()
        if self.session:self.session.update(state='cancelled',message='已结束观察。');self.save()
