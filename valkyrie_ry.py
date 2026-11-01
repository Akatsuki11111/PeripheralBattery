"""RongYuan receiver status/identity queries used by the official VK HUB.

Reference: https://vkhub.valkyrie.com.cn/js/index.a2394467.js
CommonRyDongle uses F7 status, F6/05 transient mouse routing, 8F identity,
and FC response retrieval. These commands do not write configuration or flash.
Shared receiver IDs never identify the mouse brand without the 8F response.
No keyboard/mouse Input reports are read. Call only in a killable worker.
"""
from dataclasses import dataclass
import time

RECEIVER_IDS={(0x3151,0x5045)}
MODEL_IDS={3090:('VALKYRIE','VK M5 Lite',0x374a,0xa318)}
SOURCE='https://vkhub.valkyrie.com.cn/js/index.a2394467.js'


@dataclass(frozen=True)
class Status:
    online:bool
    percent:int|None
    can_read:bool
    can_send:bool
    rf_boot:bool
    device_mask:int
    payload:bytes


def payload(frame):
    data=bytes(frame)
    if len(data)==65:
        if data[0]!=0:raise ValueError('RY Feature report ID does not match')
        data=data[1:]
    if len(data)!=64:raise ValueError('RY Feature report must contain 64 payload bytes')
    return data


def parse_status(frame):
    data=payload(frame)
    mask=data[6]
    if mask not in (0,1,2,3):raise ValueError('RY device mask is invalid')
    boot=data[8]==1
    online=bool(mask&2) and data[4]==0 and not boot
    level=data[2] if online else None
    if level is not None and not 0<=level<=100:raise ValueError('RY battery percentage is invalid')
    return Status(online,level,data[0]==1,data[5]==1,boot,mask,data)


def parse_identity(frame):
    data=payload(frame)
    if data[0]!=0x8f:raise ValueError('RY identity response does not match')
    model_id=int.from_bytes(data[1:5],'little')
    if model_id in (0,0xffffffff):raise ValueError('RY identity is unavailable')
    return model_id


def status_packet():
    return bytes([0,0xf7])+bytes(63)


def identity_packet():
    # Bit7 checksum complements the first seven payload bytes to 0xFF.
    data=bytearray(65);data[1]=0x8f;data[8]=0x70
    return bytes(data)


def validate_interface(info):
    if (info.get('vendor_id'),info.get('product_id')) not in RECEIVER_IDS:
        raise ValueError('RY receiver ID is not allowed')
    if not (info.get('interface_number')==2 and info.get('usage_page')==0xffff and info.get('usage')==2):
        raise ValueError('RY status collection does not match')
    from feature_reports import opened,channels_for
    with opened(info['path']) as (_,hid,preparsed,caps):
        channels=channels_for(info,hid,preparsed,caps)
        if caps.FeatureLength!=65 or caps.UsagePage!=0xffff or caps.Usage!=2 or not any(
                c['report_id']==0 and c['length']==65 for c in channels):
            raise ValueError('RY descriptor must declare report 0 with 65 bytes')


def _open(info,factory):
    validate_interface(info)
    if factory is None:
        import hid
        factory=hid.device
    device=factory()
    try:device.open_path(info['path'])
    except BaseException:
        device.close();raise
    return device


def _send(device,packet):
    count=device.send_feature_report(packet)
    if count!=len(packet):raise OSError('RY Feature status request was not completely sent')
    time.sleep(.02)


def _status(device):
    _send(device,status_packet())
    return parse_status(device.get_feature_report(0,65))


def query_status(info,device_factory=None):
    device=_open(info,device_factory)
    try:return _status(device)
    finally:device.close()


def _identity(device,deadline):
    # F6 changes only the current RF command target; it is not device settings.
    while True:
        status=_status(device)
        if not status.online:raise ValueError('RY mouse is asleep, off or in RF boot mode')
        if status.can_send:break
        if time.monotonic()>=deadline:raise TimeoutError('RY mouse did not become ready for identity query')
        time.sleep(.05)
    _send(device,bytes([0,0xf6,5])+bytes(62))
    _send(device,identity_packet())
    while True:
        status=_status(device)
        if not status.online:raise ValueError('RY mouse went offline during identity query')
        if status.can_read:break
        if time.monotonic()>=deadline:raise TimeoutError('RY mouse identity response did not become ready')
        time.sleep(.05)
    _send(device,bytes([0,0xfc])+bytes(63))
    return parse_identity(device.get_feature_report(0,65))


def query_receiver(info,device_factory=None,timeout=2.5):
    """Return a fresh status plus physical mouse model identity, never a guess.

    Charging remains unknown: official F7 exposes no verified charging flag.
    In USB mode official VK HUB seeds battery=100 without querying a battery;
    this module deliberately does not repeat that fabricated value.
    """
    device=_open(info,device_factory)
    try:
        status=_status(device)
        model_id=_identity(device,time.monotonic()+timeout) if status.online else None
        # Identity exchange takes several Feature transactions. Recheck the
        # radio link after it rather than returning the earlier battery sample.
        if model_id is not None:status=_status(device)
        model=MODEL_IDS.get(model_id)
        return {'status':status,'model_id':model_id,'model':model,'charging':None}
    finally:device.close()
