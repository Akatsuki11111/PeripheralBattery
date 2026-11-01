"""Immutable, validated device snapshots shared between worker and GUI."""
from dataclasses import dataclass, asdict, fields
import math
import time
import datetime as dt


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
    last_observed_at: float = 0
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
    battery_grade: str = ''
    last_battery_grade: str = ''
    battery_cache: bool = True
    protocol_model_id: int | None = None

    @property
    def type_name(self):
        return {'mouse':'鼠标','keyboard':'键盘','headset':'耳机','gamepad':'手柄','auxiliary':'辅助 USB 设备'}.get(self.kind,'外设')

    @property
    def reading_text(self):
        return ('有线' if self.power_mode=='wired' else '辅助设备' if self.kind=='auxiliary'
                else ('约' if self.approximate else '')+f'{self.percent}%' if self.usable
                else f'{self.percent}%?' if self.experimental else self.battery_grade if self.fresh_grade
                else (('约' if self.approximate else '')+f'{self.last_percent}%' if self.last_percent is not None else self.last_battery_grade) if self.cached else '—')

    @property
    def fresh_grade(self):
        return (self.power_mode!='wired' and self.present and self.connected is True and self.confidence=='confirmed'
                and not self.stale and self.battery_grade in ('耗尽','低','中','高','满'))

    @property
    def display_grade(self):
        return self.battery_grade if self.fresh_grade else self.last_battery_grade if self.cached and self.last_percent is None else ''

    @property
    def last_read_time(self):
        if not self.last_observed_at:return '时间未知'
        stamp=dt.datetime.fromtimestamp(self.last_observed_at)
        return stamp.strftime('%H:%M:%S' if stamp.date()==dt.datetime.now().date() else '%m-%d %H:%M')

    @property
    def experimental(self):
        return (self.present and self.connected is not False and self.power_mode!='wired' and self.confidence=='experimental'
                and not self.stale and valid_percent(self.percent) is not None)

    @property
    def cached(self):
        return (self.battery_cache and self.present and not self.usable and not self.fresh_grade and self.power_mode!='wired' and self.kind!='auxiliary'
                and (valid_percent(self.last_percent) is not None or self.last_battery_grade in ('耗尽','低','中','高','满')) and self.last_observed_at>0
                and 0<=time.time()-self.last_observed_at<86400)

    @property
    def display_percent(self):
        return self.percent if self.usable or self.experimental else self.last_percent if self.cached else None

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
        if self.experimental:return '实验推测 · 待核实' if self.connected is True else '实验推测 · 远端未确认'
        if self.connected is False:
            return ('休眠 / 关闭 · 上次 '+self.last_read_time if self.cached else '休眠或已关闭') if self.receiver else '已断开 · 上次 '+self.last_read_time if self.cached else '已断开'
        if (self.percent is not None or self.battery_grade) and self.stale:
            return '读数已过期'
        if self.connected is None:
            if self.cached:return '连接待确认 · 上次 '+self.last_read_time
            if self.kind=='gamepad':return '已接入 · 电量待适配'
            if self.usb_keyboard and self.power_mode=='unknown' and not self.receiver:
                return 'USB 已接入 · 供电待确认'
            return '已识别 · 电量未知' if self.battery_support == 'identify-only' else '连接待确认'
        if self.charging:
            return '正在充电'
        if self.fresh_grade:return '已连接 · 分档电量'
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
        data['kind'] = data.get('kind') if data.get('kind') in ('mouse', 'keyboard', 'headset','gamepad','auxiliary') else 'mouse'
        data['battery_grade']=data.get('battery_grade') if data.get('battery_grade') in ('耗尽','低','中','高','满') and data.get('connected') is True else ''
        data['last_battery_grade']=data.get('last_battery_grade') if data.get('last_battery_grade') in ('耗尽','低','中','高','满') else ''
        data['battery_cache']=data.get('battery_cache') is not False
        model_id=data.get('protocol_model_id')
        data['protocol_model_id']=model_id if type(model_id) is int and 0<model_id<0xffffffff else None
        data['power_mode']=data.get('power_mode') if data.get('power_mode') in ('unknown','wired','battery') else 'unknown'
        data['usb_keyboard']=data.get('usb_keyboard') is True and data['kind']=='keyboard'
        if data['power_mode']=='wired' or data['kind']=='auxiliary':data.update(percent=None,last_percent=None,charging=None,voltage_mv=None,battery_grade='',last_battery_grade='')
        if not data['battery_cache']:data.update(last_percent=None,last_battery_grade='',last_observed_at=0)
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
        for key in ('observed_at', 'last_observed_at', 'monotonic_at', 'last_seen'):
            if key in data and (not isinstance(data[key], (int, float)) or not math.isfinite(data[key]) or data[key]<0):
                data[key] = 0
        if data.get('observed_at',0)>time.time()+86400:data['observed_at']=0
        if data.get('last_observed_at',0)>time.time()+60:data['last_observed_at']=0
        for key in ('vid','pid'):
            if key in data and (not isinstance(data[key],int) or not 0<=data[key]<=65535):data[key]=0
        return cls(**data)


def lowest(devices):
    eligible = [d for d in devices if d.usable and not d.approximate]
    return min(eligible, key=lambda d: (d.percent, d.key), default=None)


def valid_percent(value):
    if isinstance(value, bool):
        return None
    try:
        n = float(value)
        return int(n) if n.is_integer() and 0 <= n <= 100 else None
    except (TypeError, ValueError, OverflowError):
        return None
