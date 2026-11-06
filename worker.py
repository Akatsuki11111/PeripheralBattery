"""No GUI: one bounded operation per separately terminable worker process."""
from dataclasses import asdict
import importlib
import os
from pathlib import Path
import re
import time
from inventory import decode_info,enumerate_groups
from models import valid_percent
from protocols import read_local,parse_razer
from settings import atomic_json,data_dir,read_json,redact,EXPERIMENTAL_ENABLED

PROVIDERS={
 'razer':('razer','RazerProvider'),'logitech':('logitech','LogitechProvider'),
 'logitech_centurion':('logitech_centurion','LogitechCenturionProvider'),
 'steelseries':('steelseries','SteelSeriesProvider'),'steelseries_elite':('steelseries_elite','SteelSeriesEliteProvider'),
 'asus':('asus','AsusProvider'),'pulsar':('pulsar','PulsarProvider'),
 'lamzu':('lamzu','LamzuProvider'),'mchose':('mchose','MchoseProvider'),
 'wlmouse':('wlmouse','WLmouseProvider'),'gwolves':('gwolves','GWolvesProvider'),
 'corsair':('corsair','CorsairProvider'),'keychron':('keychron','KeychronProvider'),
 'lofree':('lofree','LofreeProvider'),'nzxt':('nzxt','NzxtProvider'),
 'am_infinity':('am_infinity','AmInfinityProvider')}


def log_last_known(base):
    if base.get('brand')!='Razer':return {}
    try:
        folder=Path(os.environ.get('LOCALAPPDATA',Path.home()/'AppData/Local'))/'Razer/RazerAppEngine/User Data/Logs'
        files=sorted(folder.glob('systray_systrayv2*.log'),key=lambda p:p.stat().st_mtime,reverse=True)
        for path in files[:2]:
            with path.open('rb') as stream:
                stream.seek(max(0,path.stat().st_size-1024*1024));text=stream.read().decode('utf-8',errors='replace')
            snapshot,stamp=parse_razer(text,path.stat().st_mtime)
            if snapshot is None:continue
            matching=[]
            for item in snapshot:
                names=item.get('name') or {}
                name=names.get('en','') if isinstance(names,dict) else str(names)
                if name.casefold()==base.get('name','').casefold():matching.append(item)
            if len(matching)==1 and 0<=time.time()-stamp<86400:
                power=matching[0].get('powerStatus')
                if isinstance(power,dict):
                    level=valid_percent(power.get('level'))
                    if level is not None:return {'last_percent':level,'note':f'雷云缓存为 {level}%（约 {int((time.time()-stamp)/60)} 分钟前）；非实时，不参与最低电量计算。'}
            return {}
    except (OSError,ValueError,TypeError):pass
    return {}


