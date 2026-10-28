"""Enumerate once, consolidate composite collections, and assign a safe profile."""
import re
import time
import hid
from catalog import backend_for, device_profile, kind_for, recognize
from identity import digest, metadata, physical_identity, raw_input_paths,companion_names,usb_audio_infos
from models import Device
from dataclasses import replace
from classification import as_wired,wired_evidence


def classify_auxiliary(vid,pid,name,companions):
    # ESP32 VIDs alone are not grounds to reject a real custom keyboard.
    return (vid==0x303a and pid==0x4005 and 'lifesmart' in name.casefold() and
            any('cxair_r' in value.casefold() for value in companions))


def encode_info(info):
    return {key: value.hex() if isinstance(value, bytes) else value for key, value in info.items()}


def decode_info(info):
    result = dict(info)
    if isinstance(result.get('path'), str):
        result['path'] = bytes.fromhex(result['path'])
    return result


def enumerate_groups(overrides=None):
    infos = hid.enumerate()
    infos.extend(usb_audio_infos())
    known_paths = {info['path'].decode(errors='replace').lower() for info in infos}
    for path, kind in raw_input_paths().items():
        if path in known_paths:
            continue
        match = re.search(r'vid_([0-9a-f]{4})&pid_([0-9a-f]{4})', path, re.I)
        if match:
            infos.append({'path': path.encode(), 'vendor_id': int(match[1],16), 'product_id': int(match[2],16),
                          'usage_page': 1, 'usage': 2 if kind == 'mouse' else 6, 'interface_number': -1,
                          'manufacturer_string': '', 'product_string': '', 'serial_number': '', 'bus_type': 1})
    physical = {}
    for info in infos:
        if not info.get('vendor_id'):
            continue
        meta = metadata(info['path'])
        # Razer virtual consumer-control devices are not another battery device.
        if info.get('bus_type') == 0 and not info.get('product_string'):
            continue
        token = meta['container'] or meta['physical'] or digest(info['path'])
        group = physical.setdefault((info['vendor_id'], info['product_id'], token), {'infos': [], 'metadata': []})
        group['infos'].append(info)
        group['metadata'].append(meta)
    result = []
    for group in physical.values():
        infos, metas = group['infos'], group['metadata']
        first = infos[0]
        vid, pid = first['vendor_id'], first['product_id']
        name = next((i.get('product_string') for i in infos if i.get('product_string')), '')
        manufacturer = next((i.get('manufacturer_string') for i in infos if i.get('manufacturer_string')), '')
        profile = device_profile(vid,pid)
        if not name:
            name = profile['name'] if profile else next((m.get('friendly') for m in metas if m.get('friendly')), '')
        brand, evidence = recognize(vid,pid,manufacturer,name,(overrides or {}).get(f'{vid:04X}:{pid:04X}',''))
        is_input = any(i.get('usage_page') == 1 and i.get('usage') in (2,6) for i in infos)
        is_usb_keyboard=any(i.get('usage_page')==1 and i.get('usage')==6 and i.get('bus_type')==1 for i in infos)
        is_audio=any(i.get('audio_interface') for i in infos)
        if not brand and not is_input and not is_audio:
            continue
        # Don't list unrelated USB controllers merely because ASUS/MSI made them.
        if brand and not is_input and not profile and not any(word in str(name).lower() for word in
                ('mouse','keyboard','headset','receiver','dongle','arctis','鼠标','键盘','耳机')):
            continue
        name = name or ('通用鼠标' if any(i.get('usage') == 2 for i in infos) else '通用键盘')
        kind = (profile or {}).get('kind') or kind_for(name,infos)
        brand_name = brand['name'] if brand else 'Unknown'
        identifier, serial_hash = physical_identity(infos,metas)
        backend = backend_for(vid,pid,name)
        companions=[]
        if vid==0x303a and pid==0x4005:
            parent_instance=next((m['physical'] for m in metas if m.get('physical')),'')
            companions=companion_names(parent_instance)
        auxiliary=classify_auxiliary(vid,pid,str(name),companions)
        text = str(name).lower()
        receiver = (profile or {}).get('receiver',False) or any(word in text for word in ('receiver','dongle','2.4','接收器','hyperspeed'))
        mouse_input=any(i.get('usage_page')==1 and i.get('usage')==2 for i in infos)
        if (backend=='mchose' and is_usb_keyboard and kind=='keyboard' and not receiver
                and not mouse_input and 'k7 ultra' not in text):
            # The shared MCHOSE mouse VID also appears on keyboards; never send
            # the mouse status command to a keyboard-only collection.
            backend=''
        special_input=any(word in text for word in ('barcode','scanner','card reader','cardreader','读卡','扫码','扫描仪'))
        # A keyboard may expose a mouse collection too. For an otherwise unknown
        # USB input device, retain its keyboard collection without asserting that
        # the physical device is wired or batteryless.
        if (is_usb_keyboard and not receiver and not backend and not is_audio and not special_input
                and not (profile or {}).get('kind') and not any(word in text for word in ('mouse','鼠标'))):
            kind='keyboard'
        usb_keyboard=bool(is_usb_keyboard and kind=='keyboard' and not receiver and not special_input)
        transport = 'Bluetooth' if any(i.get('bus_type') == 2 for i in infos) else '2.4 GHz 接收器' if receiver else 'USB / 有线或接收器'
        device = Device('device:' + identifier, brand_name, str(name)[:240], kind,
                        receiver=receiver, transport=transport, source='本机 USB / HID 枚举',
                        note='电量协议尚未适配，可识别设备；不会猜测电量。' if not backend else '正在查询设备状态…',
                        vid=vid,pid=pid,present=True,confidence='unknown',battery_support='supported' if backend else 'identify-only',
                        evidence=evidence+'；未据此确认无线链路', identity=identifier,
                        fingerprint=digest(f'{vid:04x}:{pid:04x}:{str(name).casefold()}'), serial_hash=serial_hash,
                        last_seen=time.time(),usb_keyboard=usb_keyboard)
        if usb_keyboard and not backend:
            device=replace(device,note='检测到 USB 键盘接口；若无明确型号证据，供电方式与电池情况待确认。')
        if vid==0x19f5 and pid==0x3247 and 'nuphy' in text and not backend:
            device=replace(device,note='已识别 NuPhy 2.4G 接收器；当前尚未找到可验证的电量协议，电量暂时未知。接收器接入不代表键盘一定在线。')
        if backend=='rog_omni_mini':
            device=replace(device,note='ROG OMNI 接收器：已适配单独配对的 Harpe Ace Mini；其他组合待验证。')
        reason=wired_evidence(profile,name,infos,backend,receiver)
        if reason:
            device=as_wired(replace(device,kind=(profile or {}).get('kind',kind)),reason)
            backend=''
        if auxiliary:
            device=replace(device,kind='auxiliary',connected=True,confidence='confirmed',battery_support='not-applicable',
                transport='USB 复合设备',evidence='同一物理 USB 设备的接口：'+'、'.join(companions),
                note='同一 USB 复合设备包含 cxair、串口与键鼠 HID 功能，疑似显示/控制模块。具体硬件需对应实物确认；归为辅助设备，默认不显示在外设电量列表。')
            backend=''
        result.append({'device': device.to_dict(), 'infos': [encode_info(i) for i in infos], 'backend': backend})
    return result
