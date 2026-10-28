"""Windows Job Object lifetime for workers, including one-file bootloader children."""
import ctypes
from ctypes import wintypes
import os


class BasicLimits(ctypes.Structure):
    _fields_=[('process_time',ctypes.c_longlong),('job_time',ctypes.c_longlong),('flags',wintypes.DWORD),
              ('min_working',ctypes.c_size_t),('max_working',ctypes.c_size_t),('active',wintypes.DWORD),
              ('affinity',ctypes.c_size_t),('priority',wintypes.DWORD),('scheduling',wintypes.DWORD)]


class ExtendedLimits(ctypes.Structure):
    _fields_=[('basic',BasicLimits),('io',ctypes.c_ulonglong*6),('process_memory',ctypes.c_size_t),
              ('job_memory',ctypes.c_size_t),('peak_process',ctypes.c_size_t),('peak_job',ctypes.c_size_t)]


def api():
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateJobObjectW.argtypes=[ctypes.c_void_p,wintypes.LPCWSTR];kernel.CreateJobObjectW.restype=wintypes.HANDLE
    kernel.OpenJobObjectW.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.LPCWSTR];kernel.OpenJobObjectW.restype=wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes=[wintypes.HANDLE,ctypes.c_int,ctypes.c_void_p,wintypes.DWORD]
    kernel.AssignProcessToJobObject.argtypes=[wintypes.HANDLE,wintypes.HANDLE]
    kernel.IsProcessInJob.argtypes=[wintypes.HANDLE,wintypes.HANDLE,ctypes.POINTER(wintypes.BOOL)]
    kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];kernel.OpenProcess.restype=wintypes.HANDLE
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    kernel.GetCurrentProcess.restype=wintypes.HANDLE
    return kernel


def attach(kernel,job,process):
    inside=wintypes.BOOL()
    if kernel.IsProcessInJob(process,job,ctypes.byref(inside)) and inside.value:return
    if not kernel.AssignProcessToJobObject(job,process):raise ctypes.WinError(ctypes.get_last_error())


class ProcessTree:
    def __init__(self,nonce):
        self.kernel=api();self.name='Local\\PeripheralBattery.worker.'+nonce
        self.handle=self.kernel.CreateJobObjectW(None,self.name)
        if not self.handle:raise ctypes.WinError(ctypes.get_last_error())
        limits=ExtendedLimits();limits.basic.flags=0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.kernel.SetInformationJobObject(self.handle,9,ctypes.byref(limits),ctypes.sizeof(limits)):
            self.close();raise ctypes.WinError(ctypes.get_last_error())

    def attach_pid(self,pid):
        process=self.kernel.OpenProcess(0x0100|0x0001|0x1000,False,pid)
        if not process:return  # It may have exited already; the worker also joins before I/O.
        try:attach(self.kernel,self.handle,process)
        finally:self.kernel.CloseHandle(process)

    def close(self):
        if self.handle:self.kernel.CloseHandle(self.handle);self.handle=None


def join_worker_job():
    name=os.environ.get('PB_WORKER_JOB')
    if not name:return
    if not name.startswith('Local\\PeripheralBattery.worker.'):raise ValueError('Invalid worker job')
    kernel=api();handle=kernel.OpenJobObjectW(0x0001|0x0004,False,name)  # assign + query
    if not handle:raise ctypes.WinError(ctypes.get_last_error())
    try:attach(kernel,handle,kernel.GetCurrentProcess())
    finally:kernel.CloseHandle(handle)
