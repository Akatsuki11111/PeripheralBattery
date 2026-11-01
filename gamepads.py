"""Controller battery channels. No mode switches, rumble, or saved input data.

References and supported/unsupported modes are listed in GAMEPADS.md. XInput
grades are deliberately not invented percentages. Never match devices by order.
"""
import ctypes as C
import math
import time
import zlib
from functools import lru_cache

GRADES={0:'耗尽',1:'低',2:'中',3:'高'}
SONY_DS4={0x05c4,0x09cc,0x05c5}
SONY_DS5={0x0ce6,0x0df2}
NINTENDO={0x2006,0x2007,0x2009}
EIGHTBITDO={0x6000,0x6100,0x6001,0x6101,0x6003,0x6006,0x6009}
# USB, Bluetooth and BLE identities of the same Microsoft model families.
# Xbox 360 and different Elite/Adaptive generations must never be interchanged.
XBOX_FAMILIES=({0x02d1,0x02dd},{0x02ea,0x02e0,0x02fd,0x0b20},
               {0x02e3},{0x0b00,0x0b05,0x0b22},
               {0x0b12,0x0b13},{0x0b0a,0x0b0c,0x0b21})


def same_model(a,b):
    if a==b:return True
    known=set().union(*XBOX_FAMILIES)
    if a[0]==b[0]==0x045e and (a[1]==0x02ff and b[1] in known or b[1]==0x02ff and a[1] in known):return True
    return a[0]==b[0]==0x045e and any(a[1] in f and b[1] in f for f in XBOX_FAMILIES)


def windows_snapshot(diagnostics=None):
    from battery_backends.wgi import query
    diag=[];controllers=query(diag)
    if diagnostics is not None:diagnostics.extend(diag[:8])
    return {'at':time.time(),'mono':time.monotonic(),'wgi':[c.raw for c in controllers or []],
            'slots':xinput_snapshot()}


def augment_inventory(groups, snapshot=None):
    """Include GIP/WGI controllers even when they have no hidapi collection.

    Native IDs are opaque application-local tokens, never PnP/container paths.
    A slot without a stable device identity is visible but its battery is not
    persisted across reconnection, because XInput slot numbers can be reassigned.
    """
    from catalog import recognize,device_profile
    from identity import digest
    from models import Device
    snapshot=windows_snapshot() if snapshot is None else snapshot
    pads=[g for g in groups if g['device']['kind']=='gamepad']
    # Two identical HID units cannot be linked to WGI IDs by array order. If
    # every unit has its own valid native battery report, represent those native
    # identities instead, retaining the original HID path only when necessary.
    pairs={(g['device']['vid'],g['device']['pid']) for g in pads}
    for pair in pairs:
        hid_groups=[g for g in pads if (g['device']['vid'],g['device']['pid'])==pair]
        native=[r for r in snapshot['wgi'] if (r.get('vid'),r.get('pid'))==pair]
        if (len(hid_groups)>1 and len(native)==len(hid_groups) and
                len({r.get('id_hash') for r in native})==len(native) and
                all(r.get('id_hash') and wgi_battery(r) for r in native)):
            groups[:]=[g for g in groups if g not in hid_groups]
    pads=[g for g in groups if g['device']['kind']=='gamepad']
    for g in pads:g['controller_snapshot']=snapshot
    def matches(pair):
        return [g for g in pads if any(same_model(pair,p) for p in group_identities(g))]
    for row in snapshot['wgi']:
        pair=(row.get('vid',0),row.get('pid',0));token=row.get('id_hash')
        if matches(pair) or not token:continue
        identifier=digest('wgi:'+token)
        brand,_=recognize(*pair,'',str(row.get('name') or 'Controller'))
        name=str(row.get('name') or 'Windows 手柄')
        if name.casefold() in ('windows 手柄','xbox wireless controller','xbox controller','controller','hid-compliant game controller'):
            name=(device_profile(*pair) or {}).get('name',name)
        d=Device('device:'+identifier,brand['name'] if brand else 'Unknown',
                 name[:240],'gamepad',vid=pair[0],pid=pair[1],
                 identity=identifier,serial_hash=token,confidence='unknown',battery_support='supported',
                 transport='Windows 无线手柄' if row.get('wireless') else 'Windows 手柄接口',
                 receiver=row.get('wireless') is True,last_seen=time.time(),
                 source='Windows.Gaming.Input · 原生设备清单')
        groups.append({'device':d.to_dict(),'infos':[],'backend':'gamepad','controller_count':1,
                       'wgi_id':token,'controller_snapshot':snapshot})
    # WGI may be unavailable. XInput still sees up to four active gamepad slots.
    all_pads=[g for g in groups if g['device']['kind']=='gamepad']
    for row in snapshot['slots']:
        pair=(row.get('vid',0),row.get('pid',0))
        if any(any(same_model(pair,p) for p in group_identities(g)) for g in all_pads):continue
        identifier=digest('xinput-slot:'+str(row['slot']))
        brand,_=recognize(*pair,'','Controller')
        name='Xbox 手柄' if pair[0]==0x045e else 'XInput 兼容手柄'
        d=Device('device:'+identifier,brand['name'] if brand else 'Unknown',f'{name} · 插槽 {row["slot"]+1}',
                 'gamepad',vid=pair[0],pid=pair[1],identity=identifier,confidence='unknown',
                 battery_support='supported',transport='XInput 手柄接口',last_seen=time.time(),
                 battery_cache=False,source='XInput 原生活动插槽')
        groups.append({'device':d.to_dict(),'infos':[],'backend':'gamepad','controller_count':1,
                       'xinput_slot':row['slot'],'controller_snapshot':snapshot})
    pads=[g for g in groups if g['device']['kind']=='gamepad']
    for g in pads:
        g['controller_peers']=[list(p) for other in pads for p in group_identities(other)]
        g['controller_family_count']=sum(any(same_model(p,q) for p in group_identities(g) for q in group_identities(other)) for other in pads)
    return groups


