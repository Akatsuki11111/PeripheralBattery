"""Descriptor-declared Feature GET only; never input reports or SET operations."""
import ctypes as C
from contextlib import contextmanager
from identity import digest


class FeatureReadError(ValueError):
    def __init__(self,code,message,details):
        super().__init__(message);self.code=code;self.details=details


class Caps(C.Structure):
    _fields_=[(n,C.c_uint16) for n in ('Usage','UsagePage','InputLength','OutputLength','FeatureLength')]+[('Reserved',C.c_uint16*17)]+[(n,C.c_uint16) for n in
        ('LinkNodes','InputButtons','InputValues','InputIndices','OutputButtons','OutputValues','OutputIndices','FeatureButtons','FeatureValues','FeatureIndices')]


@contextmanager
def opened(path):
    kernel=C.WinDLL('kernel32',use_last_error=True);hid=C.WinDLL('hid',use_last_error=True)
    kernel.CreateFileW.argtypes=[C.c_wchar_p,C.c_uint32,C.c_uint32,C.c_void_p,C.c_uint32,C.c_uint32,C.c_void_p];kernel.CreateFileW.restype=C.c_void_p
    kernel.CloseHandle.argtypes=[C.c_void_p];kernel.CloseHandle.restype=C.c_int
    hid.HidD_GetPreparsedData.argtypes=[C.c_void_p,C.POINTER(C.c_void_p)];hid.HidD_GetPreparsedData.restype=C.c_ubyte
    hid.HidD_FreePreparsedData.argtypes=[C.c_void_p];hid.HidD_FreePreparsedData.restype=C.c_ubyte
    hid.HidP_GetCaps.argtypes=[C.c_void_p,C.POINTER(Caps)];hid.HidP_GetCaps.restype=C.c_int32
    hid.HidD_GetFeature.argtypes=[C.c_void_p,C.c_void_p,C.c_uint32];hid.HidD_GetFeature.restype=C.c_ubyte
    handle=kernel.CreateFileW(path.decode() if isinstance(path,bytes) else path,0,3,None,3,0,None)
    if handle in (None,C.c_void_p(-1).value):raise OSError(f'无法打开所选接口，Windows 错误 {C.get_last_error()}')
    preparsed=C.c_void_p()
    try:
        if not hid.HidD_GetPreparsedData(handle,C.byref(preparsed)):raise OSError(f'无法取得报告描述信息，Windows 错误 {C.get_last_error()}')
        caps=Caps()
        if hid.HidP_GetCaps(preparsed,C.byref(caps))!=0x110000:raise OSError('报告描述信息无效')
        yield handle,hid,preparsed,caps
    finally:
        if preparsed.value:hid.HidD_FreePreparsedData(preparsed)
        kernel.CloseHandle(handle)


def channels_for(info,hid,preparsed,caps):
    if not (caps.UsagePage>=0xff00 or caps.UsagePage==0x85) or not 2<=caps.FeatureLength<=256:return []
    raw=[];ids=set()
    for name,count in (('HidP_GetValueCaps',caps.FeatureValues),('HidP_GetButtonCaps',caps.FeatureButtons)):
        if not count:continue
        if count>256:raise ValueError('Feature 描述数量超过限制')
        # Both SDK structures have a common header (ReportID at byte 2), and
        # exactly 72 bytes with four-byte alignment; no undocumented offsets.
        entries=((C.c_uint32*18)*count)();size=C.c_uint16(count);fn=getattr(hid,name)
        fn.argtypes=[C.c_int,C.c_void_p,C.POINTER(C.c_uint16),C.c_void_p];fn.restype=C.c_int32
        if fn(2,entries,C.byref(size),preparsed)!=0x110000 or size.value>count:raise OSError('读取 Feature 描述失败')
        for i in range(size.value):
            data=bytes(entries[i]);raw.append(data.hex());ids.add(data[2])
    signature=digest((caps.Usage,caps.UsagePage,caps.FeatureLength,raw))
    return [dict(interface=info.get('interface_number',-1),usage_page=caps.UsagePage,usage=caps.Usage,
                 report_id=rid,length=caps.FeatureLength,descriptor=signature,
                 collection=digest(info['path'])) for rid in sorted(ids)[:8]]


