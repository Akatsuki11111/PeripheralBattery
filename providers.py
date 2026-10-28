"""Synchronous diagnostic facade over killable subprocesses; no in-process HID I/O."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid
from models import Device
from protocols import parse_razer,parse_nova5,parse_scyrox
from settings import DeviceStore,Settings,atomic_json,data_dir,read_json,redact,probe_timeout_ms
from process_tree import ProcessTree
from classification import bind_groups


def bounded_operation(request,timeout=7):
    nonce=uuid.uuid4().hex
    path=data_dir()/'workers'/(nonce+'.request.json')
    output=path.with_name(nonce+'.result.json')
    atomic_json(path,{**request,'nonce':nonce})
    args=[sys.executable,'--worker',str(path)] if getattr(sys,'frozen',False) else [
        sys.executable,str(Path(__file__).with_name('app.py')),'--worker',str(path)]
    tree=None
    try:
        tree=ProcessTree(nonce)
        environment={**os.environ,'PB_WORKER_JOB':tree.name}
        process=subprocess.Popen(args,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,env=environment,creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            tree.attach_pid(process.pid);process.wait(timeout)
        except subprocess.TimeoutExpired:
            tree.close();process.kill();process.wait(timeout=2)
            raise
        finally:tree.close()
        value=read_json(output,{},1_000_000)
        if value.get('nonce')!=nonce:return {'ok':False,'error':'后台进程未返回有效结果'}
        return value
    except subprocess.TimeoutExpired:
        return {'ok':False,'timed_out':True,'error':'设备查询超时，后台进程已终止'}
    finally:
        if tree:tree.close()
        path.unlink(missing_ok=True);output.unlink(missing_ok=True)
        path.with_name(nonce+'.started.json').unlink(missing_ok=True)


def diagnose_mchose():
    """Bounded targeted diagnosis without device paths, serials or key reports."""
    result=bounded_operation({'operation':'inventory','overrides':{}},10)
    if not result.get('ok'):
        return {'devices':[],'errors':[result.get('error','枚举失败')]}
    matches=[g for g in result.get('groups',[])[:120] if g.get('backend')=='mchose']
    devices=[];errors=[];deadline=time.monotonic()+30
    for group in matches[:4]:
        remaining=deadline-time.monotonic()
        if remaining<1:errors.append('诊断达到总时限');break
        device=group['device']
        interfaces=[{key:info.get(key) for key in ('vendor_id','product_id','interface_number','usage_page','usage','bus_type')}
                    for info in group.get('infos',[])[:40]]
        response=bounded_operation({'operation':'probe','group':group,'diagnostics':True},
                                   min(probe_timeout_ms('mchose')/1000,remaining))
        readings=[{key:item.get(key) for key in ('name','kind','percent','charging','connected','confidence','note')}
                  for item in response.get('readings',[])[:12] if isinstance(item,dict)]
        devices.append({'name':device.get('name'),'brand':device.get('brand'),'vid':device.get('vid'),
                        'pid':device.get('pid'),'interfaces':interfaces,'readings':readings,
                        'diagnostics':response.get('diagnostics',[]),'error':response.get('error')})
    if len(matches)>4:errors.append('最多诊断四个设备，其他设备请先断开后重试')
    return {'devices':devices,'errors':errors}


class Scanner:
    def scan(self):
        store=DeviceStore();preferences=Settings();errors=[]
        result=bounded_operation({'operation':'inventory','overrides':preferences.get('brand_overrides',{})},10)
        if not result.get('ok'):return [],[result.get('error','枚举失败')]
        groups=result.get('groups',[])[:120];store.reconcile([Device.from_dict(g['device']) for g in groups])
        groups=bind_groups(groups,store,preferences)
        deadline=time.monotonic()+30
        for group in groups:
            if not group.get('backend'):continue
            remaining=deadline-time.monotonic()
            if remaining<1:errors.append('达到诊断总时限');break
            value=bounded_operation({'operation':'probe','group':group},min(probe_timeout_ms(group.get('backend'))/1000,remaining))
            if value.get('ok'):store.apply_readings(group['device']['identity'],value.get('readings',[]))
            else:errors.append(group['device']['name']+'：'+redact(value.get('error','查询失败')))
        return store.snapshot(),errors