def group_identities(group):
    base=group['device']
    return {(base['vid'],base['pid'])}|{(i['vendor_id'],i['product_id']) for i in group.get('infos',[])}


class Battery(C.Structure):
    _fields_=[('type',C.c_ubyte),('level',C.c_ubyte)]


class Caps(C.Structure):
    _fields_=[('type',C.c_ubyte),('subtype',C.c_ubyte),('flags',C.c_uint16),
              ('supported_controls',C.c_ubyte*12),('supported_vibration',C.c_ubyte*4)]


class CapsEx(C.Structure):
    _fields_=[('caps',Caps),('vid',C.c_uint16),('pid',C.c_uint16),('revision',C.c_uint16),
              ('reserved',C.c_uint16),('reserved2',C.c_uint32)]


@lru_cache(maxsize=1)
def xinput_api():
    # Absolute System32 lookup prevents a same-directory replacement DLL.
    try:
        dll=C.WinDLL('xinput1_4.dll',winmode=0x800)
        dll.XInputGetCapabilities.argtypes=[C.c_uint32,C.c_uint32,C.POINTER(Caps)]
        dll.XInputGetCapabilities.restype=C.c_uint32
        dll.XInputGetBatteryInformation.argtypes=[C.c_uint32,C.c_ubyte,C.POINTER(Battery)]
        dll.XInputGetBatteryInformation.restype=C.c_uint32
        try:
            extended=dll[108]
            extended.argtypes=[C.c_uint32,C.c_uint32,C.c_uint32,C.POINTER(CapsEx)]
            extended.restype=C.c_uint32
        except (AttributeError,OSError):extended=None
        return dll,extended
    except (OSError,AttributeError):return None,None


def xinput_snapshot():
    dll,extended=xinput_api()
    if dll is None:return []
    rows=[]
    for slot in range(4):
        caps=Caps()
        if dll.XInputGetCapabilities(slot,0,C.byref(caps))!=0:continue
        row={'slot':slot,'vid':0,'pid':0,'flags':caps.flags}
        if extended is not None:
            extra=CapsEx()
            if extended(1,slot,0,C.byref(extra))==0:row.update(vid=extra.vid,pid=extra.pid)
        battery=Battery()
        if dll.XInputGetBatteryInformation(slot,0,C.byref(battery))==0:
            row.update(battery_type=battery.type,battery_level=battery.level)
        rows.append(row)
    return rows


