"""Data-driven recognition. Brand recognition never grants an unknown protocol."""
from functools import lru_cache
import json
from pathlib import Path
import re


@lru_cache(maxsize=1)
def load_catalog():
    return json.loads(Path(__file__).with_name('catalog.json').read_text(encoding='utf-8'))


def brands():
    return load_catalog()['brands']


def brand_info(brand):
    needle = str(brand).casefold()
    return next((entry for entry in brands() if needle in (entry['id'].casefold(), entry['name'].casefold())), None)


def device_profile(vid, pid):
    return next((row for row in load_catalog()['devices'] if int(row['vid'],16) == vid and int(row['pid'],16) == pid), None)


def recognize(vid, pid, manufacturer='', name='', override=''):
    manual = brand_info(override) if override else None
    if manual:
        return manual, '手动指定'
    profile = device_profile(vid, pid)
    if profile:
        match = brand_info(profile['brand'])
        if match:
            return match, 'VID/PID 型号目录'
    text = (str(manufacturer) + ' ' + str(name)).casefold()
    # Prefer explicit long names to short overlapping OEM aliases.
    matches = [(len(alias), entry) for entry in brands() for alias in entry['aliases'] if alias.casefold() in text]
    if matches:
        return max(matches,key=lambda item:item[0])[1], '厂商 / 型号名称'
    by_vendor = next((entry for entry in brands() if f'{vid:04X}' in entry['vids']), None)
    if by_vendor:
        return by_vendor, '厂商 ID'
    return None, '通用 HID / 品牌待指定'


def kind_for(name, interfaces):
    text = str(name).casefold()
    if any(i.get('usage_page')==1 and i.get('usage') in (4,5,8) for i in interfaces):return 'gamepad'
    if any(word in text for word in ('gamepad','game controller','xinput','dualshock','dualsense','joy-con','手柄')):return 'gamepad'
    if any(word in text for word in ('headset','headphone','arctis','blackshark','耳机','gamebuds','maxwell')):
        return 'headset'
    if any(word in text for word in ('keyboard','blackwidow','deathstalker','键盘','made68','nuphy air','nuphy halo',
                                     'air75','air60','air96','halo75','halo65','halo96','vk99','vk 99','vk87','vk 87','vk75','vk 75','mag75')):
        return 'keyboard'
    if any(info.get('usage_page') == 1 and info.get('usage') == 2 for info in interfaces):
        return 'mouse'
    return 'keyboard' if any(info.get('usage_page') == 1 and info.get('usage') == 6 for info in interfaces) else 'mouse'


def backend_for(vid, pid, name=''):
    # Shared RY receiver: query its own mouse identity before assigning a brand.
    if (vid,pid)==(0x3151,0x5045):return 'valkyrie_ry'
    # G3 V2 shares MCHOSE's vendor collections but is known to use another
    # protocol, so the M7/K7 status request must not be sent to it.
    if (vid,pid)==(0x3837,0x4245):return ''
    profile = device_profile(vid,pid)
    if profile:
        return profile['backend']
    if vid == 0x046d:
        return 'logitech'
    # These families have an explicit provider-side model/collection whitelist.
    if vid == 0x1532:
        return 'razer'
    if vid == 0x1038:
        return 'steelseries'
    if vid in (0x5253,0x3837):
        return 'mchose'
    if vid == 0x1b1c:
        return 'corsair'
    return ''


# Exact cable/receiver identities whose two USB nodes can represent one device.
_CHARGING_ENDPOINTS = {
    (0x1038, 0x2230): (0x1038, 0x2232),  # Arctis Nova 5
    (0x1532, 0x00C0): (0x1532, 0x00C1),  # Viper V3 Pro
    (0x24AE, 0x46A7): (0x24AE, 0x14A7),  # Rapoo VT7 PRO V2
}


def _charging_pair(cable, receiver):
    if (cable.brand, cable.kind) != (receiver.brand, receiver.kind):
        return False
    if (cable.vid,cable.pid,receiver.vid,receiver.pid)==(0x373b,0x129e,0x373b,0x124f):
        return (receiver.protocol_model_id == 0x129e or
                receiver.protocol_model_id is None and receiver.connected is not True and not receiver.cached)
    return (bool(cable.serial_hash and cable.serial_hash == receiver.serial_hash) or
            _CHARGING_ENDPOINTS.get((cable.vid, cable.pid)) == (receiver.vid, receiver.pid))


