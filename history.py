"""Bounded local five-minute samples and conservative discharge estimates.

History is evidence, never a live battery cache. No current/temperature/capacity
telemetry is available, so voltage history cannot be called internal resistance
or battery health.
"""
from dataclasses import dataclass
import math
from pathlib import Path
from statistics import median
import time
from models import valid_percent

INTERVAL=300
RETENTION=86400
MAX_POINTS=288
MAX_DEVICES=200
MAX_GAP=900


@dataclass(frozen=True)
class Estimate:
    rate: float | None = None
    hours: float | None = None
    reason: str = '需至少 1 小时、3 个百分点的连续放电数据'
    points: int = 0

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
        self.series={};self.dirty=False;self.last_saved=0;self.last_observed={}
        raw=read_json(self.path,{},40_000_000);now=time.time()
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
        return {'at':float(at),'percent':percent,'charging':charging if percent is not None else None,
                'voltage_mv':voltage if percent is not None else None,'source':source,
                'break':row.get('break') is True}

    def samples(self,key,now=None):
        now=time.time() if now is None else now
        return [dict(p) for p in self.series.get(key,[]) if now-RETENTION<=p['at']<=now]

    def record(self,device,now=None):
        now=time.time() if now is None else now
        if device.power_mode=='wired' or device.kind=='auxiliary':return
        good=device.usable and 0<=now-device.observed_at<=MAX_GAP
        at=device.observed_at if good else now
        if good and at<=self.last_observed.get(device.key,0):return
        if good:self.last_observed[device.key]=at
        rows=self.samples(device.key,now)
        previous=rows[-1] if rows else None
        if not good and (not previous or previous['percent'] is None):return
        sample={'at':at,'percent':device.percent if good else None,'charging':device.charging if good else None,
                'voltage_mv':device.voltage_mv if good else None,'source':device.source[:160],'break':False}
        if previous:
            sample['break']=(previous['break'] if at//INTERVAL==previous['at']//INTERVAL else False) or (
                previous['percent'] is None or not good or at-previous['at']>MAX_GAP
                or sample['charging']!=previous['charging'] or sample['source']!=previous['source']
                or good and previous['percent'] is not None and device.percent>previous['percent']+2)
            if at<previous['at']:return  # A backwards wall-clock adjustment cannot rewrite history.
            if at//INTERVAL==previous['at']//INTERVAL:rows[-1]=sample
            else:rows.append(sample)
        else:rows.append(sample)
        self.series[device.key]=rows[-MAX_POINTS:]
        if len(self.series)>MAX_DEVICES:
            oldest=min(self.series,key=lambda key:self.series[key][-1]['at']);self.series.pop(oldest,None)
        self.dirty=True

    def estimate(self,device,now=None):
        if not device.usable:return Estimate(reason='设备当前没有有效在线读数')
        if device.charging is not False:return Estimate(reason='正在充电或充电状态未知，暂不预测')
        if device.approximate:return Estimate(reason='设备只提供近似电量档位，暂不预测')
        points=[];rows=self.samples(device.key,now)
        for p in reversed(rows):
            if p['percent'] is None or p['charging'] is not False or p['source']!=device.source:break
            if points and points[-1]['at']-p['at']>MAX_GAP:break
            points.append(p)
            if p['break']:break
        points.reverse()
        current=time.time() if now is None else now
        if points and current-points[-1]['at']>MAX_GAP:return Estimate(reason='最近历史已中断，需重新积累连续采样')
        if len(points)<6:return Estimate(points=len(points))
        span=(points[-1]['at']-points[0]['at'])/3600
        drop=points[0]['percent']-points[-1]['percent']
        if span<1 or drop<3:return Estimate(points=len(points))
        slopes=[(a['percent']-b['percent'])/((b['at']-a['at'])/3600)
            for i,a in enumerate(points) for b in points[i+1:] if b['at']-a['at']>=900]
        rate=median(slopes)
        if rate<=0 or sum(s>0 for s in slopes)/len(slopes)<0.7:
            return Estimate(reason='读数变化不稳定，继续采样后再估算',points=len(points))
        residuals=[p['percent']+rate*(p['at']-points[0]['at'])/3600 for p in points]
        center=median(residuals)
        if median(abs(v-center) for v in residuals)>2:
            return Estimate(reason='放电波动较大，继续采样后再估算',points=len(points))
        hours=device.percent/rate
        if hours>240:return Estimate(reason='放电速率过低，短期数据不足以外推续航',points=len(points))
        return Estimate(round(rate,3),round(hours,3),'按最近连续在线放电趋势估算；休眠、负载和设置变化会影响结果',len(points))

    def save(self,force=False):
        if not self.dirty or not force and time.monotonic()-self.last_saved<60:return
        from settings import atomic_json
        self.series={key:self.samples(key) for key in self.series if self.samples(key)}
        atomic_json(self.path,{'version':1,'interval_seconds':INTERVAL,'devices':self.series},compact=True)
        self.dirty=False;self.last_saved=time.monotonic()

    def forget(self,key):
        self.series.pop(key,None);self.last_observed.pop(key,None);self.dirty=True;self.save(True)