def unique_match(rows,vid,pid,count):
    if count!=1:return None
    matches=[r for r in rows if r.get('vid')==vid and r.get('pid')==pid]
    return matches[0] if len(matches)==1 else None


def wgi_battery(row,xinput=None):
    """Validate Windows capacities; reject the known synthetic wired full value."""
    if not isinstance(row,dict):return None
    status=str(row.get('status','')).casefold()
    remain,full=row.get('remain'),row.get('full')
    if status not in ('charging','discharging','idle'):return None
    if not all(type(n) in (int,float) and math.isfinite(n) for n in (remain,full)):return None
    if not 0<full<=1e9 or not 0<=remain<=full:return None
    if status!='charging' and row.get('wireless') is False and (remain,full)==(1000,1000) and row.get('rate') is None:
        return None
    return round(remain*100/full),status=='charging'


def parse_passive(vid,pid,packet,bluetooth=False):
    """Extract only battery fields; report payloads never leave this function."""
    data=bytes(packet)
    if not data:return None
    if vid==0x054c and pid in SONY_DS4|SONY_DS5:
        ds5=pid in SONY_DS5
        rid,offset=(0x31,54) if ds5 and bluetooth else (0x11,32) if bluetooth else (1,53 if ds5 else 30)
        length=78 if bluetooth else 64
        if data[0]!=rid or len(data)<length:return None
        if bluetooth and zlib.crc32(b'\xa1'+data[:74])!=int.from_bytes(data[74:78],'little'):return None
        value=data[offset];level=value&15
        if ds5:
            state=value>>4
            if level>10 or state not in (0,1,2):return None
            return min(level*10+5,100),state==1,'Sony 十档电量，非精确百分比'
        if level>11:return None
        return min(level,10)*10,bool(value&16) and level<11,'DualShock 十档电量，插线位不证明充电电流'
    if vid==0x057e and pid in NINTENDO:
        if len(data)<49 or data[0] not in (0x21,0x30,0x31):return None
        level=(data[2]&0xe0)>>4
        if level>8:return None
        return level*100//8,bool(data[2]&16) and level<8,'Nintendo 五档电量，非精确百分比'
    if vid==0x2dc8 and pid in EIGHTBITDO:
        expected=4 if pid==0x6009 or not bluetooth else 1
        if len(data)<16 or data[0]!=expected:return None
        level=data[14]&127
        # Simple mode can be zero-padded to the same size. Zero is ambiguous.
        if not 1<=level<=100:return None
        return level,bool(data[14]&128),''
    return None


def parse_xbox_bluetooth(packet):
    """Xbox report 04 is a level, not a percentage. USB does not imply charge.

    Protocol facts: SDL HIDAPI Xbox One and xpadneo's power report definitions.
    No driver code is incorporated. Ignore unrelated input reports entirely.
    """
    data=bytes(packet)
    if len(data)<2 or data[0]!=4:return None
    flags=data[1]
    if flags&0x60 or not flags&0x80:return None
    mode=(flags>>2)&3
    if mode==0:return {'battery_grade':'','charging':None,'external_power':True}
    return {'battery_grade':('低','中','高','满')[flags&3],
            'charging':bool(flags&0x10) if mode==2 else None,'external_power':False}


