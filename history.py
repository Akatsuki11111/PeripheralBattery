"""Bounded local five-minute samples and conservative discharge estimates.

History is evidence, never a live battery cache. No current/temperature/capacity
telemetry is available, so voltage history cannot be called internal resistance
or battery health.
"""
from bisect import bisect_left
from dataclasses import dataclass
import math
from pathlib import Path
import time
from models import valid_percent

INTERVAL=300
RETENTION=7*86400
MAX_POINTS=RETENTION//INTERVAL
MAX_DEVICES=200
MAX_GAP=900
MAX_USAGE_GAP=120
MAX_PROFILES=4


def usage_profile(device):
    return device.transport[:48] + ' / ' + device.source[:96]


def duration_text(seconds):
    if seconds < 3600:
        return f'{seconds/60:.0f} 分钟' if seconds >= 60 else f'{seconds:.0f} 秒'
    return f'{seconds/3600:.1f} 小时'


@dataclass(frozen=True)
class Estimate:
    rate: float | None = None
    hours: float | None = None
    reason: str = '同一连接需累计至少 1 小时有效放电，并有可重复的净下降'
    points: int = 0
    active_seconds: float = 0

    @property
    def rate_text(self):
        return f'约 {self.rate:.1f} 个百分点 / 小时' if self.rate is not None else '样本不足'

    @property
    def remaining_text(self):
        if self.hours is None:return '暂不可估算'
        if self.hours<1:return f'约 {max(1,round(self.hours*60))} 分钟'
        return f'约 {self.hours:.1f} 小时'


