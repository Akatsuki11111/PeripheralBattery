"""Optional deployment settings, protected per Windows user outside the EXE."""
import ctypes as C
import json
import re
from urllib.parse import urlsplit
from settings import data_dir


class Blob(C.Structure):
    _fields_=[('size',C.c_uint32),('data',C.POINTER(C.c_ubyte))]


def protect(raw,decrypt=False):
    api=C.WinDLL('crypt32.dll',winmode=0x800);kernel=C.WinDLL('kernel32.dll',winmode=0x800)
    buffer=C.create_string_buffer(raw);source=Blob(len(raw),C.cast(buffer,C.POINTER(C.c_ubyte)));target=Blob()
    function=api.CryptUnprotectData if decrypt else api.CryptProtectData
    function.argtypes=[C.POINTER(Blob),C.c_void_p,C.c_void_p,C.c_void_p,C.c_void_p,C.c_uint32,C.POINTER(Blob)]
    function.restype=C.c_int;kernel.LocalFree.argtypes=[C.c_void_p]
    if not function(C.byref(source),None,None,None,None,1,C.byref(target)):raise ValueError('无法读取本机更新配置' if decrypt else '无法保护更新配置')
    try:return C.string_at(target.data,target.size)
    finally:kernel.LocalFree(target.data)


def validate(value):
    if not isinstance(value,dict):raise ValueError('更新配置格式无效')
    origin=value.get('origin');key=value.get('app_key','peripheral-battery');secret=value.get('app_secret','')
    if not isinstance(origin,str) or len(origin)>2048:raise ValueError('更新连接配置无效')
    parsed=urlsplit(origin)
    if (parsed.scheme not in ('https','http') or not parsed.hostname or parsed.username or parsed.password or
            parsed.path not in ('','/') or parsed.query or parsed.fragment or any(c.isspace() for c in origin)):
        raise ValueError('更新连接配置无效')
    if not isinstance(key,str) or not re.fullmatch('[a-z0-9][a-z0-9-]{1,49}',key):raise ValueError('更新应用标识无效')
    if not isinstance(secret,str) or not 1<=len(secret)<=512:raise ValueError('缺少更新请求签名配置')
    return dict(origin=origin.rstrip('/'),app_key=key,app_secret=secret)


def save_config(value):
    value=validate(value);path=data_dir()/'update-connection.dpapi';path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix('.tmp');temporary.write_bytes(protect(json.dumps(value,separators=(',',':')).encode('utf-8')))
    temporary.replace(path)


def load_config():
    path=data_dir()/'update-connection.dpapi'
    try:
        if not path.exists():return None
        raw=path.read_bytes()
        if not 0<len(raw)<=16384:raise ValueError('本机更新配置无效')
        return validate(json.loads(protect(raw,True)))
    except (OSError,ValueError,TypeError):raise ValueError('本机更新配置不可用，请重新导入部署配置') from None
