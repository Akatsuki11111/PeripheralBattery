"""Conservative status-report research; never interrogate unknown HID protocols."""
from catalog import device_profile
from inventory import enumerate_groups,decode_info
from protocols import query,parse_nova5,parse_nova5_usb,parse_scyrox,scyrox_packet
import time
import json
import re
from pathlib import Path


from device_inspection import inspect_device


def research_devices(devices,include_supported=False):
    result=[]
    for d in devices:
        if not d.present or d.kind=='auxiliary' or d.power_mode=='wired' or d.connected is False:continue
        if d.brand=='Unknown' and not d.receiver:continue
        if include_supported or not (d.usable or d.fresh_grade):
            result.append(d)
    return result


def sample(identity,channel=None):
    inventory=enumerate_groups()
    groups=[g for g in inventory if g['device'].get('identity')==identity]
    if not groups:
        from settings import read_json,data_dir
        saved=read_json(data_dir()/'devices.json',[],300000)
        if isinstance(saved,list) and any(isinstance(d,dict) and d.get('identity')==identity and d.get('kind')=='gamepad' for d in saved):
            from gamepads import augment_inventory
            groups=[g for g in augment_inventory(inventory) if g['device'].get('identity')==identity]
    if len(groups)!=1:raise ValueError('原采样连接已消失或身份改变。插线切换到另一个接口时，请分别验证两个连接；原有采样仍可导出。')
    group=groups[0];d=group['device'];backend=group['backend'];profile=device_profile(d['vid'],d['pid'])
    infos=[decode_info(x) for x in group['infos']]
    if backend=='valkyrie_ry_usb':
        raise ValueError('M5 Lite USB 模式没有已验证的电池报告；官方 100% 为占位值。请拔线并选择 2.4G 接收器。')
    if backend=='valkyrie_ry':
        from valkyrie_ry import query_receiver
        matching=[i for i in infos if i.get('interface_number')==2 and i.get('usage_page')==0xffff and i.get('usage')==2]
        if len(matching)!=1:raise ValueError('没有找到唯一的 RY 状态接口')
        result=query_receiver(matching[0]);status=result['status']
        if not status.online:raise ValueError('接收器可应答，但远端鼠标离线。插 USB 后的无线链路变化不等于充电标志；请拔线并唤醒鼠标。')
        if result['model'] is None:raise ValueError(f'已读取 RY 型号 ID {result["model_id"]}，当前型号尚未验证，请导出诊断，勿把相关字段当成已适配电量。')
        return {'timestamp':time.time(),'hex':status.payload.hex(' '),'length':len(status.payload),'charging':None,'percent':status.percent,
                'interface':2,'usage_page':0xffff,'usage':2,'backend':backend,'vid':d['vid'],'pid':d['pid'],
                'name':result['model'][1],'remote_confirmed':True,'protocol_verified':True,
                'protocol_note':'已找到官方 F7 电池字段与 8F 型号应答；无需插拔差分或等待 1–2 小时。充电标志仍未知。'}
    if backend=='atk_zero_plus':
        from atk_zero_plus import NAME, read_status
        status = read_status(infos, d['pid'])
        if status.percent is None:
            raise ValueError('未取得已验证的 ATK ZERO+ 电量，请确认鼠标唤醒并使用所选连接。')
        return dict(timestamp=time.time(),hex=status.packet.hex(' '),length=len(status.packet),
                    charging=status.charging,percent=status.percent,interface=3,usage_page=0xff05,
                    usage=1,backend=backend,vid=d['vid'],pid=d['pid'],name=NAME,
                    remote_confirmed=True,protocol_verified=True,
                    protocol_note='已核对 BitMouse 型号、链路与电量应答，可直接完成预检。')
    if backend=='rapoo_vt7_pro_v2':
        from rapoo_vt7_pro_v2 import read_status
        status = read_status(infos, d['pid'])
        if status is None or not status.online:
            raise ValueError('未收到雷柏鼠标的在线状态。请唤醒鼠标并确认当前 USB 或 2.4G 通道。')
        return dict(timestamp=time.time(),hex=status.packet.hex(' '),length=len(status.packet),
                    charging=status.charging,percent=status.percent,interface=1,usage_page=0xff00,
                    usage=2,backend=backend,vid=d['vid'],pid=d['pid'],name=d['name'],
                    remote_confirmed=True,protocol_verified=True,
                    protocol_note='已从雷柏官方定义的 07 号状态报告确认型号、电量和充电状态，无需长期观察。')
    if backend and backend not in ('nova5','nova5_usb','scyrox'):
        from worker import probe
        readings=probe(group)
        valid=[r for r in readings if r.get('connected') is True and r.get('confidence')=='confirmed' and
               (r.get('percent') is not None or r.get('battery_grade'))]
        if len(valid)!=1:raise ValueError('已识别状态通道，但本次没有唯一有效电量；请唤醒设备或切换连接后重试。')
        r=valid[0]
        return dict(timestamp=time.time(),hex='',length=0,charging=r.get('charging'),percent=r.get('percent'),
                    battery_grade=r.get('battery_grade',''),backend=backend,vid=d['vid'],pid=d['pid'],name=r.get('name',d['name']),
                    remote_confirmed=True,protocol_verified=True,protocol_note='已通过现有电池通道验证；无需插拔猜测或长时间等待。')
    if not profile or profile.get('backend')!=backend or backend not in ('nova5','nova5_usb','scyrox'):
        from feature_reports import get_feature
        data,chosen=get_feature(infos,channel,reject_blank=True)
        return {'timestamp':time.time(),'hex':data.hex(' '),'length':len(data),'charging':None,'percent':None,
                'interface':chosen['interface'],'usage_page':chosen['usage_page'],'usage':chosen['usage'],
                'backend':'feature-get','vid':d['vid'],'pid':d['pid'],'name':d['name'],'channel':chosen,
                'remote_confirmed':False}
    if backend in ('nova5','nova5_usb'):
        iface=3 if backend=='nova5' else 0
        matching=[i for i in infos if i.get('interface_number')==iface and i.get('usage_page')==0xffc0 and i.get('usage')==1]
        if len(matching)!=1:raise ValueError('状态接口不唯一或不可用。')
        data=query(matching[0],bytes([0,0xb0])+bytes(62),0xb0)
        parsed=parse_nova5(data) if backend=='nova5' else parse_nova5_usb(data)
        online,level,charging=parsed[:3]
    else:
        matching=[i for i in infos if i.get('usage_page')==0xff00 and i.get('usage')==2]
        if len(matching)!=1:raise ValueError('状态接口不唯一或不可用。')
        data=query(matching[0],scyrox_packet(),0x2e,8)
        online,level,charging,_=parse_scyrox(data)
    if not online:raise ValueError('设备未返回在线状态，可能休眠、关机或驱动占用。')
    return {'timestamp':time.time(),'hex':bytes(data).hex(' '),'length':len(data),'charging':charging,
            'percent':level,'interface':matching[0].get('interface_number'),
            'usage_page':matching[0].get('usage_page'),'usage':matching[0].get('usage'),
            'backend':backend,'vid':d['vid'],'pid':d['pid'],'name':d['name'],'remote_confirmed':True}


