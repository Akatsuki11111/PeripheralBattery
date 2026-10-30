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


def coalesce_charging_devices(devices, preferences):
    """Hide a confirmed duplicate endpoint without combining its battery data.

    Identical names alone do not identify a physical device. Allow the locally
    verified Nova 5 pair only when there is exactly one of each and the cable
    reports charging; an online receiver must agree with its battery status.
    Other devices require the same reliable hardware serial and agreement.
    """
    hidden=set(preferences.get('hidden',[]))
    items=list(devices)
    receivers=[d for d in items if d.present and d.receiver and d.key not in hidden]
    cables=[d for d in items if d.present and not d.receiver and d.key not in hidden and d.usable and d.charging is True]
    drop=set()
    for cable in cables:
        candidates=[]
        for receiver in receivers:
            if receiver.brand!=cable.brand or receiver.kind!=cable.kind:continue
            serial_match=bool(cable.serial_hash and cable.serial_hash==receiver.serial_hash)
            nova_pair=(cable.vid,cable.pid,receiver.vid,receiver.pid)==(0x1038,0x2230,0x1038,0x2232)
            if not (serial_match or nova_pair):continue
            if receiver.connected is not False and not (receiver.usable and receiver.charging is True and receiver.percent==cable.percent):continue
            candidates.append(receiver)
        if len(candidates)!=1:continue
        receiver=candidates[0]
        matching_cables=[d for d in cables if d.brand==cable.brand and d.kind==cable.kind and
                         ((d.serial_hash and d.serial_hash==receiver.serial_hash) or
                          (d.vid,d.pid,receiver.vid,receiver.pid)==(0x1038,0x2230,0x1038,0x2232))]
        if len(matching_cables)==1:drop.add(receiver.key)
    return [d for d in items if d.key not in drop]


def visible_devices(devices, preferences):
    hidden = set(preferences.get('hidden',[]))
    show_offline = preferences.get('show_offline',False)
    return [d for d in coalesce_charging_devices(devices,preferences) if d.key not in hidden and
            d.present and
            (d.kind!='auxiliary' or preferences.get('show_auxiliary',False)) and
            (d.kind in ('auxiliary','gamepad') or d.power_mode in ('wired','battery') or d.battery_support=='supported' or d.receiver or d.usb_keyboard or d.usable or d.experimental or preferences.get('show_unreadable',False)) and
            (show_offline or d.connected is not False or d.kind in ('mouse','gamepad') and d.cached)]
