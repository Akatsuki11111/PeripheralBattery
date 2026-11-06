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


def replace_targets(stage,targets,verify_startup=None):
    backups=[];changed=[];nonce=uuid.uuid4().hex;restored=False
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
        if verify_startup is not None:
            verify_startup()
        restored=True
    except Exception:
        for target,backup in reversed(backups):
            if target in changed:
                deadline=time.monotonic()+15
                while True:
                    try:
                        os.replace(backup,target)
                        break
                    except OSError:
                        if time.monotonic()>=deadline:
                            raise
                        time.sleep(.2)
        restored=True
        raise
    finally:
        if restored:
            for _,backup in backups:
                try:backup.unlink(missing_ok=True)
                except OSError:pass


def ready_marker(nonce):
    if not re.fullmatch(r'[a-f0-9]{32}',nonce):
        raise ValueError('更新启动确认标识无效')
    return data_dir()/'updates'/(nonce+'.ready.json')


def mark_ready(nonce,version):
    marker=ready_marker(nonce)
    request=read_json(marker.with_name(nonce+'.install.json'),{},20000)
    if (not getattr(sys,'frozen',False) or request.get('download',{}).get('version')!='v'+version
            or Path(request.get('origin','')).resolve()!=Path(sys.executable).resolve()):
        return False
    atomic_json(marker,{'nonce':nonce,'version':'v'+version,'pid':os.getpid()})
    return True


def launch_for_verification(origin,nonce,version):
    from process_tree import ProcessTree
    marker=ready_marker(nonce);marker.unlink(missing_ok=True)
    tree=ProcessTree(nonce,kill_on_close=False)
    child=None
    try:
        env={**os.environ,'PB_WORKER_JOB':tree.name,'PYINSTALLER_RESET_ENVIRONMENT':'1'}
        child=subprocess.Popen([str(origin),'--update-ready',nonce],env=env,
                               creationflags=subprocess.CREATE_NO_WINDOW)
        tree.attach_pid(child.pid)
        deadline=time.monotonic()+45
        while time.monotonic()<deadline:
            if child.poll() is not None:
                raise OSError('新版在托盘就绪前退出，已尝试恢复旧版')
            reply=read_json(marker,{},4096)
            if reply.get('nonce')==nonce and reply.get('version')==version:
                return
            time.sleep(.15)
        raise TimeoutError('新版启动确认超时，已尝试恢复旧版')
    except Exception:
        if child is not None:
            try:tree.terminate()
            finally:child.wait(timeout=12)
        raise
    finally:
        tree.close()
        try:marker.unlink(missing_ok=True)
        except OSError:pass


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
        version=info['download']['version']
        nonce=request.name.split('.')[0]
        replace_targets(stage,targets,lambda:launch_for_verification(origin,nonce,version))
        atomic_json(root/'last-result.json',{'ok':True,'version':version,'at':time.time()})
        return 0
    except Exception as error:
        atomic_json(root/'last-result.json',{'ok':False,'message':str(error)[:500],'at':time.time()})
        if origin and origin.is_file():
            subprocess.Popen([str(origin)],creationflags=subprocess.CREATE_NO_WINDOW,
                             env={**os.environ,'PYINSTALLER_RESET_ENVIRONMENT':'1'})
        return 1
    finally:request.unlink(missing_ok=True)
