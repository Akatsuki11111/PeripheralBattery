"""Owned autostart registration with stable installation path and state repair."""
from dataclasses import dataclass
import ctypes
import base64
import json
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import winreg
import time
import xml.etree.ElementTree as ET
from settings import data_dir

RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
APPROVED_KEY = r'Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run'
RUN_NAME = 'PeripheralBattery'
TASK_OWNER = 'Peripheral Battery user logon v1'
_task_cache = None

# COM requests are executed by the system Task Scheduler service. The service
# sees the same task and profile path at login, outside an MSIX host's registry.
TASK_SCRIPT = r'''
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
$request=[Console]::In.ReadToEnd() | ConvertFrom-Json
$identity=[Security.Principal.WindowsIdentity]::GetCurrent()
$sid=$identity.User.Value
$name='PeripheralBattery-'+$sid
$service=New-Object -ComObject Schedule.Service
$service.Connect()
$folder=$service.GetFolder('\')
$task=$null
try {$task=$folder.GetTask($name)} catch {
    if ($_.Exception.HResult -ne -2147024894) {throw}
}
if ($task -and $task.Definition.RegistrationInfo.Description -ne 'Peripheral Battery user logon v1') {
    throw 'Task name is already owned by another application.'
}
if ($request.operation -eq 'enable') {
    $definition=$service.NewTask(0)
    $definition.RegistrationInfo.Description='Peripheral Battery user logon v1'
    $definition.Principal.UserId=$sid
    $definition.Principal.LogonType=3
    $definition.Principal.RunLevel=0
    $definition.Settings.Enabled=$true
    $definition.Settings.StartWhenAvailable=$true
    $definition.Settings.DisallowStartIfOnBatteries=$false
    $definition.Settings.StopIfGoingOnBatteries=$false
    $definition.Settings.ExecutionTimeLimit='PT0S'
    $definition.Settings.MultipleInstances=2
    $trigger=$definition.Triggers.Create(9)
    $trigger.UserId=$sid
    $trigger.Delay='PT15S'
    $action=$definition.Actions.Create(0)
    $action.Path=$request.target
    $action.Arguments=$request.arguments
    $action.WorkingDirectory=$request.directory
    $task=$folder.RegisterTaskDefinition($name,$definition,6,$sid,$null,3,$null)
} elseif ($request.operation -eq 'disable' -and $task) {
    $folder.DeleteTask($name,0)
    $task=$null
}
if ($task) {
    [ordered]@{present=$true;name=$name;sid=$sid;account=$identity.Name;enabled=[bool]$task.Enabled;
        xml=$task.Xml;last_result=$task.LastTaskResult;state=$task.State;
        last_run=$task.LastRunTime.ToString('o')} | ConvertTo-Json -Compress
} else {[ordered]@{present=$false;name=$name;sid=$sid} | ConvertTo-Json -Compress}
'''


def task_request(operation='query', **values):
    global _task_cache
    if operation=='query' and _task_cache and time.monotonic()-_task_cache[0]<3:
        return _task_cache[1]
    executable=Path(os.environ.get('SystemRoot','C:/Windows'))/'System32/WindowsPowerShell/v1.0/powershell.exe'
    script=base64.b64encode(TASK_SCRIPT.encode('utf-16le')).decode('ascii')
    try:
        result=subprocess.run([str(executable),'-NoLogo','-NoProfile','-NonInteractive','-EncodedCommand',script],
            input=json.dumps({'operation':operation,**values}),capture_output=True,encoding='utf-8',
            errors='replace',timeout=15,creationflags=subprocess.CREATE_NO_WINDOW)
    except (OSError,subprocess.TimeoutExpired) as error:
        raise OSError('无法连接 Windows 任务计划服务：'+str(error)) from error
    if result.returncode:
        raise OSError('登录启动任务设置失败：'+result.stderr[-800:])
    try:value=json.loads(result.stdout.lstrip('\ufeff'))
    except ValueError as error:raise OSError('任务计划服务返回无效数据') from error
    _task_cache=(time.monotonic(),value)
    return value


@dataclass(frozen=True)
class StartupState:
    configured: bool
    enabled: bool
    valid: bool
    blocked: bool
    command: str = ''
    target: str = ''
    message: str = '已关闭'
    mechanism: str = ''
    task_name: str = ''
    last_result: int | None = None
    last_run: str = ''


def split_command(command):
    if not command:
        return []
    api = ctypes.WinDLL('shell32')
    api.CommandLineToArgvW.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_int)]
    api.CommandLineToArgvW.restype = ctypes.POINTER(ctypes.c_wchar_p)
    count = ctypes.c_int()
    pointer = api.CommandLineToArgvW(command, ctypes.byref(count))
    if not pointer:
        return []
    try:
        return [pointer[index] for index in range(count.value)]
    finally:
        kernel = ctypes.WinDLL('kernel32')
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        kernel.LocalFree(pointer)


def install_path():
    return data_dir() / 'bin' / 'PeripheralBattery.exe'


def expected_command():
    if getattr(sys, 'frozen', False):
        return subprocess.list2cmdline([str(install_path()), '--background', '--autostart'])
    python = Path(sys.executable).with_name('pythonw.exe')
    if not python.exists():
        python = Path(sys.executable)
    return subprocess.list2cmdline([str(python), str(Path(__file__).with_name('app.py')), '--background', '--autostart'])


