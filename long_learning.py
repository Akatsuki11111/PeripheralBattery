"""Bounded local long observations; correlations stay explicitly experimental."""
import math
import time
import json
from settings import atomic_json,read_json,data_dir


def signature(s):
    return (s.get('vid'),s.get('pid'),s.get('interface'),s.get('usage_page'),s.get('usage'),
            s.get('backend'),json.dumps(s.get('channel'),sort_keys=True))


def analyze(before,charged,usage):
    result={'candidates':[],'valid_minutes':0,'note':'需要至少 1 小时有效观察、12 个样本和实际电量变化。'}
    if not before or not charged or not usage:return result
    try:
        all_samples=before+charged+usage
        packets=[bytes.fromhex(s['hex']) for s in all_samples]
        if len({signature(s) for s in all_samples})!=1 or len({len(p) for p in packets})!=1:raise ValueError()
        if not packets[0] or len(packets[0])>256:raise ValueError()
        times=[s['timestamp'] for s in usage]
        if any(not isinstance(t,(int,float)) or not math.isfinite(t) for t in times):raise ValueError()
        if any(t2<=t1 for t1,t2 in zip(times,times[1:])):raise ValueError()
    except (KeyError,TypeError,ValueError):
        return {**result,'note':'身份、报告结构或时间戳不一致，不能分析。'}
    segments=[];start=0
    for i in range(1,len(usage)):
        if times[i]-times[i-1]>180 or usage[i].get('segment_start'):
            segments.append(usage[start:i]);start=i
    segments.append(usage[start:]);usage=max(segments,key=lambda s:s[-1]['timestamp']-s[0]['timestamp'])
    times=[s['timestamp'] for s in usage];valid=times[-1]-times[0]
    result['valid_minutes']=round(valid/60,1)
    if len(usage)<12 or valid<3599:return result
    if any(s.get('charging') is True for s in usage):return {**result,'note':'使用阶段包含充电，需要重新采样。'}
    b=packets[:len(before)];a=packets[len(before):len(before)+len(charged)];u=[bytes.fromhex(s['hex']) for s in usage]
    for offset in range(1,len(packets[0])):  # byte zero is the report/command header
        bv=[p[offset] for p in b];av=[p[offset] for p in a];values=[p[offset] for p in u]
        if not all(0<=v<=100 for v in bv+av+values):continue
        if max(bv)-min(bv)>1 or max(av)-min(av)>1:continue
        drop=values[0]-values[-1]
        if not 1<=drop<=30 or any(v2>v1 for v1,v2 in zip(values,values[1:])):continue
        # Reject smooth sample counters and implausible step sizes. A slow
        # countdown can still fit; it is never called a confirmed battery.
        changes=[v1-v2 for v1,v2 in zip(values,values[1:]) if v1!=v2]
        if not changes or max(changes)>3 or len(changes)>len(values)*.5:continue
        level='中' if drop>=3 and len(changes)>=3 and all(s.get('charging') is False for s in usage) else '低'
        result['candidates'].append({'offset':offset,'current':values[-1],'drop':drop,'changes':len(changes),
            'confidence':level,'rule':'uint8_percent','reason':'同接口使用阶段非递增；仍可能是慢速计数器。'})
    result['note']='观察只能提高相关性；没有独立电量旁证时最高标为中，不能据此保证读数正确。'
    return result


def mapping_path():return data_dir()/'experimental-mappings.json'


def mappings():
    value=read_json(mapping_path(),{},100000)
    return value if isinstance(value,dict) else {}


def save_mapping(session,candidate):
    if session.get('state')!='completed' or session.get('before',[{}])[0].get('backend')!='feature-get':raise ValueError('只能确认已完成的未知 Feature 报告实验')
    analysis=analyze(session['before'],session['charged'],session['usage'])
    if candidate not in analysis['candidates']:raise ValueError('候选已变化或证据不足')
    import uuid
    evidence='observations/'+uuid.uuid4().hex+'.json';atomic_json(data_dir()/evidence,session)
    sample=session['usage'][-1];data=mappings()
    data[session['identity']]={'offset':candidate['offset'],'channel':sample.get('channel'),
        'signature':list(signature(sample)[:-1]),'length':sample['length'],'confidence':candidate['confidence'],
        'created_at':time.time(),'evidence_file':evidence}
    atomic_json(mapping_path(),data)


def decode_mapping(sample,mapping):
    raw=bytes.fromhex(sample['hex']);offset=mapping.get('offset')
    if (list(signature(sample)[:-1])!=mapping.get('signature') or sample.get('channel')!=mapping.get('channel')
        or len(raw)!=mapping.get('length') or type(offset) is not int or not 1<=offset<len(raw)
        or raw[offset]>100):raise ValueError('实验映射与当前报告不符，已停用本次读数')
    return raw[offset]
