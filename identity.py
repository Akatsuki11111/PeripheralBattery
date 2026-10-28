"""Read Windows device metadata without sending commands to hardware."""
import ctypes
from ctypes import wintypes
import hashlib
import re
import uuid
from functools import lru_cache


def digest(value):
    return hashlib.sha256(str(value).encode('utf-8', errors='replace')).hexdigest()[:24]


class GUID(ctypes.Structure):
    _fields_ = [('data', ctypes.c_ubyte * 16)]


class DEVPROPKEY(ctypes.Structure):
    _fields_ = [('fmtid', GUID), ('pid', wintypes.DWORD)]


def property_key(guid, pid):
    return DEVPROPKEY(GUID.from_buffer_copy(uuid.UUID(guid).bytes_le), pid)


CONTAINER = property_key('8c7ed206-3f8a-4827-b3ab-ae9e1faefc6c', 2)
DEVICE_KEYS = {name: property_key('a45c254e-df1c-4efd-8020-67d146a850e0', index)
               for name, index in [('description', 2), ('manufacturer', 13), ('friendly', 14)]}
DEVICE_KEYS['bus_description']=property_key('540b947e-8b40-45bc-a8a2-6a0b894cbda2',4)


@lru_cache(maxsize=1)
def cfgmgr():
    api=ctypes.WinDLL('cfgmgr32')
    signatures={
        'CM_Locate_DevNodeW':[ctypes.POINTER(wintypes.DWORD),wintypes.LPWSTR,wintypes.ULONG],
        'CM_Get_DevNode_PropertyW':[wintypes.DWORD,ctypes.POINTER(DEVPROPKEY),ctypes.POINTER(wintypes.ULONG),ctypes.c_void_p,ctypes.POINTER(wintypes.ULONG),wintypes.ULONG],
        'CM_Get_Device_IDW':[wintypes.DWORD,wintypes.LPWSTR,wintypes.ULONG,wintypes.ULONG],
        'CM_Get_Parent':[ctypes.POINTER(wintypes.DWORD),wintypes.DWORD,wintypes.ULONG],
        'CM_Get_Child':[ctypes.POINTER(wintypes.DWORD),wintypes.DWORD,wintypes.ULONG],
        'CM_Get_Sibling':[ctypes.POINTER(wintypes.DWORD),wintypes.DWORD,wintypes.ULONG],
        'CM_Get_Device_ID_List_SizeW':[ctypes.POINTER(wintypes.ULONG),wintypes.LPCWSTR,wintypes.ULONG],
        'CM_Get_Device_ID_ListW':[wintypes.LPCWSTR,wintypes.LPWSTR,wintypes.ULONG,wintypes.ULONG],
    }
    for name,arguments in signatures.items():
        function=getattr(api,name);function.argtypes=arguments;function.restype=wintypes.ULONG
    return api


def instance_from_path(path):
    text = path.decode(errors='replace') if isinstance(path, bytes) else str(path)
    if text.upper().startswith(('USB\\','HID\\')):return text
    parts = text.split('#')
    if len(parts) < 3:
        return ''
    return parts[0].replace('\\\\?\\', '') + '\\' + parts[1] + '\\' + parts[2]


def metadata(path):
    result = {'container': '', 'physical': '', 'friendly': '', 'manufacturer': ''}
    try:
        api = cfgmgr()
        node = wintypes.DWORD()
        if api.CM_Locate_DevNodeW(ctypes.byref(node), instance_from_path(path), 0) != 0:
            return result
        kind, size = wintypes.ULONG(), wintypes.ULONG(2048)
        buffer = ctypes.create_string_buffer(2048)
        if api.CM_Get_DevNode_PropertyW(node, ctypes.byref(CONTAINER), ctypes.byref(kind), buffer,
                                       ctypes.byref(size), 0) == 0 and size.value == 16:
            value = str(uuid.UUID(bytes_le=buffer.raw[:16]))
            if value != str(uuid.UUID(int=0)):
                result['container'] = value
        for name, key in DEVICE_KEYS.items():
            size.value = 2048
            if api.CM_Get_DevNode_PropertyW(node, ctypes.byref(key), ctypes.byref(kind), buffer,
                                           ctypes.byref(size), 0) == 0:
                result[name] = buffer.raw[:size.value].decode('utf-16-le', errors='replace').rstrip('\0')
        # Composite HID collections all descend from the same non-MI USB device.
        current = node.value
        for _ in range(6):
            text = ctypes.create_unicode_buffer(1024)
            if api.CM_Get_Device_IDW(current, text, len(text), 0) == 0:
                value = text.value
                if value.upper().startswith('USB\\VID_') and '&MI_' not in value.upper():
                    result['physical'] = value
                    break
            parent = wintypes.DWORD()
            if api.CM_Get_Parent(ctypes.byref(parent), current, 0) != 0:
                break
            current = parent.value
    except (OSError, AttributeError, ValueError):
        pass
    return result