def probe(group,diagnostics=None):
    infos=[decode_info(item) for item in group['infos']]
    base=group['device'];backend=group['backend']
    records=[]
    if backend=='valkyrie_ry_usb':
        return [{'name':base['name'],'percent':None,'connected':True,'charging':None,'confidence':'unknown',
                 'source':'M5 Lite USB 设备节点','power_mode':'battery','transport':'USB（含电池）',
                 'battery_support':'identify-only','evidence':'已识别 VK M5 Lite 的 USB 型号标识',
                 'note':'USB 模式的官方代码直接填充 100%，不是电池应答，未采用。请拔线并通过 2.4G 接收器读取真实电量；当前充电标志未知。'}]
    if backend=='valkyrie_ry':
        from valkyrie_ry import query_receiver
        matching=[i for i in infos if i.get('interface_number')==2 and i.get('usage_page')==0xffff and i.get('usage')==2]
        if len(matching)!=1:raise ValueError('RY 接收器状态接口不唯一或不可用')
        result=query_receiver(matching[0]);status=result['status'];model=result['model'];model_id=result['model_id']
        reading={'name':model[1] if model else base['name'],'percent':status.percent if model else None,'connected':status.online,
                 'charging':None,'kind':'mouse','receiver':True,'transport':'2.4 GHz 接收器','power_mode':'battery',
                 'confidence':'confirmed' if status.online and model is not None else 'unknown',
                 'battery_support':'supported','source':f'RY F7 / 8F · 型号 {model_id}' if model_id else f'RY F7 离线状态 · 上次型号 {base.get("protocol_model_id") or "未知"}',
                 'observed_at':time.time(),'monotonic_at':time.monotonic(),
                 'evidence':f'官方 RY 状态协议；鼠标型号 ID {model_id}' if model_id else '接收器存在，远端鼠标未在线',
                 'note':'已确认无线在线并读取电池字段；协议未提供已验证的充电标志。' if status.online else '鼠标休眠、关闭或正使用 USB；接收器里的历史百分比未作为实时读数。'}
        if model:reading['brand']=model[0]
        elif status.online:reading.update(brand='Unknown',name=f'RY 无线鼠标（型号 ID {model_id}）',
                                         note='已确认接收器协议和鼠标在线，但该型号尚未验证电池字段，未采用为实时电量。')
        if model_id is not None:reading['protocol_model_id']=model_id
        return [reading]
    if backend=='valkyrie_m220':
        from valkyrie_m220 import query_receiver
        matching=[i for i in infos if i.get('interface_number')==2 and i.get('usage_page')==1 and i.get('usage')==0]
        if len(matching)!=1:raise ValueError('M3 系列配置接口不唯一或不可用')
        result=query_receiver(matching[0]);identity=result['identity'];model=result['model']
        code=identity.model_code.decode('ascii',errors='replace')
        # The receiver answers 0x10 without the mouse, so a reply never proves
        # presence; only link byte 1 is accepted, and only for a verified model.
        # Any other value is reported as an unconfirmed link, not as a disconnect.
        reading={'name':model[1] if model else base['name'],'percent':identity.percent if model else None,
                 'connected':True if model and identity.linked else None,'charging':None,'kind':'mouse','receiver':True,
                 'transport':'2.4 GHz 接收器','power_mode':'battery',
                 'confidence':'confirmed' if model and identity.linked else 'unknown',
                 'battery_support':'supported' if model else 'identify-only',
                 'source':'M220 0x10 身份页','firmware':identity.firmware,
                 'observed_at':time.time(),'monotonic_at':time.monotonic(),
                 'evidence':f'官方 M220 身份应答；型号代码 {code}，电量字段 {identity.percent}%，链路字节 {identity.link_raw}' if model
                            else f'官方驱动身份应答；型号代码 {code} 尚未验证，电量字段未采用',
                 'note':'已按官方驱动的同一身份页读取电量；充电标志未确认，读数只在链路字节为 1 时视为实时。' if model and identity.linked
                       else '接收器自行应答了身份查询，但链路字节不是 1：鼠标可能休眠或未建链，未作为实时读数。唤醒鼠标后的一次成功读数才会成为上次电量。' if model
                       else '已识别为瓦尔基里 M3 系列，但该型号代码的电池字段未验证，未采用为实时电量。'}
        if model:reading['brand']=model[0]
        return [reading]
    if backend=='gamepad':
        from gamepads import query_gamepad
        return [query_gamepad(group,infos,diagnostics)]
    if backend=='learned':
        if not EXPERIMENTAL_ENABLED:raise ValueError('正式版不支持实验电量映射')
        from research import sample
        from long_learning import mappings,decode_mapping
        mapping=mappings().get(base['identity'])
        if not isinstance(mapping,dict):raise ValueError('实验映射已被移除')
        response=sample(base['identity'],mapping.get('channel'));level=decode_mapping(response,mapping)
        return [{'name':base['name'],'percent':level,'connected':True if response.get('remote_confirmed') else None,
                 'charging':response.get('charging'),'confidence':'experimental','source':'本地实验映射 · 未经独立验证',
                 'evidence':'用户确认的长期相关性候选；不证明远端在线','observed_at':time.time(),
                 'monotonic_at':time.monotonic(),'battery_support':'experimental',
                 'note':'实验推测，可能是慢速计数器等字段；不参与最低电量和提醒，可在观察面板停用。'}]
    if backend=='atk_zero_plus':
        from atk_zero_plus import NAME, RECEIVER_NAME, USB_PID, read_status
        status = read_status(infos, base['pid'])
        is_zero = status.model == USB_PID or not status.online and base.get('protocol_model_id') == USB_PID
        reading = {
            'name': NAME if is_zero or not base['receiver'] else RECEIVER_NAME,
            'connected': status.online, 'percent': status.percent, 'charging': status.charging,
            'confidence': 'confirmed' if status.percent is not None else 'unknown',
            'source': 'ATK BitMouse · 只读 HID 状态',
            'transport': '2.4 GHz 接收器' if base['receiver'] else 'USB 有线（含电池）',
            'evidence': '型号码 8:1 与电池应答匹配' if status.percent is not None
                        else '接收器报告鼠标离线' if not status.online else '当前鼠标型号未适配',
            'note': '当前接入方式下由鼠标固件报告的电量。' if status.percent is not None
                    else '鼠标未通过接收器在线。' if not status.online else '接收器在线，但尚未验证此鼠标的电量。',
            'observed_at': time.time(), 'monotonic_at': time.monotonic(),
        }
        if status.model is not None:
            reading['protocol_model_id'] = status.model
        return [reading]
    if backend=='rapoo_vt7_pro_v2':
        from rapoo_vt7_pro_v2 import read_status
        status = read_status(infos, base['pid'])
        records = [{'level': status.percent if status else None,
                    'charging': status.charging if status else None,
                    'online': status.online if status else None}]
    elif backend=='rog_omni_mini':
        from rog_omni import query
        records=query(infos)
    elif backend in ('scyrox','nova5','nova5_usb','nordic52'):
        online,level,charging,detail=read_local(backend,infos)
        records=[{'name':base['name'],'kind':base['kind'],'level':level,'charging':charging,
                  'online':online,'source':backend,'firmware':detail if backend=='scyrox' else '',
                  'charge_complete':backend=='nova5_usb' and detail is True,
                  'voltage_mv':detail if backend=='nordic52' else None}]
    elif backend in PROVIDERS:
        from battery_backends import hidlist
        # Never open unrelated hardware or enumerate all devices again per provider.
        original_enumerate=hidlist.enumerate
        provider=None
        try:
            hidlist.enumerate=lambda vid=0:[item for item in infos if not vid or item['vendor_id']==vid]
            module_name,class_name=PROVIDERS[backend]
            provider=getattr(importlib.import_module('battery_backends.'+module_name),class_name)()
            records=[asdict(item) for item in provider.poll()]
        finally:
            hidlist.enumerate=original_enumerate
            if diagnostics is not None and provider is not None:
                diagnostics.extend(redact(line) for line in provider.diagnostics()[:60])
    else:
        return []
    readings=[]
    for record in records[:12]:
        level=valid_percent(record.get('level'))
        online=record.get('online')
        # An empty provider result or a receiver-only placeholder is not a battery read.
        connected=bool(online) if level is not None or online is False else None
        if not connected:level=None
        reading={'key':str(record.get('key',''))[:240], 'name':str(record.get('name') or base['name'])[:240],
                 'kind':record.get('kind') or base['kind'],'percent':level,'charging':record.get('charging') if connected else None,
                 'connected':connected,'source':backend+' · 只读 HID 状态',
                 'charge_complete':connected is True and record.get('charge_complete') is True,
                 'evidence':'设备状态应答' if connected is not None else 'USB 接口存在，未确认远端',
                 'confidence':'confirmed' if connected is True and level is not None else 'unknown',
                 'observed_at':time.time(),'monotonic_at':time.monotonic(),'battery_support':'supported',
                 'note':'设备已返回有效电量状态。' if connected else '设备休眠或关闭；不计入最低电量。' if connected is False else '本次没有获得有效状态。',
                 'firmware':str(record.get('firmware',''))[:120],'approximate':str(record.get('approx',''))[:120],
                 'voltage_mv':record.get('voltage_mv') if connected else None}
        if level is not None:reading['last_percent']=level
        elif backend=='razer':reading.update(log_last_known(base))
        readings.append(reading)
    if not readings:
        fallback={'name':base['name'],'percent':None,'connected':None,'charging':None,'confidence':'unknown',
                  'note':'ROG OMNI 仅适配单独配对的 Harpe Ace Mini；未匹配的型号或多设备组合暂不读取电量。' if backend=='rog_omni_mini'
                  else '已识别设备，但本型号没有返回可用电量；可能驱动占用、协议尚未匹配或设备休眠。'}
        fallback.update(log_last_known(base));readings=[fallback]
    return readings


