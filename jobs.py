"""Qt process supervision: blocking native HID calls never run in the GUI."""
import os
from pathlib import Path
import sys
import time
import uuid
from PySide6.QtCore import QObject,QProcess,QProcessEnvironment,QTimer,Signal
from process_tree import ProcessTree
from classification import bind_groups,apply_saved_modes
from identity import usb_audio_device_ids
from settings import atomic_json,data_dir,read_json,redact,probe_timeout_ms


def worker_command(request_path):
    if getattr(sys,'frozen',False):
        return sys.executable,['--worker',str(request_path)]
    python=Path(sys.executable).with_name('pythonw.exe')
    if not python.exists():python=Path(sys.executable)
    return str(python),[str(Path(__file__).with_name('app.py')),'--worker',str(request_path)]


class WorkerJob(QObject):
    finished=Signal(object)

    def __init__(self,request,timeout_ms=6500,parent=None):
        super().__init__(parent)
        self.nonce=uuid.uuid4().hex
        self.path=data_dir()/'workers'/(self.nonce+'.request.json')
        self.result_path=self.path.with_name(self.nonce+'.result.json')
        self.request={**request,'nonce':self.nonce}
        self.timeout_ms=timeout_ms
        self.process=QProcess(self)
        self.timer=QTimer(self);self.timer.setSingleShot(True)
        self.completed=False;self.expired=False;self.started_at=0
        self.tree=None
        self.process.started.connect(self._started)
        self.process.finished.connect(self._finished)
        self.process.errorOccurred.connect(self._error)
        self.process.readyReadStandardError.connect(lambda:self.process.readAllStandardError())
        self.process.readyReadStandardOutput.connect(lambda:self.process.readAllStandardOutput())
        self.timer.timeout.connect(self._expire)

    def start(self):
        try:
            atomic_json(self.path,self.request)
            executable,args=worker_command(self.path)
            self.tree=ProcessTree(self.nonce)
            environment=QProcessEnvironment.systemEnvironment();environment.insert('PB_WORKER_JOB',self.tree.name)
            self.process.setProcessEnvironment(environment)
            self.started_at=time.monotonic();self.timer.start(self.timeout_ms)
            self.process.start(executable,args)
        except Exception as error:
            self._complete({'ok':False,'error':redact(error)})

    def _started(self):
        try:self.tree.attach_pid(int(self.process.processId()))
        except OSError:pass  # The Python worker joins the same job before importing HID.

    def _expire(self):
        self.expired=True
        if self.tree:self.tree.close()
        self.process.kill()
        self._complete({'ok':False,'timed_out':True,'error':'查询超时，已终止本设备的后台进程。'})

    def _error(self,error):
        if self.process.state()==QProcess.ProcessState.NotRunning and not self.completed:
            self._complete({'ok':False,'error':'后台查询进程无法运行：'+self.process.errorString()})

    def _finished(self,*args):
        if self.completed:return
        result=read_json(self.result_path,None,1_000_000)
        if not isinstance(result,dict) or result.get('nonce')!=self.nonce:
            result={'ok':False,'error':'后台查询未返回有效结果。'}
        self._complete(result)

    def _complete(self,result):
        if self.completed:return
        self.completed=True;self.timer.stop()
        result['duration']=time.monotonic()-self.started_at if self.started_at else 0
        self.finished.emit(result)
        # Wait for OS process death before reclaiming files the worker may be using.
        if self.process.state()==QProcess.ProcessState.NotRunning:self.cleanup()
        else:self.process.finished.connect(lambda *args:self.cleanup())

    def cleanup(self):
        if self.tree:self.tree.close()
        for path in (self.path,self.result_path,self.path.with_name(self.nonce+'.started.json')):
            try:path.unlink(missing_ok=True)
            except OSError:pass
        self.deleteLater()

    def cancel(self):
        if not self.completed:self._expire()