def raw_input_paths():
    """Include protected mouse/keyboard collections that hidapi cannot open."""
    class Entry(ctypes.Structure):
        _fields_ = [('handle', wintypes.HANDLE), ('kind', wintypes.DWORD)]
    result = {}
    try:
        api = ctypes.WinDLL('user32')
        api.GetRawInputDeviceList.argtypes = [ctypes.POINTER(Entry), ctypes.POINTER(wintypes.UINT), wintypes.UINT]
        api.GetRawInputDeviceInfoW.argtypes = [wintypes.HANDLE, wintypes.UINT, ctypes.c_void_p, ctypes.POINTER(wintypes.UINT)]
        count = wintypes.UINT()
        if api.GetRawInputDeviceList(None, ctypes.byref(count), ctypes.sizeof(Entry)) == 0xffffffff:
            return result
        entries = (Entry * min(count.value, 4096))()
        count.value = len(entries)
        found = api.GetRawInputDeviceList(entries, ctypes.byref(count), ctypes.sizeof(Entry))
        if found == 0xffffffff:
            return result
        for entry in entries[:found]:
            if entry.kind not in (0, 1):
                continue
            length = wintypes.UINT()
            api.GetRawInputDeviceInfoW(entry.handle, 0x20000007, None, ctypes.byref(length))
            if not 0 < length.value < 4096:
                continue
            text = ctypes.create_unicode_buffer(length.value + 1)
            if api.GetRawInputDeviceInfoW(entry.handle, 0x20000007, text, ctypes.byref(length)) != 0xffffffff:
                result[text.value.lower()] = 'mouse' if entry.kind == 0 else 'keyboard'
    except (OSError, AttributeError, ValueError):
        pass
    return result


def usb_audio_device_ids():
    """Cheap read-only topology signature; no device handles or properties."""
    result=set()
    try:
        api=cfgmgr()
        flags=0x00000002|0x00000100|0x10000040  # SERVICE | PRESENT | DONOTGENERATE
        for service in ('usbaudio','usbaudio2'):
            for _ in range(2):
                size=wintypes.ULONG()
                if api.CM_Get_Device_ID_List_SizeW(ctypes.byref(size),service,flags)!=0 or not 1<size.value<100000:break
                buffer=ctypes.create_unicode_buffer(size.value)
                code=api.CM_Get_Device_ID_ListW(service,buffer,size.value,flags)
                if code==0x1a:continue
                if code!=0:break
                for instance in ctypes.wstring_at(ctypes.addressof(buffer),size.value).split('\0')[:256]:
                    if instance.upper().startswith('USB\\'):result.add(instance)
                break
    except (OSError,AttributeError,ValueError):pass
    return frozenset(result)


def usb_audio_infos():
    """Include named USB headsets that expose audio but no HID collections."""
    result=[]
    for instance in sorted(usb_audio_device_ids()):
        match=re.match(r'USB\\VID_([0-9A-F]{4})&PID_([0-9A-F]{4})',instance,re.I)
        if not match:continue
        meta=metadata(instance)
        name=meta.get('bus_description') or meta.get('friendly') or meta.get('description','')
        if not any(word in name.casefold() for word in ('headset','headphone','arctis','blackshark','耳机')):continue
        result.append(dict(path=instance.encode(),vendor_id=int(match[1],16),product_id=int(match[2],16),
            product_string=name,manufacturer_string=meta.get('manufacturer',''),serial_number='',
            usage_page=0,usage=0,interface_number=-1,bus_type=1,audio_interface=True))
    return result


def reliable_serial(value):
    value = str(value or '').strip().casefold()
    return value if len(value) >= 6 and len(set(value)) > 1 and value not in ('123456', '123456789', 'undefined') else ''


def companion_names(physical_instance):
    """Read sibling USB interface descriptions, without opening any HID handle."""
    result=[]
    if not physical_instance:return result
    try:
        api=cfgmgr();node=wintypes.DWORD()
        if api.CM_Locate_DevNodeW(ctypes.byref(node),physical_instance,0)!=0:return result
        child=wintypes.DWORD()
        if api.CM_Get_Child(ctypes.byref(child),node,0)!=0:return result
        for _ in range(32):
            for key in (DEVICE_KEYS['friendly'],DEVICE_KEYS['description']):
                kind=wintypes.ULONG();size=wintypes.ULONG(2048);buffer=ctypes.create_string_buffer(2048)
                if api.CM_Get_DevNode_PropertyW(child,ctypes.byref(key),ctypes.byref(kind),buffer,ctypes.byref(size),0)==0:
                    name=buffer.raw[:size.value].decode('utf-16-le',errors='replace').rstrip('\0')
                    if name and name not in result:result.append(name)
            sibling=wintypes.DWORD()
            if api.CM_Get_Sibling(ctypes.byref(sibling),child,0)!=0:break
            child=sibling
    except (OSError,AttributeError,ValueError):pass
    return result


def physical_identity(infos, info_metadata):
    first = infos[0]
    prefix = f'{first["vendor_id"]:04x}:{first["product_id"]:04x}:'
    serial = next((reliable_serial(i.get('serial_number')) for i in infos if reliable_serial(i.get('serial_number'))), '')
    if serial:
        return digest(prefix + 'serial:' + serial), digest(serial)
    container = next((m.get('container') for m in info_metadata if m.get('container')), '')
    if container:
        return digest(prefix + 'container:' + container), ''
    parent = next((m.get('physical') for m in info_metadata if m.get('physical')), '')
    if parent:
        return digest(prefix + 'parent:' + parent.casefold()), ''
    path = first['path'].decode(errors='replace').casefold()
    return digest(prefix + re.sub(r'&mi_[0-9a-f]+|&col[0-9a-f]+', '', path)), ''