def summary(info,caps,channels):
    reason='declared' if channels else 'no_feature_report' if not caps.FeatureLength else 'feature_length_limit' if not 2<=caps.FeatureLength<=256 else 'no_declared_fields'
    return {'interface':info.get('interface_number',-1),'usage_page':int(caps.UsagePage),'usage':int(caps.Usage),
            'input_length':int(caps.InputLength),'output_length':int(caps.OutputLength),'feature_length':int(caps.FeatureLength),
            'feature_value_caps':int(caps.FeatureValues),'feature_button_caps':int(caps.FeatureButtons),
            'report_ids':[c['report_id'] for c in channels],'status':reason}


def inspect_features(infos):
    """Only inspect the descriptor; no Feature GET, input reads or writes."""
    results=[]
    for info in infos[:32]:
        base={k:info.get(k) for k in ('interface_number','usage_page','usage')}
        if not (info.get('usage_page',0)>=0xff00 or info.get('usage_page')==0x85):
            results.append({**base,'status':'not_vendor_or_battery_collection'});continue
        try:
            with opened(info['path']) as (_,hid,preparsed,caps):
                results.append(summary(info,caps,channels_for(info,hid,preparsed,caps)))
        except (OSError,ValueError) as error:results.append({**base,'status':'descriptor_unavailable','error':str(error)})
    return results


def get_feature(infos,expected=None,reject_blank=False):
    details=[]
    candidates=[i for i in infos if i.get('usage_page',0)>=0xff00 or i.get('usage_page')==0x85]
    for info in candidates[:8]:
        try:
            with opened(info['path']) as (handle,hid,preparsed,caps):
                channels=channels_for(info,hid,preparsed,caps)
                item=summary(info,caps,channels);details.append(item)
                if expected is not None:
                    channels=[c for c in channels if c==expected]
                    if not channels:item['status']='channel_changed'
                for channel in channels:
                    buf=(C.c_ubyte*channel['length'])();buf[0]=channel['report_id']
                    if not hid.HidD_GetFeature(handle,buf,len(buf)):
                        item.setdefault('attempts',[]).append({'report_id':channel['report_id'],'status':'feature_read_failed','windows_error':C.get_last_error()});continue
                    if buf[0]!=channel['report_id']:
                        item.setdefault('attempts',[]).append({'report_id':channel['report_id'],'status':'unexpected_report_id'});continue
                    body=bytes(buf)[1:]
                    if reject_blank and (all(value==0 for value in body) or all(value==255 for value in body)):
                        item.setdefault('attempts',[]).append({'report_id':channel['report_id'],'status':'uninitialized_report','length':len(buf)})
                        if expected is not None:
                            raise FeatureReadError('uninitialized_report','已锁定的采样通道返回全零/填充数据，未证实为当前设备状态。已停止本次采样；不会自动改换报告通道。',details)
                        continue
                    return bytes(buf),channel
        except FeatureReadError:raise
        except (OSError,ValueError) as error:details.append({'interface':info.get('interface_number',-1),'status':'descriptor_unavailable','error':str(error)})
    statuses={d['status'] for d in details}
    attempts=[a for d in details for a in d.get('attempts',[])]
    if not candidates:code='no_vendor_collection';message='没有找到可供此实验使用的厂商或电池集合；普通鼠标输入接口不提供这种采样。'
    elif attempts and all(item['status']=='uninitialized_report' for item in attempts):code='uninitialized_report';message='已尝试的 Feature 报告均只返回全零/填充数据，未证实是设备状态。可能需要专用查询初始化；已停止，延长观察不能补足缺失的状态通道。'
    elif attempts:code='feature_read_failed';message='系统没有返回可用的 Feature 报告。该设备可能需要专用电量查询，也可能存在接口访问问题，请导出诊断。'
    elif expected is not None and 'channel_changed' in statuses:code='channel_changed';message='原采样通道已改变或报告描述不符，请重新选择设备。'
    elif 'feature_length_limit' in statuses:code='feature_length_limit';message='设备的 Feature 报告长度超过当前实验支持范围，已停止采样。'
    elif 'descriptor_unavailable' in statuses:code='descriptor_unavailable';message='无法读取一个或多个接口的报告描述；请导出诊断检查系统错误码。'
    else:code='no_feature_report';message='已检查接口描述，没有找到可用于此实验的 Feature 报告。延长等待不能补足缺失的报告，需适配专用查询。'
    raise FeatureReadError(code,message,details)