class ScanController(QObject):
    updated=Signal(object,object)
    busyChanged=Signal(bool)

    def __init__(self,store,preferences,logger,parent=None):
        super().__init__(parent)
        self.store=store;self.preferences=preferences;self.logger=logger
        self.inventory=[];self.jobs=set();self.queue=[];self.busy=False;self.stopping=False
        self.last_inventory=0;self.paths=None;self.failures={};self.errors=[];self.last_attempt={}
        self.pending_force=False;self.research_active=False
        self.total_timer=QTimer(self);self.total_timer.setSingleShot(True);self.total_timer.timeout.connect(self._total_expired)

    def refresh(self,force=False):
        if self.stopping or self.research_active:return
        if self.busy:
            if force:self.pending_force=True
            return
        self.busy=True;self.errors=[];self.busyChanged.emit(True)
        if force:self.failures={}
        try:
            from battery_backends.hidlist import interface_paths
            hid_paths=interface_paths()
            paths=(hid_paths,usb_audio_device_ids()) if hid_paths is not None else None
        except Exception:paths=None
        changed=paths is None or paths!=self.paths
        if force or changed or time.monotonic()-self.last_inventory>60 or not self.inventory:
            self.paths=paths
            job=WorkerJob({'operation':'inventory','overrides':self.preferences.get('brand_overrides',{})},9000,self)
            self.jobs.add(job);job.finished.connect(lambda result:self._inventory_done(job,result));job.start()
        else:self._start_queries()

    def _inventory_done(self,job,result):
        self.jobs.discard(job)
        if self.stopping:return
        if result.get('ok') and isinstance(result.get('groups'),list):
            from models import Device
            try:
                groups=result['groups'][:120]
                records=[Device.from_dict(group['device']) for group in groups]
                self.store.reconcile(records);self.last_inventory=time.monotonic()
                self.inventory=bind_groups(groups,self.store,self.preferences)
                active_ids={group['device']['identity'] for group in self.inventory}
                self.last_attempt={key:value for key,value in self.last_attempt.items() if key in active_ids}
                self.failures={key:value for key,value in self.failures.items() if key in active_ids}
                self.updated.emit(self.store.snapshot(),list(self.errors))
            except (KeyError,TypeError,ValueError) as error:
                self.errors.append('设备枚举数据无效：'+str(error))
        else:
            self.errors.append(result.get('error','设备枚举失败'))
            # A failed inventory cannot keep old readings looking live.
            from dataclasses import replace
            self.store.devices={key:replace(d,connected=None,percent=None,voltage_mv=None,confidence='unknown',note=self.errors[-1])
                                for key,d in self.store.devices.items()}
            for device in self.store.snapshot():self.store.history.record(device)
            self._finish();return
        self._start_queries()

    def _start_queries(self):
        now=time.monotonic()
        available=[g for g in self.inventory if g.get('backend') and
                   self.failures.get(g['device']['identity'],(0,0))[1]<=now]
        # Devices not actually started in a timed-out round get priority next time.
        available.sort(key=lambda g:(self.last_attempt.get(g['device']['identity'],0),g['device']['identity']))
        self.queue=available;self.total_timer.start(35_000)
        self._pump()

    def _pump(self):
        if self.stopping:return
        while self.queue and len(self.jobs)<2:
            group=self.queue.pop(0)
            self.last_attempt[group['device']['identity']]=time.monotonic()
            job=WorkerJob({'operation':'probe','group':group},probe_timeout_ms(group.get('backend')),self)
            self.jobs.add(job);job.finished.connect(lambda result,j=job,g=group:self._probe_done(j,g,result));job.start()
        if not self.queue and not self.jobs:self._finish()

    def _probe_done(self,job,group,result):
        self.jobs.discard(job)
        if self.stopping:return
        identity=group['device']['identity']
        readings=result.get('readings')
        if result.get('ok') and isinstance(readings,list) and readings:
            try:
                self.store.apply_readings(identity,readings)
                if any(item.get('connected') is True for item in readings):self.failures.pop(identity,None)
                elif all(item.get('connected') is None for item in readings):self._backoff(identity)
            except (ValueError,TypeError,KeyError) as error:
                self.errors.append('设备读数无效：'+str(error))
        else:
            message=redact(result.get('error','没有电量应答'))
            self.errors.append(group['device']['name']+'：'+message)
            self.logger.warning('%s query: %s',group['device']['brand'],message)
            self.store.apply_readings(identity,[{'percent':None,'connected':None,'charging':None,
                                                'confidence':'unknown','note':message}])
            self._backoff(identity)
        apply_saved_modes(self.store,self.preferences)
        self.updated.emit(self.store.snapshot(),list(self.errors))
        self._pump()

    def _backoff(self,identity):
        count=self.failures.get(identity,(0,0))[0]+1
        self.failures[identity]=(count,time.monotonic()+min(120,15*2**min(count,3)))

    def _total_expired(self):
        self.queue=[]
        self.errors.append('本轮达到查询总时限；其他设备将在后续刷新中继续查询。')
        for job in list(self.jobs):job.cancel()
        if not self.jobs:self._finish()

    def _finish(self):
        if not self.busy:return
        self.total_timer.stop();self.busy=False
        try:self.store.save()
        except OSError as error:self.logger.warning('Cannot save cache: %s',redact(error))
        self.updated.emit(self.store.snapshot(),list(self.errors));self.busyChanged.emit(False)
        if self.pending_force and not self.stopping:
            self.pending_force=False;QTimer.singleShot(0,lambda:self.refresh(True))

    def shutdown(self):
        self.stopping=True;self.pending_force=False;self.total_timer.stop();self.queue=[]
        jobs=list(self.jobs)
        for job in jobs:job.cancel()
        for job in jobs:
            if job.process.state()!=QProcess.ProcessState.NotRunning:job.process.waitForFinished(800)
            job.cleanup()
        self.jobs.clear()
