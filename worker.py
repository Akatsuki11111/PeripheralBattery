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
from settings import atomic_json,data_dir,read_json,redact

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
    if backend=='rog_omni_mini':
        from rog_omni import query
        records=query(infos)
    elif backend in ('scyrox','nova5','nova5_usb','nordic52'):
        online,level,charging,firmware=read_local(backend,infos)
        records=[{'name':base['name'],'kind':base['kind'],'level':level,'charging':charging,
                  'online':online,'source':backend,'firmware':firmware if backend!='nordic52' else '',
                  'voltage_mv':firmware if backend=='nordic52' else None}]
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
    if operation=='inventory':
        return {'groups':enumerate_groups(request.get('overrides',{}))}
    if operation=='probe':
        diagnostics=[] if request.get('diagnostics') is True else None
        readings=probe(request['group'],diagnostics)
        return {'readings':readings,**({'diagnostics':diagnostics} if diagnostics is not None else {})}
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
        result={'nonce':request['nonce'],'ok':False,'error':redact(f'{type(error).__name__}: {error}')}
    atomic_json(output,result)
    return 0