def compare(before,after):
    if len(before)<2 or len(after)<2:raise ValueError('每组至少需要两份完整应答。')
    groups=[]
    for samples in (before,after):
        packets=[]
        for item in samples:
            try:p=bytes.fromhex(item['hex'])
            except (ValueError,KeyError,TypeError):raise ValueError('数据包格式无效。')
            if not p or len(p)>256:raise ValueError('数据包长度无效。')
            packets.append(p)
        groups.append(packets)
    b,a=groups
    if len({len(p) for p in b+a})!=1:raise ValueError('应答长度发生变化，不能直接按偏移比较。')
    samples=before+after
    if (len({(x.get('vid'),x.get('pid'),x.get('interface'),x.get('usage_page'),x.get('usage'),x.get('backend')) for x in samples})!=1
            or any(x.get('channel')!=samples[0].get('channel') for x in samples)):
        raise ValueError('采样连接、报告 ID 或描述符发生变化，两组读数需分开验证。')
    changed=[];noise=[];battery=[]
    for i in range(len(b[0])):
        bv=[p[i] for p in b];av=[p[i] for p in a]
        if len(set(bv))==len(set(av))==1:
            mask=bv[0]^av[0]
            if mask:changed.append({'offset':i,'mask':mask,'before':bv[0],'after':av[0]})
        else:
            noise.append(i)
            if (all(0<=x<=100 for x in bv+av) and all(x>=y for x,y in zip(bv,bv[1:])) and
                all(x<=y for x,y in zip(av,av[1:])) and av[-1]>av[0]):
                battery.append({'offset':i,'current':av[-1],'confidence':'低','reason':'短样本单调变化，仅供排查'})
    return {'stable_changed':changed,'unstable_offsets':noise,'battery_candidates':battery,
            'confidence':'低','note':'插拔变化可能来自无线状态、序号、校验和等；候选并非电量证明。'}
