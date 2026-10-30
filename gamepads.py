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
    if (xinput or {}).get('battery_type')==1 and row.get('wireless') is False and (remain,full)==(1000,1000) and row.get('rate') is None:
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
    if count!=1:
        result['note']='检测到相同 VID/PID 的多只手柄；标准 API 无法唯一对应实物，本次不分配电量以防错配。'
        return result
    # A receiver can expose a native control VID and a virtual XInput VID.
    # Inventory only combines them after proving a shared physical parent.
    identities={(vid,pid)}|{(i['vendor_id'],i['product_id']) for i in infos}
    slots=xinput_snapshot()
    matching_slots=[s for s in slots if (s.get('vid'),s.get('pid')) in identities]
    slot=matching_slots[0] if len(matching_slots)==1 else None
    if not matching_slots and (vid,pid) in ((0x20dd,0x5134),(0x413d,0x2106)):
        result['note']='接收器控制接口仍接入，未检测到对应 XInput 会话；可能休眠、关闭或切换了模式。仅此控制接口没有可验证的电量。'
        return result
    from battery_backends.wgi import query
    diag=[];controllers=query(diag)
    if diagnostics is not None:diagnostics.extend(diag[:8])
    matching_wgi=[c.raw for c in controllers or [] if (c.raw.get('vid'),c.raw.get('pid')) in identities]
    wgi=matching_wgi[0] if len(matching_wgi)==1 else None
    battery=wgi_battery(wgi,slot)
    if battery:
        result.update(percent=battery[0],charging=battery[1],connected=True,confidence='confirmed',
                      source='Windows.Gaming.Input · BatteryReport',evidence='唯一 VID/PID 与有效电池容量报告',
                      note='由 Windows 剩余容量 / 满充容量换算；精度取决于手柄驱动。')
        return result
    if slot:
        typ=slot.get('battery_type');grade=GRADES.get(slot.get('battery_level'))
        if typ in (2,3) and grade:
            result.update(battery_grade=grade,connected=True,confidence='confirmed',source='XInput 四档电池状态',
                          evidence='XInput 扩展能力 VID/PID 唯一匹配',note='XInput 只提供耗尽 / 低 / 中 / 高四档，不换算成虚构百分比，不参与最低电量与预测。')
        elif typ==1:
            result['note']='XInput 返回 WIRED；接收器也会这样上报，不能据此认定无电池或满电。需要该型号的专用电量协议。'
            if wgi and (wgi.get('remain'),wgi.get('full'))==(1000,1000):
                result['note']+=' Windows 同时返回固定 1000/1000 容量且无功率信息，存在占位值风险，未采用为 100%。'
        elif typ==0:
            result['note']='XInput 未返回电池；这不能单独证明手柄关机，已保留最后有效电量。'
    elif vid in (0x20bc,0x20dd):
        result['note']='北通当前模式未暴露可用电池通道；公开鲲鹏20协议不能直接套用到 KP50B。'
    return result