def execute(request):
    operation=request.get('operation')
    if not EXPERIMENTAL_ENABLED and operation in ('research-sample','research-inspect'):
        raise ValueError('正式版不提供电量实验，请使用实验版')
    if operation=='inspect-device':
        from device_inspection import inspect_device
        return inspect_device(request.get('identity',''))
    if operation=='check-updates':
        from updates import check_updates
        from settings import VERSION
        return {'update':check_updates(VERSION,request.get('include_prereleases') is True,background=request.get('background') is True)}
    if operation=='download-update':
        from updates import download_update
        from settings import VERSION
        def progress(received,total):atomic_json(data_dir()/'workers'/(request['nonce']+'.progress.json'),{'received':received,'total':total})
        return {'download':download_update(VERSION,request.get('include_prereleases') is True,request.get('tag'),
                    data_dir()/'updates'/(request['nonce']+'.exe'),progress)}
    if operation=='inventory':
        from gamepads import augment_inventory
        return {'groups':augment_inventory(enumerate_groups(request.get('overrides',{})))}
    if operation=='probe':
        diagnostics=[] if request.get('diagnostics') is True else None
        readings=probe(request['group'],diagnostics)
        return {'readings':readings,**({'diagnostics':diagnostics} if diagnostics is not None else {})}
    if operation=='research-sample':
        from research import sample
        identity=request.get('identity','')
        if not re.fullmatch(r'[a-f0-9]{24}',identity):raise ValueError('设备标识无效')
        return {'sample':sample(identity,request.get('channel'))}
    if operation=='research-inspect':
        from research import inspect_device
        return inspect_device(request.get('identity',''))
    if operation=='test-sleep':
        # Only available to the isolated regression tests, never to normal IPC.
        if os.environ.get('PB_TEST_MODE')!='1':raise ValueError('Test operation disabled')
        atomic_json(data_dir()/'workers'/(request['nonce']+'.started.json'),{'pid':os.getpid()})
        time.sleep(60);return {}
    raise ValueError('Unsupported worker operation')


def run(request_file):
    path=Path(request_file).resolve()
    root=(data_dir()/'workers').resolve()
    if path.parent!=root or not re.fullmatch(r'[a-f0-9]{32}\.request\.json',path.name):
        return 2
    request=read_json(path,None,1_000_000)
    if not isinstance(request,dict) or request.get('nonce')!=path.name.split('.')[0]:return 2
    output=path.with_name(path.name.replace('.request.json','.result.json'))
    try:
        result={'nonce':request['nonce'],'ok':True,**execute(request)}
    except Exception as error:
        result={'nonce':request['nonce'],'ok':False,'error_type':type(error).__name__,'error':redact(f'{type(error).__name__}: {error}'),
                'user_message':redact(str(error))}
        if getattr(error,'code',None):result['error_code']=error.code
        if getattr(error,'details',None):result['feature_diagnostics']=error.details
    atomic_json(output,result)
    return 0