class HistoryStore:
    def __init__(self,path=None):
        from settings import data_dir,read_json
        self.path=Path(path) if path else data_dir()/'history.json'
        self.series={};self.dirty=False;self.last_saved=0;self.last_observed={};self.last_online={}
        raw=read_json(self.path,{},160_000_000);now=time.time()
        if isinstance(raw,dict) and raw.get('version')==1 and isinstance(raw.get('devices'),dict):
            for key,rows in list(raw['devices'].items())[:MAX_DEVICES]:
                if not isinstance(key,str) or len(key)>240 or not isinstance(rows,list):continue
                buckets={}
                for row in rows[-MAX_POINTS:]:
                    sample=self.validate(row,now)
                    if sample:buckets[int(sample['at']//INTERVAL)]=sample
                if buckets:self.series[key]=sorted(buckets.values(),key=lambda p:p['at'])[-MAX_POINTS:]

    @staticmethod
    def validate(row,now):
        if not isinstance(row,dict):return None
        at=row.get('at')
        if type(at) not in (int,float) or not math.isfinite(at) or not now-RETENTION<=at<=now:return None
        percent=valid_percent(row.get('percent'))
        charging=row.get('charging') if type(row.get('charging')) is bool else None
        voltage=row.get('voltage_mv');voltage=voltage if type(voltage) is int and 2000<=voltage<=5000 else None
        source=row.get('source','');source=source[:160] if isinstance(source,str) else ''
        sample = {'at':float(at),'percent':percent,'charging':charging if percent is not None else None,
                  'voltage_mv':voltage if percent is not None else None,'source':source,
                  'break':row.get('break') is True}
        if row.get('gap_after') is True:
            sample['gap_after'] = True
        usage = row.get('usage')
        if isinstance(usage, dict):
            checked = {}
            for profile, entry in list(usage.items())[:MAX_PROFILES]:
                if not isinstance(profile, str) or len(profile)>147 or not isinstance(entry,(list,tuple)) or len(entry)!=3:
                    continue
                seconds, drop, falls = entry
                if (type(seconds) in (int,float) and 0<seconds<=INTERVAL+MAX_USAGE_GAP
                        and type(drop) is int and -1000<=drop<=1000 and type(falls) is int and 0<=falls<=INTERVAL):
                    checked[profile] = (seconds, drop, falls)
            if checked:
                sample['usage'] = checked
        return sample

    def samples(self,key,now=None):
        now=time.time() if now is None else now
        return [dict(p,usage=p['usage'].copy()) if 'usage' in p else dict(p)
                for p in self.series.get(key,[]) if now-RETENTION<=p['at']<=now]

    def combined_samples(self,keys,now=None):
        if len(keys)==1:
            return self.samples(keys[0],now)
        buckets={}
        for key in keys:
            for row in self.samples(key,now):
                bucket=int(row['at']//INTERVAL)
                buckets.setdefault(bucket,[]).append((key,row))
        result=[];previous_key=None
        for entries in (buckets[i] for i in sorted(buckets)):
            key,row=max(entries,key=lambda item:(item[1]['percent'] is not None,item[1]['at']))
            usage=max((item[1].get('usage',{}) for item in entries),
                      key=lambda data:sum(entry[0] for entry in data.values()))
            if usage:
                row['usage']=usage
            if previous_key is not None and key!=previous_key:
                row['break']=True
            result.append(row)
            previous_key=key
        return result[-MAX_POINTS:]

    def record(self,device,now=None):
        now=time.time() if now is None else now
        key=device.key
        if device.power_mode=='wired' or device.kind=='auxiliary':
            self.last_online.pop(key,None)
            return
        good=device.usable and 0<=now-device.observed_at<=MAX_GAP
        at=device.observed_at if good else now
        rows=self.series.get(key,[])
        del rows[:bisect_left(rows,now-RETENTION,key=lambda sample:sample['at'])]
        previous=rows[-1] if rows else None
        if good and (at<=self.last_observed.get(key,0) or previous and at<previous['at']):
            return
        if not good and previous and at<previous['at']:
            self.last_online.pop(key,None)
            return
        same_bucket=bool(previous and at//INTERVAL==previous['at']//INTERVAL)
        usage=dict(previous.get('usage',{})) if same_bucket else {}
        if good:
            self.last_observed[key]=at
        prior=self.last_online.pop(key,None)
        if good and device.charging is False and not device.approximate:
            profile=usage_profile(device)
            self.last_online[key]=(at,device.percent,profile)
            if prior and prior[2]==profile:
                elapsed=at-prior[0]
                drop=prior[1]-device.percent
                if 0<elapsed<=MAX_USAGE_GAP and -2<=drop<=5 and (profile in usage or len(usage)<MAX_PROFILES):
                    seconds,delta,falls=usage.get(profile,(0,0,0))
                    usage[profile]=(seconds+elapsed,delta+drop,falls+int(drop>0))
        if not good and (not previous or previous['percent'] is None or previous.get('gap_after')):
            return
        if not good and same_bucket:
            previous['gap_after']=True
            self.dirty=True
            return
        sample={'at':at,'percent':device.percent if good else None,'charging':device.charging if good else None,
                'voltage_mv':device.voltage_mv if good else None,'source':device.source[:160],'break':False}
        if usage:
            sample['usage']=usage
        if previous:
            sample['break']=(same_bucket and previous['break']) or (
                previous['percent'] is None or previous.get('gap_after',False) or not good or at-previous['at']>MAX_GAP
                or sample['charging']!=previous['charging'] or sample['source']!=previous['source']
                or good and previous['percent'] is not None and device.percent>previous['percent']+2)
        if same_bucket:
            rows[-1]=sample
        else:
            rows.append(sample)
        if len(rows)>MAX_POINTS:
            del rows[:-MAX_POINTS]
        self.series[key]=rows
        if len(self.series)>MAX_DEVICES:
            oldest=min(self.series,key=lambda key:self.series[key][-1]['at'] if self.series[key] else 0)
            self.series.pop(oldest);self.last_online.pop(oldest,None);self.last_observed.pop(oldest,None)
        self.dirty=True

    def estimate(self,device,now=None,related=()):
        now=time.time() if now is None else now
        profile=usage_profile(device)
        seconds=total=drop=falls=points=0
        for sample in self.series.get(device.key,[]):
            if not now-RETENTION<=sample['at']<=now:
                continue
            usage=sample.get('usage',{})
            total+=sum(value[0] for value in usage.values())
            if profile in usage:
                elapsed,delta,decreases=usage[profile]
                seconds+=elapsed;drop+=delta;falls+=decreases;points+=1
        if related:
            total=sum(entry[0] for row in self.combined_samples((device.key,*related),now)
                      for entry in row.get('usage',{}).values())
        if not device.usable:
            return Estimate(reason='设备当前没有有效在线读数',active_seconds=total)
        if device.charging is not False:
            return Estimate(reason='正在充电或充电状态未知，暂不预测',active_seconds=total)
        if device.approximate:
            return Estimate(reason='设备只提供近似电量档位，暂不预测',active_seconds=total)
        if seconds<3600 or drop<3 or falls<2:
            return Estimate(points=points,active_seconds=total)
        rate=drop/(seconds/3600)
        return Estimate(round(rate,3),round(device.percent/rate,3),
                        f'按近 7 天同连接累计 {duration_text(seconds)}、净放电 {drop} 个百分点估算；实际时长随负载变化。',
                        points,total)

    def save(self,force=False):
        if not self.dirty or not force and time.monotonic()-self.last_saved<60:return
        from settings import atomic_json
        self.series={key:self.samples(key) for key in self.series if self.samples(key)}
        atomic_json(self.path,{'version':1,'interval_seconds':INTERVAL,'devices':self.series},compact=True)
        self.dirty=False;self.last_saved=time.monotonic()

    def end_session(self):
        self.last_online.clear()

    def forget(self,key):
        self.forget_many((key,))

    def forget_many(self,keys):
        for key in keys:
            self.series.pop(key,None);self.last_observed.pop(key,None);self.last_online.pop(key,None)
        self.dirty=True;self.save(True)
