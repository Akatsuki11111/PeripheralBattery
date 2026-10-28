"""Conservative status-report research; never interrogate unknown HID protocols."""
from catalog import device_profile
from inventory import enumerate_groups,decode_info
from protocols import query,parse_nova5,parse_nova5_usb,parse_scyrox,scyrox_packet
import time


def research_devices(devices,include_supported=False):
    result=[]
    for d in devices:
        if not d.present or d.brand=='Unknown' or d.kind=='auxiliary' or d.power_mode=='wired' or d.connected is False:continue
        profile=device_profile(d.vid,d.pid)
        known=bool((profile or {}).get('backend')) or d.usable or d.last_observed_at>0
        if not known or include_supported and d.connected is True:result.append(d)
    return result


def sample(identity,channel=None):
    groups=[g for g in enumerate_groups() if g['device'].get('identity')==identity]
    if len(groups)!=1:raise ValueError('设备已经断开、重新枚举或身份不唯一，请重新选择。')
    group=groups[0];d=group['device'];backend=group['backend'];profile=device_profile(d['vid'],d['pid'])
    infos=[decode_info(x) for x in group['infos']]
    if not profile or profile.get('backend')!=backend or backend not in ('nova5','nova5_usb','scyrox'):
        from feature_reports import get_feature
        data,chosen=get_feature(infos,channel)
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
    if len({(x.get('vid'),x.get('pid'),x.get('interface'),x.get('usage_page'),x.get('usage'),x.get('backend')) for x in before+after})!=1:
        raise ValueError('采样接口或设备身份不一致，不能比较。')
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