def xbox_bluetooth_battery(infos):
    from controller_windows import XBOX_BT_PIDS,is_bluetooth
    import hid
    for info in infos[:8]:
        if info.get('vendor_id')!=0x045e or info.get('product_id') not in XBOX_BT_PIDS:continue
        if info.get('usage_page')!=1 or info.get('usage') not in (4,5) or not is_bluetooth([info]):continue
        device=None
        try:
            device=hid.device();device.open_path(info['path'])
            # Bounded passive input only; no rumble, output or mode-change report.
            end=time.monotonic()+.35
            for _ in range(20):
                if time.monotonic()>=end:break
                result=parse_xbox_bluetooth(device.read(128,20))
                if result:return result
            # Some firmware sends 04 only when power changes. A read-only
            # GET_INPUT_REPORT of that known ID can retrieve its current state.
            # Unsupported calls are contained by the terminable probe worker.
            get_input=getattr(device,'get_input_report',None)
            if get_input:
                result=parse_xbox_bluetooth(get_input(4,2))
                if result:return result
        except (OSError,ValueError):pass
        finally:
            if device is not None:device.close()
    return None


def passive_battery(infos):
    import hid
    for info in infos[:8]:
        if info.get('usage_page')!=1 or info.get('usage') not in (4,5,8):continue
        vid,pid=info['vendor_id'],info['product_id']
        if not (vid==0x054c and pid in SONY_DS4|SONY_DS5 or vid==0x057e and pid in NINTENDO or vid==0x2dc8 and pid in EIGHTBITDO):continue
        device=None
        try:
            device=hid.device();device.open_path(info['path'])
            end=time.monotonic()+.4
            for _ in range(16):
                if time.monotonic()>=end:break
                packet=device.read(128,40)
                result=parse_passive(vid,pid,packet,info.get('bus_type')==2)
                if result:return result
        except (OSError,ValueError):pass
        finally:
            if device is not None:device.close()
    return None


