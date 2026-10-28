"""Conservative automatic supply detection and persistent per-device corrections."""
from dataclasses import replace
import re

DEVICE_MODES=('wired','battery')
WIRELESS_WORDS=('wireless','receiver','dongle','bluetooth','hyperspeed','lightspeed','2.4','无线','双模','三模','接收器')


def wired_evidence(profile,name,interfaces,backend='',receiver=False):
    if any(info.get('bus_type')==2 for info in interfaces):return ''
    if profile and profile.get('wired'):
        return '明确无电池型号目录 + 本机 USB 设备节点'
    # 0416:0110 belongs to a shared OEM VID; require the actual product AND
    # manufacturer, not the numeric ID alone, before classifying it as wired.
    if (not backend and not receiver and str(name).strip().casefold()=='made68pro+ pl' and any(
            info.get('vendor_id')==0x0416 and info.get('product_id')==0x0110
            and str(info.get('manufacturer_string') or '').strip().casefold()=='melgeek'
            and info.get('bus_type')==1 for info in interfaces)):
        return 'MelGeek MADE68 PRO+ 明确型号名称、厂商和 USB 接口'
    text=str(name).casefold()
    # USB transport, a failed query, or an absent battery interface alone cannot
    # distinguish a wired mouse from a proprietary wireless receiver.
    if backend or receiver or any(word in text for word in WIRELESS_WORDS):return ''
    batteryless=any(word in text for word in ('battery-free','batteryless','no battery','无电池'))
    if any(info.get('bus_type')==1 for info in interfaces) and batteryless:
        return '产品名称明确标注无电池 + USB 连接信息'
    return ''


def as_wired(device,evidence):
    return replace(device,power_mode='wired',connected=True if device.present else False,
        percent=None,last_percent=None,charging=None,voltage_mv=None,observed_at=0,monotonic_at=0,
        transport='有线 USB',confidence='confirmed',battery_support='not-applicable',evidence=evidence,
        note='有线供电、无电池；电量与充电状态不适用，不参与最低电量计算。')


def apply_mode(device,mode,backend=''):
    if device.kind=='auxiliary':return device
    if mode=='wired':return as_wired(device,'用户指定：有线供电 / 无电池')
    if mode=='battery':
        reset=device.power_mode=='wired'
        return replace(device,power_mode='battery',
            connected=(None if device.present else False) if reset else device.connected,
            confidence='unknown' if reset else device.confidence,
            transport='USB / 连接方式待确认' if reset else device.transport,
            battery_support='supported' if backend else 'identify-only' if reset else device.battery_support,
            evidence='用户指定：电池设备',note='已指定为电池设备；电量仍需有效协议应答，未知型号不会填充猜测值。')
    return device


def apply_saved_modes(store,preferences):
    modes=preferences.get('device_modes',{})
    for key,mode in modes.items():
        if key in store.devices:store.devices[key]=apply_mode(store.devices[key],mode)


def bind_groups(groups,store,preferences):
    """Apply corrections after key migration, so changing USB ports keeps them."""
    records={d.identity:d for d in store.snapshot() if d.present}
    bound=[]
    for group in groups:
        group=dict(group);device=records.get(group['device']['identity'])
        if device:
            device=apply_mode(device,preferences.get('device_modes',{}).get(device.key),group.get('backend',''))
            store.devices[device.key]=device;group['device']=device.to_dict()
            if device.power_mode=='wired' or device.kind=='auxiliary':group['backend']=''
        bound.append(group)
    return bound
