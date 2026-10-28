import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
import tempfile,time,unittest
import ctypes
from unittest.mock import patch
from PySide6.QtCore import QTimer,QProcess
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from jobs import WorkerJob
from settings import read_json
from worker import run
app=QApplication.instance() or QApplication([])


class ProcessTests(unittest.TestCase):
    def test_native_hang_is_killed_without_blocking_event_loop(self):
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'PB_DATA_DIR':folder,'PB_TEST_MODE':'1'}):
            results=[];ticks=[];pid=None;job=WorkerJob({'operation':'test-sleep'},1000)
            timer=QTimer();timer.setInterval(30);timer.timeout.connect(lambda:ticks.append(1));timer.start()
            job.finished.connect(results.append);started=time.monotonic();job.start()
            while not results and time.monotonic()-started<3:
                marker=read_json(job.path.with_name(job.nonce+'.started.json'),{})
                pid=marker.get('pid') or pid;QTest.qWait(20)
            timer.stop();self.assertTrue(results);self.assertTrue(results[0]['timed_out'])
            self.assertLess(time.monotonic()-started,2);self.assertGreater(len(ticks),8)
            self.assertIsNotNone(pid);QTest.qWait(180)
            kernel=ctypes.WinDLL('kernel32');kernel.OpenProcess.restype=ctypes.c_void_p;kernel.CloseHandle.argtypes=[ctypes.c_void_p]
            kernel.GetExitCodeProcess.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_ulong)]
            handle=kernel.OpenProcess(0x1000,False,pid)
            if handle:
                code=ctypes.c_ulong();kernel.GetExitCodeProcess(handle,ctypes.byref(code));kernel.CloseHandle(handle)
                self.assertNotEqual(code.value,259,'The actual Python worker survived the timeout')
            self.assertEqual(list((Path(folder)/'workers').glob('*')),[])
    def test_worker_rejects_arbitrary_request_location(self):
        self.assertEqual(run(Path(tempfile.gettempdir())/'invalid.request.json'),2)


if __name__=='__main__':unittest.main()