def query_gamepad(group,infos,diagnostics=None):
    base=group['device'];vid,pid=base['vid'],base['pid']
    count=group.get('controller_count',0)
    result={'name':base['name'],'kind':'gamepad','percent':None,'charging':None,'connected':None,
            'battery_grade':'','confidence':'unknown','battery_support':'supported','approximate':'',
            'observed_at':time.time(),'monotonic_at':time.monotonic(),'source':'手柄标准电池通道',
            'evidence':'USB/HID 接入；没有据此推断远端开关机',
            'note':'已识别手柄；当前连接模式未提供可验证的电量。'}
    # Physical HID reports are intrinsically associated, even with equal VID/PID.
    passive=passive_battery(infos)
    if passive:
        level,charging,approx=passive
        result.update(percent=level,charging=charging,connected=True,confidence='confirmed',approximate=approx,
                      source='已知手柄 HID 电池字段 · 被动读取',evidence='白名单型号与报告格式匹配',
                      note='仅提取电池字段，不保存手柄按键或摇杆数据；分档读数不参与最低电量和预测。' if approx else '设备返回有效电池字段。')
        return result
    native_id=group.get('wgi_id')
    if count!=1 and not native_id:
        result['note']='检测到相同 VID/PID 的多只手柄；标准 API 无法唯一对应实物，本次不分配电量以防错配。'
        return result
    # A receiver can expose a native control VID and a virtual XInput VID.
    # Inventory only combines them after proving a shared physical parent.
    identities=group_identities(group)
    snapshot=group.get('controller_snapshot')
    if not isinstance(snapshot,dict) or not 0<=time.monotonic()-snapshot.get('mono',0)<5:
        snapshot=windows_snapshot(diagnostics)
    slots=snapshot['slots']
    matching_slots=[s for s in slots if (s.get('vid'),s.get('pid')) in identities]
    slot=matching_slots[0] if len(matching_slots)==1 else None
    if 'xinput_slot' in group:
        slot=next((s for s in slots if s.get('slot')==group['xinput_slot']),None)
    elif native_id and group.get('controller_family_count',1)>1:slot=None
    def one_model_match(rows):
        candidates=[r for r in rows if any(same_model((r.get('vid'),r.get('pid')),p) for p in identities)]
        peers={tuple(p) for p in group.get('controller_peers',[])}
        # Only a single physical group in that model family may use an alias.
        competing=[p for p in peers if p not in identities and any(same_model(p,i) for i in identities)]
        return candidates[0] if len(candidates)==1 and not competing and group.get('controller_family_count',1)==1 else None
    if slot is None and not matching_slots:slot=one_model_match(slots)
    rows=snapshot['wgi']
    if native_id:
        matches=[r for r in rows if r.get('id_hash')==native_id]
    else:matches=[r for r in rows if r.get('vid') and r.get('pid') and (r.get('vid'),r.get('pid')) in identities]
    wgi=matches[0] if len(matches)==1 else None
    if wgi is None and not matches and not native_id:wgi=one_model_match([r for r in rows if r.get('vid') and r.get('pid')])
    if not matching_slots and not slot and not wgi and (vid,pid) in ((0x20dd,0x5134),(0x413d,0x2106)):
        result['note']='接收器控制接口仍接入，未检测到对应 XInput 会话；可能休眠、关闭或切换了模式。仅此控制接口没有可验证的电量。'
        return result
    battery=wgi_battery(wgi,slot)
    if battery:
        result.update(percent=battery[0],charging=battery[1],connected=True,confidence='confirmed',
                      source='Windows.Gaming.Input · BatteryReport',evidence='唯一 VID/PID 与有效电池容量报告',
                      note='由 Windows 剩余容量 / 满充容量换算；精度取决于手柄驱动。')
        result.update(observed_at=snapshot['at'],monotonic_at=snapshot['mono'])
        return result
    from controller_windows import is_bluetooth,bluetooth_properties,bluetooth_state
    if is_bluetooth(infos,vid,pid):
        properties=bluetooth_properties(infos)
        state=bluetooth_state(properties['address'],properties['le']) if not wgi or properties['percent'] is None else {'connected':True,'percent':None}
        connected=state['connected']
        if connected is None and wgi:connected=True
        percent=state['percent'] if state['percent'] is not None else properties['percent']
        if connected is True and percent is not None:
            result.update(percent=percent,connected=True,confidence='confirmed',
                          source='Windows 蓝牙设备电池属性',evidence='本设备节点或蓝牙父节点的电量 + 当前连接状态',
                          approximate='Windows 蓝牙驱动电量，精度由驱动决定',
                          note='采用 Windows 设备电池属性；系统可能返回分档值。未把已配对缓存当作在线证据。')
            return result
        report=xbox_bluetooth_battery(infos) if not (slot and slot.get('battery_type') in (2,3) and slot.get('battery_level') in GRADES) else None
        if report:
            result.update(connected=True,confidence='confirmed',battery_grade=report['battery_grade'],charging=report['charging'],
                          source='Xbox 蓝牙 HID · 电池报告 0x04',evidence='微软蓝牙型号白名单与有效电源状态位',
                          note='Xbox 蓝牙四档：低 / 中 / 高 / 满；不换算成百分比。' if report['battery_grade'] else
                          '设备报告外部 USB 供电；不能据此判断电池已满或正在充电。')
            return result
        if connected is False:result['connected']=False
    if slot:
        typ=slot.get('battery_type');grade=GRADES.get(slot.get('battery_level'))
        if typ in (2,3) and grade:
            result.update(battery_grade=grade,connected=True,confidence='confirmed',source='XInput 四档电池状态',
                          evidence='XInput 扩展能力 VID/PID 唯一匹配',note='XInput 只提供耗尽 / 低 / 中 / 高四档，不换算成虚构百分比，不参与最低电量与预测。')
            result.update(observed_at=snapshot['at'],monotonic_at=snapshot['mono'])
        elif typ==1:
            result['note']='XInput 返回 WIRED；接收器也会这样上报，不能据此认定无电池或满电。需要该型号的专用电量协议。'
            if wgi and (wgi.get('remain'),wgi.get('full'))==(1000,1000):
                result['note']+=' Windows 同时返回固定 1000/1000 容量且无功率信息，存在占位值风险，未采用为 100%。'
        elif typ==0:
            result['note']='XInput 未返回电池；这不能单独证明手柄关机，已保留最后有效电量。'
    elif vid in (0x20bc,0x20dd):
        result['note']='北通当前模式未暴露可用电池通道；公开鲲鹏20协议不能直接套用到 KP50B。'
    if wgi and result['connected'] is None:result['connected']=True
    return result
