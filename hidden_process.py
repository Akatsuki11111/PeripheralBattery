"""Qt-supervised Windows workers with explicit no-console process creation."""
import os,subprocess
from PySide6.QtCore import QObject,QTimer,Signal,QProcess


class HiddenProcess(QObject):
    started=Signal()
    finished=Signal(int,object)
    errorOccurred=Signal(object)
    def __init__(self,parent=None):
        super().__init__(parent);self.child=None;self.environment=dict(os.environ);self.message=''
        self.timer=QTimer(self);self.timer.setInterval(25);self.timer.timeout.connect(self.poll)
        self._running=False
    def setProcessEnvironment(self,environment):
        self.environment={entry.split('=',1)[0]:entry.split('=',1)[1] for entry in environment.toStringList() if entry and not entry.startswith('=')}
    def start(self,executable,args):
        try:
            startup=subprocess.STARTUPINFO();startup.dwFlags|=subprocess.STARTF_USESHOWWINDOW;startup.wShowWindow=0
            self.child=subprocess.Popen([executable,*args],env=self.environment,stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW,
                startupinfo=startup,close_fds=True)
            self._running=True;self.timer.start();self.started.emit()
        except OSError:
            self.message='后台进程启动失败';self.errorOccurred.emit(QProcess.ProcessError.FailedToStart)
    def poll(self):
        if not self._running or self.child is None:return
        code=self.child.poll()
        if code is None:return
        self._running=False;self.timer.stop()
        self.finished.emit(code,QProcess.ExitStatus.NormalExit if code>=0 else QProcess.ExitStatus.CrashExit)
    def state(self):return QProcess.ProcessState.Running if self._running else QProcess.ProcessState.NotRunning
    def processId(self):return self.child.pid if self.child else 0
    def errorString(self):return self.message
    def kill(self):
        if self.child and self.child.poll() is None:
            try:self.child.kill()
            except OSError:pass
    def waitForFinished(self,msecs):
        if self.child is None:return True
        try:self.child.wait(max(0,msecs)/1000)
        except subprocess.TimeoutExpired:return False
        self.poll();return True
