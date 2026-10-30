"""Verified update helper, started from the new EXE before the old app exits."""
import ctypes
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import uuid
from settings import data_dir,atomic_json,read_json


def stage_info(info):
    path=Path(info['path']).resolve();root=(data_dir()/'updates').resolve()
    if path.parent!=root or not re.fullmatch('[a-f0-9]{32}\\.exe',path.name):raise ValueError('更新文件位置无效')
    digest=info.get('sha256','')
    if not re.fullmatch('[a-f0-9]{64}',digest) or hashlib.sha256(path.read_bytes()).hexdigest()!=digest:
        raise ValueError('安装前校验失败')
    return path


def prepare_update(info):
    if not getattr(sys,'frozen',False):raise ValueError('源码运行模式请使用 Git 更新源码')
    stage=stage_info(info);origin=Path(sys.executable).resolve()
    if not origin.name.lower().startswith('peripheralbattery') or origin.suffix.lower()!='.exe':raise ValueError('当前程序位置不支持更新')
    request=data_dir()/'updates'/(uuid.uuid4().hex+'.install.json')
    atomic_json(request,{'download':info,'origin':str(origin),'pid':os.getpid()})
    subprocess.Popen([str(stage),'--apply-update',str(request)],creationflags=subprocess.CREATE_NO_WINDOW)


def replace_targets(stage,targets):
    backups=[];changed=[];nonce=uuid.uuid4().hex;success=False
    try:
        for target in targets:
            backup=target.with_name(target.name+'.'+nonce+'.bak')
            shutil.copy2(target,backup);backups.append((target,backup))
        for target,_ in backups:
            temporary=target.with_name(target.name+'.'+nonce+'.new')
            try:
                shutil.copy2(stage,temporary);deadline=time.monotonic()+30
                while True:
                    try:os.replace(temporary,target);changed.append(target);break
                    except OSError:
                        if time.monotonic()>=deadline:raise
                        time.sleep(.2)
            finally:temporary.unlink(missing_ok=True)
        success=True
    except Exception:
        for target,backup in reversed(backups):
            if target in changed:os.replace(backup,target)
        raise
    finally:
        if success:
            for _,backup in backups:backup.unlink(missing_ok=True)


def apply_update(request_file):
    request=Path(request_file).resolve();root=(data_dir()/'updates').resolve()
    if request.parent!=root or not re.fullmatch('[a-f0-9]{32}\\.install\\.json',request.name):return 2
    info=read_json(request,{},20000);origin=None
    try:
        stage=stage_info(info['download']);origin=Path(info['origin']).resolve()
        if origin==stage or not origin.is_file() or origin.suffix.lower()!='.exe' or not origin.name.lower().startswith('peripheralbattery'):
            raise ValueError('安装目标无效')
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.OpenProcess.argtypes=[ctypes.c_uint32,ctypes.c_int,ctypes.c_uint32];kernel.OpenProcess.restype=ctypes.c_void_p
        kernel.WaitForSingleObject.argtypes=[ctypes.c_void_p,ctypes.c_uint32];kernel.CloseHandle.argtypes=[ctypes.c_void_p]
        handle=kernel.OpenProcess(0x100000,False,int(info['pid']))
        if handle:
            try:
                if kernel.WaitForSingleObject(handle,30000)!=0:raise OSError('旧程序没有退出，更新已停止')
            finally:kernel.CloseHandle(handle)
        targets=[origin];installed=(data_dir()/'bin/PeripheralBattery.exe').resolve()
        if installed!=origin and installed.is_file():targets.append(installed)
        replace_targets(stage,targets)
        atomic_json(root/'last-result.json',{'ok':True,'version':info['download'].get('version'),'at':time.time()})
        subprocess.Popen([str(origin)],creationflags=subprocess.CREATE_NO_WINDOW);return 0
    except Exception as error:
        atomic_json(root/'last-result.json',{'ok':False,'message':str(error)[:500],'at':time.time()})
        if origin and origin.is_file():subprocess.Popen([str(origin)],creationflags=subprocess.CREATE_NO_WINDOW)
        return 1
    finally:request.unlink(missing_ok=True)
