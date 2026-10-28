"""Bounded JSON settings and immutable device reconciliation."""
from dataclasses import replace
import hashlib
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import re
import tempfile
from itertools import islice
import time
from models import Device

APP_NAME = 'PeripheralBattery'
VERSION = '2.3.1'
REFRESH_INTERVALS=(5,15,30,60)


def probe_timeout_ms(backend):
    # Some receivers need several seconds for their read-only status exchange.
    return {'corsair':13_000,'logitech':12_000,'razer':11_000,'lofree':9_000}.get(backend,6500)


def data_dir():
    override = os.environ.get('PB_DATA_DIR')
    # AppData writes made by an MSIX host can be private to that host. A normal
    # profile directory remains identical when Task Scheduler starts us at login.
    return Path(override) if override else Path.home() / '.peripheral-battery'


def migrate_legacy_data():
    if os.environ.get('PB_DATA_DIR'):return
    import shutil
    destination=data_dir();destination.mkdir(parents=True,exist_ok=True)
    legacy=Path(os.environ.get('LOCALAPPDATA',Path.home()/'AppData/Local'))/APP_NAME
    for name in ('settings.json','devices.json'):
        target=destination/name
        if not target.exists() and (legacy/name).is_file():
            shutil.copy2(legacy/name,target)


def atomic_json(path, value,compact=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=None if compact else 2,separators=(',',':') if compact else None)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_json(path, default=None, limit=1024 * 1024):
    try:
        path = Path(path)
        if path.stat().st_size > limit:
            return default
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError, TypeError):
        return default


def configure_logging():
    folder = data_dir()
    folder.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger('peripheral_battery')
    if not logger.handlers:
        handler = RotatingFileHandler(folder / 'application.log', maxBytes=500_000, backupCount=2, encoding='utf-8')
        handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger


def cleanup_workers():
    root=data_dir()/'workers'
    if not root.is_dir():return
    for path in islice(root.iterdir(),1000):
        try:
            if re.fullmatch(r'[a-f0-9]{32}\.(?:request|result|started)\.json',path.name) and time.time()-path.stat().st_mtime>86400:
                path.unlink(missing_ok=True)
        except OSError:pass


def redact(text):
    text = str(text).replace(str(Path.home()), '%USERPROFILE%')
    return re.sub(r'\\\\\?\\[^\s\n]+', '<HID接口>', text)[:1500]


class Settings:
    DEFAULTS = {'show_offline': False, 'show_unreadable':False, 'show_auxiliary':False, 'low_notifications': True, 'low_threshold': 20,
                'hidden': [], 'brand_overrides': {}, 'device_modes':{},'refresh_seconds':15,'autostart_requested': False,'pinned_key':''}

    def __init__(self, path=None):
        self.path = Path(path) if path else data_dir() / 'settings.json'
        loaded = read_json(self.path, {}, 100_000)
        self.value = {key: value.copy() if isinstance(value, (dict, list)) else value for key, value in self.DEFAULTS.items()}
        if isinstance(loaded, dict):
            for key, default in self.DEFAULTS.items():
                if type(loaded.get(key)) is type(default):
                    self.value[key] = loaded[key]
        self.value['low_threshold'] = min(50, max(1, self.value['low_threshold']))
        self.value['hidden'] = [str(key)[:240] for key in self.value['hidden'][:200]]
        self.value['brand_overrides'] = {str(k)[:120]: str(v)[:80] for k, v in list(self.value['brand_overrides'].items())[:200]}
        self.value['device_modes']={str(k)[:240]:v for k,v in list(self.value['device_modes'].items())[:200] if v in ('wired','battery')}
        if type(self.value['refresh_seconds']) is not int or self.value['refresh_seconds'] not in REFRESH_INTERVALS:self.value['refresh_seconds']=15

    def get(self, key, default=None):
        return self.value.get(key, default)

    def set(self, key, value):
        if key not in self.DEFAULTS:
            raise KeyError(key)
        if key=='refresh_seconds' and (type(value) is not int or value not in REFRESH_INTERVALS):raise ValueError('刷新间隔只能为 5、15、30、60 秒')
        self.value[key] = value
        atomic_json(self.path, self.value)


