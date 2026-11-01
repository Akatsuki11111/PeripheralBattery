"""Small signed-update verifier using Windows CNG, with no third-party runtime.

The application pins its release public key; transport hashes alone cannot
authenticate an executable served over HTTP. RSA PKCS#1 v1.5 / SHA-256 is
implemented by Windows, not by this module. No private key belongs in the app.

References: Microsoft BCryptVerifySignature, BCRYPT_RSAKEY_BLOB and
BCRYPT_PKCS1_PADDING_INFO documentation.
"""
import base64
import binascii
import ctypes as C
import hashlib
import json
import re
import struct
from functools import lru_cache

ALGORITHM='rsa-pkcs1-sha256'
MAX_PAYLOAD_BYTES=32768


def canonical_json(payload):
    """Stable UTF-8 encoding shared by publisher and client; reject float tricks."""
    if type(payload) is not dict or not payload:raise ValueError('更新签名内容必须为非空对象')
    remaining=[1024]
    def validate(value,depth=0):
        remaining[0]-=1
        if remaining[0]<0 or depth>8:raise ValueError('更新签名内容过于复杂')
        kind=type(value)
        if value is None or kind is bool:return
        if kind is int:
            if not -(2**63)<=value<2**63:raise ValueError('更新签名整数超出范围')
            return
        if kind is str:
            if len(value)>8192:raise ValueError('更新签名字符串过长')
            return
        if kind is list:
            for item in value:validate(item,depth+1)
            return
        if kind is dict:
            if any(type(key) is not str or len(key)>100 for key in value):raise ValueError('更新签名字段无效')
            for item in value.values():validate(item,depth+1)
            return
        raise ValueError('更新签名内容含不支持的数据类型')
    validate(payload)
    try:encoded=json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8')
    except (TypeError,ValueError,UnicodeError) as error:raise ValueError('更新签名内容编码无效') from error
    if len(encoded)>MAX_PAYLOAD_BYTES:raise ValueError('更新签名内容过大')
    return encoded


def _base64(value,maximum):
    if type(value) is not str or len(value)>maximum:raise ValueError('更新签名编码无效')
    try:decoded=base64.b64decode(value,validate=True)
    except (binascii.Error,ValueError) as error:raise ValueError('更新签名编码无效') from error
    if base64.b64encode(decoded).decode('ascii')!=value:raise ValueError('更新签名编码不规范')
    return decoded


def _key_blob(public_key):
    if type(public_key) is not dict or type(public_key.get('exponent')) is not int or public_key['exponent']!=65537:
        raise ValueError('更新发布公钥无效')
    if type(public_key.get('key_id')) is not str or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',public_key['key_id']):
        raise ValueError('更新发布公钥标识无效')
    modulus=_base64(public_key.get('modulus_b64'),344)
    if len(modulus)!=256 or not modulus[0]&0x80 or not modulus[-1]&1:raise ValueError('更新发布公钥必须为 RSA-2048')
    exponent=b'\x01\x00\x01'
    # BCRYPT_RSAKEY_BLOB header fields are little endian. The exponent and
    # modulus following it are unsigned big-endian byte strings per the SDK.
    return struct.pack('<6I',0x31415352,2048,len(exponent),len(modulus),0,0)+exponent+modulus


class _PaddingInfo(C.Structure):
    _fields_=[('algorithm',C.c_wchar_p)]


@lru_cache(maxsize=1)
def _cng():
    try:api=C.WinDLL('bcrypt.dll',winmode=0x800)
    except (AttributeError,OSError) as error:raise ValueError('Windows 更新验签组件不可用') from error
    signatures={
        'BCryptOpenAlgorithmProvider':[C.POINTER(C.c_void_p),C.c_wchar_p,C.c_wchar_p,C.c_uint32],
        'BCryptImportKeyPair':[C.c_void_p,C.c_void_p,C.c_wchar_p,C.POINTER(C.c_void_p),C.c_void_p,C.c_uint32,C.c_uint32],
        'BCryptVerifySignature':[C.c_void_p,C.c_void_p,C.c_void_p,C.c_uint32,C.c_void_p,C.c_uint32,C.c_uint32],
        'BCryptDestroyKey':[C.c_void_p],
        'BCryptCloseAlgorithmProvider':[C.c_void_p,C.c_uint32],
    }
    for name,args in signatures.items():
        function=getattr(api,name);function.argtypes=args;function.restype=C.c_int32
    return api


def verify_payload(payload,signature,public_key):
    """Return True only for a valid pinned-key signature; fail closed otherwise."""
    encoded=canonical_json(payload);blob=_key_blob(public_key)
    sig=_base64(signature,344)
    if len(sig)!=256:raise ValueError('更新签名长度无效')
    api=_cng();algorithm=C.c_void_p();key=C.c_void_p()
    try:
        if api.BCryptOpenAlgorithmProvider(C.byref(algorithm),'RSA',None,0)!=0:raise ValueError('无法启动更新验签')
        blob_buffer=C.create_string_buffer(blob)
        if api.BCryptImportKeyPair(algorithm,None,'RSAPUBLICBLOB',C.byref(key),blob_buffer,len(blob),0)!=0:
            raise ValueError('无法读取更新发布公钥')
        digest=hashlib.sha256(encoded).digest();digest_buffer=C.create_string_buffer(digest)
        sig_buffer=C.create_string_buffer(sig);padding=_PaddingInfo('SHA256')
        status=api.BCryptVerifySignature(key,C.byref(padding),digest_buffer,len(digest),sig_buffer,len(sig),2)
        if status!=0:raise ValueError('更新发布签名校验失败，未信任此版本')
        return True
    finally:
        if key.value:api.BCryptDestroyKey(key)
        if algorithm.value:api.BCryptCloseAlgorithmProvider(algorithm,0)


def verify_envelope(envelope,public_key):
    """Validate the algorithm/key selector before verifying signed payload bytes."""
    if type(envelope) is not dict or set(envelope)!={'algorithm','key_id','payload','signature'}:
        raise ValueError('更新签名封装无效')
    if type(public_key) is not dict:raise ValueError('更新发布公钥无效')
    if envelope['algorithm']!=ALGORITHM or envelope['key_id']!=public_key.get('key_id'):
        raise ValueError('更新签名算法或发布密钥不受信任')
    verify_payload(envelope['payload'],envelope['signature'],public_key)
    # The caller must still bind app_key/platform/channel/version/id/path/size to
    # the VersionHub response and enforce its fixed origin and upgrade ordering.
    return dict(envelope['payload'])
