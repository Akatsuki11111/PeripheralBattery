"""Small strict status protocols for locally tested and explicitly listed mice."""
import datetime as dt
import json
import re
import time
import hid
from models import valid_percent


def parse_razer(text, fallback_time):
    snapshot, timestamp = None, fallback_time
    for line in text.splitlines():
        match = re.search(r'info:\s*Device\s+(\[.*)',line)
        if not match:
            continue
        try:
            candidate = json.loads(match[1])
            if not isinstance(candidate,list):
                continue
            snapshot = [item for item in candidate if isinstance(item,dict) and item.get('hasBattery','powerStatus' in item)]
            stamp = re.search(r'\[(\d{4}/\d\d/\d\d \d\d:\d\d:\d\d(?:\.\d+)?)\]',line)
            timestamp = dt.datetime.fromisoformat(stamp[1].replace('/','-')).timestamp() if stamp else fallback_time
        except (ValueError,TypeError):
            continue
    return snapshot,timestamp


def query(info,packet,command,report_id=None,timeout=1.2):
    handle=hid.device()
    try:
        handle.open_path(info['path'])
        handle.write(packet)
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            remaining=deadline-time.monotonic()
            data=handle.read(128,max(1,min(100,int(remaining*1000))))
            if data and ((report_id is None and data[0]==command) or
                         (report_id is not None and len(data)>1 and data[0]==report_id and data[1]==command)):
                return data
        raise TimeoutError('设备未返回状态，可能休眠或驱动占用接口。')
    finally:
        handle.close()


def parse_nova5(data):
    if len(data)<16 or data[0]!=0xb0:
        raise ValueError('Nova 5 状态应答不匹配')
    online=data[1]!=2
    level=valid_percent(data[3])
    if online and level is None:
        raise ValueError('Nova 5 电量超出有效范围')
    return online,level if online else None,data[4]==1,level


def parse_nova5_usb(data):
    # On the directly attached Nova 5, byte 1 describes the radio link, not
    # whether the USB headset is present. The battery and charge bytes still
    # report the headset's live status when that radio link is off.
    if len(data)<16 or data[0]!=0xb0 or data[4] not in (0,1):
        raise ValueError('Nova 5 USB 状态应答不匹配')
    level=valid_percent(data[3])
    if level is None:raise ValueError('Nova 5 USB 电量超出有效范围')
    return True,level,data[4]==1,''


def scyrox_packet():
    packet=bytearray(64)
    packet[:4]=bytes([8,0x2e,0,3]);packet[-1]=sum(packet)&255
    return packet


def parse_scyrox(data):
    if len(data)!=64 or data[0]!=8 or bytes(data[1:4])!=bytes([0x2e,0,3]):
        raise ValueError('Scyrox 应答长度 / 命令不匹配')
    if data[62]!=0 or (sum(data[:-1])&255)!=data[-1]:
        raise ValueError('Scyrox 应答校验失败或设备忙碌')
    payload=data[1:]
    online=payload[5]==1
    level=valid_percent(payload[3]) if online else None
    if online and level is None:
        raise ValueError('Scyrox 电量超出有效范围')
    return online,level,payload[4]==1,f'{payload[6]|payload[7]<<8}.{payload[8]|payload[9]<<8}'


def parse_nordic52(data):
    if len(data)!=17 or data[:2]!=[8,4] or sum(data)&255!=0x55:
        raise ValueError('Nordic52 电量应答校验失败')
    level=valid_percent(data[6]);voltage=(data[8]<<8)|data[9]
    if level is None:
        raise ValueError('Nordic52 电量超出有效范围')
    if voltage==0:
        return False,None,None,None
    if not 2000<=voltage<=5000:
        raise ValueError('Nordic52 电压校验失败')
    return True,level,bool(data[7]),voltage


def read_local(backend,infos):
    if backend=='scyrox':
        info=next((i for i in infos if i.get('usage_page')==0xff00 and i.get('usage')==2),None)
        if info is None:raise ValueError('未找到 Scyrox 供应商状态接口')
        return parse_scyrox(query(info,scyrox_packet(),0x2e,8))
    if backend=='nova5':
        info=next((i for i in infos if i.get('interface_number')==3 and i.get('usage_page')==0xffc0),None)
        if info is None:raise ValueError('未找到 Nova 5 状态接口')
        online,level,charging,last=parse_nova5(query(info,bytes([0,0xb0])+bytes(62),0xb0))
        return online,level,charging,''
    if backend=='nova5_usb':
        info=next((i for i in infos if i.get('interface_number')==0 and i.get('usage_page')==0xffc0),None)
        if info is None:raise ValueError('未找到 Nova 5 USB 状态接口')
        return parse_nova5_usb(query(info,bytes([0,0xb0])+bytes(62),0xb0))
    if backend=='nordic52':
        info=next((i for i in infos if i.get('usage_page')==0xff02 and i.get('usage')==2),None)
        if info is None:raise ValueError('未找到 Nordic52 电量接口')
        return parse_nordic52(query(info,bytes([8,4])+bytes(14)+bytes([0x49]),4,8))
    raise ValueError('Unknown local protocol')
