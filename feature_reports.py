"""Descriptor-declared Feature GET only; never input reports or SET operations."""
import ctypes as C
from contextlib import contextmanager
from identity import digest


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
    if handle in (None,C.c_void_p(-1).value):raise OSError('无法打开所选 Feature 接口')
    preparsed=C.c_void_p()
    try:
        if not hid.HidD_GetPreparsedData(handle,C.byref(preparsed)):raise OSError('无法取得报告描述信息')
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
            data=bytes(entries[i]);raw.append(data.hex());page=int.from_bytes(data[:2],'little')
            if page>=0xff00 or page==0x85:ids.add(data[2])
    signature=digest((caps.Usage,caps.UsagePage,caps.FeatureLength,raw))
    return [dict(interface=info.get('interface_number',-1),usage_page=caps.UsagePage,usage=caps.Usage,
                 report_id=rid,length=caps.FeatureLength,descriptor=signature,
                 collection=digest(info['path'])) for rid in sorted(ids)[:8]]


def get_feature(infos,expected=None):
    errors=[]
    candidates=[i for i in infos if i.get('usage_page',0)>=0xff00 or i.get('usage_page')==0x85]
    for info in candidates[:8]:
        try:
            with opened(info['path']) as (handle,hid,preparsed,caps):
                channels=channels_for(info,hid,preparsed,caps)
                if expected is not None:channels=[c for c in channels if c==expected]
                for channel in channels:
                    buf=(C.c_ubyte*channel['length'])();buf[0]=channel['report_id']
                    if not hid.HidD_GetFeature(handle,buf,len(buf)):continue
                    if buf[0]!=channel['report_id']:continue
                    return bytes(buf),channel
        except (OSError,ValueError) as error:errors.append(str(error))
    raise ValueError('所选设备没有可读取的描述符 Feature 报告，或驱动占用；没有发送厂商配置命令。'+(' '+errors[-1] if errors else ''))