def equivalent(first, second):
    a, b = split_command(first), split_command(second)
    if len(a) != len(b) or not a:
        return False
    normalize = lambda value: os.path.normcase(os.path.normpath(value))
    return normalize(a[0]) == normalize(b[0]) and all(
        normalize(x) == normalize(y) if x.lower().endswith(('.exe', '.py')) else x == y
        for x, y in zip(a[1:], b[1:]))


def legacy_state():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            command, kind = winreg.QueryValueEx(key, RUN_NAME)
        if kind not in (winreg.REG_SZ, winreg.REG_EXPAND_SZ) or not isinstance(command, str):
            return StartupState(True, False, False, False, message='启动项格式无效，可重新开启修复')
        args = split_command(os.path.expandvars(command))
        target = args[0] if args else ''
        valid = bool(target and Path(target).is_file())
        if valid and len(args) > 1 and args[1].lower().endswith('.py'):
            valid = Path(args[1]).is_file()
        blocked = False
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, APPROVED_KEY) as key:
                approved, _ = winreg.QueryValueEx(key, RUN_NAME)
            blocked = isinstance(approved, bytes) and bool(approved) and approved[0] in (3, 7)
        except OSError:
            pass
        enabled = valid and not blocked
        message = '已开启' if enabled else '被 Windows 禁用' if blocked else '启动路径已失效'
        if enabled and not equivalent(command, expected_command()):
            message = '已开启 · 旧路径待修复'
        return StartupState(True, enabled, valid, blocked, command, target, message)
    except FileNotFoundError:
        return StartupState(False, False, False, False)
    except OSError as error:
        return StartupState(False, False, False, False, message='无法读取启动项：' + str(error))


def state():
    try:
        task=task_request()
        if not task.get('present'):
            legacy=legacy_state()
            return StartupState(legacy.configured,False,False,legacy.blocked,legacy.command,legacy.target,
                '旧启动项待迁移' if legacy.configured else '已关闭',mechanism='legacy-run' if legacy.configured else '')
        root=ET.fromstring(task['xml']);ns={'t':'http://schemas.microsoft.com/windows/2004/02/mit/task'}
        text=lambda path:root.findtext(path,'',ns)
        same_user=lambda value:value==task['sid'] or bool(task.get('account')) and value.casefold()==task['account'].casefold()
        target=text('t:Actions/t:Exec/t:Command');arguments=text('t:Actions/t:Exec/t:Arguments')
        command=subprocess.list2cmdline([target])+' '+arguments
        valid=(Path(target).is_file() and equivalent(command,expected_command())
            and text('t:RegistrationInfo/t:Description')==TASK_OWNER
            and text('t:Principals/t:Principal/t:LogonType')=='InteractiveToken'
            and text('t:Principals/t:Principal/t:RunLevel') in ('','LeastPrivilege')
            and same_user(text('t:Principals/t:Principal/t:UserId'))
            and same_user(text('t:Triggers/t:LogonTrigger/t:UserId'))
            and text('t:Triggers/t:LogonTrigger/t:Enabled')!='false'
            and len(root.findall('t:Actions/t:Exec',ns))==1
            and text('t:Settings/t:ExecutionTimeLimit')=='PT0S'
            and text('t:Settings/t:DisallowStartIfOnBatteries')=='false'
            and text('t:Settings/t:StopIfGoingOnBatteries')=='false')
        blocked=not task.get('enabled',False);enabled=bool(valid and not blocked)
        return StartupState(True,enabled,bool(valid),blocked,command,target,
            '已开启 · 登录后 15 秒' if enabled else '登录启动已禁用' if blocked else '登录启动配置待修复',
            'scheduled-task',task['name'],task.get('last_result'),task.get('last_run',''))
    except (OSError,ValueError,KeyError) as error:
        return StartupState(False,False,False,False,message='无法核验登录启动：'+str(error))


def ensure_installed():
    if not getattr(sys, 'frozen', False):
        return
    source, destination = Path(sys.executable).resolve(), install_path()
    if source == destination.resolve():
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and hashlib.sha256(source.read_bytes()).digest() == hashlib.sha256(destination.read_bytes()).digest():
        return
    temporary = destination.with_suffix('.new.exe')
    shutil.copy2(source, temporary)
    try:
        os.replace(temporary, destination)
    except OSError:
        temporary.unlink(missing_ok=True)
        raise OSError('已安装版本仍在运行，请退出旧版后重试。')


def set_enabled(enabled):
    if enabled:
        ensure_installed()
        args=split_command(expected_command())
        task_request('enable',target=args[0],arguments=subprocess.list2cmdline(args[1:]),directory=str(Path(args[0]).parent))
    else:
        task_request('disable')
    # Remove only the obsolete, owned Run value after the replacement succeeded.
    # A second cleanup from the scheduled launch also covers the real hive.
    cleanup_legacy()
    result = state()
    if enabled and not result.enabled:
        raise OSError(result.message)
    return result


def cleanup_legacy():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,RUN_KEY,0,winreg.KEY_SET_VALUE) as key:
            try:
                winreg.DeleteValue(key, RUN_NAME)
            except FileNotFoundError:
                pass
    except FileNotFoundError:pass


def repair_if_requested(preferences):
    current = state()
    requested = preferences.get('autostart_requested', False) or current.configured
    if requested and not current.blocked and (not current.enabled or not equivalent(current.command, expected_command())):
        current = set_enabled(True)
        preferences.set('autostart_requested', True)
    return current
