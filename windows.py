"""Small Windows integration layer; autostart is opt-in."""
import ctypes
import os
from pathlib import Path
import subprocess
import sys
import winreg

RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
RUN_NAME = 'PeripheralBattery'


def is_dark():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Themes\Personalize') as k:
            return winreg.QueryValueEx(k, 'AppsUseLightTheme')[0] == 0
    except OSError:
        return False


def accent():
    return '#60cdff' if is_dark() else '#0067c0'


def is_taskbar_dark():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Themes\Personalize') as k:
            return winreg.QueryValueEx(k, 'SystemUsesLightTheme')[0] == 0
    except OSError:
        return is_dark()


def startup_enabled():
    from startup import state
    return state().enabled


def startup_command():
    from startup import expected_command
    return expected_command()


def set_startup(enabled):
    from startup import set_enabled
    return set_enabled(enabled)


def round_window(hwnd):
    try:
        value = ctypes.c_int(2)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(ctypes.c_void_p(hwnd), 33, ctypes.byref(value), 4)
        dark = ctypes.c_int(is_dark())
        ctypes.windll.dwmapi.DwmSetWindowAttribute(ctypes.c_void_p(hwnd), 20, ctypes.byref(dark), 4)
    except OSError:
        pass


def show_tray_settings():
    os.startfile('ms-settings:taskbar')


def canonical_executable(path):
    """Resolve MSIX AppData virtualization before matching Explorer's icon record."""
    normalized=lambda value:os.path.normcase(os.path.normpath(str(value).removeprefix('\\\\?\\')))
    api=ctypes.WinDLL('kernel32',use_last_error=True)
    api.CreateFileW.argtypes=[ctypes.c_wchar_p,ctypes.c_ulong,ctypes.c_ulong,ctypes.c_void_p,ctypes.c_ulong,ctypes.c_ulong,ctypes.c_void_p]
    api.CreateFileW.restype=ctypes.c_void_p
    api.GetFinalPathNameByHandleW.argtypes=[ctypes.c_void_p,ctypes.c_wchar_p,ctypes.c_ulong,ctypes.c_ulong]
    api.CloseHandle.argtypes=[ctypes.c_void_p]
    handle=api.CreateFileW(str(path),0x80,7,None,3,0,None)
    if handle and handle!=ctypes.c_void_p(-1).value:
        try:
            buffer=ctypes.create_unicode_buffer(4096)
            size=api.GetFinalPathNameByHandleW(handle,buffer,len(buffer),0)
            if 0<size<len(buffer):return normalized(buffer.value)
        finally:api.CloseHandle(handle)
    return normalized(path)


TRAY_KEY=r'Control Panel\NotifyIconSettings'


def tray_records(executable=None):
    executable=executable or sys.executable
    targets={os.path.normcase(os.path.normpath(str(executable))),canonical_executable(executable)}
    result=[]
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,TRAY_KEY) as root:
            for index in range(min(winreg.QueryInfoKey(root)[0],1000)):
                name=winreg.EnumKey(root,index)
                try:
                    with winreg.OpenKey(root,name) as key:stored,kind=winreg.QueryValueEx(key,'ExecutablePath')
                    if kind==winreg.REG_SZ and isinstance(stored,str) and os.path.normcase(os.path.normpath(stored)) in targets:
                        result.append((name,stored))
                except OSError:continue
    except FileNotFoundError:pass
    return result


def set_tray_promoted(enabled,executable=None):
    """Windows 11 fallback when Explorer cannot drag ANY tray icons.

    Only existing records for this executable are touched. No Explorer restart,
    policy changes, or edits to other applications' icon entries are performed.
    """
    if executable is None and not getattr(sys,'frozen',False):
        raise OSError('源码模式请使用 Windows 任务栏设置，以免影响其他 Python 程序。')
    records=tray_records(executable)
    if not records:raise OSError('Windows 尚未建立本程序的托盘记录，请使用“任务栏设置 → 其他系统托盘图标”。')
    previous=[]
    # Check every path before any mutation; preserve missing values for rollback.
    for name,expected in records:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,TRAY_KEY+'\\'+name,0,winreg.KEY_QUERY_VALUE|winreg.KEY_SET_VALUE) as key:
            current,kind=winreg.QueryValueEx(key,'ExecutablePath')
            if kind!=winreg.REG_SZ or current!=expected:raise OSError('托盘记录已变化，请重试。')
            try:old=winreg.QueryValueEx(key,'IsPromoted')
            except FileNotFoundError:old=None
            previous.append((name,expected,old))
    changed=[]
    try:
        for name,expected,old in previous:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,TRAY_KEY+'\\'+name,0,winreg.KEY_QUERY_VALUE|winreg.KEY_SET_VALUE) as key:
                current,kind=winreg.QueryValueEx(key,'ExecutablePath')
                if kind!=winreg.REG_SZ or current!=expected:raise OSError('托盘记录已变化，请重试。')
                winreg.SetValueEx(key,'IsPromoted',0,winreg.REG_DWORD,int(bool(enabled)))
                changed.append((name,expected,old))
    except OSError as error:
        rollback_failed=False
        for name,expected,old in reversed(changed):
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER,TRAY_KEY+'\\'+name,0,winreg.KEY_QUERY_VALUE|winreg.KEY_SET_VALUE) as key:
                    current,kind=winreg.QueryValueEx(key,'ExecutablePath')
                    written,written_kind=winreg.QueryValueEx(key,'IsPromoted')
                    if kind!=winreg.REG_SZ or current!=expected or written_kind!=winreg.REG_DWORD or written!=int(bool(enabled)):
                        rollback_failed=True;continue
                    if old is None:winreg.DeleteValue(key,'IsPromoted')
                    else:winreg.SetValueEx(key,'IsPromoted',0,old[1],old[0])
            except OSError:rollback_failed=True
        if rollback_failed:raise OSError('托盘记录更新失败且无法完全回退，请检查 Windows 任务栏设置。') from error
        raise
    return len(records)
