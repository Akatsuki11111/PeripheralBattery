"""Immutable, validated device snapshots shared between worker and GUI."""
from dataclasses import dataclass, asdict, fields
import math
import time


@dataclass(frozen=True)
class Device:
    key: str
    brand: str
    name: str
    kind: str = 'mouse'
    percent: int | None = None
    charging: bool | None = None
    connected: bool | None = None
    receiver: bool = False
    transport: str = 'USB / 连接方式待确认'
    source: str = ''
    observed_at: float = 0
    note: str = ''
    vid: int = 0
    pid: int = 0
    firmware: str = ''
    last_percent: int | None = None
    present: bool = True
    confidence: str = 'confirmed'
    battery_support: str = 'identify-only'
    evidence: str = ''
    identity: str = ''
    fingerprint: str = ''
    serial_hash: str = ''
    monotonic_at: float = 0
    last_seen: float = 0
    approximate: str = ''
    power_mode: str = 'unknown'
    voltage_mv: int | None = None
    usb_keyboard: bool = False

    @property
    def type_name(self):
        return {'mouse':'鼠标','keyboard':'键盘','headset':'耳机','auxiliary':'辅助 USB 设备'}.get(self.kind,'外设')

    @property
    def reading_text(self):
        return '有线' if self.power_mode=='wired' else '辅助设备' if self.kind=='auxiliary' else f'{self.percent}%' if self.percent is not None else '—'

    @property
    def stale(self):
        age = time.monotonic() - self.monotonic_at if self.monotonic_at else time.time() - self.observed_at
        return not self.observed_at or age < -60 or age > 900

    @property
    def usable(self):
        return (self.power_mode!='wired' and self.kind!='auxiliary' and self.present and self.connected is True and self.confidence == 'confirmed'
                and not self.stale and valid_percent(self.percent) is not None)

    @property
    def status(self):
        if not self.present:
            return '未接入'
        if self.kind=='auxiliary':return '辅助设备已接入'
        if self.power_mode=='wired':return '有线连接' if self.connected is True else '有线 · 连接待确认' if self.connected is None else '已断开'
        if self.connected is False:
            return '休眠或已关闭' if self.receiver else '已断开'
        if self.percent is not None and self.stale:
            return '读数已过期'
        if self.connected is None:
            if self.usb_keyboard and self.power_mode=='unknown' and not self.receiver:
                return 'USB 已接入 · 供电待确认'
            return '已识别 · 电量未知' if self.battery_support == 'identify-only' else '连接待确认'
        if self.charging:
            return '正在充电'
        return '已连接' if self.percent is not None else '已连接 · 电量未知'

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict):
            raise ValueError('Invalid device record')
        allowed = {field.name for field in fields(cls)}
        data = {key: item for key, item in value.items() if key in allowed}
        for key in ('key', 'brand', 'name'):
            if not isinstance(data.get(key), str) or not data[key] or len(data[key]) > 240:
                raise ValueError('Invalid device identity')
        data['kind'] = data.get('kind') if data.get('kind') in ('mouse', 'keyboard', 'headset','auxiliary') else 'mouse'
        data['power_mode']=data.get('power_mode') if data.get('power_mode') in ('unknown','wired','battery') else 'unknown'
        data['usb_keyboard']=data.get('usb_keyboard') is True and data['kind']=='keyboard'
        if data['power_mode']=='wired' or data['kind']=='auxiliary':data.update(percent=None,last_percent=None,charging=None,voltage_mv=None)
        voltage=data.get('voltage_mv')
        data['voltage_mv']=voltage if type(voltage) is int and 2000<=voltage<=5000 else None
        if data.get('connected') is not True:data['voltage_mv']=None
        for key in ('percent', 'last_percent'):
            data[key] = valid_percent(data.get(key))
        for key in ('connected', 'charging'):
            if data.get(key) is not True and data.get(key) is not False:
                data[key] = None
        for key in ('note', 'source', 'evidence', 'firmware', 'approximate'):
            if key in data:
                data[key] = str(data[key])[:1000]
        for key in ('observed_at', 'monotonic_at', 'last_seen'):
            if key in data and (not isinstance(data[key], (int, float)) or not math.isfinite(data[key]) or data[key]<0):
                data[key] = 0
        if data.get('observed_at',0)>time.time()+86400:data['observed_at']=0
        for key in ('vid','pid'):
            if key in data and (not isinstance(data[key],int) or not 0<=data[key]<=65535):data[key]=0
        return cls(**data)


def lowest(devices):
    eligible = [d for d in devices if d.usable]
    return min(eligible, key=lambda d: (d.percent, d.key), default=None)


def valid_percent(value):
    if isinstance(value, bool):
        return None
    try:
        n = float(value)
        return int(n) if n.is_integer() and 0 <= n <= 100 else None
    except (TypeError, ValueError, OverflowError):
        return None