class DeviceStore:
    RETENTION = 24 * 3600

    def __init__(self, path=None):
        self.path = Path(path) if path else data_dir() / 'devices.json'
        from history import HistoryStore
        self.history=HistoryStore(self.path.with_name('history.json'))
        saved = read_json(self.path, [], 300_000)
        self.devices = {}
        if isinstance(saved, list):
            for item in saved[:200]:
                try:
                    device = Device.from_dict(item)
                    if time.time() - device.last_seen < self.RETENTION:
                        if not device.last_observed_at:
                            if device.usable:
                                device=replace(device,last_percent=device.percent,last_observed_at=device.observed_at)
                            else:
                                valid=[p for p in self.history.samples(device.key) if p['percent'] is not None]
                                if valid and valid[-1]['percent']==device.last_percent:
                                    device=replace(device,last_observed_at=valid[-1]['at'])
                        device = replace(device, present=False, percent=None, connected=False, voltage_mv=None,monotonic_at=0)
                        self.devices[device.key] = device
                except (ValueError, TypeError):
                    continue

    def reconcile(self, incoming):
        """Keep paired children in place of their parent receiver on inventory refresh.

        apply_readings updates those same stable child keys when a shared receiver
        returns one ambiguous or several slot-specific responses.
        """
        now = time.time()
        old = self.devices
        incoming = list(incoming)
        new_keys = {device.key for device in incoming}
        counts = {}
        for device in incoming:
            counts[device.fingerprint] = counts.get(device.fingerprint, 0) + 1
        result = {}
        migrated = set()
        for device in incoming:
            children=[d for d in old.values() if d.identity==device.identity and ':paired:' in d.key]
            if children:
                for child in children:
                    fresh=child.usable and now-child.observed_at<90
                    result[child.key]=replace(child,present=True,last_seen=now,brand=device.brand,
                        connected=child.connected if fresh else None,percent=child.percent if fresh else None)
                continue
            previous = old.get(device.key)
            if previous is None and device.fingerprint and counts[device.fingerprint] == 1:
                candidates = [candidate for key, candidate in old.items()
                              if key not in new_keys and key not in migrated and candidate.fingerprint == device.fingerprint
                              and not (candidate.serial_hash and device.serial_hash and candidate.serial_hash != device.serial_hash)]
                if len(candidates) == 1:
                    previous = candidates[0]
                    migrated.add(previous.key)
                    device = replace(device, key=previous.key)
            if previous:
                last = device.last_percent if device.last_percent is not None else previous.last_percent
                device = replace(device, last_percent=device.percent if device.percent is not None else last,
                                 last_observed_at=previous.last_observed_at)
                if (device.percent is None and device.connected is None and previous.present and
                        (previous.usable or previous.experimental) and time.time()-previous.observed_at<90):
                    device=replace(device,percent=previous.percent,connected=previous.connected,charging=previous.charging,
                                   confidence=previous.confidence,observed_at=previous.observed_at,monotonic_at=previous.monotonic_at,
                                   source=previous.source,voltage_mv=previous.voltage_mv,note='正在刷新，暂显示最近一次有效应答。')
            if device.usable:device=replace(device,last_percent=device.percent,last_observed_at=device.observed_at)
            result[device.key] = replace(device, last_seen=now)
        for key, previous in old.items():
            if key not in result and key not in migrated and now - previous.last_seen < self.RETENTION:
                result[key] = replace(previous, present=False, connected=False, percent=None,
                                      charging=None,voltage_mv=None,monotonic_at=0, note='设备已移除；可在设备管理中忘记。')
                self.history.record(result[key])
        self.devices = dict(sorted(result.items(), key=lambda item: item[1].last_seen, reverse=True)[:200])
        return self.snapshot()

    def apply_readings(self, group_identity, readings):
        """Reconcile readings with the paired-child contract described above."""
        existing = [d for d in self.devices.values() if d.identity == group_identity and d.present]
        if not readings or not existing:
            return self.snapshot()
        base = existing[0]
        previous={d.key:d for d in existing}
        if len(readings)==1 and not readings[0].get('key') and any(':paired:' in d.key for d in existing):
            for device in existing:
                self.devices[device.key]=self._with_last(Device.from_dict({**device.to_dict(),**readings[0],'key':device.key}),device)
                self.history.record(self.devices[device.key])
            return self.snapshot()
        for device in existing:
            self.devices.pop(device.key, None)
        for index, reading in enumerate(readings):
            key = base.key if len(readings) == 1 else base.key.split(':paired:')[0] + ':paired:' + hashlib.sha256(str(reading.get('key', index)).encode()).hexdigest()[:10]
            current = Device.from_dict({**previous.get(key,base).to_dict(), **reading, 'key': key, 'identity': group_identity,
                                       'present': True, 'last_seen': time.time()})
            self.devices[key] = self._with_last(current,previous.get(key,base))
            self.history.record(current)
        return self.snapshot()

    @staticmethod
    def _with_last(current,previous):
        if current.usable:
            return replace(current,last_percent=current.percent,last_observed_at=current.observed_at)
        return replace(current,last_percent=previous.last_percent,last_observed_at=previous.last_observed_at,
                       charging=None if current.connected is not True else current.charging)

    def snapshot(self):
        return sorted(self.devices.values(), key=lambda d: (not d.present, d.brand, d.name, d.key))

    def save(self):
        atomic_json(self.path, [{**d.to_dict(), 'monotonic_at': 0} for d in self.snapshot()])
        self.history.save()

    def forget(self, key):
        self.devices.pop(key, None)
        self.history.forget(key)
        self.save()