def coalesce_charging_devices(devices, preferences):
    """Prefer a verified USB reading over an inactive duplicate receiver."""
    hidden = set(preferences.get('hidden', []))
    items = list(devices)
    present = [d for d in items if d.present and d.key not in hidden]
    receivers = [d for d in present if d.receiver]
    cables = [d for d in present if not d.receiver]
    drop = set()
    for cable in cables:
        if not cable.usable or cable.charging is not True and (cable.vid,cable.pid)!=(0x373b,0x129e):
            continue
        candidates = [r for r in receivers if _charging_pair(cable, r)]
        if len(candidates) != 1:
            continue
        receiver = candidates[0]
        if receiver.connected is True and not (receiver.usable and receiver.charging is True
                                               and receiver.percent == cable.percent):
            continue
        if sum(_charging_pair(d, receiver) for d in cables) == 1:
            drop.add(receiver.key)
    return [d for d in items if d.key not in drop]


def endpoint_type(device):
    if 'bluetooth' in device.transport.casefold():
        return 'bluetooth'
    return 'radio' if device.receiver else 'usb'


def physical_key(device, devices, preferences):
    explicit=preferences.get('device_links',{}).get(device.key)
    if explicit:
        return explicit
    if device.brand=='Unknown' or not device.serial_hash or ':paired:' in device.key:
        return device.key
    match=lambda other: (other.brand,other.kind,other.serial_hash)==(device.brand,device.kind,device.serial_hash)
    routes=[endpoint_type(other) for other in devices if match(other)]
    if len(set(routes)) != len(routes):
        return device.key
    return 'serial:'+device.brand+':'+device.kind+':'+device.serial_hash


def related_keys(device, devices, preferences):
    logical=physical_key(device,devices,preferences)
    keys=[logical,device.key]
    keys.extend(other.key for other in devices if physical_key(other,devices,preferences)==logical)
    keys.extend(key for key,group in preferences.get('device_links',{}).items() if group==logical)
    return tuple(dict.fromkeys(keys))


def link_candidates(device, devices, preferences):
    keys=set(related_keys(device,devices,preferences))
    routes={endpoint_type(d) for d in devices if d.key in keys}
    routes.add(endpoint_type(device))
    return [d for d in devices if d.key not in keys and d.brand==device.brand and d.kind==device.kind
            and d.brand!='Unknown' and ':paired:' not in d.key and endpoint_type(d) not in routes
            and (d.name.casefold()==device.name.casefold() or _charging_pair(device,d) or _charging_pair(d,device))
            and not any(endpoint_type(member) in routes for member in devices
                        if member.key in related_keys(d,devices,preferences))]


def device_mode(device, devices, preferences):
    modes=preferences.get('device_modes',{})
    keys=related_keys(device,devices,preferences)
    explicit=modes.get(keys[0]) or modes.get(device.key)
    if explicit:
        return explicit
    values={modes[k] for k in keys if k in modes}
    return next(iter(values)) if len(values)==1 else None


def visible_devices(devices, preferences):
    hidden = set(preferences.get('hidden',[]))
    show_offline = preferences.get('show_offline',False)
    devices=list(devices)
    visible=[d for d in coalesce_charging_devices(devices,preferences) if d.key not in hidden and
            d.present and
            (d.kind!='auxiliary' or preferences.get('show_auxiliary',False)) and
            (d.kind in ('auxiliary','gamepad') or d.power_mode in ('wired','battery') or d.battery_support=='supported' or d.receiver or d.usb_keyboard or d.usable or d.experimental or preferences.get('show_unreadable',False)) and
            (show_offline or not (d.receiver and (d.vid,d.pid) in ((0x1038,0x2232),(0x1038,0x2253))
                                  and d.connected is not True)) and
            (show_offline or d.connected is not False or d.kind in ('mouse','gamepad') and d.cached)]
    selected={}
    def priority(device):
        return (device.usable or device.fresh_grade,device.charging is True,
                device.connected is True,device.cached,device.observed_at)
    for device in visible:
        key=physical_key(device,devices,preferences)
        if key not in selected or priority(device)>priority(selected[key]):
            selected[key]=device
    return list(selected.values())
